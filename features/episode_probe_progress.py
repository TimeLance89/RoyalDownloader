"""Bounded, short-lived progress snapshots for episode language requests."""
import threading
import time


class EpisodeProbeProgress:
    def __init__(self, capacity=128, ttl=180):
        self._lock = threading.Lock()
        self._entries = {}
        self._capacity = capacity
        self._ttl = ttl

    def start(self, probe_id):
        if not probe_id:
            return
        with self._lock:
            now = time.monotonic()
            self._entries = {key: value for key, value in self._entries.items() if now - value[0] < self._ttl}
            if len(self._entries) >= self._capacity:
                self._entries.pop(next(iter(self._entries)))
            self._entries[probe_id] = (now, {})

    def update(self, probe_id, slug, provider, status, *, future=None):
        with self._lock:
            entry = self._entries.get(probe_id)
            if entry:
                entry[1][(slug, provider)] = (status, future)

    def snapshot(self, probe_id):
        with self._lock:
            entry = self._entries.get(probe_id)
            if not entry or time.monotonic() - entry[0] >= self._ttl:
                return []
            rows = list(entry[1].items())
        result = []
        for (slug, provider), (status, future) in rows:
            if future is not None:
                if not future.done():
                    status = ("checking" if status == "checking" else "searching") if future.running() else "waiting"
                elif future.exception() is not None:
                    status = "retry"
                else:
                    status = "checked" if future.result() else "no_match"
            result.append({"slug": slug, "provider": provider, "status": status})
        return result


probe_progress = EpisodeProbeProgress()
