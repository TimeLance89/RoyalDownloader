"""Shared, bounded background episode searches across enabled series sources."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait


class EpisodeSourceProbes:
    def __init__(self, *, workers=4, ttl=60, capacity=32):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="episode-sources")
        self._lock = threading.Lock()
        self._entries = {}
        self._ttl = ttl
        self._capacity = capacity

    def search(self, key, providers, lookup, *, timeout=6):
        now = time.monotonic()
        with self._lock:
            for old_key, (created, futures) in list(self._entries.items()):
                if now - created >= self._ttl and all(future.done() for future in futures.values()):
                    del self._entries[old_key]
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self._capacity:
                    completed = next((k for k, (_, jobs) in self._entries.items() if all(f.done() for f in jobs.values())), None)
                    if completed is None:
                        return [], True
                    del self._entries[completed]
                futures = {provider: self._pool.submit(lookup, provider) for provider in providers}
                self._entries[key] = (now, futures)
            else:
                futures = entry[1]
                if now - entry[0] >= 5:
                    failed = [provider for provider, future in futures.items() if future.done() and future.exception() is not None]
                    if failed:
                        futures = dict(futures)
                        for provider in failed:
                            futures[provider] = self._pool.submit(lookup, provider)
                        self._entries[key] = (now, futures)
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
        self._pool.shutdown(wait=True, cancel_futures=True)


episode_source_probes = EpisodeSourceProbes()
