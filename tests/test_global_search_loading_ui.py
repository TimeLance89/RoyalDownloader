from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME_JS = (ROOT / "web" / "screens" / "home.js").read_text(encoding="utf-8")
SEARCH_CSS = (ROOT / "web" / "styles" / "search.css").read_text(encoding="utf-8")
GLOBAL_SEARCH_RUNTIME = (ROOT / "web" / "global-search-runtime.js").read_text(encoding="utf-8")
CATALOG_RUNTIME = (ROOT / "web" / "catalog-runtime.js").read_text(encoding="utf-8")


def test_global_search_has_distinct_loading_state_before_empty_state():
    assert 'state.globalSearch.loading = true;' in HOME_JS
    assert 'page.classList.toggle("is-loading", state.globalSearch.loading);' in HOME_JS
    assert 'Suche nach «${state.globalSearch.query}» …' in HOME_JS
    assert 'Nichts in diesem Filter' in HOME_JS


def test_progressive_search_stays_loading_while_empty_catalogs_are_pending():
    assert 'state.globalSearch.results = mergeCatalogGroups(groups);' in GLOBAL_SEARCH_RUNTIME
    assert 'state.globalSearch.loading = state.globalSearch.results.length === 0' in GLOBAL_SEARCH_RUNTIME
    assert '&& state.globalSearch.pendingCatalogs.length > 0;' in GLOBAL_SEARCH_RUNTIME
    assert 'state.globalSearch.loading = groups.size === 0' not in GLOBAL_SEARCH_RUNTIME


def test_global_search_empty_message_is_hidden_during_loading_as_defense_in_depth():
    assert '.global-search-page.is-loading .global-search-empty { display: none; }' in SEARCH_CSS


def test_rendered_catalog_pages_start_thumbnail_downloads_immediately():
    start = CATALOG_RUNTIME.index('function scheduleResultPoster(image, coverCandidates)')
    end = CATALOG_RUNTIME.index('\nfunction discardObservedResultPosters', start)
    scheduler = CATALOG_RUNTIME[start:end]
    assert 'image.loading = "eager";' in scheduler
    assert 'image.src = coverCandidates[coverIndex];' in scheduler
    assert 'if (resultPosterObserver) resultPosterObserver.observe(image);' in scheduler
    assert scheduler.rstrip().endswith('load();\n}')
