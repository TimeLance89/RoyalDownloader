import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from features.movie_probes import MovieProbeIncomplete, MovieProbePool, movie_probe_context
import api.api_discovery_router as router


def test_late_answer_is_retained_and_concurrent_clients_share_one_probe():
    pool = MovieProbePool(workers=2)
    release = threading.Event()
    calls = []

    def slow():
        calls.append(1)
        release.wait(2)
        return "hoster"

    try:
        jobs = [("movie", "provider", slow)]
        pending = pool.collect(jobs, context="same", timeout=0.01)
        assert not pending and pending.incomplete
        again = pool.collect(jobs, context="same", timeout=0.01)
        assert not again and again.incomplete
        release.set()
        found = pool.collect(jobs, context="same", timeout=1)
        assert found == [("movie", "hoster")]
        assert not found.incomplete and calls == [1]
    finally:
        release.set()
        pool.close()


def test_fast_provider_wins_without_waiting_for_stalled_preferred_provider():
    pool = MovieProbePool(workers=2)
    release = threading.Event()
    try:
        found = pool.collect([("slow", "a", lambda: release.wait(2)),
                              ("fast", "b", lambda: "hoster")], context="same", timeout=0.1)
        assert ("fast", "hoster") in found and found.incomplete
    finally:
        release.set()
        pool.close()


def test_saturation_is_unknown_and_existing_job_can_still_be_observed():
    pool = MovieProbePool(workers=1, pending_capacity=1)
    release = threading.Event()
    try:
        first = pool.submit("one", "a", lambda: release.wait(2))
        assert pool.submit("one", "a", lambda: None) is first
        assert pool.submit("two", "b", lambda: None) is None
        results = pool.collect([("two", "b", lambda: None)], context="new", timeout=0)
        assert not results and results.incomplete
    finally:
        release.set()
        pool.close()


def test_positive_negative_and_error_cache_expire_independently():
    now = [0]
    pool = MovieProbePool(clock=lambda: now[0], positive_ttl=180, negative_ttl=30, error_ttl=5)

    def fail():
        raise TimeoutError("temporary")

    try:
        positive = pool.submit("positive", "a", lambda: "hoster")
        negative = pool.submit("negative", "b", lambda: None)
        error = pool.submit("error", "c", fail)
        positive.result(1)
        negative.result(1)
        with pytest.raises(TimeoutError):
            error.result(1)
        now[0] = 6
        assert pool.submit("error", "c", lambda: "recovered").result(1) == "recovered"
        assert pool.submit("negative", "b", lambda: "new") is negative
        now[0] = 31
        assert pool.submit("negative", "b", lambda: "new").result(1) == "new"
        assert pool.submit("positive", "a", lambda: "new") is positive
        now[0] = 181
        assert pool.submit("positive", "a", lambda: "new").result(1) == "new"
    finally:
        pool.close()


def test_context_changes_with_language_and_provider_configuration():
    state = SimpleNamespace(fp_movies={}, content_languages={"de"},
                            provider_enabled={"movies": ["a"]}, provider_priorities={"movies": ["a", "b"]})
    first = movie_probe_context(state)
    assert first == movie_probe_context(state)
    state.content_languages = {"en"}
    assert first != movie_probe_context(state)
    state.content_languages = {"de"}
    state.provider_enabled["movies"] = ["b"]
    assert first != movie_probe_context(state)
    state.fp_movies = {}
    assert first[0] != movie_probe_context(state)[0]


def test_custom_expiry_is_fixed_at_completion_not_shortened_on_each_poll():
    now = [0]
    pool = MovieProbePool(clock=lambda: now[0], ttl_for=lambda _: 10 - now[0])
    try:
        first = pool.submit("movie", "a", lambda: "source")
        first.result(1)
        now[0] = 6
        assert pool.submit("movie", "a", lambda: "new") is first
        now[0] = 10
        assert pool.submit("movie", "a", lambda: "new").result(1) == "new"
    finally:
        pool.close()


@pytest.fixture
def progressive_api(monkeypatch):
    pool = MovieProbePool(workers=2, error_ttl=0)
    monkeypatch.setattr(router, "movie_detail_probes", pool)
    monkeypatch.setattr(router, "state", SimpleNamespace(fp_movies={}, content_languages={"de"}))
    monkeypatch.setattr(router, "provider_priority", lambda _: ["a"], raising=False)
    monkeypatch.setattr(router, "MOVIE_AVAILABILITY_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(router, "movie_detail_to_dict", lambda slug, movie: {"slug": slug, "hosters": movie.hosters})
    monkeypatch.setattr(router, "log", lambda *args: None, raising=False)
    yield pool
    pool.close()


def test_api_pending_then_success_without_reopening_and_without_duplicate_load(monkeypatch, progressive_api):
    release = threading.Event()
    calls = []

    def load(slug):
        calls.append(slug)
        release.wait(2)
        return SimpleNamespace(hosters=["found"])

    monkeypatch.setattr(router, "load_movie_for_slug", load)

    async def request_twice():
        return await asyncio.gather(router.api_movie("a:42", progressive=True),
                                    router.api_movie("a:42", progressive=True))

    try:
        responses = asyncio.run(request_twice())
        assert all(response.status_code == 202 for response in responses)
        assert json.loads(responses[0].body)["availability"]["state"] == "checking"
        assert calls == ["a:42"]
        release.set()
        result = asyncio.run(router.api_movie("a:42", progressive=True))
        assert result["hosters"] == ["found"]
        assert result["availability"]["complete"]
        assert calls == ["a:42"]
    finally:
        release.set()


def test_incomplete_api_never_becomes_definitive_404_and_can_recover(monkeypatch, progressive_api):
    def fail(_):
        raise MovieProbeIncomplete("still checking")

    monkeypatch.setattr(router, "load_movie_for_slug", fail)
    response = asyncio.run(router.api_movie("a:42", progressive=True))
    assert response.status_code == 202
    assert not router.state.fp_movies
    assert json.loads(response.body)["availability"]["state"] == "retrying"
    with pytest.raises(HTTPException) as raised:
        asyncio.run(router.api_movie("a:42"))
    assert raised.value.status_code == 503
    monkeypatch.setattr(router, "load_movie_for_slug", lambda _: SimpleNamespace(hosters=["recovered"]))
    assert asyncio.run(router.api_movie("a:42", progressive=True))["hosters"] == ["recovered"]


def test_progressive_api_revalidates_stale_catalog_hosters(monkeypatch, progressive_api):
    router.state.fp_movies["a:42"] = SimpleNamespace(hosters=["old"])
    monkeypatch.setattr(router, "load_movie_for_slug", lambda _: None)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(router.api_movie("a:42", progressive=True))
    assert raised.value.status_code == 404


def test_identity_fallback_preserves_all_language_sources_under_selected_slug(monkeypatch, progressive_api):
    german = SimpleNamespace(hosters=["de"])
    english = SimpleNamespace(hosters=["en"])
    router.state.movie_source_cache = {"tmdb:42": [german, english]}
    router.state.movie_source_cache_lock = threading.RLock()
    monkeypatch.setattr(router, "load_movie_for_slug", lambda slug: german if slug == "tmdb:42" else None)
    monkeypatch.setattr(router, "movie_detail_to_dict", lambda slug, movie: {
        "hosters": movie.hosters, "sources": [item.hosters for item in router.state.movie_source_cache[slug]]})
    payload = asyncio.run(router.api_movie("a:42", tmdb_id=42, progressive=True))
    assert payload["sources"] == [["de"], ["en"]]


def test_progressive_api_rejects_a_result_from_old_language_settings(monkeypatch, progressive_api):
    def load(_):
        router.state.content_languages = {"en"}
        return SimpleNamespace(hosters=["old German result"])

    monkeypatch.setattr(router, "load_movie_for_slug", load)
    response = asyncio.run(router.api_movie("a:42", progressive=True))
    assert response.status_code == 202
    assert not router.state.fp_movies


def test_tmdb_resolution_merges_late_sources_instead_of_freezing_first_partial_result(monkeypatch):
    import server
    from application_services import movie_catalog, movie_availability
    from providers.models import FilmpalastMovie, FilmpalastSearchResult, HosterInfo

    release = threading.Event()
    pool = MovieProbePool(workers=2)
    calls = []
    monkeypatch.setattr(server.state, "fp_movies", {})
    monkeypatch.setattr(server.state, "movie_source_cache", {})
    monkeypatch.setattr(server, "provider_priority", lambda _: ["moflix", "filmpalast"])
    monkeypatch.setattr(server, "get_tmdb_client", lambda: SimpleNamespace(
        movie_by_id=lambda _: {"title": "Alpha", "original_title": "Alpha", "year": "2024"}))
    candidates = [FilmpalastSearchResult("Alpha", f"{provider}:alpha", "https://example.test/alpha",
        year="2024", provider=provider) for provider in ["moflix", "filmpalast"]]
    monkeypatch.setattr(server, "search_movie_candidates", lambda *args, **kwargs: candidates)
    monkeypatch.setattr(movie_availability, "movie_source_probes", pool)
    monkeypatch.setattr(movie_catalog, "MOVIE_DETAIL_LOAD_BUDGET_SECONDS", 0.05)

    def load(slug):
        calls.append(slug)
        provider = slug.split(":")[0]
        if provider == "filmpalast":
            release.wait(2)
        movie = FilmpalastMovie("Alpha", "https://example.test/alpha", year="2024",
            provider=provider, content_language="de", hosters=[HosterInfo("VOE", "https://example.test/embed", language="de")])
        movie._movie_probe_checked_at = time.time()
        return movie

    monkeypatch.setattr(movie_catalog, "_RAW_LOAD_MOVIE_FOR_SLUG", load)
    try:
        first = server.resolve_tmdb_movie_sources(42)
        assert len(first) == 1 and first[0]._movie_availability_incomplete
        release.set()
        # Observe the retained future without replacing the provider lookup.
        pool.collect([(item.slug, item.provider, lambda: None) for item in candidates],
            context=(movie_availability._movie_probe_context(), ("source", "tmdb:42")), timeout=1, early=False)
        second = server.resolve_tmdb_movie_sources(42)
        assert [source.provider for source in second] == ["moflix", "filmpalast"]
        assert not any(source._movie_availability_incomplete for source in second)
        assert sorted(calls) == sorted(item.slug for item in candidates)
    finally:
        release.set()
        pool.close()


def test_tmdb_search_with_no_routable_providers_is_unknown_during_cooldown(monkeypatch):
    import server
    from application_services import movie_catalog, movie_availability

    monkeypatch.setattr(server, "provider_priority", lambda _: [])
    monkeypatch.setattr(server, "provider_order", lambda _: ["moflix"])
    monkeypatch.setattr(server.state, "provider_enabled", {"movies": ["moflix"]})
    monkeypatch.setattr(server.state, "content_languages", {"de"})
    monkeypatch.setattr(server.state.provider_health, "routing_allowed", lambda _: False)
    result = server.search_movie_candidates("Alpha", interactive=True)
    assert not result and result.incomplete
    assert movie_availability._movie_routing_incomplete()
