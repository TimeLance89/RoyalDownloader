from __future__ import annotations

import uuid

import server
from api_queue_router import MovieDownloadPreference
from application_services import content_language_policy
from providers.models import (
    FilmpalastMovie,
    FilmpalastSearchResult,
    FilmpalastSeriesResult,
    HosterInfo,
)


def _movie_result(title: str, slug: str, provider: str, language: str, year: str = "2026"):
    return FilmpalastSearchResult(
        title=title,
        slug=slug,
        url=f"https://example.test/{slug}",
        year=year,
        provider=provider,
        content_language=language,
    )


def _series_result(title: str, slug: str, year: str = "2026"):
    return FilmpalastSeriesResult(
        title=title,
        base_slug=slug,
        sample_slug=f"{slug}-s01e01",
        sample_url=f"https://example.test/{slug}",
        year=year,
    )


def _movie_source(title: str, provider: str, language: str, suffix: str):
    return FilmpalastMovie(
        title=title,
        url=f"https://example.test/{provider}/{suffix}",
        year="2026",
        provider=provider,
        content_language=language,
        hosters=[
            HosterInfo(
                name="VOE",
                url=f"https://voe.example/{provider}/{suffix}",
                language=language,
                quality="1080p",
            )
        ],
    )


def test_movie_catalog_alternates_language_lanes_even_with_more_german_results(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    provider_results = {
        "filmpalast": [
            _movie_result(f"Deutsch {index}", f"de-{index}", "filmpalast", "de")
            for index in range(6)
        ],
        "sflix": [
            _movie_result("English One", "en-1", "sflix", "en"),
            _movie_result("English Two", "en-2", "sflix", "en"),
        ],
    }

    mixed = content_language_policy._mix_movie_provider_results(
        provider_results,
        ["filmpalast", "sflix"],
    )

    assert [item.content_language for _provider, item in mixed[:4]] == [
        "en", "de", "en", "de",
    ]
    assert len(mixed) == 8


def test_bilingual_movie_is_one_card_with_both_languages(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    provider_results = {
        "filmpalast": [
            _movie_result("Shared Movie", "shared-de", "filmpalast", "de"),
        ],
        "sflix": [
            _movie_result("Shared Movie", "shared-en", "sflix", "en"),
        ],
    }

    mixed = content_language_policy._mix_movie_provider_results(
        provider_results,
        ["filmpalast", "sflix"],
    )

    assert len(mixed) == 1
    provider, result = mixed[0]
    assert provider == "sflix"
    assert result.content_language == "en"
    assert result.content_languages == ["de", "en"]


def test_explicit_release_language_overrides_german_provider_lane(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    provider_results = {
        "kinoger": [
            _movie_result("English Release", "kinoger-en", "kinoger", "en"),
        ],
        "filmpalast": [
            _movie_result("Deutsche Fassung", "fp-de", "filmpalast", "de"),
        ],
    }

    mixed = content_language_policy._mix_movie_provider_results(
        provider_results,
        ["kinoger", "filmpalast"],
    )

    assert [item.content_language for _provider, item in mixed] == ["en", "de"]


def test_series_catalog_balances_by_language_not_provider_count(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    provider_results = {
        "serienstream": [
            _series_result(f"Deutsch Serie {index}", f"de-serie-{index}")
            for index in range(5)
        ],
        "sflix": [
            _series_result("English Series One", "en-serie-1"),
            _series_result("English Series Two", "en-serie-2"),
        ],
    }

    mixed = content_language_policy._mix_series_provider_results(
        provider_results,
        ["serienstream", "sflix"],
    )

    assert [entry.provider for entry in mixed[:4]] == [
        "sflix", "serienstream", "sflix", "serienstream",
    ]
    assert len(mixed) == 7


def test_language_download_preference_keeps_fallbacks_inside_selected_language(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    slug = f"test-language-{uuid.uuid4().hex}"
    german = _movie_source("Shared Movie", "filmpalast", "de", "de")
    english_primary = _movie_source("Shared Movie", "sflix", "en", "en-1")
    english_fallback = _movie_source("Shared Movie", "ridomovies", "en", "en-2")
    with server.state.movie_source_cache_lock:
        server.state.movie_source_cache[slug] = [german, english_primary, english_fallback]
    try:
        chosen, fallbacks = content_language_policy._preferred_movie_sources(
            slug,
            german,
            MovieDownloadPreference(provider="language:en", quality="1080p"),
        )

        assert chosen.provider == "sflix"
        assert chosen.content_language == "en"
        assert [source.provider for source in fallbacks] == ["ridomovies"]
        assert all(source.content_language == "en" for source in fallbacks)
    finally:
        with server.state.movie_source_cache_lock:
            server.state.movie_source_cache.pop(slug, None)
        server.state.fp_movies.pop(slug, None)


def test_selected_language_is_persisted_and_filters_restored_fallbacks(monkeypatch):
    monkeypatch.setattr(server.state, "content_languages", {"de", "en"})
    slug = f"test-persist-language-{uuid.uuid4().hex}"
    german = _movie_source("Shared Movie", "filmpalast", "de", "de")
    english_primary = _movie_source("Shared Movie", "sflix", "en", "en-1")
    english_fallback = _movie_source("Shared Movie", "ridomovies", "en", "en-2")
    with server.state.movie_source_cache_lock:
        server.state.movie_source_cache[slug] = [german, english_primary, english_fallback]
    server.state.fp_movies[slug] = english_primary
    try:
        job = content_language_policy._ensure_queue_job(slug, english_primary)
        assert job["content_language"] == "en"
        assert job["provider"] == "sflix"

        fallbacks = content_language_policy.cached_movie_source_fallbacks(slug)
        assert [source.provider for source in fallbacks] == ["ridomovies"]
    finally:
        with server.state.queue_claim_lock:
            job_id = server.state.queue_job_by_slug.pop(slug, "")
            if job_id:
                server.state.queue_jobs.pop(job_id, None)
        with server.state.movie_source_cache_lock:
            server.state.movie_source_cache.pop(slug, None)
        server.state.fp_movies.pop(slug, None)
