"""Bounded, atomic Sentinel diagnostics and declarative repair journal."""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path


DEFAULT_CONFIG = {"enabled": True, "interval_hours": 12, "intensity": "standard", "auto_repair": True, "notify_changes": False}
MAX_HISTORY = 120
MAX_REPAIRS = 20
RETENTION_SECONDS = 30 * 86400


class ProviderMonitorStore:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.RLock()
        self._disk_lock = threading.Lock()
        self._revision = 0
        self._dirty = False
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sentinel-state")
        self._flush_task = None
        self._last_flush_started = float("-inf")
        self.last_write_error = False
        self.data = {"version": 1, "config": dict(DEFAULT_CONFIG), "providers": {}, "hosters": {}}
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
                self.data["hosters"] = {key: value for key, value in raw.get("hosters", {}).items() if isinstance(value, dict)} if isinstance(raw.get("hosters", {}), dict) else {}
                for entry in [*self.data["providers"].values(), *self.data["hosters"].values()]:
                    history = entry.get("history") if isinstance(entry.get("history"), list) else []
                    repairs = entry.get("repairs") if isinstance(entry.get("repairs"), list) else []
                    entry["history"] = [item for item in history if isinstance(item, dict) and isinstance(item.get("timestamp"), (int, float)) and item["timestamp"] >= self.clock() - RETENTION_SECONDS][-MAX_HISTORY:]
                    repairs = [item for item in repairs if isinstance(item, dict) and isinstance(item.get("id"), str)]
                    entry["repairs"] = [item for item in repairs[:-MAX_REPAIRS] if item["id"] == entry.get("active_repair")] + repairs[-MAX_REPAIRS:]
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _write(self):
        with self._disk_lock:
            self._write_data(self.data)

    def _write_data(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _commit(self, data, *, deferred=False):
        previous = self.data
        was_dirty = self._dirty
        self.data = data
        self._revision += 1
        if deferred:
            self._dirty = True
            return
        try:
            self._write()
        except Exception:
            self.data = previous
            self._revision += 1
            self._dirty = was_dirty
            self.last_write_error = True
            raise
        self._dirty = False
        self.last_write_error = False

    def _commit_entry(self, provider, entry, namespace="providers", *, deferred=False):
        entry["revision"] = self.data[namespace].get(provider, {}).get("revision", 0) + 1
        self._commit({**self.data, namespace: {**self.data[namespace], provider: entry}}, deferred=deferred)

    def flush(self):
        """One immutable snapshot; never hold the state lock during disk I/O."""
        with self.lock:
            if not self._dirty:
                return True
            snapshot, revision = self.data, self._revision
        try:
            with self._disk_lock:
                # A durable commit may have overtaken this queued snapshot.
                if revision != self._revision:
                    return False
                self._write_data(snapshot)
        except Exception:
            with self.lock:
                if revision == self._revision:
                    self.last_write_error = True
            return False
        with self.lock:
            if revision == self._revision:
                self._dirty = False
                self.last_write_error = False
        return True

    def flush_background(self, *, force=False):
        with self.lock:
            due = force or time.monotonic() - self._last_flush_started >= 30
            if due and self._dirty and (self._flush_task is None or self._flush_task.done()):
                if self._writer is None:
                    self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sentinel-state")
                self._last_flush_started = time.monotonic()
                self._flush_task = self._writer.submit(self.flush)
            return self._flush_task

    def close(self):
        # A blocked durable write must not hang application shutdown.
        if not self.lock.acquire(timeout=.05):
            return
        try:
            task = self.flush_background(force=True)
        finally:
            self.lock.release()
        if task is not None:
            try:
                task.result(timeout=.2)
            except (TimeoutError, OSError):
                pass
        if not self.lock.acquire(timeout=.05):
            return
        try:
            writer, self._writer = self._writer, None
        finally:
            self.lock.release()
        if writer is not None:
            writer.shutdown(wait=False)

    def persistence_status(self):
        with self.lock:
            return {"pending": self._dirty, "write_failed": self.last_write_error}

    def summary_entry(self, provider, *, namespace="providers"):
        with self.lock:
            entry = self.data[namespace].get(provider, {})
            result = copy.deepcopy({k: v for k, v in entry.items() if k not in {"history", "repairs", "canaries", "fingerprints"}})
            history = entry.get("history", [])
            probes = [h for h in history if h.get("event") == "probe" and self.clock() - h["timestamp"] < 86400]
            result.update(history=[], repairs=[], history_count=len(history), repairs_count=len(entry.get("repairs", [])),
                          observed_hosters=sorted({str(name) for h in history for name in h.get("hoster_names", [])}),
                          probe_count=len(probes), probe_failures=sum(h.get("diagnosis") != "healthy" for h in probes),
                          probe_duration=sum(h.get("duration_ms", 0) for h in probes))
            return result

    def remove_hoster(self, key):
        with self.lock:
            row = self.data["hosters"].get(key, {})
            if row.get("active_repair"):
                return False
            self._commit({**self.data, "hosters": {k: v for k, v in self.data["hosters"].items() if k != key}}, deferred=True)
            return True

    def update_many(self, changes):
        """Durably accept a whole manual schedule with one atomic write."""
        with self.lock:
            data = {**self.data, "providers": dict(self.data["providers"]), "hosters": dict(self.data["hosters"])}
            for namespace, key, fields in changes:
                previous = data[namespace].get(key, {})
                data[namespace][key] = {**previous, **copy.deepcopy(fields), "revision": previous.get("revision", 0) + 1}
            self._commit(data)

    def entry(self, provider, fields=None, *, namespace="providers"):
        with self.lock:
            entry = self.data[namespace].get(provider, {})
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

    def update(self, provider, *, namespace="providers", deferred=False, **fields):
        with self.lock:
            entry = self.entry(provider, namespace=namespace)
            if all(entry.get(key) == value for key, value in fields.items()):
                return
            entry.update(copy.deepcopy(fields))
            self._commit_entry(provider, entry, namespace, deferred=deferred)

    def record(self, provider, event, *, namespace="providers", deferred=False):
        with self.lock:
            entry = self.entry(provider, namespace=namespace)
            history = entry.setdefault("history", [])
            history.append({**copy.deepcopy(event), "timestamp": self.clock()})
            entry["history"] = [item for item in history if item["timestamp"] >= self.clock() - RETENTION_SECONDS][-MAX_HISTORY:]
            self._commit_entry(provider, entry, namespace, deferred=deferred)

    def add_repair(self, provider, repair, *, namespace="providers"):
        with self.lock:
            entry = self.entry(provider, namespace=namespace)
            repairs = entry.setdefault("repairs", [])
            repairs.append(copy.deepcopy(repair))
            active = entry.get("active_repair")
            entry["repairs"] = [item for item in repairs[:-MAX_REPAIRS] if item["id"] == active] + repairs[-MAX_REPAIRS:]
            self._commit_entry(provider, entry, namespace)


class HosterStore:
    """Namespace view of the same atomic store, lock and retention policy."""
    def __init__(self, store):
        self.store, self.lock, self.clock = store, store.lock, store.clock

    def entry(self, key, fields=None):
        return self.store.entry(key, fields, namespace="hosters")

    def summary_entry(self, key):
        return self.store.summary_entry(key, namespace="hosters")

    def update(self, key, **fields):
        return self.store.update(key, namespace="hosters", **fields)

    def record(self, key, event, *, deferred=False):
        return self.store.record(key, event, namespace="hosters", deferred=deferred)

    def add_repair(self, key, repair):
        return self.store.add_repair(key, repair, namespace="hosters")

    def config(self):
        return self.store.config()
