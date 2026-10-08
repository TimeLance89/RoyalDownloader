"""Shared movie probes: bounded admission, retained late answers and explicit incompleteness."""
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from concurrent.futures import FIRST_COMPLETED, wait

from features.episode_probe_scheduler import ProviderProbeScheduler


class MovieProbeIncomplete(RuntimeError):
    """The attempted sources did not establish a definitive negative result."""


class _CacheIdentity:
    """Retain the cache object so recycled object IDs cannot reuse another probe."""
    def __init__(self, cache):
        self.cache = cache

    def __hash__(self):
        return id(self.cache)

    def __eq__(self, other):
        return isinstance(other, _CacheIdentity) and self.cache is other.cache


def movie_probe_context(state):
    return (_CacheIdentity(state.fp_movies), tuple(sorted(getattr(state, "content_languages", ()))),
            tuple(getattr(state, "provider_enabled", {}).get("movies", ())),
            tuple(getattr(state, "provider_priorities", {}).get("movies", ())))


class ProbeResults(list):
    def __init__(self, values=(), *, incomplete=False):
        super().__init__(values)
        self.incomplete = incomplete


_INTERACTIVE = threading.local()


def interactive_movie_probe():
    return bool(getattr(_INTERACTIVE, "active", False))


@contextmanager
def movie_probe_scope():
    previous = interactive_movie_probe()
    _INTERACTIVE.active = True
    try:
        yield
    finally:
        _INTERACTIVE.active = previous


class MovieProbePool:
    def __init__(self, *, workers=8, capacity=512, pending_capacity=48,
                 positive_ttl=180, negative_ttl=30, error_ttl=5, ttl_for=None,
                 clock=time.monotonic, name="movie-probes"):
        self._pool = ProviderProbeScheduler(workers, name)
        self._lock = threading.RLock()
        self._entries = OrderedDict()
        self._capacity = capacity
        self._pending_capacity = pending_capacity
        self._positive_ttl = positive_ttl
        self._negative_ttl = negative_ttl
        self._error_ttl = error_ttl
        self._ttl_for = ttl_for
        self._clock = clock

    def _fresh(self, future, now):
        if not future.done():
            return True
        timing = future.movie_probe_timing
        if future.cancelled() or future.exception() is not None:
            ttl = self._error_ttl
        else:
            value = future.result()
            ttl = timing.get("ttl")
            if ttl is None:
                ttl = self._ttl_for(value) if self._ttl_for else self._positive_ttl if value else self._negative_ttl
        return now - timing["finished"] < ttl

    def submit(self, key, provider, lookup):
        with self._lock:
            now = self._clock()
            for old, future in list(self._entries.items()):
                if not self._fresh(future, now):
                    del self._entries[old]
            future = self._entries.get(key)
            if future is not None:
                self._entries.move_to_end(key)
                return future
            if sum(not item.done() for item in self._entries.values()) >= self._pending_capacity:
                return None
            while len(self._entries) >= self._capacity:
                completed = next((old for old, item in self._entries.items() if item.done()), None)
                if completed is None:
                    return None
                del self._entries[completed]
            timing = {"finished": now}

            def measured():
                try:
                    value = lookup()
                    if self._ttl_for:
                        timing["ttl"] = self._ttl_for(value)
                    return value
                finally:
                    # Record expiry before Future.set_result wakes its observers.
                    timing["finished"] = self._clock()

            future = self._pool.submit(provider, measured)
            future.movie_probe_timing = timing
            self._entries[key] = future
            return future

    def collect(self, jobs, *, context, timeout, early=True):
        futures = {key: self.submit((context, key), provider, lookup) for key, provider, lookup in jobs}
        deadline = self._clock() + max(0, timeout)
        while True:
            values, pending, incomplete = [], [], False
            for key, future in futures.items():
                if future is None:
                    incomplete = True
                elif not future.done():
                    pending.append(future)
                elif future.cancelled() or future.exception() is not None:
                    incomplete = True
                else:
                    values.append((key, future.result()))
            remaining = deadline - self._clock()
            if not pending or remaining <= 0 or (early and any(value for _, value in values)):
                return ProbeResults(values, incomplete=incomplete or bool(pending))
            wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)

    def close(self):
        self._pool.close()


movie_source_probes = MovieProbePool()
movie_language_probes = MovieProbePool(workers=2, pending_capacity=8,
    ttl_for=lambda sources: 1 if any(getattr(source, "_movie_availability_incomplete", False)
                                   for source in sources or []) else 180 if sources else 30,
    name="movie-languages")
movie_detail_probes = MovieProbePool(workers=4, capacity=256, pending_capacity=16,
    ttl_for=lambda payload: 30 if payload is None else
        min(180, max(0, payload.get("availability", {}).get("expires_at", time.time() + 180) - time.time()))
        if payload.get("availability", {}).get("complete", True) else 1,
    name="movie-availability")
