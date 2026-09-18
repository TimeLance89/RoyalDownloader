"""Explicit Monster anthology bridge between TMDB and SerienStream.

This module is intentionally isolated and ID-driven. It must never infer or
rewrite unrelated series/provider identities.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MonsterTmdbSeries:
    tmdb_id: int
    source_season: int
    fallback_title: str
    year: str
    tmdb_slug: str

    @property
    def virtual_base_slug(self) -> str:
        return f"monster-tmdb:{self.tmdb_id}"

    @property
    def tmdb_url(self) -> str:
        return f"https://www.themoviedb.org/tv/{self.tmdb_id}-{self.tmdb_slug}"

    @property
    def source_url(self) -> str:
        return (
            "https://serienstream.to/serie/monster-2022/"
            f"staffel-{self.source_season}"
        )


MONSTER_TMDB_SERIES: tuple[MonsterTmdbSeries, ...] = (
    MonsterTmdbSeries(
        113988,
        1,
        "Dahmer – Monster: The Jeffrey Dahmer Story",
        "2022",
        "dahmer-monster-the-jeffrey-dahmer-story",
    ),
    MonsterTmdbSeries(
        225634,
        2,
        "Monsters: The Lyle and Erik Menendez Story",
        "2024",
        "monsters-the-lyle-and-erik-menendez-story",
    ),
    MonsterTmdbSeries(
        286801,
        3,
        "Monster: The Ed Gein Story",
        "2025",
        "monster-the-ed-gein-story",
    ),
    MonsterTmdbSeries(
        299939,
        4,
        "Monster: The Lizzie Borden Story",
        "2026",
        "monster-the-lizzie-borden-story",
    ),
)

_BY_TMDB_ID = {item.tmdb_id: item for item in MONSTER_TMDB_SERIES}
_VIRTUAL_EPISODE_RE = re.compile(
    r"^monster-tmdb:(?P<tmdb_id>\d+)-s01e(?P<episode>\d{1,3})$",
    re.IGNORECASE,
)


def monster_tmdb_series(tmdb_id) -> MonsterTmdbSeries | None:
    try:
        return _BY_TMDB_ID.get(int(tmdb_id))
    except (TypeError, ValueError):
        return None


def is_monster_search(query: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(query or "").casefold())
    return normalized == "monster"


def monster_search_payloads() -> list[dict]:
    return [
        {
            "title": item.fallback_title,
            "year": item.year,
            "base_slug": item.virtual_base_slug,
            "sample_slug": item.virtual_base_slug,
            "sample_url": item.tmdb_url,
            "cover_url": "",
            "provider": "tmdb",
            "provider_label": "TMDB",
            "content_language": "",
            "language_label": "TMDB",
            "sources": [{"key": "tmdb", "label": "TMDB", "content_language": ""}],
            "tmdb_id": item.tmdb_id,
            "special_series": "monster_tmdb",
        }
        for item in MONSTER_TMDB_SERIES
    ]


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def is_replaced_monster_provider_result(payload: dict) -> bool:
    """Hide only provider cards represented by the four explicit TMDB cards."""
    source = str(
        payload.get("base_slug")
        or payload.get("sample_slug")
        or payload.get("sample_url")
        or ""
    ).casefold()
    if "serienstream:monster-2022" in source or "/serie/monster-2022" in source:
        return True

    title = _normalized_title(payload.get("title", ""))
    signatures = (
        ("dahmer",),
        ("jeffreydahmer",),
        ("lyle", "erik", "menendez"),
        ("edgein",),
        ("lizzieborden",),
    )
    return any(all(part in title for part in signature) for signature in signatures)


def inject_monster_search_results(query: str, results: list[dict]) -> list[dict]:
    if not is_monster_search(query):
        return results
    remaining = [
        item for item in results
        if not is_replaced_monster_provider_result(item)
    ]
    return [*monster_search_payloads(), *remaining]


def parse_monster_virtual_episode(slug: str) -> tuple[MonsterTmdbSeries, int] | None:
    match = _VIRTUAL_EPISODE_RE.fullmatch(str(slug or "").strip())
    if not match:
        return None
    item = monster_tmdb_series(match.group("tmdb_id"))
    if item is None:
        return None
    return item, int(match.group("episode"))


def monster_source_episode_slug(slug: str) -> str | None:
    parsed = parse_monster_virtual_episode(slug)
    if parsed is None:
        return None
    item, episode = parsed
    return (
        "serienstream:monster-2022"
        f"-s{item.source_season:02d}e{episode:02d}"
    )
