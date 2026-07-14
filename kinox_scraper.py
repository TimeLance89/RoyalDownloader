"""
Scraper fuer kinox.camp – Backup-Provider, nur Filme (keine Serien).

Alte DataLife-Engine-Seite (viel Ad-/Anti-Adblock-JS direkt nach <body>,
aber die eigentlichen Inhalte stehen als normales HTML dahinter – kein
Rendering noetig):

  GET /index.php?do=search&subaction=search&story=<query>  -> Suche
  GET /rss.xml                                              -> neueste Filme
  GET /<genre-slug>/                                        -> Genre-Auswahl
  GET /<id>-<slug>.html                                     -> Film-Detail
     - Hoster:   <li data-link="..."><div class="Named">Name</div></li>
     - Cover:    div.player_window_poster img
     - Titel:    <meta property="og:title">
     - Text:     <meta property="og:description"> (Fallback: meta[name=description])
     - Genre:    li.DetailDat[title="Genre"] a
     - Laufzeit: li.DetailDat[title="Runtime"]

Serien laufen auf kinox.camp pro Staffel (nicht pro Episode) als eigene
Artikel ohne konsistente Verlinkung zwischen den Staffeln -> hier bewusst
nicht unterstuetzt, nur Filme (analog zu einschalten_scraper.py).
"""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

from filmpalast_scraper import FilmpalastMovie, FilmpalastSearchResult, HosterInfo

logger = logging.getLogger(__name__)

BASE_URL = "https://kinox.camp"
SOURCE_PREFIX = "kinox:"

GENRES: Dict[str, str] = {
    "Action": "action",
    "Komödie": "komodie",
    "Drama": "drama",
    "Horror": "horror",
    "Krieg": "krieg",
}

# data-link-Eintraege auf diesen Domains sind nur der Trailer, nicht der Film
_TRAILER_HOSTS = ("youtube.com", "youtu.be")


class KinoxScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.session = cr.Session(impersonate="chrome136")

    # ------------------------------------------------------------------
    def search(self, query: str) -> List[FilmpalastSearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        self._log(f"Kinox Suche: {query}")
        resp = self.session.get(
            f"{BASE_URL}/index.php",
            params={
                "do": "search", "subaction": "search", "story": query,
                "search_start": 0, "full_search": 0, "result_from": 1,
            },
            timeout=25,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results = self._parse_short_entries(soup)
        self._log(f"  Kinox: {len(results)} Treffer")
        return results

    def list_movies(self, category: str = "new", page: int = 1) -> List[FilmpalastSearchResult]:
        if page != 1:
            return []
        self._log("Kinox Liste (neu)")
        try:
            resp = self.session.get(f"{BASE_URL}/rss.xml", timeout=25)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            self._log(f"Kinox RSS nicht ladbar: {exc}")
            return []

        results: List[FilmpalastSearchResult] = []
        channel = root.find("channel")
        if channel is None:
            return []
        for item in channel.findall("item"):
            category_text = item.findtext("category") or ""
            if "kinofilme" not in category_text.lower():
                continue  # Serien-Eintraege (Staffel-Artikel) ueberspringen
            link = item.findtext("link") or ""
            title = item.findtext("title") or ""
            slug = self._slug_from_url(link)
            if not slug:
                continue
            results.append(FilmpalastSearchResult(
                title=f"{title}  [Kinox]", slug=f"{SOURCE_PREFIX}{slug}", url=link,
            ))
        return results

    def list_genres(self) -> List[str]:
        return list(GENRES.keys())

    def list_by_genre(self, genre: str, page: int = 1) -> List[FilmpalastSearchResult]:
        if page != 1:
            return []
        genre_slug = GENRES.get((genre or "").strip())
        if not genre_slug:
            return []
        self._log(f"Kinox Genre: {genre}")
        resp = self.session.get(f"{BASE_URL}/{genre_slug}/", timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        ul = soup.select_one("ul.List2")
        results: List[FilmpalastSearchResult] = []
        if ul:
            for a in ul.select("li a[href]"):
                href = a.get("href", "")
                slug = self._slug_from_url(href)
                if not slug:
                    continue
                title_span = a.select_one("span.title")
                title = title_span.get_text(strip=True) if title_span else a.get_text(strip=True)
                results.append(FilmpalastSearchResult(
                    title=f"{title}  [Kinox]", slug=f"{SOURCE_PREFIX}{slug}", url=href,
                ))
        return results

    # ------------------------------------------------------------------
    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        url = self._resolve_url(url_or_slug)
        if not url:
            return None
        self._log(f"Lade Film (Kinox): {url}")
        try:
            resp = self.session.get(url, timeout=25)
            resp.raise_for_status()
        except Exception as exc:
            self._log(f"Kinox-Film nicht ladbar: {exc}")
            return None
        soup = BeautifulSoup(resp.text, "lxml")

        title = self._meta(soup, "og:title")
        if not title and soup.title:
            title = re.sub(r"\s*Stream.*$", "", soup.title.get_text(strip=True))
        description = self._meta(soup, "og:description") or self._meta_name(soup, "description")

        cover_url = ""
        poster_img = soup.select_one("div.player_window_poster img")
        if poster_img and poster_img.get("src"):
            cover_url = self._abs_url(poster_img["src"])

        runtime = ""
        runtime_li = soup.find("li", attrs={"title": "Runtime"})
        if runtime_li:
            m = re.search(r"\d+", runtime_li.get_text())
            if m:
                runtime = f"{m.group(0)} min"

        genres: List[str] = []
        genre_li = soup.find("li", attrs={"title": "Genre"})
        if genre_li:
            for a in genre_li.find_all("a"):
                name = a.get_text(strip=True)
                if name and name != "Kinofilme" and name not in genres:
                    genres.append(name)

        hosters = self._extract_hosters(soup)
        if not hosters:
            self._log("  Keine Hoster auf der Seite gefunden.")
            return None

        return FilmpalastMovie(
            title=title or "Unbekannt", url=url, year="",
            runtime=runtime, cover_url=cover_url, description=description,
            genres=genres, hosters=hosters,
        )

    # ------------------------------------------------------------------
    # Keine Serien auf kinox.camp (siehe Modul-Docstring)
    # ------------------------------------------------------------------
    def search_series(self, query: str) -> List:
        return []

    def list_series(self, page: int = 1) -> List:
        return []

    # ------------------------------------------------------------------
    def _extract_hosters(self, soup: BeautifulSoup) -> List[HosterInfo]:
        hosters: List[HosterInfo] = []
        seen: set = set()
        for li in soup.find_all("li", attrs={"data-link": True}):
            link = (li.get("data-link") or "").strip()
            if not link:
                continue
            if any(h in link.lower() for h in _TRAILER_HOSTS):
                continue
            link = self._abs_url(link)
            if link in seen:
                continue
            seen.add(link)
            named = li.find("div", class_="Named")
            name = named.get_text(strip=True) if named else (urlparse(link).netloc or "Kinox")
            hosters.append(HosterInfo(name=name, url=link))
        return hosters

    @staticmethod
    def _meta(soup: BeautifulSoup, prop: str) -> str:
        tag = soup.find("meta", property=prop)
        return tag.get("content", "").strip() if tag else ""

    @staticmethod
    def _meta_name(soup: BeautifulSoup, name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        return tag.get("content", "").strip() if tag else ""

    @staticmethod
    def _abs_url(href: str) -> str:
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return BASE_URL + href
        return href

    @staticmethod
    def _slug_from_url(url: str) -> str:
        m = re.search(r"/(\d+-[^/?#]+\.html)", url or "")
        return m.group(1) if m else ""

    def _resolve_url(self, value: str) -> str:
        value = str(value or "")
        if value.startswith(SOURCE_PREFIX):
            value = value[len(SOURCE_PREFIX):]
        if value.startswith("http"):
            return value
        return f"{BASE_URL}/{value.lstrip('/')}"

    def _parse_short_entries(self, soup: BeautifulSoup) -> List[FilmpalastSearchResult]:
        results: List[FilmpalastSearchResult] = []
        for entry in soup.select("div.short-entry"):
            a = entry.select_one("div.short-entry-title a[href]")
            if not a:
                continue
            href = a.get("href", "")
            slug = self._slug_from_url(href)
            if not slug:
                continue
            title, year = self._split_title_year(a.get_text(strip=True))
            results.append(FilmpalastSearchResult(
                title=f"{title}  [Kinox]", slug=f"{SOURCE_PREFIX}{slug}", url=href, year=year,
            ))
        return results

    @staticmethod
    def _split_title_year(text: str):
        m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", text or "")
        if m:
            return m.group(1).strip(), m.group(2)
        return (text or "").strip(), ""
