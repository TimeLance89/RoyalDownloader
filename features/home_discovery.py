"""Home-only, deterministic, optional TMDB candidate discovery.

This module never resolves providers, enqueues downloads or sends personal
identifiers/history to TMDB. Only public TMDB genre IDs leave the server.
"""
from __future__ import annotations

import hashlib
import json
import math
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
CACHE_SECONDS = 6 * 60 * 60


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
                day: str) -> dict[str, Any] | None:
    if raw.get("adult") is True or not str(raw.get("id") or "").isdigit():
        return None
    tmdb_id = int(raw["id"])
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
    if year:
        dimensions["decades"] = [f"{int(year) // 10 * 10}er"]
    taste = score_profile_dimensions(profile, dimensions)
    if taste["positive"] < 1 or taste["negative"] < -max(2.5, taste["positive"]):
        return None
    logical = f"{'movie' if kind == 'movie' else 'series'}:tmdb:{tmdb_id}"
    if logical in set(profile.get("blocked_items") or []):
        return None
    rating = float(raw.get("vote_average") or 0)
    votes = int(raw.get("vote_count") or 0)
    if rating < 5.5 or votes < 25:
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


def discover_home_candidates(profile: Mapping[str, Any], client: Any,
                             *, day: str | None = None, limit: int = 24) -> list[dict[str, Any]]:
    """Search beyond provider catalog; suggestions are explicitly not availability claims."""
    if not getattr(client, "configured", False):
        return []
    favorites = _favorite_genres(profile)
    if not favorites:
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
    results: dict[str, dict[str, Any]] = {}
    for index, (kind, genre_id, genre) in enumerate(requests[:MAX_REQUESTS]):
        params = {
            "language": getattr(client, "language", "de-DE"),
            "include_adult": "false",
            "with_genres": genre_id,
            "sort_by": "vote_average.desc" if index % 2 else "popularity.desc",
            "vote_count.gte": 75 if kind == "movie" else 30,
            "page": 1 + (day_offset if index else 0),
        }
        payload = client._request(f"/discover/{kind}", params) or {}
        names = {genre_id: genre}
        # Make all other candidate genres meaningful for reranking if supplied.
        known = TMDB_GENRES[kind]
        names.update({value: name for name, value in known.items() if value != genre_id})
        for raw in (payload.get("results") or [])[:20]:
            if not isinstance(raw, dict):
                continue
            suggestion = _suggestion(kind, raw, client, profile, names, day)
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
    for candidate in ranked:
        lead = candidate["item"]["genres"][0]
        if genre_counts.get(lead, 0) >= max(4, limit // 3):
            continue
        genre_counts[lead] = genre_counts.get(lead, 0) + 1
        selected.append({key: value for key, value in candidate.items() if key != "_score"})
        if len(selected) >= limit:
            break
    return selected


class HomeDiscoveryService:
    """Isolated per-user in-memory result cache; no disk or browser persistence."""

    def __init__(self, *, clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, user_id: str, profile: Mapping[str, Any], client: Any) -> dict[str, Any]:
        ready = bool(getattr(client, "configured", False))
        dimensions = profile.get("dimensions") or {}
        key_data = json.dumps([
            user_id, dimensions, profile.get("blocked_items") or [],
            date.today().isoformat(), getattr(client, "language", ""),
        ], sort_keys=True, ensure_ascii=False, default=str)
        key = hashlib.sha256(key_data.encode()).hexdigest()
        now = float(self.clock())
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < CACHE_SECONDS:
                return dict(cached[1])
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
