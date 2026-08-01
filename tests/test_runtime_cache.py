from runtime_cache import BoundedTTLCache


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_cache_evicts_deterministic_lru_entry():
    cache = BoundedTTLCache("test", max_entries=2, ttl_seconds=60)
    cache["first"] = 1
    cache["second"] = 2
    assert cache["first"] == 1
    cache["third"] = 3

    assert list(cache) == ["first", "third"]
    assert cache.diagnostics()["evictions"] == 1


def test_cache_periodically_expires_never_revisited_entries():
    clock = Clock()
    cache = BoundedTTLCache(
        "test", max_entries=4, ttl_seconds=10, clock=clock,
    )
    cache["old"] = 1
    clock.now = 11

    assert cache.cleanup() == {"expired": 1, "evicted": 0}
    assert len(cache) == 0
    assert cache.diagnostics()["expirations"] == 1


def test_pinned_entries_survive_then_become_evictable():
    pinned = {"active"}
    cache = BoundedTTLCache(
        "test",
        max_entries=2,
        ttl_seconds=60,
        is_pinned=pinned.__contains__,
    )
    cache["active"] = 1
    cache["old"] = 2
    cache["new"] = 3
    assert list(cache) == ["active", "new"]

    pinned.clear()
    cache["newer"] = 4
    assert len(cache) == 2
    assert "active" not in cache


def test_each_runtime_cache_enforces_its_configured_limit(monkeypatch):
    import server

    monkeypatch.setattr(server.state, "watchlist", [])
    monkeypatch.setattr(server.state, "movie_subscriptions", [])
    monkeypatch.setattr(server.state, "picked", set())
    for cache in server.state.runtime_caches:
        cache.clear()
        for index in range(cache.max_entries + 3):
            cache[f"key-{index}"] = index
        assert len(cache) == cache.max_entries
        assert cache.diagnostics()["evictions"] >= 3
