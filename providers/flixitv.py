"""FlixiTV catalog adapter. Requests are paced per provider and cached."""

from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from providers.models import (
    FilmpalastMovie,
    FilmpalastSearchResult,
    FilmpalastSeries,
    FilmpalastSeriesResult,
    HosterInfo,
    SeriesEpisode,
    parse_episode_slug,
)

BASE_URL = "https://flixitv-stream.eu"
SOURCE_PREFIX = "flixitv:"
_YEAR = re.compile(r"\s*\((\d{4})(?:\s*[-–]\s*\d{4})?\)\s*$")
_ID = re.compile(r"^[A-Za-z0-9]{11}$")
_SESSION = requests.Session()
_lock = threading.RLock()
_last_request = 0.0
_blocked_until = 0.0
_cache: dict[tuple, tuple[float, object]] = {}
logger = logging.getLogger(__name__)


def _title_year(value: str) -> tuple[str, str]:
    title = " ".join(value.split())
    match = _YEAR.search(title)
    return (_YEAR.sub("", title).strip(), match.group(1) if match else "")


def _identity(value: str) -> str:
    value = str(value or "")
    value = value.removeprefix(SOURCE_PREFIX)
    parsed = parse_episode_slug(value)
    if parsed:
        value = parsed[0]
    if value.startswith(("http", "/")):
        value = parse_qs(urlparse(value).query).get("v", [""])[0]
    return value if _ID.fullmatch(value) else ""


class FlixiTVScraper:
    def __init__(self, progress_cb=None, health=None):
        self._log = progress_cb or logger.info
        self._health = health

    def _request(self, path: str, *, query: str = "") -> BeautifulSoup:
        global _last_request, _blocked_until
        probe = False
        if self._health is not None:
            status = self._health.status("flixitv")
            if status["state"] != "healthy":
                if status["remaining_seconds"] or not self._health.begin_probe("flixitv"):
                    raise RuntimeError("FlixiTV im Provider-Cooldown")
                probe = True
        key = (path, query)
        with _lock:
            now = time.monotonic()
            if self._health is None and now < _blocked_until:
                raise RuntimeError("FlixiTV im Cooldown")
            cached = _cache.get(key)
            if cached and cached[0] > now and not probe:
                return cached[1]
            delay = 1.25 - (now - _last_request)
            if delay > 0:
                time.sleep(delay)
            failure_reason = "transient_failure"
            try:
                response = (_SESSION.post if query else _SESSION.get)(
                    urljoin(BASE_URL, path),
                    **({"data": {"srh": query}} if query else {}),
                    timeout=15,
                )
                _last_request = time.monotonic()
                if response.status_code in (403, 429, 503) or any(
                    marker in response.text.casefold()
                    for marker in ("captcha", "rate limit", "cloudflare challenge")
                ):
                    failure_reason = "rate_limit" if response.status_code == 429 else "access_blocked"
                    _blocked_until = time.monotonic() + 15 * 60
                    raise RuntimeError("FlixiTV blockiert oder limitiert")
                if response.status_code == 404:
                    failure_reason = "unavailable"
                response.raise_for_status()
                soup = BeautifulSoup(response.content.decode("cp1252"), "lxml")
                ttl = 60 if urlparse(path).hostname == "hubu.cloud" else (900 if query else 1200)
                _cache[key] = (time.monotonic() + ttl, soup)
                if probe:
                    self._health.mark_success("flixitv")
                return soup
            except Exception as exc:
                _blocked_until = max(_blocked_until, time.monotonic() + 15 * 60)
                if self._health is not None:
                    self._health.mark_blocked("flixitv", failure_reason, str(exc))
                raise

    @staticmethod
    def _cards(soup: BeautifulSoup) -> list[FilmpalastSearchResult]:
        results = []
        seen = set()
        for card in soup.select("a.card-link[href*='/serie'], a.text-decoration-none[href*='/serie']"):
            identity = _identity(card.get("href", ""))
            if not identity or identity in seen:
                continue
            seen.add(identity)
            title, year = _title_year(card.select_one("h5").get_text(" ", strip=True)) if card.select_one("h5") else ("", "")
            if not title or "[subbed]" in title.casefold():
                continue
            info = card.select_one(".card-info p, .card-text")
            is_movie = bool(info and re.search(r"\bFilm\b", info.get_text(" ", strip=True), re.IGNORECASE))
            image = card.select_one("img[src]")
            results.append(FilmpalastSearchResult(
                title=title, slug=SOURCE_PREFIX + identity,
                url=f"{BASE_URL}/serie/?v={identity}", year=year,
                is_movie=is_movie, provider="flixitv", content_language="de",
                cover_url=urljoin(BASE_URL, image["src"]) if image else "",
            ))
        return results

    def search(self, query: str):
        return [item for item in self._cards(self._request("/search/", query=query[:20])) if item.is_movie]

    def search_series(self, query: str):
        return [self._series_result(item) for item in self._cards(self._request("/search/", query=query[:20])) if not item.is_movie]

    @staticmethod
    def _series_result(item: FilmpalastSearchResult) -> FilmpalastSeriesResult:
        return FilmpalastSeriesResult(
            title=item.title, base_slug=item.slug, sample_slug=item.slug,
            sample_url=item.url, year=item.year, cover_url=item.cover_url,
        )

    def list_movies(self, category="new", page=1):
        items = [item for item in self._cards(self._request("/serie/")) if item.is_movie]
        return items[(page - 1) * 32:page * 32]

    def list_series(self, page=1):
        items = [self._series_result(item) for item in self._cards(self._request("/serie/")) if not item.is_movie]
        return items[(page - 1) * 32:page * 32]

    def list_genres(self):
        return []

    def list_by_genre(self, genre, page=1):
        return []

    def _detail(self, identity: str, season: int | None = None):
        suffix = f"&s={season}" if season else ""
        return self._request(f"/serie/?v={identity}{suffix}")

    @staticmethod
    def _episodes(soup: BeautifulSoup, identity: str, season: int):
        episodes = []
        for row in soup.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            number = cells[1].get_text(" ", strip=True)
            link = cells[1].find("a", href=True)
            title = cells[2].get_text(" ", strip=True)
            if not number.isdigit() or not link:
                continue
            # A source covering multiple numbered episodes cannot safely satisfy
            # a single SxxExx queue job.
            if re.search(r"\b(?:Teil|Part)\s*\d+\s*(?:&|und|[-–])\s*\d+\b", title, re.IGNORECASE):
                continue
            episode = int(number)
            episodes.append(SeriesEpisode(
                season=season, episode=episode,
                slug=f"{SOURCE_PREFIX}{identity}-s{season:02d}e{episode:02d}",
                url=urljoin(BASE_URL, link["href"]), release_name=title,
            ))
        return episodes

    def get_series(self, value: str):
        identity = _identity(value)
        if not identity:
            return None
        detail = self._detail(identity)
        if detail.find("li", string=re.compile(r"^Film$", re.IGNORECASE)):
            return None
        title_tag = detail.find("h1") or detail.find("h2")
        if not title_tag:
            return None
        title, _year = _title_year(title_tag.get_text(" ", strip=True))
        season_numbers = sorted({
            int(match.group(1)) for a in detail.select("a[href*='s=']")
            if (match := re.search(r"[?&]s=(\d+)", a.get("href", "")))
        })
        seasons = {}
        for season in season_numbers:
            episodes = self._episodes(self._detail(identity, season), identity, season)
            if episodes:
                seasons[season] = episodes
        return FilmpalastSeries(
            title=title, base_slug=SOURCE_PREFIX + identity,
            url=f"{BASE_URL}/serie/?v={identity}", seasons=seasons,
        ) if seasons else None

    def get_movie(self, value: str):
        identity = _identity(value)
        if not identity:
            return None
        parsed = parse_episode_slug(value.removeprefix(SOURCE_PREFIX))
        season, episode = (parsed[1], parsed[2]) if parsed else (1, 1)
        detail = self._detail(identity, season)
        title_tag = detail.find("h1") or detail.find("h2")
        if not title_tag:
            return None
        title, year = _title_year(title_tag.get_text(" ", strip=True))
        selected = next((item for item in self._episodes(detail, identity, season) if item.episode == episode), None)
        if not selected:
            return None
        watch = self._request(urlparse(selected.url).path + "?" + urlparse(selected.url).query)
        iframe = watch.select_one("iframe[src*='hubu.cloud/video/embed/']")
        if not iframe:
            return None
        embed_url = iframe["src"]
        if urlparse(embed_url).hostname != "hubu.cloud":
            return None
        embed = self._request(embed_url)
        source = embed.select_one("video source[src]")
        if not source:
            return None
        stream_url = source["src"]
        if urlparse(stream_url).hostname not in {"hubu.cloud", "ww3.hubu.cloud"}:
            return None
        return FilmpalastMovie(
            title=f"{title} S{season:02d}E{episode:02d}" if parsed else title,
            url=selected.url, year=year, provider="flixitv", content_language="de",
            hosters=[HosterInfo("Hubu", stream_url, "Deutsch", "HD")],
        )
