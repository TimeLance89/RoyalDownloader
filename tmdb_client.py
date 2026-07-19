"""Optionale TMDB-Metadaten für Filme und Serien (stdlib, mit Cache)."""

import json
import logging
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urlencode


logger = logging.getLogger(__name__)
API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_IMAGE_BASE = "https://image.tmdb.org/t/p/w1280"
SERIES_CACHE_TTL = 6 * 60 * 60
SERIES_NEGATIVE_CACHE_TTL = 60


def _series_cache_ttl(value: Optional[dict]) -> int:
    """Fehler und unvollständige Detailantworten nur kurz zwischenspeichern."""
    if value and float(value.get("season_counts_checked_at") or 0) > 0:
        return SERIES_CACHE_TTL
    return SERIES_NEGATIVE_CACHE_TTL


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _year_from_date(value: str) -> str:
    match = re.match(r"(\d{4})", value or "")
    return match.group(1) if match else ""


class TMDBClient:
    def __init__(self, api_key: str = "", language: str = "de-DE", timeout: float = 8.0):
        self.api_key = (api_key or "").strip()
        self.language = language
        self.timeout = timeout
        self._movie_summary_cache: dict = {}
        self._movie_cache: dict = {}
        self._movie_id_cache: dict = {}
        self._series_cache: dict = {}
        self._series_id_cache: dict = {}
        self._series_match_cache: dict = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def _uses_bearer(self) -> bool:
        return self.api_key.startswith("eyJ") or self.api_key.count(".") == 2

    def _request(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        if not self.configured:
            return None
        query = dict(params or {})
        headers = {"Accept": "application/json", "User-Agent": "RoyalDownloader/1.0"}
        if self._uses_bearer:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            query["api_key"] = self.api_key
        url = f"{API_BASE}{path}"
        if query:
            url += "?" + urlencode(query)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            logger.warning("TMDB-Anfrage fehlgeschlagen (%s): HTTP %s", path, exc.code)
        except Exception as exc:
            logger.warning("TMDB-Anfrage fehlgeschlagen (%s): %s", path, exc)
        return None

    def validate(self) -> bool:
        data = self._request("/authentication")
        return bool(data and data.get("success"))

    @staticmethod
    def _best_result(results: list, title: str, year: str, title_fields: tuple, date_field: str) -> Optional[dict]:
        wanted = _normalize(title)
        if not wanted:
            return None
        candidates = []
        for item in results or []:
            names = [_normalize(str(item.get(field) or "")) for field in title_fields]
            exact = wanted in names
            partial = any(wanted in name or name in wanted for name in names if len(name) >= 4)
            if not exact and not partial:
                continue
            item_year = _year_from_date(str(item.get(date_field) or ""))
            score = (
                100 if exact else 30,
                25 if year and item_year == str(year) else 0,
                float(item.get("popularity") or 0),
            )
            candidates.append((score, item))
        return max(candidates, key=lambda pair: pair[0])[1] if candidates else None

    @staticmethod
    def _poster_url(path: str) -> str:
        return f"{IMAGE_BASE}{path}" if path else ""

    @staticmethod
    def _backdrop_url(path: str) -> str:
        return f"{BACKDROP_IMAGE_BASE}{path}" if path else ""

    def movie_summary(self, title: str, year: str = "") -> Optional[dict]:
        """Schnelle Listenmetadaten mit nur einer TMDB-Suchanfrage."""
        query_title = re.sub(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", title or "").strip()
        cache_key = (_normalize(query_title), str(year or ""))
        with self._lock:
            if cache_key in self._movie_summary_cache:
                return self._movie_summary_cache[cache_key]

        params = {"query": query_title, "language": self.language, "include_adult": "false"}
        if year:
            params["primary_release_year"] = str(year)
        search = self._request("/search/movie", params) or {}
        best = self._best_result(
            search.get("results", []), query_title, str(year or ""),
            ("title", "original_title"), "release_date",
        )
        if best is None and year:
            params.pop("primary_release_year", None)
            search = self._request("/search/movie", params) or {}
            best = self._best_result(
                search.get("results", []), query_title, str(year),
                ("title", "original_title"), "release_date",
            )

        result = None
        if best:
            result = {
                "tmdb_id": best["id"],
                "title": best.get("title") or title,
                "year": _year_from_date(best.get("release_date") or ""),
                "runtime": "",
                "cover_url": self._poster_url(best.get("poster_path") or ""),
                "backdrop_url": self._backdrop_url(best.get("backdrop_path") or ""),
                "description": best.get("overview") or "",
                "genres": [],
                "original_title": best.get("original_title") or "",
                "release_date": best.get("release_date") or "",
                "rating": round(float(best.get("vote_average") or 0), 1),
                "vote_count": int(best.get("vote_count") or 0),
                "details_loaded": False,
                "metadata_source": "TMDB",
            }
        # Temporäre API-/Rate-Limit-Fehler dürfen den Titel nicht dauerhaft
        # negativ cachen. Beim nächsten Seerr-Retry wird erneut geprüft.
        if result is not None:
            with self._lock:
                self._movie_summary_cache[cache_key] = result
        return result

    def movie(self, title: str, year: str = "") -> Optional[dict]:
        query_title = re.sub(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", title or "").strip()
        cache_key = (_normalize(query_title), str(year or ""))
        with self._lock:
            if cache_key in self._movie_cache:
                return self._movie_cache[cache_key]

        summary = self.movie_summary(query_title, year)
        result = None
        if summary:
            details = self._request(f"/movie/{summary['tmdb_id']}", {"language": self.language}) or summary
            if not details.get("overview"):
                english = self._request(f"/movie/{summary['tmdb_id']}", {"language": "en-US"}) or {}
                details["overview"] = english.get("overview", "")
            runtime = details.get("runtime")
            result = {
                "tmdb_id": summary["tmdb_id"],
                "title": details.get("title") or summary.get("title") or title,
                "year": _year_from_date(details.get("release_date") or "") or summary.get("year", ""),
                "runtime": f"{runtime} min" if runtime else "",
                "cover_url": self._poster_url(details.get("poster_path") or "") or summary.get("cover_url", ""),
                "backdrop_url": self._backdrop_url(details.get("backdrop_path") or "") or summary.get("backdrop_url", ""),
                "description": details.get("overview") or summary.get("description") or "",
                "genres": [g.get("name", "") for g in details.get("genres", []) if g.get("name")],
                "original_title": details.get("original_title") or summary.get("original_title") or "",
                "release_date": details.get("release_date") or summary.get("release_date") or "",
                "rating": round(float(details.get("vote_average") or summary.get("rating") or 0), 1),
                "vote_count": int(details.get("vote_count") or summary.get("vote_count") or 0),
                "tagline": details.get("tagline") or "",
                "details_loaded": True,
                "metadata_source": "TMDB",
            }
        with self._lock:
            self._movie_cache[cache_key] = result
        return result

    def movie_by_id(self, tmdb_id, title: str = "", force: bool = False) -> Optional[dict]:
        """Lädt einen Film eindeutig über seine TMDB-ID (z. B. aus Seerr)."""
        key = str(tmdb_id or "").strip()
        if not key.isdigit():
            return None
        with self._lock:
            if key in self._movie_id_cache and not force:
                return self._movie_id_cache[key]

        details = self._request(f"/movie/{key}", {"language": self.language})
        result = None
        if details:
            if not details.get("overview"):
                english = self._request(f"/movie/{key}", {"language": "en-US"}) or {}
                details["overview"] = english.get("overview", "")
            runtime = details.get("runtime")
            result = {
                "tmdb_id": int(key),
                "title": details.get("title") or title,
                "year": _year_from_date(details.get("release_date") or ""),
                "runtime": f"{runtime} min" if runtime else "",
                "cover_url": self._poster_url(details.get("poster_path") or ""),
                "backdrop_url": self._backdrop_url(details.get("backdrop_path") or ""),
                "description": details.get("overview") or "",
                "genres": [g.get("name", "") for g in details.get("genres", []) if g.get("name")],
                "original_title": details.get("original_title") or "",
                "release_date": details.get("release_date") or "",
                "rating": round(float(details.get("vote_average") or 0), 1),
                "vote_count": int(details.get("vote_count") or 0),
                "tagline": details.get("tagline") or "",
                "details_loaded": True,
                "metadata_source": "TMDB",
            }
        if result is not None:
            with self._lock:
                self._movie_id_cache[key] = result
        return result

    def _series_payload(
        self, details: dict, fallback_title: str, tmdb_id, fetched_at: float,
    ) -> dict:
        runtimes = details.get("episode_run_time") or []
        runtime = runtimes[0] if runtimes else None
        return {
            "tmdb_id": int(tmdb_id),
            "title": details.get("name") or fallback_title,
            "original_title": details.get("original_name") or "",
            "year": _year_from_date(details.get("first_air_date") or ""),
            "runtime": f"{runtime} min/Folge" if runtime else "",
            "cover_url": self._poster_url(details.get("poster_path") or ""),
            "description": details.get("overview") or "",
            "genres": [g.get("name", "") for g in details.get("genres", []) if g.get("name")],
            "season_episode_counts": {
                str(int(season.get("season_number"))): int(season.get("episode_count"))
                for season in details.get("seasons", [])
                if season.get("season_number") is not None and season.get("episode_count")
            },
            "season_counts_checked_at": fetched_at,
            "metadata_source": "TMDB",
        }

    def series_by_id(self, tmdb_id, title: str = "", force: bool = False) -> Optional[dict]:
        key = str(tmdb_id or "").strip()
        if not key.isdigit():
            return None
        now = time.time()
        with self._lock:
            cached = self._series_id_cache.get(key)
            if cached and not force and now - cached[0] < _series_cache_ttl(cached[1]):
                return cached[1]
        details = self._request(f"/tv/{key}", {"language": self.language})
        result = None
        if details:
            if not details.get("overview"):
                english = self._request(f"/tv/{key}", {"language": "en-US"}) or {}
                details["overview"] = english.get("overview", "")
            result = self._series_payload(details, title, key, now)
        with self._lock:
            self._series_id_cache[key] = (now, result)
        return result

    def series_matches_id(self, title: str, tmdb_id, year: str = "") -> bool:
        """Bestätigt einen Quelltitel über einen exakten Treffer der TMDB-ID."""
        query_title = str(title or "").strip()
        wanted_title = _normalize(query_title)
        wanted_id = str(tmdb_id or "").strip()
        wanted_year = str(year or "").strip()
        if not wanted_title or not wanted_id.isdigit() or not self.configured:
            return False
        cache_key = (wanted_title, wanted_id, wanted_year)
        with self._lock:
            if self._series_match_cache.get(cache_key):
                return True

        search = self._request("/search/tv", {
            "query": query_title,
            "language": self.language,
            "include_adult": "false",
        }) or {}
        matched = False
        for item in search.get("results", []):
            if str(item.get("id") or "") != wanted_id:
                continue
            names = {
                _normalize(str(item.get("name") or "")),
                _normalize(str(item.get("original_name") or "")),
            }
            if wanted_title not in names:
                continue
            item_year = _year_from_date(str(item.get("first_air_date") or ""))
            if wanted_year and item_year and item_year != wanted_year:
                continue
            matched = True
            break
        if matched:
            with self._lock:
                self._series_match_cache[cache_key] = True
        return matched

    def series(self, title: str, force: bool = False) -> Optional[dict]:
        cache_key = _normalize(title)
        now = time.time()
        with self._lock:
            cached = self._series_cache.get(cache_key)
            if cached and not force and now - cached[0] < _series_cache_ttl(cached[1]):
                return cached[1]

        search = self._request("/search/tv", {
            "query": title, "language": self.language, "include_adult": "false",
        }) or {}
        best = self._best_result(
            search.get("results", []), title, "", ("name", "original_name"), "first_air_date",
        )
        result = None
        if best:
            result = self.series_by_id(best["id"], best.get("name") or title, force=force)
            if result is None:
                # Anzeige darf Suchmetadaten nutzen; Staffelvollständigkeit bleibt
                # wegen checked_at=0 strikt gesperrt.
                result = self._series_payload(best, title, best["id"], 0.0)
        with self._lock:
            self._series_cache[cache_key] = (now, result)
        return result
