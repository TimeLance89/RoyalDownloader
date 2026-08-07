from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tmdb_artwork_is_upgraded_for_high_density_displays():
    api = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "_upgradeTmdbImageUrl" in api
    assert '.replace(/^\\/t\\/p\\/w500\\//, "/t/p/w780/")' in api
    assert '.replace(/^\\/t\\/p\\/w1280\\//, "/t/p/original/")' in api
    assert "const parsed = this._upgradeTmdbImageUrl(url);" in api


def test_catalog_artwork_is_not_softened_by_css_filters():
    css = (ROOT / "web" / "styles" / "catalog-polish.css").read_text(encoding="utf-8")
    hero_block = css.split("#tab-filme .movie-feature-art,", 1)[1].split("/* Poster-only", 1)[0]
    assert "filter: none;" in hero_block
    assert "filter: saturate" not in hero_block
    assert "image-rendering: auto;" in hero_block
    assert ".result-card-poster" in css


def test_setup_is_not_part_of_desktop_primary_navigation():
    css = (ROOT / "web" / "styles" / "catalog-polish.css").read_text(encoding="utf-8")
    navigation = css.split("Desktop navigation: calmer streaming hierarchy", 1)[1]
    assert ".topbar .tabs .mobile-settings-tab" in navigation
    assert "display: none !important;" in navigation
    # The actual settings control remains available outside the content tabs.
    assert ".topbar #settings-btn" in navigation
