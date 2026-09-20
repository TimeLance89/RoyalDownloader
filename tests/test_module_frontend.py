from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_module_ui_uses_authoritative_api_and_does_not_dirty_normal_settings():
    source = (ROOT / "web" / "module-manager.js").read_text(encoding="utf-8")
    api = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "/module-manager.js?v=royal-20260920-4" in api
    assert 'api.get("/api/modules")' in source
    assert 'api._req("PUT", `/api/modules/${input.dataset.module}`' in source
    assert 'input.addEventListener("input", (event) => event.stopPropagation())' in source
    assert 'event.stopPropagation();' in source
    assert "needs_configuration" in source
    assert 'new Event("royal:modules-changed")' in source


def test_seerr_action_is_disabled_when_the_module_is_not_available():
    source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    modules = (ROOT / "web" / "module-manager.js").read_text(encoding="utf-8")
    assert 'new Event("royal:settings-ready")' in source
    assert "const syncFeatureCapabilities = async ()" in modules
    assert 'module.id === "seerr-sync"' in modules
    assert "button.disabled = !available" in modules
    assert "Seerr-Modul deaktiviert" in modules
