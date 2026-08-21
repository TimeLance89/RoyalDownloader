from pathlib import Path

import pytest

import config
import storage_locations as sl


@pytest.fixture
def isolated_storage_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_PROJECT_DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_legacy_migration_checked", True)
    monkeypatch.delenv("SERIENDL_DATA_DIR", raising=False)
    return tmp_path


def test_storage_locations_persist_update_and_remove(isolated_storage_registry):
    created = sl.save_storage_location(
        label="Externe Festplatte",
        path="/external-media",
        mode="monitor",
    )
    assert created["id"]
    assert sl.load_storage_locations() == [created]

    updated = sl.save_storage_location(
        location_id=created["id"],
        label="USB Medien",
        path="/external-media",
        mode="media",
    )
    assert updated["id"] == created["id"]
    assert updated["mode"] == "media"
    assert sl.load_storage_locations() == [updated]

    assert sl.remove_storage_location(created["id"]) is True
    assert sl.load_storage_locations() == []
    assert sl.remove_storage_location(created["id"]) is False


def test_duplicate_storage_path_is_rejected(isolated_storage_registry):
    sl.save_storage_location(label="Disk A", path="/storage/a", mode="monitor")
    with pytest.raises(ValueError, match="bereits eingetragen"):
        sl.save_storage_location(label="Disk A Copy", path="/storage/a", mode="media")


def test_combined_status_deduplicates_media_and_adds_external_volume(monkeypatch):
    def fake_status(paths, deployment_mode):
        movies = paths.get("movies", "")
        if movies == "/movies":
            return {
                "deployment_mode": deployment_mode,
                "enabled": True,
                "poll_interval_seconds": 5,
                "roots": [
                    {
                        "key": "movies", "label": "Filme", "path": "/movies",
                        "available": True, "measurement": "nas_mount",
                        "resolved_path": "/movies", "total_bytes": 1000,
                        "used_bytes": 800, "free_bytes": 200, "used_percent": 80.0,
                        "volume_id": "nas-main",
                    },
                    {
                        "key": "series", "label": "Serien", "path": "/series",
                        "available": True, "measurement": "nas_mount",
                        "resolved_path": "/series", "total_bytes": 1000,
                        "used_bytes": 800, "free_bytes": 200, "used_percent": 80.0,
                        "volume_id": "nas-main",
                    },
                ],
            }
        assert movies == "/external"
        return {
            "deployment_mode": deployment_mode,
            "enabled": True,
            "poll_interval_seconds": 5,
            "roots": [
                {
                    "key": "movies", "label": "Filme", "path": "/external",
                    "available": True, "measurement": "nas_mount",
                    "resolved_path": "/external", "total_bytes": 4000,
                    "used_bytes": 1000, "free_bytes": 3000, "used_percent": 25.0,
                    "volume_id": "usb-disk",
                },
                {"key": "series", "label": "Serien", "path": "", "available": False},
            ],
        }

    monkeypatch.setattr(sl, "storage_status", fake_status)
    payload = sl.combined_storage_status(
        {"movies": "/movies", "series": "/series"},
        "nas",
        [{"id": "ext1", "label": "Externe Festplatte", "path": "/external", "mode": "monitor"}],
    )

    assert payload["summary"] == {
        "total_bytes": 5000,
        "used_bytes": 1800,
        "free_bytes": 3200,
        "used_percent": 36.0,
        "volume_count": 2,
    }
    by_id = {volume["id"]: volume for volume in payload["volumes"]}
    assert by_id["nas-main"]["label"] == "NAS Hauptspeicher"
    assert {member["label"] for member in by_id["nas-main"]["members"]} == {"Filme", "Serien"}
    assert by_id["usb-disk"]["label"] == "Externe Festplatte"
    assert by_id["usb-disk"]["mode"] == "monitor"


def test_only_media_locations_join_smart_scan(monkeypatch):
    calls = []

    def fake_scan(paths, *, max_candidates):
        calls.append(dict(paths))
        root = paths["movies"]
        return {
            "scanned_files": 2,
            "truncated": False,
            "media_file_median_bytes": 10,
            "large_file_threshold_bytes": 20,
            "candidates": [{
                "root": "movies", "root_label": "Filme", "relative_path": "Huge.mkv",
                "name": "Huge.mkv", "kind": "file", "size_bytes": 100,
                "file_count": 1, "media_file_count": 1, "score": 2.0,
                "expires_at": 9999999999, "token": "a" * 64,
            }],
            "errors": [],
        }

    monkeypatch.setattr(sl, "scan_large_content", fake_scan)
    monkeypatch.setattr(sl, "_resolved_directory", lambda value: Path(value))
    monkeypatch.setattr(sl, "_overlaps", lambda root, other: root == other)

    payload = sl.scan_configured_storage(
        {"movies": "/movies", "series": "/series"},
        [
            {"id": "watch", "label": "Backup", "path": "/backup", "mode": "monitor"},
            {"id": "media", "label": "USB Medien", "path": "/external", "mode": "media"},
        ],
        max_candidates=40,
    )

    assert len(calls) == 2
    assert calls[0]["movies"] == "/movies"
    assert calls[1]["movies"] == "/external"
    assert not any(call["movies"] == "/backup" for call in calls)
    assert any(item["root"] == "location:media" for item in payload["candidates"])
    assert any(item["root_label"] == "USB Medien" for item in payload["candidates"])


def test_cleanup_custom_location_requires_media_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(sl, "cleanup_candidate", lambda paths, **kwargs: calls.append((paths, kwargs)) or {
        "deleted": True, "root": "movies", "freed_bytes": 100,
    })
    locations = [
        {"id": "watch", "label": "Backup", "path": "/backup", "mode": "monitor"},
        {"id": "media", "label": "USB Medien", "path": "/external", "mode": "media"},
    ]

    with pytest.raises(ValueError, match="nicht für Medien-Bereinigung"):
        sl.cleanup_configured_candidate(
            {"movies": "/movies", "series": "/series"}, locations,
            root_key="location:watch", relative_path="Huge.mkv", token="a" * 64,
            expected_size=100, expires_at=9999999999,
        )

    result = sl.cleanup_configured_candidate(
        {"movies": "/movies", "series": "/series"}, locations,
        root_key="location:media", relative_path="Huge.mkv", token="a" * 64,
        expected_size=100, expires_at=9999999999,
    )
    assert result["root"] == "location:media"
    assert calls[0][0] == {"movies": "/external", "series": ""}
    assert calls[0][1]["root_key"] == "movies"
