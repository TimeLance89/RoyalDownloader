"""Hoster evidence and repairs owned by the existing Source Sentinel scheduler."""
import hashlib
import statistics
import threading
from urllib.parse import urlsplit

from application_services.hoster_probe import HosterProbe, classify_failure
from application_services.hoster_repair import HosterRepair
from media.hoster_contracts import CONTRACTS, runtime_contract, hoster_key, canary_identity, media_identity
from media.provider_monitor_store import HosterStore
from application_services.provider_probe import valid_source_link

MAX_HOSTERS = 64
MAX_CANARIES = 8
CANARY_TTL = 7 * 86400
MAX_SAMPLES = 1024


def metrics(samples, now, days=1, buckets=None):
    rows = [row for row in samples if now - days * 86400 <= row["timestamp"] <= now]
    successes = sum(row["code"] == "resolve_success" for row in rows)
    attempts = len(rows)
    if buckets is not None:
        counted = [bucket for bucket in buckets if now - days * 86400 <= bucket["timestamp"] <= now]
        attempts = sum(bucket["attempts"] for bucket in counted)
        successes = sum(bucket["successes"] for bucket in counted)
    return {"attempts": attempts, "success_rate": round(successes / attempts, 4) if attempts else None,
            "error_rate": round(1 - successes / attempts, 4) if attempts else None,
            "median_resolve_ms": round(statistics.median(row["duration_ms"] for row in rows), 1) if rows else None}


def health(samples):
    rows = list(samples)
    if not rows:
        return "unknown"
    recent = rows[-20:]
    failed = [row for row in recent if row["code"] not in {"resolve_success", "removed", "recognition_only"}]
    independent = {row["identity"] for row in failed}
    blocked = {row["identity"] for row in failed if row["code"] in {"blocked", "rate_limit"}}
    if len(blocked) >= 3:
        return "blocked"
    if len(independent) >= 3 and any(row["code"] == "needs_attention" for row in failed):
        return "needs_attention"
    success = sum(row["code"] == "resolve_success" for row in recent)
    if len(independent) >= 3 and len(recent) >= 5 and success / len(recent) < .3:
        if all(row["code"] in {"network_error", "timeout"} for row in failed):
            return "offline"
        if any(row["code"] in {"parser_error", "media_invalid"} for row in failed):
            return "broken"
    if failed:
        return "degraded"
    if success >= 3:
        return "healthy"
    return "unknown"


class HosterMonitor:
    def __init__(self, owner, probe=None):
        self.owner = owner
        self.store = HosterStore(owner.store)
        self.clock = owner.clock
        self.probe = probe or HosterProbe()
        self.repairs = HosterRepair(self.store, self.probe)
        self.lock = threading.RLock()
        self.canaries = {}
        self.inventory = dict(CONTRACTS)
        with owner.store.lock:
            for key in owner.store.data["hosters"]:
                if key != "unknown" and hoster_key(key) == key and len(self.inventory) < MAX_HOSTERS:
                    self.inventory[key] = runtime_contract(key)

    def begin(self, name, url, provider=""):
        if self.owner.stopped or not valid_source_link(url) or len(url) > 8192:
            return
        self.seed(name, url, provider)
        key = hoster_key(name, url)
        if key in self.inventory:
            self.store.record(key, {"event": "resolve_attempt"})

    def observe(self, name, url, ok, duration_ms=0, provider="", message="", media_url=""):
        if self.owner.stopped or not valid_source_link(url) or len(url) > 8192:
            return
        contract = runtime_contract(name, url)
        key = contract.hoster
        now = self.clock()
        # Do not persist token-bearing URLs, paths, titles or response bodies.
        identity = canary_identity(url)
        domain = urlsplit(url).hostname.lower()
        code = "resolve_success" if ok else classify_failure(message)
        with self.lock:
            if key not in self.inventory and len(self.inventory) >= MAX_HOSTERS:
                return
            self.inventory[key] = contract
            entry = self.store.entry(key)
            samples = [row for row in entry.get("samples", []) if now - row["timestamp"] <= 7 * 86400]
            row = {"timestamp": now, "code": code, "identity": identity, "duration_ms": min(300000, max(0, round(duration_ms, 1)))}
            samples.append(row)
            samples = samples[-MAX_SAMPLES:]
            buckets = [bucket for bucket in entry.get("runtime_buckets", []) if now - bucket["timestamp"] < 7 * 86400]
            minute = int(now // 60) * 60
            if buckets and buckets[-1]["timestamp"] == minute:
                bucket = buckets[-1]
            else:
                bucket = {"timestamp": minute, "attempts": 0, "successes": 0}
                buckets.append(bucket)
            bucket["attempts"] += 1
            bucket["successes"] += int(ok)
            state = health([row for row in samples if now - row["timestamp"] < 86400])
            providers = sorted(set(entry.get("providers", [])) | ({provider} if provider in self.owner.enabled() else set()))[:15]
            domains = sorted(set(entry.get("domains", [])) | {domain})[:16]
            self.store.update(key, samples=samples, runtime_buckets=buckets[-10081:], diagnosis=state, providers=providers, domains=domains,
                              last_success_at=now if ok else entry.get("last_success_at", 0),
                              last_failure_at=now if not ok else entry.get("last_failure_at", 0), last_error="" if ok else code)
            self.store.record(key, {"event": code, "duration_ms": row["duration_ms"]})
            if ok:
                self.seed(name, url, provider, proven=True, media_signature=media_identity(media_url))
            if entry.get("active_repair"):
                repair = next(item for item in entry.get("repairs", []) if item["id"] == entry["active_repair"])
                after = [row for row in samples if row["timestamp"] >= repair.get("activated_at", now)]
                failures = {row["identity"] for row in after if row["code"] != "resolve_success"}
                if len(after) >= 5 and len(failures) >= 3 and sum(row["code"] == "resolve_success" for row in after) / len(after) < .5:
                    self.repairs.rollback(key, repair["id"], "runtime_success_rate_regressed")
                    self.store.update(key, diagnosis="needs_attention")
                    self.owner._notify(key, "repair_rolled_back", "hoster")
            if state != entry.get("diagnosis") and state in {"broken", "offline", "blocked", "healthy"}:
                self.owner._notify(key, state, "hoster")

    def seed(self, name, url, provider="", proven=False, media_signature=""):
        if not valid_source_link(url) or len(url) > 8192:
            return
        key, now = hoster_key(name, url), self.clock()
        # Provider redirects must be resolved by their owner, not tested as embeds.
        from providers.catalog import PROVIDER_CATALOG
        hostname = urlsplit(url).hostname.lower()
        if any(hostname == domain or hostname.endswith("." + domain) for definition in PROVIDER_CATALOG.values() for domain in definition.domains):
            return
        with self.lock:
            if key not in self.inventory and len(self.inventory) >= MAX_HOSTERS:
                return
            self.inventory[key] = runtime_contract(name, url)
            entry = self.store.entry(key, ("providers", "domains"))
            domains = sorted(set(entry.get("domains", [])) | {hostname})[:16]
            providers = sorted(set(entry.get("providers", [])) | ({provider} if provider in self.owner.enabled() else set()))[:15]
            if domains != entry.get("domains") or providers != entry.get("providers"):
                self.store.update(key, domains=domains, providers=providers)
            identity = canary_identity(url)
            rows = [row for row in self.canaries.get(key, []) if now - row["seen_at"] <= CANARY_TTL]
            prior = next((row for row in rows if row["identity"] == identity), {})
            rows = [row for row in rows if row["identity"] != identity]
            rows.append({"url": url, "identity": identity, "seen_at": now, "proven": proven or prior.get("proven", False), "provider": provider, "media_signature": media_signature or prior.get("media_signature", "")})
            rows.sort(key=lambda row: (row["proven"], row["seen_at"]))
            self.canaries[key] = rows[-MAX_CANARIES:]

    def candidates(self, key):
        with self.lock:
            rows = [row.copy() for row in self.canaries.get(key, []) if self.clock() - row["seen_at"] <= CANARY_TTL]
            self.canaries[key] = rows
            return sorted(rows, key=lambda row: (row["proven"], row["seen_at"]), reverse=True)

    def check(self, key, intensity="standard", generation=None):
        previous = self.store.entry(key)
        canaries = self.candidates(key)
        result = self.probe.run(key, intensity, self.repairs.profile(key), canaries)
        if self.owner.stopped or generation is not None and generation != self.owner.generation:
            return
        evidence = [{**row, "timestamp": self.clock(), "code": "resolve_success" if row["ok"] else row["code"]} for row in result["details"]]
        accumulated = [row for row in previous.get("probe_evidence", []) if self.clock() - row["timestamp"] < 86400] + evidence
        accumulated = accumulated[-30:]
        state = health(accumulated) if evidence else "unknown"
        # A no-browser check cannot prove a JS-only mechanism has failed.
        if len({row["identity"] for row in accumulated}) < 3 and state in {"broken", "offline", "blocked"}:
            state = "degraded"
        self.store.update(key, diagnosis=state, steps=result["steps"], last_check_at=self.clock(), requested_intensity=None, probe_evidence=accumulated)
        self.store.record(key, {"event": "sentinel_probe", "diagnosis": state, "tested": len(evidence), "successful": sum(row["ok"] for row in result["details"])})
        for row in result["details"]:
            if row["ok"]:
                reference = next(ref for ref in canaries if ref["identity"] == row["identity"])
                self.seed(key, reference["url"], reference.get("provider", ""), proven=True, media_signature=row.get("media_signature", ""))
        canaries = self.candidates(key)[:5]
        requested = previous.get("requested_repair")
        if requested:
            repair = next((item for item in previous.get("repairs", []) if item["id"] == requested), None)
            if repair:
                profile, validation = self.repairs.validate(key, repair["profile"], result, canaries)
                if self.owner.stopped or generation is not None and generation != self.owner.generation:
                    return
                repair.update(profile=profile, validation=validation, confidence="high" if validation["shadow_passed"] else "low", state="available" if validation["shadow_passed"] else "needs_attention")
                self.store.update(key, repairs=previous["repairs"], requested_repair=None)
                if validation["shadow_passed"]:
                    self.repairs.activate(key, requested)
                    self.store.update(key, diagnosis="repairing")
        elif not previous.get("active_repair") and intensity != "light":
            proposals = self.repairs.propose(key, result, canaries)
            if self.owner.stopped or generation is not None and generation != self.owner.generation:
                return
            if proposals:
                proposal = proposals[0]
                if proposal["confidence"] == "high" and self.store.config()["auto_repair"]:
                    self.repairs.activate(key, proposal["id"])
                    self.store.update(key, diagnosis="repairing")
                else:
                    self.store.update(key, diagnosis="repair_available" if proposal["confidence"] == "high" else "needs_attention")
        self.schedule(key)
        diagnosis = self.store.entry(key, ("diagnosis",)).get("diagnosis", "unknown")
        if diagnosis != previous.get("diagnosis") and diagnosis in {"broken", "offline", "blocked", "repairing", "repair_available", "needs_attention"}:
            self.owner._notify(key, diagnosis, "hoster")

    def schedule(self, key, delay=None):
        jitter = int(hashlib.sha256(key.encode()).hexdigest()[:6], 16) % 900
        self.store.update(key, next_check_at=self.clock() + (delay if delay is not None else self.store.config()["interval_hours"] * 3600) + jitter)

    def penalty(self, name, url=""):
        entry = self.store.entry(hoster_key(name, url), ("diagnosis", "last_check_at", "last_success_at", "last_failure_at"))
        observed = max(entry.get(field, 0) or 0 for field in ("last_check_at", "last_success_at", "last_failure_at"))
        state = entry.get("diagnosis", "unknown") if 0 <= self.clock() - observed < 86400 else "unknown"
        return {"broken": -100, "offline": -100, "blocked": -80, "degraded": -20, "needs_attention": -40}.get(state, 0)

    def diagnostics(self):
        rows = []
        with self.lock:
            contracts = sorted(self.inventory.items())
        for key, contract in contracts:
            entry = self.store.entry(key)
            samples = entry.get("samples", [])
            rows.append({"hoster": key, "label": key, "contract": contract.public_dict(), "diagnosis": entry.get("diagnosis", "unknown"),
                         "domains": entry.get("domains", []), "providers": entry.get("providers", []), "running": f"hoster:{key}" in self.owner.active,
                         "metrics_24h": metrics(samples, self.clock(), buckets=entry.get("runtime_buckets")), "metrics_7d": metrics(samples, self.clock(), 7, entry.get("runtime_buckets")),
                         **{field: entry.get(field, [] if field in {"steps", "history", "repairs"} else None) for field in ("last_check_at", "next_check_at", "last_success_at", "last_failure_at", "last_error", "steps", "history", "repairs", "active_repair")}})
        return rows
