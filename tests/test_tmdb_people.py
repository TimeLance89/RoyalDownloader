from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_people_router import create_people_router
from integrations.tmdb_client import TMDBClient
from application_services.people_series import resolve_person_series
from types import SimpleNamespace


def test_credits_preserve_movie_tv_identity_and_merge_roles(monkeypatch):
    client = TMDBClient("test")
    movie = {"id": 7, "media_type": "movie", "title": "One Piece", "release_date": "2023-08-31"}
    payload = {"id": 4, "name": "Actor", "combined_credits": {
        "cast": [{**movie, "character": "First"}, {**movie, "character": "Second"},
                 {"id": 7, "media_type": "tv", "name": "One Piece", "first_air_date": "1999-10-20"},
                 {"id": 8, "media_type": "movie", "adult": True}],
        "crew": [{**movie, "job": "Producer", "department": "Production"}],
    }}
    monkeypatch.setattr(client, "_request", lambda *args: payload)
    person = client.person(4)
    assert len(person["credits"]) == 2
    film, series = person["credits"]
    assert film["roles"] == ["First", "Second", "Producer"]
    assert film["characters"] == ["First", "Second"]
    assert film["departments"] == ["Acting", "Production"]
    assert film["year"] == "2023"
    assert series["year"] == "1999"
    film["title"] = "changed"
    assert client.person(4)["credits"][0]["title"] == "One Piece"


def test_search_outage_is_not_cached_and_query_is_passed(monkeypatch):
    client = TMDBClient("test")
    requests = []
    replies = iter([None, {"results": [{"id": 1, "name": "Actor"}, {"id": 2, "adult": True}], "total_pages": 0}])

    def fetch(path, params):
        requests.append((path, params))
        return next(replies)

    monkeypatch.setattr(client, "_request", fetch)
    assert client.people(" Name ") is None
    result = client.people(" Name ")
    assert [row["id"] for row in result["results"]] == [1]
    assert result["total_pages"] == 1
    assert requests[-1] == ("/search/person", {"language": "de-DE", "page": 1, "include_adult": "false", "query": "Name"})
    assert client.people(" Name ") == result
    assert len(requests) == 2


def test_missing_combined_credits_does_not_cache_empty_filmography(monkeypatch):
    client = TMDBClient("test")
    replies = iter([{"id": 1, "name": "Actor"}, {"id": 1, "name": "Actor", "combined_credits": {}}])
    monkeypatch.setattr(client, "_request", lambda *args: next(replies))
    assert client.person(1) is None
    assert client.person(1)["credits"] == []


def test_people_api_aliases_validation_and_configuration(monkeypatch):
    tmdb = TMDBClient()
    app = FastAPI()
    app.include_router(create_people_router(lambda: tmdb))
    client = TestClient(app)
    assert client.get("/api/people").status_code == 503
    tmdb.api_key = "test"
    monkeypatch.setattr(tmdb, "_request", lambda *args: {"results": []})
    assert client.get("/api/people").json() == client.get("/api/v1/people").json()
    assert client.get("/api/people?page=501").status_code == 422
    assert client.get("/api/people?query=" + "x" * 201).status_code == 422
    assert client.get("/api/people/0").status_code == 400
    monkeypatch.setattr(tmdb, "person", lambda *args: None)
    assert client.get("/api/v1/people/1").status_code == 503


def test_series_credit_never_opens_same_name_original_and_recovers_provider_failure():
    original = SimpleNamespace(title="Scrubs", year="2001", sample_slug="original", seasons={1: [1]})
    remake = SimpleNamespace(title="Scrubs", year="2026", sample_slug="remake", seasons={1: [1]})
    client = SimpleNamespace(series_by_id=lambda _: {"title": "Scrubs", "year": "2026"},
                             series_matches_id=lambda title, identity, year: year == "2026")
    loaded = []

    def search(provider, title):
        if provider == "offline":
            raise RuntimeError("offline")
        return [original, remake]

    def load(provider, slug):
        loaded.append(slug)
        return remake

    assert resolve_person_series(client, 42, ["offline", "online"], search, load) is remake
    assert loaded == ["remake"]
    assert resolve_person_series(client, 42, ["online"], search, lambda *args: original) is None
    unknown = SimpleNamespace(title="Scrubs", year="", seasons={1: [1]})
    assert resolve_person_series(client, 42, ["online"], search, lambda *args: unknown) is None
