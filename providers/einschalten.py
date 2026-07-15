"""
Scraper fuer einschalten.in – Backup-Provider, nur Filme (keine Serien).

Angular-SSR-Seite mit TMDB-IDs. Alle Daten kommen sauber ueber eine JSON-API,
kein HTML-Parsing noetig:

  POST /api/search           {"query": "..."}      -> Titel-Treffer
  GET  /api/movies                                  -> "neu" sortierte Liste
  GET  /api/movies?genreId=<id>                      -> nach Genre gefiltert
  GET  /api/movies/<id>                              -> Metadaten
  GET  /api/movies/<id>/watch                        -> {releaseName, streamUrl}

Jeder Film hat genau EINEN Hoster (aktuell immer vide0.net, ein DoodStream-
Rebrand). Die eigentliche Stream-Extraktion laeuft ueber
extractor.extract_doodstream_url().
"""

import logging
import re
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

from curl_cffi import requests as cr

from providers.models import (
    FilmpalastMovie,
    FilmpalastSearchResult,
    HosterInfo,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://einschalten.in"
API_URL = f"{BASE_URL}/api"
SOURCE_PREFIX = "einschalten:"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


class EinschaltenScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.session = cr.Session(impersonate="chrome136")
        self._genre_ids: Optional[Dict[str, int]] = None

    # ------------------------------------------------------------------
    def search(self, query: str) -> List[FilmpalastSearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        self._log(f"Einschalten Suche: {query}")
        resp = self.session.post(
            f"{API_URL}/search", json={"query": query}, timeout=25,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        titles = resp.json().get("data", [])
        results = [self._result_from_title(t) for t in titles]
        self._log(f"  Einschalten: {len(results)} Treffer")
        return results

    def list_movies(self, category: str = "new", page: int = 1) -> List[FilmpalastSearchResult]:
        if page != 1:
            return []
        self._log("Einschalten Liste (neu)")
        data = self._get_json(f"{API_URL}/movies")
        titles = data.get("data", [])
        return [self._result_from_title(t) for t in titles]

    def list_genres(self) -> List[str]:
        genres = self._load_genres()
        return list(genres.keys())

    def list_by_genre(self, genre: str, page: int = 1) -> List[FilmpalastSearchResult]:
        if page != 1:
            return []
        genre = (genre or "").strip()
        genres = self._load_genres()
        genre_id = genres.get(genre)
        if genre_id is None:
            return []
        self._log(f"Einschalten Genre: {genre}")
        data = self._get_json(f"{API_URL}/movies", params={"genreId": genre_id})
        titles = data.get("data", [])
        return [self._result_from_title(t) for t in titles]

    # ------------------------------------------------------------------
    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        movie_id = self._movie_id(url_or_slug)
        if movie_id is None:
            return None
        self._log(f"Lade Film (Einschalten): {movie_id}")
        try:
            detail = self._get_json(f"{API_URL}/movies/{movie_id}")
            watch = self._get_json(f"{API_URL}/movies/{movie_id}/watch")
        except Exception as exc:
            self._log(f"  Einschalten-Film nicht ladbar: {exc}", )
            return None

        stream_url = watch.get("streamUrl") or ""
        hosters: List[HosterInfo] = []
        if stream_url:
            hosters.append(HosterInfo(name=self._hoster_name(stream_url), url=stream_url))
        if not hosters:
            self._log("  Kein Hoster verfuegbar.")
            return None

        genres = [g["name"] for g in detail.get("genres") or [] if isinstance(g, dict) and g.get("name")]
        poster = detail.get("posterPath") or ""

        return FilmpalastMovie(
            title=detail.get("title") or "Unbekannt",
            url=f"{BASE_URL}/movies/{movie_id}",
            year=self._year(detail.get("releaseDate")),
            runtime=f"{detail['runtime']} min" if detail.get("runtime") else "",
            cover_url=f"{TMDB_IMAGE_BASE}{poster}" if poster else "",
            description=detail.get("overview") or "",
            genres=genres,
            hosters=hosters,
        )

    # ------------------------------------------------------------------
    # Keine Serien auf einschalten.in
    # ------------------------------------------------------------------
    def search_series(self, query: str) -> List:
        return []

    def list_series(self, page: int = 1) -> List:
        return []

    # ------------------------------------------------------------------
    def _load_genres(self) -> Dict[str, int]:
        if self._genre_ids is None:
            data = self._get_json(f"{API_URL}/genres")
            self._genre_ids = {
                g["name"]: g["id"] for g in data if isinstance(g, dict) and g.get("name") and g.get("id") is not None
            }
        return self._genre_ids

    def _get_json(self, url: str, params: Optional[dict] = None) -> dict:
        resp = self.session.get(
            url, params=params, timeout=25, headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    def _result_from_title(self, title: dict) -> FilmpalastSearchResult:
        movie_id = title["id"]
        name = title.get("title") or str(movie_id)
        return FilmpalastSearchResult(
            title=f"{name}  [Einschalten]",
            slug=f"{SOURCE_PREFIX}{movie_id}",
            url=f"{BASE_URL}/movies/{movie_id}",
            year=self._year(title.get("releaseDate")),
            is_movie=True,
        )

    def _movie_id(self, value: str) -> Optional[int]:
        value = str(value or "")
        if value.startswith(SOURCE_PREFIX):
            value = value[len(SOURCE_PREFIX):]
        m = re.search(r"(?:movies/)?(\d+)", value)
        return int(m.group(1)) if m else None

    @staticmethod
    def _year(value) -> str:
        m = re.search(r"\b(19|20)\d{2}\b", str(value or ""))
        return m.group(0) if m else ""

    @staticmethod
    def _hoster_name(url: str) -> str:
        low = (url or "").lower()
        if "vide0" in low or "dood" in low:
            return "Doodstream"
        return "Einschalten"
