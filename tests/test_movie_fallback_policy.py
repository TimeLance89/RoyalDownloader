from pathlib import Path

import server
from application_services import movie_fallback_policy as policy
from providers.models import FilmpalastMovie, FilmpalastSearchResult, HosterInfo


def _movie(title, url, provider, year="2024", language="de"):
    return FilmpalastMovie(
        title=title,
        url=url,
        year=year,
        hosters=[HosterInfo(name=f"{provider}-hoster", url=f"https://cdn.test/{provider}")],
        provider=provider,
        content_language=language,
    )


def _result(title, slug, provider, year="2024"):
    return FilmpalastSearchResult(
        title=title,
        slug=slug,
        url=f"https://catalog.test/{provider}/{slug}",
        year=year,
        is_movie=True,
        provider=provider,
        content_language="de",
    )


def test_cached_movie_fallbacks_seed_sources_without_claiming_exhaustion(monkeypatch):
    primary = _movie("Primary", "https://filmfrei24.test/primary", "filmfrei24")
    fallback = _movie("Primary", "https://huhu.test/fallback", "huhu")
    captured = {}

    def fake_run(jobs, out_root, movie_fallbacks=None, start_queue=True, cancelled=None):
        captured["fallbacks"] = movie_fallbacks
        assert movie_fallbacks.get("filmfrei24:1") == [fallback]
        assert "filmfrei24:1" not in movie_fallbacks
        assert "show-s01e01" in movie_fallbacks
        return {slug for _movie_item, slug in jobs}

    monkeypatch.setattr(policy, "_ORIGINAL_RUN_DOWNLOAD_QUEUE", fake_run)

    result = server.run_download_queue(
        [(primary, "filmfrei24:1"), (primary, "show-s01e01")],
        Path("."),
        movie_fallbacks={
            "filmfrei24:1": [fallback],
            "show-s01e01": [fallback],
        },
        start_queue=False,
    )

    assert result == {"filmfrei24:1", "show-s01e01"}
    assert captured["fallbacks"].get("filmfrei24:1") == [fallback]


def test_live_fallback_uses_tmdb_canonical_alias(monkeypatch):
    primary = _movie(
        "Transformers 5: The Last Knight",
        "https://filmfrei24.test/transformers5",
        "filmfrei24",
        year="2017",
    )
    huhu = _movie(
        "Transformers: The Last Knight",
        "https://huhu.test/transformers-last-knight",
        "huhu",
        year="2017",
    )
    queries = []

    class TMDB:
        configured = True

        @staticmethod
        def movie_summary(title, year):
            assert title == "Transformers 5: The Last Knight"
            assert year == "2017"
            return {
                "tmdb_id": "335988",
                "title": "Transformers: The Last Knight",
                "original_title": "Transformers: The Last Knight",
                "year": "2017",
            }

    def search(query):
        queries.append(query)
        if "Last Knight" not in query:
            return []
        return [_result("Transformers: The Last Knight", "huhu:last-knight", "huhu", "2017")]

    monkeypatch.setattr(policy, "get_tmdb_client", lambda: TMDB())
    monkeypatch.setattr(policy, "provider_priority", lambda _kind: ["filmfrei24", "huhu"])
    monkeypatch.setattr(policy, "search_movie_candidates", search)
    monkeypatch.setattr(policy, "load_movie_for_slug", lambda _slug: huhu)
    monkeypatch.setattr(policy, "_queue_job_for_slug", lambda _slug: {"content_language": "de"})
    monkeypatch.setattr(policy, "provider_for_value", lambda value: "filmfrei24" if "filmfrei24" in value else "")

    alternatives = server.find_movie_source_fallbacks(
        primary,
        "filmfrei24:123",
        {primary.url},
    )

    assert alternatives == [huhu]
    assert any(query == "Transformers: The Last Knight" for query in queries)


def test_live_fallback_returns_every_remaining_provider_without_six_source_cap(monkeypatch):
    providers = [
        "filmfrei24",
        "filmo",
        "filmpalast",
        "huhu",
        "moflix",
        "einschalten",
        "kinox",
        "kinoger",
        "megakino",
        "xcine",
        "sflix",
        "ridomovies",
    ]
    primary = _movie("Batch Movie", "https://filmfrei24.test/batch", "filmfrei24")
    results = [
        _result("Batch Movie", f"slug-{provider}", provider)
        for provider in providers[1:]
    ]
    loaded = {
        result.slug: _movie(
            "Batch Movie",
            f"https://{result.provider}.test/movie",
            result.provider,
        )
        for result in results
    }

    class TMDB:
        configured = True

        @staticmethod
        def movie_summary(_title, _year):
            return {
                "tmdb_id": "42",
                "title": "Batch Movie",
                "original_title": "Batch Movie",
                "year": "2024",
            }

    monkeypatch.setattr(policy, "get_tmdb_client", lambda: TMDB())
    monkeypatch.setattr(policy, "provider_priority", lambda _kind: providers)
    monkeypatch.setattr(policy, "search_movie_candidates", lambda _query: list(results))
    monkeypatch.setattr(policy, "load_movie_for_slug", lambda slug: loaded[slug])
    monkeypatch.setattr(policy, "_queue_job_for_slug", lambda _slug: {"content_language": "de"})
    monkeypatch.setattr(policy, "provider_for_value", lambda value: "filmfrei24" if "filmfrei24" in value else "")

    alternatives = server.find_movie_source_fallbacks(
        primary,
        "filmfrei24:batch",
        {primary.url},
    )

    assert len(alternatives) == 11
    assert [item.provider for item in alternatives] == providers[1:]


def test_live_fallback_preserves_queue_language_lane(monkeypatch):
    primary = _movie("Language Movie", "https://filmfrei24.test/lang", "filmfrei24", language="de")
    de_movie = _movie("Language Movie", "https://huhu.test/lang", "huhu", language="de")
    en_movie = _movie("Language Movie", "https://sflix.test/lang", "sflix", language="en")
    results = [
        _result("Language Movie", "huhu:lang", "huhu"),
        _result("Language Movie", "sflix:lang", "sflix"),
    ]
    loaded = {"huhu:lang": de_movie, "sflix:lang": en_movie}

    class TMDB:
        configured = True

        @staticmethod
        def movie_summary(_title, _year):
            return {
                "tmdb_id": "99",
                "title": "Language Movie",
                "original_title": "Language Movie",
                "year": "2024",
            }

    monkeypatch.setattr(policy, "get_tmdb_client", lambda: TMDB())
    monkeypatch.setattr(policy, "provider_priority", lambda _kind: ["filmfrei24", "huhu", "sflix"])
    monkeypatch.setattr(policy, "search_movie_candidates", lambda _query: list(results))
    monkeypatch.setattr(policy, "load_movie_for_slug", lambda slug: loaded[slug])
    monkeypatch.setattr(policy, "_queue_job_for_slug", lambda _slug: {"content_language": "de"})
    monkeypatch.setattr(policy, "provider_for_value", lambda value: "filmfrei24" if "filmfrei24" in value else "")

    alternatives = server.find_movie_source_fallbacks(
        primary,
        "filmfrei24:lang",
        {primary.url},
    )

    assert alternatives == [de_movie]


def test_live_fallback_rejects_wrong_year_even_when_title_matches(monkeypatch):
    primary = _movie("Same Title", "https://filmfrei24.test/same", "filmfrei24", year="2024")
    wrong = _movie("Same Title", "https://huhu.test/same", "huhu", year="1999")

    class TMDB:
        configured = True

        @staticmethod
        def movie_summary(_title, _year):
            return {
                "tmdb_id": "100",
                "title": "Same Title",
                "original_title": "Same Title",
                "year": "2024",
            }

    monkeypatch.setattr(policy, "get_tmdb_client", lambda: TMDB())
    monkeypatch.setattr(policy, "provider_priority", lambda _kind: ["filmfrei24", "huhu"])
    monkeypatch.setattr(
        policy,
        "search_movie_candidates",
        lambda _query: [_result("Same Title", "huhu:same", "huhu", year="1999")],
    )
    monkeypatch.setattr(policy, "load_movie_for_slug", lambda _slug: wrong)
    monkeypatch.setattr(policy, "_queue_job_for_slug", lambda _slug: {"content_language": "de"})
    monkeypatch.setattr(policy, "provider_for_value", lambda value: "filmfrei24" if "filmfrei24" in value else "")

    assert server.find_movie_source_fallbacks(
        primary,
        "filmfrei24:same",
        {primary.url},
    ) == []
