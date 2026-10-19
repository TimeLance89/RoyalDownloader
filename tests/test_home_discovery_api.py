"""Authentication and per-user boundary regression for optional Home discovery."""

import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.api_discovery_router as router


def _auth(monkeypatch, current_user):
    # Isolated route contract: the app's real auth service needs a registered
    # composition backend, which the Home router test intentionally lacks.
    monkeypatch.setitem(sys.modules, "application_services.auth",
                        SimpleNamespace(current_user=current_user))


def _request():
    return SimpleNamespace(headers={}, cookies={})


def test_home_discovery_requires_authenticated_profile(monkeypatch):
    _auth(monkeypatch, lambda headers, cookies: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(router.api_home_discovery(_request()))
    assert exc.value.status_code == 401


def test_home_discovery_can_be_disabled_without_accessing_tmdb(monkeypatch):
    _auth(monkeypatch, lambda headers, cookies: {"id": "user-a"})
    monkeypatch.setenv("ROYAL_HOME_DISCOVERY_V3_ENABLED", "0")
    monkeypatch.setattr(router, "get_tmdb_client", lambda: (_ for _ in ()).throw(AssertionError("TMDB must be skipped")))
    assert asyncio.run(router.api_home_discovery(_request())) == {
        "available": False, "results": [], "disabled": True,
    }


def test_home_discovery_never_reuses_another_household_profiles_taste(monkeypatch):
    monkeypatch.delenv("ROYAL_HOME_DISCOVERY_V3_ENABLED", raising=False)
    active = ["user-a"]
    _auth(monkeypatch, lambda headers, cookies: {"id": active[0]})

    class Stores:
        def for_user(self, user_id):
            return SimpleNamespace(public_profile=lambda: {"profile_owner": user_id})

    calls = []

    def get(user_id, profile, client):
        calls.append((user_id, profile["profile_owner"]))
        return {"available": True, "results": [{"id": user_id}]}

    monkeypatch.setattr(router.state, "taste_profiles", Stores(), raising=False)
    monkeypatch.setattr(router, "_HOME_DISCOVERY", SimpleNamespace(get=get))
    monkeypatch.setattr(router, "get_tmdb_client", lambda: object())
    first = asyncio.run(router.api_home_discovery(_request()))
    active[0] = "user-b"
    second = asyncio.run(router.api_home_discovery(_request()))
    assert first["results"] != second["results"]
    assert calls == [("user-a", "user-a"), ("user-b", "user-b")]
