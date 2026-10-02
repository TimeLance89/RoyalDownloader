"""Movie2k catalog and exact episode mirror selection."""

from __future__ import annotations

import base64
import logging
import re
from urllib.parse import quote, urljoin, urlparse

from providers.models import FilmpalastMovie, FilmpalastSearchResult, FilmpalastSeries, FilmpalastSeriesResult, SeriesEpisode, parse_episode_slug
from providers.sentinel_runtime import monitor_adapter
from providers.source_utils import CachedHTTP, hoster

BASE_URL = "https://movie2k.cx"
SOURCE_PREFIX = "movie2k:"
_MIRROR = re.compile(r"loadMirror\(['\"](https?://[^'\"]+)")
_EPISODE = re.compile(r"-s(\d+)e(\d+)-", re.I)


def _path(value):
    value = str(value or "").removeprefix(SOURCE_PREFIX)
    parsed = parse_episode_slug(value)
    if parsed:
        value = parsed[0]
    path = urlparse(value)
    return value if value.startswith("/stream/") and not path.netloc else ""


def _episode_number(value):
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4)).decode()
    except (ValueError, UnicodeError):
        return None
    match = _EPISODE.search(decoded)
    return (int(match[1]), int(match[2])) if match else None


@monitor_adapter("movie2k")
class Movie2kScraper:
    def __init__(self, progress_cb=None, health=None):
        self._log = progress_cb or logging.getLogger(__name__).info
        self.http = CachedHTTP("movie2k", health)
        self.session = self.http.session

    @staticmethod
    def probe_session():
        from curl_cffi import requests
        return requests.Session(impersonate="chrome")

    def _soup(self, path):
        self.http.session = self.session
        return self.http.soup(urljoin(BASE_URL, path))

    @staticmethod
    def _cards(soup):
        results, seen = [], set()
        for heading in soup.select("h2 a[href^='/stream/']"):
            path = heading.get("href", "")
            if path in seen:
                continue
            seen.add(path)
            title = re.sub(r"^\[SERIE\]\s*", "", heading.get_text(" ", strip=True))
            if not title:
                continue
            is_movie = not any(marker in path for marker in ("type=tv", "type=series"))
            parent = heading.find_parent("table") or heading.parent
            text = parent.get_text(" ", strip=True) if parent else ""
            year = re.search(r"\b(?:19|20)\d{2}\b", text)
            poster = parent.select_one("img[src]") if parent else None
            results.append(FilmpalastSearchResult(
                title=title, slug=SOURCE_PREFIX + path,
                url=urljoin(BASE_URL, path), year=year.group() if year else "",
                is_movie=is_movie, provider="movie2k", content_language="de",
                cover_url=urljoin(BASE_URL, poster["src"]) if poster else "",
            ))
        return results

    def search(self, query):
        return [x for x in self._cards(self._soup("/search?q=" + quote(query))) if x.is_movie]

    def search_series(self, query):
        return [self._series_result(x) for x in self._cards(self._soup("/search?q=" + quote(query))) if not x.is_movie]

    @staticmethod
    def _series_result(item):
        return FilmpalastSeriesResult(item.title, item.slug, item.slug, item.url, year=item.year)

    def list_movies(self, category="new", page=1):
        return [x for x in self._cards(self._soup(f"/movies?page={page}")) if x.is_movie]

    def list_series(self, page=1):
        return [self._series_result(x) for x in self._cards(self._soup(f"/tv/all?page={page}")) if not x.is_movie]

    def list_genres(self):
        return []

    def list_by_genre(self, genre, page=1):
        return []

    @staticmethod
    def _links(container):
        links, seen = [], set()
        for a in container.select("#tablemoviesindex2 a"):
            match = _MIRROR.search(a.get("onclick", ""))
            url = a.get("href", "") if a.get("href", "").startswith("http") else match.group(1) if match else ""
            if url in seen:
                continue
            candidate = hoster(url, "Deutsch" if container.select_one("img[src*='ger_flag']") else "")
            if candidate:
                image = a.select_one("img[alt*='HD'], img[alt*='SD'], img[alt*='CAM']")
                candidate.quality = image.get("alt", "") if image else ""
                links.append(candidate)
                seen.add(url)
        return links

    def get_series(self, value):
        path = _path(value)
        if not path:
            return None
        soup = self._soup(path)
        title = re.sub(r"\s*Qualität:.*$", "", soup.h1.get_text(" ", strip=True)).strip() if soup.h1 else ""
        seasons = {}
        for table in soup.select("table[data-episode-id]"):
            numbers = _episode_number(table.get("data-episode-id", ""))
            if not numbers or not self._links(table):
                continue
            season, episode = numbers
            seasons.setdefault(season, {})[episode] = SeriesEpisode(
                season, episode, f"{SOURCE_PREFIX}{path}-s{season:02d}e{episode:02d}",
                urljoin(BASE_URL, path),
            )
        return FilmpalastSeries(title, SOURCE_PREFIX + path, urljoin(BASE_URL, path),
            seasons={s: list(sorted(e.values(), key=lambda x: x.episode)) for s, e in seasons.items()}) if title and seasons else None

    def get_movie(self, value):
        path = _path(value)
        if not path:
            return None
        soup = self._soup(path)
        title = re.sub(r"\s*Qualität:.*$", "", soup.h1.get_text(" ", strip=True)).strip() if soup.h1 else ""
        if not title:
            return None
        parsed = parse_episode_slug(str(value).removeprefix(SOURCE_PREFIX))
        tables = soup.select("table[data-episode-id]")
        if parsed:
            selected = next((table for table in tables if _episode_number(table.get("data-episode-id", "")) == parsed[1:]), None)
            if selected is None:
                return None
            links = self._links(selected)
            title += f" S{parsed[1]:02d}E{parsed[2]:02d}"
        else:
            if tables:
                return None
            links = self._links(soup)
        match = re.search(r"Land/Jahr:\s*[^/\s]+\s*/\s*((?:19|20)\d{2})", soup.get_text(" ", strip=True))
        return FilmpalastMovie(title, urljoin(BASE_URL, path), year=match.group(1) if match else "", hosters=links,
            provider="movie2k", content_language="de") if links else None
