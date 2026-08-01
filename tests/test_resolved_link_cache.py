import json

from resolved_link_cache import ResolvedLinkCache


class Clock:
    def __init__(self, value=1000.0):
        self.value = float(value)

    def __call__(self):
        return self.value


def test_cache_persists_atomically_without_source_token(tmp_path):
    clock = Clock()
    path = tmp_path / "resolved-links.json"
    source = "https://serienstream.to/r?t=secret-token"
    target = "https://hoster.invalid/embed/episode"
    cache = ResolvedLinkCache(path, ttl_seconds=60, clock=clock)
    cache.put(source, target)

    payload = path.read_text(encoding="utf-8")
    assert source not in payload
    assert target in payload
    assert not list(tmp_path.glob("*.tmp"))
    assert ResolvedLinkCache(path, ttl_seconds=60, clock=clock).get(source) == target


def test_expired_link_is_not_restored_or_returned(tmp_path):
    clock = Clock()
    path = tmp_path / "resolved-links.json"
    source = "https://serienstream.to/r?t=expired"
    cache = ResolvedLinkCache(path, ttl_seconds=10, clock=clock)
    cache.put(source, "https://hoster.invalid/embed/expired")
    clock.value += 11

    assert cache.get(source) is None
    assert ResolvedLinkCache(path, ttl_seconds=10, clock=clock).count() == 0


def test_cache_keeps_only_configured_number_of_newest_entries(tmp_path):
    clock = Clock()
    path = tmp_path / "resolved-links.json"
    cache = ResolvedLinkCache(path, ttl_seconds=60, max_entries=2, clock=clock)
    for index in range(3):
        clock.value += 1
        cache.put(f"source-{index}", f"target-{index}")

    assert cache.count() == 2
    assert cache.get("source-0") is None
    assert cache.get("source-1") == "target-1"
    assert cache.get("source-2") == "target-2"
    assert len(json.loads(path.read_text(encoding="utf-8"))["entries"]) == 2


def test_invalidate_only_removes_matching_target(tmp_path):
    cache = ResolvedLinkCache(tmp_path / "resolved-links.json", ttl_seconds=60)
    cache.put("source", "target-new")
    assert not cache.invalidate("source", "target-old")
    assert cache.get("source") == "target-new"
    assert cache.invalidate("source", "target-new")
    assert cache.get("source") is None
