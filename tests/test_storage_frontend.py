from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_storage_runtime_is_loaded_by_frontend_manifest():
    api_js = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "/storage-manager.js?v=royal-20260817-2" in api_js
    assert "data-royal-storage-manager" in api_js


def test_storage_runtime_exposes_multi_volume_management_and_guarded_cleanup_ui():
    source = (ROOT / "web" / "storage-manager.js").read_text(encoding="utf-8")
    for marker in (
        'id="settings-storage"',
        'id="storage-location-form"',
        'id="storage-location-mode"',
        'value="monitor"',
        'value="media"',
        "/api/storage/status",
        "/api/storage/locations/save",
        "/api/storage/locations/remove",
        "/api/storage/scan",
        "/api/storage/cleanup",
        "physische",
        "dauerhaft löschen?",
        "expires_at:",
        "confirm: true",
    ):
        assert marker in source


def test_storage_runtime_warns_that_nas_paths_require_container_mounts():
    source = (ROOT / "web" / "storage-manager.js").read_text(encoding="utf-8")
    assert "Bind-Mount" in source
    assert "Royal mountet keine Host-Laufwerke selbst" in source
    assert "Nur Live-Monitoring · keine Bereinigung" in source


def test_storage_styles_cover_volume_registry_desktop_and_mobile_layouts():
    css = (ROOT / "web" / "styles" / "storage-manager.css").read_text(encoding="utf-8")
    assert ".storage-summary-ring" in css
    assert ".storage-locations-card" in css
    assert ".storage-location-form" in css
    assert ".storage-volume-members" in css
    assert ".storage-content-candidate" in css
    assert "@media(max-width:620px)" in css
