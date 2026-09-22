from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_premium_topbar_is_loaded_after_existing_navigation_layers():
    manifest = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    premium_css = (ROOT / "web" / "styles" / "topbar-premium.css").read_text(encoding="utf-8")

    assert '/styles/topbar-premium.css' in manifest
    assert manifest.index('/styles/topbar-premium.css') > manifest.index('/styles/catalog-polish.css')
    assert '.topbar .tabs > .tab-btn.active' in premium_css
    assert '.topbar .global-search-shell' in premium_css
    assert '.topbar .inbox-trigger' in premium_css
    assert '.topbar .user-menu-trigger' in premium_css
    assert '@media (max-width: 820px)' in premium_css


def test_topbar_keeps_existing_controls_and_adds_premium_semantics():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    topbar = html.split('<header class="topbar">', 1)[1].split('<section id="global-search-page"', 1)[0]

    for control in (
        'data-tab="home"',
        'data-tab="filme"',
        'data-tab="serien"',
        'data-tab="bibliothek"',
        'id="global-search-input"',
        'id="notif-bell"',
        'id="user-menu-trigger"',
        'id="settings-btn"',
    ):
        assert control in topbar
    assert 'class="tab-icon nav-icon"' in topbar
    assert 'class="settings-icon"' in topbar


def test_ctrl_k_remains_a_real_search_shortcut_not_visual_copy_only():
    core = (ROOT / "web" / "core.js").read_text(encoding="utf-8")

    assert 'event.key.toLowerCase() !== "k"' in core
    assert 'input.focus();' in core
