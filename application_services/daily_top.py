"""Collect and score the signals used by Royal Charts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time as day_time, timezone

from fastapi import Query, Response
from starlette.concurrency import run_in_threadpool

from api.api_discovery_router import router as discovery_router
from application_services.chart_history import ALGORITHM, ChartHistory, chart_view
from application_services.runtime import backend_value
from core.config import config_path

logger = logging.getLogger(__name__)
PROVIDER_LIMIT = 30
TMDB_LIMIT = 40
ENRICH_LIMIT_PER_KIND = 16
WEIGHTS = {"popularity": 0.90, "quality": 0.10}
POPULARITY_STRENGTH = {
    "views_rank": 1.0, "trending_rank": 1.0,
    "popularity_rank": 0.80, "editorial_top": 0.55,
}
MOVIE_SIGNALS = {
    "megakino": "views_rank", "sflix": "trending_rank",
    "kinoking": "editorial_top", "filmpalast": "editorial_top",
    "ridomovies": "editorial_top", "huhu": "popularity_rank",
    "filmo": "rating_rank", "filmfrei24": "rating_rank", "xcine": "rating_rank",
    "kinoger": "recent_uploads", "kinox": "recent_uploads", "einschalten": "recent_uploads",
}
SERIES_SIGNALS = {
    "serienstream": "views_rank", "huhu": "popularity_rank",
    "filmpalast": "recent_uploads", "megakino": "recent_uploads",
    "ridomovies": "recent_uploads", "xcine": "recent_uploads",
}
_TITLE_QUALIFIER = re.compile(
    r"\s*(?:\[[^\]]{1,40}\]|\*(?:subbed|dubbed|ger(?:man)?(?:\s+dub)?|eng(?:lish)?)\*)\s*$",
    re.IGNORECASE,
)
_BUILD_LOCK = threading.Lock()
_BUILD_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="royal-charts")
_build = None


def chart_day() -> date:
    return datetime.now(timezone.utc).date()


def _display_title(value):
    title = str(value or "").strip()
    while _TITLE_QUALIFIER.search(title):
        title = _TITLE_QUALIFIER.sub("", title).strip()
    return title


def _normalise_title(value):
    text = unicodedata.normalize("NFKD", _display_title(value)).casefold()
    return "".join(char for char in text if char.isalnum())


def _clean_year(value):
    value = str(value or "").strip()[:4]
    return value if len(value) == 4 and value.isascii() and value.isdigit() else ""


def _id(value):
    value = str(value or "")
    return int(value) if len(value) <= 12 and value.isascii() and value.isdigit() and int(value) else None


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def rank_signal(rank):
    return 100.0 / (1.0 + 0.12 * (rank - 1))


def _rating_confidence_score(rating, votes):
    confidence = min(1.0, math.log10(max(0, votes) + 1.0) / 4.5)
    return min(10.0, max(0.0, rating)) * 10.0 * confidence


def _candidate_identity(kind, title, year, tmdb_id=None):
    if _id(tmdb_id):
        return f"{kind}:tmdb:{int(tmdb_id)}"
    return f"{kind}:title:{_normalise_title(title)}:{_clean_year(year)}"


def _provider_rows(grouped, kind, provider, rows, signal):
    ordered = []
    for rank, row in enumerate((rows or [])[:PROVIDER_LIMIT], 1):
        raw = asdict(row) if is_dataclass(row) else row
        if not isinstance(raw, dict):
            continue
        item = {key: raw[key] for key in (
            "slug", "url", "base_slug", "sample_slug", "sample_url",
            "cover_url", "content_language",
        ) if raw.get(key)}
        slug = item.get("slug") if kind == "movie" else item.get("base_slug")
        title = _display_title(raw.get("title"))
        name = _normalise_title(title)
        if not name or not slug:
            continue
        year = _clean_year(raw.get("year"))
        tmdb_id = _id(raw.get("tmdb_id"))
        if not tmdb_id and provider == "huhu":
            match = re.match(r"huhu(?:-movie)?:(\d+):", slug)
            tmdb_id = _id(match[1]) if match else None
        item.update(title=title, year=year, provider=provider)
        if tmdb_id:
            item["tmdb_id"] = tmdb_id
        alias = _candidate_identity(kind, title, year)
        locator = f"{kind}:source:{provider}:{slug}"
        identity = _candidate_identity(kind, title, year, tmdb_id) if tmdb_id else alias if year else locator
        # Keep exact title/year matches separate from explicit IDs until we know
        # whether the title/year is shared by multiple productions.
        candidate = grouped.setdefault(identity, {
            "kind": kind, "item": item, "identity": identity, "aliases": [],
            "availability_providers": [], "provider_signals": {},
        })
        if not candidate["item"].get("cover_url") and item.get("cover_url"):
            candidate["item"]["cover_url"] = item["cover_url"]
        candidate["aliases"].extend([locator, *([alias] if year else [])])
        if provider not in candidate["availability_providers"]:
            candidate["availability_providers"].append(provider)
        candidate["provider_signals"].setdefault(provider, {
            "rank": rank, "type": signal,
            "source": "tmdb" if provider == "huhu" else provider,
        })
        ordered.append((name, year))
    return tuple(dict.fromkeys(ordered))


def _tmdb_request(client, path, **params):
    try:
        result = client._request(path, {"language": client.language, **params})
        return result if isinstance(result, dict) else {}
    except Exception:
        logger.debug("Chart metadata unavailable for %s", path, exc_info=True)
        return {}


def _result_list(payload, key="results"):
    values = payload.get(key)
    return values if isinstance(values, list) else []


def _tmdb_row(raw, media_type):
    if not isinstance(raw, dict) or not _id(raw.get("id")):
        return None
    movie = media_type == "movie"
    release = raw.get("release_date" if movie else "first_air_date")
    return {
        "tmdb_id": _id(raw["id"]),
        "title": _display_title(raw.get("title" if movie else "name")),
        "original_title": _display_title(raw.get("original_title" if movie else "original_name")),
        "year": _clean_year(release),
        "rating": round(_number(raw.get("vote_average")), 1),
        "vote_count": int(_number(raw.get("vote_count"))),
        "poster_path": raw.get("poster_path"),
        "backdrop_path": raw.get("backdrop_path"),
        "genre_ids": raw.get("genre_ids"),
    }


def _tmdb_rows(client, media_type):
    rows = {}
    for page in (1, 2):
        data = _tmdb_request(client, f"/trending/{media_type}/day", page=str(page))
        results = _result_list(data)
        for index, raw in enumerate(results, 1):
            row = _tmdb_row(raw, media_type)
            rank = (page - 1) * 20 + index
            if row and rank <= TMDB_LIMIT:
                rows.setdefault(row["tmdb_id"], (rank, row))
        if not results:
            break
    return rows


def _match_tmdb(item, rows, *, allow_yearless=False):
    wanted_id = _id(item.get("tmdb_id"))
    if wanted_id:
        return next((row for row in rows if row["tmdb_id"] == wanted_id), None)
    # A yearless provider listing cannot rule out remakes outside the trend list.
    year = item.get("year")
    if not year and not allow_yearless:
        return None
    title = _normalise_title(item["title"])
    matches = {
        row["tmdb_id"]: row for row in rows
        if (not year or year == row["year"]) and title in {
            _normalise_title(row["title"]), _normalise_title(row["original_title"]),
        }
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _merge_metadata(item, row, client, genres):
    item["tmdb_id"] = row["tmdb_id"]
    for key in ("year", "rating", "vote_count", "original_title"):
        if row.get(key):
            item[key] = row[key]
    if row.get("poster_path"):
        item["cover_url"] = client._poster_url(row["poster_path"])
    if row.get("backdrop_path"):
        item["backdrop_url"] = client._backdrop_url(row["backdrop_path"])
    item["genres"] = [
        genres[str(key)] for key in row.get("genre_ids") or [] if str(key) in genres
    ]


def _merge_candidates(candidates):
    merged = {}
    alias_ids = {}
    for candidate in candidates:
        item = candidate["item"]
        if item.get("tmdb_id"):
            identity = _candidate_identity(candidate["kind"], "", "", item["tmdb_id"])
            for alias in candidate["aliases"]:
                alias_ids.setdefault(alias, set()).add(identity)
    for candidate in candidates:
        item = candidate["item"]
        if item.get("tmdb_id"):
            identity = _candidate_identity(candidate["kind"], "", "", item["tmdb_id"])
        else:
            matches = set().union(*(alias_ids.get(alias, set()) for alias in candidate["aliases"]))
            identity = next(iter(matches)) if len(matches) == 1 else candidate["identity"]
        candidate["identity"] = identity
        target = merged.setdefault(identity, candidate)
        if target is candidate:
            continue
        for provider, signal in candidate["provider_signals"].items():
            previous = target["provider_signals"].get(provider)
            if previous is None or signal["rank"] < previous["rank"]:
                target["provider_signals"][provider] = signal
        target["availability_providers"].extend(candidate["availability_providers"])
        target["aliases"].extend(candidate["aliases"])
        if candidate.get("tmdb_trend_rank"):
            target["tmdb_trend_rank"] = candidate["tmdb_trend_rank"]
        for key in ("tmdb_id", "year", "rating", "vote_count", "cover_url", "backdrop_url", "genres"):
            if not target["item"].get(key) and item.get(key):
                target["item"][key] = item[key]
    return list(merged.values())


def _score_candidate(candidate):
    item = candidate["item"]
    signals = candidate["provider_signals"]
    observations = {}
    for provider, signal in signals.items():
        strength = POPULARITY_STRENGTH.get(signal["type"])
        if strength is None:
            continue
        value = rank_signal(signal["rank"]) * strength
        source = signal["source"]
        if source not in observations or value > observations[source]["value"]:
            observations[source] = {"provider": provider, "rank": signal["rank"], "value": value}
    tmdb_rank = candidate.get("tmdb_trend_rank")
    if tmdb_rank:
        value = rank_signal(tmdb_rank)
        if value >= observations.get("tmdb", {}).get("value", 0):
            observations["tmdb"] = {"provider": "tmdb", "rank": tmdb_rank, "value": value}
    popularity = max((value["value"] for value in observations.values()), default=0.0)
    rating = _rating_confidence_score(item.get("rating", 0), item.get("vote_count", 0))
    rank_quality = max((
        rank_signal(signal["rank"]) * 0.55 for signal in signals.values()
        if signal["type"] == "rating_rank"
    ), default=0.0)
    quality = rating or rank_quality
    direct = {signal["source"] for signal in signals.values()
              if signal["type"] in {"views_rank", "trending_rank"}}
    if tmdb_rank:
        direct.add("tmdb")
    return {
        **candidate,
        "score": round(popularity * WEIGHTS["popularity"] + quality * WEIGHTS["quality"], 3),
        "components": {"popularity": round(popularity, 2), "quality": round(quality, 2)},
        "quality_source": "tmdb_votes" if rating else "rating_rank" if rank_quality else None,
        "confidence": "high" if len(direct) >= 2 else "medium" if direct else "limited",
        "popularity_observations": observations,
        "provider_ranks": {provider: signal["rank"] for provider, signal in signals.items()},
        "availability_providers": sorted(set(candidate["availability_providers"])),
        "aliases": sorted(set(candidate["aliases"])),
    }


def _apply_diversity(candidates, limit=30):
    ordered = sorted(candidates, key=lambda candidate: (-candidate["score"], candidate["identity"]))
    preview = ordered[:10]
    if len(preview) == 10:
        floor = max(18.0, preview[0]["score"] * 0.34)
        dominant = next((kind for kind in ("movie", "series")
                         if sum(item["kind"] == kind for item in preview) > 7), None)
        if dominant:
            others = [item for item in ordered if item["kind"] != dominant and item["score"] >= floor]
            if len(others) >= 3:
                leaders = [item for item in ordered if item["kind"] == dominant][:7]
                selected = {item["identity"] for item in leaders + others[:3]}
                ordered = ([item for item in ordered if item["identity"] in selected]
                           + [item for item in ordered if item["identity"] not in selected])
    return [dict(item, global_rank=rank) for rank, item in enumerate(ordered[:limit], 1)]


def _configuration():
    priority = backend_value("provider_priority")
    state = backend_value("state")
    client = backend_value("get_tmdb_client")()
    # Routing health must not change the scope during an outage.
    with state.provider_priority_lock:
        movies = priority("movies", configured_only=True)
        series = priority("series", configured_only=True)
        configuration = [
            movies, series, sorted(state.content_languages),
            client.language if getattr(client, "configured", False) else None,
        ]
    key = hashlib.sha256(json.dumps(configuration).encode()).hexdigest()
    return key, movies, series, client


def _collect(kind, providers, grouped, client, fresh_since):
    types = MOVIE_SIGNALS if kind == "movie" else SERIES_SIGNALS
    status = {}
    fingerprints = {}
    loader = backend_value("_load_movie_provider_pages" if kind == "movie" else "_load_series_provider_pages")
    healthy = backend_value("state").provider_health.request_allowed
    ranked_movies = {key for key, signal in MOVIE_SIGNALS.items() if signal != "recent_uploads"}
    groups = (
        {"chart-top": ranked_movies, "new": set(providers) - ranked_movies}
        if kind == "movie"
        else {"trending": ["serienstream"], "discover": [key for key in providers if key != "serienstream"]}
    )
    pages = {}
    for mode, keys in groups.items():
        requests = [(key, 1) for key in providers if key in keys and healthy(key)]
        if not requests:
            continue
        try:
            pages.update(loader(mode, "", requests, None, fresh_since=fresh_since))
        except Exception:
            logger.warning("Chart catalog unavailable for %s/%s", kind, mode, exc_info=True)
    for provider in providers:
        signal = types.get(provider, "unknown")
        fingerprint = _provider_rows(grouped, kind, provider, pages.get((provider, 1), []), signal)
        status[provider] = {"type": signal, "observed": bool(fingerprint)}
        if len(fingerprint) >= 3 and signal in POPULARITY_STRENGTH and provider != "huhu":
            fingerprints.setdefault(fingerprint, []).append(provider)
    for providers_with_same_list in fingerprints.values():
        if len(providers_with_same_list) == 1:
            continue
        source = min(providers_with_same_list)
        for candidate in grouped.values():
            if candidate["kind"] == kind:
                for provider in providers_with_same_list:
                    signal = candidate["provider_signals"].get(provider)
                    if signal:
                        signal["source"] = source

    media_type = "movie" if kind == "movie" else "tv"
    if not getattr(client, "configured", False) or not any(row["kind"] == kind for row in grouped.values()):
        return status
    trends = _tmdb_rows(client, media_type)
    status["tmdb"] = {"type": "trending_rank", "observed": bool(trends)}
    by_rank = [row for _, row in trends.values()]
    targets = []
    for candidate in grouped.values():
        if candidate["kind"] != kind:
            continue
        row = _match_tmdb(candidate["item"], by_rank)
        if row:
            targets.append((candidate, row))
    matched = {candidate["identity"] for candidate, _ in targets}
    for candidate, row in targets:
        candidate["tmdb_trend_rank"] = trends[row["tmdb_id"]][0]

    remaining = sorted(
        (candidate for candidate in grouped.values()
         if candidate["kind"] == kind and candidate["identity"] not in matched),
        key=lambda candidate: (-_score_candidate(candidate)["score"], candidate["identity"]),
    )

    metadata_unavailable = threading.Event()

    def enrich(candidate):
        if metadata_unavailable.is_set():
            return candidate, None
        item = candidate["item"]
        data = _tmdb_request(client, f"/search/{media_type}", query=item["title"], include_adult="false")
        if not data:
            metadata_unavailable.set()
            return candidate, None
        rows = [_tmdb_row(raw, media_type) for raw in _result_list(data)]
        return candidate, _match_tmdb(
            item, [row for row in rows if row], allow_yearless=data.get("total_pages") == 1,
        )

    if remaining:
        with ThreadPoolExecutor(max_workers=4) as pool:
            targets.extend(pool.map(enrich, remaining[:ENRICH_LIMIT_PER_KIND]))
    if targets:
        genre_data = _tmdb_request(client, f"/genre/{media_type}/list")
        genres = {str(row["id"]): str(row.get("name") or "") for row in _result_list(genre_data, "genres")
                  if isinstance(row, dict) and "id" in row}
        for candidate, row in targets:
            if row:
                _merge_metadata(candidate["item"], row, client, genres)
                if row["year"]:
                    candidate["aliases"].extend(
                        _candidate_identity(kind, row[key], row["year"])
                        for key in ("title", "original_title") if row[key]
                    )
                trend = trends.get(row["tmdb_id"])
                if trend:
                    candidate["tmdb_trend_rank"] = trend[0]
    return status


def _build_daily_top(day, movies, series, client):
    grouped = {}
    fresh_since = datetime.combine(day, day_time.min, timezone.utc).timestamp()
    sources = {
        "movie": _collect("movie", movies, grouped, client, fresh_since),
        "series": _collect("series", series, grouped, client, fresh_since),
    }
    scored = [_score_candidate(candidate) for candidate in _merge_candidates(grouped.values())]
    eligible = [
        candidate for candidate in scored if candidate["components"]["popularity"]
        and len(candidate["item"]["title"]) >= 2
        and (candidate["item"].get("cover_url") or candidate["item"].get("backdrop_url"))
    ]
    return {
        "period": day.isoformat(), "algorithm_version": ALGORITHM, "generated_at": int(time.time()),
        "weights": WEIGHTS, "sources": sources, "candidates": _apply_diversity(eligible),
        "source_status": {
            "movie_providers": movies,
            "series_trending_provider": "serienstream" if sources["series"].get("serienstream", {}).get("observed") else None,
            "tmdb": any(kind.get("tmdb", {}).get("observed") for kind in sources.values()),
        },
    }


def _record(history, scope, day, claim, movies, series, client):
    try:
        payload = _build_daily_top(day, movies, series, client)
        if payload["candidates"] and chart_day() == day and _configuration()[0] == scope:
            history.save(scope, day, claim, payload)
    except Exception:
        logger.exception("Chart collection failed")


def _schedule(history, scope, day, config):
    global _build
    with _BUILD_LOCK:
        if _build and not _build[2].done():
            return _build[2] if _build[:2] == (scope, day) else None
        claim = history.claim(scope, day)
        if claim is None:
            return None
        job = _BUILD_POOL.submit(_record, history, scope, day, claim, *config)
        _build = (scope, day, job)
        return job


def collect_scheduled_chart():
    scope, *config = _configuration()
    _schedule(ChartHistory(config_path().with_name("royal_charts.sqlite3")), scope, chart_day(), config)


def _prepare(period):
    today = chart_day()
    if period:
        try:
            day = date.fromisoformat(period)
        except ValueError:
            day = today
    else:
        day = today
    scope, *config = _configuration()
    history = ChartHistory(config_path().with_name("royal_charts.sqlite3"))
    job = _schedule(history, scope, day, config) if day == today else None
    return history, scope, day, today, job


def _payload(history, scope, day, today, mode, kind, genre):
    result = chart_view(history.read(scope, day), day, mode, kind, genre)
    result.update(scope=scope[:16], chart_day=today.isoformat(), timezone="UTC", weights=WEIGHTS)
    if not result["source_status"]:
        result["source_status"] = {"movie_providers": [], "series_trending_provider": None, "tmdb": False}
    return result


async def _serve(period, mode="today", kind="mixed", genre=""):
    history, scope, day, today, job = await run_in_threadpool(_prepare, period)
    if job is not None:
        await asyncio.shield(asyncio.wrap_future(job))
    return await run_in_threadpool(_payload, history, scope, day, today, mode, kind, genre)


async def api_daily_top(response: Response, period: str = Query(default="", max_length=10)):
    response.headers["Cache-Control"] = "private, no-store"
    result = await _serve(period)
    return {**result, "version": 2}


async def api_royal_charts(
    response: Response,
    mode: str = Query(default="today", pattern="^(today|week|month|breakouts|new)$"),
    kind: str = Query(default="mixed", pattern="^(mixed|movie|series)$"),
    genre: str = Query(default="", max_length=80),
    period: str = Query(default="", max_length=10),
):
    response.headers["Cache-Control"] = "private, no-store"
    return await _serve(period, mode, kind, genre)


_existing_paths = {getattr(route, "path", "") for route in discovery_router.routes}
for path, endpoint in (
    ("/api/daily-top", api_daily_top),
    ("/api/v1/daily-top", api_daily_top),
    ("/api/v3/royal-charts", api_royal_charts),
):
    if path not in _existing_paths:
        discovery_router.add_api_route(path, endpoint, methods=["GET"])
