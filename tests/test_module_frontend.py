from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_module_ui_uses_authoritative_api_and_does_not_dirty_normal_settings():
    source = (ROOT / "web/js/features/settings/modules.js").read_text(encoding="utf-8")
    api = ((ROOT / "web" / "js/core/api.js").read_text(encoding="utf-8") + "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "web/js/composition").glob("*.js")))
    assert "/module-manager.js" not in api
    assert 'api.get("/api/modules", { signal: current.signal })' in source
    assert 'api.put(`/api/modules/${input.dataset.module}`' in source
    assert 'rows.listen(input, "input", (event) => event.stopPropagation())' in source
    assert 'event.stopPropagation();' in source
    assert "needs_configuration" in source
    assert 'new Event("royal:modules-changed")' in source


def test_seerr_action_is_disabled_when_the_module_is_not_available():
    source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    modules = (ROOT / "web/js/features/integrations/settings.js").read_text(encoding="utf-8")
    assert 'new Event("royal:settings-ready")' in source
    assert "async function syncFeatureCapabilities()" in modules
    assert 'module.id === "seerr-sync"' in modules
    assert "button.disabled = !available" in modules
    assert "Seerr-Modul deaktiviert" in modules
