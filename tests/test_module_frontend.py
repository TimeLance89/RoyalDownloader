from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_module_ui_uses_authoritative_api_and_does_not_dirty_normal_settings():
    source = (ROOT / "web" / "module-manager.js").read_text(encoding="utf-8")
    api = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "/module-manager.js?v=royal-20260920-2" in api
    assert 'api.get("/api/modules")' in source
    assert 'api._req("PUT", `/api/modules/${input.dataset.module}`' in source
    assert 'input.addEventListener("input", (event) => event.stopPropagation())' in source
    assert 'event.stopPropagation();' in source
    assert "needs_configuration" in source
