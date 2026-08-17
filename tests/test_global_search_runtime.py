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
