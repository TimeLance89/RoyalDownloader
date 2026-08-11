import threading
import time

import server  # noqa: F401 - registers the application service backend
from application_services import series_catalog


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
