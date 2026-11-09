from threading import Lock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_media_center_router import create_media_center_router
from api.api_media_segments_router import create_media_segments_router
from application_services.media_segments import MediaSegments
from core import egress_requests as requests
from integrations.jellyfin_client import JellyfinClient

ITEM = "1" * 32
PROFILE = "2" * 32
OTHER = "3" * 32
PATH = f"/api/media-center/items/{ITEM}/segments"


@pytest.fixture
def setup_api(monkeypatch):
    user = {"id": "reader", "role": "member", "enabled": True, "jellyfin_user_id": PROFILE}
    state = SimpleNamespace(jellyfin_cache_lock=Lock(), jellyfin_config_generation=1,
                            jellyfin_cfg={"provider": "jellyfin", "url": "http://jellyfin/base", "api_key": "private-key"})
    backend = SimpleNamespace(state=state, current_user=lambda headers, cookies: user if user else None)
    calls = []
    payload = {"Items": [{"ItemId": ITEM, "Type": "Intro", "StartTicks": 0, "EndTicks": 900_000_000}]}
    flags = {"visible": True, "disabled": False, "playback": True, "duration": 30_000_000_000}

    def read(self, method, path, body=None, params=None):
        calls.append((self.base_url, self.api_key, path, params))
        if path.startswith("/Users/"):
            return {"Id": path.rsplit("/", 1)[-1], "Policy": {
                "IsDisabled": flags["disabled"], "EnableMediaPlayback": flags["playback"],
            }}
        if path == "/Items":
            return {"Items": [{"Id": ITEM, "Type": "Episode", "RunTimeTicks": flags["duration"]}] if flags["visible"] else []}
        assert path == f"/MediaSegments/{ITEM}"
        if flags.get("during_read"):
            flags["during_read"]()
        return payload

    monkeypatch.setattr(JellyfinClient, "_saved_request", read)
    app = FastAPI()
    app.include_router(create_media_center_router(backend))
    return SimpleNamespace(client=TestClient(app), user=user, state=state, backend=backend,
                           calls=calls, payload=payload, flags=flags)


@pytest.mark.parametrize("versioned", [False, True])
def test_registered_endpoint_returns_item_bound_metadata_for_authenticated_members(setup_api, versioned):
    env = setup_api
    path = PATH.replace("/api/", "/api/v1/", 1) if versioned else PATH
    response = env.client.get(path)
    assert response.status_code == 200
    assert response.json() == {"media_id": ITEM, "available": True, "status": "available", "segments": [
        {"type": "Intro", "start_seconds": 0.0, "end_seconds": 90.0},
    ]}
    assert response.headers["cache-control"] == "no-store"
    assert env.calls[1][3]["UserId"] == PROFILE
    assert "private-key" not in response.text


def test_api_authentication_disabled_users_and_refresh_roles(setup_api):
    env = setup_api
    assert env.client.post(PATH + "/refresh").status_code == 403
    env.user["enabled"] = False
    assert env.client.get(PATH).status_code == 401
    env.user.clear()
    assert env.client.get(PATH).status_code == 401
    assert not env.calls


def test_unlinked_profiles_never_fall_back_to_the_server_administrator(setup_api):
    env = setup_api
    env.state.jellyfin_cfg["user_id"] = OTHER
    env.user["role"] = "admin"
    env.user["jellyfin_user_id"] = ""
    assert env.client.get(PATH).status_code == 403
    assert not env.calls
    env.user["id"] = "admin-legacy"
    assert env.client.get(PATH).status_code == 200
    assert env.calls[1][3]["UserId"] == OTHER


@pytest.mark.parametrize("field,value", [("disabled", True), ("playback", False), ("visible", False)])
def test_permissions_are_checked_again_even_when_segments_are_cached(setup_api, field, value):
    env = setup_api
    assert env.client.get(PATH).status_code == 200
    env.flags[field] = value
    response = env.client.get(PATH)
    assert response.status_code == (404 if field == "visible" else 403)
    assert not response.json()["segments"]
    assert len([call for call in env.calls if call[2].startswith("/MediaSegments")]) == 1


def test_cached_results_cannot_be_changed_by_a_client_and_permissions_are_not_cached(setup_api):
    env = setup_api
    first = env.client.get(PATH).json()
    first["segments"].clear()
    second = env.client.get(PATH + f"?user_id={OTHER}")
    assert second.json()["available"] is True
    assert len(env.calls) == 5  # user + item on each request; one segment read
    assert all(call[3]["UserId"] == PROFILE for call in env.calls if call[2] == "/Items")


def test_admin_refresh_observes_reanalysis_and_replaces_positive_and_negative_cache(setup_api):
    env = setup_api
    env.user["role"] = "admin"
    assert env.client.get(PATH).json()["available"] is True
    env.payload["Items"] = []
    assert env.client.get(PATH).json()["available"] is True
    empty = env.client.post(PATH + "/refresh")
    assert empty.status_code == 200 and empty.json()["status"] == "empty"
    assert env.client.get(PATH).json()["status"] == "empty"
    env.payload["Items"] = [{"ItemId": ITEM, "Type": "Outro", "StartTicks": 25_000_000_000, "EndTicks": 29_000_000_000}]
    refreshed = env.client.post(PATH.replace("/api/", "/api/v1/", 1) + "/refresh")
    assert refreshed.json()["segments"][0]["type"] == "Outro"


def test_cache_isolated_by_profile_connection_credentials_generation_and_duration(setup_api):
    env = setup_api
    assert env.client.get(PATH).status_code == 200
    mutations = [lambda: env.user.update(jellyfin_user_id=OTHER),
                 lambda: env.state.jellyfin_cfg.update(url="http://other/base"),
                 lambda: env.state.jellyfin_cfg.update(api_key="rotated-key"),
                 lambda: setattr(env.state, "jellyfin_config_generation", 2),
                 lambda: env.flags.update(duration=35_000_000_000)]
    for mutate in mutations:
        mutate()
        assert env.client.get(PATH).status_code == 200
    assert len([call for call in env.calls if call[2].startswith("/MediaSegments")]) == 6


@pytest.mark.parametrize("kind", ["profile", "generation", "logout"])
def test_inflight_profile_or_connection_changes_discard_old_results(setup_api, kind):
    env = setup_api
    changes = {"profile": lambda: env.user.update(jellyfin_user_id=OTHER),
               "generation": lambda: setattr(env.state, "jellyfin_config_generation", 2),
               "logout": lambda: env.user.clear()}
    env.flags["during_read"] = changes[kind]
    response = env.client.get(PATH)
    assert response.status_code == 409
    assert "segments" not in response.json()


def test_absent_provider_invalid_ids_and_unsupported_provider_do_not_trigger_network(setup_api):
    env = setup_api
    assert env.client.get(PATH.replace(ITEM, "invalid")).status_code == 422
    env.state.jellyfin_cfg["provider"] = "plex"
    response = env.client.get(PATH)
    assert response.status_code == 503 and response.json()["status"] == "unsupported"
    env.state.jellyfin_cfg = {}
    response = env.client.get(PATH)
    assert response.status_code == 503 and response.json()["error"]["code"] == "jellyfin_not_configured"
    assert not env.calls


def test_invalid_segment_data_is_an_error_rather_than_no_markers(setup_api):
    env = setup_api
    env.payload["Items"][0]["EndTicks"] = -10
    response = env.client.get(PATH)
    assert response.status_code == 502
    assert response.json()["status"] == "error" and response.json()["available"] is False


def test_standalone_router_also_requires_authentication():
    backend = SimpleNamespace(current_user=lambda *_: None)
    app = FastAPI()
    app.include_router(create_media_segments_router(backend, service=MediaSegments()))
    assert TestClient(app).get(PATH).status_code == 401


@pytest.mark.parametrize("status,expected", [(404, 503), (500, 503), (401, 502)])
def test_upstream_failures_have_explicit_http_status_and_never_return_cached_markers(setup_api, monkeypatch, status, expected):
    env = setup_api
    env.user["role"] = "admin"
    assert env.client.get(PATH).json()["available"] is True
    original = JellyfinClient._saved_request

    def fail(self, method, path, **kwargs):
        if path.startswith("/MediaSegments/"):
            raise requests.HTTPError("private-key and private server address", response=SimpleNamespace(status_code=status))
        return original(self, method, path, **kwargs)

    monkeypatch.setattr(JellyfinClient, "_saved_request", fail)
    response = env.client.post(PATH + "/refresh")
    assert response.status_code == expected
    assert response.json()["segments"] == [] and response.json()["available"] is False
    assert "private-key" not in response.text
    assert env.client.get(PATH).status_code == expected


def test_new_routes_are_registered_once_and_remain_protected_by_global_security_policy(setup_api):
    from api.api_security import is_public_path

    env = setup_api

    def walk(routes):
        for route in routes:
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from walk(nested.routes)
            else:
                yield route

    for version in ("/api", "/api/v1"):
        path = f"{version}/media-center/items/{{item_id}}/segments"
        for endpoint, method in ((path, "GET"), (path + "/refresh", "POST")):
            matches = [route for route in walk(env.client.app.routes) if getattr(route, "path", "") == endpoint and method in route.methods]
            assert len(matches) == 1
            assert not is_public_path(endpoint, method, lambda: False)
