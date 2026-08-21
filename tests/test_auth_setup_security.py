import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import api_setup_router
import server


def test_ui_config_public_read_but_authenticated_write_after_setup(monkeypatch):
    monkeypatch.setattr(server.appconfig, "is_initialized", lambda: True)
    monkeypatch.setattr(server, "auth_configured", lambda: True)
    save_called = False

    def _save(_language):
        nonlocal save_called
        save_called = True
        return True

    monkeypatch.setattr(server.appconfig, "save_ui_language", _save)
    client = TestClient(server.app)

    assert client.get("/api/ui/config").status_code == 200
    response = client.post("/api/ui/config", json={"language": "en"})

    assert response.status_code == 401
    assert response.json()["code"] == "auth_required"
    assert save_called is False


def test_ui_config_write_remains_available_during_setup(monkeypatch):
    monkeypatch.setattr(server.appconfig, "is_initialized", lambda: False)
    monkeypatch.setattr(server, "auth_configured", lambda: False)
    monkeypatch.setattr(server.appconfig, "save_ui_language", lambda _language: True)
    previous_language = server.state.ui_language
    previous_tmdb = dict(server.state.tmdb_cfg)
    try:
        response = TestClient(server.app).post(
            "/api/ui/config", json={"language": "en"},
        )
        assert response.status_code == 200
        assert response.json()["saved"] is True
    finally:
        server.state.ui_language = previous_language
        server.state.tmdb_cfg = previous_tmdb
        server.state.tmdb_client = server.TMDBClient(**previous_tmdb)


def test_fail_closed_protects_initialized_install_without_account(monkeypatch):
    monkeypatch.setattr(server.appconfig, "is_initialized", lambda: True)
    monkeypatch.setattr(server, "auth_configured", lambda: False)
    monkeypatch.setenv("APP_REQUIRE_AUTH", "true")

    assert server.auth_required() is True
    assert server.setup_required() is True
    response = TestClient(server.app).get("/api/config")
    assert response.status_code == 401
    assert response.json()["code"] == "auth_required"


def test_legacy_open_lan_flag_cannot_disable_auth(monkeypatch):
    monkeypatch.setattr(server.appconfig, "is_initialized", lambda: True)
    monkeypatch.setattr(server, "auth_configured", lambda: False)
    monkeypatch.setenv("APP_REQUIRE_AUTH", "false")

    assert server.auth_required() is True


def test_public_legacy_health_contains_only_liveness():
    response = TestClient(server.app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_parallel_setup_completion_rejects_second_request(monkeypatch):
    monkeypatch.setattr(server.appconfig, "is_initialized", lambda: False)
    monkeypatch.setattr(server, "auth_configured", lambda: False)
    # This test targets the non-blocking transaction lock. Bootstrap validation
    # has dedicated adversarial coverage and is stubbed here so both concurrent
    # requests reach the lock deterministically without touching real token state.
    monkeypatch.setattr(api_setup_router, "verify_setup_token", lambda _token, _request: None)
    monkeypatch.setattr(api_setup_router, "consume_setup_token", lambda: None)
    entered = threading.Event()
    release = threading.Event()

    async def _slow_complete(_body, _request):
        entered.set()
        assert release.wait(timeout=5)
        return {"saved": True}

    monkeypatch.setattr(server, "_api_setup_complete_locked", _slow_complete)

    def _complete():
        return TestClient(server.app).post(
            "/api/setup/complete",
            json={"save_path": "/tmp", "bootstrap_token": "test-bootstrap-token"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_complete)
        assert entered.wait(timeout=5)
        second = pool.submit(_complete).result(timeout=5)
        release.set()
        first_response = first.result(timeout=5)

    assert first_response.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "setup_in_progress"
    assert "set-cookie" not in second.headers
