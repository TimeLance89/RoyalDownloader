import threading
import time
import asyncio

import server  # noqa: F401 - registers the application service backend
import api_discovery_router
from application_services import movie_catalog
from providers.models import FilmpalastSearchResult


def test_slow_movie_provider_continues_after_request_deadline(monkeypatch):
    release = threading.Event()

    def slow_provider(*_args):
        release.wait(timeout=1)
        return []

    monkeypatch.setattr(movie_catalog, "_fetch_movie_provider_page", slow_provider)
    timed_out = [False]
    started = time.monotonic()
    try:
        result = movie_catalog._load_movie_provider_pages(
            "new",
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


def test_stale_movie_provider_page_returns_immediately_and_revalidates(monkeypatch):
    provider = "filmpalast"
    source_page = 97
    cache_key = ("provider", "new", "", provider, source_page)
    release = threading.Event()

    with server.state.movie_list_cache_lock:
        server.state.movie_list_cache[cache_key] = (
            time.time() - server.MOVIE_LIST_CACHE_TTL - 1,
            ["stale-result"],
            server.MOVIE_LIST_CACHE_TTL,
        )

    def refreshed_provider(*_args):
        assert release.wait(timeout=1)
        return ["fresh-result"]

    monkeypatch.setattr(movie_catalog, "_fetch_movie_provider_page", refreshed_provider)
    started = time.monotonic()
    try:
        result = movie_catalog._load_movie_provider_pages(
            "new", "", [(provider, source_page)],
        )
        elapsed = time.monotonic() - started
        assert result == {(provider, source_page): ["stale-result"]}
        assert elapsed < 0.1

        release.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if movie_catalog._cached_movie_provider_page(cache_key) == ["fresh-result"]:
                break
            time.sleep(0.01)
        assert movie_catalog._cached_movie_provider_page(cache_key) == ["fresh-result"]
    finally:
        release.set()
        with server.state.movie_list_cache_lock:
            server.state.movie_list_cache.pop(cache_key, None)


def test_movie_catalog_response_does_not_wait_for_jellyfin(monkeypatch):
    monkeypatch.setattr(
        api_discovery_router,
        "movie_catalog_page",
        lambda *_args: {
            "results": [{
                "slug": "movie:test", "title": "Test", "year": "2026",
                "provider": "", "is_movie": True,
            }],
            "page": 1,
            "has_more": False,
            "sources": [],
        },
    )
    monkeypatch.setattr(
        api_discovery_router,
        "get_jellyfin_movie_identities",
        lambda: (_ for _ in ()).throw(AssertionError("Jellyfin blocked catalog")),
    )

    result = asyncio.run(api_discovery_router.api_movies(mode="new", page=1))

    assert result["results"][0]["slug"] == "movie:test"
    assert "in_jellyfin" not in result["results"][0]


def test_partial_movie_page_is_marked_for_same_page_retry(monkeypatch):
    results = [
        FilmpalastSearchResult(
            title=f"Film {index}",
            slug=f"film-{index}",
            url=f"https://example.test/{index}",
            year="2026",
            provider="filmpalast",
        )
        for index in range(14)
    ]

    monkeypatch.setattr(movie_catalog, "provider_priority", lambda _kind: ["filmpalast"])

    def partial_load(_mode, _genre, requests, _cold_budget, _deadline, timed_out):
        timed_out[0] = True
        return {requests[0]: results}

    monkeypatch.setattr(movie_catalog, "_load_movie_provider_pages", partial_load)

    page = movie_catalog.movie_catalog_page("new", 1)

    assert len(page["results"]) == 14
    assert page["has_more"] is True
    assert page["page_complete"] is False


def test_full_page_still_reports_missing_active_provider(monkeypatch):
    monkeypatch.setattr(movie_catalog, "provider_priority", lambda _: ["filmpalast", "kinoger"])
    movies = [
        FilmpalastSearchResult(title=f"Film {i}", slug=f"film-{i}", url=f"https://example.test/{i}")
        for i in range(server.MOVIE_BROWSE_PAGE_SIZE + 1)
    ]

    def load(*_args):
        _args[-1][0] = True
        return {("filmpalast", 1): movies}

    monkeypatch.setattr(movie_catalog, "_load_movie_provider_pages", load)
    page = movie_catalog.movie_catalog_page("new", 1)
    assert len(page["results"]) == server.MOVIE_BROWSE_PAGE_SIZE
    assert page["refresh_pending"] is True
    assert page["page_complete"] is False


def test_new_movie_keeps_best_provider_position_and_preferred_source():
    def movie(title, provider):
        return FilmpalastSearchResult(
            title=title, slug=f"{provider}:{title}", url=f"https://example.test/{title}",
            provider=provider, content_language="de",
        )

    preferred = [movie(f"Film {i}", "filmpalast") for i in range(20)]
    preferred.append(movie("Neuheit", "filmpalast"))
    mixed = movie_catalog._mix_movie_provider_results(
        {"filmpalast": preferred, "kinoger": [movie("Neuheit", "kinoger")]},
        ["filmpalast", "kinoger"], newest_first=True,
    )
    assert mixed[1][1].title == "Neuheit"
    assert mixed[1][0] == "filmpalast"
    assert sum(result.title == "Neuheit" for _, result in mixed) == 1
