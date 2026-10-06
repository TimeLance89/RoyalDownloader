import threading
from types import SimpleNamespace

from features.episode_language_probe import EpisodeLanguageProbes


def test_primary_language_requests_share_inflight_work_and_retry_only_unmatched_results():
    broker = EpisodeLanguageProbes(workers=2)
    slow = threading.Event()
    calls = []
    def lookup():
        calls.append("lookup")
        slow.wait(2)
        return ["en"]
    try:
        first = broker.submit("episode", lookup)
        assert broker.submit("episode", lookup, retry_unmatched=lambda languages: "de" in languages) is first
        slow.set()
        assert first.result(timeout=1) == ["en"]
        retry = broker.submit("episode", lambda: ["de"], retry_unmatched=lambda languages: "de" in languages)
        assert retry is not first
        assert retry.result(timeout=1) == ["de"]
        assert broker.submit("episode", lambda: ["en"]) is retry
        assert calls == ["lookup"]
    finally:
        slow.set()
        broker.close()


def test_slow_primary_returns_pending_within_budget_and_retry_collects_completed_work(monkeypatch):
    import asyncio
    import time

    import api.api_discovery_router as discovery
    import api.api_library_router as library
    import server  # noqa: F401
    broker = EpisodeLanguageProbes(workers=1)
    monkeypatch.setattr("features.episode_language_probe.language_probes", broker)
    monkeypatch.setattr(discovery, "state", SimpleNamespace(content_languages={"de"}, series_cache={}))
    monkeypatch.setattr(discovery, "provider_priority", lambda kind: ["serienstream"])
    monkeypatch.setattr(discovery, "provider_for_value", lambda slug: "serienstream")
    monkeypatch.setattr(discovery, "EPISODE_PRIMARY_WAIT_SECONDS", .05)
    monkeypatch.setattr(discovery, "EPISODE_PROBE_BUDGET_SECONDS", .1)
    monkeypatch.setattr(library, "record_watchlist_episode_languages", lambda values: None)
    release, started = threading.Event(), threading.Event()
    calls = []
    def lookup(*args):
        calls.append(args)
        started.set()
        release.wait(2)
        return ["de"]
    monkeypatch.setattr(discovery, "episode_languages_for_slug", lookup)
    body = discovery.SeriesEpisodeLanguagesBody(provider="serienstream", slugs=["serienstream:slow-s01e01"])
    try:
        began = time.monotonic()
        first = asyncio.run(discovery.api_series_episode_languages(body))
        assert time.monotonic() - began < .5
        assert first["pending"] == body.slugs
        assert first["available"] == {}
        assert started.is_set()
        release.set()
        second = asyncio.run(discovery.api_series_episode_languages(body))
        assert second["available"] == {body.slugs[0]: True}
        assert len(calls) == 1
    finally:
        release.set()
        broker.close()
