"""Thread-safe bounded TTL/LRU caches for long-running server state."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, MutableMapping
from typing import Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


class BoundedTTLCache(MutableMapping[K, V], Generic[K, V]):
    """Dictionary-compatible cache with deterministic TTL and LRU eviction.

    ``is_pinned`` is evaluated only for eviction. It keeps active queue or
    watchlist data available while still bounding all ordinary cache entries.
    """

    def __init__(
        self,
        name: str,
        *,
        max_entries: int,
        ttl_seconds: float,
        is_pinned: Callable[[K], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError("max_entries and ttl_seconds must be positive")
        self.name = name
        self.max_entries = int(max_entries)
        self.ttl_seconds = float(ttl_seconds)
        self._is_pinned = is_pinned or (lambda _key: False)
        self._clock = clock
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def _pinned(self, key: K) -> bool:
        try:
            return bool(self._is_pinned(key))
        except Exception:
            return False

    def _prune_locked(self, now: float) -> int:
        expired = [
            key
            for key, (expires_at, _value) in self._entries.items()
            if expires_at <= now and not self._pinned(key)
        ]
        for key in expired:
            self._entries.pop(key, None)
        self._expirations += len(expired)
        return len(expired)

    def _enforce_limit_locked(self) -> int:
        removed = 0
        while len(self._entries) > self.max_entries:
            victim = next(
                (key for key in self._entries if not self._pinned(key)),
                None,
            )
            if victim is None:
                # Pinned entries may temporarily exceed the limit. They become
                # eligible on the next maintenance pass once no longer active.
                break
            self._entries.pop(victim, None)
            removed += 1
        self._evictions += removed
        return removed

    def cleanup(self) -> dict[str, int]:
        with self._lock:
            expired = self._prune_locked(self._clock())
            evicted = self._enforce_limit_locked()
            return {"expired": expired, "evicted": evicted}

    def diagnostics(self) -> dict[str, int | float | str]:
        self.cleanup()
        with self._lock:
            return {
                "name": self.name,
                "size": len(self._entries),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "expirations": self._expirations,
            }

    def __getitem__(self, key: K) -> V:
        with self._lock:
            now = self._clock()
            record = self._entries.get(key)
            if record is None:
                self._misses += 1
                raise KeyError(key)
            expires_at, value = record
            if expires_at <= now and not self._pinned(key):
                self._entries.pop(key, None)
                self._misses += 1
                self._expirations += 1
                raise KeyError(key)
            self._entries.move_to_end(key)
            self._hits += 1
            return value

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            self._entries[key] = (now + self.ttl_seconds, value)
            self._entries.move_to_end(key)
            self._enforce_limit_locked()

    def __delitem__(self, key: K) -> None:
        with self._lock:
            del self._entries[key]

    def __iter__(self) -> Iterator[K]:
        self.cleanup()
        with self._lock:
            return iter(tuple(self._entries))

    def __len__(self) -> int:
        self.cleanup()
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

