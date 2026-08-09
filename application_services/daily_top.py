"""Server-side popularity signals for the Royal Daily Top 10 v2."""

from __future__ import annotations

import math
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from starlette.concurrency import run_in_threadpool

from application_services.runtime import backend_value
from api_discovery_router import router as discovery_router


DAILY_TOP_PROVIDER_LIMIT = 30
DAILY_TOP_TMDB_LIMIT = 40
DAILY_TOP_ENRICH_LIMIT_PER_KIND = 18
DAILY_TOP_RESULT_LIMIT = 30
DAILY_TOP_CACHE_TTL = 2 * 60 * 60
DAILY_TOP_MAX_SAME_KIND = 7

_cache_lock = threading.RLock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

_TITLE_QUALIFIER_RE = re.compile(
    r"\s*(?:\[[^\]]{1,40}\]|\*(?:subbed|dubbed|ger(?:man)?(?:\s+dub)?|eng(?:lish)?)\*)\s*$",
    re.IGNORECASE,
)


def _display_title(value: str) -> str:
    title = str(value or "").strip()
    previous = None
    while title and title != previous:
        previous = title
        title = _TITLE_QUALIFIER_RE.sub("", title).strip()
    return title


def _normalise_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", _display_title(value))
    ascii_text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return "".join(char for char in ascii_text if char.isalnum())


def _clean_year(value: Any) -> str:
    text = str(value or "").strip()
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _rank_signal(rank: int, slope: float = 0.18) -> float:
    rank = max(1, int(rank or 1))
    return 100.0 / (1.0 + slope * (rank - 1))


def _provider_momentum(provider_ranks: dict[str, int]) -> float:
    values = sorted((_rank_signal(rank) for rank in provider_ranks.values()), reverse=True)
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return min(100.0, values[0] * 0.75 + values[1] * 0.25)


def _provider_consensus(provider_ranks: dict[str, int]) -> float:
    values = sorted((_rank_signal(rank) for rank in provider_ranks.values()), reverse=True)
    if len(values) < 2:
        return 0.0
    supporting = sum(values[1:]) / len(values[1:])
    return min(100.0, (len(values) - 1) * 28.0 + supporting * 0.45)


def _tmdb_trend_score(rank: int | None, popularity: float = 0.0) -> float:
    if not rank:
        return 0.0
    rank_component = _rank_signal(rank, slope=0.12)
    popularity_component = min(
        100.0,
        max(0.0, math.log10(max(0.0, popularity) + 1.0) * 30.0),
    )
    return min(100.0, rank_component * 0.82 + popularity_component * 0.18)


def _rating_confidence_score(rating: float, votes: int) -> float:
    rating = min(10.0, max(0.0, float(rating or 0.0)))
    votes = max(0, int(votes or 0))
    if rating <= 0 or votes <= 0:
        return 0.0
    confidence = min(1.0, math.log10(votes + 1.0) / 4.5)
    return (rating / 10.0) * 100.0 * confidence


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _freshness_score(
    release_date: str,
    year: str,
    *,
    kind: str,
    is_trending: bool,
    today: date | None = None,
) -> float:
    today = today or date.today()
    released = _parse_date(release_date)
    if released is not None:
        age = (today - released).days
        if age < -45:
            score = 0.0
        elif age < 0:
            score = max(35.0, 70.0 - abs(age) * 0.8)
        elif age <= 14:
            score = 100.0
        elif age <= 30:
            score = 85.0
        elif age <= 90:
            score = 60.0
        elif age <= 180:
            score = 35.0
        elif age <= 365:
            score = 15.0
        else:
            score = 4.0
    else:
        numeric_year = int(year) if str(year or "").isdigit() else 0
        delta = today.year - numeric_year if numeric_year else 99
        score = 55.0 if delta <= 0 else 30.0 if delta == 1 else 8.0 if delta == 2 else 0.0
    # An older series can genuinely trend because a current season is hot even
    # though first_air_date is years old. Do not punish that signal twice.
    if kind == "series" and is_trending:
        score = max(score, 55.0)
    return min(100.0, max(0.0, score))


def _score_candidate(candidate: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    provider_score = _provider_momentum(candidate.get("provider_ranks") or {})
    consensus_score = _provider_consensus(candidate.get("provider_ranks") or {})
    tmdb_score = _tmdb_trend_score(
        candidate.get("tmdb_trend_rank"),
        float(candidate.get("tmdb_popularity") or 0.0),
    )
    rating_score = _rating_confidence_score(
        float(candidate.get("rating") or 0.0),
        int(candidate.get("vote_count") or 0),
    )
    freshness_score = _freshness_score(
        str(candidate.get("release_date") or candidate.get("first_air_date") or ""),
        str(candidate.get("year") or ""),
        kind=str(candidate.get("kind") or "movie"),
        is_trending=bool(candidate.get("tmdb_trend_rank")),
        today=today,
    )
    total = (
        provider_score * 0.45
        + consensus_score * 0.20
        + tmdb_score * 0.15
        + rating_score * 0.10
        + freshness_score * 0.10
    )
    candidate = dict(candidate)
    candidate["score"] = round(total, 3)
    candidate["components"] = {
        "provider_momentum": round(provider_score, 2),
        "provider_consensus": round(consensus_score, 2),
        "tmdb_trending": round(tmdb_score, 2),
        "rating_confidence": round(rating_score, 2),
        "freshness": round(freshness_score, 2),
    }
    return candidate


def _row_payload(item: Any, provider: str, kind: str) -> dict[str, Any]:
    raw = asdict(item) if is_dataclass(item) else dict(item) if isinstance(item, dict) else {}
    if kind == "movie":
        return {
            "title": _display_title(raw.get("title") or getattr(item, "title", "")),
            "year": _clean_year(raw.get("year") or getattr(item, "year", "")),
            "slug": str(raw.get("slug") or getattr(item, "slug", "") or ""),
            "url": str(raw.get("url") or getattr(item, "url", "") or ""),
            "cover_url": str(raw.get("cover_url") or getattr(item, "cover_url", "") or ""),
            "provider": provider,
            "content_language": str(
                raw.get("content_language") or getattr(item, "content_language", "") or ""
            ),
        }
    return {
        "title": _display_title(raw.get("title") or getattr(item, "title", "")),
        "year": _clean_year(raw.get("year") or getattr(item, "year", "")),
        "base_slug": str(raw.get("base_slug") or getattr(item, "base_slug", "") or ""),
        "sample_slug": str(raw.get("sample_slug") or getattr(item, "sample_slug", "") or ""),
        "sample_url": str(raw.get("sample_url") or getattr(item, "sample_url", "") or ""),
        "cover_url": str(raw.get("cover_url") or getattr(item, "cover_url", "") or ""),
        "provider": provider,
        "content_language": str(
            raw.get("content_language") or getattr(item, "content_language", "") or ""
        ),
    }


def _candidate_identity(kind: str, title: str, year: str, tmdb_id: Any = None) -> str:
    tmdb_text = str(tmdb_id or "").strip()
    if tmdb_text.isdigit():
        return f"{kind}:tmdb:{int(tmdb_text)}"
    return f"{kind}:title:{_normalise_title(title)}:{_clean_year(year)}"


def _provider_group_key(kind: str, item: dict[str, Any]) -> tuple[str, str, str]:
    return kind, _normalise_title(item.get("title") or ""), _clean_year(item.get("year"))


def _add_provider_rows(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    *,
    kind: str,
    provider: str,
    rows: list[Any],
    ranked: bool,
) -> None:
    for index, row in enumerate(rows[:DAILY_TOP_PROVIDER_LIMIT], start=1):
        item = _row_payload(row, provider, kind)
        if not item["title"]:
            continue
        key = _provider_group_key(kind, item)
        candidate = grouped.setdefault(
            key,
            {
                "kind": kind,
                "title": item["title"],
                "year": item.get("year", ""),
                "item": item,
                "provider_ranks": {},
                "availability_providers": [],
            },
        )
        if provider not in candidate["availability_providers"]:
            candidate["availability_providers"].append(provider)
        if ranked:
            candidate["provider_ranks"][provider] = min(
                index,
                int(candidate["provider_ranks"].get(provider) or index),
            )


def _tmdb_rows(client: Any, media_type: str) -> list[dict[str, Any]]:
    if client is None or not getattr(client, "configured", False):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in (1, 2):
        data = client._request(  # noqa: SLF001 - same application boundary
            f"/trending/{media_type}/day",
            {"language": client.language, "page": str(page)},
        ) or {}
        for raw in data.get("results") or []:
            try:
                tmdb_id = int(raw.get("id"))
            except (TypeError, ValueError):
                continue
            if tmdb_id in seen:
                continue
            seen.add(tmdb_id)
            is_movie = media_type == "movie"
            release_date = str(
                (raw.get("release_date") if is_movie else raw.get("first_air_date")) or ""
            )
            rows.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": str(
                        (raw.get("title") if is_movie else raw.get("name")) or ""
                    ).strip(),
                    "original_title": str(
                        (raw.get("original_title") if is_movie else raw.get("original_name")) or ""
                    ).strip(),
                    "year": _clean_year(release_date),
                    "release_date": release_date,
                    "rating": round(float(raw.get("vote_average") or 0.0), 1),
                    "vote_count": int(raw.get("vote_count") or 0),
                    "popularity": float(raw.get("popularity") or 0.0),
                    "cover_url": client._poster_url(  # noqa: SLF001
                        str(raw.get("poster_path") or "")
                    ),
                    "backdrop_url": client._backdrop_url(  # noqa: SLF001
                        str(raw.get("backdrop_path") or "")
                    ),
                    "description": str(raw.get("overview") or ""),
                }
            )
            if len(rows) >= DAILY_TOP_TMDB_LIMIT:
                return rows
    return rows


def _match_tmdb(
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[int | None, dict[str, Any] | None]:
    wanted = _normalise_title(candidate.get("title") or "")
    year = _clean_year(candidate.get("year"))
    best: tuple[tuple[int, int], int, dict[str, Any]] | None = None
    for index, row in enumerate(rows, start=1):
        names = {
            _normalise_title(row.get("title") or ""),
            _normalise_title(row.get("original_title") or ""),
        }
        if wanted not in names:
            continue
        row_year = _clean_year(row.get("year"))
        year_match = bool(year and row_year and year == row_year)
        if year and row_year and not year_match:
            continue
        quality = (1 if year_match else 0, -index)
        if best is None or quality > best[0]:
            best = (quality, index, row)
    return (best[1], best[2]) if best else (None, None)


def _merge_metadata(candidate: dict[str, Any], metadata: dict[str, Any] | None) -> None:
    if not metadata:
        return
    for key in (
        "tmdb_id",
        "year",
        "release_date",
        "first_air_date",
        "rating",
        "vote_count",
        "cover_url",
        "backdrop_url",
        "description",
        "genres",
        "original_title",
    ):
        value = metadata.get(key)
        if value not in (None, "", [], 0, 0.0):
            candidate[key] = value
            if key in {
                "cover_url",
                "backdrop_url",
                "description",
                "genres",
                "rating",
                "vote_count",
                "tmdb_id",
                "year",
            }:
                candidate["item"][key] = value


def _enrich_candidates(candidates: list[dict[str, Any]], client: Any) -> None:
    if client is None or not getattr(client, "configured", False):
        return
    by_kind = {
        "movie": [candidate for candidate in candidates if candidate["kind"] == "movie"],
        "series": [candidate for candidate in candidates if candidate["kind"] == "series"],
    }
    targets: list[dict[str, Any]] = []
    for values in by_kind.values():
        values.sort(
            key=lambda candidate: (
                _provider_momentum(candidate.get("provider_ranks") or {})
                + _provider_consensus(candidate.get("provider_ranks") or {}) * 0.45
                + _tmdb_trend_score(
                    candidate.get("tmdb_trend_rank"),
                    candidate.get("tmdb_popularity") or 0.0,
                )
                * 0.55
            ),
            reverse=True,
        )
        targets.extend(values[:DAILY_TOP_ENRICH_LIMIT_PER_KIND])

    def load(candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        title = str(candidate.get("title") or "")
        year = str(candidate.get("year") or "")
        if candidate["kind"] == "movie":
            return candidate, client.movie_summary(title, year)
        return candidate, client.series_summary(title, year)

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as pool:
        for candidate, metadata in pool.map(load, targets):
            _merge_metadata(candidate, metadata)


def _merge_title_year_fallbacks(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge yearless provider rows only when one year is unambiguous."""
    by_title: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        key = (candidate["kind"], _normalise_title(candidate.get("title") or ""))
        by_title.setdefault(key, []).append(candidate)

    result: list[dict[str, Any]] = []
    for values in by_title.values():
        known_years = {
            _clean_year(candidate.get("year"))
            for candidate in values
            if _clean_year(candidate.get("year"))
        }
        if len(known_years) != 1:
            result.extend(values)
            continue
        wanted_year = next(iter(known_years))
        target = next(
            (
                candidate
                for candidate in values
                if _clean_year(candidate.get("year")) == wanted_year
            ),
            None,
        )
        if target is None:
            result.extend(values)
            continue
        for candidate in values:
            if candidate is target:
                continue
            if _clean_year(candidate.get("year")):
                result.append(candidate)
                continue
            for provider, rank in (candidate.get("provider_ranks") or {}).items():
                current = target["provider_ranks"].get(provider)
                target["provider_ranks"][provider] = (
                    rank if current is None else min(current, rank)
                )
            for provider in candidate.get("availability_providers") or []:
                if provider not in target["availability_providers"]:
                    target["availability_providers"].append(provider)
        result.append(target)
    return result


def _merge_candidates_by_identity(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        identity = _candidate_identity(
            candidate["kind"],
            candidate.get("title") or "",
            candidate.get("year") or "",
            candidate.get("tmdb_id"),
        )
        existing = merged.get(identity)
        if existing is None:
            candidate["identity"] = identity
            merged[identity] = candidate
            continue
        for provider, rank in (candidate.get("provider_ranks") or {}).items():
            current = existing["provider_ranks"].get(provider)
            existing["provider_ranks"][provider] = rank if current is None else min(current, rank)
        for provider in candidate.get("availability_providers") or []:
            if provider not in existing["availability_providers"]:
                existing["availability_providers"].append(provider)
        if candidate.get("tmdb_trend_rank") and (
            not existing.get("tmdb_trend_rank")
            or candidate["tmdb_trend_rank"] < existing["tmdb_trend_rank"]
        ):
            existing["tmdb_trend_rank"] = candidate["tmdb_trend_rank"]
            existing["tmdb_popularity"] = candidate.get("tmdb_popularity", 0.0)
        _merge_metadata(existing, candidate)
    return list(merged.values())


def _presentable_candidate(candidate: dict[str, Any]) -> bool:
    item = candidate.get("item") or {}
    title = _display_title(candidate.get("title") or item.get("title") or "")
    artwork = str(
        candidate.get("cover_url")
        or candidate.get("backdrop_url")
        or item.get("cover_url")
        or item.get("backdrop_url")
        or ""
    ).strip()
    if len(title) < 2 or not artwork:
        return False
    candidate["title"] = title
    item["title"] = title
    return True


def _apply_diversity(
    candidates: list[dict[str, Any]],
    limit: int = DAILY_TOP_RESULT_LIMIT,
) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (-float(candidate.get("score") or 0.0), candidate["identity"]),
    )
    if limit <= 0:
        return []
    preview = ordered[:10]
    if not preview:
        return []
    counts = {
        kind: sum(1 for candidate in preview if candidate["kind"] == kind)
        for kind in ("movie", "series")
    }
    relevance_floor = max(22.0, float(preview[0].get("score") or 0.0) * 0.34)
    enough_other = {
        kind: sum(
            1
            for candidate in ordered
            if candidate["kind"] == kind
            and float(candidate.get("score") or 0.0) >= relevance_floor
        )
        >= 3
        for kind in ("movie", "series")
    }
    dominant = (
        "movie"
        if counts["movie"] > DAILY_TOP_MAX_SAME_KIND
        else "series"
        if counts["series"] > DAILY_TOP_MAX_SAME_KIND
        else ""
    )
    other = "series" if dominant == "movie" else "movie"
    if dominant and enough_other[other]:
        selected: list[dict[str, Any]] = []
        dominant_count = 0
        for candidate in ordered:
            if len(selected) >= 10:
                break
            if candidate["kind"] == dominant and dominant_count >= DAILY_TOP_MAX_SAME_KIND:
                continue
            selected.append(candidate)
            if candidate["kind"] == dominant:
                dominant_count += 1
        selected_ids = {candidate["identity"] for candidate in selected}
        ordered = selected + [
            candidate for candidate in ordered if candidate["identity"] not in selected_ids
        ]
    for index, candidate in enumerate(ordered, start=1):
        candidate["global_rank"] = index
    return ordered[:limit]


def _build_daily_top(period: str) -> dict[str, Any]:
    provider_priority = backend_value("provider_priority")
    load_movie_pages = backend_value("_load_movie_provider_pages")
    load_series_pages = backend_value("_load_series_provider_pages")
    tmdb_client = backend_value("get_tmdb_client")()

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    movie_providers = list(provider_priority("movies"))
    if movie_providers:
        loaded = load_movie_pages(
            "top",
            "",
            [(provider, 1) for provider in movie_providers],
            None,
        )
        for provider in movie_providers:
            _add_provider_rows(
                grouped,
                kind="movie",
                provider=provider,
                rows=list(loaded.get((provider, 1), [])),
                ranked=True,
            )

    series_providers = list(provider_priority("series"))
    seriesstream_active = "serienstream" in series_providers
    seriesstream_rows: list[Any] = []
    if seriesstream_active:
        loaded = load_series_pages("trending", "", [("serienstream", 1)], None)
        seriesstream_rows = list(loaded.get(("serienstream", 1), []))
        _add_provider_rows(
            grouped,
            kind="series",
            provider="serienstream",
            rows=seriesstream_rows,
            ranked=True,
        )

    # If the only true provider trend signal is unavailable, use other active
    # series catalogs solely as an availability pool. They receive no provider
    # popularity points; TMDB trending still has to prove relevance.
    if not seriesstream_rows:
        fallback = [provider for provider in series_providers if provider != "serienstream"]
        if fallback:
            loaded = load_series_pages(
                "discover",
                "",
                [(provider, 1) for provider in fallback],
                None,
            )
            for provider in fallback:
                _add_provider_rows(
                    grouped,
                    kind="series",
                    provider=provider,
                    rows=list(loaded.get((provider, 1), []))[:12],
                    ranked=False,
                )

    candidates = _merge_title_year_fallbacks(list(grouped.values()))
    movie_trending = _tmdb_rows(tmdb_client, "movie")
    series_trending = _tmdb_rows(tmdb_client, "tv")
    for candidate in candidates:
        rows = movie_trending if candidate["kind"] == "movie" else series_trending
        rank, tmdb = _match_tmdb(candidate, rows)
        if tmdb:
            candidate["tmdb_trend_rank"] = rank
            candidate["tmdb_popularity"] = float(tmdb.get("popularity") or 0.0)
            _merge_metadata(candidate, tmdb)

    _enrich_candidates(candidates, tmdb_client)
    candidates = _merge_candidates_by_identity(candidates)
    candidates = [candidate for candidate in candidates if _presentable_candidate(candidate)]
    try:
        scoring_day = datetime.strptime(period, "%Y-%m-%d").date()
    except ValueError:
        scoring_day = date.today()
    scored = [_score_candidate(candidate, scoring_day) for candidate in candidates]
    ranked = _apply_diversity(scored)
    return {
        "version": 2,
        "period": period,
        "generated_at": int(time.time()),
        "weights": {
            "provider_momentum": 0.45,
            "provider_consensus": 0.20,
            "tmdb_trending": 0.15,
            "rating_confidence": 0.10,
            "freshness": 0.10,
        },
        "source_status": {
            "movie_providers": movie_providers,
            "series_trending_provider": "serienstream" if seriesstream_rows else None,
            "tmdb": bool(getattr(tmdb_client, "configured", False)),
        },
        "candidates": [
            {
                "identity": candidate["identity"],
                "kind": candidate["kind"],
                "item": candidate["item"],
                "global_rank": candidate["global_rank"],
                "score": candidate["score"],
                "components": candidate["components"],
                "provider_ranks": candidate.get("provider_ranks") or {},
                "availability_providers": candidate.get("availability_providers") or [],
                "tmdb_trend_rank": candidate.get("tmdb_trend_rank"),
            }
            for candidate in ranked
        ],
    }


def daily_top_payload(period: str = "") -> dict[str, Any]:
    period = str(period or "").strip()
    try:
        period = datetime.strptime(period, "%Y-%m-%d").date().isoformat()
    except ValueError:
        period = date.today().isoformat()
    now = time.time()
    with _cache_lock:
        cached = _cache.get(period)
        if cached and now - cached[0] < DAILY_TOP_CACHE_TTL:
            return cached[1]
        payload = _build_daily_top(period)
        _cache[period] = (now, payload)
        if len(_cache) > 3:
            oldest = min(_cache, key=lambda key: _cache[key][0])
            _cache.pop(oldest, None)
        return payload


async def api_daily_top(period: str = "") -> dict[str, Any]:
    return await run_in_threadpool(daily_top_payload, period)


# The discovery router object already exists before runtime post-services are
# imported. Attach this isolated route here so no legacy router contract or
# composition-root wiring needs to be rewritten.
_existing_paths = {getattr(route, "path", "") for route in discovery_router.routes}
if "/api/daily-top" not in _existing_paths:
    discovery_router.add_api_route("/api/daily-top", api_daily_top, methods=["GET"])
if "/api/v1/daily-top" not in _existing_paths:
    discovery_router.add_api_route("/api/v1/daily-top", api_daily_top, methods=["GET"])
