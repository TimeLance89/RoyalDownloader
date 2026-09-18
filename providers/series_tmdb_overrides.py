"""Explicit TMDB-to-provider overrides for exceptional series layouts.

Keep this registry deliberately tiny. These are cases where TMDB models each
story as its own TV series while the configured provider exposes the same
stories as seasons of one anthology.
"""

from __future__ import annotations

from dataclasses import dataclass

from providers.models import FilmpalastSeries


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



def apply_tmdb_season_override(
    series: FilmpalastSeries,
    override: TmdbSeriesSeasonOverride,
    *,
    title: str = "",
    cover_url: str = "",
    description: str = "",
    genres: list[str] | None = None,
) -> FilmpalastSeries | None:
    episodes = list((series.seasons or {}).get(override.season) or [])
    if not episodes:
        return None
    return FilmpalastSeries(
        title=str(title or override.fallback_title),
        base_slug=override.virtual_base_slug,
        url=override.source_url,
        cover_url=str(cover_url or series.cover_url or ""),
        description=str(description or series.description or ""),
        genres=list(genres or series.genres or []),
        seasons={override.season: episodes},
    )
