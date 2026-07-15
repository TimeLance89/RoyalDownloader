"""Scraper fuer kinoger.com (Filme und Serien).

KinoGer basiert auf DataLife Engine. Katalog und Suche sind normales HTML;
die Player stehen als JavaScript-Aufrufe ``<name>.show(staffeln, [[urls...]])``
in der Detailseite. Dadurch lassen sich auch Serien ohne Browser in Staffeln
und Episoden zerlegen. Erst die spaetere Stream-Aufloesung braucht je nach
Mirror den vorhandenen Vidara-/VOE-/Browser-Fallback.
"""

import ast
import logging
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

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

BASE_URL = "https://kinoger.com"
SOURCE_PREFIX = "kinoger:"

GENRES: Dict[str, str] = {
    "Anime": "anime",
    "Action": "action",
    "Animation": "animation",
    "Abenteuer": "abenteuer",
    "Biografie": "biography",
    "Drama": "drama",
    "Dokumentation": "dokumentation",
    "Familie": "familie",
    "Fantasy": "fantasy",
    "Geschichte": "geschichte",
    "Horror": "horror",
    "Krimi": "krimi",
    "Krieg": "krieg",
    "Komödie": "komdie",
    "Musik": "music",
    "Mystery": "mystery",
    "Romance": "romance",
    "Sci-Fi": "sci-fi",
    "Sport": "sport",
    "Thriller": "thriller",
    "Western": "western",
    "Zeichentrick": "zeichentrick",
}

_ARTICLE_RE = re.compile(r"/stream/(?P<slug>\d+-[^/?#]+)\.html", re.I)
_SERIES_MARKER_RE = re.compile(r"\bS\d{1,2}(?:-\d{1,2})?E\d{1,3}", re.I)
_SHOW_RE = re.compile(
    r"(?P<player>[A-Za-z_$][\w$]*)\.show\(\s*\d+\s*,\s*"
    r"(?P<seasons>\[\[.*?\]\])\s*(?:,\s*[\d.]+)?\s*\)",
    re.S,
)
_META_LINE_RE = re.compile(
    r"^(?:imdb|veröffentlicht|released|spielzeit|laufzeit|dauer|"
    r"kategorien|genre(?:\(s\))?|regie|schauspieler|schöpfer|"
    r"casts?|orginal titel|original titel|land|drehbuch|hauptrolle)\b",
    re.I,
)


@dataclass
class _Card:
    title: str
    year: str
    slug: str
    url: str
    cover_url: str
    is_series: bool


class KinogerScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.session = cr.Session(impersonate="chrome136")

    # ------------------------------------------------------------------
    # Katalog / Suche
    # ------------------------------------------------------------------
    def search(self, query: str) -> List[FilmpalastSearchResult]:
        cards = self._search_cards(query)
        results = [self._movie_result(card) for card in cards if not card.is_series]
        self._log(f"  KinoGer: {len(results)} Film(e) gefunden")
        return results

    def list_movies(self, category: str = "new", page: int = 1) -> List[FilmpalastSearchResult]:
        # KinoGer hat keine separate stabile Top-Route. Die Hauptliste ist die
        # verlaessliche, chronologische Quelle und wird auch fuer "top" genutzt.
        url = BASE_URL + "/" if page <= 1 else f"{BASE_URL}/page/{page}/"
        cards = self._parse_cards(self._get_soup(url))
        return [self._movie_result(card) for card in cards if not card.is_series]

    def list_genres(self) -> List[str]:
        return list(GENRES.keys())

    def list_by_genre(self, genre: str, page: int = 1) -> List[FilmpalastSearchResult]:
        slug = GENRES.get((genre or "").strip())
        if not slug:
            return []
        suffix = f"page/{page}/" if page > 1 else ""
        cards = self._parse_cards(self._get_soup(f"{BASE_URL}/stream/{slug}/{suffix}"))
        return [self._movie_result(card) for card in cards if not card.is_series]

    def search_series(self, query: str) -> List[FilmpalastSeriesResult]:
        cards = self._search_cards(query)
        results = [self._series_result(card) for card in cards if card.is_series]
        self._log(f"  KinoGer: {len(results)} Serie(n) gefunden")
        return results

    def list_series(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        suffix = f"page/{page}/" if page > 1 else ""
        cards = self._parse_cards(self._get_soup(f"{BASE_URL}/stream/serie/{suffix}"))
        return [self._series_result(card) for card in cards]

    def _search_cards(self, query: str) -> List[_Card]:
        query = " ".join((query or "").split()).strip()
        if not query:
            return []
        self._log(f"KinoGer Suche: {query}")
        soup = self._get_soup(
            f"{BASE_URL}/index.php",
            params={
                "do": "search",
                "subaction": "search",
                "search_start": 0,
                "full_search": 0,
                "result_from": 1,
                "titleonly": 3,
                "story": query,
            },
        )
        return self._parse_cards(soup)

    # ------------------------------------------------------------------
    # Detail / Episoden
    # ------------------------------------------------------------------
    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        article_slug, season, episode = self._article_and_episode(url_or_slug)
        if not article_slug:
            return None
        url = self._article_url(article_slug)
        self._log(f"Lade KinoGer: {url}")
        soup = self._get_soup(url)
        metadata = self._metadata(soup, url)
        players = self._player_seasons(soup)

        hosters: List[HosterInfo] = []
        seen = set()
        for seasons in players:
            if season is None or episode is None:
                selected = seasons[0][0:1] if seasons else []
            elif 0 < season <= len(seasons) and 0 < episode <= len(seasons[season - 1]):
                selected = seasons[season - 1][episode - 1:episode]
            else:
                selected = []
            for play_url in selected:
                play_url = play_url.strip()
                if not play_url or play_url in seen:
                    continue
                seen.add(play_url)
                hosters.append(HosterInfo(
                    name=self._hoster_name(play_url),
                    url=play_url,
                    language="Deutsch",
                    quality="HD",
                ))

        title = metadata["title"]
        if season is not None and episode is not None:
            title = f"{title} S{season:02d}E{episode:02d}"
        if not hosters:
            self._log("  KinoGer: keine Hoster für diesen Eintrag gefunden")
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
        article_slug, _season, _episode = self._article_and_episode(url_or_slug)
        if not article_slug:
            return None
        url = self._article_url(article_slug)
        self._log(f"Lade Serie (KinoGer): {url}")
        soup = self._get_soup(url)
        metadata = self._metadata(soup, url)
        players = self._player_seasons(soup)
        if not players:
            return None

        season_count = max((len(seasons) for seasons in players), default=0)
        seasons: Dict[int, List[SeriesEpisode]] = {}
        for season in range(1, season_count + 1):
            episode_count = max(
                (len(items[season - 1]) for items in players if len(items) >= season),
                default=0,
            )
            if not episode_count:
                continue
            episodes: List[SeriesEpisode] = []
            for episode in range(1, episode_count + 1):
                slug = f"{SOURCE_PREFIX}{article_slug}-s{season:02d}e{episode:02d}"
                episodes.append(SeriesEpisode(
                    season=season,
                    episode=episode,
                    slug=slug,
                    url=f"{url}#S{season:02d}E{episode:02d}",
                ))
            seasons[season] = episodes

        if not seasons:
            return None
        base_slug = f"{SOURCE_PREFIX}{article_slug}"
        return FilmpalastSeries(
            title=metadata["title"],
            base_slug=base_slug,
            url=url,
            cover_url=metadata["cover_url"],
            description=metadata["description"],
            genres=metadata["genres"],
            seasons=seasons,
        )

    # ------------------------------------------------------------------
    # Parser-Helfer
    # ------------------------------------------------------------------
    def _get_soup(self, url: str, params: Optional[dict] = None) -> BeautifulSoup:
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def _parse_cards(self, soup: BeautifulSoup) -> List[_Card]:
        cards: List[_Card] = []
        seen = set()
        for a in soup.select("#dle-content .titlecontrol .title a[href*='/stream/']"):
            href = urljoin(BASE_URL + "/", a.get("href", ""))
            slug = self._slug_from_url(href)
            if not slug or slug in seen:
                continue
            seen.add(slug)

            title_control = a.find_parent("div", class_="titlecontrol")
            short = a.find_parent("div", class_="short")
            if short is not None:
                box = short.select_one(".general_box")
            else:
                box = title_control.find_next_sibling("div", class_="general_box") if title_control else None
            content = box.select_one(".content_text") if box else None
            raw_title = re.sub(r"\s+Film\s*$", "", a.get_text(" ", strip=True), flags=re.I)
            title, year = self._split_title_year(raw_title)
            if not title:
                continue

            is_series = False
            if content and _SERIES_MARKER_RE.search(content.get_text(" ", strip=True)):
                is_series = True
            if box and box.select_one("a[href*='/serie/']"):
                is_series = True
            image = content.select_one("img[src]") if content else None
            cover = urljoin(BASE_URL + "/", image.get("src", "")) if image else ""
            cards.append(_Card(title, year, slug, href, cover, is_series))
        return cards

    @staticmethod
    def _movie_result(card: _Card) -> FilmpalastSearchResult:
        return FilmpalastSearchResult(
            title=f"{card.title}  [KinoGer]",
            slug=f"{SOURCE_PREFIX}{card.slug}",
            url=card.url,
            year=card.year,
            is_movie=True,
        )

    @staticmethod
    def _series_result(card: _Card) -> FilmpalastSeriesResult:
        value = f"{SOURCE_PREFIX}{card.slug}"
        return FilmpalastSeriesResult(
            title=f"{card.title}  [KinoGer]",
            base_slug=value,
            sample_slug=value,
            sample_url=card.url,
            year=card.year,
            cover_url=card.cover_url,
        )

    @staticmethod
    def _player_seasons(soup: BeautifulSoup) -> List[List[List[str]]]:
        players: List[List[List[str]]] = []
        html = str(soup)
        for match in _SHOW_RE.finditer(html):
            try:
                raw = ast.literal_eval(match.group("seasons"))
            except (SyntaxError, ValueError):
                continue
            if not isinstance(raw, list):
                continue
            seasons: List[List[str]] = []
            for values in raw:
                if not isinstance(values, (list, tuple)):
                    seasons.append([])
                    continue
                seasons.append([str(value).strip() for value in values if str(value).strip()])
            if seasons:
                players.append(seasons)
        return players

    @staticmethod
    def _metadata(soup: BeautifulSoup, page_url: str) -> dict:
        title_tag = soup.select_one("meta[property='og:title']")
        raw_title = title_tag.get("content", "").strip() if title_tag else ""
        if not raw_title:
            heading = soup.select_one("#news-title")
            raw_title = heading.get_text(" ", strip=True) if heading else "Unbekannt"
        title, year = KinogerScraper._split_title_year(raw_title)

        detail = soup.select_one("#dle-content .images-border")
        image = detail.select_one("img[src]") if detail else None
        cover_url = urljoin(page_url, image.get("src", "")) if image else ""
        lines = list(detail.stripped_strings) if detail else []
        if lines and (
            _SERIES_MARKER_RE.search(lines[0])
            or re.fullmatch(r"(?:WEB|BD|HD|TS|DVDRip|HDRip).*", lines[0], re.I)
        ):
            lines.pop(0)
        description_lines: List[str] = []
        for line in lines:
            if _META_LINE_RE.match(line):
                break
            description_lines.append(line)
        description = " ".join(description_lines).strip()
        all_text = "\n".join(lines)

        runtime = ""
        runtime_match = re.search(
            r"(?:Spielzeit|Laufzeit|Dauer)\s*:?\s*(?:Ca\.\s*)?(\d+)\s*(?:min|Min)",
            all_text,
            re.I,
        )
        if runtime_match:
            runtime = f"{runtime_match.group(1)} min"

        genres: List[str] = []
        for link in soup.select("#dle-content li.category a[href]"):
            name = link.get_text(" ", strip=True)
            href = link.get("href", "")
            if name and name not in ("Stream", "Serie") and "/stream/" in href and name not in genres:
                genres.append(name)

        return {
            "title": title or "Unbekannt",
            "year": year,
            "runtime": runtime,
            "cover_url": cover_url,
            "description": description,
            "genres": genres,
        }

    @staticmethod
    def _hoster_name(url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if "kinoger.pw" in host or "vidara" in host:
            return "Vidara"
        if "kinoger.ru" in host or "voe" in host:
            return "VOE"
        if "fsst" in host or "incvideo" in host:
            return "FSST"
        if "kinoger.be" in host:
            return "VidHide"
        if "embed4me" in host:
            return "Embed4Me"
        if "seekplays" in host:
            return "SeekPlays"
        return host or "KinoGer"

    @staticmethod
    def _split_title_year(text: str):
        match = re.match(r"^(.*?)\s*\(((?:19|20)\d{2})\)\s*$", text or "")
        if match:
            return match.group(1).strip(), match.group(2)
        return (text or "").strip(), ""

    @staticmethod
    def _slug_from_url(url: str) -> str:
        match = _ARTICLE_RE.search(url or "")
        return match.group("slug") if match else ""

    @staticmethod
    def _article_url(slug: str) -> str:
        return f"{BASE_URL}/stream/{slug}.html"

    @staticmethod
    def _article_and_episode(value: str):
        raw = str(value or "").strip()
        if raw.startswith(SOURCE_PREFIX):
            raw = raw[len(SOURCE_PREFIX):]
        if raw.startswith(("http://", "https://")):
            slug = KinogerScraper._slug_from_url(raw)
            return slug, None, None
        parsed = parse_episode_slug(raw)
        if parsed:
            return parsed
        raw = raw.removeprefix("stream/").removesuffix(".html").strip("/")
        return (raw, None, None) if re.match(r"^\d+-", raw) else ("", None, None)
