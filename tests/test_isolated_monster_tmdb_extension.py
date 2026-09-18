import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import api_discovery_router
from application_services import movie_catalog
from features.monster_series_extension import (
    MONSTER_TMDB_SERIES,
    inject_monster_search_results,
    monster_source_episode_slug,
    monster_tmdb_series,
    parse_monster_virtual_episode,
)
from providers.models import FilmpalastMovie, FilmpalastSeries, HosterInfo, SeriesEpisode


EXPECTED = {
    113988: 1,
    225634: 2,
    286801: 3,
    299939: 4,
}


def _source_series():
    return FilmpalastSeries(
        title="Monster",
        base_slug="serienstream:monster-2022",
        url="https://serienstream.to/serie/monster-2022",
        seasons={
            season: [
                SeriesEpisode(
                    season=season,
                    episode=episode,
                    slug=f"serienstream:monster-2022-s{season:02d}e{episode:02d}",
                    url=(
                        "https://serienstream.to/serie/monster-2022/"
                        f"staffel-{season}/episode-{episode}"
                    ),
                )
                for episode in (1, 2)
            ]
            for season in range(1, 5)
        },
    )


def test_mapping_is_exactly_the_four_requested_tmdb_ids():
    assert {
        item.tmdb_id: item.source_season
        for item in MONSTER_TMDB_SERIES
    } == EXPECTED
    assert monster_tmdb_series(999999) is None


def test_only_virtual_monster_episode_slugs_translate_to_serienstream():
    assert monster_source_episode_slug(
        "monster-tmdb:225634-s01e03"
    ) == "serienstream:monster-2022-s02e03"
    assert monster_source_episode_slug(
        "monster-tmdb:286801-s01e07"
    ) == "serienstream:monster-2022-s03e07"

    normal = "serienstream:monster-2022-s03e07"
    assert parse_monster_virtual_episode(normal) is None
    assert monster_source_episode_slug(normal) is None

    huhu = "huhu:some-normal-series-s01e01"
    assert parse_monster_virtual_episode(huhu) is None
    assert monster_source_episode_slug(huhu) is None


def test_monster_search_replaces_only_the_four_franchise_provider_cards():
    provider_results = [
        {
            "title": "Monster: Die Geschichte von Ed Gein",
            "year": "2025",
            "base_slug": "huhu:ed-gein",
            "sample_slug": "huhu:ed-gein-s01e01",
            "provider": "huhu",
        },
        {
            "title": "Monarch: Legacy of Monsters",
            "year": "2023",
            "base_slug": "huhu:monarch",
            "sample_slug": "huhu:monarch-s01e01",
            "provider": "huhu",
        },
    ]

    results = inject_monster_search_results("Monster", provider_results)

    assert [item["tmdb_id"] for item in results[:4]] == list(EXPECTED)
    assert all(item["special_series"] == "monster_tmdb" for item in results[:4])
    assert not any(item.get("base_slug") == "huhu:ed-gein" for item in results)
    assert any(item.get("base_slug") == "huhu:monarch" for item in results)

    untouched = inject_monster_search_results("Monarch", provider_results)
    assert untouched == provider_results


@pytest.mark.parametrize("tmdb_id,source_season", EXPECTED.items())
def test_special_load_exposes_logical_season_one_only(
    monkeypatch, tmdb_id, source_season,
):
    captured = {}

    monkeypatch.setattr(
        api_discovery_router,
        "get_series_for_value",
        lambda value: _source_series() if value == "serienstream:monster-2022" else None,
    )
    monkeypatch.setattr(
        api_discovery_router,
        "get_tmdb_client",
        lambda: SimpleNamespace(
            configured=True,
            series_by_id=lambda value, _title="": {
                "tmdb_id": value,
                "title": f"TMDB {value}",
                "year": "2026",
                "description": "Exact TMDB metadata",
                "genres": ["Drama"],
                "season_episode_counts": {"1": 2},
            },
        ),
    )

    def fake_series_to_dict(series, **_kwargs):
        captured["series"] = series
        return {
            "title": series.title,
            "base_slug": series.base_slug,
            "url": series.url,
            "seasons": [
                {
                    "season": season,
                    "episodes": [
                        {
                            "season": episode.season,
                            "episode": episode.episode,
                            "slug": episode.slug,
                            "url": episode.url,
                            "in_jellyfin": False,
                        }
                        for episode in episodes
                    ],
                }
                for season, episodes in series.seasons.items()
            ],
            "episode_count": len(series.all_episodes),
            "jellyfin_configured": False,
            "jellyfin_pending": True,
            "jellyfin_available": True,
        }

    monkeypatch.setattr(api_discovery_router, "series_to_dict", fake_series_to_dict)
    monkeypatch.setattr(
        api_discovery_router,
        "state",
        SimpleNamespace(series_cache={}),
    )

    payload = asyncio.run(
        api_discovery_router.api_monster_tmdb_series_load(
            api_discovery_router.MonsterSeriesLoadBody(
                tmdb_id=tmdb_id,
                defer_checks=True,
            )
        )
    )

    series = captured["series"]
    assert series.base_slug == f"monster-tmdb:{tmdb_id}"
    assert series.season_numbers == [1]
    assert [episode.episode for episode in series.all_episodes] == [1, 2]
    assert all(episode.season == 1 for episode in series.all_episodes)
    assert series.all_episodes[0].slug == f"monster-tmdb:{tmdb_id}-s01e01"
    assert series.all_episodes[0].url.endswith(
        f"/staffel-{source_season}/episode-1"
    )
    assert payload["tmdb_id"] == tmdb_id
    assert payload["special_series"] == "monster_tmdb"
    assert payload["monster_source_season"] == source_season


def test_special_load_rejects_every_other_tmdb_id():
    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            api_discovery_router.api_monster_tmdb_series_load(
                api_discovery_router.MonsterSeriesLoadBody(tmdb_id=42)
            )
        )
    assert raised.value.status_code == 404


def test_virtual_episode_uses_serienstream_loader_but_normal_huhu_does_not(monkeypatch):
    calls = []

    class FakeSto:
        def get_movie(self, slug):
            calls.append(slug)
            return FilmpalastMovie(
                title="Provider Monster",
                url=slug,
                hosters=[HosterInfo("VOE", "https://example.invalid/voe")],
            )

    monkeypatch.setattr(movie_catalog, "get_sto_scraper", lambda: FakeSto())
    monkeypatch.setattr(
        movie_catalog.state.provider_health,
        "request_allowed",
        lambda provider: provider == "serienstream",
    )
    movie_catalog.state.series_cache.pop("monster-tmdb:225634", None)

    movie = movie_catalog.load_movie_for_slug("monster-tmdb:225634-s01e03")

    assert calls == ["serienstream:monster-2022-s02e03"]
    assert movie is not None
    assert movie.provider == "serienstream"
    assert movie.title.endswith("S01E03")
    assert "Lyle and Erik Menendez" in movie.title

    assert movie_catalog.provider_for_value("huhu:ordinary-series-s01e01") == "huhu"


def test_frontend_routes_only_virtual_base_slugs_to_special_endpoint():
    from pathlib import Path

    api_source = (
        Path(__file__).resolve().parents[1] / "web" / "api.js"
    ).read_text(encoding="utf-8")

    assert '/^monster-tmdb:(\\d+)$/i.exec(baseSlug || sampleSlug || "")' in api_source
    assert '"/api/series/monster-tmdb-load"' in api_source
    assert '"/api/series/load"' in api_source
