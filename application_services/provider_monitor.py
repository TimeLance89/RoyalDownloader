"""Staggered Sentinel scheduling and conservative existing health integration."""
from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from application_services.provider_probe import ProviderProbe, diagnose, identity, reference, payload, title_key
from application_services.provider_repair import ProviderRepair
from media.provider_monitor_store import ProviderMonitorStore
from providers.catalog import PROVIDER_CATALOG, provider_content_languages, normalize_content_language
from providers.probe_contracts import contract
from providers.models import parse_episode_slug
from application_services.source_service_health import source_service_health
from core.source_urls import valid_source_link


class ProviderMonitor:
    def __init__(self, path, health, enabled, *, hoster_intel=None, probe=None, notify=None, priorities=None, languages=None, clock=time.time):
        self.store = ProviderMonitorStore(path, clock)
        self.health, self.enabled, self.hoster_intel = health, enabled, hoster_intel
        self.probe = probe or ProviderProbe()
        self.repairs = ProviderRepair(self.store, self.probe)
        self.clock, self.notify = clock, notify or (lambda _event: None)
        self.priorities = priorities or (lambda _media: [])
        self.has_priorities = priorities is not None
        self.languages = languages
        self.lock = threading.RLock()
        self.active = set()
        self.last_manual = {}
        self.last_canary_observation = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="provider-sentinel")
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.stopped = False
        self.generation = 0
        self.last_service_notice = None
        self.notice_lock = threading.Lock()
        from application_services.hoster_monitor import HosterMonitor
        self.hosters = HosterMonitor(self)
        if hoster_intel is not None:
            hoster_intel.health_penalty = self.hosters.penalty

    def _notify(self, key, diagnosis, kind="provider"):
        if not self.store.config()["notify_changes"]:
            return
        service = self.diagnostics()["service"]
        signature = tuple((path["media_type"], path["language"], path["state"]) for path in service["paths"])
        with self.notice_lock:
            previous = self.last_service_notice
            self.last_service_notice = (service["user_impact"], signature)
            important = service["action_required"] or service["user_impact"] == "reduced_redundancy"
            recovered = previous and previous[0] in {"blocking", "reduced_redundancy"} and service["service_health"] == "healthy"
            changed = previous != self.last_service_notice
        if (important or recovered) and changed:
            self.notify({"provider": key, "source_kind": kind, "diagnosis": diagnosis,
                         "service_health": service["service_health"], "action_required": service["action_required"],
                         "message_code": "source_recovered" if recovered else "source_unavailable" if service["action_required"] else "source_redundancy_reduced"})

    def profile(self, provider):
        return self.repairs.profile(provider)

    def allowed(self, provider):
        return self.health.request_allowed(provider)

    def _schedule(self, provider, delay=None):
        config = self.store.config()
        jitter = int(hashlib.sha256(provider.encode()).hexdigest()[:6], 16) % 900
        if delay is None and not self.store.entry(provider).get("last_check_at"):
            seconds = 30 + jitter % 30
        else:
            seconds = config["interval_hours"] * 3600 + jitter if delay is None else delay + jitter
        self.store.update(provider, next_check_at=self.clock() + seconds)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stopped = False
            self.stop_event.clear()
            for provider in self.enabled():
                if not self.store.entry(provider).get("last_check_at"):
                    self._schedule(provider)
            self.thread = threading.Thread(target=self._loop, name="provider-sentinel-scheduler", daemon=True)
            self.thread.start()

    def stop(self):
        self.stopped = True
        self.generation += 1
        self.stop_event.set()
        self.wake.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        # Running transport calls retain bounded timeouts; no restart creates another pool.

    def configure(self, values):
        config = self.store.configure(values)
        for provider in self.enabled():
            self._schedule(provider)
        for hoster in list(self.hosters.inventory):
            self.hosters.schedule(hoster)
        self.wake.set()
        return config

    def _loop(self):
        while not self.stop_event.is_set():
            if self.store.config()["enabled"] or any(self.store.entry(p).get("requested_intensity") for p in self.enabled()):
                for provider in self.enabled():
                    entry = self.store.entry(provider)
                    if not self.store.config()["enabled"] and not entry.get("requested_intensity"):
                        continue
                    if not entry.get("next_check_at"):
                        self._schedule(provider, 300)
                    elif entry["next_check_at"] <= self.clock():
                        if self.request(provider, entry.get("requested_intensity"), manual=False):
                            self.store.update(provider, requested_intensity=None)
            for hoster in list(self.hosters.inventory):
                entry = self.hosters.store.entry(hoster)
                if not self.store.config()["enabled"] and not entry.get("requested_intensity"):
                    continue
                if not self.hosters.candidates(hoster):
                    continue
                if not entry.get("next_check_at"):
                    self.hosters.schedule(hoster, 300)
                elif entry["next_check_at"] <= self.clock():
                    self.request(f"hoster:{hoster}", entry.get("requested_intensity"), manual=False)
            self.wake.wait(30)
            self.wake.clear()

    def request(self, provider, intensity=None, manual=True, repair_id=None):
        is_hoster = provider.startswith("hoster:")
        key = provider.split(":", 1)[1] if is_hoster else provider
        store = self.hosters.store if is_hoster else self.store
        if key not in (self.hosters.inventory if is_hoster else PROVIDER_CATALOG):
            raise KeyError(provider)
        intensity = intensity or self.store.config()["intensity"]
        if intensity not in {"light", "standard", "full"}:
            raise ValueError("Ungültige Prüftiefe")
        with self.lock:
            if self.stopped or provider in self.active or len(self.active) >= 2:
                return False
            previous = store.entry(key).get("last_check_at", 0)
            if self.clock() - max(previous, self.last_manual.get(provider, 0)) < 60:
                return False
            self.last_manual[provider] = self.clock()
            self.active.add(provider)
            if repair_id:
                store.update(key, requested_repair=repair_id)
            try:
                self.pool.submit(self._execute, provider, intensity, self.generation)
            except Exception:
                self.active.discard(provider)
                raise
            return True

    def _execute(self, provider, intensity, generation):
        try:
            if provider.startswith("hoster:"):
                self.hosters.check(provider.split(":", 1)[1], intensity, generation=generation)
            else:
                self.check(provider, intensity, generation=generation)
        except Exception:
            # Persist only fixed diagnostic codes, never exception URLs/headers.
            if generation == self.generation and not self.stopped:
                if provider.startswith("hoster:"):
                    key = provider.split(":", 1)[1]
                    self.hosters.store.record(key, {"event": "probe_error", "reason": "internal_probe_error"})
                    self.hosters.schedule(key, 900)
                else:
                    self.store.record(provider, {"event": "probe_error", "reason": "internal_probe_error"})
                    self._schedule(provider, 900)
        finally:
            with self.lock:
                self.active.discard(provider)
            self.wake.set()

    def check(self, provider, intensity="standard", generation=None):
        previous = self.store.entry(provider)
        if intensity != "light" and not self.health.request_allowed(provider):
            # Recovery must also prove series/anime episode hosters; a standard
            # detail-only success cannot reopen a source isolated by full tests.
            intensity = "full"
        result = self.probe.run(provider, intensity, self.profile(provider), previous.get("canaries", []))
        if self.stopped or (generation is not None and generation != self.generation):
            return
        diagnosis = diagnose(result, previous.get("fingerprints"))
        for candidate in result.get("hoster_candidates", []):
            self.hosters.seed(candidate["name"], candidate["url"], provider)
        successes = [item for item in result["details"] if item["ok"]]
        for item in successes:
            for language in item.get("content_languages", []):
                self.record_language_success(provider, item["media_type"], language)
        canaries = previous.get("canaries", [])
        if successes:
            canaries = [{k: item[k] for k in ("source", "title", "media_type", "identity", "metadata", "hoster_count", "cover_identity") if k in item} for item in successes][:8]
        repair_canaries = previous.get("canaries") or canaries
        fingerprints = [response["signature"] for response in result["responses"][:12]]
        changed = bool(previous.get("fingerprints") and fingerprints != previous["fingerprints"])
        failed_rounds = previous.get("failed_rounds", 0) + 1 if diagnosis != "healthy" else 0
        failures = [step for step in result["steps"] if step.get("ok") is False]
        # HTTP-only probes omit production browser recovery. Parser/hoster/
        # track failures remain diagnostics, even across independent titles.
        independent = {step["sample"] for step in failures if step.get("name") == "detail" and step.get("sample") and step["code"] not in {"removed", "budget_exhausted", "missing_hosters"}}
        runtime = self.health.status(provider)
        runtime_success = runtime.get("last_runtime_success_at", 0)
        recent_success = 0 <= self.clock() - runtime_success < 86400 and bool(runtime_success)
        complete_failure = result.get("production_equivalent") is True and len(independent) >= 3 and not successes
        domain_offline = any(step.get("name") == "connectivity" and step.get("code") == "domain_offline" for step in failures)
        offline_rounds = previous.get("offline_rounds", 0) + 1 if domain_offline else 0
        isolated = (failed_rounds >= 2 and complete_failure or offline_rounds >= 3) and not recent_success
        if isolated:
            self.health.mark_blocked(provider, "sentinel_production_failure", diagnosis)
        elif diagnosis == "healthy" and len(successes) >= 3:
            # A homepage-only success cannot recover a quarantined provider.
            self.health.mark_success(provider, runtime=False)
        self.store.update(provider, diagnosis=diagnosis, last_check_at=self.clock(), steps=result["steps"],
                          last_error=failures[-1]["code"] if failures else previous.get("last_error", ""),
                          last_error_at=self.clock() if failures else previous.get("last_error_at", 0),
                          canaries=canaries, fingerprints=fingerprints if diagnosis == "healthy" else previous.get("fingerprints", []),
                          changed=changed, failed_rounds=failed_rounds, offline_rounds=offline_rounds, last_success_at=self.clock() if diagnosis == "healthy" else previous.get("last_success_at", 0))
        self.store.record(provider, {"event": "probe", "diagnosis": diagnosis, "changed": changed,
                                     "duration_ms": round(sum(step["duration_ms"] for step in result["steps"]), 1),
                                     "isolated": isolated, "steps": result["steps"],
                                     "hoster_names": sorted({name for item in result["details"] for name in item.get("hoster_names", [])})[:30]})
        requested = previous.get("requested_repair")
        if requested:
            candidate = next((r for r in previous.get("repairs", []) if r["id"] == requested), None)
            self.store.update(provider, requested_repair=None)
            if candidate:
                profile, evidence = self.repairs.validate(provider, candidate["profile"], result, repair_canaries)
                candidate.update(profile=profile, validation=evidence, confidence="high" if evidence["shadow_passed"] else "low",
                                 state="available" if evidence["shadow_passed"] else "needs_attention")
                self.store.update(provider, repairs=previous["repairs"])
                if evidence["shadow_passed"]:
                    self.repairs.activate(provider, requested)
                    self.health.mark_success(provider, runtime=False)
                else:
                    self.store.update(provider, diagnosis="needs_attention")
                    diagnosis = "needs_attention"
        elif diagnosis in {"broken", "healthy"} and not previous.get("active_repair") and len(canaries) >= 3:
            candidates = self.repairs.propose(provider, result, repair_canaries)
            validated = next((candidate for candidate in candidates if candidate["confidence"] == "high"), None)
            if validated and self.store.config()["auto_repair"] and not self.stopped and (generation is None or generation == self.generation):
                self.repairs.activate(provider, validated["id"])
                self.health.mark_success(provider, runtime=False)
                self.store.update(provider, diagnosis="healthy", failed_rounds=0)
                diagnosis = "repaired"
            elif candidates:
                self.store.update(provider, diagnosis="repair_available" if validated else "needs_attention")
                diagnosis = "repair_available" if validated else "needs_attention"
            elif diagnosis == "broken":
                self.store.update(provider, diagnosis="needs_attention")
                diagnosis = "needs_attention"
        elif diagnosis == "broken":
            self.store.update(provider, diagnosis="needs_attention")
            diagnosis = "needs_attention"
        self._schedule(provider, min(3600, self.store.config()["interval_hours"] * 3600) if isolated else None)
        if self.store.config()["notify_changes"] and (diagnosis != previous.get("diagnosis", "unknown") or isolated and runtime["state"] == "healthy") and diagnosis in {"healthy", "broken", "offline", "blocked", "repaired", "needs_attention"}:
            self._notify(provider, diagnosis)
        return self.store.entry(provider)

    def observe(self, provider, ok, duration, source="", result=None, operation="", *, runtime_failure=False):
        if not self.stopped:
            # Record actual adapter outcomes before stricter repair-identity
            # checks. A changed poster is not a production provider outage.
            episode = parse_episode_slug(source)
            runtime_source = episode[0].split("|", 1)[0] if episode else source
            previous_runtime = self.health.status(provider)
            runtime = self.health.record_runtime(provider, ok, runtime_source if runtime_failure and operation.startswith("get_") else "")
            if runtime["state"] != previous_runtime["state"]:
                if runtime["state"] == "cooldown":
                    # The existing bounded scheduler owns automatic recovery;
                    # do not leave a real circuit waiting for a 12h diagnosis.
                    self.store.update(provider, next_check_at=runtime["next_probe_at"])
                    self.wake.set()
                self._notify(provider, self.store.entry(provider, ("diagnosis",)).get("diagnosis", "unknown"))
        if not source or self.stopped:
            return
        with self.lock:
            entry = self.store.entry(provider, ("active_repair", "canaries", "repair_failures"))
            repair = entry.get("active_repair")
            sample = identity(source)
            expected = next((ref for ref in entry.get("canaries", []) if ref["identity"] == sample), None)
            data = payload(result)
            if ok and expected:
                ok = title_key(data.get("title")) == title_key(expected["title"]) and all(
                    not present or bool(data.get(field)) for field, present in expected.get("metadata", {}).items()
                )
                ok = ok and (not expected.get("cover_identity") or identity(data.get("cover_url", "")) == expected["cover_identity"])
                if expected.get("media_type") == "movies":
                    ok = ok and len(data.get("hosters") or []) >= expected.get("hoster_count", 0)
            is_episode = operation == "get_episode" or parse_episode_slug(source) is not None
            if ok:
                for hoster in (data.get("hosters") or [])[:20]:
                    row = payload(hoster)
                    self.hosters.seed(str(row.get("name") or ""), str(row.get("url") or ""), provider)
                if is_episode and any(valid_source_link(payload(h).get("url") or "") for h in data.get("hosters", [])) and PROVIDER_CATALOG[provider].media_types == ("anime",):
                    self.record_language_success(provider, "anime", data.get("content_language"))
            if ok and result and not is_episode and self.clock() - self.last_canary_observation.get(provider, 0) >= 60:
                media_type = "anime" if operation == "get_anime" or PROVIDER_CATALOG[provider].media_types == ("anime",) else "series" if operation == "get_series" or hasattr(result, "seasons") else "movies"
                canary = reference(result, media_type)
                if canary:
                    canary["metadata"] = {field: bool(data.get(field)) for field in ("title", "cover_url", "description", "genres", "year")}
                    canary["hoster_count"] = len(data.get("hosters") or [])
                    canary["cover_identity"] = identity(data["cover_url"]) if data.get("cover_url") else ""
                    canaries = [canary] + [ref for ref in entry.get("canaries", []) if ref["identity"] != canary["identity"]]
                    if canaries[:8] != entry.get("canaries", []):
                        self.store.update(provider, canaries=canaries[:8])
                        self.last_canary_observation[provider] = self.clock()
            if not repair:
                return
            failures = [row for row in entry.get("repair_failures", []) if self.clock() - row["timestamp"] < 900]
            failures = [row for row in failures if row["sample"] != sample]
            if not ok:
                failures.append({"sample": sample, "timestamp": self.clock()})
            self.store.update(provider, repair_failures=failures)
            if len(failures) >= 3:
                self.repairs.rollback(provider, repair, "three_independent_runtime_failures")
                self.store.update(provider, diagnosis="needs_attention")
                if self.store.config()["notify_changes"]:
                    self._notify(provider, "repair_rolled_back")

    def record_language_success(self, provider, media_type, language):
        """Bounded capability evidence, without episode/user/source identifiers."""
        definition = PROVIDER_CATALOG.get(provider)
        language = normalize_content_language(language)
        if self.stopped or not definition or media_type not in definition.media_types or language not in definition.content_languages:
            return
        with self.lock:
            now = self.clock()
            old = self.store.entry(provider, ("language_evidence",)).get("language_evidence", {})
            evidence = {media: {lang: timestamp for lang, timestamp in values.items()
                                if lang in definition.content_languages and 0 <= now - timestamp < 86400}
                        for media, values in old.items() if media in definition.media_types}
            # Avoid a disk write for every resolve of the same language.
            if now - evidence.get(media_type, {}).get(language, 0) < 60:
                return
            evidence.setdefault(media_type, {})[language] = now
            self.store.update(provider, language_evidence=evidence)

    def diagnostics(self, provider=None):
        enabled = set(self.enabled())
        hoster_rows = self.hosters.diagnostics()
        hoster_states = {row["hoster"]: row["diagnosis"] for row in hoster_rows}
        rows = []
        for key, definition in PROVIDER_CATALOG.items():
            entry = self.store.entry(key)
            priority = {media: order.index(key) + 1 for media in definition.media_types if key in (order := self.priorities(media))}
            history = [item for item in entry.get("history", []) if self.clock() - item["timestamp"] < 86400 and item["event"] == "probe"]
            failed = sum(item["diagnosis"] != "healthy" for item in history)
            hoster_names = {str(name) for item in entry.get("history", []) for name in item.get("hoster_names", [])}
            from media.hoster_contracts import hoster_key
            hosters = [{"name": name, "state": hoster_states.get(hoster_key(name), "unknown")} for name in sorted(hoster_names)]
            rows.append({"provider": key, "label": definition.label, "enabled": key in enabled, "priority": priority,
                         "domain": self.profile(key).get("domain") or definition.domains[0],
                         "contract": contract(key).public_dict(), "runtime": self.health.status(key),
                         "routing": {"allowed": self.health.routing_allowed(key), "evidence": self.health.status(key)["reason"]},
                         "content_language": definition.content_language, "content_languages": list(provider_content_languages(key)),
                         "language_evidence": entry.get("language_evidence", {}),
                         "enabled_media_types": [media for media in definition.media_types if not self.has_priorities or key in self.priorities(media)],
                         "diagnosis": entry.get("diagnosis", "unknown"), "running": key in self.active,
                         "last_check_at": entry.get("last_check_at", 0), "next_check_at": entry.get("next_check_at", 0),
                         "last_success_at": entry.get("last_success_at", 0), "steps": entry.get("steps", []),
                         "last_error": entry.get("last_error", ""), "last_error_at": entry.get("last_error_at", 0),
                         "changed": entry.get("changed", False), "active_repair": entry.get("active_repair"),
                         "repairs": entry.get("repairs", []), "history": entry.get("history", []), "hosters": hosters,
                         "error_rate_24h": round(failed / len(history), 3) if history else None,
                         "average_duration_ms": round(sum(item["duration_ms"] for item in history) / len(history), 1) if history else None})
        service = source_service_health(rows, hoster_rows, self.clock(), self.languages() if self.languages else None)
        for row in rows:
            row["user_impact"] = service["sources"]["providers"].get(row["provider"], {"impact": "none", "action_required": False})
        if provider:
            rows = [row for row in rows if row["provider"] == provider]
        active = [row for row in rows if row["enabled"]]
        return {"config": self.store.config(), "providers": rows, "hosters": hoster_rows,
                "service": service,
                "hoster_summary": {state: sum(row["diagnosis"] == state for row in hoster_rows) for state in {"healthy", "degraded", "offline", "broken", "blocked", "unknown", "needs_attention", "repair_available"}},
                "last_complete_check_at": min((row["last_check_at"] for row in active), default=0),
                "next_check_at": min((row["next_check_at"] for row in active if row["next_check_at"]), default=0),
                "summary": {state: sum(row["diagnosis"] == state for row in active) for state in {"healthy", "degraded", "broken", "blocked", "unknown", "needs_attention", "repair_available"}}}
