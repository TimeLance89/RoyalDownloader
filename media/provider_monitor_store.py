"""Bounded, atomic Sentinel diagnostics and declarative repair journal."""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path


DEFAULT_CONFIG = {"enabled": True, "interval_hours": 12, "intensity": "standard", "auto_repair": True, "notify_changes": False}
MAX_HISTORY = 120
MAX_REPAIRS = 20
RETENTION_SECONDS = 30 * 86400


class ProviderMonitorStore:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.RLock()
        self.data = {"version": 1, "config": dict(DEFAULT_CONFIG), "providers": {}}
        try:
            if self.path.stat().st_size > 64_000_000:
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") == 1 and isinstance(raw.get("providers"), dict):
                self.data = raw
                config = raw.get("config") if isinstance(raw.get("config"), dict) else {}
                self.data["config"] = dict(DEFAULT_CONFIG)
                for key, default in DEFAULT_CONFIG.items():
                    item = config.get(key, default)
                    if type(item) is type(default) and (key != "interval_hours" or 1 <= item <= 168) and (key != "intensity" or item in {"light", "standard", "full"}):
                        self.data["config"][key] = item
                self.data["providers"] = {key: value for key, value in raw["providers"].items() if isinstance(value, dict)}
                for entry in self.data["providers"].values():
                    history = entry.get("history") if isinstance(entry.get("history"), list) else []
                    repairs = entry.get("repairs") if isinstance(entry.get("repairs"), list) else []
                    entry["history"] = [item for item in history if isinstance(item, dict) and isinstance(item.get("timestamp"), (int, float)) and item["timestamp"] >= self.clock() - RETENTION_SECONDS][-MAX_HISTORY:]
                    repairs = [item for item in repairs if isinstance(item, dict) and isinstance(item.get("id"), str)]
                    entry["repairs"] = [item for item in repairs[:-MAX_REPAIRS] if item["id"] == entry.get("active_repair")] + repairs[-MAX_REPAIRS:]
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _commit(self, data):
        previous = self.data
        self.data = data
        try:
            self._write()
        except Exception:
            self.data = previous
            raise

    def _commit_entry(self, provider, entry):
        self._commit({**self.data, "providers": {**self.data["providers"], provider: entry}})

    def entry(self, provider, fields=None):
        with self.lock:
            entry = self.data["providers"].get(provider, {})
            return copy.deepcopy(entry if fields is None else {key: entry[key] for key in fields if key in entry})

    def config(self):
        with self.lock:
            return dict(self.data["config"])

    def configure(self, values):
        if set(values) - set(DEFAULT_CONFIG):
            raise ValueError("Unbekannte Monitor-Einstellung")
        config = {**self.config(), **values}
        if not all(isinstance(config[key], bool) for key in ("enabled", "auto_repair", "notify_changes")):
            raise ValueError("Ungültige Monitor-Einstellung")
        if not isinstance(config["interval_hours"], int) or not 1 <= config["interval_hours"] <= 168:
            raise ValueError("Prüfintervall muss zwischen 1 und 168 Stunden liegen")
        if config["intensity"] not in {"light", "standard", "full"}:
            raise ValueError("Ungültige Prüftiefe")
        with self.lock:
            self._commit({**self.data, "config": config})
        return dict(config)

    def update(self, provider, **fields):
        with self.lock:
            entry = self.entry(provider)
            entry.update(copy.deepcopy(fields))
            self._commit_entry(provider, entry)

    def record(self, provider, event):
        with self.lock:
            entry = self.entry(provider)
            history = entry.setdefault("history", [])
            history.append({**copy.deepcopy(event), "timestamp": self.clock()})
            entry["history"] = [item for item in history if item["timestamp"] >= self.clock() - RETENTION_SECONDS][-MAX_HISTORY:]
            self._commit_entry(provider, entry)

    def add_repair(self, provider, repair):
        with self.lock:
            entry = self.entry(provider)
            repairs = entry.setdefault("repairs", [])
            repairs.append(copy.deepcopy(repair))
            active = entry.get("active_repair")
            entry["repairs"] = [item for item in repairs[:-MAX_REPAIRS] if item["id"] == active] + repairs[-MAX_REPAIRS:]
            self._commit_entry(provider, entry)
