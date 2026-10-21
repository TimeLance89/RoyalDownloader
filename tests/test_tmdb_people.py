from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_people_router import create_people_router
from integrations.tmdb_client import TMDBClient
from application_services.people_series import resolve_person_series
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize("providers", [[], ["huhu"], ["moflix", "huhu"]])
@pytest.mark.parametrize("progressive", [False, True])
def test_cached_series_respects_enabled_sources_and_priority(monkeypatch, providers, progressive):
    import server  # noqa: F401 - register the application service backend
    from application_services import series_catalog as catalog
    from providers.catalog import provider_for_source

    snapshots = [SimpleNamespace(title="Show", year="2024", base_slug=f"{provider}:show",
                                 url=f"{provider}:show", seasons={1: [1]})
                 for provider in ["filmpalast", "huhu", "moflix"]]
    monkeypatch.setattr(catalog, "state", SimpleNamespace(series_cache={s.base_slug: s for s in snapshots}), raising=False)
    monkeypatch.setattr(catalog, "provider_priority", lambda kind: providers, raising=False)
    monkeypatch.setattr(catalog, "provider_for_value", provider_for_source, raising=False)
    monkeypatch.setattr(catalog, "series_to_dict", lambda series, **kwargs: {"base_slug": series.base_slug}, raising=False)

    def unexpected(*args):
        pytest.fail("cached active sources must not trigger a remote provider lookup")

    monkeypatch.setattr(catalog, "_search_series_for_provider", unexpected)
    monkeypatch.setattr(catalog, "_load_series_for_provider", unexpected)
    tmdb = SimpleNamespace(configured=True, series_by_id=lambda _: {"title": "Show", "year": "2024"},
                           series_matches_id=lambda *args: True)

    async def enrich(identity, work, **kwargs):
        return work()

    app = FastAPI()
    app.include_router(create_people_router(lambda: tmdb, enrich_series=enrich))
    response = TestClient(app).get(f"/api/people/series/42?progressive={str(progressive).lower()}")
    if providers:
        assert response.status_code == 200
        assert response.json()["base_slug"] == f"{providers[0]}:show"
    else:
        assert response.status_code == 404


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


def test_tmdb_series_opens_cached_provider_seasons_without_remote_search():
    cached = SimpleNamespace(
        title="Cached Show", year="2024", sample_slug="serienstream:cached", seasons={1: [1]})
    checks = []
    tmdb = SimpleNamespace(
        series_by_id=lambda _: {"title": "Cached Show", "year": "2024"},
        series_matches_id=lambda title, tmdb_id, year: checks.append((title, tmdb_id, year)) or True,
    )

    def no_search(*args):
        raise AssertionError("cached provider inventory must bypass remote provider searches")

    found = resolve_person_series(tmdb, 788, ["serienstream"], no_search, no_search,
                                  cached_series=[cached])
    assert found is cached
    assert checks == [("Cached Show", 788, "2024")]


def test_tmdb_series_search_validates_only_plausible_loaded_candidates():
    old = SimpleNamespace(title="Remake", year="2003", sample_slug="old", seasons={1: [1]})
    actual = SimpleNamespace(title="Remake", year="2026", sample_slug="actual", seasons={1: [1]})
    checked = []
    tmdb = SimpleNamespace(
        series_by_id=lambda _: {"title": "Remake", "year": "2026"},
        series_matches_id=lambda title, identity, year: checked.append((title, year)) or year == "2026",
    )
    loaded = []
    def search(provider, title):
        return [old, SimpleNamespace(title="Wrong Title", year="2026", sample_slug="wrong"),
                actual]
    def load(provider, slug):
        loaded.append(slug)
        return actual
    assert resolve_person_series(tmdb, 777, ["serienstream"], search, load) is actual
    assert loaded == ["actual"]
    assert checked == [("Remake", "2026")]


def test_progressive_tmdb_series_uses_non_blocking_shared_resolver_with_deferred_checks():
    app = FastAPI()
    observed = []

    async def enrich(identity, work, *, progressive):
        observed.append((identity, progressive))
        return {"title": "Ready", "seasons": []}

    app.include_router(create_people_router(lambda: SimpleNamespace(configured=True), enrich_series=enrich))
    client = TestClient(app)
    response = client.get("/api/people/series/8765?progressive=true&defer_checks=true")
    assert response.status_code == 200
    assert response.json()["title"] == "Ready"
    assert observed == [(("people", 8765, False, True), True)]


def test_fast_tv_identity_uses_one_request_and_cached_response(monkeypatch):
    tmdb = TMDBClient("test")
    calls = []

    def fetch(path, params):
        calls.append((path, params))
        return {"id": 81, "name": "Beispiel", "original_name": "Original",
                "first_air_date": "2020-07-04"}

    monkeypatch.setattr(tmdb, "_request", fetch)
    first = tmdb.series_identity_by_id(81)
    second = tmdb.series_identity_by_id(81)
    assert first == second == {
        "title": "Beispiel", "original_title": "Original", "year": "2020",
    }
    assert calls == [("/tv/81", {"language": "de-DE"})]


def test_series_resolution_stops_loading_candidates_after_search_budget():
    elapsed = [0]
    loaded = []
    tmdb = SimpleNamespace(
        series_by_id=lambda _: {"title": "Show", "year": "2024"},
        series_matches_id=lambda *args: False,
    )
    candidates = [SimpleNamespace(title="Show", year="2024", sample_slug=str(i)) for i in range(20)]

    def load(provider, slug):
        loaded.append(slug)
        elapsed[0] += 13
        return SimpleNamespace(title="Show", year="2024", seasons={1: [1]})

    assert resolve_person_series(tmdb, 81, ["fixture"], lambda *args: candidates, load,
                                 clock=lambda: elapsed[0]) is None
    assert loaded == ["0", "1"]


def test_series_resolution_identity_time_counts_towards_search_budget():
    elapsed = [0]

    def identity(_):
        elapsed[0] = 26
        return {"title": "Show", "year": "2024"}

    tmdb = SimpleNamespace(series_by_id=identity)

    def unexpected(*args):
        raise AssertionError("expired identity lookup must not start provider work")

    assert resolve_person_series(tmdb, 81, ["fixture"], unexpected, unexpected,
                                 clock=lambda: elapsed[0]) is None


@pytest.mark.parametrize(("title", "provider_title"), [
    ("S.W.A.T.", "SWAT"), ("Die Brücke", "Die Brucke"), ("Marvel's Show", "Marvels Show"),
])
def test_series_prefilter_preserves_existing_tmdb_title_normalization(monkeypatch, title, provider_title):
    tmdb = TMDBClient("fixture")

    def request(path, params):
        if path == "/tv/42":
            return {"id": 42, "name": title, "first_air_date": "2024-01-01"}
        assert path == "/search/tv"
        return {"results": [{"id": 42, "name": title, "first_air_date": "2024-01-01"}]}

    monkeypatch.setattr(tmdb, "_request", request)
    # This title already passes the established exact-ID/year verifier.
    assert tmdb.series_matches_id(provider_title, 42, "2024")
    candidate = SimpleNamespace(title=provider_title, year="2024", sample_slug="fixture:show")
    loaded = SimpleNamespace(title=provider_title, year="2024", seasons={1: [1]})
    assert resolve_person_series(tmdb, 42, ["fixture"], lambda *args: [candidate],
                                 lambda *args: loaded) is loaded
