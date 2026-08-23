import asyncio
import threading
import time

import api_discovery_router


def test_series_artwork_batch_returns_fast_results_without_waiting_for_slow_title(
    monkeypatch,
):
    release_slow = threading.Event()
    slow_started = threading.Event()

    class FakeTmdb:
        configured = True

        @staticmethod
        def series_summary(title, _year=""):
            if title == "Slow Series":
                slow_started.set()
                release_slow.wait(timeout=2)
            return {
                "title": title,
                "backdrop_url": f"https://image.invalid/{title}.jpg",
            }

    monkeypatch.setattr(api_discovery_router, "get_tmdb_client", lambda: FakeTmdb())
    monkeypatch.setattr(api_discovery_router, "_norm_title", lambda value: value.casefold())
    monkeypatch.setattr(api_discovery_router, "strip_source_suffix", lambda value: value)
    monkeypatch.setattr(api_discovery_router, "TMDB_METADATA_BATCH_BUDGET_SECONDS", 0.05)
    body = api_discovery_router.SeriesMetadataBody(items=[
        {"base_slug": "slow-series", "title": "Slow Series"},
        {"base_slug": "fast-series", "title": "Fast Series"},
    ])

    started = time.monotonic()
    try:
        result = asyncio.run(api_discovery_router.api_tmdb_series(body))
    finally:
        release_slow.set()
    elapsed = time.monotonic() - started

    assert slow_started.wait(timeout=0.5)
    assert elapsed < 0.5
    assert result["series"]["fast-series"]["title"] == "Fast Series"
    assert result["pending"] == ["slow-series"]
