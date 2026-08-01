"""Kurzlebiger, persistenter Cache fuer bereits aufgeloeste Provider-Links."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class ResolvedLinkCache:
    """Speichert Redirect-Ziele mit striktem TTL und atomischen Writes.

    Die Provider-URL wird nur als SHA-256-Schluessel abgelegt. Dadurch landen
    darin enthaltene Redirect-Tokens nicht ein zweites Mal im Runtime-State.
    Ziel-URLs koennen selbst kurzlebige Signaturen enthalten und werden deshalb
    nie laenger als das konfigurierte TTL wiederverwendet.
    """

    def __init__(
        self,
        path: Path,
        *,
        ttl_seconds: int = 15 * 60,
        max_entries: int = 2000,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self.clock = clock
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(source_url: str) -> str:
        return hashlib.sha256(str(source_url).encode("utf-8")).hexdigest()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return
        entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
        if not isinstance(entries, dict):
            return
        now = self.clock()
        for key, value in entries.items():
            if not isinstance(value, dict):
                continue
            target = str(value.get("target_url") or "").strip()
            try:
                expires_at = float(value.get("expires_at") or 0)
                resolved_at = float(value.get("resolved_at") or 0)
            except (TypeError, ValueError):
                continue
            if len(key) != 64 or not target or expires_at <= now:
                continue
            self._entries[key] = {
                "target_url": target,
                "resolved_at": resolved_at,
                "expires_at": expires_at,
            }
        self._trim_locked()

    def _trim_locked(self) -> None:
        overflow = len(self._entries) - self.max_entries
        if overflow <= 0:
            return
        oldest = sorted(
            self._entries,
            key=lambda key: (
                float(self._entries[key].get("resolved_at") or 0), key,
            ),
        )
        for key in oldest[:overflow]:
            self._entries.pop(key, None)

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        payload = json.dumps(
            {"version": 1, "entries": self._entries},
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

    def get(self, source_url: str) -> Optional[str]:
        key = self._key(source_url)
        with self._lock:
            item = self._entries.get(key)
            if not item:
                return None
            if float(item.get("expires_at") or 0) <= self.clock():
                self._entries.pop(key, None)
                self._write_locked()
                return None
            return str(item["target_url"])

    def put(self, source_url: str, target_url: str) -> None:
        source = str(source_url or "").strip()
        target = str(target_url or "").strip()
        if not source or not target or source == target:
            return
        now = self.clock()
        with self._lock:
            self._entries[self._key(source)] = {
                "target_url": target,
                "resolved_at": now,
                "expires_at": now + self.ttl_seconds,
            }
            self._trim_locked()
            self._write_locked()

    def invalidate(self, source_url: str, target_url: str = "") -> bool:
        key = self._key(source_url)
        expected = str(target_url or "").strip()
        with self._lock:
            item = self._entries.get(key)
            if not item or (
                expected and str(item.get("target_url") or "") != expected
            ):
                return False
            self._entries.pop(key, None)
            self._write_locked()
            return True

    def count(self) -> int:
        with self._lock:
            now = self.clock()
            return sum(
                1 for item in self._entries.values()
                if float(item.get("expires_at") or 0) > now
            )
