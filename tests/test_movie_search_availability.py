"""Regression tests for complete provider-first movie search."""

from types import SimpleNamespace

import server
from application_services import movie_search_availability as availability


class FakeTMDBClient:
    language = "de-DE"

    def __init__(self, movies, configured=True):
        self.movies = list(movies)
        self.configured = configured
        self.calls = []

    def search_movies(self, query, max_results):
        self.calls.append((query, max_results))
        return [dict(movie) for movie in self.movies]

    def movie_summary(self, _title, _year=""):
        return None


def _movie(tmdb_id, title, year, original_title=""):
    return {
        "tmdb_id": tmdb_id,
        "title": title,
        "original_title": original_title,
        "year": year,
        "cover_url": f"https://img/{tmdb_id}.jpg",
        "backdrop_url": "",
        "description": f"TMDB {title}",
    }


def _candidate(slug, title, year="", provider="moflix", cover_url=""):
    return SimpleNamespace(
        slug=slug,
        title=title,
        year=year,
        provider=provider,
        content_language="de",
        is_movie=True,
        url=f"https://{provider}.example/{slug}",
        cover_url=cover_url,
    )


def _loaded(title, year="", provider="moflix", hosters=True):
    return SimpleNamespace(
        title=title,
        year=year,
        provider=provider,
        content_language="de",
        hosters=[object()] if hosters else [],
        url=f"https://{provider}.example/title",
        cover_url="",
    )


def _configure(monkeypatch, movies, candidates, loader=None, providers=None, configured=True):
    availability._MOVIE_SEARCH_AVAILABILITY_CACHE.clear()
    availability._MOVIE_SEARCH_GROUP_CACHE.clear()
    client = FakeTMDBClient(movies, configured=configured)
    active = list(providers or ["moflix", "filmpalast", "xcine"])
    search_calls = []
    load_calls = []

    monkeypatch.setattr(server, "get_tmdb_client", lambda: client)
    monkeypatch.setattr(server, "provider_priority", lambda _kind: list(active))

    def search(query):
        search_calls.append(query)
        return list(candidates)

    monkeypatch.setattr(server, "search_movie_candidates", search)

    if loader is None:
        by_slug = {
            item.slug: _loaded(item.title, item.year, item.provider)
            for item in candidates
        }

        def fake_loader(slug):
            load_calls.append(slug)
            return by_slug.get(slug)
    else:
        def fake_loader(slug):
            load_calls.append(slug)
            return loader(slug)

    monkeypatch.setattr(availability, "_ORIGINAL_LOAD_MOVIE_FOR_SLUG", fake_loader)
    monkeypatch.setattr(
        server,
        "provider_for_value",
        lambda value: next(
            (
                provider
                for provider in active
                if str(value or "").startswith(f"{provider}:")
            ),
            "",
        ),
    )
    monkeypatch.setattr(server, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.state, "fp_movies", {})
    return client, search_calls, load_calls, active


def test_provider_results_define_complete_star_wars_search(monkeypatch):
    movies = [
        _movie(11, "Star Wars", "1977", "Star Wars"),
        _movie(12, "Das Imperium schlägt zurück", "1980", "The Empire Strikes Back"),
    ]
    candidates = [
        _candidate("moflix:11", "Star Wars", "1977"),
        _candidate("moflix:12", "Das Imperium schlägt zurück", "1980"),
        _candidate("moflix:13", "Die Rückkehr der Jedi-Ritter", "1983"),
        _candidate("moflix:14", "Star Wars: Episode I - Die dunkle Bedrohung", "1999"),
        _candidate("moflix:15", "Rogue One: A Star Wars Story", "2016"),
    ]
    client, search_calls, load_calls, _active = _configure(monkeypatch, movies, candidates)

    results = server._tmdb_search_results("Star Wars")

    assert len(results) == 5
    assert {item["slug"] for item in results} == {item.slug for item in candidates}
    assert "Die Rückkehr der Jedi-Ritter" in {item["title"] for item in results}
    assert all(item["availability"] == "unverified" for item in results)
    assert search_calls == ["Star Wars"]
    assert load_calls == []
    assert client.calls == [("Star Wars", 100)]


def test_provider_only_results_survive_empty_tmdb_search(monkeypatch):
    candidates = [_candidate("moflix:fan-edit", "Star Wars Fan Edit", "2024")]
    _configure(monkeypatch, [], candidates)

    results = server._tmdb_search_results("Star Wars")

    assert len(results) == 1
    assert results[0]["slug"] == "moflix:fan-edit"
    assert results[0]["tmdb_id"] is None
    assert results[0]["metadata_source"] == "provider"


def test_provider_search_service_still_works_when_tmdb_client_is_unconfigured(monkeypatch):
    candidates = [_candidate("moflix:alpha", "Alpha", "2024")]
    client, _search_calls, load_calls, _active = _configure(
        monkeypatch, [], candidates, configured=False
    )

    results = server._tmdb_search_results("Alpha")

    assert [item["slug"] for item in results] == ["moflix:alpha"]
    assert load_calls == []
    assert client.calls == []


def test_same_movie_across_providers_becomes_one_card_with_sources(monkeypatch):
    candidates = [
        _candidate("moflix:alpha", "Alpha", "2024", "moflix"),
        _candidate("filmpalast:alpha", "Alpha", "2024", "filmpalast"),
        _candidate("xcine:alpha", "Alpha", "2024", "xcine"),
    ]
    _configure(monkeypatch, [_movie(1, "Alpha", "2024")], candidates)

    results = server._tmdb_search_results("Alpha")

    assert len(results) == 1
    result = results[0]
    assert result["tmdb_id"] == 1
    assert result["source_count"] == 3
    assert [source["key"] for source in result["sources"]] == [
        "moflix", "filmpalast", "xcine",
    ]
    assert not any(source["verified"] for source in result["sources"])


def test_same_title_different_years_stays_separate(monkeypatch):
    candidates = [
        _candidate("moflix:thing-1982", "The Thing", "1982"),
        _candidate("moflix:thing-2011", "The Thing", "2011"),
    ]
    movies = [
        _movie(10, "The Thing", "1982"),
        _movie(11, "The Thing", "2011"),
    ]
    _configure(monkeypatch, movies, candidates)

    results = server._tmdb_search_results("The Thing")

    assert {(item["title"], item["year"]) for item in results} == {
        ("The Thing", "1982"),
        ("The Thing", "2011"),
    }


def test_yearless_hit_merges_when_only_one_year_is_known(monkeypatch):
    candidates = [
        _candidate("moflix:alpha", "Alpha", "2024", "moflix"),
        _candidate("filmpalast:alpha", "Alpha", "", "filmpalast"),
    ]
    _configure(monkeypatch, [], candidates)

    results = server._tmdb_search_results("Alpha")

    assert len(results) == 1
    assert results[0]["year"] == "2024"
    assert results[0]["source_count"] == 2


def test_ambiguous_yearless_hit_is_not_attached_to_wrong_remake(monkeypatch):
    candidates = [
        _candidate("moflix:thing-1982", "The Thing", "1982", "moflix"),
        _candidate("filmpalast:thing-2011", "The Thing", "2011", "filmpalast"),
        _candidate("xcine:thing", "The Thing", "", "xcine"),
    ]
    _configure(monkeypatch, [], candidates)

    results = server._tmdb_search_results("The Thing")

    assert len(results) == 3
    assert {item["slug"] for item in results} == {item.slug for item in candidates}


def test_roman_and_numeric_suffixes_deduplicate(monkeypatch):
    candidates = [
        _candidate("moflix:rocky-ii", "Rocky II", "1979", "moflix"),
        _candidate("filmpalast:rocky-2", "Rocky 2", "1979", "filmpalast"),
    ]
    _configure(monkeypatch, [], candidates)

    results = server._tmdb_search_results("Rocky")

    assert len(results) == 1
    assert results[0]["source_count"] == 2


def test_localized_provider_titles_coalesce_when_tmdb_proves_identity(monkeypatch):
    candidates = [
        _candidate("moflix:shawshank", "Die Verurteilten", "1994", "moflix"),
        _candidate(
            "filmpalast:shawshank",
            "The Shawshank Redemption",
            "1994",
            "filmpalast",
        ),
    ]
    movies = [_movie(278, "Die Verurteilten", "1994", "The Shawshank Redemption")]
    _configure(monkeypatch, movies, candidates)

    results = server._tmdb_search_results("Verurteilten")

    assert len(results) == 1
    assert results[0]["tmdb_id"] == 278
    assert results[0]["source_count"] == 2


def test_search_keeps_group_even_when_no_source_has_usable_hosters(monkeypatch):
    candidates = [
        _candidate("moflix:alpha", "Alpha", "2024", "moflix"),
        _candidate("filmpalast:alpha", "Alpha", "2024", "filmpalast"),
    ]
    _client, _search_calls, load_calls, _active = _configure(
        monkeypatch,
        [],
        candidates,
        loader=lambda slug: _loaded(
            "Alpha", "2024", slug.split(":", 1)[0], hosters=False
        ),
    )

    results = server._tmdb_search_results("Alpha")

    assert len(results) == 1
    assert results[0]["slug"] == "moflix:alpha"
    assert load_calls == []


def test_lazy_resolution_falls_through_to_next_provider(monkeypatch):
    candidates = [
        _candidate("moflix:alpha", "Alpha", "2024", "moflix"),
        _candidate("filmpalast:alpha", "Alpha", "2024", "filmpalast"),
    ]

    def loader(slug):
        if slug == "moflix:alpha":
            return _loaded("Alpha", "2024", "moflix", hosters=False)
        return _loaded("Alpha", "2024", "filmpalast", hosters=True)

    _client, _search_calls, load_calls, _active = _configure(
        monkeypatch, [], candidates, loader=loader
    )

    results = server._tmdb_search_results("Alpha")
    assert [item["slug"] for item in results] == ["moflix:alpha"]
    assert load_calls == []

    loaded = server.load_movie_for_slug("moflix:alpha")

    assert loaded is not None
    assert loaded.provider == "filmpalast"
    assert load_calls == ["moflix:alpha", "filmpalast:alpha"]
    assert server.state.fp_movies["moflix:alpha"] is loaded
    assert server.state.fp_movies["filmpalast:alpha"] is loaded


def test_lazy_resolution_returns_none_only_after_all_group_sources_fail(monkeypatch):
    candidates = [
        _candidate("moflix:alpha", "Alpha", "2024", "moflix"),
        _candidate("filmpalast:alpha", "Alpha", "2024", "filmpalast"),
    ]
    _client, _search_calls, load_calls, _active = _configure(
        monkeypatch,
        [],
        candidates,
        loader=lambda slug: _loaded(
            "Alpha", "2024", slug.split(":", 1)[0], hosters=False
        ),
    )

    assert len(server._tmdb_search_results("Alpha")) == 1
    assert server.load_movie_for_slug("moflix:alpha") is None
    assert load_calls == ["moflix:alpha", "filmpalast:alpha"]


def test_explicit_alternate_source_is_tried_before_other_group_sources(monkeypatch):
    candidates = [
        _candidate("moflix:alpha", "Alpha", "2024", "moflix"),
        _candidate("filmpalast:alpha", "Alpha", "2024", "filmpalast"),
    ]
    _client, _search_calls, load_calls, _active = _configure(monkeypatch, [], candidates)

    server._tmdb_search_results("Alpha")
    loaded = server.load_movie_for_slug("filmpalast:alpha")

    assert loaded is not None
    assert loaded.provider == "filmpalast"
    assert load_calls == ["filmpalast:alpha"]


def test_non_search_slug_remains_transparent_pass_through(monkeypatch):
    candidates = [_candidate("moflix:alpha", "Alpha", "2024")]
    _client, _search_calls, load_calls, _active = _configure(monkeypatch, [], candidates)

    loaded = server.load_movie_for_slug("moflix:direct")

    assert loaded is None
    assert load_calls == ["moflix:direct"]


def test_tmdb_result_limit_never_caps_provider_result_count(monkeypatch):
    candidates = [
        _candidate(f"moflix:sw-{index}", f"Star Wars Story {index}", str(1980 + index))
        for index in range(45)
    ]
    _configure(monkeypatch, [_movie(1, "Star Wars Story 0", "1980")], candidates)

    results = server._tmdb_search_results("Star Wars")

    assert len(results) == 45


def test_cached_results_are_deep_copies_and_do_not_trigger_detail_loading(monkeypatch):
    candidates = [
        _candidate("moflix:alpha", "Alpha", "2024", "moflix"),
        _candidate("filmpalast:alpha", "Alpha", "2024", "filmpalast"),
    ]
    client, search_calls, load_calls, _active = _configure(monkeypatch, [], candidates)

    first = server._tmdb_search_results("Alpha")
    first[0]["title"] = "mutated"
    first[0]["sources"][0]["label"] = "mutated"
    second = server._tmdb_search_results("Alpha")

    assert second[0]["title"] == "Alpha"
    assert second[0]["sources"][0]["label"] != "mutated"
    assert search_calls == ["Alpha"]
    assert load_calls == []
    assert client.calls == [("Alpha", 100)]


def test_cache_key_changes_with_active_provider_configuration(monkeypatch):
    candidates = [_candidate("moflix:alpha", "Alpha", "2024", "moflix")]
    client, search_calls, _load_calls, active = _configure(
        monkeypatch, [], candidates, providers=["moflix"]
    )

    server._tmdb_search_results("Alpha")
    active.append("filmpalast")
    server._tmdb_search_results("Alpha")

    assert search_calls == ["Alpha", "Alpha"]
    assert client.calls == [("Alpha", 100), ("Alpha", 100)]
