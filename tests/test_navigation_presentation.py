from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def navigation_css():
    return (ROOT / "web" / "styles" / "catalog-polish.css").read_text(encoding="utf-8")


def test_streaming_navigation_stays_in_existing_polish_layer():
    manifest = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    assert '/styles/catalog-polish.css' in manifest
    assert '/styles/navigation.css' not in manifest
    assert "Desktop navigation: calmer streaming hierarchy" in navigation_css()


def test_desktop_navigation_uses_streaming_style_active_pill():
    css = navigation_css()
    assert "@media (min-width: 821px)" in css
    assert ".topbar .tabs .tab-btn.active" in css
    assert "border-radius: 999px;" in css
    assert "background: rgba(255, 255, 255, .18);" in css
    assert "padding-inline: clamp(18px, 1.35vw, 25px);" in css
    assert ".topbar .tabs .tab-icon" in css
    assert "display: none;" in css


def test_desktop_navigation_matches_streaming_content_order_without_html_contract_changes():
    css = navigation_css()
    expected = [
        '[data-tab="home"] { order: 1; }',
        '[data-tab="serien"] { order: 2; }',
        '[data-tab="kalender"] { order: 3; }',
        '[data-tab="filme"] { order: 4; }',
        '[data-tab="anime"] { order: 5; }',
        '[data-tab="aniworld"] { order: 6; }',
        '[data-tab="bibliothek"] { order: 7; }',
        '.mood-nav-open { order: 8; }',
    ]
    for contract in expected:
        assert contract in css


def test_navigation_rules_are_scoped_to_desktop_topbar_not_mobile_bottom_nav():
    css = navigation_css()
    navigation_section = css.split("Desktop navigation: calmer streaming hierarchy", 1)[1]
    assert ".mobile-tabs" not in navigation_section
    assert ".topbar .tabs" in navigation_section
