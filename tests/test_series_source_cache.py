from core.series_source_cache import SeriesSourceCache
from providers.models import FilmpalastSeries, SeriesEpisode


def snapshot(upcoming=False, count=1):
    return FilmpalastSeries(title="Test", base_slug="serienstream:test", url="test", seasons={2: [
        SeriesEpisode(season=2, episode=n, slug=f"test-s02e{n:02d}", url="test",
                      release_label="Demnächst" if upcoming else "")
        for n in range(1, count + 1)
    ]})


def test_opening_does_not_extend_source_freshness_or_retention():
    now = [0]
    cache = SeriesSourceCache("test", max_entries=2, ttl_seconds=3600, clock=lambda: now[0])
    series = snapshot(True)
    cache[series.base_slug] = series
    now[0] = 59
    cache[series.base_slug] = cache[series.base_slug]
    assert not cache.needs_refresh(series.base_slug)
    now[0] = 60
    assert cache.needs_refresh(series.base_slug)
    assert cache.get(series.base_slug) is series
    now[0] = 3600
    assert cache.get(series.base_slug) is None


def test_ordinary_series_refresh_in_five_minutes_and_failures_have_backoff():
    now = [0]
    cache = SeriesSourceCache("test", max_entries=2, ttl_seconds=3600, clock=lambda: now[0])
    series = snapshot()
    cache[series.base_slug] = series
    now[0] = 299
    assert not cache.needs_refresh(series.base_slug)
    now[0] = 300
    assert cache.needs_refresh(series.base_slug)
    cache.refresh_failed(series.base_slug)
    now[0] = 359
    assert not cache.needs_refresh(series.base_slug)
    assert cache.get(series.base_slug) is series
    now[0] = 360
    assert cache.needs_refresh(series.base_slug)
    cache[series.base_slug] = snapshot(count=3)
    assert not cache.needs_refresh(series.base_slug)


def test_source_refresh_updates_existing_season_and_release_state(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import api.api_discovery_router as discovery
    from application_services.series_catalog import merge_series_snapshots

    now = [0]
    cache = SeriesSourceCache("test", max_entries=2, ttl_seconds=3600, clock=lambda: now[0])
    old = snapshot(True)
    cache[old.base_slug] = old
    now[0] = 61
    fresh = snapshot(count=3)
    calls = []
    monkeypatch.setattr(discovery, "state", SimpleNamespace(series_cache=cache))
    monkeypatch.setattr(discovery, "get_series_for_value", lambda _: calls.append(1) or fresh)
    monkeypatch.setattr(discovery, "merge_series_snapshots", merge_series_snapshots)
    monkeypatch.setattr(discovery, "series_to_dict", lambda series, **kw: {
        "episodes": len(series.all_episodes), "released": series.all_episodes[0].is_released,
    })
    body = discovery.SeriesLoadBody(sample_slug="test", base_slug=old.base_slug, defer_checks=True)
    assert asyncio.run(discovery.api_series_load(body)) == {"episodes": 3, "released": True}
    assert asyncio.run(discovery.api_series_load(body)) == {"episodes": 3, "released": True}
    assert len(calls) == 1

    now[0] += 301
    monkeypatch.setattr(discovery, "get_series_for_value", lambda _: None)
    monkeypatch.setattr(discovery, "log", lambda *args: None)
    assert asyncio.run(discovery.api_series_load(body)) == {"episodes": 3, "released": True}
    assert not cache.needs_refresh(old.base_slug)
