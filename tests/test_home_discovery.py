"""Active home discovery must remain user-scoped, bounded and provider-independent."""
from types import SimpleNamespace

from features.home_discovery import HomeDiscoveryService, discover_home_candidates


class FakeTMDB:
    configured = True
    language = "de-DE"

    def __init__(self):
        self.calls = []

    def _request(self, path, params):
        self.calls.append((path, params))
        return {"results": [
            {"id": 101, "title": "Tiefes Geheimnis", "genre_ids": [53],
             "poster_path": "/101.jpg", "vote_average": 8.1,
             "vote_count": 800, "overview": "Eine spannungsgeladene Geschichte."},
            {"id": 102, "title": "Kein Interesse", "genre_ids": [53],
             "poster_path": "/102.jpg", "vote_average": 7.1,
             "vote_count": 300},
        ]}

    def _poster_url(self, path):
        return "https://image.tmdb.org/t/p/w500" + path

    def _backdrop_url(self, path):
        return "https://image.tmdb.org/t/p/w1280" + path


def _profile(blocked=()):
    return {"dimensions": {"genres": {"Thriller": 12, "Action": -5}},
            "blocked_items": list(blocked), "confidence": 0.05}


def test_home_discovery_searches_tmdb_with_only_genre_ids_and_hides_blocked():
    client = FakeTMDB()
    results = discover_home_candidates(_profile(["movie:tmdb:102"]), client,
                                       day="2026-10-19")
    assert [row["item"]["tmdb_id"] for row in results] == [101]
    assert results[0]["item"]["tmdb_discovery"] is True
    assert results[0]["item"]["discovery_reason"] == ["Thriller"]
    assert len(client.calls) <= 3
    assert all("with_genres" in params for _path, params in client.calls)
    assert all("user" not in params for _path, params in client.calls)


def test_home_discovery_skips_empty_profiles_and_missing_tmdb():
    assert discover_home_candidates({"dimensions": {}}, FakeTMDB()) == []
    assert discover_home_candidates(_profile(), SimpleNamespace(configured=False)) == []


def test_home_discovery_cache_is_per_user_and_invalidated_on_feedback():
    client = FakeTMDB()
    service = HomeDiscoveryService(clock=lambda: 1000)
    one = service.get("user-one", _profile(), client)
    requests = len(client.calls)
    assert one["results"]
    service.get("user-one", _profile(), client)
    assert len(client.calls) == requests
    service.get("user-two", _profile(), client)
    assert len(client.calls) > requests
    updated = service.get("user-one", _profile(["movie:tmdb:101"]), client)
    assert not any(row["item"]["tmdb_id"] == 101 for row in updated["results"])

def test_recently_opened_tmdb_idea_is_not_repeated_for_two_weeks():
    import time
    client = FakeTMDB()
    profile = _profile()
    profile["recent"] = [{"key": "movie:tmdb:101", "at": time.time(), "action": "open"}]
    results = discover_home_candidates(profile, client, day="2026-10-19")
    assert [row["item"]["tmdb_id"] for row in results] == [102]
    service = HomeDiscoveryService(clock=lambda: 1000)
    first = service.get("one", _profile(), client)
    second = service.get("one", profile, client)
    assert len(first["results"]) == 2
    assert len(second["results"]) == 1
