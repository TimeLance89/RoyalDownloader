from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_movie_search_is_not_discarded_by_catalog_timeout():
    source = (ROOT / "web/js/features/discovery/movie-browse.js").read_text(encoding="utf-8")
    assert 'timeoutMs: params.mode === "search" ? 0 : 15_000' in source
    search = (ROOT / "web/js/features/search/index.js").read_text(encoding="utf-8")
    assert "timeoutMs: 0" in search


def test_global_search_runtime_is_loaded():
    source = (ROOT / "web/js/legacy-adapter.js").read_text(encoding="utf-8")
    assert 'import { createSearch } from "./features/search/index.js"' in source
    assert 'search: createSearch(' in source


def test_global_search_merges_all_catalog_results_without_sixty_card_cap():
    source = (ROOT / "web" / "js/features/search/index.js").read_text(encoding="utf-8")
    assert "async function performGlobalSearch(query, requestId, current)" in source
    assert "return uniqueHomeEntries(mixed);" in source
    assert "mixed.length < 60" not in source
    assert ".slice(0, 60)" not in source


def test_global_search_deduplicates_each_catalog_by_content_identity():
    source = (ROOT / "web" / "js/features/search/index.js").read_text(encoding="utf-8")
    assert "function uniqueCatalogContentEntries(entries)" in source
    assert 'typeof uniqueHomeContentEntries === "function"' in source
    assert "return uniqueHomeContentEntries(entries);" in source
    assert ".map((catalog) => uniqueCatalogContentEntries(groups.get(catalog.key) || []))" in source
    assert source.count("data.results = mergeCatalogGroups(groups);") >= 3


def test_global_search_exposes_pending_and_failed_catalogs():
    source = (ROOT / "web" / "js/features/search/index.js").read_text(encoding="utf-8")
    for marker in (
        'label: "Filme"',
        'label: "Serien"',
        'label: "Anime"',
        "data.pendingCatalogs",
        "data.failures",
        "werden noch durchsucht",
        "nicht erreichbar",
    ):
        assert marker in source


def test_global_search_still_uses_all_three_catalog_endpoints():
    source = (ROOT / "web" / "js/features/search/index.js").read_text(encoding="utf-8")
    assert 'client.get(`/api/movies?' in source
    assert 'client.get(`/api/series?' in source
    assert 'client.get(`/api/anime?' in source


def test_global_search_exposes_tmdb_collections_without_resolving_providers():
    runtime = (ROOT / "web" / "js/features/search/index.js").read_text(encoding="utf-8")
    collection_ui = (ROOT / "web" / "js/features/collections/index.js").read_text(
        encoding="utf-8",
    )
    assert 'label: "Filmreihen"' in runtime
    assert 'client.get(`/api/movie-collections?' in runtime
    assert "openMovieCollection(key)" in (ROOT / "web/js/features/home/cards.js").read_text(encoding="utf-8")
    assert "await client.get(`/api/movie-collections/${encodeURIComponent(collectionId)}`" in collection_ui
    assert "await loadMovie(part, detail.signal)" in collection_ui
    assert "COLLECTION_RESOLVE_WORKERS = 2" in collection_ui
    assert '"unavailable" : "error"' in collection_ui
    assert 'client.post("/api/queue/add", { slugs: available, preferences: {}, source: "collection" }' in collection_ui


def test_opening_global_search_result_keeps_search_behind_detail_modal():
    source = (ROOT / "web/js/features/home/cards.js").read_text(encoding="utf-8")
    start = source.index("function openHomeEntry(")
    end = source.index("function createHomeCard", start)
    block = source[start:end]
    assert "closeGlobalSearch" not in block
    assert "selectFpRow(movie.slug, movie)" in block
    assert "openAnimeDetail(anime)" in block
    assert "loadSeries(series)" in block


def test_visible_media_detail_prevents_outside_click_from_destroying_search():
    source = (ROOT / "web" / "js/features/search/index.js").read_text(encoding="utf-8")
    assert "if (!force && data.active && mediaDetailModalOpen()) return;" in source
    adapter = (ROOT / "web/js/legacy-adapter.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll(".media-modal")' in adapter
