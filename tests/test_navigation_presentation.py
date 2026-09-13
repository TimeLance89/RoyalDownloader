from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def navigation_css():
    return (ROOT / "web" / "styles" / "catalog-polish.css").read_text(encoding="utf-8")


def navigation_html():
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_focused_navigation_stays_in_existing_polish_layer():
    manifest = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    assert '/styles/catalog-polish.css' in manifest
    assert '/styles/navigation.css' not in manifest
    assert "Navigation: four destinations, focused discovery" in navigation_css()


def test_desktop_navigation_uses_streaming_style_active_pill():
    css = navigation_css()
    assert "@media (min-width: 821px)" in css
    assert ".topbar .tabs > .tab-btn.active" in css
    assert "border-radius: 999px;" in css
    assert "background: rgba(255, 255, 255, .18);" in css
    assert "padding-inline: clamp(18px, 1.35vw, 25px);" in css
    assert ".nav-menu-trigger.is-open" in css
    assert ".nav-menu-popover" in css


def test_primary_navigation_has_a_clear_task_order_and_groups_discovery():
    html = navigation_html()
    topbar = html.split('<nav class="tabs"', 1)[1].split('</nav>', 1)[0]
    destinations = [
        'data-tab="home"',
        'data-tab="filme"',
        'data-tab="serien"',
        'data-tab="bibliothek"',
    ]
    positions = [topbar.index(destination) for destination in destinations]
    assert positions == sorted(positions)
    assert 'data-nav-menu="desktop"' in topbar
    assert 'id="desktop-discovery-menu"' in topbar
    assert 'data-tab="kalender"' in topbar
    assert 'data-tab="anime"' in topbar
    assert 'data-tab="aniworld"' in topbar
    assert 'data-mood-open' in topbar


def test_mobile_navigation_keeps_five_touch_targets_and_moves_secondary_areas_to_more():
    html = navigation_html()
    mobile = html.split('<nav class="mobile-tabs"', 1)[1].split('</nav>', 1)[0]
    assert mobile.count('class="tab-btn') == 4
    assert 'data-nav-menu="mobile"' in mobile
    assert 'id="mobile-more-menu"' in mobile
    assert 'data-tab="einstellungen"' in mobile
    assert 'data-tab="kalender"' in mobile


def test_navigation_rules_are_scoped_to_desktop_topbar_not_mobile_bottom_nav():
    css = navigation_css()
    navigation_section = css.split("Navigation: four destinations, focused discovery", 1)[1]
    assert ".topbar .tabs" in navigation_section
    assert ".mobile-tabs .nav-menu--mobile" in navigation_section
