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
    # The composition root must bind services before importing their facades.
    import api.api_discovery_router as discovery
    import api.api_library_router as library
    import application_services.download_lifecycle as lifecycle
    import server  # noqa: F401
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


def test_retry_rechecks_negative_sources_but_preserves_hits_and_running_jobs(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("features.episode_source_probe.time.monotonic", lambda: clock[0])
    broker = EpisodeSourceProbes(workers=3)
    slow = threading.Event()
    calls = []
    fast = SimpleNamespace(url="fast")
    recovered = SimpleNamespace(url="recovered")
    def lookup(provider):
        calls.append(provider)
        if provider == "slow":
            slow.wait(2)
            return []
        if provider == "negative":
            return [] if clock[0] == 100 else [recovered]
        return [fast]
    try:
        assert broker.search("episode", ["negative", "fast", "slow"], lookup, timeout=.1) == ([fast], True)
        clock[0] = 102
        assert broker.search("episode", ["negative", "fast", "slow"], lookup, timeout=.1, retry_unmatched=bool) == ([recovered, fast], True)
        assert calls.count("negative") == 2
        assert calls.count("fast") == calls.count("slow") == 1
    finally:
        slow.set()
        broker.close()


def test_retry_discards_only_this_series_negative_cache_and_finds_german_source(monkeypatch):
    import api.api_discovery_router as discovery
    import api.api_library_router as library
    import application_services.download_lifecycle as lifecycle
    import server  # noqa: F401
    from application_services.media_identity import _norm_title
    clock = [100.0]
    monkeypatch.setattr("features.episode_source_probe.time.monotonic", lambda: clock[0])
    broker = EpisodeSourceProbes(workers=1)
    monkeypatch.setattr("features.episode_source_probe.episode_source_probes", broker)
    slug = "serienstream:exact-s02e04"
    negative_key = "filmpalast:" + _norm_title("Exact Show")
    unrelated = "filmpalast:" + _norm_title("Other Show")
    runtime = SimpleNamespace(content_languages={"de"}, series_cache={},
        movie_source_cache={}, movie_source_cache_lock=threading.Lock(), fallback_provider_errors={},
        fallback_series_cache_lock=threading.Lock(), fallback_series_cache={negative_key: (999, None), unrelated: (999, None)})
    monkeypatch.setattr(discovery, "state", runtime)
    monkeypatch.setattr(discovery, "provider_priority", lambda kind: ["serienstream", "filmpalast"])
    monkeypatch.setattr(discovery, "provider_for_value", lambda value: "serienstream")
    monkeypatch.setattr(discovery, "provider_supports_languages", lambda *args: True)
    monkeypatch.setattr(discovery, "episode_languages_for_slug", lambda *args: ["en"])
    monkeypatch.setattr(library, "record_watchlist_episode_languages", lambda values: None)
    calls = []
    def lookup(*args, **options):
        calls.append(options)
        if negative_key in runtime.fallback_series_cache:
            return []
        return [FilmpalastMovie("Exact Show S02E04", "https://fallback.test/episode", provider="filmpalast",
            hosters=[HosterInfo("VOE", "https://stream.test/file", "de")])]
    monkeypatch.setattr(lifecycle, "find_episode_fallbacks", lookup)
    try:
        first = asyncio.run(discovery.api_series_episode_languages(discovery.SeriesEpisodeLanguagesBody(
            provider="serienstream", slugs=[slug], title="Exact Show")))
        assert first["available"][slug] is False
        clock[0] = 102
        second = asyncio.run(discovery.api_series_episode_languages(discovery.SeriesEpisodeLanguagesBody(
            provider="serienstream", slugs=[slug], title="Exact Show", attempt=1)))
        assert second["available"][slug] is True
        assert second["source_providers"][slug] == ["filmpalast"]
        assert unrelated in runtime.fallback_series_cache
        assert len(calls) == 2
    finally:
        broker.close()


def test_many_slow_provider_episodes_do_not_starve_other_providers():
    broker = EpisodeSourceProbes(workers=2)
    release = threading.Event()
    fast = SimpleNamespace(url="fast")
    calls = []
    def lookup(provider):
        calls.append(provider)
        if provider == "slow":
            release.wait(2)
            return []
        return [fast]
    try:
        for index in range(5):
            sources, pending = broker.search(f"episode-{index}", ["slow", "fast"], lookup, timeout=.1)
            assert sources == [fast], "healthy source keeps making progress while slow episodes are queued"
            assert pending is True
        assert calls.count("slow") == 1
        assert calls.count("fast") == 5
    finally:
        release.set()
        broker.close()


def test_late_source_results_remain_available_to_next_request(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("features.episode_source_probe.time.monotonic", lambda: clock[0])
    broker = EpisodeSourceProbes(ttl=60)
    release, started = threading.Event(), threading.Event()
    jobs, calls = {}, []
    movie = SimpleNamespace(url="late")
    def lookup(provider):
        calls.append(provider)
        started.set()
        release.wait(2)
        return [movie]
    try:
        assert broker.search("episode", ["slow"], lookup, timeout=.01, on_jobs=jobs.update) == ([], True)
        assert started.wait(1)
        clock[0] = 200.0
        release.set()
        assert jobs["slow"].result(timeout=1) == [movie]
        clock[0] = 201.0
        assert broker.search("episode", ["slow"], lookup, timeout=0) == ([movie], False)
        assert calls == ["slow"]
    finally:
        release.set()
        broker.close()
