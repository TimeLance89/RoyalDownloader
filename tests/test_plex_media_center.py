import copy
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_media_center_router import create_media_center_router
from core import config
from core.users import UserStore
from integrations.media_center import (
    media_client,
    profile_identity,
    validate_server_url,
)
from integrations.plex_client import PlexClient, PlexError, item_id


@pytest.fixture
def plex(monkeypatch):
    client = PlexClient("http://plex.local:32400", "secret", libraries=["1", "2"])
    calls = []
    movies = [{"ratingKey": "10", "type": "movie", "title": "Arrival", "year": 2016,
               "Guid": [{"id": "tmdb://329865"}], "viewCount": 1,
               "Media": [{"height": 1080, "Part": [{"file": "D:/Movies/Arrival.mkv"}]}]}]
    episodes = [{"ratingKey": "21", "type": "episode", "title": "Pilot", "parentIndex": 1,
                 "index": 1, "grandparentTitle": "Dark", "grandparentRatingKey": "20", "viewCount": 1}]
    def request(method, path, params=None):
        calls.append((method, path, params))
        if path == "/": return {"machineIdentifier": "machine", "friendlyName": "Local Plex"}
        if path == "/library/sections": return {"Directory": [
            {"key": "1", "title": "Filme", "type": "movie"}, {"key": "2", "title": "Serien", "type": "show"}]}
        if path == "/library/sections/1/all": return {"Metadata": movies, "totalSize": len(movies)}
        if path == "/library/sections/2/all" and str(params.get("type")) == "2":
            return {"Metadata": [{"ratingKey": "20", "type": "show", "title": "Dark", "Guid": [{"id": "tmdb://70523"}]}]}
        if path in {"/library/sections/2/all", "/library/metadata/20/allLeaves"}: return {"Metadata": episodes, "totalSize": len(episodes)}
        if path == "/status/sessions": return {"Metadata": []}
        if path.endswith("/refresh"): return {}
        raise AssertionError(path)
    monkeypatch.setattr(client, "_request", request)
    return client, calls, movies, episodes


def test_plex_snapshots_match_the_existing_catalog_contract(plex):
    client, _, _, _ = plex
    movies = client.list_movies()
    assert movies[0]["quality_rank"] == 1080
    assert movies[0]["path"] == "D:/Movies/Arrival.mkv"
    assert client.match("Wrong title", tmdb_id="329865", items=movies)
    assert not client.match("Arrival", tmdb_id="999", items=movies)
    assert client.list_movie_identities()[0]["tmdb_id"] == "329865"
    series = client.list_series()
    assert client.series_ids_for("Dark", tmdb_id="70523", items=series) == {item_id(20)}
    assert client.list_episodes_for_series(item_id(20))[0]["episode"] == 1
    assert client.has_episode("Dark", 1, 1)


def test_plex_watched_status_is_token_scoped(plex):
    client, calls, _, _ = plex
    assert client.list_users() == [{"id": client.profile_id, "name": "Plex-Konto dieser Verbindung"}]
    assert client.list_movies_with_user_data(client.profile_id)[0]["played"] is True
    episodes = client.list_episodes_with_user_data(client.profile_id)
    assert client.watched_episodes_for_series("Dark", episodes) == {(1, 1)}
    calls.clear()
    assert client.list_episodes_with_user_data("other-user") is None
    assert calls == []


def test_selected_libraries_and_lost_access_fail_closed(plex):
    client, _, _, _ = plex
    client.libraries = ["2"]
    assert client.list_movies() == []
    client.libraries = ["999"]
    assert client.list_movies() is None


def test_paginated_reads_and_repeated_pages(plex, monkeypatch):
    client = plex[0]
    def pages(method, path, params):
        start = params["X-Plex-Container-Start"]
        return {"Metadata": [{"ratingKey": str(start + 1)}], "totalSize": 3}
    monkeypatch.setattr(client, "_request", pages)
    assert len(client._pages("/items", page_size=1)) == 3
    monkeypatch.setattr(client, "_request", lambda *_: {"Metadata": [{"ratingKey": "1"}], "totalSize": 3})
    with pytest.raises(PlexError, match="wiederholt"):
        client._pages("/items", page_size=1)


def test_refresh_playback_and_disabled_deletion(plex):
    client, calls, _, _ = plex
    assert client.has_active_playback() is False
    assert client.refresh_library()
    assert len([path for _, path, _ in calls if path.endswith("/refresh")]) == 2
    calls.clear()
    assert client.delete_item(item_id(10)) is False
    assert calls == []


def test_revision_changes_when_watched_status_changes(plex):
    client, _, movies, _ = plex
    before = client.library_revision()
    movies[0]["viewCount"] = 2
    assert client.library_revision() != before


def test_transport_uses_header_auth_and_never_follows_redirects(monkeypatch):
    calls = []
    from integrations import plex_client
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, content=b"{}", json=lambda: {"MediaContainer": {"size": 0}})
    monkeypatch.setattr(plex_client.requests, "request", request)
    client = PlexClient("http://plex.local:32400", "private-token")
    assert client._request("GET", "/library/sections") == {"size": 0}
    assert calls[0][2]["headers"]["X-Plex-Token"] == "private-token"
    assert "private-token" not in calls[0][1]
    assert calls[0][2]["allow_redirects"] is False
    monkeypatch.setattr(plex_client.requests, "request", lambda *a, **k: SimpleNamespace(status_code=302))
    with pytest.raises(PlexError, match="302"):
        client._request("GET", "/library/sections")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:token@plex.local", "http://plex/?X-Plex-Token=secret", "http://plex/#secret", "ftp://plex", "http://plex:bad"])
def test_invalid_server_addresses(url):
    with pytest.raises(ValueError): validate_server_url(url)


@pytest.fixture
def api(monkeypatch, tmp_path, plex):
    storage = {"jellyfin_url": "http://jellyfin:8096", "jellyfin_api_key": "jf-secret", "jellyfin_user_id": "jf-user"}
    monkeypatch.setattr(config, "_read_all", lambda: dict(storage))
    monkeypatch.setattr(config, "_write_all", lambda values: storage.update(values) or True)
    state = SimpleNamespace(jellyfin_cfg=config.load_media_center(), jellyfin_cache_lock=threading.RLock(),
                            jellyfin_config_update_lock=threading.RLock(), jellyfin_config_generation=0,
                            taste_profiles=SimpleNamespace(for_user=lambda _: SimpleNamespace(replace_jellyfin_items=lambda _: None)))
    store = UserStore(tmp_path / "users.json", {})
    store.create("Admin", "admin", "admin")
    events = []
    def apply(cfg):
        state.jellyfin_cfg = cfg
        state.jellyfin_config_generation += 1
    backend = SimpleNamespace(state=state, current_user=lambda *_: {"role": "admin"},
                              _set_runtime_jellyfin_config=apply, _recommender_wake_event=threading.Event(),
                              broadcast=events.append, USER_STORE=store)
    import api.api_media_center_router as module
    monkeypatch.setattr(module, "media_client", lambda *_a, **_k: plex[0])
    app = FastAPI()
    app.include_router(create_media_center_router(backend))
    return TestClient(app), backend, storage, events


def activation(api, plex):
    return {"provider": "plex", "url": "http://plex.local:32400", "api_key": "secret", "libraries": ["1", "2"],
            "user_id": plex[0].profile_id, "server_id": "machine", "expected_generation": api[1].state.jellyfin_config_generation}


def test_probe_has_no_side_effect_and_never_returns_secrets(api, plex):
    http, backend, storage, events = api
    previous = copy.deepcopy(storage)
    response = http.post("/api/media-center/probe", json=activation(api, plex))
    assert response.status_code == 200
    assert len(response.json()["libraries"]) == 2
    assert "secret" not in response.text
    assert storage == previous
    assert backend.state.jellyfin_config_generation == 0
    assert events == []


def test_atomic_switch_preserves_jellyfin_and_survives_reload(api, plex):
    http, backend, _storage, events = api
    response = http.post("/api/media-center/activate", json=activation(api, plex))
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "plex"
    assert "secret" not in response.text
    assert config.load_media_center()["provider"] == "plex"
    assert isinstance(media_client(config.load_media_center()), PlexClient)
    assert config.load_jellyfin()["api_key"] == "jf-secret"
    assert backend.state.jellyfin_cfg["cleanup_default"] == "keep"
    assert events[0]["type"] == "media_center_update"
    assert config.save_media_center("jellyfin", config.load_jellyfin())
    assert config.load_media_center()["provider"] == "jellyfin"
    assert config.load_media_connection("plex")["libraries"] == ["1", "2"]


@pytest.mark.parametrize("change", [{"libraries": []}, {"libraries": ["gone"]}, {"user_id": "other"}, {"server_id": "different"}, {"expected_generation": 99}])
def test_invalid_or_stale_activation_keeps_previous_connection(api, plex, change):
    http, backend, storage, _ = api
    previous = copy.deepcopy(storage)
    response = http.post("/api/media-center/activate", json=activation(api, plex) | change)
    assert response.status_code in {400, 409, 502}
    assert storage == previous
    assert backend.state.jellyfin_config_generation == 0


def test_failed_probe_or_write_never_replaces_runtime(api, plex, monkeypatch):
    http, backend, _, _ = api
    monkeypatch.setattr(config, "save_media_center", lambda *_: False)
    response = http.post("/api/media-center/activate", json=activation(api, plex))
    assert response.status_code == 500
    assert backend.state.jellyfin_config_generation == 0
    monkeypatch.setattr(plex[0], "list_libraries", lambda: (_ for _ in ()).throw(PlexError("offline")))
    assert http.post("/api/media-center/activate", json=activation(api, plex)).status_code == 502
    assert backend.state.jellyfin_config_generation == 0


def test_administrator_required(api, plex):
    http, backend, _, _ = api
    backend.current_user = lambda *_: {"role": "member"}
    assert http.get("/api/media-center/config").status_code == 403
    assert http.post("/api/media-center/probe", json=activation(api, plex)).status_code == 403
    assert http.post("/api/media-center/activate", json=activation(api, plex)).status_code == 403
    assert set(http.get("/api/media-center/status").json()) == {"provider", "configured", "generation", "cleanup_supported"}


def test_server_specific_plex_profile_does_not_overwrite_jellyfin(tmp_path):
    store = UserStore(tmp_path / "users.json", {})
    user = store.create("Alice", "alice", "member")
    store.set_jellyfin_user(user["id"], "jf-alice", "Alice")
    store.set_media_user(user["id"], "plex", "machine", "plex-token-profile", "Plex")
    saved = store.get(user["id"])
    assert profile_identity(saved, {"provider": "plex", "server_id": "machine"}) == ("plex-token-profile", "Plex")
    assert profile_identity(saved, {"provider": "plex", "server_id": "other"}) == ("", "")
    assert profile_identity(saved, {"provider": "jellyfin"}) == ("jf-alice", "Alice")
    assert "media_profiles" not in store.public(saved)


def test_runtime_activation_failure_restores_previous_connection(api, plex):
    http, backend, _, _ = api
    def apply(cfg):
        if cfg.get("provider") == "plex":
            raise RuntimeError("runtime unavailable")
        backend.state.jellyfin_cfg = cfg
    backend._set_runtime_jellyfin_config = apply
    response = http.post("/api/media-center/activate", json=activation(api, plex))
    assert response.status_code == 500
    assert config.load_media_center()["provider"] == "jellyfin"
    assert backend.state.jellyfin_cfg["provider"] == "jellyfin"


def test_retained_alternative_configuration_never_exposes_token(api):
    http, _, _, _ = api
    response = http.get("/api/media-center/config")
    assert response.json()["connections"]["jellyfin"]["has_api_key"] is True
    assert "jf-secret" not in response.text


def test_saved_media_reads_only_requested_series(plex):
    client, calls, _, _ = plex
    items = client.saved_library(client.profile_id, [{"media_type": "tv", "tmdb_id": "70523"}])
    assert any(item["Type"] == "Episode" for item in items)
    assert any(path == "/library/metadata/20/allLeaves" for _, path, _ in calls)


def test_malformed_metadata_is_not_treated_as_an_empty_library(plex, monkeypatch):
    client = plex[0]
    monkeypatch.setattr(client, "_pages", lambda *_: [{"ratingKey": "1", "type": "bad-type"}])
    assert client.list_movies() is None


def test_switch_back_to_jellyfin_uses_its_own_retained_credentials(api, monkeypatch):
    http, backend, _, _ = api
    seen = []
    import api.api_media_center_router as module
    def factory(cfg, **_):
        seen.append(cfg)
        return SimpleNamespace(list_users=lambda: [{"id": "jf-user", "name": "Jellyfin-Profil"}])
    monkeypatch.setattr(module, "media_client", factory)
    backend.state.jellyfin_cfg = {"provider": "plex", "url": "http://plex.local:32400", "api_key": "different-plex-secret"}
    response = http.post("/api/media-center/activate", json={
        "provider": "jellyfin", "url": "http://jellyfin:8096", "api_key": "", "user_id": "jf-user", "expected_generation": 0,
    })
    assert response.status_code == 200
    assert seen[0]["api_key"] == "jf-secret"
    assert backend.state.jellyfin_cfg["provider"] == "jellyfin"
    assert backend.state.jellyfin_cfg["user_name"] == "Jellyfin-Profil"


def test_new_server_never_reuses_a_retained_token(api, plex):
    http, _, _, _ = api
    body = activation(api, plex) | {"url": "http://other-plex:32400", "api_key": ""}
    assert http.post("/api/media-center/probe", json=body).status_code == 400


def test_plex_does_not_inherit_jellyfin_watched_cleanup_history(monkeypatch):
    from api import api_library_router as library
    from providers.models import FilmpalastSeries, SeriesEpisode
    captured = {}
    monkeypatch.setattr(library, "state", SimpleNamespace(content_languages={"de"}, subscription_content_languages={}))
    monkeypatch.setattr(library, "compute_downloaded_episodes", lambda _: set())
    monkeypatch.setattr(library, "_unreleased_episode_slugs", lambda *_: set())
    monkeypatch.setattr(library, "_watchlist_episode_language_evidence", lambda *_: (None, {}))
    def classify(*_, **kwargs):
        captured.update(kwargs)
        return {}
    monkeypatch.setattr(library, "classify_subscription_episode_states", classify)
    client = SimpleNamespace(provider="plex", configured=True,
        series_ids_for=lambda *a, **k: {"series"}, episodes_for_series=lambda *a, **k: {(1, 1)},
        watched_episodes_for_series=lambda *a, **k: set())
    series = FilmpalastSeries(title="Example", base_slug="example", url="https://example.test", seasons={1: [SeriesEpisode(1, 1, "example-s01e01", "https://example.test/1")]})
    entry = {"title": "Example", "download_mode": "all", "cleanup_mode": "watched_episodes", "cleanup_history": ["1:1"]}
    result = library._calculate_watchlist_entry_state(entry, series, client, [], [], [{"id": "series"}])
    assert captured["jellyfin_watched"] == set()
    assert result["cleanup_items"] == []


@pytest.mark.parametrize("payload", [[], None, 123, "broken-json"])
def test_malformed_persisted_plex_config_is_unconfigured(monkeypatch, payload):
    import json
    monkeypatch.setattr(config, "_read_all", lambda: {"media_center_provider": "plex", "plex_connection": json.dumps(payload)})
    assert config.load_media_center() == {"provider": "plex", "cleanup_default": "keep"}
    assert config.load_media_connection("plex") == {"provider": "plex", "cleanup_default": "keep"}


@pytest.mark.parametrize("page", [{"size": 0, "totalSize": 3}, {}])
def test_incomplete_pages_are_not_published_as_complete(plex, monkeypatch, page):
    client = plex[0]
    monkeypatch.setattr(client, "_request", lambda *_: page)
    with pytest.raises(PlexError): client._pages("/items")


def test_plex_reads_reject_replaced_server_identity(plex):
    client = plex[0]
    client.server_id = "other-machine"
    assert client.list_movies() is None
    assert client.library_revision() is None


def test_deleted_managed_playlist_is_idempotent(plex, monkeypatch):
    client = plex[0]
    def gone(*_): raise PlexError("gone", 404)
    monkeypatch.setattr(client, "_request", gone)
    client.delete_saved_playlist(item_id(123))


def test_post_commit_refresh_failures_do_not_report_a_failed_switch(api, plex):
    http, backend, _, _ = api
    def unavailable(*_): raise OSError("derived data unavailable")
    backend.state.taste_profiles.for_user = unavailable
    backend.broadcast = unavailable
    response = http.post("/api/media-center/activate", json=activation(api, plex))
    assert response.status_code == 200
    assert response.json()["saved"] is True
    assert len(response.json()["warnings"]) == 2
    assert backend.state.jellyfin_cfg["provider"] == "plex"


def test_failed_rollback_write_is_not_reported_as_restored(api, plex, monkeypatch):
    http, backend, _, _ = api
    def apply(cfg):
        if cfg["provider"] == "plex": raise RuntimeError("failed activation")
        backend.state.jellyfin_cfg = cfg
    backend._set_runtime_jellyfin_config = apply
    monkeypatch.setattr(config, "save_media_center", lambda provider, _: provider == "plex")
    response = http.post("/api/media-center/activate", json=activation(api, plex))
    assert response.status_code == 500
    assert "nicht wiederhergestellt" in response.json()["detail"]


@pytest.mark.parametrize("payload", [{}, {"Metadata": None}, {"Metadata": ["bad"]}, {"Metadata": [{"Player": "bad"}]}])
def test_malformed_playback_evidence_is_unknown(plex, monkeypatch, payload):
    client = plex[0]
    original = client._request
    monkeypatch.setattr(client, "_request", lambda method, path, *args: payload if path == "/status/sessions" else original(method, path, *args))
    assert client.has_active_playback() is None


def test_revision_periodically_refreshes_changes_outside_recent_sample(plex, monkeypatch):
    from integrations import plex_client
    client = plex[0]
    monkeypatch.setattr(plex_client.time, "monotonic", lambda: 10)
    before = client.library_revision()
    monkeypatch.setattr(plex_client.time, "monotonic", lambda: 310)
    assert client.library_revision() != before


def test_plex_playback_polling_is_cached_and_forceable(plex, monkeypatch):
    from features import smart_automation as smart
    from integrations import media_center
    calls = []
    monkeypatch.setattr(media_center, "media_client", lambda *_a, **_k: SimpleNamespace(configured=True, active_sessions=lambda: calls.append(True) or [{"Player": {"state": "playing"}}]))
    monkeypatch.setattr(smart, "_JELLYFIN_CACHE", {"signature": None, "checked_at": 0})
    state = SimpleNamespace(jellyfin_cfg={"provider": "plex", "url": "http://plex:32400", "api_key": "secret"})
    assert smart.jellyfin_playback_status(state)["active_streams"] == 1
    assert smart.jellyfin_playback_status(state)["active_streams"] == 1
    assert len(calls) == 1
    assert smart.jellyfin_playback_status(state, force=True)["active_streams"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize("views,played", [("0", False), (0, False), ("1", True), (-1, False)])
def test_watched_counts_are_numeric_evidence(views, played):
    item = PlexClient._normalize({"type": "movie", "ratingKey": "1", "viewCount": views})
    assert item["UserData"]["Played"] is played


@pytest.mark.parametrize("total,viewed,played", [(0, 0, False), (10, 9, False), (10, 10, True)])
def test_series_seen_evidence_requires_all_episodes(total, viewed, played):
    item = PlexClient._normalize({"type": "show", "ratingKey": "1", "leafCount": total, "viewedLeafCount": viewed})
    assert item["UserData"]["Played"] is played
