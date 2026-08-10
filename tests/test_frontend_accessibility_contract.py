from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
HOME = (ROOT / "web" / "screens" / "home.js").read_text(encoding="utf-8")
CORE = (ROOT / "web" / "core.js").read_text(encoding="utf-8")
TASTE = (ROOT / "web" / "taste_v2.js").read_text(encoding="utf-8")
CARD_CSS = (ROOT / "web" / "styles" / "home-card-hover.css").read_text(encoding="utf-8")


def test_global_search_does_not_put_expanded_state_on_searchbox():
    input_markup = INDEX.split('id="global-search-input"', 1)[1].split(">", 1)[0]
    assert "aria-expanded" not in input_markup
    global_render = HOME.split("function renderGlobalSearchResults()", 1)[1].split(
        "async function performGlobalSearch", 1
    )[0]
    assert 'input.setAttribute("aria-expanded"' not in global_render


def test_named_home_tracks_are_accessible_groups():
    for track_id in (
        "home-movies-track",
        "home-top-track",
        "home-series-track",
        "home-genre-track",
        "home-explore-track",
        "home-gems-track",
        "home-new-track",
    ):
        markup = INDEX.split(f'id="{track_id}"', 1)[1].split(">", 1)[0]
        assert 'role="group"' in markup
        assert 'aria-label="' in markup


def test_hidden_queue_drawer_is_inert_until_opened():
    drawer_markup = INDEX.split('id="queue-drawer"', 1)[1].split(">", 1)[0]
    assert " inert" in drawer_markup
    assert "drawer.inert = !expanded" in CORE
    assert 'document.getElementById("queue-drawer").inert = false' in CORE


def test_home_card_actions_are_siblings_not_nested_controls():
    assert 'document.createElement("article")' in HOME
    assert 'primaryAction.className = "home-card-primary-action"' in HOME
    assert 'document.createElement("button")' in TASTE
    assert 'control.setAttribute("role", "button")' not in TASTE
    assert 'control.setAttribute("tabindex", "0")' not in TASTE
    assert ".home-card-primary-action {" in CARD_CSS
    assert "#tab-home .home-card-primary-action" not in CARD_CSS
