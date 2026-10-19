"""Deterministic offline relevance guardrails for the Home recommendation feed."""
from collections import Counter
from features.home_discovery import discover_home_candidates

class ScenarioTMDB:
    configured = True
    language = "de-DE"

    def __init__(self):
        self.calls = []

    def _request(self, path, params):
        self.calls.append((path, params))
        candidates = [
            {"id": idx, "title": f"Thriller {idx}", "genre_ids": [53],
             "poster_path": f"/{idx}.jpg", "vote_average": 8.1,
             "vote_count": 700}
            for idx in range(1, 17)
        ]
        candidates.extend({"id": idx, "title": f"Drama {idx}",
                           "genre_ids": [18], "poster_path": f"/{idx}.jpg",
                           "vote_average": 8.0, "vote_count": 600}
                          for idx in range(17, 25))
        candidates.extend({"id": idx, "title": f"Horror {idx}",
                           "genre_ids": [27], "poster_path": f"/{idx}.jpg",
                           "vote_average": 9.9, "vote_count": 2000}
                          for idx in range(25, 29))
        return {"results": candidates}

    def _poster_url(self, path):
        return "https://image.tmdb.org/t/p/w500" + path

    def _backdrop_url(self, path):
        return "https://image.tmdb.org/t/p/w1280" + path


def _profile():
    return {"dimensions": {"genres": {"Thriller": 13, "Drama": 8, "Horror": -70}},
            "confidence": .6, "blocked_items": ["movie:tmdb:4"], "recent": []}


def test_discovery_favors_personal_matches_over_high_rating_and_excludes_dislikes():
    client = ScenarioTMDB()
    results = discover_home_candidates(_profile(), client, day="2026-10-19", limit=16)
    titles = [entry["item"] for entry in results]
    assert len(titles) == 16
    assert len({(entry["kind"], entry["item"]["tmdb_id"]) for entry in results}) == 16
    assert not any("Horror" in title["genres"] for title in titles)
    assert not any(title["tmdb_id"] == 4 for title in titles)
    assert all(title["tmdb_discovery"] is True for title in titles)
    assert all(title["discovery_reason"] for title in titles)
    assert len(client.calls) <= 3
    assert all("user" not in params for _path, params in client.calls)


def test_discovery_has_diversity_without_starving_a_strong_genre():
    results = discover_home_candidates(_profile(), ScenarioTMDB(), day="2026-10-19", limit=16)
    first_twelve = Counter(entry["item"]["genres"][0] for entry in results[:12])
    assert first_twelve["Drama"] >= 4, "alternative matches must beat a mono-genre feed"
    assert len(results) == 16, "diversity limit must not withhold good recommendations"


def test_discovery_is_repeatable_for_the_same_profile_and_day():
    one = discover_home_candidates(_profile(), ScenarioTMDB(), day="2026-10-19")
    two = discover_home_candidates(_profile(), ScenarioTMDB(), day="2026-10-19")
    assert one == two
