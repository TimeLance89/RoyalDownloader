from fastapi import FastAPI
from fastapi.testclient import TestClient

import pytest

import api.api_storage_autopilot_router as storage_api


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(storage_api, "backend_value", lambda _name: lambda *_args: {"role": "admin"})
    app = FastAPI()
    app.include_router(storage_api.router)
    return TestClient(app)


@pytest.mark.parametrize("alias", ["/api/storage", "/api/v1/storage"])
def test_autopilot_api_rejects_non_admin_on_reads_and_writes(client, monkeypatch, alias):
    monkeypatch.setattr(storage_api, "backend_value", lambda _name: lambda *_args: {"role": "member"})
    calls = []
    monkeypatch.setattr(storage_api, "get_autopilot", lambda **_kw: calls.append("read"))
    monkeypatch.setattr(storage_api, "save_policy", lambda *_args, **_kw: calls.append("write"))
    assert client.get(f"{alias}/autopilot").status_code == 403
    assert client.put(f"{alias}/autopilot", json={"policy": {"mode": "full"}}).status_code == 403
    assert client.post(f"{alias}/optimize").status_code == 403
    assert calls == []


@pytest.mark.parametrize("alias", ["/api/storage", "/api/v1/storage"])
def test_move_requires_explicit_boolean_confirmation(client, monkeypatch, alias):
    calls = []
    monkeypatch.setattr(storage_api, "queue_context", lambda: [])
    monkeypatch.setattr(storage_api, "apply_recommendation", lambda *_args, **_kw: calls.append(True) or {"job_id": "move"})
    endpoint = f"{alias}/recommendations/one/apply"
    assert client.post(endpoint, json={"confirm": False}).status_code == 400
    assert client.post(endpoint, json={"confirm": "true"}).status_code == 422
    assert calls == []
    assert client.post(endpoint, json={"confirm": True}).json()["job"]["job_id"] == "move"
    assert calls == [True]


def test_delete_confirmation_and_safe_conflict_remain_explicit(client, monkeypatch):
    calls = []
    def save(policy, **kwargs):
        calls.append((policy, kwargs))
        if policy.get("auto_delete") and not kwargs["delete_confirmed"]:
            raise ValueError("Vorschau bestätigen")
        return policy
    monkeypatch.setattr(storage_api, "save_policy", save)
    endpoint = "/api/storage/autopilot"
    assert client.put(endpoint, json={"policy": {"auto_delete": True}}).status_code == 409
    assert client.put(endpoint, json={"policy": {"auto_delete": True}, "delete_confirmed": "yes"}).status_code == 422
    response = client.put(endpoint, json={"policy": {"auto_delete": True, "delete_categories": ["royal_partials"]}, "delete_confirmed": True})
    assert response.status_code == 200 and calls[-1][1]["delete_confirmed"] is True


def test_global_auth_protects_storage_autopilot_when_uninitialized_or_signed_out(monkeypatch):
    import server
    monkeypatch.setattr(server.appconfig, "is_initialized", lambda: True)
    monkeypatch.setattr(server, "auth_configured", lambda: True)
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "localhost")
    response = TestClient(server.app, base_url="http://localhost").get("/api/storage/autopilot")
    assert response.status_code == 401


def test_storage_routes_have_both_aliases_and_administration_owner():
    import server
    pairs = {(method, route.path) for route in server.app.routes for method in getattr(route, "methods", ())}
    for prefix in ("/api/storage", "/api/v1/storage"):
        for method, path in (("GET", "/autopilot"), ("PUT", "/autopilot"), ("PUT", "/autopilot/volume"),
                             ("GET", "/recommendations"), ("POST", "/recommendations/{recommendation_id}/apply"),
                             ("POST", "/recommendations/{recommendation_id}/dismiss"), ("GET", "/activity"),
                             ("GET", "/cleanup/preview"), ("POST", "/optimize")):
            assert (method, prefix + path) in pairs
