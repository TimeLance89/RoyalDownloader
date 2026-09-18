from pathlib import Path

import pytest

import server
from providers.models import FilmpalastSeries, SeriesEpisode
from providers.series_tmdb_overrides import (
    MONSTER_TMDB_SEASON_OVERRIDES,
    apply_tmdb_season_override,
    logical_episode_identity,
    source_episode_slug,
    tmdb_series_override_for_episode_slug,
    tmdb_series_override_for_value,
    tmdb_series_season_override,
)


EXPECTED = {
    113988: 1,
    225634: 2,
    286801: 3,
    299939: 4,
}


def _anthology():
    return FilmpalastSeries(
        title="Monster",
        base_slug="serienstream:monster-2022",
        url="https://serienstream.to/serie/monster-2022",
        seasons={
            season: [
                SeriesEpisode(
                    season,
                    1,
                    f"serienstream:monster-2022-s{season:02d}e01",
                    (
                        "https://serienstream.to/serie/monster-2022/"
                        f"staffel-{season}/episode-1"
                    ),
                ),
            ]
            for season in range(1, 5)
        },
    )


def test_override_registry_contains_only_requested_monster_tmdb_ids():
    assert {
        override.tmdb_id: override.season
        for override in MONSTER_TMDB_SEASON_OVERRIDES
    } == EXPECTED


@pytest.mark.parametrize("tmdb_id,season", EXPECTED.items())
def test_tmdb_id_maps_to_exact_serienstream_season(tmdb_id, season):
    override = tmdb_series_season_override(tmdb_id)

    assert override is not None
    assert override.provider == "serienstream"
    assert override.source_slug == "monster-2022"
    assert override.season == season
    assert override.source_url == (
        f"https://serienstream.to/serie/monster-2022/staffel-{season}"
    )


def test_unrelated_tmdb_id_has_no_override():
    assert tmdb_series_season_override(94997) is None
    assert tmdb_series_override_for_value("tmdb-series:94997") is None


@pytest.mark.parametrize("tmdb_id,source_season", EXPECTED.items())
def test_virtual_episode_resolves_to_exact_provider_episode(tmdb_id, source_season):
    virtual = f"tmdb-series:{tmdb_id}-s01e03"

    override = tmdb_series_override_for_episode_slug(virtual)

    assert override is not None
    assert override.tmdb_id == tmdb_id
    assert logical_episode_identity(virtual) == (1, 3)
    assert source_episode_slug(virtual) == (
        f"serienstream:monster-2022-s{source_season:02d}e03"
    )


def test_direct_anthology_episode_is_not_affected_by_tmdb_exception():
    source = "serienstream:monster-2022-s03e04"

    assert tmdb_series_override_for_episode_slug(source) is None
    assert logical_episode_identity(source) == (3, 4)
    assert source_episode_slug(source) == source


@pytest.mark.parametrize("tmdb_id,season", EXPECTED.items())
def test_filtered_override_exposes_only_requested_provider_season(tmdb_id, season):
    override = tmdb_series_season_override(tmdb_id)
    filtered = apply_tmdb_season_override(_anthology(), override)

    assert filtered is not None
    assert filtered.base_slug == f"tmdb-series:{tmdb_id}"
    assert filtered.url.endswith(f"/staffel-{season}")
    assert filtered.season_numbers == [1]
    assert [(episode.season, episode.slug) for episode in filtered.all_episodes] == [
        (1, f"tmdb-series:{tmdb_id}-s01e01")
    ]
    assert filtered.all_episodes[0].url.endswith(
        f"/staffel-{season}/episode-1"
    )


@pytest.mark.parametrize("tmdb_id,season", EXPECTED.items())
def test_runtime_virtual_tmdb_source_loads_only_mapped_season(
    monkeypatch, tmdb_id, season,
):
    calls = []

    def load(provider, source):
        calls.append((provider, source))
        return _anthology()

    monkeypatch.setattr(server, "_load_series_for_provider", load)

    loaded = server.get_series_for_value(f"tmdb-series:{tmdb_id}")

    assert loaded is not None
    assert loaded.base_slug == f"tmdb-series:{tmdb_id}"
    assert loaded.season_numbers == [1]
    assert loaded.all_episodes[0].slug == f"tmdb-series:{tmdb_id}-s01e01"
    assert source_episode_slug(loaded.all_episodes[0].slug) == (
        f"serienstream:monster-2022-s{season:02d}e01"
    )
    assert calls == [("serienstream", "serienstream:monster-2022")]


def test_frontend_passes_tmdb_identity_into_series_load():
    root = Path(__file__).resolve().parents[1]
    api_js = (root / "web" / "api.js").read_text(encoding="utf-8")
    series_js = (root / "web" / "screens" / "series.js").read_text(encoding="utf-8")
    movies_js = (root / "web" / "screens" / "movies.js").read_text(encoding="utf-8")

    assert "tmdb_id: Number(tmdbId) > 0 ? Number(tmdbId) : null" in api_js
    assert "result.tmdb_id || null" in series_js
    assert "current.tmdb_id || null" in movies_js
