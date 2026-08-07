from types import SimpleNamespace

import server as app
from jellyfin_client import JellyfinClient
from tmdb_client import TMDBClient


def _movie_result(movie_id, title, year):
    return {
        "id": movie_id,
        "title": title,
        "original_title": title,
        "release_date": f"{year}-01-01",
        "poster_path": None,
        "backdrop_path": None,
        "overview": "",
        "genre_ids": [],
        "vote_average": 7.0,
        "vote_count": 100,
        "popularity": 10.0,
    }


def _series_result(series_id, title, year):
    return {
        "id": series_id,
        "name": title,
        "original_name": title,
        "first_air_date": f"{year}-01-01",
        "poster_path": None,
        "backdrop_path": None,
        "overview": "Beschreibung",
        "genre_ids": [],
        "vote_average": 7.0,
        "vote_count": 100,
        "popularity": 10.0,
    }


def test_movie_tmdb_aliases_recover_localized_subtitle_and_provider_numbering():
    client = TMDBClient("test-key")
    calls = []

    def fake_request(path, params=None):
        params = dict(params or {})
        calls.append((path, params.get("query", "")))
        if path != "/search/movie":
            return None
        if params.get("query") == "Sayara":
            return {"results": [_movie_result(1, "Sayara", "2024")]}
        if params.get("query") == "Transformers: The Last Knight":
            return {
                "results": [
                    _movie_result(2, "Transformers: The Last Knight", "2017")
                ]
            }
        return {"results": []}

    client._request = fake_request

    sayara = client.movie_summary("Sayara - Der Racheengel", "2024")
    transformers = client.movie_summary("Transformers 5: The Last Knight", "2017")

    assert sayara and sayara["tmdb_id"] == 1
    assert transformers and transformers["tmdb_id"] == 2
    assert ("/search/movie", "Sayara") in calls
    assert ("/search/movie", "Transformers: The Last Knight") in calls


def test_series_tmdb_aliases_recover_franchise_separator_variants():
    client = TMDBClient("test-key")
    calls = []

    def fake_request(path, params=None):
        params = dict(params or {})
        calls.append((path, params.get("query", "")))
        if path == "/search/tv":
            query = params.get("query")
            if query == "Der Herr der Ringe: Die Ringe der Macht":
                return {
                    "results": [
                        _series_result(
                            84773,
                            "Der Herr der Ringe: Die Ringe der Macht",
                            "2022",
                        )
                    ]
                }
            if query == "Star Wars: Skeleton Crew":
                return {
                    "results": [
                        _series_result(202879, "Star Wars: Skeleton Crew", "2024")
                    ]
                }
            return {"results": []}
        if path == "/tv/84773":
            return {
                **_series_result(
                    84773, "Der Herr der Ringe: Die Ringe der Macht", "2022"
                ),
                "episode_run_time": [60],
                "genres": [],
                "videos": {"results": []},
                "credits": {"cast": []},
                "seasons": [],
                "created_by": [],
                "networks": [],
                "status": "Returning Series",
            }
        return None

    client._request = fake_request

    rings = client.series("Der Herr der Ringe - Die Ringe der Macht")
    skeleton = client.series_summary("Star Wars - Skeleton Crew")

    assert rings and rings["tmdb_id"] == 84773
    assert skeleton and skeleton["tmdb_id"] == 202879
    assert ("/search/tv", "Der Herr der Ringe: Die Ringe der Macht") in calls
    assert ("/search/tv", "Star Wars: Skeleton Crew") in calls


def test_legacy_royal_hash_name_matches_even_if_jellyfin_metadata_was_wrong():
    client = JellyfinClient()
    items = [
        {
            "name": "Smile.-.Siehst.du.es.auch~c9a270ac",
            "original_title": "",
            "sort_name": "",
            "year": 1999,
            "tmdb_id": "wrong-id",
            "path": "/movies/Smile.-.Siehst.du.es.auch~c9a270ac.mp4",
        }
    ]

    assert client.match(
        "Smile - Siehst du es auch?",
        "2022",
        items=items,
        tmdb_id="correct-id",
    )
    assert not client.match(
        "Smile 2 - Siehst du es auch?",
        "2024",
        items=items,
        tmdb_id="different-id",
    )


def test_stable_jellyfin_tmdb_id_wins_for_existing_canonical_transformers():
    client = JellyfinClient()
    items = [
        {
            "name": "Transformers: The Last Knight",
            "original_title": "Transformers: The Last Knight",
            "sort_name": "Transformers: The Last Knight",
            "year": 2017,
            "tmdb_id": "335988",
            "path": "/movies/Transformers.The.Last.Knight.2017.mkv",
        }
    ]

    assert client.match(
        "Transformers 5: The Last Knight",
        "2017",
        items=items,
        tmdb_id="335988",
    )


def test_future_movie_filename_uses_tmdb_canonical_title_without_hash(monkeypatch):
    client = TMDBClient("test-key")

    def fake_request(path, params=None):
        params = dict(params or {})
        if path == "/search/movie" and params.get("query") == "Transformers: The Last Knight":
            return {
                "results": [
                    _movie_result(335988, "Transformers: The Last Knight", "2017")
                ]
            }
        return {"results": []}

    client._request = fake_request
    monkeypatch.setattr(app.state, "tmdb_client", client)

    filename = app.build_movie_filename("Transformers 5: The Last Knight", "2017")

    assert filename == "Transformers.The.Last.Knight.2017.mp4"
    assert "~" not in filename


def test_old_hashed_movie_file_is_found_locally_without_jellyfin(monkeypatch, tmp_path):
    old_file = tmp_path / "Smile.-.Siehst.du.es.auch~c9a270ac.mp4"
    old_file.write_bytes(b"legacy")
    monkeypatch.setattr(app, "validate_media_file", lambda path: (True, "ok"))
    monkeypatch.setattr(app.state.tmdb_client, "api_key", "")
    movie = SimpleNamespace(title="Smile - Siehst du es auch?", year="")

    found = app._existing_valid_movie_path(tmp_path, movie)

    assert found == old_file


def test_series_folder_identity_ignores_old_hash_suffix():
    assert app._series_folder_key("Star Wars Skeleton Crew~deadbeef") == (
        app._series_folder_key("Star Wars: Skeleton Crew")
    )
