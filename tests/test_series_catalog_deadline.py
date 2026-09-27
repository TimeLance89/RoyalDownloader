import threading
import time
import asyncio

import pytest
from fastapi import HTTPException

import server  # noqa: F401 - registers the application service backend
from application_services import series_catalog


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
