import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import api_administration_router as router


@pytest.fixture
def jellyfin(monkeypatch):
    writes, runtime, probes = [], [], []
    state = SimpleNamespace(
        jellyfin_cfg={}, jellyfin_cache_lock=threading.RLock(),
        jellyfin_config_update_lock=threading.RLock(),
        module_manager=SimpleNamespace(reconcile=lambda *_: None),
    )
    monkeypatch.setattr(router, "state", state)
    monkeypatch.setattr(router.appconfig, "save_jellyfin", lambda *args: writes.append(args) or True)
    monkeypatch.setattr(router, "_set_runtime_jellyfin_config", lambda value: runtime.append(value))
    monkeypatch.setattr(router, "_recommender_wake_event", threading.Event())
    monkeypatch.setattr(router, "threading", SimpleNamespace(Thread=lambda **_: SimpleNamespace(start=lambda: None)))

    class Client:
        def __init__(self, url, key):
            probes.append((url, key))

        def list_users(self):
            return [{"id": "user", "name": "User"}]

    monkeypatch.setattr(router, "JellyfinClient", Client)
    return state, writes, runtime, probes


@pytest.mark.parametrize("url,key", [("", ""), ("http://jellyfin:8096", ""), ("", "orphan-key")])
def test_unconfigured_jellyfin_can_be_saved_without_network_probe(jellyfin, url, key):
    _, writes, runtime, probes = jellyfin
    result = asyncio.run(router.api_jellyfin_config_set(router.JellyfinConfigBody(
        url=url, api_key=key, user_id="stale", user_name="Stale")))
    assert result["saved"] is True
    assert result["has_api_key"] is False
    assert result["user_id"] == ""
    assert writes[0][:4] == (url, "", "", "")
    assert runtime[0]["api_key"] == ""
    assert probes == []


def test_blank_key_preserves_secret_for_same_server(jellyfin):
    state, writes, _, probes = jellyfin
    state.jellyfin_cfg = {"url": "http://jellyfin:8096", "api_key": "stored"}
    result = asyncio.run(router.api_jellyfin_config_set(router.JellyfinConfigBody(
        url="http://jellyfin:8096/", api_key="", user_id="user")))
    assert result["has_api_key"] is True
    assert writes[0][1] == "stored"
    assert probes == [("http://jellyfin:8096/", "stored")]


def test_server_change_does_not_reuse_previous_secret(jellyfin):
    state, writes, _, probes = jellyfin
    state.jellyfin_cfg = {"url": "http://old:8096", "api_key": "stored"}
    asyncio.run(router.api_jellyfin_config_set(router.JellyfinConfigBody(url="http://new:8096", api_key="")))
    assert writes[0][1] == ""
    assert probes == []


def test_configured_jellyfin_still_rejects_invalid_user(jellyfin):
    _, writes, _, probes = jellyfin
    with pytest.raises(HTTPException) as error:
        asyncio.run(router.api_jellyfin_config_set(router.JellyfinConfigBody(
            url="http://jellyfin:8096", api_key="key", user_id="invalid")))
    assert error.value.status_code == 400
    assert writes == []
    assert len(probes) == 1
