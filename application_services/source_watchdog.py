"""Bounded source incidents; no download decisions or token-bearing references."""
import uuid

from providers.catalog import PROVIDER_CATALOG


class SourceWatchdog:
    def __init__(self, owner):
        self.owner = owner

    def result(self, key, *, kind="provider", failed=False, recovered=False, rollback=False):
        """Only completed, meaningful probes count; partial probes never recover incidents."""
        owner = self.owner
        store = owner.hosters.store if kind == "hoster" else owner.store
        with owner.lock:
            old = store.entry(key, ("watchdog",)).get("watchdog", {})
            state = dict(old)
            now = owner.clock()
            if recovered:
                state.update(failures=0, first_failure_at=0, phase="healthy", incident=None)
            elif failed or rollback:
                failures = old.get("failures", 0) + 1
                state.update(failures=failures, first_failure_at=old.get("first_failure_at") or now,
                             phase="retrying")
                if failures >= 2 or rollback:
                    incident = old.get("incident")
                    if not incident:
                        incident = {"id": uuid.uuid4().hex,
                                    "opened_at": now, "read_by": []}
                    state.update(phase="attention", incident=incident)
            else:
                return
            if state == old:
                return
            # Incidents survive restart even when optional push notices are disabled.
            store.update(key, deferred=True, watchdog=state)
            if bool(state.get("incident")) != bool(old.get("incident")) and owner.store.config()["notify_changes"]:
                owner.notify({"provider": key, "source_kind": kind, "diagnosis": state["phase"],
                              "message_code": "source_attention" if state.get("incident") else "source_recovered"})

    def retry_delay(self, key, kind="provider"):
        store = self.owner.hosters.store if kind == "hoster" else self.owner.store
        state = store.entry(key, ("watchdog",)).get("watchdog", {})
        count = state.get("failures", 0)
        return (300 if count == 1 else 900 if count == 2 else 3600) if count else None

    def incidents(self, user_id):
        owner = self.owner
        enabled = set(owner.enabled())
        with owner.lock, owner.hosters.lock:
            sources = [("provider", key, owner.store) for key in enabled if key in PROVIDER_CATALOG]
            sources += [("hoster", key, owner.hosters.store) for key in owner.hosters.inventory
                        if enabled.intersection(owner.hosters.store.entry(key, ("providers",)).get("providers", []))]
            rows = []
            for kind, key, store in sources:
                incident = store.entry(key, ("watchdog",)).get("watchdog", {}).get("incident")
                if incident:
                    rows.append({"id": incident["id"], "kind": kind, "key": key,
                                 "label": PROVIDER_CATALOG[key].label if kind == "provider" else key,
                                 "opened_at": incident["opened_at"], "read": str(user_id) in incident.get("read_by", []),
                                 "message": "Wiederholte Quellenprüfung fehlgeschlagen. Keine dauerhaft bestätigte automatische Lösung. Details unter Quellen & Verfügbarkeit."})
            return sorted(rows, key=lambda row: row["opened_at"], reverse=True)

    def acknowledge(self, incident_id, user_id):
        owner = self.owner
        with owner.lock:
            row = next((row for row in self.incidents(user_id) if row["id"] == incident_id), None)
            if not row:
                raise KeyError(incident_id)
            store = owner.hosters.store if row["kind"] == "hoster" else owner.store
            state = store.entry(row["key"], ("watchdog",))["watchdog"]
            readers = state["incident"].get("read_by", [])
            state["incident"]["read_by"] = [*readers, str(user_id)][-64:] if str(user_id) not in readers else readers
            store.update(row["key"], watchdog=state)
