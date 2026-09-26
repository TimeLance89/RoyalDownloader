"""Enforce the migrated boundaries without constraining presentation source layout."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_http_and_websocket_have_single_owners():
    for path in WEB.rglob("*.js"):
        source = path.read_text(encoding="utf-8")
        if path != WEB / "js/core/api.js":
            assert not re.search(r"\bfetch\s*\(", source), path
        if path != WEB / "js/core/websocket.js":
            assert not re.search(r"\bnew\s+WebSocket\s*\(", source), path


def test_native_module_imports_resolve_without_build_step():
    modules = [WEB / "app.js", *list((WEB / "js").rglob("*.js"))]
    for path in modules:
        source = path.read_text(encoding="utf-8")
        for target in re.findall(r'from\s+["\']([^"\']+)["\']', source):
            assert target.startswith("."), (path, target)
            assert (path.parent / target).resolve().is_file(), (path, target)
    markup = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<script type="module" src="/app.js?' in markup
    assert "/screens/movie-releases.js" not in markup
    assert not (WEB / "screens/movie-releases.js").exists()


def test_migrated_features_do_not_install_new_window_globals():
    for path in (WEB / "js/features").rglob("*.js"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\bwindow\.\w+\s*=(?!=)", source), path


def test_architecture_and_migration_inventory_are_documented():
    assert (ROOT / "docs/FRONTEND_ARCHITECTURE.md").is_file()
    assert (ROOT / "docs/FRONTEND_AUDIT.md").is_file()
