"""Home-only, deterministic, optional TMDB candidate discovery.

This module never resolves providers, enqueues downloads or sends personal
identifiers/history to TMDB. Only public genre IDs and recent positive seed-title IDs reach TMDB.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
import math
import re
import threading
import time
from datetime import date
from typing import Any, Mapping

from features.taste_model import canonical_value, score_profile_dimensions

# Stable TMDB genre identifiers; TV genres differ from movie genres.
TMDB_GENRES = {
    "movie": {
        "Action": 28, "Abenteuer": 12, "Animation": 16,
        "Komödie": 35, "Krimi": 80, "Dokumentation": 99, "Drama": 18,
        "Familie": 10751, "Fantasy": 14, "Geschichte": 36,
        "Horror": 27, "Musik": 10402, "Mystery": 9648,
        "Romanze": 10749, "Science-Fiction": 878, "Thriller": 53,
        "Krieg": 10752, "Western": 37,
    },
    "tv": {
        "Action": 10759, "Abenteuer": 10759, "Animation": 16,
        "Komödie": 35, "Krimi": 80, "Dokumentation": 99, "Drama": 18,
        "Familie": 10751, "Fantasy": 10765, "Mystery": 9648,
        "Science-Fiction": 10765, "Krieg": 10768, "Western": 37,
    },
}
MAX_REQUESTS = 3
# Shared limit: three TMDB requests run together instead of serially blocking
# the 15-second Home fetch when one external request is slow.
_DISCOVERY_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="home-discovery")
CACHE_SECONDS = 6 * 60 * 60
EMPTY_CACHE_SECONDS = 5 * 60


def _favorite_genres(profile: Mapping[str, Any]) -> list[str]:
    raw = (profile.get("dimensions") or {}).get("genres") or profile.get("genres") or {}
    ranked = []
    for genre, value in raw.items():
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(score) and score >= 1.5:
            ranked.append((canonical_value("genres", genre), score))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return [genre for genre, _ in ranked][:4]


def _suggestion(kind: str, raw: Mapping[str, Any], client: Any,
                profile: Mapping[str, Any], genre_names: Mapping[int, str],
                day: str, *, extra: tuple[str, str] | None = None) -> dict[str, Any] | None:
    if raw.get("adult") is True or not str(raw.get("id") or "").isdigit():
        return None
    tmdb_id = int(raw["id"])
    if tmdb_id < 1 or tmdb_id > 9_999_999_999:
        return None
    title = str(raw.get("title") or raw.get("name") or "").strip()
    if not title:
        return None
    genres = [genre_names[int(genre_id)] for genre_id in raw.get("genre_ids") or []
              if str(genre_id).isdigit() and int(genre_id) in genre_names]
    if not genres:
        return None
    date_value = str(raw.get("release_date") or raw.get("first_air_date") or "")
    year = date_value[:4] if date_value[:4].isdigit() else ""
    dimensions = {"genres": genres, "media_types": ["movie" if kind == "movie" else "series"]}
    if extra and extra[0] in {"actors", "directors", "franchises"}:
        dimensions[extra[0]] = [extra[1]]
    if year:
        dimensions["decades"] = [f"{int(year) // 10 * 10}er"]
    taste = score_profile_dimensions(profile, dimensions)
    if taste["positive"] < 1 or taste["negative"] < -max(2.5, taste["positive"]):
        return None
    logical = f"{'movie' if kind == 'movie' else 'series'}:tmdb:{tmdb_id}"
    if logical in set(profile.get("blocked_items") or []):
        return None
    # A clicked idea is weak evidence, not a reason to repeat it for weeks.
    # Timestamps are seconds on the server; tolerate legacy milliseconds.
    cutoff = time.time() - 14 * 86400
    for event in (profile.get("recent") or [])[:60]:
        if event.get("key") != logical:
            continue
        try:
            last_at = float(event.get("at") or 0)
        except (ValueError, TypeError):
            continue
        if last_at > 1e12:
            last_at /= 1000
        if last_at >= cutoff:
            return None
    try:
        rating = float(raw.get("vote_average") or 0)
        votes = int(raw.get("vote_count") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(rating) or rating < 5.5 or rating > 10 or votes < 25:
        return None
    art = str(raw.get("poster_path") or "")
    backdrop = str(raw.get("backdrop_path") or "")
    if not art and not backdrop:
        return None
    jitter = int(hashlib.sha256(f"{day}|{logical}".encode()).hexdigest()[:6], 16) / 0xFFFFFF
    score = (
        13 * math.tanh(float(taste["score"]) / 13)
        + rating * 0.20
        + min(2.0, math.log10(votes + 1) * .4)
        + jitter * 1.5
    )
    media_type = "movie" if kind == "movie" else "series"
    item = {
        "tmdb_id": tmdb_id,
        "slug": f"tmdb:{tmdb_id}",
        "base_slug": f"tmdb:{tmdb_id}",
        "title": title[:160],
        "year": year,
        "release_date": date_value,
        "genres": genres[:8],
        "rating": round(rating, 1),
        "vote_count": votes,
        "cover_url": client._poster_url(art) if art else "",
        "backdrop_url": client._backdrop_url(backdrop) if backdrop else "",
        "description": str(raw.get("overview") or "").strip()[:500],
        "tmdb_discovery": True,
        "discovery_reason": [r["value"] for r in taste["reasons"]
                             if r["contribution"] > 0][:3],
    }
    return {"kind": media_type, "item": item, "_score": score}


def _recent_tmdb_seed(profile: Mapping[str, Any]) -> tuple[str, int] | None:
    """Choose a recent positive TMDB title, never a rejected title."""
    for event in (profile.get("recent") or [])[:30]:
        if event.get("action") not in {"open", "like", "favorite", "download"}:
            continue
        match = re.fullmatch(r"(movie|series):tmdb:([1-9]\d{0,9})", str(event.get("key") or ""))
        if match:
            return ("movie" if match[1] == "movie" else "tv", int(match[2]))
    return None


def _favorite_subject(profile: Mapping[str, Any]) -> tuple[str, str] | None:
    """Pick one confident public actor/director/franchise, avoiding query fan-out."""
    dimensions = profile.get("dimensions") or {}
    candidates: list[tuple[float, str, str]] = []
    for dimension, multiplier in (("directors", 0.82), ("actors", 0.46), ("franchises", 0.74)):
        for name, value in (dimensions.get(dimension) or {}).items():
            clean = str(name or "").strip()
            if not 2 <= len(clean) <= 64:
                continue
            try:
                score = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(score) and score >= 4.0:
                candidates.append((score * multiplier, dimension, clean))
    if not candidates:
        return None
    _score, dimension, name = max(candidates, key=lambda row: (row[0], row[2]))
    return (dimension, name)


def discover_home_candidates(profile: Mapping[str, Any], client: Any,
                             *, day: str | None = None, limit: int = 24) -> list[dict[str, Any]]:
    """Search beyond provider catalog; suggestions are explicitly not availability claims."""
    if not getattr(client, "configured", False):
        return []
    favorites = _favorite_genres(profile)
    seed = _recent_tmdb_seed(profile)
    subject_seed = _favorite_subject(profile) if not seed else None
    if not favorites and not seed and not subject_seed:
        return []
    day = day or date.today().isoformat()
    day_offset = int(hashlib.sha256(day.encode()).hexdigest()[:2], 16) % 3
    requests: list[tuple[str, int, str]] = []
    # Up to two different film genres and one TV genre; no unbounded fan-out.
    for kind in ("movie", "tv"):
        allowed = TMDB_GENRES[kind]
        seen_ids = set()
        for genre in favorites:
            genre_id = allowed.get(genre)
            if genre_id and genre_id not in seen_ids:
                seen_ids.add(genre_id)
                requests.append((kind, genre_id, genre))
            if len([entry for entry in requests if entry[0] == kind]) >= (2 if kind == "movie" else 1):
                break
    jobs = [("genre", kind, genre_id, genre) for kind, genre_id, genre in requests]
    if seed:
        # Trade one generic genre request for titles related to a recent
        # positive choice, without increasing the external request budget.
        movie = next((job for job in jobs if job[1] == "movie"), None)
        television = next((job for job in jobs if job[1] == "tv"), None)
        jobs = [job for job in (movie, ("related", seed[0], seed[1], ""), television) if job]
    elif subject_seed:
        # Resolving a public person name needs a second TMDB call to fetch
        # credited films. Keep just one genre call: 1 + 1 + 1 <= MAX_REQUESTS.
        jobs = jobs[:1]
    batches = jobs[:MAX_REQUESTS]

    def fetch_page(index_and_batch):
        index, (mode, kind, value, _genre) = index_and_batch
        try:
            if mode == "related":
                payload = client._request(f"/{kind}/{value}/recommendations", {
                    "language": getattr(client, "language", "de-DE"),
                })
            elif mode == "franchise":
                collection = client._request(f"/collection/{value}", {
                    "language": getattr(client, "language", "de-DE"),
                })
                payload = {"results": (collection or {}).get("parts") or []}
            elif mode == "person":
                payload = client._request("/discover/movie", {
                    "language": getattr(client, "language", "de-DE"),
                    "include_adult": "false",
                    "with_cast" if kind == "actors" else "with_crew": value,
                    "sort_by": "popularity.desc", "vote_count.gte": 25,
                    "page": 1,
                })
            else:
                payload = client._request(f"/discover/{kind}", {
                    "language": getattr(client, "language", "de-DE"),
                    "include_adult": "false",
                    "with_genres": value,
                    "sort_by": "vote_average.desc" if index % 2 else "popularity.desc",
                    "vote_count.gte": 75 if kind == "movie" else 30,
                    "page": 1 + (day_offset if index else 0),
                })
        except Exception:
            # A single failing TMDB query must not blank the entire Home feed.
            return {}
        return payload if isinstance(payload, dict) else {}

    def lookup_subject():
        if not subject_seed:
            return None
        dimension, name = subject_seed
        path = "/search/collection" if dimension == "franchises" else "/search/person"
        try:
            payload = client._request(path, {
                "language": getattr(client, "language", "de-DE"),
                "query": name, "page": 1, "include_adult": "false",
            })
            people = (payload or {}).get("results") or []
        except Exception:
            return None
        for person in people[:12]:
            if not isinstance(person, dict) or str(person.get("name") or "").casefold() != name.casefold():
                continue
            try:
                person_id = int(person.get("id"))
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 < person_id <= 9_999_999_999:
                return (dimension, person_id, name)
        return None

    person_future = _DISCOVERY_POOL.submit(lookup_subject) if subject_seed else None
    fetched = list(zip(batches, _DISCOVERY_POOL.map(fetch_page, enumerate(batches))))
    if person_future:
        person = person_future.result()
        if person:
            dimension, person_id, name = person
            job = ("franchise", "movie", person_id, name) if dimension == "franchises" else (
                "person", dimension, person_id, name)
            fetched.append((job, fetch_page((len(fetched), job))))

    results: dict[str, dict[str, Any]] = {}
    # Bounded pool: one genre + person search + person credits = at most 3 calls.
    for (mode, kind, genre_id, genre), payload in fetched:
        media_kind = "movie" if mode in {"person", "franchise"} else kind
        names = {value: name for name, value in TMDB_GENRES[media_kind].items()}
        if mode == "genre" and genre:
            names[genre_id] = genre
        for raw in (payload.get("results") or [])[:20]:
            if not isinstance(raw, dict):
                continue
            extra = (("franchises" if mode == "franchise" else kind), genre) if mode in {"person", "franchise"} else None
            suggestion = _suggestion(media_kind, raw, client, profile, names, day,
                                     extra=extra)
            if suggestion is None:
                continue
            logical = f"{suggestion['kind']}:{suggestion['item']['tmdb_id']}"
            existing = results.get(logical)
            if existing is None or suggestion["_score"] > existing["_score"]:
                results[logical] = suggestion
    ranked = sorted(results.values(), key=lambda candidate: -candidate["_score"])
    # Mix series and films, avoid a feed made solely of the first genre.
    selected: list[dict[str, Any]] = []
    genre_counts: dict[str, int] = {}
    deferred: list[dict[str, Any]] = []
    for candidate in ranked:
        lead = candidate["item"]["genres"][0]
        if genre_counts.get(lead, 0) >= max(4, limit // 3):
            deferred.append(candidate)
            continue
        genre_counts[lead] = genre_counts.get(lead, 0) + 1
        selected.append({key: value for key, value in candidate.items() if key != "_score"})
        if len(selected) >= limit:
            break
    # Variety is a preference, not a hard scarcity cap. A Thriller enthusiast
    # must not be shown just eight matches when there are twenty good titles.
    for candidate in deferred:
        if len(selected) >= limit:
            break
        selected.append({key: value for key, value in candidate.items() if key != "_score"})
    return selected


class HomeDiscoveryService:
    """Isolated per-user in-memory result cache; no disk or browser persistence."""

    def __init__(self, *, clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._inflight: dict[str, threading.Event] = {}

    def get(self, user_id: str, profile: Mapping[str, Any], client: Any) -> dict[str, Any]:
        ready = bool(getattr(client, "configured", False))
        dimensions = profile.get("dimensions") or {}
        key_data = json.dumps([
            user_id, dimensions, profile.get("blocked_items") or [],
            [(event.get("key"), event.get("at"))
             for event in (profile.get("recent") or [])[:30]],
            date.today().isoformat(), getattr(client, "language", ""), ready,
        ], sort_keys=True, ensure_ascii=False, default=str)
        key = hashlib.sha256(key_data.encode()).hexdigest()
        now = float(self.clock())
        while True:
            with self._lock:
                cached = self._cache.get(key)
                if cached:
                    ttl = CACHE_SECONDS if cached[1].get("results") else EMPTY_CACHE_SECONDS
                    if now - cached[0] < ttl:
                        return dict(cached[1])
                waiter = self._inflight.get(key)
                if waiter is None:
                    waiter = threading.Event()
                    self._inflight[key] = waiter
                    break
            # A second browser tab should reuse the first result, not trigger
            # another three-request TMDB burst. A stalled fetch cannot hold a
            # waiting request forever; each wait is bounded to 20 seconds.
            if not waiter.wait(timeout=20):
                break
        try:
            results = discover_home_candidates(profile, client) if ready else []
            response = {"available": ready, "results": results, "updated_at": now}
            with self._lock:
                if len(self._cache) >= 32:
                    self._cache = {k: v for k, v in self._cache.items()
                                   if now - v[0] < CACHE_SECONDS}
                    if len(self._cache) >= 32:
                        oldest = min(self._cache, key=lambda k: self._cache[k][0])
                        self._cache.pop(oldest, None)
                self._cache[key] = (now, response)
            return dict(response)
        finally:
            with self._lock:
                if self._inflight.get(key) is waiter:
                    self._inflight.pop(key, None)
                    waiter.set()
