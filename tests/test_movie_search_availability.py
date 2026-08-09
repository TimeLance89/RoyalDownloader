"""Regression tests for fast provider-verified TMDB movie search."""

import time
from types import SimpleNamespace

import server
from application_services import movie_search_availability as availability


class FakeTMDBClient:
    configured = True
    language = "de-DE"

    def __init__(self, movies):
        self.movies = movies
        self.calls = 0

    def search_movies(self, query, max_results):
        self.calls += 1
        assert query
        assert max_results == server.TMDB_MOVIE_SEARCH_MAX_RESULTS
        return [dict(movie) for movie in self.movies]


def _movie(tmdb_id, title, year, original_title=""):
    return {
        "tmdb_id": tmdb_id,
        "title": title,
        "original_title": original_title,
        "year": year,
        "cover_url": "",
        "backdrop_url": "",
        "description": "",
    }


def _candidate(slug, title, year, provider="filmpalast", is_movie=True):
    return SimpleNamespace(
        slug=slug,
        title=title,
        year=year,
        provider=provider,
        is_movie=is_movie,
    )


def _loaded(title, year, hosters=True):
    return SimpleNamespace(
        title=title,
        year=year,
        hosters=[object()] if hosters else [],
    )


def _configure(monkeypatch, movies, candidates, loader, providers=None):
    availability._MOVIE_SEARCH_AVAILABILITY_CACHE.clear()
    client = FakeTMDBClient(movies)
    active = providers if providers is not None else ["filmpalast", "moflix"]
    search_calls = []

    monkeypatch.setattr(server, "get_tmdb_client", lambda: client)
    monkeypatch.setattr(server, "provider_priority", lambda _kind: list(active))

    def search(query):
        search_calls.append(query)
        return list(candidates)

    monkeypatch.setattr(server, "search_movie_candidates", search)
    monkeypatch.setattr(server, "load_movie_for_slug", loader)
    monkeypatch.setattr(server, "provider_for_value", lambda _value: "filmpalast")
    monkeypatch.setattr(server, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.state, "fp_movies", {})
    return client, search_calls, active


def test_search_uses_one_provider_wave_and_keeps_only_hosted_matches(monkeypatch):
    movies = [
        _movie(1, "Die Verurteilten", "1994", "The Shawshank Redemption"),
        _movie(2, "The Thing", "1982", "The Thing"),
        _movie(3, "The Thing", "2011", "The Thing"),
        _movie(4, "Unrelated", "2024", "Unrelated"),
    ]
    candidates = [
        _candidate("fp:shawshank", "The Shawshank Redemption", "1994"),
        _candidate("fp:thing-1982", "The Thing", "1982"),
    ]
    load_calls = []

    def loader(slug):
        load_calls.append(slug)
        if slug == "fp:shawshank":
            return _loaded("The Shawshank Redemption", "1994")
        return _loaded("The Thing", "1982", hosters=False)

    _client, search_calls, _active = _configure(
        monkeypatch, movies, candidates, loader
    )

    results = server._tmdb_search_results("the")

    assert [item["tmdb_id"] for item in results] == [1]
    assert results[0]["slug"] == "tmdb:1"
    assert results[0]["provider"] == ""
    assert search_calls == ["the"]
    assert set(load_calls) == {"fp:shawshank", "fp:thing-1982"}


def test_top_result_can_use_one_original_title_fallback_wave(monkeypatch):
    movies = [
        _movie(5, "Die Verurteilten", "1994", "The Shawshank Redemption"),
        _movie(6, "Andere Verurteilte", "2024", "Other Convicts"),
    ]
    availability._MOVIE_SEARCH_AVAILABILITY_CACHE.clear()
    client = FakeTMDBClient(movies)
    search_calls = []

    monkeypatch.setattr(server, "get_tmdb_client", lambda: client)
    monkeypatch.setattr(
        server, "provider_priority", lambda _kind: ["filmpalast", "moflix"]
    )

    def search(query):
        search_calls.append(query)
        if query == "The Shawshank Redemption":
            return [
                _candidate(
                    "moflix:shawshank",
                    "The Shawshank Redemption",
                    "1994",
                    "moflix",
                )
            ]
        return []

    monkeypatch.setattr(server, "search_movie_candidates", search)
    monkeypatch.setattr(
        server,
        "load_movie_for_slug",
        lambda _slug: _loaded("The Shawshank Redemption", "1994"),
    )
    monkeypatch.setattr(server, "provider_for_value", lambda _value: "moflix")
    monkeypatch.setattr(server, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.state, "fp_movies", {})

    results = server._tmdb_search_results("Die Verurteilten")

    assert [item["tmdb_id"] for item in results] == [5]
    assert search_calls == ["Die Verurteilten", "The Shawshank Redemption"]


def test_unmatched_tmdb_results_never_trigger_detail_loads(monkeypatch):
    movies = [_movie(index, f"Movie {index}", "2024") for index in range(1, 31)]
    candidates = [_candidate("fp:movie-1", "Movie 1", "2024")]
    load_calls = []

    def loader(slug):
        load_calls.append(slug)
        return _loaded("Movie 1", "2024")

    _configure(monkeypatch, movies, candidates, loader)

    results = server._tmdb_search_results("movie")

    assert [item["tmdb_id"] for item in results] == [1]
    assert load_calls == ["fp:movie-1"]


def test_candidate_failure_falls_through_to_next_provider(monkeypatch):
    movies = [_movie(10, "Alpha", "2020")]
    candidates = [
        _candidate("fp:alpha", "Alpha", "2020", "filmpalast"),
        _candidate("moflix:alpha", "Alpha", "2020", "moflix"),
    ]
    load_calls = []

    def loader(slug):
        load_calls.append(slug)
        if slug == "fp:alpha":
            raise RuntimeError("provider temporarily unavailable")
        return _loaded("Alpha", "2020")

    _configure(monkeypatch, movies, candidates, loader)

    results = server._tmdb_search_results("alpha")

    assert [item["tmdb_id"] for item in results] == [10]
    assert load_calls == ["fp:alpha", "moflix:alpha"]


def test_aggregate_provider_search_failure_returns_no_false_positive(monkeypatch):
    movies = [_movie(11, "Beta", "2021")]
    availability._MOVIE_SEARCH_AVAILABILITY_CACHE.clear()
    client = FakeTMDBClient(movies)

    monkeypatch.setattr(server, "get_tmdb_client", lambda: client)
    monkeypatch.setattr(
        server, "provider_priority", lambda _kind: ["filmpalast", "moflix"]
    )
    monkeypatch.setattr(
        server,
        "search_movie_candidates",
        lambda _query: (_ for _ in ()).throw(RuntimeError("search failed")),
    )
    monkeypatch.setattr(server, "log", lambda *_args, **_kwargs: None)

    assert server._tmdb_search_results("beta") == []


def test_parallel_verification_preserves_tmdb_relevance_order(monkeypatch):
    movies = [
        _movie(40, "First", "2022"),
        _movie(41, "Second", "2023"),
        _movie(42, "Third", "2024"),
    ]
    candidates = [
        _candidate("fp:first", "First", "2022"),
        _candidate("fp:second", "Second", "2023"),
        _candidate("fp:third", "Third", "2024"),
    ]
    delays = {"fp:first": 0.03, "fp:second": 0.02, "fp:third": 0.01}
    titles = {
        "fp:first": ("First", "2022"),
        "fp:second": ("Second", "2023"),
        "fp:third": ("Third", "2024"),
    }

    def loader(slug):
        time.sleep(delays[slug])
        title, year = titles[slug]
        return _loaded(title, year)

    _configure(monkeypatch, movies, candidates, loader)

    results = server._tmdb_search_results("ordered")

    assert [item["tmdb_id"] for item in results] == [40, 41, 42]


def test_ambiguous_yearless_provider_hit_is_not_used_for_two_tmdb_movies(monkeypatch):
    movies = [
        _movie(50, "The Thing", "1982", "The Thing"),
        _movie(51, "The Thing", "2011", "The Thing"),
    ]
    candidates = [_candidate("fp:thing", "The Thing", "")]
    load_calls = []

    def loader(slug):
        load_calls.append(slug)
        return _loaded("The Thing", "1982")

    _configure(monkeypatch, movies, candidates, loader)

    assert server._tmdb_search_results("the thing") == []
    assert load_calls == []


def test_provider_year_marker_in_title_separates_same_named_movies():
    aliases = server._movie_title_match_keys("War Machine")

    assert server._movie_matches_tmdb_choice("War Machine *2026*", "", aliases, "2026")
    assert not server._movie_matches_tmdb_choice("War Machine *2026*", "", aliases, "2017")


def test_verified_search_results_are_cached_and_returned_as_copies(monkeypatch):
    movies = [_movie(20, "Cached", "2024")]
    candidates = [_candidate("fp:cached", "Cached", "2024")]
    load_calls = []

    def loader(slug):
        load_calls.append(slug)
        return _loaded("Cached", "2024")

    client, search_calls, _active = _configure(
        monkeypatch, movies, candidates, loader
    )

    first = server._tmdb_search_results("cached")
    first[0]["title"] = "mutated locally"
    second = server._tmdb_search_results("cached")

    assert second[0]["title"] == "Cached"
    assert client.calls == 1
    assert search_calls == ["cached"]
    assert load_calls == ["fp:cached"]


def test_cache_key_changes_with_active_provider_configuration(monkeypatch):
    movies = [_movie(30, "Provider Key", "2024")]
    candidates = [_candidate("fp:key", "Provider Key", "2024")]
    load_calls = []

    def loader(slug):
        load_calls.append(slug)
        return _loaded("Provider Key", "2024")

    client, search_calls, active = _configure(
        monkeypatch,
        movies,
        candidates,
        loader,
        providers=["filmpalast"],
    )

    server._tmdb_search_results("provider key")
    active.append("moflix")
    server._tmdb_search_results("provider key")

    assert client.calls == 2
    assert search_calls == ["provider key", "provider key"]
    # The second run can reuse the already validated provider detail object.
    assert load_calls == ["fp:key"]
