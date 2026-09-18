"""Explicit TMDB-to-provider overrides for exceptional series layouts.

Keep this registry deliberately tiny. These are cases where TMDB models each
story as its own TV series while the configured provider exposes the same
stories as seasons of one anthology.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from providers.models import FilmpalastSeries, parse_episode_slug


@dataclass(frozen=True)
class TmdbSeriesSeasonOverride:
    tmdb_id: int
    fallback_title: str
    provider: str
    source_slug: str
    season: int

    @property
    def virtual_base_slug(self) -> str:
        return f"tmdb-series:{self.tmdb_id}"

    @property
    def source_url(self) -> str:
        return (
            f"https://serienstream.to/serie/{self.source_slug}"
            f"/staffel-{self.season}"
        )

    @property
    def provider_source(self) -> str:
        return f"{self.provider}:{self.source_slug}"


# Intentional one-off mapping requested for the Netflix Monster anthology.
# Do not infer more mappings by title or year.
MONSTER_TMDB_SEASON_OVERRIDES: tuple[TmdbSeriesSeasonOverride, ...] = (
    TmdbSeriesSeasonOverride(
        tmdb_id=113988,
        fallback_title="Dahmer – Monster: The Jeffrey Dahmer Story",
        provider="serienstream",
        source_slug="monster-2022",
        season=1,
    ),
    TmdbSeriesSeasonOverride(
        tmdb_id=225634,
        fallback_title="Monsters: The Lyle and Erik Menendez Story",
        provider="serienstream",
        source_slug="monster-2022",
        season=2,
    ),
    TmdbSeriesSeasonOverride(
        tmdb_id=286801,
        fallback_title="Monster: The Ed Gein Story",
        provider="serienstream",
        source_slug="monster-2022",
        season=3,
    ),
    TmdbSeriesSeasonOverride(
        tmdb_id=299939,
        fallback_title="Monster: The Lizzie Borden Story",
        provider="serienstream",
        source_slug="monster-2022",
        season=4,
    ),
)

_BY_TMDB_ID = {
    override.tmdb_id: override
    for override in MONSTER_TMDB_SEASON_OVERRIDES
}
_BY_VIRTUAL_SLUG = {
    override.virtual_base_slug.casefold(): override
    for override in MONSTER_TMDB_SEASON_OVERRIDES
}


def tmdb_series_season_override(tmdb_id) -> TmdbSeriesSeasonOverride | None:
    try:
        key = int(tmdb_id)
    except (TypeError, ValueError):
        return None
    return _BY_TMDB_ID.get(key)


def tmdb_series_override_for_value(value: str) -> TmdbSeriesSeasonOverride | None:
    return _BY_VIRTUAL_SLUG.get(str(value or "").strip().casefold())


def tmdb_series_override_for_episode_slug(
    value: str,
) -> TmdbSeriesSeasonOverride | None:
    parsed = parse_episode_slug(str(value or ""))
    if parsed is None:
        return None
    base_slug, logical_season, _episode = parsed
    if int(logical_season) != 1:
        return None
    return tmdb_series_override_for_value(base_slug)


def source_episode_slug(value: str) -> str:
    """Translate a virtual Monster episode back to its exact S.to source."""
    parsed = parse_episode_slug(str(value or ""))
    override = tmdb_series_override_for_episode_slug(value)
    if parsed is None or override is None:
        return str(value or "")
    _base_slug, _logical_season, episode = parsed
    return (
        f"{override.provider}:{override.source_slug}"
        f"-s{override.season:02d}e{int(episode):02d}"
    )


def logical_episode_identity(value: str) -> tuple[int, int] | None:
    parsed = parse_episode_slug(str(value or ""))
    if parsed is None:
        return None
    _base_slug, season, episode = parsed
    return int(season), int(episode)


def apply_tmdb_season_override(
    series: FilmpalastSeries,
    override: TmdbSeriesSeasonOverride,
    *,
    title: str = "",
    cover_url: str = "",
    description: str = "",
    genres: list[str] | None = None,
) -> FilmpalastSeries | None:
    source_episodes = list(
        (series.seasons or {}).get(
            1 if series.base_slug == override.virtual_base_slug else override.season
        )
        or []
    )
    if not source_episodes:
        return None
    # TMDB führt jede Geschichte als eigenständige Serie mit Staffel 1. Die
    # technische S.to-Staffel bleibt ausschließlich im Slug/URL erhalten, damit
    # der Provider weiterhin die richtige Quelle abruft.
    logical_episodes = [
        replace(
            episode,
            season=1,
            slug=(
                f"{override.virtual_base_slug}"
                f"-s01e{int(episode.episode):02d}"
            ),
        )
        for episode in source_episodes
    ]
    return FilmpalastSeries(
        title=str(title or override.fallback_title),
        base_slug=override.virtual_base_slug,
        url=override.source_url,
        cover_url=str(cover_url or series.cover_url or ""),
        description=str(description or series.description or ""),
        genres=list(genres or series.genres or []),
        seasons={1: logical_episodes},
    )
