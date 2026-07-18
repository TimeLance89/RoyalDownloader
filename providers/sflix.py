"""Scraper für den englischsprachigen SFlix-Katalog.

Der aktuelle Spiegel liefert Filme und Serien als serverseitiges HTML. Die
Playerliste wird über einen verschlüsselten AJAX-Link geladen; dessen Token
wird unverändert aus der Detailseite übernommen. Erst die spätere Auflösung
des ausgewählten Players benötigt den gemeinsamen Browser-Pool.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

from providers.models import (
    FilmpalastMovie,
    FilmpalastSearchResult,
    FilmpalastSeries,
    FilmpalastSeriesResult,
    HosterInfo,
    SeriesEpisode,
    parse_episode_slug,
)

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("SFLIX_BASE_URL", "https://sflix.win").strip().rstrip("/")
SOURCE_PREFIX = "sflix:"

GENRES: Dict[str, str] = {
    "Action": "action",
    "Action & Adventure": "action-adventure",
    "Adventure": "adventure",
    "Animation": "animation",
    "Comedy": "comedy",
    "Crime": "crime",
    "Documentary": "documentary",
    "Drama": "drama",
    "Family": "family",
    "Fantasy": "fantasy",
    "History": "history",
    "Horror": "horror",
    "Kids": "kids",
    "Music": "music",
    "Mystery": "mystery",
    "News": "news",
    "Reality": "reality",
    "Romance": "romance",
    "Sci-Fi & Fantasy": "sci-fi-fantasy",
    "Science Fiction": "science-fiction",
    "Soap": "soap",
    "Talk": "talk",
    "Thriller": "thriller",
    "TV Movie": "tv-movie",
    "War": "war",
    "Western": "western",
}

_MEDIA_PATH_RE = re.compile(
    r"/(?P<kind>movie|series)/(?P<slug>[a-z0-9][a-z0-9-]*)/?",
    re.I,
)
_EPISODE_PATH_RE = re.compile(
    r"/series/(?P<slug>[a-z0-9][a-z0-9-]*)/"
    r"(?P<season>\d{1,2})-(?P<episode>\d{1,3})/?",
    re.I,
)
_SITE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,180}$", re.I)
_PLAYER_URL_RE = re.compile(
    r"\bconst\s+pl_url\s*=\s*(['\"])(?P<url>https?://.+?)\1",
    re.I,
)


@dataclass(frozen=True)
class _Card:
    title: str
    site_slug: str
    url: str
    year: str
    cover_url: str
    is_movie: bool


class SflixScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.base_url = BASE_URL
        self.session = cr.Session(impersonate="chrome136")

    # ------------------------------------------------------------------
    # Katalog und Suche
    # ------------------------------------------------------------------
    def search(self, query: str) -> List[FilmpalastSearchResult]:
        cards = self._search_cards(query)
        results = [self._movie_result(card) for card in cards if card.is_movie]
        self._log(f"  SFlix: {len(results)} englische Film(e) gefunden")
        return results

    def list_movies(
        self,
        category: str = "new",
        page: int = 1,
    ) -> List[FilmpalastSearchResult]:
        page = max(1, int(page or 1))
        if category == "top":
            if page != 1:
                return []
            soup = self._get_soup("/home")
            container = soup.select_one("#trending-movies") or soup
        else:
            container = self._get_soup(f"/movies/page/{page}/")
        return [
            self._movie_result(card)
            for card in self._parse_cards(container)
            if card.is_movie
        ]

    def list_genres(self) -> List[str]:
        return list(GENRES.keys())

    def list_by_genre(
        self,
        genre: str,
        page: int = 1,
    ) -> List[FilmpalastSearchResult]:
        genre_key = " ".join(str(genre or "").split()).casefold()
        genre_slug = next(
            (slug for label, slug in GENRES.items() if label.casefold() == genre_key),
            "",
        )
        if not genre_slug:
            return []
        page = max(1, int(page or 1))
        suffix = f"page/{page}/" if page > 1 else ""
        cards = self._parse_cards(
            self._get_soup(f"/genre/{genre_slug}/{suffix}")
        )
        return [self._movie_result(card) for card in cards if card.is_movie]

    def search_series(self, query: str) -> List[FilmpalastSeriesResult]:
        cards = self._search_cards(query)
        results = [self._series_result(card) for card in cards if not card.is_movie]
        self._log(f"  SFlix: {len(results)} englische Serie(n) gefunden")
        return results

    def list_series(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        page = max(1, int(page or 1))
        cards = self._parse_cards(self._get_soup(f"/tv-series/page/{page}/"))
        return [self._series_result(card) for card in cards if not card.is_movie]

    def _search_cards(self, query: str) -> List[_Card]:
        query = " ".join(str(query or "").split()).strip()
        if not query:
            return []
        self._log(f"SFlix Suche: {query}")
        # SFlix wertet Bindestriche als einzelne Suchbegriffe. Echte
        # Leerzeichen müssen deshalb percent-kodiert im Pfad erhalten bleiben.
        return self._parse_cards(
            self._get_soup(f"/search/{quote(query, safe='')}/")
        )

    # ------------------------------------------------------------------
    # Details, Staffeln und Player
    # ------------------------------------------------------------------
    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        parsed_episode = parse_episode_slug(str(url_or_slug or ""))
        site_slug = self._site_slug(
            parsed_episode[0] if parsed_episode else url_or_slug
        )
        if not site_slug:
            return None

        season = parsed_episode[1] if parsed_episode else None
        episode = parsed_episode[2] if parsed_episode else None
        if season is not None and episode is not None:
            url = f"{self.base_url}/series/{site_slug}/{season}-{episode}/"
        else:
            url = f"{self.base_url}/movie/{site_slug}/"

        self._log(f"Lade SFlix: {url}")
        soup = self._get_soup(url)
        metadata = self._metadata(soup)
        if not metadata["title"]:
            return None
        hosters = self._hosters(soup, url)
        title = metadata["title"]
        if season is not None and episode is not None:
            title = f"{title} S{season:02d}E{episode:02d}"
        return FilmpalastMovie(
            title=title,
            url=url,
            year=metadata["year"],
            runtime=metadata["runtime"],
            cover_url=metadata["cover_url"],
            description=metadata["description"],
            genres=metadata["genres"],
            hosters=hosters,
        )

    def get_series(self, url_or_slug: str) -> Optional[FilmpalastSeries]:
        site_slug = self._site_slug(url_or_slug)
        if not site_slug:
            return None
        url = f"{self.base_url}/series/{site_slug}/"
        self._log(f"Lade Serie (SFlix): {url}")
        soup = self._get_soup(url)
        metadata = self._metadata(soup)
        if not metadata["title"]:
            return None

        seasons: Dict[int, List[SeriesEpisode]] = {}
        for season_link in soup.select(".ss-item[data-ss][data-id]"):
            try:
                season = int(season_link.get("data-ss", ""))
            except (TypeError, ValueError):
                continue
            token = str(season_link.get("data-id") or "").strip()
            if season < 0 or not token:
                continue
            try:
                episode_soup = self._get_soup(
                    "/ajax/ajax.php",
                    params={"episode": token},
                    referer=url,
                )
            except Exception as exc:
                self._log(
                    f"  SFlix Staffel {season} übersprungen: {exc}"
                )
                continue
            episodes = self._parse_season_episodes(
                episode_soup,
                site_slug,
                expected_season=season,
            )
            if episodes:
                seasons[season] = episodes

        if not seasons:
            return None
        total = sum(len(episodes) for episodes in seasons.values())
        self._log(
            f"  Serie (SFlix): «{metadata['title']}» – "
            f"{len(seasons)} Staffel(n), {total} Episoden"
        )
        return FilmpalastSeries(
            title=metadata["title"],
            base_slug=f"{SOURCE_PREFIX}{site_slug}",
            url=url,
            cover_url=metadata["cover_url"],
            description=metadata["description"],
            genres=metadata["genres"],
            seasons=seasons,
        )

    def _hosters(self, soup: BeautifulSoup, referer: str) -> List[HosterInfo]:
        match = _PLAYER_URL_RE.search(str(soup))
        if not match:
            self._log("  SFlix: Playerliste fehlt")
            return []
        ajax_url = match.group("url")
        parsed = urlparse(ajax_url)
        base_host = (urlparse(self.base_url).hostname or "").casefold()
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != base_host
            or parsed.path != "/ajax/ajax.php"
        ):
            self._log("  SFlix: ungültiger Playerlisten-Link")
            return []
        try:
            server_soup = self._get_soup(ajax_url, referer=referer)
        except Exception as exc:
            self._log(f"  SFlix Playerliste nicht ladbar: {exc}")
            return []

        quality_node = soup.select_one(".fs-item strong")
        quality = (
            quality_node.get_text(" ", strip=True)
            if quality_node
            else "HD"
        )
        hosters: List[HosterInfo] = []
        seen = set()
        for node in server_soup.select("#servers-list [data-id]"):
            play_url = str(node.get("data-id") or "").strip()
            parsed_play = urlparse(play_url)
            if parsed_play.scheme not in ("http", "https") or not parsed_play.netloc:
                continue
            if play_url in seen:
                continue
            seen.add(play_url)
            name = str(node.get("data-srv") or "").strip() or "SFlix"
            hosters.append(HosterInfo(
                name=name,
                url=play_url,
                language="English",
                quality=quality,
            ))
        return hosters

    def _parse_season_episodes(
        self,
        soup: BeautifulSoup,
        site_slug: str,
        expected_season: int,
    ) -> List[SeriesEpisode]:
        episodes: List[SeriesEpisode] = []
        seen = set()
        for item in soup.select(".flw-item"):
            link = item.select_one("a.eps-item[href]") or item.select_one(
                "a[href*='/series/']"
            )
            if not link:
                continue
            href = urljoin(self.base_url + "/", str(link.get("href") or ""))
            match = _EPISODE_PATH_RE.search(urlparse(href).path)
            if not match or match.group("slug").casefold() != site_slug.casefold():
                continue
            season = int(match.group("season"))
            episode = int(match.group("episode"))
            if season != expected_season or episode in seen:
                continue
            seen.add(episode)
            title_node = item.select_one(".film-name")
            release_name = (
                title_node.get_text(" ", strip=True)
                if title_node
                else ""
            )
            episodes.append(SeriesEpisode(
                season=season,
                episode=episode,
                slug=(
                    f"{SOURCE_PREFIX}{site_slug}"
                    f"-s{season:02d}e{episode:02d}"
                ),
                url=href,
                release_name=release_name,
            ))
        return sorted(episodes, key=lambda item: item.episode)

    # ------------------------------------------------------------------
    # Parser- und HTTP-Helfer
    # ------------------------------------------------------------------
    def _get_soup(
        self,
        url_or_path: str,
        params: Optional[dict] = None,
        referer: str = "",
    ) -> BeautifulSoup:
        url = (
            url_or_path
            if str(url_or_path).lower().startswith(("http://", "https://"))
            else urljoin(self.base_url + "/", str(url_or_path).lstrip("/"))
        )
        parsed = urlparse(url)
        base_host = (urlparse(self.base_url).hostname or "").casefold()
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != base_host
        ):
            raise ValueError("SFlix-URL liegt außerhalb der konfigurierten Domain")
        headers = {
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
            headers["X-Requested-With"] = "XMLHttpRequest"
        response = self.session.get(
            url,
            params=params or {},
            headers=headers,
            timeout=30,
            allow_redirects=True,
        )
        if response.status_code in (520, 521, 522, 523, 524):
            raise RuntimeError(f"SFlix-Domain nicht erreichbar ({response.status_code})")
        response.raise_for_status()
        final_host = (urlparse(str(response.url)).hostname or "").casefold()
        if final_host != base_host:
            raise RuntimeError("SFlix-Antwort wurde auf eine fremde Domain umgeleitet")
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.get_text(" ", strip=True).casefold() if soup.title else ""
        if "just a moment" in title or "attention required" in title:
            raise RuntimeError("SFlix Cloudflare-Sperre aktiv")
        return soup

    def _parse_cards(self, container) -> List[_Card]:
        cards: List[_Card] = []
        seen = set()
        for item in container.select(".flw-item"):
            link = item.select_one(".film-name a[href]") or item.select_one(
                ".film-poster-ahref[href]"
            )
            if not link:
                continue
            href = urljoin(self.base_url + "/", str(link.get("href") or ""))
            match = _MEDIA_PATH_RE.search(urlparse(href).path)
            if not match:
                continue
            kind = match.group("kind").casefold()
            site_slug = match.group("slug")
            identity = (kind, site_slug.casefold())
            if identity in seen:
                continue
            seen.add(identity)

            title = (
                str(link.get("title") or "").strip()
                or link.get_text(" ", strip=True)
            )
            if not title:
                title_node = item.select_one(".film-name")
                title = title_node.get_text(" ", strip=True) if title_node else ""
            if not title:
                continue
            year = ""
            for info in item.select(".fdi-item"):
                value = info.get_text(" ", strip=True)
                if re.fullmatch(r"(?:19|20)\d{2}", value):
                    year = value
                    break
            image = item.select_one(".film-poster-img")
            cover_url = ""
            if image:
                cover_url = str(
                    image.get("src")
                    or image.get("data-src")
                    or ""
                ).strip()
            cards.append(_Card(
                title=title,
                site_slug=site_slug,
                url=href,
                year=year,
                cover_url=cover_url,
                is_movie=kind == "movie",
            ))
        return cards

    def _metadata(self, soup: BeautifulSoup) -> dict:
        title_node = soup.select_one("h2.heading-name")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        description_node = soup.select_one(".description")
        description = (
            description_node.get_text(" ", strip=True)
            if description_node
            else ""
        )
        description = re.sub(r"^Overview:\s*", "", description, flags=re.I)

        rows = soup.select(".row-line")
        year = ""
        runtime = ""
        genres: List[str] = []
        for row in rows:
            text = row.get_text(" ", strip=True)
            if re.match(r"^Genre:", text, re.I):
                genres = [
                    link.get_text(" ", strip=True)
                    for link in row.select("a[href*='/genre/']")
                    if link.get_text(" ", strip=True)
                ]
            elif re.match(r"^Duration:", text, re.I):
                runtime = re.sub(r"^Duration:\s*", "", text, flags=re.I)
            elif re.match(r"^Year:", text, re.I):
                match = re.search(r"\b(?:19|20)\d{2}\b", text)
                year = match.group(0) if match else ""
            elif not year and re.match(r"^Released:", text, re.I):
                match = re.search(r"\b(?:19|20)\d{2}\b", text)
                year = match.group(0) if match else ""

        image = soup.select_one(".detail_page-infor .film-poster-img")
        cover_url = ""
        if image:
            cover_url = str(
                image.get("src")
                or image.get("data-src")
                or ""
            ).strip()
        return {
            "title": title,
            "year": year,
            "runtime": runtime,
            "cover_url": cover_url,
            "description": description,
            "genres": genres,
        }

    def _movie_result(self, card: _Card) -> FilmpalastSearchResult:
        return FilmpalastSearchResult(
            title=f"{card.title}  [SFlix]",
            slug=f"{SOURCE_PREFIX}{card.site_slug}",
            url=card.url,
            year=card.year,
            is_movie=True,
        )

    def _series_result(self, card: _Card) -> FilmpalastSeriesResult:
        base_slug = f"{SOURCE_PREFIX}{card.site_slug}"
        return FilmpalastSeriesResult(
            title=f"{card.title}  [SFlix]",
            base_slug=base_slug,
            sample_slug=base_slug,
            sample_url=card.url,
            year=card.year,
            cover_url=card.cover_url,
        )

    def _site_slug(self, value: str) -> str:
        raw = str(value or "").strip()
        parsed_episode = parse_episode_slug(raw)
        if parsed_episode:
            raw = parsed_episode[0]
        if raw.casefold().startswith(SOURCE_PREFIX):
            raw = raw[len(SOURCE_PREFIX):]
        if raw.lower().startswith(("http://", "https://")):
            match = _MEDIA_PATH_RE.search(urlparse(raw).path)
            raw = match.group("slug") if match else ""
        raw = raw.strip().strip("/")
        return raw if _SITE_SLUG_RE.fullmatch(raw) else ""
