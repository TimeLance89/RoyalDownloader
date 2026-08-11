"""Optionale TMDB-Metadaten für Filme und Serien (stdlib, mit Cache)."""

import json
import logging
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import urlencode


logger = logging.getLogger(__name__)
API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_IMAGE_BASE = "https://image.tmdb.org/t/p/w1280"
PROFILE_IMAGE_BASE = "https://image.tmdb.org/t/p/w185"
SERIES_CACHE_TTL = 6 * 60 * 60
SERIES_NEGATIVE_CACHE_TTL = 60
NOW_PLAYING_CACHE_TTL = 6 * 60 * 60


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


def _clean_movie_query_title(title: str) -> str:
    """Entfernt Release-/Anbieterzusätze, die kein TMDB-Titelbestandteil sind."""
    value = " ".join(str(title or "").split()).strip()
    language = r"(?:ENGLISH|ENGLISCH|GERMAN|DEUTSCH|MULTI(?:LANGUAGE)?|OV|O-TON)"
    previous = None
    while value and value != previous:
        previous = value
        value = re.sub(r"\s*\[[^\]]+\]\s*$", "", value).strip()
        value = re.sub(r"\s*\([^()]*\)\s*$", "", value).strip()
        value = re.sub(
            rf"^[\\/|:_-]*\s*{language}(?:\s+(?:DUB|SUB|DL))?"
            rf"\s*[\\/|:_-]+\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(
            rf"\s*[\\/|:_-]+\s*{language}(?:\s+(?:DUB|SUB|DL))?"
            rf"\s*[\\/|:_-]*\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(
            r"\s+(?:ENGLISH|ENGLISCH|GERMAN|DEUTSCH|MULTI|OV|O-TON)"
            r"(?:\s+(?:DUB|SUB|DL))?\s*$",
            "",
            value,
        ).strip()
    return re.sub(
        r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", value,
    ).strip()


class TMDBClient:
    def __init__(self, api_key: str = "", language: str = "de-DE", timeout: float = 8.0):
        self.api_key = (api_key or "").strip()
        self.language = language
        self.timeout = timeout
        self._movie_summary_cache: dict = {}
        self._movie_summary_id_cache: dict = {}
        self._series_summary_cache: dict = {}
        self._movie_search_cache: dict = {}
        self._movie_cache: dict = {}
        self._movie_id_cache: dict = {}
        self._series_cache: dict = {}
        self._series_id_cache: dict = {}
        self._series_match_cache: dict = {}
        self._season_cache: dict = {}
        self._genre_cache: dict = {}
        self._now_playing_cache: tuple[float, set[int]] = (0.0, set())
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

    @staticmethod
    def _profile_url(path: str) -> str:
        return f"{PROFILE_IMAGE_BASE}{path}" if path else ""

    def _preferred_region(self) -> str:
        parts = str(self.language or "").split("-", 1)
        return parts[1].upper() if len(parts) == 2 and len(parts[1]) == 2 else "US"

    def _genre_names(self, media_type: str, genre_ids: list) -> list[str]:
        ids = []
        for value in genre_ids or []:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if not ids:
            return []
        cache_key = (media_type, self.language)
        with self._lock:
            mapping = self._genre_cache.get(cache_key)
        if mapping is None:
            data = self._request(
                f"/genre/{media_type}/list", {"language": self.language},
            ) or {}
            mapping = {
                int(item["id"]): str(item.get("name") or "").strip()
                for item in data.get("genres", [])
                if isinstance(item, dict) and str(item.get("id") or "").isdigit()
            }
            with self._lock:
                self._genre_cache[cache_key] = mapping
        return [mapping[genre_id] for genre_id in ids if mapping.get(genre_id)]

    def _movie_certification(self, details: dict) -> tuple[str, str]:
        countries = (details.get("release_dates") or {}).get("results") or []
        by_country = {
            str(item.get("iso_3166_1") or "").upper(): item
            for item in countries if isinstance(item, dict)
        }
        preferred = self._preferred_region()
        for country in (preferred, "US", *by_country):
            releases = (by_country.get(country) or {}).get("release_dates") or []
            certified = [
                release for release in releases
                if isinstance(release, dict) and str(release.get("certification") or "").strip()
            ]
            if certified:
                priority = {3: 0, 2: 1, 4: 2, 5: 3, 6: 4, 1: 5}
                best = min(
                    certified,
                    key=lambda release: priority.get(int(release.get("type") or 99), 99),
                )
                return str(best.get("certification") or "").strip(), country
        return "", ""

    def _movie_trailer(self, videos: list) -> Optional[dict]:
        preferred_language = str(self.language or "en-US").split("-", 1)[0].lower()
        candidates = [
            video for video in videos or []
            if isinstance(video, dict)
            and str(video.get("site") or "").casefold() == "youtube"
            and str(video.get("key") or "").strip()
            and str(video.get("type") or "") in {"Trailer", "Teaser"}
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda video: (
            bool(video.get("official")),
            str(video.get("type") or "") == "Trailer",
            str(video.get("iso_639_1") or "").lower() == preferred_language,
            int(video.get("size") or 0),
            str(video.get("published_at") or ""),
        ))
        return {
            "site": "YouTube",
            "key": str(best.get("key") or "").strip(),
            "name": str(best.get("name") or "Trailer"),
            "official": bool(best.get("official")),
        }

    def _movie_payload(
        self, details: dict, fallback: dict, tmdb_id, fallback_title: str,
        details_loaded: bool,
    ) -> dict:
        runtime = details.get("runtime")
        crew = (details.get("credits") or {}).get("crew") or []
        cast = (details.get("credits") or {}).get("cast") or []
        directors = list(dict.fromkeys(
            str(member.get("name") or "").strip()
            for member in crew
            if isinstance(member, dict)
            and member.get("job") == "Director"
            and member.get("name")
        ))
        writers = list(dict.fromkeys(
            str(member.get("name") or "").strip()
            for member in crew
            if isinstance(member, dict)
            and member.get("job") in {"Screenplay", "Writer", "Story"}
            and member.get("name")
        ))
        certification, certification_country = self._movie_certification(details)
        trailer = self._movie_trailer(
            (details.get("videos") or {}).get("results") or []
        )
        keywords = (details.get("keywords") or {}).get("keywords") or []
        original_language = str(details.get("original_language") or "").lower()
        spoken_languages = [
            str(language.get("english_name") or language.get("name") or "").strip()
            for language in details.get("spoken_languages") or []
            if isinstance(language, dict)
            and (language.get("english_name") or language.get("name"))
        ]
        return {
            "tmdb_id": int(tmdb_id),
            "title": details.get("title") or fallback.get("title") or fallback_title,
            "year": (
                _year_from_date(details.get("release_date") or "")
                or fallback.get("year", "")
            ),
            "runtime": (
                f"{runtime} min" if runtime else fallback.get("runtime", "")
            ),
            "cover_url": (
                self._poster_url(details.get("poster_path") or "")
                or fallback.get("cover_url", "")
            ),
            "backdrop_url": (
                self._backdrop_url(details.get("backdrop_path") or "")
                or fallback.get("backdrop_url", "")
            ),
            "description": details.get("overview") or fallback.get("description") or "",
            "genres": (
                [genre.get("name", "") for genre in details.get("genres", []) if genre.get("name")]
                or fallback.get("genres", [])
            ),
            "original_title": (
                details.get("original_title") or fallback.get("original_title") or ""
            ),
            "release_date": (
                details.get("release_date") or fallback.get("release_date") or ""
            ),
            "rating": round(
                float(details.get("vote_average") or fallback.get("rating") or 0), 1
            ),
            "vote_count": int(
                details.get("vote_count") or fallback.get("vote_count") or 0
            ),
            "tagline": details.get("tagline") or "",
            "certification": certification,
            "certification_country": certification_country,
            "status": str(details.get("status") or ""),
            "original_language": original_language,
            "spoken_languages": spoken_languages[:4],
            "countries": [
                str(country.get("name") or "").strip()
                for country in details.get("production_countries") or []
                if isinstance(country, dict) and country.get("name")
            ][:4],
            "directors": directors[:3],
            "writers": writers[:4],
            "cast": [
                {
                    "name": str(member.get("name") or "").strip(),
                    "character": str(member.get("character") or "").strip(),
                    "profile_url": self._profile_url(member.get("profile_path") or ""),
                }
                for member in cast[:8]
                if isinstance(member, dict) and member.get("name")
            ],
            "production_companies": [
                str(company.get("name") or "").strip()
                for company in details.get("production_companies") or []
                if isinstance(company, dict) and company.get("name")
            ][:4],
            "keywords": [
                str(keyword.get("name") or "").strip()
                for keyword in keywords
                if isinstance(keyword, dict) and keyword.get("name")
            ][:8],
            "collection": str(
                (details.get("belongs_to_collection") or {}).get("name") or ""
            ),
            "budget": int(details.get("budget") or 0),
            "revenue": int(details.get("revenue") or 0),
            "trailer": trailer,
            "tmdb_url": f"https://www.themoviedb.org/movie/{int(tmdb_id)}",
            "details_loaded": details_loaded,
            "metadata_source": "TMDB",
        }

    def _movie_details(self, tmdb_id) -> Optional[dict]:
        details = self._request(f"/movie/{tmdb_id}", {
            "language": self.language,
            "append_to_response": "credits,videos,release_dates,keywords",
        })
        if not details:
            return None
        if not details.get("overview"):
            english = self._request(f"/movie/{tmdb_id}", {"language": "en-US"}) or {}
            details["overview"] = english.get("overview", "")
        if "videos" in details and not self._movie_trailer(
            (details.get("videos") or {}).get("results") or []
        ):
            english_videos = self._request(
                f"/movie/{tmdb_id}/videos", {"language": "en-US"},
            ) or {}
            if english_videos.get("results"):
                details["videos"] = english_videos
        return details

    def movie_summary(self, title: str, year: str = "") -> Optional[dict]:
        """Schnelle Listenmetadaten mit nur einer TMDB-Suchanfrage."""
        query_title = _clean_movie_query_title(title)
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
                "genres": self._genre_names("movie", best.get("genre_ids") or []),
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

    def movie_summary_by_id(self, tmdb_id, title: str = "") -> Optional[dict]:
        """Schnelle, eindeutige Listenmetadaten über eine bekannte TMDB-ID."""
        key = str(tmdb_id or "").strip()
        if not key.isdigit():
            return None
        with self._lock:
            cached = self._movie_summary_id_cache.get(key)
            if cached is not None:
                return dict(cached)

        item = self._request(f"/movie/{key}", {"language": self.language})
        result = None
        if item:
            result = {
                "tmdb_id": int(key),
                "title": item.get("title") or title,
                "year": _year_from_date(item.get("release_date") or ""),
                "runtime": "",
                "cover_url": self._poster_url(item.get("poster_path") or ""),
                "backdrop_url": self._backdrop_url(item.get("backdrop_path") or ""),
                "description": item.get("overview") or "",
                "genres": [
                    str(genre.get("name") or "").strip()
                    for genre in item.get("genres") or []
                    if isinstance(genre, dict) and genre.get("name")
                ],
                "original_title": item.get("original_title") or "",
                "release_date": item.get("release_date") or "",
                "rating": round(float(item.get("vote_average") or 0), 1),
                "vote_count": int(item.get("vote_count") or 0),
                "details_loaded": False,
                "metadata_source": "TMDB",
            }
            with self._lock:
                self._movie_summary_id_cache[key] = dict(result)
        return result

    def now_playing_ids(self, force: bool = False) -> set[int]:
        """Aktuell im Kino laufende TMDB-Filme der konfigurierten Region."""
        now = time.time()
        with self._lock:
            cached_at, cached_ids = self._now_playing_cache
            if cached_ids and not force and now - cached_at < NOW_PLAYING_CACHE_TTL:
                return set(cached_ids)
        params = {
            "language": self.language,
            "region": self._preferred_region(),
            "page": "1",
        }
        response = self._request("/movie/now_playing", params) or {}
        pages = [response]
        page_count = min(3, max(1, int(response.get("total_pages") or 1)))
        if page_count > 1:
            with ThreadPoolExecutor(max_workers=page_count - 1) as pool:
                pages.extend(filter(None, pool.map(
                    lambda page: self._request(
                        "/movie/now_playing", {**params, "page": str(page)},
                    ),
                    range(2, page_count + 1),
                )))
        ids = {
            int(item["id"])
            for page in pages
            for item in page.get("results", [])
            if str(item.get("id") or "").isdigit()
        }
        with self._lock:
            self._now_playing_cache = (now, ids)
        return set(ids)

    def cached_now_playing_ids(self) -> set[int]:
        """Liefert Kinostatus nur aus dem Cache und blockiert keine Poster."""
        now = time.time()
        with self._lock:
            cached_at, cached_ids = self._now_playing_cache
            if now - cached_at < NOW_PLAYING_CACHE_TTL:
                return set(cached_ids)
        return set()

    def search_movies(self, query: str, max_results: int = 100) -> list[dict]:
        """Liefert die TMDB-Trefferauswahl vor jeder Anbietersuche.

        Mehrdeutige Begriffe wie ``Saw`` bleiben dadurch als einzelne Filme
        sichtbar. Erst der anschließend gewählte TMDB-Titel wird bei den
        aktivierten Streaming-Quellen gesucht.
        """
        query = " ".join(str(query or "").split()).strip()
        if not query or not self.configured:
            return []
        limit = max(1, min(int(max_results), 100))
        cache_key = (_normalize(query), limit)
        with self._lock:
            cached = self._movie_search_cache.get(cache_key)
            if cached is not None:
                return [dict(item) for item in cached]

        params = {
            "query": query,
            "language": self.language,
            "include_adult": "false",
            "page": "1",
        }
        first = self._request("/search/movie", params)
        if first is None:
            return []

        pages = [first]
        result_count = len(first.get("results") or [])
        total_pages = max(1, int(first.get("total_pages") or 1))
        wanted_pages = min(total_pages, max(1, (limit + 19) // 20))
        if wanted_pages > 1 and result_count < limit:
            def _page(number: int) -> Optional[dict]:
                return self._request("/search/movie", {**params, "page": str(number)})

            with ThreadPoolExecutor(max_workers=min(4, wanted_pages - 1)) as pool:
                pages.extend(
                    page for page in pool.map(_page, range(2, wanted_pages + 1))
                    if page is not None
                )

        results: list[dict] = []
        seen: set[int] = set()
        for page in pages:
            for item in page.get("results") or []:
                try:
                    tmdb_id = int(item.get("id"))
                except (TypeError, ValueError):
                    continue
                if tmdb_id in seen:
                    continue
                seen.add(tmdb_id)
                results.append({
                    "tmdb_id": tmdb_id,
                    "title": item.get("title") or item.get("original_title") or query,
                    "year": _year_from_date(item.get("release_date") or ""),
                    "cover_url": self._poster_url(item.get("poster_path") or ""),
                    "backdrop_url": self._backdrop_url(item.get("backdrop_path") or ""),
                    "description": item.get("overview") or "",
                    "genres": self._genre_names("movie", item.get("genre_ids") or []),
                    "original_title": item.get("original_title") or "",
                    "release_date": item.get("release_date") or "",
                    "rating": round(float(item.get("vote_average") or 0), 1),
                    "vote_count": int(item.get("vote_count") or 0),
                    "details_loaded": False,
                    "metadata_source": "TMDB",
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        with self._lock:
            self._movie_search_cache[cache_key] = [dict(item) for item in results]
        return results

    def movie(self, title: str, year: str = "") -> Optional[dict]:
        query_title = _clean_movie_query_title(title)
        cache_key = (_normalize(query_title), str(year or ""))
        with self._lock:
            if cache_key in self._movie_cache:
                return self._movie_cache[cache_key]

        summary = self.movie_summary(query_title, year)
        result = None
        if summary:
            details = self._movie_details(summary["tmdb_id"])
            result = self._movie_payload(
                details or summary, summary, summary["tmdb_id"], title,
                details_loaded=details is not None,
            )
        if result and result.get("details_loaded"):
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

        details = self._movie_details(key)
        result = None
        if details:
            result = self._movie_payload(
                details, {}, key, title, details_loaded=True,
            )
        if result is not None:
            with self._lock:
                self._movie_id_cache[key] = result
        return result

    def _series_payload(
        self, details: dict, fallback_title: str, tmdb_id, fetched_at: float,
    ) -> dict:
        runtimes = details.get("episode_run_time") or []
        runtime = runtimes[0] if runtimes else None
        trailer = self._movie_trailer(
            (details.get("videos") or {}).get("results") or []
        )
        return {
            "tmdb_id": int(tmdb_id),
            "title": details.get("name") or fallback_title,
            "original_title": details.get("original_name") or "",
            "year": _year_from_date(details.get("first_air_date") or ""),
            "first_air_date": str(details.get("first_air_date") or ""),
            "runtime": f"{runtime} min/Folge" if runtime else "",
            "cover_url": self._poster_url(details.get("poster_path") or ""),
            "backdrop_url": self._backdrop_url(details.get("backdrop_path") or ""),
            "description": details.get("overview") or "",
            "genres": [g.get("name", "") for g in details.get("genres", []) if g.get("name")],
            "rating": round(float(details.get("vote_average") or 0), 1),
            "vote_count": int(details.get("vote_count") or 0),
            "status": str(details.get("status") or ""),
            "creators": [
                creator.get("name", "")
                for creator in details.get("created_by", [])
                if creator.get("name")
            ],
            "networks": [
                network.get("name", "")
                for network in details.get("networks", [])
                if network.get("name")
            ],
            "cast": [
                {
                    "name": member.get("name", ""),
                    "character": member.get("character", ""),
                    "profile_url": self._profile_url(member.get("profile_path") or ""),
                }
                for member in (details.get("credits") or {}).get("cast", [])[:16]
                if member.get("name")
            ],
            "trailer": trailer,
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
        details = self._request(f"/tv/{key}", {
            "language": self.language,
            "append_to_response": "videos,credits",
        })
        result = None
        if details:
            if not details.get("overview"):
                english = self._request(f"/tv/{key}", {"language": "en-US"}) or {}
                details["overview"] = english.get("overview", "")
            if "videos" in details and not self._movie_trailer(
                (details.get("videos") or {}).get("results") or []
            ):
                english_videos = self._request(
                    f"/tv/{key}/videos", {"language": "en-US"},
                ) or {}
                if english_videos.get("results"):
                    details["videos"] = english_videos
            result = self._series_payload(details, title, key, now)
        with self._lock:
            self._series_id_cache[key] = (now, result)
        return result

    def series_summary(self, title: str, year: str = "") -> Optional[dict]:
        """Schnelle Serien-Listenmetadaten mit nur einer TMDB-Suchanfrage."""
        query_title = str(title or "").strip()
        cache_key = (_normalize(query_title), str(year or ""))
        with self._lock:
            if cache_key in self._series_summary_cache:
                return self._series_summary_cache[cache_key]

        params = {
            "query": query_title,
            "language": self.language,
            "include_adult": "false",
        }
        if year:
            params["first_air_date_year"] = str(year)
        search = self._request("/search/tv", params) or {}
        best = self._best_result(
            search.get("results", []), query_title, str(year or ""),
            ("name", "original_name"), "first_air_date",
        )
        if best is None and year:
            params.pop("first_air_date_year", None)
            search = self._request("/search/tv", params) or {}
            best = self._best_result(
                search.get("results", []), query_title, str(year),
                ("name", "original_name"), "first_air_date",
            )

        result = None
        if best:
            result = {
                "tmdb_id": best["id"],
                "title": best.get("name") or title,
                "original_title": best.get("original_name") or "",
                "year": _year_from_date(best.get("first_air_date") or ""),
                "first_air_date": best.get("first_air_date") or "",
                "cover_url": self._poster_url(best.get("poster_path") or ""),
                "backdrop_url": self._backdrop_url(best.get("backdrop_path") or ""),
                "description": best.get("overview") or "",
                "genres": self._genre_names("tv", best.get("genre_ids") or []),
                "rating": round(float(best.get("vote_average") or 0), 1),
                "vote_count": int(best.get("vote_count") or 0),
                "metadata_source": "TMDB",
            }
        if result is not None:
            with self._lock:
                self._series_summary_cache[cache_key] = result
        return result

    def season_air_dates(
        self, tmdb_id, season_number: int, force: bool = False,
    ) -> Optional[dict[int, str]]:
        """Liefert {episode_number: air_date} einer Staffel, oder ``None``
        wenn TMDB dazu nichts Verwertbares liefert (Aufrufer müssen das als
        "nicht prüfbar" behandeln, nicht als "nichts ist erschienen")."""
        key = (str(tmdb_id or "").strip(), int(season_number))
        if not key[0].isdigit():
            return None
        now = time.time()
        with self._lock:
            cached = self._season_cache.get(key)
            if cached:
                ttl = SERIES_CACHE_TTL if cached[1] is not None else SERIES_NEGATIVE_CACHE_TTL
                if not force and now - cached[0] < ttl:
                    return cached[1]
        details = self._request(
            f"/tv/{key[0]}/season/{key[1]}", {"language": self.language},
        )
        result = None
        if details and details.get("episodes"):
            result = {
                int(episode["episode_number"]): str(episode.get("air_date") or "")
                for episode in details["episodes"]
                if episode.get("episode_number") is not None
            }
        with self._lock:
            self._season_cache[key] = (now, result)
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
