import threading
import time
from types import SimpleNamespace

import server  # noqa: F401 - registers the application-service composition root
import application_services.jellyfin_live as live


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _state(**overrides):
    values = {
        "jellyfin_cache_lock": threading.RLock(),
        "jellyfin_config_generation": 7,
        "jellyfin_cfg": {"user_id": "user-1"},
        "jellyfin_movie_data_generation": 0,
        "jellyfin_episode_data_generation": 0,
        "jellyfin_library": [{"id": "old-movie"}],
        "jellyfin_library_time": 1.0,
        "jellyfin_library_available": True,
        "jellyfin_library_retry_after": 0.0,
        "jellyfin_movie_identities": [{"id": "old-movie"}],
        "jellyfin_movie_identities_time": 1.0,
        "jellyfin_movie_identities_available": True,
        "jellyfin_movie_identities_retry_after": 0.0,
        "jellyfin_episodes": [{"id": "old-episode", "series_id": "series-1"}],
        "jellyfin_episodes_time": 1.0,
        "jellyfin_episodes_available": True,
        "jellyfin_episodes_retry_after": 0.0,
        "jellyfin_series": [{"id": "series-1"}],
        "jellyfin_series_time": 1.0,
        "jellyfin_series_available": True,
        "jellyfin_series_retry_after": 0.0,
        "jellyfin_user_episodes": [{"id": "old-user-episode"}],
        "jellyfin_user_episodes_time": 1.0,
        "jellyfin_user_episodes_available": True,
        "jellyfin_user_episodes_retry_after": 0.0,
        "jellyfin_targeted_episodes": {},
        "jellyfin_live_stale": False,
        "jellyfin_live_checked_at": time.time(),
        "automation": {"check_interval_min": 30},
        "watchlist_lock": threading.RLock(),
        "watchlist": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_live_probe_is_one_bounded_page(monkeypatch):
    calls = []

    def fake_get(url, *, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return _Response({
            "Items": [
                {"Id": "episode-2", "Type": "Episode", "DateCreated": "2026-08-21T05:00:00Z"},
                {"Id": "movie-1", "Type": "Movie", "DateCreated": "2026-08-21T04:00:00Z"},
            ],
            "TotalRecordCount": 502,
        })

    monkeypatch.setattr(live.requests, "get", fake_get)
    client = SimpleNamespace(
        configured=True,
        base_url="http://jellyfin:8096",
        api_key="secret",
        timeout=5.0,
    )

    first = live._probe_library_revision(client)
    second = live._probe_library_revision(client)

    assert first == second
    assert len(calls) == 2
    url, params, headers, timeout = calls[0]
    assert url == "http://jellyfin:8096/Items"
    assert params["Limit"] == str(live._LIVE_PROBE_LIMIT)
    assert int(params["Limit"]) <= 20
    assert params["StartIndex"] == "0"
    assert params["IncludeItemTypes"] == "Movie,Series,Episode"
    assert params["EnableTotalRecordCount"] == "true"
    assert headers["X-Emby-Token"] == "secret"
    assert timeout == 5.0


def test_shared_snapshot_refreshes_all_core_indexes_once_and_clears_targeted(monkeypatch):
    fake_state = _state(jellyfin_targeted_episodes={"series-1": {"items": [1]}})
    monkeypatch.setattr(live, "state", fake_state)
    calls = {"movies": 0, "series": 0, "episodes": 0, "user": 0}

    class Client:
        configured = True

        def list_movies(self):
            calls["movies"] += 1
            return [{
                "id": "movie-1", "name": "Dune", "original_title": "Dune",
                "sort_name": "Dune", "year": 2021, "tmdb_id": "438631",
                "quality_rank": 2160, "path": "/movies/Dune.mkv",
            }]

        def list_series(self):
            calls["series"] += 1
            return [{"id": "series-1", "name": "Dark", "tmdb_id": "70523"}]

        def list_episodes(self):
            calls["episodes"] += 1
            return [{"id": "ep-1", "series_id": "series-1", "season": 1, "episode": 1}]

        def list_episodes_with_user_data(self, user_id):
            assert user_id == "user-1"
            calls["user"] += 1
            return [{"id": "ep-1", "series_id": "series-1", "played": True}]

    assert live._refresh_snapshot(Client()) is True

    assert calls == {"movies": 1, "series": 1, "episodes": 1, "user": 1}
    assert fake_state.jellyfin_library[0]["quality_rank"] == 2160
    assert fake_state.jellyfin_movie_identities == [{
        "id": "movie-1", "name": "Dune", "original_title": "Dune",
        "sort_name": "Dune", "year": 2021, "tmdb_id": "438631",
    }]
    assert fake_state.jellyfin_series[0]["id"] == "series-1"
    assert fake_state.jellyfin_episodes[0]["id"] == "ep-1"
    assert fake_state.jellyfin_targeted_episodes == {}
    assert fake_state.jellyfin_live_stale is False


def test_immediate_cached_read_never_calls_blocking_legacy(monkeypatch):
    fake_state = _state(jellyfin_movie_identities=[{"id": "cached"}])
    monkeypatch.setattr(live, "state", fake_state)
    refreshes = []
    monkeypatch.setattr(live, "request_jellyfin_live_refresh", lambda **kwargs: refreshes.append(kwargs))
    monkeypatch.setattr(
        live,
        "backend_value",
        lambda name: (lambda: SimpleNamespace(configured=True)) if name == "get_jellyfin_client" else None,
    )

    def blocking_legacy(*_args, **_kwargs):
        raise AssertionError("cached interactive read must not call Jellyfin")

    started = time.monotonic()
    value = live._cached_snapshot("jellyfin_movie_identities", False, blocking_legacy)
    elapsed = time.monotonic() - started

    assert value == [{"id": "cached"}]
    assert elapsed < 0.05
    assert refreshes == []


def test_nonblocking_stale_read_returns_last_state_and_schedules_background_refresh(monkeypatch):
    fake_state = _state(
        jellyfin_movie_identities=[{"id": "cached"}],
        jellyfin_live_stale=True,
    )
    monkeypatch.setattr(live, "state", fake_state)
    refreshes = []
    monkeypatch.setattr(live, "request_jellyfin_live_refresh", lambda **kwargs: refreshes.append(kwargs))
    monkeypatch.setattr(
        live,
        "backend_value",
        lambda name: (lambda: SimpleNamespace(configured=True)) if name == "get_jellyfin_client" else None,
    )

    value = live._cached_snapshot(
        "jellyfin_movie_identities",
        False,
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must stay nonblocking")),
    )

    assert value == [{"id": "cached"}]
    assert refreshes == [{}]


def test_targeted_episode_status_is_derived_from_shared_snapshot_without_network(monkeypatch):
    fake_state = _state(jellyfin_episodes=[
        {"id": "a", "series_id": "series-1", "season": 1, "episode": 1},
        {"id": "b", "series_id": "series-2", "season": 1, "episode": 1},
        {"id": "c", "series_id": "series-1", "season": 1, "episode": 2},
    ])
    monkeypatch.setattr(live, "state", fake_state)

    items, available, stale, checked_at = live.get_jellyfin_targeted_episodes({"series-1"})

    assert [item["id"] for item in items] == ["a", "c"]
    assert available is True
    assert stale is False
    assert checked_at == fake_state.jellyfin_episodes_time


def test_targeted_episode_first_load_preserves_legacy_cache_path(monkeypatch):
    fake_state = _state(jellyfin_episodes=None, jellyfin_episodes_available=False)
    monkeypatch.setattr(live, "state", fake_state)
    calls = []
    refreshes = []
    monkeypatch.setattr(
        live,
        "_legacy_get_jellyfin_targeted_episodes",
        lambda series_ids, force=False: calls.append((set(series_ids), force))
        or ([{"series_id": "series-1"}], True, False, 42.0),
    )
    monkeypatch.setattr(live, "request_jellyfin_live_refresh", lambda **kwargs: refreshes.append(kwargs))

    result = live.get_jellyfin_targeted_episodes({"series-1"})

    assert result == ([{"series_id": "series-1"}], True, False, 42.0)
    assert calls == [({"series-1"}, False)]
    assert refreshes == [{"force_full": True}]


def test_background_change_coalesces_into_one_snapshot_push_and_automation_wake(monkeypatch):
    fake_state = _state()
    monkeypatch.setattr(live, "state", fake_state)
    monkeypatch.setattr(live, "_last_revision", "old-revision")
    monkeypatch.setattr(live, "_failure_count", 0)
    monkeypatch.setattr(live, "_probe_library_revision", lambda _client: "new-revision")
    snapshots = []
    pushes = []
    wakes = []
    monkeypatch.setattr(live, "_refresh_snapshot", lambda _client: snapshots.append(True) or True)
    monkeypatch.setattr(live, "_broadcast_live_update", lambda: pushes.append(True))
    client = SimpleNamespace(configured=True)

    def backend(name):
        if name == "get_jellyfin_client":
            return lambda: client
        if name == "wake_watchlist_auto_check":
            return lambda: wakes.append(True)
        raise AssertionError(name)

    monkeypatch.setattr(live, "backend_value", backend)

    result = live._monitor_cycle()

    assert result == "changed"
    assert snapshots == [True]
    assert pushes == [True]
    assert wakes == [True]
    assert live._last_revision == "new-revision"


def test_unchanged_probe_verifies_cache_without_another_full_snapshot(monkeypatch):
    fake_state = _state(jellyfin_live_stale=False)
    monkeypatch.setattr(live, "state", fake_state)
    monkeypatch.setattr(live, "_last_revision", "same")
    monkeypatch.setattr(live, "_probe_library_revision", lambda _client: "same")
    monkeypatch.setattr(
        live,
        "_refresh_snapshot",
        lambda _client: (_ for _ in ()).throw(AssertionError("unchanged probe must not full-scan")),
    )
    client = SimpleNamespace(configured=True)
    monkeypatch.setattr(
        live,
        "backend_value",
        lambda name: (lambda: client) if name == "get_jellyfin_client" else None,
    )

    assert live._monitor_cycle() == "unchanged"
    assert fake_state.jellyfin_live_stale is False
    assert fake_state.jellyfin_library_time > 1.0
    assert fake_state.jellyfin_series_time > 1.0


def test_probe_failure_preserves_visual_cache_but_blocks_safety_caches(monkeypatch):
    fake_state = _state(jellyfin_library=[{"id": "keep-me"}])
    monkeypatch.setattr(live, "state", fake_state)
    monkeypatch.setattr(live, "_last_revision", "known")
    monkeypatch.setattr(live, "_failure_count", 0)
    monkeypatch.setattr(live, "_probe_library_revision", lambda _client: None)
    client = SimpleNamespace(configured=True)
    monkeypatch.setattr(
        live,
        "backend_value",
        lambda name: (lambda: client) if name == "get_jellyfin_client" else None,
    )

    assert live._monitor_cycle() == "unavailable"
    assert fake_state.jellyfin_library == [{"id": "keep-me"}]
    assert fake_state.jellyfin_movie_identities_available is True
    assert fake_state.jellyfin_series_available is True
    assert fake_state.jellyfin_library_available is False
    assert fake_state.jellyfin_episodes_available is False
    assert fake_state.jellyfin_user_episodes_available is False
    assert fake_state.jellyfin_live_stale is True
    assert live._failure_count == 1


def test_download_safety_blocks_when_live_snapshot_is_stale(monkeypatch):
    fake_state = _state(jellyfin_live_stale=True)
    monkeypatch.setattr(live, "state", fake_state)
    monkeypatch.setattr(live, "_legacy_content_already_available", lambda _movie, _slug: (False, ""))
    monkeypatch.setattr(
        live,
        "backend_value",
        lambda name: (lambda: SimpleNamespace(configured=True)) if name == "get_jellyfin_client" else None,
    )

    available, reason = live._content_already_available(SimpleNamespace(), "movie")

    assert available is True
    assert "Jellyfin-Livestatus veraltet" in reason


def test_movie_download_waits_for_running_live_refresh(monkeypatch):
    fake_state = _state(jellyfin_live_stale=True)
    waits = []
    refreshes = []

    class CompletingEvent:
        def clear(self):
            return None

        def set(self):
            return None

        def wait(self, timeout):
            waits.append(timeout)
            fake_state.jellyfin_live_stale = False
            return True

    monkeypatch.setattr(live, "state", fake_state)
    monkeypatch.setattr(live, "_live_ready_event", CompletingEvent())
    monkeypatch.setattr(live, "request_jellyfin_live_refresh", lambda **kwargs: refreshes.append(kwargs))
    monkeypatch.setattr(
        live,
        "backend_value",
        lambda name: (lambda: SimpleNamespace(configured=True))
        if name == "get_jellyfin_client" else None,
    )

    assert live.wait_for_jellyfin_live_ready(timeout=0.25) is True
    assert refreshes == [{}]
    assert waits == [0.25]


def test_movie_download_wait_fails_closed_after_timeout(monkeypatch):
    fake_state = _state(jellyfin_live_stale=True)
    monkeypatch.setattr(live, "state", fake_state)
    monkeypatch.setattr(live, "request_jellyfin_live_refresh", lambda **_kwargs: None)
    monkeypatch.setattr(
        live,
        "backend_value",
        lambda name: (lambda: SimpleNamespace(configured=True))
        if name == "get_jellyfin_client" else None,
    )
    event = threading.Event()
    monkeypatch.setattr(live, "_live_ready_event", event)

    assert live.wait_for_jellyfin_live_ready(timeout=0.0) is False


def test_frontend_live_event_refreshes_every_visible_jellyfin_surface():
    core = (live.backend_value("APP_DIR") / "web" / "core.js").read_text(encoding="utf-8")
    home = (live.backend_value("APP_DIR") / "web" / "screens" / "home.js").read_text(encoding="utf-8")

    event = core.split('data.type === "jellyfin_update"', 1)[1].split("watchlist_update", 1)[0]
    assert "refreshFpJellyfinStatus()" in event
    assert "refreshSeriesJellyfinStatus()" in event
    assert "refreshAllCatalogJellyfinStatuses()" in event
    assert "state.globalSearch.results" in home
    assert "state.series.results.map(homeSeriesEntry)" in home
    assert "state.anime.results.map(homeAnimeEntry)" in home


def test_frontend_reconnect_and_idle_resume_refresh_every_jellyfin_surface():
    app_dir = live.backend_value("APP_DIR")
    core = (app_dir / "web" / "core.js").read_text(encoding="utf-8")
    resume = (app_dir / "web" / "jellyfin-resume.js").read_text(encoding="utf-8")
    api = (app_dir / "web" / "api.js").read_text(encoding="utf-8")

    reconnect = core.split("async function resyncAfterWsOpen", 1)[1].split(
        "function connectWs", 1
    )[0]
    assert "refreshAllCatalogJellyfinStatuses()" in reconnect
    assert 'window.addEventListener("focus"' in resume
    assert 'window.addEventListener("online"' in resume
    assert 'document.addEventListener("visibilitychange"' in resume
    assert "JELLYFIN_RESUME_IDLE_MS" in resume
    assert "_postWithin" in api
    assert '"/api/jellyfin/matches"' in api


def test_live_service_preserves_automation_ownership_and_is_installed_last():
    app_dir = live.backend_value("APP_DIR")
    runtime = (app_dir / "application_services" / "runtime.py").read_text(encoding="utf-8")
    automation = (app_dir / "application_services" / "automation.py").read_text(encoding="utf-8")

    assert '"application_services.jellyfin_live"' in runtime
    assert runtime.index('"application_services.smart_automation"') < runtime.index(
        '"application_services.jellyfin_live"'
    )
    assert "def wake_watchlist_auto_check()" in automation
    assert "_watchlist_wake_event.wait" in automation
    assert server.watchlist_auto_check_loop.__module__ == "application_services.automation"
