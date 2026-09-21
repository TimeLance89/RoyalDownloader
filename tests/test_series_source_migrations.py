import server

from providers.serienstream import SerienstreamScraper
from providers.series_migrations import canonical_series_source, equivalent_series_sources


DAHMER = "dahmer-monster-die-geschichte-von-jeffrey-dahmer"
MENENDEZ = "monster-die-geschichte-von-lyle-und-erik-menendez"
ED_GEIN = "monster-die-geschichte-von-ed-gein"
CANONICAL = "monster-2022"


def test_monster_split_series_roots_migrate_to_combined_anthology():
    for legacy in (DAHMER, MENENDEZ, ED_GEIN):
        assert canonical_series_source(f"serienstream:{legacy}") == f"serienstream:{CANONICAL}"
        assert equivalent_series_sources(
            f"serienstream:{legacy}", f"serienstream:{CANONICAL}"
        )


def test_monster_legacy_episode_seasons_are_translated():
    assert canonical_series_source(f"serienstream:{DAHMER}-s01e03") == (
        f"serienstream:{CANONICAL}-s01e03"
    )
    assert canonical_series_source(f"serienstream:{MENENDEZ}-s01e04") == (
        f"serienstream:{CANONICAL}-s02e04"
    )
    assert canonical_series_source(f"serienstream:{ED_GEIN}-s01e07") == (
        f"serienstream:{CANONICAL}-s03e07"
    )


def test_monster_legacy_urls_are_migrated_without_losing_query():
    assert canonical_series_source(
        f"https://s.to/serie/stream/{MENENDEZ}/staffel-1/episode-2?foo=bar"
    ) == f"https://s.to/serie/{CANONICAL}/staffel-2/episode-2?foo=bar"


def test_serienstream_scraper_loads_canonical_monster_root():
    assert SerienstreamScraper._series_slug(
        f"https://s.to/serie/stream/{ED_GEIN}"
    ) == CANONICAL


def test_watchlist_lookup_matches_legacy_monster_entry_to_canonical(monkeypatch):
    stored = {
        "base_slug": f"serienstream:{MENENDEZ}",
        "title": "Monster: Die Geschichte von Lyle und Erik Menendez",
        "download_mode": "latest_season",
        "aliases": [],
    }
    monkeypatch.setattr(server.state, "watchlist", [stored])

    assert server.watchlist_lookup(f"serienstream:{CANONICAL}") is stored
