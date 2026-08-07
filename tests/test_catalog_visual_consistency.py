from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_catalog_polish_loads_after_base_catalog_styles():
    manifest = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    base = manifest.index('/styles/catalog.css')
    polish = manifest.index('/styles/catalog-polish.css')
    assert polish > base


def test_movie_and_series_heroes_share_cinematic_desktop_composition():
    css = (ROOT / "web" / "styles" / "catalog-polish.css").read_text(encoding="utf-8")
    assert "#tab-filme .movie-feature-art" in css
    assert "#tab-serien .series-feature-art" in css
    assert "inset: 0;" in css
    assert "background-position: right 40%;" in css
    assert "background-size: clamp(980px, 63vw, 1400px) auto;" in css
    assert "min-height: clamp(470px, 36vw, 620px);" in css
    # Cover is intentionally limited to the narrow/mobile fallback, where a
    # width-based desktop backdrop would leave uncovered space.
    assert "@media (max-width: 820px)" in css
    assert "background-size: cover;" in css


def test_movie_and_series_shelves_use_the_same_poster_geometry():
    css = (ROOT / "web" / "styles" / "catalog-polish.css").read_text(encoding="utf-8")
    assert "#tab-filme #fp-results.result-shelf" in css
    assert "#tab-serien #series-results.result-shelf" in css
    assert "grid-template-columns: repeat(auto-fill, minmax(210px, 230px));" in css
    assert "aspect-ratio: 2 / 3;" in css


def test_catalogs_deduplicate_logical_media_not_only_provider_slugs():
    library = (ROOT / "web" / "screens" / "library.js").read_text(encoding="utf-8")
    for contract in [
        "function catalogLogicalMediaMatch",
        "function dedupeCatalogMedia",
        "function mergeCatalogMediaRecord",
        "window.mergeCatalogItems = function logicalCatalogMerge",
        "window.applyFpResults = function logicalMovieResults",
        "window.applySeriesResults = function logicalSeriesResults",
    ]:
        assert contract in library
    assert "leftTmdb && rightTmdb" in library
    assert "leftYear && rightYear && leftYear !== rightYear" in library
    assert "merged.source_providers" in library
    assert "merged.content_languages" in library


def test_poster_fallback_initials_ignore_punctuation_only_words():
    library = (ROOT / "web" / "screens" / "library.js").read_text(encoding="utf-8")
    assert "function cleanMediaCardInitials" in library
    assert "/[\\p{L}\\p{N}]/u.test(word)" in library
    assert "window.mediaCardInitials = cleanMediaCardInitials" in library
