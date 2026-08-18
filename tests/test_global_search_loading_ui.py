from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME_JS = (ROOT / "web" / "screens" / "home.js").read_text(encoding="utf-8")
SEARCH_CSS = (ROOT / "web" / "styles" / "search.css").read_text(encoding="utf-8")


def test_global_search_has_distinct_loading_state_before_empty_state():
    assert 'state.globalSearch.loading = true;' in HOME_JS
    assert 'page.classList.toggle("is-loading", state.globalSearch.loading);' in HOME_JS
    assert 'Suche nach «${state.globalSearch.query}» …' in HOME_JS
    assert 'Nichts in diesem Filter' in HOME_JS


def test_global_search_empty_message_is_hidden_until_loading_finishes():
    assert '.global-search-page.is-loading .global-search-empty { display: none; }' in SEARCH_CSS
