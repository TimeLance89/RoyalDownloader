"""Share bounded primary-language requests without blocking HTTP workers."""
import threading
import time

from features.episode_language_policy import LANGUAGE_EVIDENCE_TTL
from features.episode_probe_scheduler import ProviderProbeScheduler


class EpisodeLanguageProbes:
    def __init__(self, workers=4, capacity=128, ttl=60):
        self._pool = ProviderProbeScheduler(workers, "episode-languages")
        self._lock = threading.Lock()
        self._entries = {}
        self._releases = {}
        self._capacity = capacity
        self._ttl = ttl

    def submit(self, key, lookup, *, retry_unmatched=None, provider="primary"):
        with self._lock:
            now = time.monotonic()
            for old_key, (created, future) in list(self._entries.items()):
                if future.done() and now - getattr(future, "probe_finished_at", created) >= self._ttl:
                    del self._entries[old_key]
            entry = self._entries.get(key)
            if entry:
                future = entry[1]
                if not future.done():
                    return future
                if future.exception() is None and future.result() and (retry_unmatched is None or retry_unmatched(future.result())):
                    return future
            elif len(self._entries) >= self._capacity:
                completed = next((old_key for old_key, (_, future) in self._entries.items() if future.done()), None)
                if completed is None:
                    return None
                del self._entries[completed]
            future = self._pool.submit(provider, lookup)
            self._entries[key] = (now, future)
            return future

    def record_release(self, slug, languages):
        with self._lock:
            now = time.monotonic()
            self._releases.pop(slug, None)
            if len(self._releases) >= self._capacity:
                self._releases.pop(next(iter(self._releases)))
            self._releases[slug] = (now, frozenset(languages))

    def confirmed_languages(self, slug):
        with self._lock:
            release = self._releases.get(slug)
            if release and time.monotonic() - release[0] < LANGUAGE_EVIDENCE_TTL:
                return release[1]
            self._releases.pop(slug, None)
            return frozenset()

    def close(self):
        self._pool.close()


language_probes = EpisodeLanguageProbes()
