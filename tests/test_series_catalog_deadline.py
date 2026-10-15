import threading
import time
import asyncio

import pytest
from fastapi import HTTPException

import server  # noqa: F401 - registers the application service backend
from application_services import series_catalog, series_catalog_cache


@pytest.fixture
def clean_catalog_cache():
    with server.state.series_list_cache_lock:
        saved = dict(server.state.series_list_cache)
        server.state.series_list_cache.clear()
    yield
    with server.state.series_list_cache_lock:
        server.state.series_list_cache.clear()
        server.state.series_list_cache.update(saved)


def series_items(prefix, count):
    return [server.FilmpalastSeriesResult(
        title=f"{prefix} {index}", base_slug=f"{prefix}-{index}",
        sample_slug=f"{prefix}-{index}/s01e01", sample_url=f"https://example.invalid/{prefix}/{index}",
    ) for index in range(count)]


def test_slow_source_does_not_block_fast_followup_pages(monkeypatch, clean_catalog_cache):
    items = series_items("fast", 100)

    def load_pages(_mode, _letter, requests, _budget, _deadline, timed_out):
        timed_out[0] = any(provider == "serienstream" for provider, _page in requests)
        return {(provider, page): items[(page - 1) * 32:page * 32]
                for provider, page in requests if provider == "filmpalast"}

    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["serienstream", "filmpalast"])
    monkeypatch.setattr(server, "_load_series_provider_pages", load_pages)
    monkeypatch.setattr(server, "_schedule_series_provider_prefetch", lambda *_args: None)
    first = server.series_catalog_page("discover", 1)
    second = server.series_catalog_page("discover", 2)
    assert len(first["entries"]) == len(second["entries"]) == 32
    assert second["entries"][0].result.base_slug == "fast-32"
    assert second["has_more"] is True


def test_late_source_does_not_shift_already_emitted_offsets(monkeypatch, clean_catalog_cache):
    fast, late = series_items("fast", 64), series_items("late", 32)
    ready = [False]

    def load_pages(_mode, _letter, requests, _budget, _deadline, timed_out):
        timed_out[0] = not ready[0]
        loaded = {}
        for provider, page in requests:
            if provider == "serienstream" and not ready[0]:
                continue
            items = late if provider == "serienstream" else fast
            loaded[(provider, page)] = items[(page - 1) * 32:page * 32]
        return loaded

    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["serienstream", "filmpalast"])
    monkeypatch.setattr(server, "_load_series_provider_pages", load_pages)
    monkeypatch.setattr(server, "_schedule_series_provider_prefetch", lambda *_args: None)
    first = server.series_catalog_page("discover", 1)
    ready[0] = True
    second = server.series_catalog_page("discover", 2)
    third = server.series_catalog_page("discover", 3)
    slugs = [entry.result.base_slug for result in [first, second, third] for entry in result["entries"]]
    assert len(slugs) == len(set(slugs)) == 96
    assert set(slugs) == {item.base_slug for item in [*fast, *late]}
    assert third["has_more"] is False


@pytest.mark.parametrize("cached_failure", [False, True])
def test_failed_provider_page_is_pending_instead_of_catalog_end(monkeypatch, clean_catalog_cache, cached_failure):
    def failed(*_args):
        raise RuntimeError("Provider unavailable")

    if cached_failure:
        key = ("series-provider", "updates", "", "filmpalast", 1)
        series_catalog_cache.cache_page(key, [], failed=True, ttl=30)
    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["filmpalast"])
    monkeypatch.setattr(series_catalog, "_fetch_series_provider_page", failed)
    with pytest.raises(server.SeriesCatalogColdLoadLimit):
        server.series_catalog_page("discover", 1)


def test_partial_initial_page_waits_instead_of_skipping_offsets(monkeypatch, clean_catalog_cache):
    items = series_items("partial", 12)

    def load_pages(_mode, _letter, _requests, _budget, _deadline, timed_out):
        timed_out[0] = True
        return {("huhu", 1): items}

    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["huhu", "serienstream"])
    monkeypatch.setattr(server, "_load_series_provider_pages", load_pages)
    with pytest.raises(server.SeriesCatalogColdLoadLimit):
        server.series_catalog_page("discover", 1)


def test_empty_successful_provider_page_is_a_real_catalog_end(monkeypatch, clean_catalog_cache):
    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["filmpalast"])
    monkeypatch.setattr(series_catalog, "_fetch_series_provider_page", lambda *_args: [])
    result = server.series_catalog_page("discover", 1)
    assert result["entries"] == []
    assert result["has_more"] is False


def test_full_serienstream_catalog_continues_past_296(monkeypatch, clean_catalog_cache):
    from types import SimpleNamespace

    items = series_items("catalog", 400)
    scraper = SimpleNamespace(list_series_catalog=lambda page: items[(page - 1) * 32:page * 32])
    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["serienstream"])
    monkeypatch.setattr(server.state.provider_health, "request_allowed", lambda _provider: True)
    monkeypatch.setattr(server, "get_sto_scraper", lambda: scraper)
    monkeypatch.setattr(server, "_schedule_series_provider_prefetch", lambda *_args: None)
    slugs = []
    for page in range(1, 14):
        result = server.series_catalog_page("discover", page)
        slugs.extend(entry.result.base_slug for entry in result["entries"])
        assert result["has_more"] is (page < 13)
    assert slugs == [item.base_slug for item in items]


def test_incomplete_followup_page_waits_without_skipping_titles(monkeypatch):
    items = [server.FilmpalastSeriesResult(
        title=f"Serie {index}", base_slug=f"serie-{index}",
        sample_slug=f"serie-{index}/s01e01", sample_url=f"https://example.invalid/{index}",
    ) for index in range(4)]
    pending = [True]

    def load_pages(_mode, _letter, _requests, _budget, _deadline, timed_out):
        timed_out[0] = pending[0]
        return {("filmpalast", 1): items[:3] if pending[0] else items}

    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["filmpalast"])
    monkeypatch.setattr(series_catalog, "SERIES_BROWSE_PAGE_SIZE", 2)
    monkeypatch.setattr(server, "_load_series_provider_pages", load_pages)
    monkeypatch.setattr(server, "_series_provider_is_paginated", lambda *_args: False)
    with pytest.raises(server.SeriesCatalogColdLoadLimit):
        server._series_catalog_page_locked("discover", 2)
    pending[0] = False
    result = server._series_catalog_page_locked("discover", 2)
    assert [entry.result.base_slug for entry in result["entries"]] == ["serie-2", "serie-3"]
    assert result["has_more"] is False
    # A genuinely complete final page may still contain fewer than the page size.
    items.pop()
    result = server._series_catalog_page_locked("discover", 2)
    assert [entry.result.base_slug for entry in result["entries"]] == ["serie-2"]
    assert result["has_more"] is False


def test_series_pending_response_has_retry_contract(monkeypatch):
    from api import api_discovery_router

    def pending(*_args):
        raise server.SeriesCatalogColdLoadLimit("Noch in Vorbereitung")

    monkeypatch.setattr(server, "series_catalog_page", pending)
    with pytest.raises(HTTPException) as captured:
        asyncio.run(api_discovery_router.api_series(mode="discover", page=2))
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "series_catalog_pending"
    assert captured.value.headers["Retry-After"] == "1"


def test_slow_series_provider_continues_after_request_deadline(monkeypatch):
    release = threading.Event()

    def slow_provider(*_args):
        release.wait(timeout=1)
        return []

    monkeypatch.setattr(series_catalog, "_fetch_series_provider_page", slow_provider)
    timed_out = [False]
    started = time.monotonic()
    try:
        result = series_catalog._load_series_provider_pages(
            "discover",
            "",
            [("filmpalast", 99)],
            deadline=time.monotonic() + 0.04,
            timed_out=timed_out,
        )
    finally:
        release.set()

    assert time.monotonic() - started < 0.3
    assert result == {}
    assert timed_out == [True]


def test_stale_series_provider_page_returns_immediately_and_revalidates(monkeypatch):
    provider = "filmpalast"
    source_page = 97
    cache_key = ("series-provider", "updates", "", provider, source_page)
    release = threading.Event()

    with server.state.series_list_cache_lock:
        server.state.series_list_cache[cache_key] = (
            time.time() - server.SERIES_LIST_CACHE_TTL - 1,
            ["stale-result"],
            server.SERIES_LIST_CACHE_TTL,
        )

    def refreshed_provider(*_args):
        assert release.wait(timeout=1)
        return ["fresh-result"]

    monkeypatch.setattr(series_catalog, "_fetch_series_provider_page", refreshed_provider)
    started = time.monotonic()
    try:
        result = series_catalog._load_series_provider_pages(
            "discover", "", [(provider, source_page)],
        )
        assert result == {(provider, source_page): ["stale-result"]}
        assert time.monotonic() - started < 0.1

        release.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if series_catalog._cached_series_provider_page(cache_key) == ["fresh-result"]:
                break
            time.sleep(0.01)
        assert series_catalog._cached_series_provider_page(cache_key) == ["fresh-result"]
    finally:
        release.set()
        with server.state.series_list_cache_lock:
            server.state.series_list_cache.pop(cache_key, None)
