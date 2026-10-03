"""KinoKing adapter using typed cards and explicit episode JSON."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
from providers.sentinel_runtime import monitor_adapter
from providers.source_utils import hoster as identify_hoster

from providers.models import (
    FilmpalastMovie,
    FilmpalastSearchResult,
    FilmpalastSeries,
    FilmpalastSeriesResult,
    SeriesEpisode,
    parse_episode_slug,
)

BASE_URL = "https://kinoking.cc"
SOURCE_PREFIX = "kinoking:"
_CACHE: dict[str, tuple[float, BeautifulSoup]] = {}
_SESSION = requests.Session(impersonate="chrome136")
_LOCK = threading.RLock()
_LAST_REQUEST = 0.0
_BLOCKED_UNTIL = 0.0
_JSON = json.JSONDecoder()
logger = logging.getLogger(__name__)


def _identity(value: str) -> str:
    value = str(value or "")
    value = value.removeprefix(SOURCE_PREFIX)
    parsed = parse_episode_slug(value)
    if parsed:
        value = parsed[0]
    if value.startswith("http"):
        value = parse_qs(urlparse(value).query).get("id", [""])[0]
    return value if value.isdigit() else ""


def _json_after(text: str, marker: str):
    offset = text.find(marker)
    if offset < 0:
        return None
    try:
        return _JSON.raw_decode(text[offset + len(marker):].lstrip())[0]
    except (ValueError, TypeError):
        return None


@monitor_adapter("kinoking")
class KinoKingScraper:
    def __init__(self, progress_cb=None, health=None):
        self._log = progress_cb or logger.info
        self._health = health
        self.session = _SESSION

    @staticmethod
    def probe_session():
        return requests.Session(impersonate="chrome136")

    def _request(self, path: str) -> BeautifulSoup:
        global _LAST_REQUEST, _BLOCKED_UNTIL
        probe = False
        if self._health is not None:
            status = self._health.status("kinoking")
            if status["state"] != "healthy":
                if status["remaining_seconds"] or not self._health.begin_probe("kinoking"):
                    raise RuntimeError("KinoKing im Provider-Cooldown")
                probe = True
        with _LOCK:
            now = time.monotonic()
            if self._health is None and now < _BLOCKED_UNTIL:
                raise RuntimeError("KinoKing im Cooldown")
            cached = _CACHE.get(path)
            if cached and cached[0] > now and not probe:
                return cached[1]
            delay = 0.8 - (now - _LAST_REQUEST)
            if delay > 0:
                time.sleep(delay)
            failure_reason = "transient_failure"
            try:
                response = self.session.get(urljoin(BASE_URL, path), timeout=20)
                _LAST_REQUEST = time.monotonic()
                if response.status_code in (403, 429, 503) or any(
                    marker in response.text.casefold()
                    for marker in ("captcha challenge", "cloudflare challenge", "too many requests")
                ):
                    failure_reason = "rate_limit" if response.status_code == 429 else "access_blocked"
                    _BLOCKED_UNTIL = time.monotonic() + 15 * 60
                    raise RuntimeError("KinoKing blockiert oder limitiert")
                if response.status_code == 404:
                    failure_reason = "unavailable"
                response.raise_for_status()
                soup = BeautifulSoup(response.content, "lxml")
                _CACHE[path] = (time.monotonic() + 900, soup)
                if probe:
                    self._health.mark_success("kinoking")
                return soup
            except Exception as exc:
                _BLOCKED_UNTIL = max(_BLOCKED_UNTIL, time.monotonic() + 15 * 60)
                if self._health is not None:
                    self._health.mark_blocked("kinoking", failure_reason, str(exc))
                raise

    @staticmethod
    def _cards(soup: BeautifulSoup):
        found = []
        seen = set()
        for card in soup.select(".fav-data-source[data-id][data-type]"):
            identity = card.get("data-id", "")
            kind = card.get("data-type", "")
            if not identity.isdigit() or kind not in ("movie", "series") or (kind, identity) in seen:
                continue
            seen.add((kind, identity))
            title = card.get("data-title", "").strip()
            if not title:
                continue
            text = card.get_text(" ", strip=True)
            year = (re.search(r"\b(?:19|20)\d{2}\b", text) or re.search(r"\b(?:19|20)\d{2}\b", title))
            image = card.get("data-img", "")
            found.append(FilmpalastSearchResult(
                title=title, slug=SOURCE_PREFIX + identity,
                url=f"{BASE_URL}/{kind}.php?id={identity}",
                year=year.group(0) if year else "", is_movie=kind == "movie",
                provider="kinoking", content_language="de", cover_url=image,
                tmdb_id=card.get("data-tmdb", ""),
            ))
        return found

    def _search(self, query: str):
        query = " ".join(str(query or "").split())
        if not query:
            return []
        from urllib.parse import urlencode
        return self._cards(self._request("/index.php?" + urlencode({"search": query})))

    def search(self, query: str):
        return [item for item in self._search(query) if item.is_movie]

    def search_series(self, query: str):
        return [FilmpalastSeriesResult(
            title=item.title, base_slug=item.slug, sample_slug=item.slug,
            sample_url=item.url, year=item.year, cover_url=item.cover_url,
            tmdb_id=item.tmdb_id,
        ) for item in self._search(query) if not item.is_movie]

    def list_movies(self, category="new", page=1):
        from urllib.parse import urlencode
        genre = "top10-movies" if category == "top" else "current-movies"
        return [item for item in self._cards(self._request("/index.php?" + urlencode({"genre": genre, "page": page}))) if item.is_movie]

    def list_series(self, page=1):
        from urllib.parse import urlencode
        return [FilmpalastSeriesResult(
            title=item.title, base_slug=item.slug, sample_slug=item.slug,
            sample_url=item.url, year=item.year, cover_url=item.cover_url,
            tmdb_id=item.tmdb_id,
        ) for item in self._cards(self._request("/index.php?" + urlencode({"genre": "current-series", "page": page}))) if not item.is_movie]

    def list_genres(self):
        return []

    def list_by_genre(self, genre, page=1):
        return []

    @staticmethod
    def _title_year(soup: BeautifulSoup):
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        match = re.match(r"(.+?)\s*\(((?:19|20)\d{2})\)", title)
        return (match.group(1).strip(), match.group(2)) if match else ("", "")

    def _series_rows(self, identity: str):
        soup = self._request(f"/series.php?id={identity}")
        script = "\n".join(tag.string or tag.get_text() for tag in soup.find_all("script"))
        rows = _json_after(script, "const allEpisodesData = ")
        return soup, rows if isinstance(rows, list) else []

    def get_series(self, value: str):
        identity = _identity(value)
        if not identity:
            return None
        soup, rows = self._series_rows(identity)
        title, _year = self._title_year(soup)
        if not title or not rows:
            return None
        seasons = {}
        for row in rows:
            try:
                season = int(row["season_number"])
                episode = int(row["episode_number"])
            except (KeyError, TypeError, ValueError):
                continue
            if season < 1 or episode < 1 or not str(row.get("video_links") or "").strip():
                continue
            seasons.setdefault(season, []).append(SeriesEpisode(
                season=season, episode=episode,
                slug=f"{SOURCE_PREFIX}{identity}-s{season:02d}e{episode:02d}",
                url=f"{BASE_URL}/series.php?id={identity}&season={season}#episode-{row.get('id', '')}",
                release_name=str(row.get("name") or ""),
                release_at=str(row.get("air_date") or ""),
            ))
        for episodes in seasons.values():
            episodes.sort(key=lambda item: item.episode)
        return FilmpalastSeries(
            title=title, base_slug=SOURCE_PREFIX + identity,
            url=f"{BASE_URL}/series.php?id={identity}", seasons=seasons,
        ) if seasons else None

    @staticmethod
    def _hosters(urls, language=""):
        hosters = []
        seen = set()
        for raw in urls:
            url = str(raw or "").strip()
            if url in seen:
                continue
            candidate = identify_hoster(url, language)
            if not candidate:
                continue
            seen.add(url)
            hosters.append(candidate)
        return hosters

    def get_movie(self, value: str):
        identity = _identity(value)
        if not identity:
            return None
        raw = value.removeprefix(SOURCE_PREFIX)
        parsed = parse_episode_slug(raw)
        if parsed:
            _soup, rows = self._series_rows(identity)
            season, episode = parsed[1:]
            row = next((item for item in rows if str(item.get("season_number")) == str(season) and str(item.get("episode_number")) == str(episode)), None)
            if not row:
                return None
            links = re.split(r"[,\n]+", str(row.get("video_links") or ""))
            hosters = self._hosters(links)
            if not hosters:
                return None
            return FilmpalastMovie(
                title=f"{self._title_year(_soup)[0]} S{season:02d}E{episode:02d}",
                url=f"{BASE_URL}/series.php?id={identity}&season={season}#episode-{row.get('id', '')}",
                hosters=hosters, provider="kinoking", content_language="de",
            )
        soup = self._request(f"/movie.php?id={identity}")
        title, year = self._title_year(soup)
        script = "\n".join(tag.string or tag.get_text() for tag in soup.find_all("script"))
        servers = _json_after(script, "const SERVERS = ")
        if not isinstance(servers, list):
            return None
        hosters = []
        seen = set()
        for server in servers:
            if not isinstance(server, dict):
                continue
            language_match = re.search(r"\((DE|EN|ES|FR)\)", server.get("name", ""), re.IGNORECASE)
            language = {"DE": "Deutsch", "EN": "English", "ES": "Español", "FR": "Français"}.get(language_match.group(1).upper(), "") if language_match else ""
            for candidate in self._hosters(server.get("mirrors") or [], language):
                if candidate.url not in seen:
                    seen.add(candidate.url)
                    hosters.append(candidate)
        return FilmpalastMovie(
            title=title, url=f"{BASE_URL}/movie.php?id={identity}", year=year,
            hosters=hosters, provider="kinoking", content_language="de",
        ) if title and hosters else None
