from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_movie_search_is_not_discarded_by_catalog_timeout():
    source = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    movies_start = source.index("  movies(params) {")
    movies_end = source.index("  movie(slug)", movies_start)
    block = source[movies_start:movies_end]

    assert 'if (params?.mode === "search") return request;' in block
    assert "15_000" in block
    assert block.index('if (params?.mode === "search") return request;') < block.index("15_000")


def test_global_search_runtime_is_loaded():
    source = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "/global-search-runtime.js?v=royal-20260817-1" in source
    assert "data-royal-global-search-runtime" in source
    assert "loadRoyalGlobalSearchRuntime" in source


def test_global_search_merges_all_catalog_results_without_sixty_card_cap():
    source = (ROOT / "web" / "global-search-runtime.js").read_text(encoding="utf-8")
    assert "window.performGlobalSearch = async function performGlobalSearchProgressively" in source
    assert "return uniqueHomeEntries(mixed);" in source
    assert "mixed.length < 60" not in source
    assert ".slice(0, 60)" not in source


def test_global_search_deduplicates_each_catalog_by_content_identity():
    source = (ROOT / "web" / "global-search-runtime.js").read_text(encoding="utf-8")
    assert "function uniqueCatalogContentEntries(entries)" in source
    assert 'typeof uniqueHomeContentEntries === "function"' in source
    assert "return uniqueHomeContentEntries(entries);" in source
    assert ".map((catalog) => uniqueCatalogContentEntries(groups.get(catalog.key) || []))" in source
    assert source.count("state.globalSearch.results = mergeCatalogGroups(groups);") >= 3


def test_global_search_exposes_pending_and_failed_catalogs():
    source = (ROOT / "web" / "global-search-runtime.js").read_text(encoding="utf-8")
    for marker in (
        'label: "Filme"',
        'label: "Serien"',
        'label: "Anime"',
        "state.globalSearch.pendingCatalogs",
        "state.globalSearch.failures",
        "werden noch durchsucht",
        "nicht erreichbar",
    ):
        assert marker in source


def test_global_search_still_uses_all_three_catalog_endpoints():
    source = (ROOT / "web" / "global-search-runtime.js").read_text(encoding="utf-8")
    assert 'api.movies({ mode: "search", query })' in source
    assert 'api.series({ mode: "search", query })' in source
    assert 'api.anime({ mode: "search", query, page: 1 })' in source


def test_opening_global_search_result_keeps_search_behind_detail_modal():
    source = (ROOT / "web" / "global-search-runtime.js").read_text(encoding="utf-8")
    start = source.index("window.openHomeEntry = function openHomeEntryKeepingGlobalSearch")
    end = source.index("const baseRunGlobalSearch", start)
    block = source[start:end]

    assert "closeGlobalSearch" not in block
    assert "selectFpRow(movie.slug, movie)" in block
    assert "openAnimeDetail(anime)" in block
    assert "loadSeries(series)" in block


def test_visible_media_detail_prevents_outside_click_from_destroying_search():
    source = (ROOT / "web" / "global-search-runtime.js").read_text(encoding="utf-8")
    assert "function mediaDetailModalOpen()" in source
    assert 'document.querySelectorAll(".media-modal")' in source
    assert "if (state.globalSearch.active && mediaDetailModalOpen()) return;" in source
