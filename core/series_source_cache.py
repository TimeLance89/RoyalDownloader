"""Source freshness is independent of retaining a usable offline snapshot."""
from core.runtime_cache import BoundedTTLCache


class SeriesSourceCache(BoundedTTLCache):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._retry_after = {}

    def __setitem__(self, key, value):
        with self._lock:
            existing = self._entries.get(key)
            if existing and existing[1] is value:
                return  # Reusing a snapshot is not a new source read.
            super().__setitem__(key, value)
            self._retry_after.pop(key, None)

    def needs_refresh(self, key):
        with self._lock:
            record = self._entries.get(key)
            now = self._clock()
            if now < self._retry_after.get(key, 0):
                return False
            if record is None:
                return True
            expires, series = record
            interval = 60 if any(ep.release_label or ep.release_at for ep in series.all_episodes) else 300
            return now - (expires - self.ttl_seconds) >= interval

    def refresh_failed(self, key):
        with self._lock:
            self._retry_after[key] = self._clock() + 60
            while len(self._retry_after) > self.max_entries:
                self._retry_after.pop(next(iter(self._retry_after)))

    def clear(self):
        with self._lock:
            super().clear()
            self._retry_after.clear()
