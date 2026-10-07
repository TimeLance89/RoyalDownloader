from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_saved_media_router import create_saved_media_router
from application_services.saved_media import SavedMediaSync, resolve_wishes
from core.saved_media import SavedMediaStore
from integrations.jellyfin_client import JellyfinClient
from integrations.jellyfin_saved import playlist_name


A, B = UUID(int=1).hex, UUID(int=2).hex
MOVIE, SERIES, EPISODE = UUID(int=10).hex, UUID(int=11).hex, UUID(int=12).hex


def movie(identity=7, **extra):
    return {"Id": MOVIE, "Type": "Movie", "ProviderIds": {"Tmdb": str(identity)}, "Path": "/media/movie.mkv", **extra}


def wish(kind="movie", identity=7, owner="a"):
    return {"owner": owner, "media_type": kind, "tmdb_id": identity, "title": "Same title"}


def test_personal_wishes_survive_restart_and_separate_media_types_and_users(tmp_path):
    path = tmp_path / "saved.json"
    store = SavedMediaStore(path)
    store.set("a", "movie", 7, "Film", True)
    store.set("a", "tv", 7, "Serie", True)
    store.set("b", "movie", 7, "Film", True)
    store.set("a", "movie", 7, "Film", True)
    restored = SavedMediaStore(path)
    assert len(restored.items("a")) == 2
    restored.set("a", "movie", 7, "Film", False)
    assert restored.items("a")[0]["media_type"] == "tv"
    assert len(restored.items("b")) == 1
    assert restored.delete_for_user("a") == 1
    assert len(SavedMediaStore(path).items("b")) == 1


def test_failed_atomic_write_preserves_previous_memory_and_disk(tmp_path, monkeypatch):
    store = SavedMediaStore(tmp_path / "saved.json")
    store.set("a", "movie", 7, "Film", True)
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr("core.saved_media.os.replace", fail)
    with pytest.raises(OSError):
        store.set("a", "movie", 7, "Film", False)
    assert len(store.items("a")) == len(SavedMediaStore(store.path).items("a")) == 1


def test_resolver_requires_exact_unambiguous_identity_and_playable_files():
    series = {"Id": SERIES, "Type": "Series", "ProviderIds": {"Tmdb": "7"}}
    episode = {"Id": EPISODE, "Type": "Episode", "SeriesId": SERIES, "Path": "/media/episode.mkv"}
    wishes = [wish(), wish("tv")]
    assert resolve_wishes(wishes, [movie(), series]) == {("movie", 7): [MOVIE]}
    assert resolve_wishes(wishes, [movie(), series, episode]) == {("movie", 7): [MOVIE], ("tv", 7): [EPISODE]}
    for unavailable in [{"IsMissing": True}, {"IsPlaceHolder": True}, {"LocationType": "Virtual"}, {"LocationType": "Offline"}, {"Path": ""}]:
        assert not resolve_wishes([wish()], [movie(**unavailable)])
    assert not resolve_wishes([wish()], [movie(8)])  # same title/remake is not sufficient
    assert not resolve_wishes([wish()], [movie(), movie(Id=UUID(int=13).hex)])


class JellyfinFixture:
    configured = True
    base_url = "http://jellyfin.test"
    api_key = "fixture"

    def __init__(self):
        self.library = {A: [], B: []}
        self.playlists = {}
        self.owners = {}
        self.writes = []
        self.fail = False

    def saved_library(self, user, wishes=()):
        return None if self.fail else deepcopy(self.library[user])

    def saved_server_id(self):
        return UUID(int=400).hex

    def create_saved_playlist(self, user):
        playlist = UUID(int=100 + len(self.playlists)).hex
        self.playlists[playlist] = {"ItemIds": [], "OpenAccess": False, "Shares": []}
        self.owners[user] = playlist
        return playlist

    def saved_playlist(self, identity):
        return deepcopy(self.playlists[identity])

    def replace_saved_playlist(self, identity, user, ids):
        assert identity == self.owners[user]
        self.writes.append((user, list(ids)))
        self.playlists[identity] = {"ItemIds": list(ids), "OpenAccess": False, "Shares": []}


def test_sync_is_user_scoped_delayed_idempotent_and_retries_outages(tmp_path):
    store = SavedMediaStore(tmp_path / "saved.json")
    jf = JellyfinFixture()
    profiles = [{"id": "a", "enabled": True, "jellyfin_user_id": A}, {"id": "b", "enabled": True, "jellyfin_user_id": B}]
    sync = SavedMediaSync(store, lambda: jf, lambda: deepcopy(profiles))
    store.set("a", "movie", 7, "Film", True)
    store.set("b", "movie", 8, "Other film", True)
    sync.run()
    assert not jf.writes
    jf.library[A] = [movie()]
    jf.library[B] = [movie()]  # profile B cannot receive A's saved film
    sync.run()
    assert jf.writes == [(A, [MOVIE])]
    sync.run()
    assert len(jf.writes) == 1
    jf.fail = True
    sync.run()
    assert jf.playlists[jf.owners[A]]["ItemIds"] == [MOVIE]
    assert sync.status(profiles[0])["state"] == "error"
    jf.fail = False
    # Removal and remapping clear the old private list, without moving other users' wishes.
    profiles[0]["jellyfin_user_id"] = B
    sync.run()
    assert jf.playlists[jf.owners[A]]["ItemIds"] == []
    assert jf.playlists[jf.owners[B]]["ItemIds"] == [MOVIE]
    store.set("a", "movie", 7, "Film", False)
    sync.run()
    assert jf.playlists[jf.owners[B]]["ItemIds"] == []


def test_unlinked_wishes_wait_and_mapping_changes_during_scan_cancel_writes(tmp_path):
    store = SavedMediaStore(tmp_path / "saved.json")
    store.set("a", "movie", 7, "Film", True)
    jf = JellyfinFixture()
    profile = {"id": "a", "enabled": True, "jellyfin_user_id": ""}
    sync = SavedMediaSync(store, lambda: jf, lambda: [dict(profile)])
    sync.run()
    assert not jf.playlists and sync.status(profile)["state"] == "unlinked"
    profile["jellyfin_user_id"] = A
    def change_mapping(user, wishes=()):
        profile["jellyfin_user_id"] = B
        return [movie()]
    jf.saved_library = change_mapping
    sync.run()
    assert not jf.playlists
    assert len(store.items("a")) == 1


def test_api_rejects_owner_spoofing_and_never_reads_other_users(tmp_path):
    store = SavedMediaStore(tmp_path / "saved.json")
    store.set("b", "movie", 8, "Private", True)
    current = {"id": "a", "enabled": True}
    sync = SimpleNamespace(status=lambda _: {"state": "synced", "ready": ["movie:7", "movie:8"]}, request=Mock(), tick=Mock())
    app = FastAPI()
    app.include_router(create_saved_media_router(store, lambda *_: current, sync))
    client = TestClient(app)
    body = {"media_type": "movie", "tmdb_id": 7, "title": "Film", "saved": True}
    assert client.post("/api/me/saved-media", json={**body, "owner": "b"}).status_code == 422
    assert client.post("/api/me/saved-media", json={**body, "jellyfin_user_id": B}).status_code == 422
    response = client.post("/api/v1/me/saved-media", json=body)
    assert response.status_code == 200
    assert [item["tmdb_id"] for item in response.json()["items"]] == [7]
    assert response.json()["sync"]["ready"] == ["movie:7"]
    assert [item["tmdb_id"] for item in client.get("/api/me/saved-media").json()["items"]] == [7]
    current = None
    assert client.get("/api/me/saved-media").status_code == 401
    assert client.post("/api/me/saved-media", json=body).status_code == 401


def test_native_playlist_is_video_private_and_has_unique_profile_name(monkeypatch):
    client = JellyfinClient("http://jellyfin.test", "key")
    calls = []
    def request(method, path, body=None, **kwargs):
        calls.append((method, path, body))
        return {"Id": UUID(int=100).hex}
    monkeypatch.setattr(client, "_saved_request", request)
    playlist = client.create_saved_playlist(A)
    client.replace_saved_playlist(playlist, A, [MOVIE])
    assert calls[0][2]["UserId"] == A
    assert calls[0][2]["MediaType"] == "Video"
    assert all(call[2]["IsPublic"] is False and call[2]["Users"] == [] for call in calls)
    assert playlist_name(A) != playlist_name(B)


def test_library_read_is_scoped_to_linked_jellyfin_user(monkeypatch):
    client = JellyfinClient("http://jellyfin.test", "key")
    read = Mock(return_value=[])
    monkeypatch.setattr(client, "_list_endpoint_items", read)
    client.saved_library(A)
    assert read.call_args.args[0] == f"/Users/{A}/Items"
    assert read.call_args.args[1]["ExcludeLocationTypes"] == "Virtual,Offline"
    assert read.call_args.args[1]["CollapseBoxSetItems"] == "false"


def test_series_episode_reads_are_bounded_to_wished_visible_series(monkeypatch):
    client = JellyfinClient("http://jellyfin.test", "key")
    rows = [{"Id": SERIES, "Type": "Series", "ProviderIds": {"Tmdb": "7"}},
            {"Id": UUID(int=13).hex, "Type": "Series", "ProviderIds": {"Tmdb": "8"}}]
    calls = []
    def read(endpoint, params, *args):
        calls.append((endpoint, params))
        return deepcopy(rows) if params["IncludeItemTypes"] == "Movie,Series" else []
    monkeypatch.setattr(client, "_list_endpoint_items", read)
    client.saved_library(A, [wish("tv")])
    assert len(calls) == 2
    assert calls[-1][1]["ParentId"] == SERIES
    assert all(call[0] == f"/Users/{A}/Items" for call in calls)


def test_transport_keeps_auth_in_headers_and_rejects_redirects(monkeypatch):
    client = JellyfinClient("http://jellyfin.test", "key")
    request = Mock(return_value=SimpleNamespace(status_code=200, content=b"{}", json=lambda: {"Id": UUID(int=100).hex}, raise_for_status=lambda: None))
    monkeypatch.setattr("integrations.jellyfin_saved.requests.request", request)
    client.create_saved_playlist(A)
    args, options = request.call_args
    assert args == ("POST", "http://jellyfin.test/Playlists")
    assert "key" not in args[1]
    assert options["headers"] and options["allow_redirects"] is False
    request.return_value.status_code = 307
    with pytest.raises(ValueError, match="redirect rejected"):
        client.create_saved_playlist(A)


def test_deleting_native_playlist_recreates_it_without_losing_wishes(tmp_path):
    from requests import HTTPError
    store = SavedMediaStore(tmp_path / "saved.json")
    store.set("a", "movie", 7, "Film", True)
    jf = JellyfinFixture()
    jf.library[A] = [movie()]
    profile = {"id": "a", "enabled": True, "jellyfin_user_id": A}
    sync = SavedMediaSync(store, lambda: jf, lambda: [dict(profile)])
    sync.run()
    old = jf.owners[A]
    original_read = jf.saved_playlist
    def missing(identity):
        if identity == old:
            raise HTTPError(response=SimpleNamespace(status_code=404))
        return original_read(identity)
    jf.saved_playlist = missing
    sync.run()
    sync.run()
    assert jf.owners[A] != old
    assert jf.playlists[jf.owners[A]]["ItemIds"] == [MOVIE]
    assert len(store.items("a")) == 1


def test_disabled_profile_removes_managed_contents_and_reasserts_privacy(tmp_path):
    store = SavedMediaStore(tmp_path / "saved.json")
    store.set("a", "movie", 7, "Film", True)
    jf = JellyfinFixture()
    jf.library[A] = [movie()]
    profile = {"id": "a", "enabled": True, "jellyfin_user_id": A}
    sync = SavedMediaSync(store, lambda: jf, lambda: [dict(profile)])
    sync.run()
    jf.playlists[jf.owners[A]]["OpenAccess"] = True
    jf.playlists[jf.owners[A]]["Shares"] = [{"UserId": B, "CanEdit": True}]
    sync.run()
    assert jf.playlists[jf.owners[A]]["OpenAccess"] is False
    assert jf.playlists[jf.owners[A]]["Shares"] == []
    profile["enabled"] = False
    sync.run()
    assert jf.playlists[jf.owners[A]]["ItemIds"] == []


def test_server_url_change_reuses_stable_binding_and_guid_format_does_not_trigger_writes(tmp_path):
    store = SavedMediaStore(tmp_path / "saved.json")
    store.set("a", "movie", 7, "Film", True)
    jf = JellyfinFixture()
    jf.library[A] = [movie()]
    profile = {"id": "a", "enabled": True, "jellyfin_user_id": A}
    sync = SavedMediaSync(store, lambda: jf, lambda: [dict(profile)])
    sync.run()
    playlist = jf.owners[A]
    jf.playlists[playlist]["ItemIds"] = [str(UUID(MOVIE))]
    jf.base_url = "http://new-jellyfin-url.test"
    sync.run()
    assert jf.owners[A] == playlist
    assert len(jf.playlists) == len(jf.writes) == 1
