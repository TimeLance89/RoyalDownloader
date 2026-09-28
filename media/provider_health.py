"""Persistenter, threadsicherer Circuit-Breaker für externe Anbieter."""

from __future__ import annotations

import json
import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


HEALTHY = "healthy"
COOLDOWN = "cooldown"
PROBING = "probing"
BLOCKED = "blocked"
VALID_STATES = {HEALTHY, COOLDOWN, PROBING, BLOCKED}


class ProviderHealth:
    """Verwaltet Provider-Zustände und schreibt sie atomar auf Disk.

    ``begin_probe`` ist die einzige Operation, die einen Provider nach einem
    Cooldown in ``probing`` versetzt. Der gemeinsame Lock garantiert, dass
    parallele Worker niemals mehr als eine Probe erhalten.
    """

    def __init__(
        self,
        path: Path,
        *,
        initial_cooldown: int = 15 * 60,
        maximum_cooldown: int = 6 * 60 * 60,
        multiplier: float = 2.0,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.initial_cooldown = max(1, int(initial_cooldown))
        self.maximum_cooldown = max(self.initial_cooldown, int(maximum_cooldown))
        self.multiplier = max(1.0, float(multiplier))
        self.clock = clock
        self._lock = threading.RLock()
        self._providers: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _default(provider: str) -> dict:
        return {
            "provider": provider,
            "state": HEALTHY,
            "failure_count": 0,
            "blocked_reason": "",
            "blocked_at": 0.0,
            "next_probe_at": 0.0,
            "last_success_at": 0.0,
            "last_runtime_success_at": 0.0,
            "last_error": "",
            "runtime_failures": [],
        }

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        providers = raw.get("providers", raw) if isinstance(raw, dict) else {}
        if not isinstance(providers, dict):
            return
        reconciled = False
        for key, value in providers.items():
            if not isinstance(value, dict):
                continue
            provider = str(key).strip().casefold()
            if not provider:
                continue
            item = self._default(provider)
            item.update({field: value.get(field, default) for field, default in item.items()})
            if item["state"] not in VALID_STATES:
                item["state"] = HEALTHY
            # Ein Prozessabbruch während einer Probe darf keinen permanenten
            # probing-Zustand hinterlassen. Die alte Sperrfrist bleibt gültig.
            if item["state"] == PROBING:
                item["state"] = COOLDOWN
                item["next_probe_at"] = max(
                    float(item.get("next_probe_at") or 0), self.clock(),
                )
            self._providers[provider] = item
            # The old Sentinel treated incomplete HTTP diagnoses as runtime
            # outages. Only that obsolete provenance is reconciled here.
            if item["blocked_reason"] == "sentinel_confirmed_failure":
                item.update(state=HEALTHY, blocked_reason="", blocked_at=0.0,
                            next_probe_at=0.0, failure_count=0, last_error="")
                reconciled = True
        if reconciled:
            self._write_locked()

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        payload = json.dumps(
            {"version": 1, "providers": self._providers},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _entry_locked(self, provider: str) -> dict:
        key = str(provider).strip().casefold()
        if key not in self._providers:
            self._providers[key] = self._default(key)
        return self._providers[key]

    def cooldown_seconds(self, failure_count: int) -> int:
        exponent = max(0, int(failure_count) - 1)
        value = self.initial_cooldown * (self.multiplier ** exponent)
        return min(self.maximum_cooldown, max(1, int(value)))

    def mark_blocked(self, provider: str, reason: str, error: str = "") -> dict:
        with self._lock:
            item = self._entry_locked(provider)
            now = self.clock()
            item["state"] = BLOCKED
            item["failure_count"] = int(item.get("failure_count") or 0) + 1
            item["blocked_reason"] = str(reason or "provider_blocked")[:120]
            item["blocked_at"] = now
            item["last_error"] = str(error or reason or "")[:500]
            item["next_probe_at"] = now + self.cooldown_seconds(item["failure_count"])
            # BLOCKED ist der atomare Erkennungszustand; nach Berechnung der
            # Sperrfrist wechselt der persistierte Zustand in den Cooldown.
            item["state"] = COOLDOWN
            self._write_locked()
            return dict(item)

    def begin_probe(self, provider: str, *, force: bool = False) -> bool:
        with self._lock:
            item = self._entry_locked(provider)
            if item["state"] == PROBING:
                return False
            if item["state"] == HEALTHY and not force:
                return False
            if not force and self.clock() < float(item.get("next_probe_at") or 0):
                return False
            item["state"] = PROBING
            self._write_locked()
            return True

    def mark_success(self, provider: str, *, reset_failures: bool = True, runtime: bool = True) -> dict:
        with self._lock:
            item = self._entry_locked(provider)
            item.update({
                "state": HEALTHY,
                "blocked_reason": "",
                "blocked_at": 0.0,
                "next_probe_at": 0.0,
                "last_success_at": self.clock(),
                "last_error": "",
            })
            if reset_failures:
                item["failure_count"] = 0
                item["runtime_failures"] = []
            if runtime:
                item["last_runtime_success_at"] = self.clock()
            self._write_locked()
            return dict(item)

    def finish_probe_error(self, provider: str, error: str) -> dict:
        return self.mark_blocked(provider, "probe_failed", error)

    def request_allowed(self, provider: str) -> bool:
        with self._lock:
            return self._entry_locked(provider)["state"] == HEALTHY

    def routing_allowed(self, provider: str) -> bool:
        """An expired cooldown permits one adapter-owned recovery attempt."""
        with self._lock:
            item = self._entry_locked(provider)
            return item["state"] == HEALTHY or item["state"] == COOLDOWN and self.clock() >= float(item.get("next_probe_at") or 0)

    def record_runtime(self, provider: str, ok: bool, source: str = "") -> dict:
        """Three independent real failures in 15 minutes open the circuit.

        Store only bounded hashed identities, never titles or source URLs.
        Active Sentinel probes must never call this method.
        """
        with self._lock:
            item = self._entry_locked(provider)
            now = self.clock()
            if ok:
                # Successful browsing need not fsync on every request.
                if item["state"] != HEALTHY or item.get("runtime_failures") or now - float(item.get("last_runtime_success_at") or 0) >= 60:
                    return self.mark_success(provider)
                return dict(item)
            if not source:
                return dict(item)
            sample = hashlib.sha256(source.encode()).hexdigest()[:24]
            rows = [row for row in item.get("runtime_failures", [])
                    if 0 <= now - row["timestamp"] < 900 and row["sample"] != sample]
            rows.append({"sample": sample, "timestamp": now})
            item["runtime_failures"] = rows[-8:]
            if len(rows) >= 3:
                return self.mark_blocked(provider, "runtime_independent_failures")
            self._write_locked()
            return dict(item)

    def status(self, provider: str, *, waiting_episode_count: int = 0) -> dict:
        with self._lock:
            item = dict(self._entry_locked(provider))
            remaining = max(
                0, int(float(item.get("next_probe_at") or 0) - self.clock()),
            ) if item["state"] in {COOLDOWN, BLOCKED, PROBING} else 0
            item.update({
                "reason": item.get("blocked_reason", ""),
                "remaining_seconds": remaining,
                "waiting_episode_count": max(0, int(waiting_episode_count)),
                "runtime_failure_count": len([row for row in item.get("runtime_failures", []) if 0 <= self.clock() - row["timestamp"] < 900]),
            })
            return item

    def next_probe_at(self, provider: str) -> float:
        with self._lock:
            return float(self._entry_locked(provider).get("next_probe_at") or 0)
