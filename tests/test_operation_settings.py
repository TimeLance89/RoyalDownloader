"""Runtime facts and explicit mode transitions cannot pretend to migrate a NAS."""
import asyncio

import pytest

import api.api_administration_router as administration
from core.environment_file import deployment_runtime


def test_container_cannot_change_mode_or_prepare_computer_paths(monkeypatch):
    monkeypatch.setattr(administration.appconfig, "load_deployment_mode", lambda: "nas")
    monkeypatch.setattr(administration, "deployment_runtime", lambda: {"startup_managed": True})
    def unexpected(*args):
        raise AssertionError("Mode rejection must precede media/config mutations")
    monkeypatch.setattr(administration, "_prepare_media_directory", unexpected)
    monkeypatch.setattr(administration.appconfig, "save", unexpected)
    with pytest.raises(administration.HTTPException) as caught:
        asyncio.run(administration.api_config_set(administration.ConfigBody(
            deployment_mode="desktop", save_path="C:\\Royal\\Filme", series_path="C:\\Royal\\Serien")))
    assert caught.value.status_code == 409


def test_runtime_reports_actual_listener_instead_of_a_saved_profile(monkeypatch, tmp_path):
    monkeypatch.setattr("core.runtime_paths.in_container", lambda: False)
    monkeypatch.setenv("SERIENDL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("ROYAL_DEPLOYMENT_MODE", "nas")
    result = deployment_runtime()
    assert result["mode"] == "desktop"
    assert result["startup_managed"]
    assert not result["container"]
    monkeypatch.setenv("HOST", "0.0.0.0")
    assert deployment_runtime()["mode"] == "nas"


def test_native_installation_can_manage_its_own_start_profile(monkeypatch):
    monkeypatch.setattr("core.runtime_paths.in_container", lambda: False)
    monkeypatch.delenv("SERIENDL_DATA_DIR", raising=False)
    monkeypatch.setenv("HOST", "localhost")
    result = deployment_runtime()
    assert result["mode"] == "desktop" and not result["startup_managed"]
