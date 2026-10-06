"""Source discovery is shared, bounded, and never invents language evidence."""
import asyncio
import threading
from types import SimpleNamespace

from features.episode_source_probe import EpisodeSourceProbes
from providers.models import FilmpalastMovie, HosterInfo


def test_slow_source_does_not_erase_fast_results_and_overlapping_probes_are_shared():
    broker = EpisodeSourceProbes(workers=2)
    slow = threading.Event()
    started = threading.Event()
    calls = []
    movie = SimpleNamespace(url="fast")
    def lookup(provider):
        calls.append(provider)
        if provider == "slow":
            started.set()
            slow.wait(2)
            return []
        return [movie]
    try:
        sources, pending = broker.search("episode", ["slow", "fast"], lookup, timeout=.1)
        assert started.is_set()
        assert sources == [movie]
        assert pending is True
        assert broker.search("episode", ["slow", "fast"], lookup, timeout=0) == ([movie], True)
        assert sorted(calls) == ["fast", "slow"]
        slow.set()
        assert broker.search("episode", ["slow", "fast"], lookup, timeout=1) == ([movie], False)
    finally:
        slow.set()
        broker.close()


def test_missing_german_episode_searches_every_enabled_matching_source_and_preserves_queue_hints(monkeypatch):
    import server  # noqa: F401

    # The composition root must bind services before importing their facades.
    import api.api_discovery_router as discovery
    import api.api_library_router as library
    import application_services.download_lifecycle as lifecycle
    broker = EpisodeSourceProbes(workers=3)
    monkeypatch.setattr("features.episode_source_probe.episode_source_probes", broker)
    slug = "serienstream:exact-s02e04"
    active = ["serienstream", "huhu", "filmpalast", "moflix", "sflix"]
    runtime = SimpleNamespace(content_languages={"de"}, sto_lock=threading.RLock(),
        movie_source_cache={}, movie_source_cache_lock=threading.Lock(), series_cache={}, fallback_provider_errors={})
    monkeypatch.setattr(discovery, "state", runtime)
    monkeypatch.setattr(discovery, "provider_priority", lambda kind: active)
    monkeypatch.setattr(discovery, "provider_for_value", lambda value: "serienstream")
    monkeypatch.setattr(discovery, "provider_supports_languages", lambda provider, languages: provider != "sflix")
    monkeypatch.setattr(discovery, "get_sto_scraper", lambda: SimpleNamespace(get_movie=lambda value: None))
    monkeypatch.setattr(library, "record_watchlist_episode_languages", lambda values: None)
    calls = []
    def fallback(title, season, episode, **options):
        allowed = set(active) - options["excluded_providers"]
        assert len(allowed) == 1
        provider = allowed.pop()
        calls.append(provider)
        assert (title, season, episode) == ("Exact Show", 2, 4)
        assert options["tmdb_id"] == "123"
        assert options["source_slug"] == slug
        if provider == "moflix":
            return []
        return [FilmpalastMovie("Exact Show S02E04", f"https://{provider}.test/episode", provider=provider,
            hosters=[HosterInfo("VOE", "https://stream.test/file", "de" if provider == "huhu" else "en")])]
    monkeypatch.setattr(lifecycle, "find_episode_fallbacks", fallback)
    body = discovery.SeriesEpisodeLanguagesBody(provider="serienstream", slugs=[slug], title="Exact Show", tmdb_id=123)
    try:
        result = asyncio.run(discovery.api_series_episode_languages(body))
        assert sorted(calls) == ["filmpalast", "huhu", "moflix"]
        assert result["available"] == {slug: True}
        assert result["languages"] == {slug: ["de"]}
        assert result["source_providers"] == {slug: ["huhu"]}
        sources = runtime.movie_source_cache[slug]
        assert sources[0].title == "Exact Show S02E04"
        assert sources[0].url == slug
        assert [source.provider for source in sources[1:]] == ["huhu"]
        asyncio.run(discovery.api_series_episode_languages(body))
        assert len(calls) == 3, "completed source searches are shared with retries"
    finally:
        broker.close()


def test_failed_source_retries_without_repeating_completed_sources(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("features.episode_source_probe.time.monotonic", lambda: clock[0])
    broker = EpisodeSourceProbes(workers=2)
    calls = []
    recovered = SimpleNamespace(url="recovered")
    fast = SimpleNamespace(url="fast")
    def lookup(provider):
        calls.append(provider)
        if provider == "failed" and clock[0] < 105:
            raise RuntimeError("temporary provider outage")
        return [recovered if provider == "failed" else fast]
    try:
        assert broker.search("episode", ["failed", "fast"], lookup, timeout=1) == ([fast], True)
        assert broker.search("episode", ["failed", "fast"], lookup, timeout=0) == ([fast], True)
        clock[0] = 106
        assert broker.search("episode", ["failed", "fast"], lookup, timeout=1) == ([recovered, fast], False)
        assert calls.count("failed") == 2
        assert calls.count("fast") == 1
    finally:
        broker.close()
