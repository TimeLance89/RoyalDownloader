"""Royal Discovery 3.0 Home-only wiring and compatibility regression guards."""
from pathlib import Path

from core.home_layout import HOME_RAIL_IDS, HomeLayoutStore

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "web/js/features/home"


def test_new_discovery_rail_is_visible_and_old_layouts_migrate():
    assert "discovered" in HOME_RAIL_IDS
    defaults = HomeLayoutStore.defaults()
    assert "discovered" not in defaults["hidden_rails"]
    assert defaults["rail_order"].index("discovered") == 1
    legacy = HomeLayoutStore.normalize({
        "rail_order": ["personal", "top", "series", "genre", "explore", "gems", "fresh"],
        "hidden_rails": [],
    })
    assert legacy["rail_order"][1] == "discovered"
    assert 'id: "discovered"' in (HOME / "layout-model.js").read_text(encoding="utf-8")


def test_tmdb_suggestions_search_provider_catalog_instead_of_enqueuing():
    cards = (HOME / "cards.js").read_text(encoding="utf-8")
    search = (ROOT / "web/js/features/search/home.js").read_text(encoding="utf-8")
    assert "if (item.tmdb_discovery) searchHomeTitle(item.title, kind)" in cards
    assert "if (!item.tmdb_discovery) registerDock(card, entry)" in cards
    assert "function searchTitle(title, kind" in search


def test_user_feed_not_cached_in_shared_catalog_or_mixed_after_user_switch():
    data = (HOME / "data.js").read_text(encoding="utf-8")
    cache = (HOME / "cache.js").read_text(encoding="utf-8")
    assert "discoveryOwner === String(getTasteStorageKey()" in data
    assert "discoverySeq++" in data
    assert "personalDiscoveries" not in cache


def test_personal_spotlight_accepts_poster_only_matches_and_more_cards():
    lanes = (HOME / "lanes.js").read_text(encoding="utf-8")
    rows = (HOME / "rows.js").read_text(encoding="utf-8")
    assert "return homePersonalArtworkCandidates();" in lanes
    assert 'entries.slice(0, 12)' in rows


def test_feedback_refreshes_discovery_and_discovery_is_not_in_download_queue():
    taste = (HOME / "taste-ranking.js").read_text(encoding="utf-8")
    composition = (ROOT / "web/js/composition/home.js").read_text(encoding="utf-8")
    assert "onProfileChanged();" in taste
    assert "services.homeData.refreshDiscovery()" in composition
    assert "searchHomeTitle:" in composition
