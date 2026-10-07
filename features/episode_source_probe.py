"""Shared, bounded background episode searches across enabled series sources."""
import threading
import time
from concurrent.futures import wait

from features.episode_probe_scheduler import ProviderProbeScheduler
from providers.catalog import PROVIDER_CATALOG

# Serialize a provider's catalog miss so overlapping episodes share its cache.
catalog_probe_locks = {provider: threading.RLock() for provider in PROVIDER_CATALOG}


class EpisodeSourceProbes:
    def __init__(self, *, workers=4, ttl=60, capacity=32):
        self._pool = ProviderProbeScheduler(workers, "episode-sources")
        self._lock = threading.Lock()
        self._entries = {}
        self._ttl = ttl
        self._capacity = capacity

    def search(self, key, providers, lookup, *, timeout=6, on_jobs=None, retry_unmatched=None):
        now = time.monotonic()
        with self._lock:
            for old_key, (created, futures) in list(self._entries.items()):
                if all(future.done() for future in futures.values()) and now - max((getattr(future, "probe_finished_at", created) for future in futures.values()), default=created) >= self._ttl:
                    del self._entries[old_key]
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self._capacity:
                    completed = next((k for k, (_, jobs) in self._entries.items() if all(f.done() for f in jobs.values())), None)
                    if completed is None:
                        return [], True
                    del self._entries[completed]
                futures = {provider: self._pool.submit(provider, lambda provider=provider: lookup(provider)) for provider in providers}
                self._entries[key] = (now, futures)
            else:
                futures = entry[1]
                if now - entry[0] >= (1 if retry_unmatched else 5):
                    failed = [provider for provider, future in futures.items() if future.done() and (future.exception() is not None
                        or (retry_unmatched is not None and not retry_unmatched(future.result())))]
                    if failed:
                        futures = dict(futures)
                        for provider in failed:
                            futures[provider] = self._pool.submit(provider, lambda provider=provider: lookup(provider))
                        self._entries[key] = (now, futures)
        if on_jobs is not None:
            on_jobs(futures)
        if futures:
            wait(futures.values(), timeout=max(0, timeout))
        sources, seen, pending = [], set(), False
        for provider in providers:
            future = futures.get(provider)
            if future is None or not future.done():
                pending = True
                continue
            try:
                found = future.result()
            except Exception:  # noqa: BLE001 -- independent provider boundary
                # A provider failure remains retryable and does not erase hits.
                pending = True
                continue
            for source in found:
                if source.url not in seen:
                    seen.add(source.url)
                    sources.append(source)
        return sources, pending

    def close(self):
        self._pool.close()


episode_source_probes = EpisodeSourceProbes()
