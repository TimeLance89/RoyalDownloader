"""Offline product scenarios, independent of external services and Ollama."""
import time
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event

import pytest

import features.home_discovery as discovery
from features.home_taste import home_profile
from features.taste_profile import TasteProfileStore
from tests.test_home_discovery import FakeTMDB, _profile


def test_five_favorites_survive_one_curiosity_click_and_restart(tmp_path):
    now = [1_800_000_000.0]
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: now[0])
    store.seed_onboarding([{"item_key": f"movie:{i}", "media_type": "movie",
                            "metadata": {"genres": ["Horror"]}} for i in range(5)])
    store.record_event("open", item_key="movie:comedy", media_type="movie",
                       metadata={"genres": ["Comedy"]})
    profile = store.public_profile()
    assert profile["dimensions"]["genres"]["Horror"] > 10 * profile["dimensions"]["genres"]["Komödie"]
    assert profile["home_preferences"]["short_term"]["genres"]["Komödie"] <= 1
    restarted = TasteProfileStore(store.path, clock=lambda: now[0])
    assert restarted.public_profile()["home_preferences"] == profile["home_preferences"]
    now[0] += 29 * 86400
    assert not restarted.public_profile()["home_preferences"]["short_term"]


def test_media_specific_taste_separates_film_and_series_interests(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json")
    store.set_feedback("movie:one", "like", media_type="movie", metadata={"genres": ["Horror"]})
    store.set_feedback("series:one", "like", media_type="series", metadata={"genres": ["Drama"]})
    profile = store.public_profile()
    movie = home_profile(profile, "movie")["dimensions"]["genres"]
    series = home_profile(profile, "series")["dimensions"]["genres"]
    assert movie["Horror"] > movie["Drama"]
    assert series["Drama"] > series["Horror"]


def test_recent_clicks_never_cancel_explicit_negative_genres():
    profile = {"dimensions": {"genres": {"Komödie": -10}}, "home_preferences": {
        "short_term": {"genres": {"Komödie": 100}},
        "by_media_type": {"movie": {"genres": {"Komödie": 50}}}}}
    assert home_profile(profile, "movie")["dimensions"]["genres"]["Komödie"] == -10


def test_series_only_profile_does_not_spend_requests_on_rejected_films():
    client = FakeTMDB()
    profile = _profile()
    profile["dimensions"].update(genres={"Drama": 12}, media_types={"series": 25, "movie": -10})
    discovery.discover_home_candidates(profile, client)
    assert client.calls and all(path == "/discover/tv" for path, _ in client.calls)


@pytest.mark.parametrize("bad", [None, 4, "broken", {"id": 8}])
def test_malformed_result_container_fails_closed(bad):
    class Client(FakeTMDB):
        def _request(self, path, params):
            return {"results": bad}
    assert discovery.discover_home_candidates(_profile(), Client()) == []


@pytest.mark.parametrize("bad", [None, 53, "53", {"genre": 53}])
def test_malformed_genres_preserve_other_candidates(bad):
    class Client(FakeTMDB):
        def _request(self, path, params):
            payload = super()._request(path, params)
            payload["results"][0]["genre_ids"] = bad
            return payload
    assert [row["item"]["tmdb_id"] for row in discovery.discover_home_candidates(_profile(), Client())] == [102]


def test_cache_response_mutation_cannot_change_another_browser_result():
    service = discovery.HomeDiscoveryService()
    client = FakeTMDB()
    first = service.get("user", _profile(), client)
    first["results"][0]["item"]["title"] = "mutated"
    assert service.get("user", _profile(), client)["results"][0]["item"]["title"] != "mutated"


def test_timed_out_follower_does_not_start_duplicate_tmdb_work():
    started, release = Event(), Event()
    class Client(FakeTMDB):
        def _request(self, path, params):
            started.set()
            release.wait(2)
            return super()._request(path, params)
    service = discovery.HomeDiscoveryService(wait_seconds=0.01)
    client = Client()
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(service.get, "user", _profile(), client)
        try:
            assert started.wait(1)
            assert service.get("user", _profile(), client)["results"] == []
        finally:
            release.set()
        assert owner.result(2)["results"]
    assert len(client.calls) == 1


def test_slow_external_request_is_bounded_and_can_recover(monkeypatch):
    release = Event()
    started = Event()
    class Client(FakeTMDB):
        def _request(self, path, params):
            started.set()
            release.wait(2)
            return super()._request(path, params)
    monkeypatch.setattr(discovery, "FETCH_SECONDS", 0.03)
    before = time.monotonic()
    try:
        assert discovery.discover_home_candidates(_profile(), Client()) == []
        assert started.is_set()
        assert time.monotonic() - before < 0.5
    finally:
        release.set()


def test_director_recommendations_exclude_other_crew_jobs():
    class Client(FakeTMDB):
        def _request(self, path, params):
            if path == "/search/person":
                return {"results": [{"id": 88, "name": "The Director"}]}
            payload = super()._request(path, params)
            return {"crew": [dict(payload["results"][0], job="Producer"),
                             dict(payload["results"][1], job="Director")]}
    profile = {"dimensions": {"directors": {"The Director": 12}}}
    rows = discovery.discover_home_candidates(profile, Client())
    assert [row["item"]["tmdb_id"] for row in rows] == [102]


def test_partial_outage_retries_without_losing_healthy_candidates():
    now = [1000.0]
    class Client(FakeTMDB):
        offline = True
        def _request(self, path, params):
            if path == "/discover/movie" and self.offline:
                self.calls.append((path, params))
                raise TimeoutError("partial outage")
            payload = super()._request(path, params)
            if path == "/discover/tv":
                for item in payload["results"]:
                    item["genre_ids"] = [18]
            return payload
    client = Client()
    profile = _profile()
    profile["dimensions"]["genres"]["Drama"] = 6
    service = discovery.HomeDiscoveryService(clock=lambda: now[0])
    first = service.get("user", profile, client)
    assert first["results"] and first["degraded"]
    client.offline = False
    now[0] += 301
    recovered = service.get("user", profile, client)
    assert not recovered["degraded"]
    assert any(row["kind"] == "movie" for row in recovered["results"])


def test_explicit_like_can_seed_related_discovery(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json")
    store.set_feedback("movie:tmdb:101", "like", media_type="movie", metadata={"genres": ["Thriller"]})
    client = FakeTMDB()
    discovery.discover_home_candidates(store.public_profile(), client)
    assert any(path == "/movie/101/recommendations" for path, _ in client.calls)
    assert len(client.calls) <= 3


def test_series_person_interest_uses_television_credits():
    class Client(FakeTMDB):
        def _request(self, path, params):
            self.calls.append((path, params))
            if path == "/search/person":
                return {"results": [{"id": 88, "name": "TV Actor"}]}
            return {"cast": [{"id": 555, "name": "A Series", "genre_ids": [18],
                              "poster_path": "/series.jpg", "vote_average": 8, "vote_count": 100}]}
    client = Client()
    profile = {"dimensions": {"actors": {"TV Actor": 20}, "media_types": {"series": 20, "movie": -10}}}
    rows = discovery.discover_home_candidates(profile, client)
    assert [row["kind"] for row in rows] == ["series"]
    assert any(path == "/person/88/tv_credits" for path, _ in client.calls)


def test_profile_reads_do_not_bypass_cache_as_taste_decays(tmp_path):
    now = [1_800_000_000.0]
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: now[0])
    store.set_feedback("movie:tmdb:700", "like", media_type="movie", metadata={"genres": ["Thriller"]})
    client = FakeTMDB()
    service = discovery.HomeDiscoveryService(clock=lambda: now[0])
    first = service.get("user", store.public_profile(), client)
    calls = len(client.calls)
    now[0] += 120
    assert service.get("user", store.public_profile(), client) == first
    assert len(client.calls) == calls
    store.set_feedback("movie:tmdb:101", "dislike")
    second = service.get("user", store.public_profile(), client)
    assert not any(row["item"]["tmdb_id"] == 101 for row in second["results"])
    assert len(client.calls) > calls


def test_external_work_admission_is_bounded_and_releases_capacity(monkeypatch):
    gate = BoundedSemaphore(2)
    monkeypatch.setattr(discovery, "_PENDING_REQUESTS", gate)
    release = Event()
    completed = [Event(), Event()]
    futures = []
    try:
        for done in completed:
            future = discovery._submit(lambda: release.wait(2))
            assert future is not None
            future.add_done_callback(lambda _, event=done: event.set())
            futures.append(future)
        assert discovery._submit(lambda: pytest.fail("excess work must not execute")) is None
    finally:
        release.set()
        for future in futures:
            future.result(2)
        for event in completed:
            assert event.wait(1)
    assert gate.acquire(blocking=False)
    assert gate.acquire(blocking=False)
    assert not gate.acquire(blocking=False)
    gate.release()
    gate.release()
