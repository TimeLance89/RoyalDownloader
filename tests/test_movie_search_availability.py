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


def _candidate(title, year, provider="filmpalast"):
    return SimpleNamespace(
        title=title,
        year=year,
        provider=provider,
        slug=f"{provider}:{title}",
        is_movie=True,
    )


def _configure(monkeypatch, movies, candidates, resolver):
    availability._MOVIE_SEARCH_AVAILABILITY_CACHE.clear()
    client = FakeTMDBClient(movies)
    searches = []
    monkeypatch.setattr(server, "get_tmdb_client", lambda: client)
    monkeypatch.setattr(server, "provider_priority", lambda _kind: ["filmpalast", "moflix"])
    monkeypatch.setattr(
        server,
        "search_movie_candidates",
        lambda query: searches.append(query) or list(candidates),
    )
    monkeypatch.setattr(server, "resolve_tmdb_movie_sources", resolver)
    monkeypatch.setattr(server, "log", lambda *_args, **_kwargs: None)
    return client, searches


def test_search_keeps_only_provider_verified_movies_and_matches_original_title(monkeypatch):
    movies = [
        _movie(1, "Die Verurteilten", "1994", "The Shawshank Redemption"),
        _movie(2, "The Thing", "1982", "The Thing"),
        _movie(3, "The Thing", "2011", "The Thing"),
    ]
    candidates = [
        _candidate("The Shawshank Redemption", "1994"),
        _candidate("The Thing", "1982", "moflix"),
        _candidate("The Thing", "1999"),
    ]
    resolved = []

    def resolver(tmdb_id):
        resolved.append(tmdb_id)
        if tmdb_id == 1:
            return [object()]
        raise LookupError("no usable hoster")

    _client, searches = _configure(monkeypatch, movies, candidates, resolver)

    results = server._tmdb_search_results("the")

    assert [item["tmdb_id"] for item in results] == [1]
    assert results[0]["slug"] == "tmdb:1"
    assert results[0]["provider"] == ""
    assert searches == ["the"]
    assert set(resolved) == {1, 2}


def test_provider_failure_does_not_hide_other_verified_results(monkeypatch):
    movies = [_movie(10, "Alpha", "2020"), _movie(11, "Beta", "2021")]
    candidates = [_candidate("Alpha", "2020"), _candidate("Beta", "2021", "moflix")]

    def resolver(tmdb_id):
        if tmdb_id == 10:
            raise RuntimeError("provider temporarily unavailable")
        return [object()]

    _configure(monkeypatch, movies, candidates, resolver)

    results = server._tmdb_search_results("alpha beta")

    assert [item["tmdb_id"] for item in results] == [11]


def test_verified_search_results_are_cached_and_returned_as_copies(monkeypatch):
    movies = [_movie(20, "Cached", "2024")]
    candidates = [_candidate("Cached", "2024")]
    resolve_calls = []

    def resolver(tmdb_id):
        resolve_calls.append(tmdb_id)
        return [object()]

    client, searches = _configure(monkeypatch, movies, candidates, resolver)

    first = server._tmdb_search_results("cached")
    first[0]["title"] = "mutated locally"
    second = server._tmdb_search_results("cached")

    assert second[0]["title"] == "Cached"
    assert client.calls == 1
    assert searches == ["cached"]
    assert resolve_calls == [20]


def test_cache_key_changes_with_active_provider_configuration(monkeypatch):
    movies = [_movie(30, "Provider Key", "2024")]
    candidates = [_candidate("Provider Key", "2024")]
    client, searches = _configure(
        monkeypatch,
        movies,
        candidates,
        lambda _tmdb_id: [object()],
    )
    active = ["filmpalast"]
    monkeypatch.setattr(server, "provider_priority", lambda _kind: list(active))

    server._tmdb_search_results("provider key")
    active.append("moflix")
    server._tmdb_search_results("provider key")

    assert client.calls == 2
    assert searches == ["provider key", "provider key"]
