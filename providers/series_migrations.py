"""Provider series source migrations for renamed or merged catalog entries.

A provider can rename a series slug or merge previously separate shows into a
single canonical series.  Persisted watchlist/queue entries must keep working
across those changes, including episode slugs whose season number changed as
part of the merge.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit, urlunsplit


_EPISODE_RE = re.compile(
    r"^(?P<base>.+)-s(?P<season>\d{1,2})e(?P<episode>\d{1,3})$",
    re.IGNORECASE,
)
_SERIES_PATH_RE = re.compile(
    r"^/serie/(?:stream/)?(?P<slug>[^/?#]+)"
    r"(?P<tail>/staffel-(?P<season>\d+)(?:/episode-(?P<episode>\d+))?)?/?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SeriesSourceMigration:
    provider: str
    legacy_slug: str
    canonical_slug: str
    canonical_season: int | None = None
    legacy_title: str = ""


# Registry intentionally uses explicit historical identities.  More provider
# migrations can be added here without teaching queue/watchlist code about a
# particular site or title.
SERIES_SOURCE_MIGRATIONS: tuple[SeriesSourceMigration, ...] = (
    SeriesSourceMigration(
        provider="serienstream",
        legacy_slug="dahmer-monster-die-geschichte-von-jeffrey-dahmer",
        canonical_slug="monster-2022",
        canonical_season=1,
        legacy_title="Dahmer – Monster: Die Geschichte von Jeffrey Dahmer",
    ),
    SeriesSourceMigration(
        provider="serienstream",
        legacy_slug="monster-die-geschichte-von-lyle-und-erik-menendez",
        canonical_slug="monster-2022",
        canonical_season=2,
        legacy_title="Monster: Die Geschichte von Lyle und Erik Menendez",
    ),
    SeriesSourceMigration(
        provider="serienstream",
        legacy_slug="monster-die-geschichte-von-ed-gein",
        canonical_slug="monster-2022",
        canonical_season=3,
        legacy_title="Monster: Die Geschichte von Ed Gein",
    ),
)

_MIGRATIONS_BY_KEY = {
    (migration.provider.casefold(), migration.legacy_slug.casefold()): migration
    for migration in SERIES_SOURCE_MIGRATIONS
}
_PROVIDER_PREFIXES = {
    "serienstream": "serienstream:",
}
_PROVIDER_HOSTS = {
    "serienstream": {"serienstream.to", "www.serienstream.to", "s.to", "www.s.to"},
}


def migration_for(provider: str, slug: str) -> SeriesSourceMigration | None:
    return _MIGRATIONS_BY_KEY.get(
        (str(provider or "").strip().casefold(), str(slug or "").strip().casefold())
    )


def canonical_provider_series_slug(provider: str, slug: str) -> str:
    """Return the current provider root slug for a historical series slug."""
    migration = migration_for(provider, slug)
    return migration.canonical_slug if migration else str(slug or "").strip()


def _canonical_episode(provider: str, base: str, season: int, episode: int) -> tuple[str, int, int]:
    migration = migration_for(provider, base)
    if migration is None:
        return base, season, episode
    # The known split->anthology migrations came from standalone shows whose
    # only season was S01.  Preserve unexpected legacy season numbers rather
    # than guessing an offset for data we have never observed.
    target_season = (
        migration.canonical_season
        if migration.canonical_season is not None and season == 1
        else season
    )
    return migration.canonical_slug, target_season, episode


def canonical_series_source(value: str) -> str:
    """Canonicalize persisted provider roots, episode slugs and provider URLs."""
    raw = str(value or "").strip()
    if not raw:
        return raw

    for provider, prefix in _PROVIDER_PREFIXES.items():
        if not raw.casefold().startswith(prefix.casefold()):
            continue
        rest = raw[len(prefix):]
        episode_match = _EPISODE_RE.match(rest)
        if episode_match:
            base, season, episode = _canonical_episode(
                provider,
                episode_match.group("base"),
                int(episode_match.group("season")),
                int(episode_match.group("episode")),
            )
            return f"{prefix}{base}-s{season:02d}e{episode:02d}"
        return f"{prefix}{canonical_provider_series_slug(provider, rest)}"

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    host = (parsed.hostname or "").casefold()
    provider = next(
        (name for name, hosts in _PROVIDER_HOSTS.items() if host in hosts),
        "",
    )
    if not provider:
        return raw
    match = _SERIES_PATH_RE.match(parsed.path or "")
    if not match:
        return raw

    slug = match.group("slug")
    migration = migration_for(provider, slug)
    if migration is None:
        return raw

    season_text = match.group("season")
    episode_text = match.group("episode")
    new_path = f"/serie/{migration.canonical_slug}"
    if season_text is not None:
        season = int(season_text)
        if migration.canonical_season is not None and season == 1:
            season = migration.canonical_season
        new_path += f"/staffel-{season}"
        if episode_text is not None:
            new_path += f"/episode-{int(episode_text)}"
    return urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))


def equivalent_series_sources(left: str, right: str) -> bool:
    """Compare provider series identities after applying known migrations."""
    return canonical_series_source(left).casefold() == canonical_series_source(right).casefold()
