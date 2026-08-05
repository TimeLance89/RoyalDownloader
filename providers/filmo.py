"""Scraper fuer filmo.to (Filme, Genres und externe Stream-Hoster)."""

from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional
from urllib.parse import quote, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

from providers.models import FilmpalastMovie, FilmpalastSearchResult, HosterInfo


logger = logging.getLogger(__name__)

BASE_URL = "https://filmo.to"
SOURCE_PREFIX = "filmo:"
_MOVIE_PATH_RE = re.compile(r"^/movies/([a-z0-9-]+)$", re.IGNORECASE)


class FilmoScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.session = cr.Session(impersonate="chrome136")

    def search(self, query: str) -> List[FilmpalastSearchResult]:
        query = str(query or "").strip()
        if not query:
            return []
        self._log(f"Filmo Suche: {query}")
        soup = self._get_soup("/search", params={"q": query})
        results = self._parse_results(soup)
        self._log(f"  Filmo: {len(results)} Treffer")
        return results

    def list_movies(
        self,
        category: str = "new",
        page: int = 1,
    ) -> List[FilmpalastSearchResult]:
        sort = "rating_desc" if category == "top" else "release_desc"
        soup = self._get_soup("/movies", params={"sort": sort, "page": max(1, int(page))})
        return self._parse_results(soup)

    def list_genres(self) -> List[str]:
        soup = self._get_soup("/genres")
        genres = {
            " ".join(link.get_text(" ", strip=True).split())
            for link in soup.select('a[href*="/genres/"]')
            if self._genre_slug(link.get("href", ""))
        }
        return sorted((genre for genre in genres if genre), key=str.casefold)

    def list_by_genre(
        self,
        genre: str,
        page: int = 1,
    ) -> List[FilmpalastSearchResult]:
        wanted = " ".join(str(genre or "").split()).casefold()
        if not wanted:
            return []
        soup = self._get_soup("/genres")
        genre_url = next(
            (
                link.get("href", "")
                for link in soup.select('a[href*="/genres/"]')
                if " ".join(link.get_text(" ", strip=True).split()).casefold() == wanted
            ),
            "",
        )
        slug = self._genre_slug(genre_url)
        if not slug:
            return []
        page_soup = self._get_soup(
            f"/genres/{quote(slug, safe='-')}",
            params={"page": max(1, int(page))},
        )
        return self._parse_results(page_soup)

    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        slug = self._movie_slug(url_or_slug)
        if not slug:
            return None
        url = f"{BASE_URL}/movies/{quote(slug, safe='-')}"
        soup = self._get_soup(url)
        # Das ausgelieferte Markup enthält dekorative Container, die der
        # Python-HTML-Parser früher schließt als ein Browser. Die semantischen
        # Detailknoten sind deshalb bewusst global und über ihre Klassen gewählt.
        title_node = soup.select_one("h1")
        if title_node is None:
            return None

        title = " ".join(title_node.get_text(" ", strip=True).split())
        description_node = soup.select_one(".movie-detail-synopsis")
        description = description_node.get_text(" ", strip=True) if description_node else ""
        genres = list(dict.fromkeys(
            " ".join(link.get_text(" ", strip=True).split())
            for link in soup.select('.ft-meta-label a[href*="/genres/"]')
            if link.get_text(strip=True)
        ))
        metadata_text = " ".join(
            node.get_text(" ", strip=True)
            for node in soup.select(".ft-meta-label")
        )
        year_match = re.search(r"\b(?:19|20)\d{2}\b", metadata_text)
        runtime_match = re.search(r"\b(?:(\d+)\s*h\s*)?(\d+)\s*min\b", metadata_text, re.IGNORECASE)
        runtime = ""
        if runtime_match:
            minutes = int(runtime_match.group(2)) + int(runtime_match.group(1) or 0) * 60
            runtime = f"{minutes} min"
        poster = soup.select_one(".movie-poster-modal__img[data-src], img[src*='/img/poster/']")
        cover_url = urljoin(BASE_URL + "/", poster.get("data-src") or poster.get("src") or "") if poster else ""

        hosters = self._resolve_hosters(soup, url)
        if not hosters:
            self._log(f"  Filmo: keine abspielbaren Hoster fuer {title}")
            return None
        return FilmpalastMovie(
            title=title,
            url=url,
            year=year_match.group(0) if year_match else "",
            runtime=runtime,
            cover_url=cover_url,
            description=description,
            genres=genres,
            hosters=hosters,
        )

    def search_series(self, query: str) -> List:
        return []

    def list_series(self, page: int = 1) -> List:
        return []

    def _resolve_hosters(self, soup: BeautifulSoup, referer: str) -> List[HosterInfo]:
        token_cookie = unquote(self.session.cookies.get("XSRF-TOKEN", ""))
        headers = {
            "Accept": "application/json",
            "Origin": BASE_URL,
            "Referer": referer,
        }
        if token_cookie:
            headers["X-XSRF-TOKEN"] = token_cookie
        hosters: List[HosterInfo] = []
        seen: set[str] = set()
        for chip in soup.select("[data-provider-chip][data-p]"):
            payload = chip.get("data-p", "").strip()
            if not payload:
                continue
            row = chip.find_parent(class_="provider-row")
            language_node = row.select_one(".provider-row__lang") if row else None
            language = language_node.get_text(" ", strip=True) if language_node else ""
            name_node = chip.select_one(".provider-chip__name")
            name = name_node.get_text(" ", strip=True) if name_node else chip.get("aria-label", "Filmo")
            tags = [tag.get_text(" ", strip=True) for tag in chip.select(".provider-chip__metadata-tag")]
            quality = next((tag for tag in reversed(tags) if re.search(r"\d+p|HD|UHD|4K", tag, re.I)), "")
            try:
                minted = self.session.post(
                    f"{BASE_URL}/n", json={"p": payload}, headers=headers, timeout=25,
                )
                minted.raise_for_status()
                token = str(minted.json().get("x") or "").strip()
                if not token:
                    continue
                opened = self.session.get(
                    f"{BASE_URL}/n/{quote(token, safe='')}",
                    headers={"Referer": referer}, timeout=25, allow_redirects=False,
                )
                play_url = urljoin(BASE_URL + "/", opened.headers.get("Location", ""))
            except Exception as exc:
                self._log(f"  Filmo-Hoster {name} uebersprungen: {exc}")
                continue
            parsed = urlparse(play_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.endswith("filmo.to"):
                continue
            if play_url in seen:
                continue
            seen.add(play_url)
            hosters.append(HosterInfo(name=name, url=play_url, language=language, quality=quality))
        return hosters

    def _get_soup(self, path_or_url: str, params: Optional[dict] = None) -> BeautifulSoup:
        url = urljoin(BASE_URL + "/", path_or_url)
        response = self.session.get(
            url,
            params=params,
            timeout=25,
            headers={"Accept": "text/html,application/xhtml+xml,*/*"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.select_one("title") is None:
            raise RuntimeError("Filmo lieferte keine gueltige HTML-Seite")
        return soup

    @classmethod
    def _parse_results(cls, soup: BeautifulSoup) -> List[FilmpalastSearchResult]:
        results: List[FilmpalastSearchResult] = []
        seen: set[str] = set()
        for link in soup.select('a[href*="/movies/"]'):
            url = urljoin(BASE_URL + "/", link.get("href", ""))
            slug = cls._movie_slug(url)
            if not slug or slug in seen:
                continue
            title_node = link.select_one(
                ".movie-poster-grid-card__title, .popular-spotlight-card__title"
            )
            image = link.select_one("img")
            title = (
                title_node.get_text(" ", strip=True) if title_node
                else image.get("alt", "").strip() if image
                else ""
            )
            if not title:
                continue
            seen.add(slug)
            cover_url = urljoin(BASE_URL + "/", image.get("src", "")) if image else ""
            results.append(FilmpalastSearchResult(
                title=f"{' '.join(title.split())}  [Filmo]",
                slug=f"{SOURCE_PREFIX}{slug}",
                url=url,
                is_movie=True,
                cover_url=cover_url,
            ))
        return results

    @staticmethod
    def _movie_slug(value: str) -> str:
        raw = str(value or "").strip()
        if raw.casefold().startswith(SOURCE_PREFIX):
            raw = raw[len(SOURCE_PREFIX):]
        parsed = urlparse(raw)
        if parsed.scheme or parsed.netloc:
            match = _MOVIE_PATH_RE.match(parsed.path.rstrip("/"))
            return match.group(1).casefold() if match else ""
        return raw.strip("/").casefold() if re.fullmatch(r"[a-z0-9-]+", raw, re.I) else ""

    @staticmethod
    def _genre_slug(value: str) -> str:
        path = urlparse(str(value or "")).path.rstrip("/")
        match = re.search(r"/genres/([a-z0-9-]+)$", path, re.IGNORECASE)
        return match.group(1).casefold() if match else ""
