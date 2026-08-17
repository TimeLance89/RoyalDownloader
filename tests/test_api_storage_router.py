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
    assert ("GET", "/api/storage/locations") in pairs
    assert ("POST", "/api/storage/locations/save") in pairs
    assert ("POST", "/api/storage/locations/remove") in pairs
    assert ("POST", "/api/storage/scan") in pairs
    assert ("POST", "/api/storage/cleanup") in pairs
    assert ("POST", "/api/storage/move/plan") in pairs
    assert ("POST", "/api/storage/move") in pairs
    assert ("GET", "/api/v1/storage/status") in pairs
    assert ("POST", "/api/v1/storage/move/plan") in pairs
    assert ("POST", "/api/v1/storage/move") in pairs


def test_storage_status_route_uses_configured_paths(monkeypatch, tmp_path):
    movies = tmp_path / "movies"
    series = tmp_path / "series"
    movies.mkdir(); series.mkdir()
    monkeypatch.setattr(storage_api.appconfig, "load", lambda: str(movies))
    monkeypatch.setattr(storage_api.appconfig, "load_series_path", lambda: str(series))
    monkeypatch.setattr(storage_api.appconfig, "load_deployment_mode", lambda: "nas")
    monkeypatch.setattr(storage_api, "load_storage_locations", lambda: [])
    payload = asyncio.run(storage_api.api_storage_status())
    assert payload["deployment_mode"] == "nas"
    assert {root["key"] for root in payload["roots"]} == {"movies", "series"}


def test_storage_location_save_uses_safe_registry(monkeypatch):
    monkeypatch.setattr(storage_api.appconfig, "demo_mode_enabled", lambda: False)
    calls = []
    monkeypatch.setattr(
        storage_api,
        "save_storage_location",
        lambda **kwargs: calls.append(kwargs) or {
            "id": "external",
            "label": kwargs["label"],
            "path": kwargs["path"],
            "mode": kwargs["mode"],
        },
    )
    body = storage_api.StorageLocationBody(
        label="Externe Festplatte",
        path="/external-media",
        mode="monitor",
    )
    payload = asyncio.run(storage_api.api_storage_location_save(body))
    assert payload["saved"] is True
    assert payload["location"]["path"] == "/external-media"
    assert calls[0]["mode"] == "monitor"


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


def test_move_plan_returns_safe_targets(monkeypatch):
    monkeypatch.setattr(storage_api.appconfig, "demo_mode_enabled", lambda: False)
    monkeypatch.setattr(storage_api, "_media_paths", lambda: {"movies": "/movies", "series": "/series"})
    monkeypatch.setattr(storage_api, "load_storage_locations", lambda: [])
    monkeypatch.setattr(storage_api, "plan_move_candidate", lambda *args, **kwargs: {
        "source_name": "Movie.mkv",
        "source_kind": "movie",
        "targets": [{"root": "location:external", "eligible": True}],
        "eligible_target_count": 1,
    })
    body = storage_api.StorageMovePlanBody(
        root="movies", relative_path="Movie.mkv", token="x" * 64,
        expected_size=100, expires_at=9999999999,
    )
    payload = asyncio.run(storage_api.api_storage_move_plan(body))
    assert payload["source_kind"] == "movie"
    assert payload["eligible_target_count"] == 1


def test_move_route_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(storage_api.appconfig, "demo_mode_enabled", lambda: False)
    body = storage_api.StorageMoveBody(
        root="movies", relative_path="Movie.mkv", token="x" * 64,
        expected_size=100, expires_at=9999999999,
        destination_root="location:external", confirm=False,
    )
    try:
        asyncio.run(storage_api.api_storage_move(body))
    except storage_api.HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("move without confirmation must fail")


def test_move_route_passes_destination_to_guarded_move(monkeypatch):
    monkeypatch.setattr(storage_api.appconfig, "demo_mode_enabled", lambda: False)
    monkeypatch.setattr(storage_api, "_media_paths", lambda: {"movies": "/movies", "series": "/series"})
    monkeypatch.setattr(storage_api, "load_storage_locations", lambda: [])
    captured = {}

    def fake_move(*args, **kwargs):
        captured.update(kwargs)
        return {"moved": True, "destination_root": kwargs["destination_root"]}

    monkeypatch.setattr(storage_api, "move_candidate", fake_move)
    body = storage_api.StorageMoveBody(
        root="movies", relative_path="Movie.mkv", token="x" * 64,
        expected_size=100, expires_at=9999999999,
        destination_root="location:external", confirm=True,
    )
    payload = asyncio.run(storage_api.api_storage_move(body))
    assert payload["moved"] is True
    assert captured["destination_root"] == "location:external"
