"""One DeVideoSRC-backed catalog with mirror failover."""

from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import quote, unquote, urljoin, urlparse

from providers.models import FilmpalastMovie, FilmpalastSearchResult, FilmpalastSeries, FilmpalastSeriesResult, SeriesEpisode, parse_episode_slug
from providers.sentinel_runtime import monitor_adapter
from providers.source_utils import CachedHTTP, hoster

SOURCE_PREFIX = "hdfilme_family:"
MIRRORS = ("https://hdfilme.ceo", "https://streamcloud.download", "https://streamkiste.bid")
_ID = re.compile(r"(?:/|:)(\d+)-")
_IMDB = re.compile(r"(?:var\s+imdb\s*=\s*['\"]|devideosrc\.co/(?:movie|serial|embed/download)/)(tt\d+)", re.I)
_TOKEN = re.compile(r"token:\s*['\"]([A-Za-z0-9_.=-]+)")
_CACHE: dict[str, tuple[float, dict]] = {}
_PATHS: dict[str, str] = {}
_LOCK = threading.RLock()


def _identity(value):
    value = str(value or "").removeprefix(SOURCE_PREFIX)
    parsed = parse_episode_slug(value)
    if parsed:
        value = parsed[0]
    match = _ID.search("/" + value)
    return match.group(1) if match else ""


@monitor_adapter("hdfilme_family")
class HDFilmeFamilyScraper:
    def __init__(self, progress_cb=None, health=None):
        self._log = progress_cb or logging.getLogger(__name__).info
        # A single dead mirror must not cool down the entire logical provider.
        self.http = CachedHTTP("hdfilme_family", None)
        self.session = self.http.session
        self._preferred = 0

    @staticmethod
    def probe_session():
        from curl_cffi import requests
        return requests.Session(impersonate="chrome")

    def _soup(self, url):
        self.http.session = self.session
        return self.http.soup(url)

    @staticmethod
    def _cards(soup):
        results, seen = [], set()
        for anchor in soup.select("a.movie-title, .item-video .f_title a, .movie-preview .movie-title a, .movie-preview h2 a, .movie-preview h3 a"):
            url = anchor.get("href", "")
            match = _ID.search(url)
            if not match or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            if not title:
                continue
            card = anchor.find_parent(class_=re.compile(r"\b(?:item|movie-preview)\b")) or anchor.parent
            text = card.get_text(" ", strip=True)
            year = re.search(r"\b(?:19|20)\d{2}\b", text)
            # Series are signalled by site path or category badges. A detail
            # verification below is still required before episode use.
            is_series = "/serien/" in url or bool(re.search(r"\bSerien?\b", text, re.I))
            slug = SOURCE_PREFIX + match.group(1) + "-" + quote(title, safe="")
            _PATHS[match.group(1)] = url
            image = card.select_one("img[src], img[data-src]")
            results.append(FilmpalastSearchResult(
                title, slug, url, year=year.group() if year else "", is_movie=not is_series,
                provider="hdfilme_family", content_language="de",
                cover_url=urljoin(url, image.get("src") or image.get("data-src")) if image else "",
            ))
        return results

    def _search(self, query, skip=()):
        # One successful backend answers the family-wide search. Others are
        # contacted only after transport or parser failure.
        errors = []
        for index in (self._preferred, *(i for i in range(len(MIRRORS)) if i != self._preferred)):
            if index in skip:
                continue
            base = MIRRORS[index]
            path = "/?story=" + quote(query) + "&do=search&subaction=search"
            try:
                soup = self._soup(base + path)
                results = self._cards(soup)
                if results:
                    self._preferred = index
                    return results
                if soup.title and "search" in soup.title.get_text(" ", strip=True).casefold():
                    self._preferred = index
                    return []
                errors.append(f"{base}: no cards")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
        self._log("HDFilme-Suche: " + "; ".join(errors))
        return []

    def search(self, query):
        return self._search(query)

    def search_series(self, query):
        wanted = " ".join(str(query or "").split()).casefold()
        # DLE search cards carry no reliable media-type flag. Verify exact
        # candidates through the serial player before publishing TV results.
        results = []
        for item in self._search(query):
            if item.title.casefold() != wanted:
                continue
            try:
                detail = self._soup(item.url)
                if "devideosrc.co/serial/" in str(detail) and _IMDB.search(str(detail)):
                    results.append(self._series_result(item))
            except Exception:
                continue
        return results

    @staticmethod
    def _series_result(item):
        return FilmpalastSeriesResult(item.title, item.slug, item.slug, item.url, year=item.year)

    def list_movies(self, category="new", page=1):
        return [x for x in self._cards(self._soup(MIRRORS[self._preferred] + f"/filme1/page/{page}/")) if x.is_movie]

    def list_series(self, page=1):
        return [self._series_result(x) for x in self._cards(self._soup(MIRRORS[self._preferred] + f"/serien/page/{page}/")) if not x.is_movie]

    def list_genres(self):
        return []

    def list_by_genre(self, genre, page=1):
        return []

    def _detail(self, value):
        identity = _identity(value)
        if not identity:
            return None
        url = _PATHS.get(identity)
        if url:
            try:
                page = self._soup(url)
                if page.h1 and _IMDB.search(str(page)):
                    return page, url
            except Exception:
                pass
        # A mirrored detail may use a different path template. Search once
        # on the currently healthy mirror and match the stable numeric ID.
        title = unquote(str(value).removeprefix(SOURCE_PREFIX).split("-", 1)[-1])
        skip = tuple(i for i, base in enumerate(MIRRORS) if url and url.startswith(base))
        for result in self._search(title, skip=skip):
            if _identity(result.slug) == identity:
                return self._soup(result.url), result.url
        return None

    def _player(self, soup, kind):
        match = _IMDB.search(str(soup))
        if not match:
            return None
        imdb = match.group(1)
        key = f"{kind}:{imdb}"
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        url = f"https://devideosrc.co/{'movie' if kind == 'movie' else 'serial'}/{imdb}?r={time.monotonic_ns()}"
        response = self.session.get(url, timeout=12)
        response.raise_for_status()
        token = _TOKEN.search(response.text)
        if not token:
            return None
        response = self.session.post("https://devideosrc.co/api/embed-links",
            json={"type": kind, "id": imdb, "token": token.group(1)}, timeout=12)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok") is not True or payload.get("type") != kind:
            return None
        with _LOCK:
            _CACHE[key] = (time.monotonic() + 300, payload)
        return payload

    @staticmethod
    def _hosters(sources):
        seen, result = set(), []
        for source in sorted((x for x in sources if isinstance(x, dict)), key=lambda x: x.get("rank", 99)):
            item = hoster(source.get("url", ""), label=str(source.get("name", "")).split(".")[0])
            if item and item.url not in seen:
                result.append(item)
                seen.add(item.url)
        return result

    @staticmethod
    def _title_year(soup):
        metadata = soup.find("meta", attrs={"property": "og:title"})
        raw = metadata.get("content", "") if metadata else ""
        if not raw and soup.title:
            raw = soup.title.get_text(" ", strip=True)
        match = re.match(r"(.+?)\s*\(((?:19|20)\d{2})\)", raw)
        if match:
            return match.group(1).strip(), match.group(2)
        return (soup.h1.get_text(" ", strip=True), "") if soup.h1 else ("", "")

    def get_series(self, value):
        detail = self._detail(value)
        if not detail:
            return None
        soup, url = detail
        payload = self._player(soup, "tv")
        if not payload:
            return None
        title, _year = self._title_year(soup)
        seasons = {}
        for row in payload.get("tv", {}).get("seasons", []):
            try:
                season = int(row["season_number"])
            except (ValueError, TypeError, KeyError):
                continue
            episodes = []
            for episode_row in row.get("episodes", []):
                try:
                    episode = int(episode_row["episode_number"])
                except (ValueError, TypeError, KeyError):
                    continue
                if self._hosters(episode_row.get("sources", [])):
                    episodes.append(SeriesEpisode(season, episode,
                        f"{SOURCE_PREFIX}{str(value).removeprefix(SOURCE_PREFIX).split('-s', 1)[0]}-s{season:02d}e{episode:02d}",
                        url, release_name=episode_row.get("title", "")))
            if episodes:
                seasons[season] = sorted(episodes, key=lambda x: x.episode)
        return FilmpalastSeries(title, SOURCE_PREFIX + str(value).removeprefix(SOURCE_PREFIX), url,
            seasons=seasons) if title and seasons else None

    def get_movie(self, value):
        detail = self._detail(value)
        if not detail:
            return None
        soup, url = detail
        parsed = parse_episode_slug(str(value).removeprefix(SOURCE_PREFIX))
        kind = "tv" if parsed else "movie"
        payload = self._player(soup, kind)
        if not payload:
            return None
        if parsed:
            source_rows = []
            for season in payload.get("tv", {}).get("seasons", []):
                if str(season.get("season_number")) != str(parsed[1]):
                    continue
                source_rows = [ep.get("sources", []) for ep in season.get("episodes", [])
                    if str(ep.get("episode_number")) == str(parsed[2])]
            sources = source_rows[0] if len(source_rows) == 1 else []
        else:
            sources = payload.get("sources", [])
        links = self._hosters(sources)
        title, year = self._title_year(soup)
        if parsed:
            title += f" S{parsed[1]:02d}E{parsed[2]:02d}"
        return FilmpalastMovie(title, url, year=year, hosters=links,
            provider="hdfilme_family", content_language="de") if title and links else None
