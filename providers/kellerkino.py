"""KellerKino movie-only adapter."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, urljoin, urlparse

from providers.models import FilmpalastMovie, FilmpalastSearchResult
from providers.sentinel_runtime import monitor_adapter
from providers.source_utils import CachedHTTP, hoster

BASE_URL = "https://www.kellerkino.com"
SOURCE_PREFIX = "kellerkino:"


@monitor_adapter("kellerkino")
class KellerKinoScraper:
    def __init__(self, progress_cb=None, health=None):
        self._log = progress_cb or logging.getLogger(__name__).info
        self.http = CachedHTTP("kellerkino", health)
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
        result, seen = [], set()
        for card in soup.select("article.movie-card"):
            anchor = card.select_one("h2 a[href]")
            if not anchor:
                continue
            url = anchor["href"]
            if url in seen or urlparse(url).hostname not in ("www.kellerkino.com", "kellerkino.com"):
                continue
            seen.add(url)
            title = anchor.get_text(" ", strip=True)
            year = re.search(r"\b(?:19|20)\d{2}\b", card.get_text(" ", strip=True))
            image = card.select_one(".movie-thumb img")
            if title:
                result.append(FilmpalastSearchResult(title, SOURCE_PREFIX + urlparse(url).path,
                    url, year=year.group() if year else "", provider="kellerkino",
                    content_language="de", cover_url=urljoin(BASE_URL, image.get("src", "")) if image else ""))
        return result

    def search(self, query):
        return self._cards(self._soup("/seite/1/?s=" + quote(query)))

    def list_movies(self, category="new", page=1):
        return self._cards(self._soup("/archiv/" if page == 1 else f"/archiv/seite/{page}/"))

    def list_genres(self):
        return []

    def list_by_genre(self, genre, page=1):
        return []

    def get_movie(self, value):
        path = str(value or "").removeprefix(SOURCE_PREFIX)
        if not path.startswith("/") or urlparse(path).netloc:
            return None
        soup = self._soup(path)
        detail = soup.select_one("article.movie-detail")
        if not detail:
            return None
        title_tag = detail.select_one("h1")
        if not title_tag:
            return None
        title = title_tag.get_text(" ", strip=True)
        metadata = {row.select_one("dt").get_text(" ", strip=True).rstrip(":"): row.select_one("dd").get_text(" ", strip=True)
            for row in soup.select(".info-list > div") if row.select_one("dt") and row.select_one("dd")}
        links, seen = [], set()
        for iframe in soup.select("iframe[src]"):
            url = urljoin(BASE_URL, iframe["src"])
            hostname = (urlparse(url).hostname or "").lower()
            if url in seen or hostname in {"youtube.com", "youtu.be"} or hostname.endswith(".youtube.com"):
                continue
            candidate = hoster(url)
            if candidate:
                links.append(candidate)
                seen.add(url)
        poster = soup.select_one(".poster-box img[src]")
        return FilmpalastMovie(title, urljoin(BASE_URL, path), year=metadata.get("Jahr", ""),
            runtime=metadata.get("Laufzeit", ""),
            description=(soup.select_one("section.movie-description").get_text(" ", strip=True)
                if soup.select_one("section.movie-description") else ""),
            genres=[x.strip() for x in metadata.get("Genre", "").split(",") if x.strip()],
            cover_url=urljoin(BASE_URL, poster["src"]) if poster else "",
            hosters=links, provider="kellerkino", content_language="de") if title and links else None
