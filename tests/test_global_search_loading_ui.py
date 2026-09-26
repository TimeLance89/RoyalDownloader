from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME_JS = (ROOT / "web/js/features/search/index.js").read_text(encoding="utf-8")
SEARCH_CSS = (ROOT / "web" / "styles" / "search.css").read_text(encoding="utf-8")
GLOBAL_SEARCH_RUNTIME = (ROOT / "web/js/features/search/index.js").read_text(encoding="utf-8")
CATALOG_RUNTIME = (ROOT / "web/screens/movies.js").read_text(encoding="utf-8")


def test_global_search_has_distinct_loading_state_before_empty_state():
    assert 'data.loading = true;' in HOME_JS
    assert 'page.classList.toggle("is-loading", data.loading);' in HOME_JS
    assert 'Suche nach «${data.query}» …' in HOME_JS
    assert 'Nichts in diesem Filter' in HOME_JS


def test_progressive_search_stays_loading_while_empty_catalogs_are_pending():
    assert 'data.results = mergeCatalogGroups(groups);' in GLOBAL_SEARCH_RUNTIME
    assert 'data.loading = data.results.length === 0' in GLOBAL_SEARCH_RUNTIME
    assert '&& data.pendingCatalogs.length > 0;' in GLOBAL_SEARCH_RUNTIME
    assert 'data.loading = groups.size === 0' not in GLOBAL_SEARCH_RUNTIME


def test_global_search_empty_message_is_hidden_during_loading_as_defense_in_depth():
    assert '.global-search-page.is-loading .global-search-empty { display: none; }' in SEARCH_CSS


def test_rendered_catalog_pages_start_thumbnail_downloads_immediately():
    start = CATALOG_RUNTIME.index('function scheduleResultPoster(image, coverCandidates)')
    end = CATALOG_RUNTIME.index('\nfunction discardObservedResultPosters', start)
    scheduler = CATALOG_RUNTIME[start:end]
    assert 'sharedPresentation.cardArtwork.set(image, coverCandidates.map(url => ({ url })), { eager: true });' in scheduler
    artwork = (ROOT / "web/js/shared/components/card-artwork.js").read_text(encoding="utf-8")
    assert 'image.loading = "eager";' in artwork
    assert 'image.src = candidate.url;' in artwork
    assert 'if (eager) start(image); else observe(image);' in artwork
