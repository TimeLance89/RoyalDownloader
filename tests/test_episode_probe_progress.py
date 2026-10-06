import asyncio
import threading
from types import SimpleNamespace

from features.episode_probe_progress import EpisodeProbeProgress


def test_progress_endpoint_reports_primary_while_language_request_is_still_running(monkeypatch):
    import api.api_discovery_router as discovery
    import api.api_library_router as library
    import server  # noqa: F401
    tracker = EpisodeProbeProgress()
    monkeypatch.setattr("features.episode_probe_progress.probe_progress", tracker)
    monkeypatch.setattr(discovery, "state", SimpleNamespace(content_languages={"de"}, series_cache={}))
    monkeypatch.setattr(discovery, "provider_priority", lambda kind: ["serienstream"])
    monkeypatch.setattr(discovery, "provider_for_value", lambda slug: "serienstream")
    monkeypatch.setattr(library, "record_watchlist_episode_languages", lambda values: None)
    started, release = threading.Event(), threading.Event()
    def language_lookup(*args):
        started.set()
        release.wait(2)
        return ["de"]
    monkeypatch.setattr(discovery, "episode_languages_for_slug", language_lookup)
    async def run():
        task = asyncio.create_task(discovery.api_series_episode_languages(discovery.SeriesEpisodeLanguagesBody(
            provider="serienstream", slugs=["serienstream:show-s01e01"], probe_id="live-probe")))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.01)
            assert started.is_set()
            snapshot = await discovery.api_series_episode_probe_progress("live-probe")
            assert snapshot["providers"][0]["provider"] == "serienstream"
            assert snapshot["providers"][0]["status"] == "checking"
            assert not task.done()
            release.set()
            result = await task
            assert result["progress"][0]["status"] == "found"
        finally:
            release.set()
            await task
    asyncio.run(run())


def test_progress_is_bounded_and_expires(monkeypatch):
    clock = [100]
    monkeypatch.setattr("features.episode_probe_progress.time.monotonic", lambda: clock[0])
    tracker = EpisodeProbeProgress(capacity=2, ttl=10)
    for key in ["first", "second", "third"]:
        tracker.start(key)
        tracker.update(key, "episode", "source", "checking")
    assert tracker.snapshot("first") == []
    assert tracker.snapshot("third")[0]["status"] == "checking"
    clock[0] = 111
    assert tracker.snapshot("third") == []
