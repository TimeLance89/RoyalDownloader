"""Staggered Sentinel scheduling and conservative existing health integration."""
from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from application_services.provider_probe import ProviderProbe, diagnose, identity, reference, payload, title_key
from application_services.provider_repair import ProviderRepair
from media.provider_monitor_store import ProviderMonitorStore
from providers.catalog import PROVIDER_CATALOG
from providers.probe_contracts import contract


class ProviderMonitor:
    def __init__(self, path, health, enabled, *, hoster_intel=None, probe=None, notify=None, priorities=None, clock=time.time):
        self.store = ProviderMonitorStore(path, clock)
        self.health, self.enabled, self.hoster_intel = health, enabled, hoster_intel
        self.probe = probe or ProviderProbe()
        self.repairs = ProviderRepair(self.store, self.probe)
        self.clock, self.notify = clock, notify or (lambda _event: None)
        self.priorities = priorities or (lambda _media: [])
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

    def profile(self, provider):
        return self.repairs.profile(provider)

    def allowed(self, provider):
        return self.health.request_allowed(provider)

    def _schedule(self, provider, delay=None):
        config = self.store.config()
        jitter = int(hashlib.sha256(provider.encode()).hexdigest()[:6], 16) % 900
        seconds = config["interval_hours"] * 3600 + jitter if delay is None else delay + jitter
        self.store.update(provider, next_check_at=self.clock() + seconds)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stopped = False
            self.stop_event.clear()
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
            self.wake.wait(30)
            self.wake.clear()

    def request(self, provider, intensity=None, manual=True, repair_id=None):
        if provider not in PROVIDER_CATALOG:
            raise KeyError(provider)
        intensity = intensity or self.store.config()["intensity"]
        if intensity not in {"light", "standard", "full"}:
            raise ValueError("Ungültige Prüftiefe")
        with self.lock:
            if self.stopped or provider in self.active or len(self.active) >= 2:
                return False
            previous = self.store.entry(provider).get("last_check_at", 0)
            if self.clock() - max(previous, self.last_manual.get(provider, 0)) < 60:
                return False
            self.last_manual[provider] = self.clock()
            self.active.add(provider)
            if repair_id:
                self.store.update(provider, requested_repair=repair_id)
            try:
                self.pool.submit(self._execute, provider, intensity, self.generation)
            except Exception:
                self.active.discard(provider)
                raise
            return True

    def _execute(self, provider, intensity, generation):
        try:
            self.check(provider, intensity, generation=generation)
        except Exception:
            # Persist only fixed diagnostic codes, never exception URLs/headers.
            if generation == self.generation and not self.stopped:
                self.store.record(provider, {"event": "probe_error", "reason": "internal_probe_error"})
                self._schedule(provider, 900)
        finally:
            with self.lock:
                self.active.discard(provider)
            self.wake.set()

    def check(self, provider, intensity="standard", generation=None):
        previous = self.store.entry(provider)
        result = self.probe.run(provider, intensity, self.profile(provider), previous.get("canaries", []))
        if self.stopped or (generation is not None and generation != self.generation):
            return
        diagnosis = diagnose(result, previous.get("fingerprints"))
        successes = [item for item in result["details"] if item["ok"]]
        canaries = previous.get("canaries", [])
        if successes:
            canaries = [{k: item[k] for k in ("source", "title", "media_type", "identity", "metadata", "hoster_count", "cover_identity") if k in item} for item in successes][:8]
        repair_canaries = previous.get("canaries") or canaries
        fingerprints = [response["signature"] for response in result["responses"][:12]]
        changed = bool(previous.get("fingerprints") and fingerprints != previous["fingerprints"])
        failed_rounds = previous.get("failed_rounds", 0) + 1 if diagnosis != "healthy" else 0
        failures = [step for step in result["steps"] if step.get("ok") is False]
        independent = {step["sample"] for step in result["steps"] if step.get("ok") is False and step["sample"] and step["code"] not in {"removed", "budget_exhausted"}}
        isolated = failed_rounds >= 2 and (len(independent) >= 2 or diagnosis == "blocked")
        if isolated:
            self.health.mark_blocked(provider, "sentinel_confirmed_failure", diagnosis)
        elif diagnosis == "healthy" and len(successes) >= 3:
            # A homepage-only success cannot recover a quarantined provider.
            self.health.mark_success(provider)
        self.store.update(provider, diagnosis=diagnosis, last_check_at=self.clock(), steps=result["steps"],
                          last_error=failures[-1]["code"] if failures else previous.get("last_error", ""),
                          last_error_at=self.clock() if failures else previous.get("last_error_at", 0),
                          canaries=canaries, fingerprints=fingerprints if diagnosis == "healthy" else previous.get("fingerprints", []),
                          changed=changed, failed_rounds=failed_rounds, last_success_at=self.clock() if diagnosis == "healthy" else previous.get("last_success_at", 0))
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
                if evidence["shadow_passed"]:
                    candidate.update(profile=profile, validation=evidence, confidence="high")
                    self.store.update(provider, repairs=previous["repairs"])
                    self.repairs.activate(provider, requested)
                    self.health.mark_success(provider)
        elif diagnosis in {"broken", "healthy"} and not previous.get("active_repair") and len(canaries) >= 3:
            candidates = self.repairs.propose(provider, result, repair_canaries)
            validated = next((candidate for candidate in candidates if candidate["confidence"] == "high"), None)
            if validated and self.store.config()["auto_repair"] and not self.stopped and (generation is None or generation == self.generation):
                self.repairs.activate(provider, validated["id"])
                self.health.mark_success(provider)
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
        if self.store.config()["notify_changes"] and diagnosis != previous.get("diagnosis", "unknown") and diagnosis in {"broken", "blocked", "repaired", "needs_attention"}:
            self.notify({"provider": provider, "diagnosis": diagnosis})
        return self.store.entry(provider)

    def observe(self, provider, ok, duration, source="", result=None):
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
            if ok and result and self.clock() - self.last_canary_observation.get(provider, 0) >= 60:
                media_type = "series" if hasattr(result, "seasons") else "anime" if hasattr(result, "episodes") else "movies"
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
                    self.notify({"provider": provider, "diagnosis": "repair_rolled_back"})

    def diagnostics(self, provider=None):
        enabled = set(self.enabled())
        rows = []
        for key, definition in PROVIDER_CATALOG.items():
            if provider and key != provider:
                continue
            entry = self.store.entry(key)
            priority = {media: order.index(key) + 1 for media in definition.media_types if key in (order := self.priorities(media))}
            history = [item for item in entry.get("history", []) if self.clock() - item["timestamp"] < 86400 and item["event"] == "probe"]
            failed = sum(item["diagnosis"] != "healthy" for item in history)
            hoster_names = {str(name) for item in entry.get("history", []) for name in item.get("hoster_names", [])}
            hosters = [{"name": name, "state": "cooldown" if self.hoster_intel and self.hoster_intel.cooldown(hoster_name=name)[0] else "unknown"} for name in sorted(hoster_names)]
            rows.append({"provider": key, "label": definition.label, "enabled": key in enabled, "priority": priority,
                         "domain": self.profile(key).get("domain") or definition.domains[0],
                         "contract": contract(key).public_dict(), "runtime": self.health.status(key),
                         "diagnosis": entry.get("diagnosis", "unknown"), "running": key in self.active,
                         "last_check_at": entry.get("last_check_at", 0), "next_check_at": entry.get("next_check_at", 0),
                         "last_success_at": entry.get("last_success_at", 0), "steps": entry.get("steps", []),
                         "last_error": entry.get("last_error", ""), "last_error_at": entry.get("last_error_at", 0),
                         "changed": entry.get("changed", False), "active_repair": entry.get("active_repair"),
                         "repairs": entry.get("repairs", []), "history": entry.get("history", []), "hosters": hosters,
                         "error_rate_24h": round(failed / len(history), 3) if history else None,
                         "average_duration_ms": round(sum(item["duration_ms"] for item in history) / len(history), 1) if history else None})
        active = [row for row in rows if row["enabled"]]
        return {"config": self.store.config(), "providers": rows,
                "last_complete_check_at": min((row["last_check_at"] for row in active), default=0),
                "next_check_at": min((row["next_check_at"] for row in active if row["next_check_at"]), default=0),
                "summary": {state: sum(row["diagnosis"] == state for row in active) for state in {"healthy", "degraded", "broken", "blocked", "unknown", "needs_attention", "repair_available"}}}
