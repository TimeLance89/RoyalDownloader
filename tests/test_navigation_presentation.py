from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_streaming_navigation_loads_last_in_stylesheet_cascade():
    manifest = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    polish = manifest.index('/styles/catalog-polish.css')
    navigation = manifest.index('/styles/navigation.css')
    assert navigation > polish


def test_desktop_navigation_uses_streaming_style_active_pill():
    css = (ROOT / "web" / "styles" / "navigation.css").read_text(encoding="utf-8")
    assert "@media (min-width: 821px)" in css
    assert ".topbar .tabs .tab-btn.active" in css
    assert "border-radius: 999px;" in css
    assert "background: rgba(255, 255, 255, .18);" in css
    assert "padding-inline: clamp(18px, 1.35vw, 25px);" in css
    assert ".topbar .tabs .tab-icon" in css
    assert "display: none;" in css


def test_desktop_navigation_matches_streaming_content_order_without_html_contract_changes():
    css = (ROOT / "web" / "styles" / "navigation.css").read_text(encoding="utf-8")
    expected = [
        '[data-tab="home"] { order: 1; }',
        '[data-tab="serien"] { order: 2; }',
        '[data-tab="filme"] { order: 3; }',
        '[data-tab="anime"] { order: 4; }',
        '[data-tab="bibliothek"] { order: 5; }',
        '.mood-nav-open { order: 6; }',
    ]
    for contract in expected:
        assert contract in css


def test_navigation_layer_does_not_target_mobile_bottom_navigation():
    css = (ROOT / "web" / "styles" / "navigation.css").read_text(encoding="utf-8")
    assert ".mobile-tabs" not in css
    assert ".topbar .tabs" in css
