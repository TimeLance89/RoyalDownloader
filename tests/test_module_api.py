from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.api_administration_router import _require_enabled_module
from api.api_module_router import create_module_router
from core.module_manager import ModuleManager, ModuleManifest


class _Controller:
    def __init__(self):
        self.running = False

    def configuration_state(self):
        return True, "konfiguriert"

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
        return True

    def health(self):
        return self.running, "läuft" if self.running else "gestoppt"


def _manager():
    base = ModuleManifest("base", "Base", "", "", {})
    child = ModuleManifest("child", "Child", "", "", {}, requires=("base",))
    manager = ModuleManager(lambda: {"base": True, "child": True}, lambda _: True, (base, child))
    for module_id in ("base", "child"):
        controller = _Controller()
        controller.running = True
        manager.register_controller(module_id, controller)
    return manager


def test_module_api_reports_status_and_dependency_errors():
    app = FastAPI()
    app.include_router(create_module_router(_manager()))
    client = TestClient(app)

    response = client.get("/api/modules")
    assert response.status_code == 200
    assert response.json()["modules"][0]["configured"] is True

    blocked = client.put("/api/modules/base", json={"enabled": False})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["modules"] == ["child"]

    missing = client.put("/api/modules/unknown", json={"enabled": False})
    assert missing.status_code == 404


def test_disabled_feature_guard_returns_a_defined_api_error(monkeypatch):
    manager = ModuleManager(
        lambda: {"seerr-sync": False},
        lambda _: True,
        (ModuleManifest("seerr-sync", "Seerr", "", "", {}),),
    )
    import api.api_administration_router as administration

    monkeypatch.setattr(administration, "state", type("State", (), {"module_manager": manager})())
    try:
        _require_enabled_module("seerr-sync")
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "module_unavailable"
    else:
        raise AssertionError("disabled module must reject its feature route")


def test_relevant_configuration_endpoints_trigger_module_reconciliation():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "api" / "api_administration_router.py").read_text(
        encoding="utf-8",
    )
    for module_id in (
        "automatic-updates",
        "jellyfin-recommendations",
        "telegram-control",
        "seerr-sync",
    ):
        assert f'state.module_manager.reconcile("{module_id}")' in source


def test_module_health_contract_is_additive_and_applies_to_reads_and_writes():
    app = FastAPI()
    app.include_router(create_module_router(_manager()))
    client = TestClient(app)
    payload = client.get("/api/modules").json()
    assert payload["health_schema_version"] == 1
    assert payload["modules"][0]["health"] == "healthy"
    assert payload["modules"][0]["integration_health"] == {"state": "healthy", "detail": "läuft"}
    changed = client.put("/api/modules/child", json={"enabled": False}).json()
    child = next(module for module in changed["modules"] if module["id"] == "child")
    assert child["integration_health"]["state"] == "disabled"


def test_integration_health_uses_explicit_states_without_guessing_error_text():
    from api.integration_health import HEALTH_STATES, integration_health

    for state in HEALTH_STATES:
        assert integration_health({"health": state, "enabled": True})["state"] == state
    assert integration_health({"health": "healthy", "enabled": False})["state"] == "disabled"
    assert integration_health({"health": "healthy", "missing_optional": ["tmdb"]})["state"] == "degraded"
    assert integration_health({"health": "unavailable", "health_detail": "401 offline"})["state"] == "degraded"
    assert integration_health({"health_detail": "401 offline"})["state"] == "unknown"
