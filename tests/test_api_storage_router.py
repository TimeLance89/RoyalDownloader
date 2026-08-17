import asyncio
from pathlib import Path

import api_storage_router as storage_api
import server


def test_storage_routes_are_owned_by_administration_domain():
    pairs = {
        (method, getattr(route, "path", ""))
        for route in server.app.routes
        for method in (getattr(route, "methods", None) or ())
    }
    assert ("GET", "/api/storage/status") in pairs
    assert ("POST", "/api/storage/scan") in pairs
    assert ("POST", "/api/storage/cleanup") in pairs
    assert ("GET", "/api/v1/storage/status") in pairs


def test_storage_status_route_uses_configured_paths(monkeypatch, tmp_path):
    movies = tmp_path / "movies"
    series = tmp_path / "series"
    movies.mkdir(); series.mkdir()
    monkeypatch.setattr(storage_api.appconfig, "load", lambda: str(movies))
    monkeypatch.setattr(storage_api.appconfig, "load_series_path", lambda: str(series))
    monkeypatch.setattr(storage_api.appconfig, "load_deployment_mode", lambda: "nas")
    payload = asyncio.run(storage_api.api_storage_status())
    assert payload["deployment_mode"] == "nas"
    assert {root["key"] for root in payload["roots"]} == {"movies", "series"}


def test_cleanup_route_requires_explicit_confirmation(monkeypatch, tmp_path):
    movies = tmp_path / "movies"; movies.mkdir()
    monkeypatch.setattr(storage_api.appconfig, "demo_mode_enabled", lambda: False)
    monkeypatch.setattr(storage_api.appconfig, "load", lambda: str(movies))
    monkeypatch.setattr(storage_api.appconfig, "load_series_path", lambda: str(movies))
    body = storage_api.StorageCleanupBody(
        root="movies", relative_path="example.mkv", token="x" * 64,
        expected_size=1, expires_at=9999999999, confirm=False,
    )
    try:
        asyncio.run(storage_api.api_storage_cleanup(body))
    except storage_api.HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("cleanup without confirmation must fail")
