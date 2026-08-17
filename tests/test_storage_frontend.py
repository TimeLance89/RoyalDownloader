from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_storage_runtime_is_loaded_by_frontend_manifest():
    api_js = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "/storage-manager.js?v=royal-20260817-1" in api_js
    assert "data-royal-storage-manager" in api_js


def test_storage_runtime_exposes_live_scan_and_guarded_cleanup_ui():
    source = (ROOT / "web" / "storage-manager.js").read_text(encoding="utf-8")
    for marker in (
        'id="settings-storage"',
        'data-settings-target="settings-storage"',
        "/api/storage/status",
        "/api/storage/scan",
        "/api/storage/cleanup",
        "dauerhaft löschen?",
        "expires_at:",
        "confirm: true",
    ):
        assert marker in source


def test_storage_styles_cover_desktop_and_mobile_layouts():
    css = (ROOT / "web" / "styles" / "storage-manager.css").read_text(encoding="utf-8")
    assert ".storage-summary-ring" in css
    assert ".storage-content-candidate" in css
    assert "@media(max-width:620px)" in css
