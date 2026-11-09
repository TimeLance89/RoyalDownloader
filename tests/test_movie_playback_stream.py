from contextlib import nullcontext
from threading import Lock
from types import SimpleNamespace

from core.auth import SessionStore
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_movie_playback_router import _stream_options, create_movie_playback_router


def playback_info(monkeypatch, container):
    source = {
        "Protocol": "File", "Id": "source", "Container": container,
        "RunTimeTicks": 61_271_250_000,
        "MediaStreams": [
            {"Type": "Video", "Codec": "h264", "BitDepth": 8},
            {"Type": "Audio", "Codec": "aac"},
        ],
    }
    monkeypatch.setattr(
        "api.api_movie_playback_router.requests.get",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(
            status_code=200, json=lambda: {"MediaSources": [source]},
        )),
    )


def test_ts_with_aac_is_converted_to_mp4_in_isolated_playback_sessions(monkeypatch):
    playback_info(monkeypatch, "ts")
    first = _stream_options("http://jellyfin", {}, "encanto", 9_790_000_000)
    retry = _stream_options("http://jellyfin", {}, "encanto", 9_790_000_000)
    assert first["Static"] == "false"
    assert first["AllowAudioStreamCopy"] == "false"
    assert first["AudioCodec"] == "aac"
    assert first["StartTimeTicks"] == 9_790_000_000
    assert first["PlaySessionId"] != retry["PlaySessionId"]
    assert first["DeviceId"] != retry["DeviceId"]


def test_compatible_mp4_can_still_stream_directly(monkeypatch):
    playback_info(monkeypatch, "mp4")
    options = _stream_options("http://jellyfin", {}, "movie")
    assert options == {"MediaSourceId": "source", "Static": "true"}


def test_resume_actions_isolate_hide_and_restore_episode_progress(monkeypatch, tmp_path):
    profile, episode = "1" * 32, "2" * 32
    position = 600_000_000
    user_data = {"PlaybackPositionTicks": position, "LastPlayedDate": "2026-11-01T13:00:00Z", "Played": False}
    item = {"Id": episode, "Type": "Episode", "Name": "Pilot", "SeriesName": "Demo", "UserData": user_data}
    backend = SimpleNamespace(
        state=SimpleNamespace(jellyfin_cache_lock=Lock(), jellyfin_config_generation=1,
                              jellyfin_cfg={"url": "http://jellyfin", "api_key": "fixture"}),
        current_user=lambda headers, cookies: {"id": headers.get("x-test-user", "a"), "role": "member", "jellyfin_user_id": profile},
    )
    authenticate(backend)
    module = "api.api_movie_playback_router"
    monkeypatch.setattr(f"{module}.home_layout_file", lambda: tmp_path / "home_layout.json")
    monkeypatch.setattr(f"{module}._jellyfin_json", lambda _url, _key, path, _: {"Id": profile, "Policy": {"IsDisabled": False}} if path.startswith("/Users/") else {"Items": [item]})

    def save(_url, _key, owner, target, data):
        assert (owner, target) == (profile, episode)
        user_data.update(data)
        return dict(user_data)

    monkeypatch.setattr(f"{module}._save_jellyfin_data", save)
    app = FastAPI()
    app.include_router(create_movie_playback_router(backend, lambda: None))
    client = TestClient(app)
    rail = "/api/media-center/continue-watching"
    endpoint = f"{rail}/{episode}/action"
    context = {"profile_id": profile, "generation": 1}

    def act(action, **fields):
        result = client.post(endpoint, json=context | {"action": action} | fields)
        assert result.status_code == 200, result.text
        return result.json()

    token = act("hide")["undo_token"]
    assert client.get(rail).json()["items"] == []
    assert client.get(rail, headers={"x-test-user": "b"}).json()["items"][0]["id"] == episode
    assert user_data["PlaybackPositionTicks"] == position
    act("undo", undo_token=token)
    assert client.get(rail).json()["items"][0]["id"] == episode
    act("hide")
    user_data["LastPlayedDate"] = "2026-11-02T13:00:00Z"
    assert client.get(rail).json()["items"][0]["id"] == episode

    token = act("watched")["undo_token"]
    assert user_data["Played"] is True
    assert client.get(rail).json()["items"] == []
    act("undo", undo_token=token)
    assert user_data["Played"] is False
    assert client.get(rail).json()["items"][0]["position_ticks"] == position


def test_resume_series_details_use_linked_jellyfin_ids_without_catalog_match(monkeypatch):
    profile, episode, series = "1" * 32, "2" * 32, "3" * 32
    item = {"Id": episode, "Type": "Episode", "Name": "Pilot", "SeriesId": series,
            "SeriesName": "Demo", "ParentIndexNumber": 1, "IndexNumber": 2,
            "UserData": {"PlaybackPositionTicks": 600_000_000}}
    backend = SimpleNamespace(
        state=SimpleNamespace(jellyfin_cache_lock=Lock(), jellyfin_config_generation=4,
                              jellyfin_cfg={"url": "http://jellyfin", "api_key": "fixture"}),
        current_user=lambda *_: {"id": "a", "role": "member", "jellyfin_user_id": profile},
    )
    authenticate(backend)
    paths = []

    def jellyfin(_url, _key, path, params):
        paths.append(path)
        if path.startswith("/Users/"):
            return {"Id": profile, "Policy": {"IsDisabled": False}}
        assert params.get("UserId", params.get("userId")) == profile
        if path == "/Items":
            return {"Items": [item] if params["Ids"] == episode else [{"Id": series, "Type": "Series", "Name": "Demo", "Overview": "Aus der Bibliothek"}]}
        if path == f"/Shows/{series}/Episodes":
            return {"Items": []}  # The already validated episode remains playable.
        assert path == f"/Items/{series}"
        return {"Name": "Demo", "Overview": "Aus der Bibliothek"}

    monkeypatch.setattr("api.api_movie_playback_router._jellyfin_json", jellyfin)
    app = FastAPI()
    app.include_router(create_movie_playback_router(backend, lambda: None))
    response = TestClient(app).get(f"/api/media-center/continue-watching/{episode}/details")
    assert response.status_code == 200
    details = response.json()
    assert details["series_id"] == series
    assert details["description"] == "Aus der Bibliothek"
    assert details["inventory"]["profile_id"] == profile
    assert details["inventory"]["items"][0]["id"] == episode
    assert paths == [f"/Users/{profile}", "/Items", "/Items", f"/Shows/{series}/Episodes", "/Items"]


def authenticate(backend):
    backend.SESSION_STORE = SessionStore()
    tokens = {owner: backend.SESSION_STORE.create(user_id=owner) for owner in ("a", "b")}
    backend.authenticated_web_token = lambda cookies, **_: ""
    backend.authenticated_mobile_token = lambda headers, **_: ""
    # Existing isolation fixture selects an identity through a test-only header.
    from core.auth import SESSION_KIND_MOBILE
    mobile = {owner: backend.SESSION_STORE.create(kind=SESSION_KIND_MOBILE, user_id=owner) for owner in tokens}
    backend.authenticated_mobile_token = lambda headers, **_: mobile[headers.get("x-test-user", "a")]
