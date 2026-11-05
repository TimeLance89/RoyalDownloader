import asyncio
from unittest.mock import patch

import pytest

from integrations.tmdb_client import TMDBClient
from integrations.tmdb_movie_worlds import MOVIE_WORLDS


def payload():
    return {"results": [{"id": 12, "title": "Titel", "original_language": "en",
                         "release_date": "1994-06-15", "vote_average": 8.2}],
            "total_pages": 3, "total_results": 49}


@pytest.mark.parametrize("world", [w for w in MOVIE_WORLDS if w != "star-wars"])
def test_worlds_use_metadata_not_provider_or_title_search(world):
    client = TMDBClient("key")
    with patch.object(client, "_request", return_value=payload()) as request:
        data = client.movie_world(world, 2, language="en", period="1990s", rating="8", sort="rating")
    path, params = request.call_args.args
    assert path == "/discover/movie"
    assert params["language"] == "en-US"
    assert params["primary_release_date.gte"] == "1990-01-01"
    assert params["vote_count.gte"] == "50"
    assert params["sort_by"] == "vote_average.desc"
    assert data["results"][0]["slug"] == "tmdb:12"
    assert data["results"][0]["content_language"] == ""  # original language is no audio proof
    assert data["has_more"] is True


def test_cache_is_bounded_isolated_by_language_and_defensive():
    client = TMDBClient("key")
    with patch.object(client, "_request", return_value=payload()) as request:
        client.movie_world("pixar")["results"][0]["title"] = "mutated"
        assert client.movie_world("pixar")["results"][0]["title"] == "Titel"
        client.movie_world("pixar", language="en")
        assert request.call_count == 2
    assert client._movie_world_cache.max_entries == 128


@pytest.mark.parametrize("kwargs", [{"world": "unknown"}, {"page": 0}, {"page": 501},
                                  {"language": "xx"}, {"period": "oops"}, {"genre": "bad"},
                                  {"sort": "invalid"}, {"rating": "nan"}])
def test_invalid_filters_do_not_request_tmdb(kwargs):
    client = TMDBClient("key")
    with patch.object(client, "_request") as request, pytest.raises(ValueError):
        client.movie_world(**{"world": "disney", **kwargs})
    request.assert_not_called()


def test_failure_is_not_cached_as_empty_catalogue():
    client = TMDBClient("key")
    with patch.object(client, "_request", side_effect=[None, payload()]) as request:
        with pytest.raises(RuntimeError):
            client.movie_world("dc")
        assert client.movie_world("dc")["total_results"] == 49
    assert request.call_count == 2


def test_classics_combines_genres_and_excludes_pixar():
    client = TMDBClient("key")
    with patch.object(client, "_request", return_value=payload()) as request:
        client.movie_world("disney-classics", genre="Familie")
    params = request.call_args.args[1]
    assert params["with_genres"] == "16,10751"
    assert params["without_companies"] == "3"


@pytest.mark.parametrize("world", ["disney", "disney-classics"])
@pytest.mark.parametrize("language", ["de", "en"])
def test_disney_includes_historical_studios_and_sequels_across_pages(world, language):
    client = TMDBClient("key")
    # Verified TMDB production credits: Sleeping Beauty, Snow White, The Lion
    # King (1994), The Lion King II and The Lion King 1½ must all be eligible.
    titles = [(10882, "Sleeping Beauty", "3166"), (408, "Snow White", "3166"),
              (8587, "The Lion King", "171656"), (9732, "The Lion King II", "3475"),
              (11430, "The Lion King 1½", "5391")]
    calls = []

    def discover(path, params):
        assert path == "/discover/movie"
        calls.append(params)
        companies = set(params["with_companies"].split("|"))
        eligible = [{"id": movie_id, "title": title} for movie_id, title, company in titles
                    if company in companies]
        page = int(params["page"])
        return {"results": eligible[(page - 1) * 3:page * 3],
                "total_pages": 2, "total_results": len(eligible)}

    with patch.object(client, "_request", side_effect=discover):
        first = client.movie_world(world, language=language)
        second = client.movie_world(world, 2, language=language)
    assert {m["tmdb_id"] for m in first["results"] + second["results"]} == {t[0] for t in titles}
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert first["total_results"] == 5
    assert all(p["language"] == ("de-DE" if language == "de" else "en-US") for p in calls)


def test_star_wars_uses_official_saga_not_fan_film_keywords():
    client = TMDBClient("key")
    parts = [{"id": 1, "title": "Later", "release_date": "2015-01-01", "vote_average": 8,
              "vote_count": 100}, {"id": 2, "title": "Earlier", "release_date": "1977-01-01"}]
    with patch.object(client, "_request", return_value={"parts": parts}) as request:
        data = client.movie_world("star-wars")
        assert [m["tmdb_id"] for m in data["results"]] == [2, 1]
        assert client.movie_world("star-wars", period="2010s")["total_results"] == 1
    assert request.call_args.args[0] == "/collection/10"


def test_world_route_preserves_total_and_pagination(monkeypatch):
    from api import api_discovery_router as router

    client = TMDBClient("key")
    monkeypatch.setattr(router, "MOVIE_MAX_GLOBAL_PAGE", 500)
    monkeypatch.setattr(router, "get_tmdb_client", lambda: client)
    with patch.object(client, "_request", return_value=payload()):
        data = asyncio.run(router.api_movies(mode="world", world="pixar", page=2, language="en"))
    assert data["category"] == "world"
    assert data["total_results"] == 49
    assert data["has_more"] is True
    assert data["page"] == 2


def test_world_route_requires_tmdb(monkeypatch):
    from fastapi import HTTPException

    from api import api_discovery_router as router

    monkeypatch.setattr(router, "MOVIE_MAX_GLOBAL_PAGE", 500)
    monkeypatch.setattr(router, "get_tmdb_client", lambda: TMDBClient())
    with pytest.raises(HTTPException) as error:
        asyncio.run(router.api_movies(mode="world", world="disney"))
    assert error.value.status_code == 503
