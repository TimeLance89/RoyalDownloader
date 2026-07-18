"""Scraper fuer filmfrei24.com – direkter Filmkatalog mit eigenen HLS-Streams.

FilmFrei24 unterscheidet sich von den anderen Katalogquellen:

* ``/api/films.php`` liefert den kompletten Filmkatalog als JSON.
* ``/api/availability.php`` markiert momentan abspielbare Titel.
* Die offizielle M3U-Liste nutzt ``/api/stream.php`` als HLS-Proxy.
* Die Katalogdaten enthalten zusaetzlich den direkten TV-HLS-Endpunkt.

Es gibt derzeit keinen Serienkatalog. Suche, Genre und Sortierung erfolgen
deshalb lokal auf dem kurzzeitig gecachten Gesamtkatalog.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from typing import Callable, List, Optional
from urllib.parse import parse_qs, quote, urlparse

from curl_cffi import requests as cr

from providers.models import FilmpalastMovie, FilmpalastSearchResult, HosterInfo


logger = logging.getLogger(__name__)

BASE_URL = "https://filmfrei24.com"
API_URL = f"{BASE_URL}/api"
SOURCE_PREFIX = "filmfrei24:"
CATALOG_CACHE_TTL = 5 * 60
AVAILABILITY_CACHE_TTL = 30

_cache_lock = threading.RLock()
_catalog_cache: List[dict] = []
_catalog_cache_until = 0.0
_availability_cache: dict[str, bool] = {}
_availability_cache_until = 0.0


def clear_cache() -> None:
    """Leert die Prozess-Caches (vor allem fuer Tests und manuelle Refreshes)."""
    global _catalog_cache, _catalog_cache_until
    global _availability_cache, _availability_cache_until
    with _cache_lock:
        _catalog_cache = []
        _catalog_cache_until = 0.0
        _availability_cache = {}
        _availability_cache_until = 0.0


class FilmFrei24Scraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.session = cr.Session(impersonate="chrome136")

    def search(self, query: str) -> List[FilmpalastSearchResult]:
        query_key = self._search_key(query)
        if not query_key:
            return []
        self._log(f"FilmFrei24 Suche: {query.strip()}")
        films = [
            film for film in self._catalog()
            if query_key in self._search_key(film.get("title"))
        ]
        results = [self._result_from_film(film) for film in films]
        self._log(f"  FilmFrei24: {len(results)} Treffer")
        return results

    def list_movies(
        self,
        category: str = "new",
        page: int = 1,
    ) -> List[FilmpalastSearchResult]:
        # Der Gesamtkatalog wird einmal geladen und vom Server ueber seine
        # globalen 32er-Seiten verteilt.
        if page != 1:
            return []
        self._log(f"FilmFrei24 Liste ({'top' if category == 'top' else 'neu'})")
        films = list(self._catalog())
        if category == "top":
            films.sort(
                key=lambda film: (
                    self._float(film.get("tmdb_rating")),
                    self._int(film.get("tmdb_votes")),
                    str(film.get("upload_date") or ""),
                ),
                reverse=True,
            )
        else:
            films.sort(
                key=lambda film: str(film.get("upload_date") or ""),
                reverse=True,
            )
        self._log(f"  FilmFrei24: {len(films)} Filme")
        return [self._result_from_film(film) for film in films]

    def list_genres(self) -> List[str]:
        genres = {
            " ".join(str(genre or "").split())
            for film in self._catalog()
            for genre in (film.get("genres") or [])
            if isinstance(genre, str) and genre.strip()
        }
        return sorted(genres, key=str.casefold)

    def list_by_genre(
        self,
        genre: str,
        page: int = 1,
    ) -> List[FilmpalastSearchResult]:
        if page != 1:
            return []
        genre_key = " ".join(str(genre or "").split()).casefold()
        if not genre_key:
            return []
        self._log(f"FilmFrei24 Genre: {genre}")
        films = [
            film for film in self._catalog()
            if any(
                " ".join(str(item or "").split()).casefold() == genre_key
                for item in (film.get("genres") or [])
            )
        ]
        films.sort(
            key=lambda film: str(film.get("upload_date") or ""),
            reverse=True,
        )
        return [self._result_from_film(film) for film in films]

    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        film = self._find_film(url_or_slug)
        if not film:
            return None

        title = str(film.get("title") or "").strip()
        site_slug = self._site_slug(title)
        if not site_slug:
            return None

        availability = self._availability()
        if availability.get(site_slug) is False:
            self._log(f"  FilmFrei24 momentan nicht verfügbar: {title}")
            return None

        player_url = f"{BASE_URL}/player/?s={quote(site_slug, safe='')}"
        proxy_url = (
            f"{API_URL}/stream.php?film={quote(site_slug, safe='')}"
            "&file=playlist.m3u8"
        )
        language = str(film.get("language") or "Deutsch")
        quality = str(film.get("quality") or "HD")
        hosters = [
            HosterInfo(
                name="FilmFrei24",
                url=proxy_url,
                language=language,
                quality=quality,
            ),
        ]

        direct_url = str(film.get("video") or "").strip()
        direct = urlparse(direct_url)
        if (
            direct.scheme == "https"
            and direct.hostname == "tv.filmfrei24.com"
            and direct_url != proxy_url
        ):
            hosters.append(HosterInfo(
                name="FilmFrei24 Direct",
                url=direct_url,
                language=language,
                quality=quality,
            ))

        return FilmpalastMovie(
            title=title or "Unbekannt",
            url=player_url,
            year=self._year(film.get("year")),
            runtime=str(film.get("duration") or ""),
            cover_url=str(film.get("thumbnail") or ""),
            description=str(film.get("description") or ""),
            genres=[
                str(genre).strip()
                for genre in (film.get("genres") or [])
                if str(genre).strip()
            ],
            hosters=hosters,
        )

    # FilmFrei24 bietet aktuell keine Serien an.
    def search_series(self, query: str) -> List:
        return []

    def list_series(self, page: int = 1) -> List:
        return []

    def _catalog(self) -> List[dict]:
        global _catalog_cache, _catalog_cache_until
        now = time.monotonic()
        with _cache_lock:
            if _catalog_cache and now < _catalog_cache_until:
                return list(_catalog_cache)
            films = self._load_catalog()
            normalized = [
                film for film in films
                if isinstance(film, dict) and film.get("id") and film.get("title")
            ]
            if not normalized:
                raise RuntimeError("FilmFrei24 Katalog ist leer")
            _catalog_cache = normalized
            _catalog_cache_until = time.monotonic() + CATALOG_CACHE_TTL
            return list(_catalog_cache)

    def _load_catalog(self) -> List[dict]:
        try:
            data = self._get_json(f"{API_URL}/films.php")
            if isinstance(data, list):
                return data
            raise RuntimeError("FilmFrei24 Film-API lieferte keine Liste")
        except Exception as api_exc:
            # Die Startseite enthaelt denselben Katalog als ALL_FILMS. Damit
            # bleibt der Anbieter bei einem isolierten API-Fehler nutzbar.
            self._log(f"  FilmFrei24 API-Fallback auf Startseite: {api_exc}")
            response = self.session.get(
                f"{BASE_URL}/",
                timeout=25,
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            )
            response.raise_for_status()
            marker = re.search(r"\bconst\s+ALL_FILMS\s*=\s*", response.text)
            if not marker:
                raise RuntimeError("FilmFrei24 Katalog fehlt") from api_exc
            data, _end = json.JSONDecoder().raw_decode(response.text[marker.end():])
            if not isinstance(data, list):
                raise RuntimeError("FilmFrei24 Seitenkatalog ist ungültig") from api_exc
            return data

    def _availability(self) -> dict[str, bool]:
        global _availability_cache, _availability_cache_until
        now = time.monotonic()
        with _cache_lock:
            if now < _availability_cache_until:
                return dict(_availability_cache)
            try:
                data = self._get_json(f"{API_URL}/availability.php")
                results = data.get("results", {}) if isinstance(data, dict) else {}
                if not isinstance(results, dict):
                    raise RuntimeError("ungültige Antwort")
            except Exception as exc:
                # Unbekannt ist nicht gleich gesperrt. Die HLS-Probe der
                # Download-Pipeline entscheidet anschließend verbindlich. Der
                # kurze Fehlercache verhindert einen API-Sturm bei großen Queues.
                self._log(f"  FilmFrei24 Verfügbarkeit nicht prüfbar: {exc}")
                _availability_cache = {}
                _availability_cache_until = (
                    time.monotonic() + min(10, AVAILABILITY_CACHE_TTL)
                )
                return {}
            _availability_cache = {
                str(slug): bool(available)
                for slug, available in results.items()
            }
            _availability_cache_until = time.monotonic() + AVAILABILITY_CACHE_TTL
            return dict(_availability_cache)

    def _get_json(self, url: str):
        response = self.session.get(
            url,
            timeout=25,
            headers={
                "Accept": "application/json",
                "Referer": f"{BASE_URL}/",
            },
        )
        response.raise_for_status()
        return response.json()

    def _find_film(self, value: str) -> Optional[dict]:
        raw = str(value or "").strip()
        movie_id = self._movie_id(raw)
        requested_slug = self._slug_from_value(raw)
        for film in self._catalog():
            if movie_id is not None and str(film.get("id")) == movie_id:
                return film
            if requested_slug and self._site_slug(film.get("title")) == requested_slug:
                return film
        return None

    def _result_from_film(self, film: dict) -> FilmpalastSearchResult:
        movie_id = str(film.get("id"))
        title = str(film.get("title") or movie_id).strip()
        site_slug = self._site_slug(title)
        return FilmpalastSearchResult(
            title=f"{title}  [FilmFrei24]",
            slug=f"{SOURCE_PREFIX}{movie_id}:{site_slug}",
            url=f"{BASE_URL}/player/?s={quote(site_slug, safe='')}",
            year=self._year(film.get("year")),
            is_movie=True,
        )

    @staticmethod
    def _movie_id(value: str) -> Optional[str]:
        if value.startswith(SOURCE_PREFIX):
            value = value[len(SOURCE_PREFIX):]
            candidate = value.split(":", 1)[0]
            return candidate if candidate.isdigit() else None
        return None

    @staticmethod
    def _slug_from_value(value: str) -> str:
        if value.startswith(SOURCE_PREFIX):
            payload = value[len(SOURCE_PREFIX):]
            if ":" in payload:
                return payload.split(":", 1)[1]
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        return str((query.get("s") or query.get("film") or [""])[0])

    @staticmethod
    def _site_slug(title) -> str:
        # Exakt dieselbe Regel wie makeSlug() auf filmfrei24.com.
        return re.sub(r"[^a-zA-Z0-9]", "", str(title or ""))

    @staticmethod
    def _search_key(value) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(char for char in normalized if char.isalnum())

    @staticmethod
    def _year(value) -> str:
        match = re.search(r"\b(?:19|20)\d{2}\b", str(value or ""))
        return match.group(0) if match else ""

    @staticmethod
    def _float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
