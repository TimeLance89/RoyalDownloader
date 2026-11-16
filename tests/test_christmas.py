from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from features.christmas import BERLIN, ChristmasService, christmas_evidence, daily_selection
from api.api_christmas_router import create_christmas_router


def movie(number):
    return {"tmdb_id": number, "title": f"Weihnachtsfilm {number}", "genre_ids": [10751],
            "cover_url": "/poster.jpg"}


@pytest.fixture
def season(tmp_path, monkeypatch):
    now = [datetime(2026, 11, 24, 12, tzinfo=BERLIN)]
    service = ChristmasService(tmp_path / "christmas.sqlite", clock=lambda: now[0])
    calls = []

    def discover(client, today):
        if client is None:
            return []
        calls.append(today)
        return [movie(i) for i in range(1, 65)]

    monkeypatch.setattr(service, "discover", discover)
    return service, now, calls


@pytest.mark.parametrize(("date", "calendar", "carousel", "unlocked"), [
    ("2026-11-09", False, False, 0), ("2026-11-10", False, True, 0),
    ("2026-11-23", False, True, 0), ("2026-11-24", False, True, 0),
    ("2026-12-01", True, True, 1), ("2026-12-09", True, True, 9),
    ("2026-12-10", True, True, 10), ("2026-12-24", True, True, 24),
    ("2026-12-30", True, True, 24), ("2026-12-31", False, False, 0),
    ("2027-01-01", False, False, 0),
])
def test_windows_and_server_date(season, date, calendar, carousel, unlocked):
    service, now, _ = season
    now[0] = datetime.fromisoformat(date).replace(tzinfo=BERLIN)
    result = service.status("alice", object())
    assert (result["calendar_active"], result["carousel_active"], result["unlocked"]) == (calendar, carousel, unlocked)


def test_calendar_is_immutable_survives_restart_and_differs_next_year(season):
    service, now, calls = season
    first = service.status("alice", object())["manifest"]
    assert len(first) == 24
    assert len({item["tmdb_id"] for item in first}) == 24
    now[0] = datetime(2026, 12, 20, tzinfo=BERLIN)
    restarted = ChristmasService(service.path, clock=lambda: now[0])
    assert restarted.status("alice", None)["manifest"] == first
    assert len(calls) == 1
    assert service.status("bob", None)["manifest"] != first
    now[0] = datetime(2027, 11, 24, tzinfo=BERLIN)
    assert service.status("alice", object())["manifest"] != first


def test_future_locked_past_days_catchup_and_concurrent_open_idempotent(season):
    service, now, _ = season
    service.status("alice", object())
    with pytest.raises(ValueError):
        service.open("alice", 1)
    now[0] = datetime(2026, 12, 12, tzinfo=BERLIN)
    with pytest.raises(ValueError):
        service.open("alice", 13)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.open("alice", 2), range(8)))
    assert all(item == results[0] for item in results)
    service.open("alice", 12)
    assert service.status("alice", None)["opened"] == [2, 12]
    assert service.status("bob", None)["opened"] == []


def test_dec31_purges_current_year_and_rejects_opening(season):
    service, now, _ = season
    service.status("alice", object())
    now[0] = datetime(2026, 12, 31, tzinfo=BERLIN)
    assert service.status("alice", None)["manifest"] == []
    with service.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM calendars").fetchone()[0] == 0
    with pytest.raises(ValueError):
        service.open("alice", 24)


def test_rotation_is_daily_stable_mixed_and_not_winter_only():
    assert christmas_evidence({"Name": "Die Weihnachtsfeier"})
    assert christmas_evidence({"Name": "A quiet day", "Overview": "The family reunites for Christmas."})
    assert not christmas_evidence({"Name": "Winterurlaub", "Overview": "Schnee und Berge im Dezember."})
    movies = [movie(i) for i in range(30)]
    episodes = [{"id": f"episode-{i}", "kind": "episode"} for i in range(4)]
    today = daily_selection(movies, episodes, "2026-12-12")
    assert today == daily_selection(movies, episodes, "2026-12-12")
    assert today != daily_selection(movies, episodes, "2026-12-13")
    assert len(today) == 12 and any(item.get("kind") == "episode" for item in today)


def test_partial_discovery_does_not_freeze_incomplete_calendar(season, monkeypatch):
    service, _, _ = season
    monkeypatch.setattr(service, "discover", lambda *_: [movie(1)])
    assert service.status("alice", object())["preparing"]
    with service.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM calendars").fetchone()[0] == 0


def test_http_date_and_owner_cannot_be_overridden(season):
    service, now, _ = season
    service.status("alice", object())
    now[0] = datetime(2026, 12, 12, tzinfo=BERLIN)
    backend = SimpleNamespace(
        current_user=lambda *_: {"id": "alice", "enabled": True},
        state=SimpleNamespace(jellyfin_cache_lock=__import__("threading").Lock(), jellyfin_cfg={}))
    app = FastAPI()
    app.include_router(create_christmas_router(backend, service=service))
    with TestClient(app) as client:
        assert client.post("/api/home/christmas/doors/13",
                           json={"server_date": "2026-12-24"}).status_code == 403
        assert client.post("/api/home/christmas/doors/2", headers={"X-Royal-Profile": "bob"}).status_code == 409
        assert client.post("/api/home/christmas/doors/2").json()["day"] == 2
        assert client.post("/api/home/christmas/doors/2").json()["day"] == 2


def test_read_only_status_does_not_wait_for_provider_preparation(season):
    service, _, _ = season
    with service.preparation:
        with ThreadPoolExecutor(max_workers=1) as pool:
            # A Home request must remain fast while the provider is fetching films.
            result = pool.submit(service.status, "alice", None).result(timeout=1)
    assert result["preparing"] and result["manifest"] == []


def test_release_uses_berlin_midnight_not_utc(season):
    service, now, _ = season
    service.status("alice", object())
    now[0] = datetime(2026, 11, 30, 23, 1, tzinfo=timezone.utc)
    assert service.status("alice", None)["unlocked"] == 1
    assert service.open("alice", 1)["server_date"] == "2026-12-01"
    with pytest.raises(ValueError):
        service.open("alice", 2)


def test_discovery_requires_exact_christmas_keywords_and_filters_adult():
    calls = []
    def request(path, params):
        calls.append((path, params))
        if path == "/search/keyword":
            return {"results": [{"id": 42, "name": "christmas"}, {"id": 43, "name": "not christmas"}]}
        return {"results": [
            {"id": 1, "title": "Season film", "poster_path": "/one.jpg", "adult": False},
            {"id": 2, "title": "Adult", "poster_path": "/two.jpg", "adult": True},
        ]}
    client = SimpleNamespace(configured=True, _request=request, _poster_url=lambda p: p,
                             _backdrop_url=lambda p: p)
    films = ChristmasService.discover(client, datetime(2026, 11, 24).date())
    assert [film["tmdb_id"] for film in films] == [1]
    discoveries = [params for path, params in calls if path == "/discover/movie"]
    assert len(discoveries) == 4
    assert all(params["with_keywords"] == "42" and params["include_adult"] == "false"
               for params in discoveries)
