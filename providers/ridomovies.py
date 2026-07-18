"""Scraper für den englischsprachigen Ridomovies-Katalog.

Ridomovies stellt Suche und aktuelle Katalogseiten als JSON bereit. Details,
Staffeln, Episoden und die Playerliste liegen im serverseitig erzeugten HTML.
Die Player-Templates werden nur in normalisierte Embed-URLs umgewandelt; die
eigentliche Stream-Auflösung übernimmt der gemeinsame Extraktor.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlsplit,
    urlunsplit,
)

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

BASE_URL = os.environ.get(
    "RIDOMOVIES_BASE_URL",
    "https://ridomovies.su",
).strip().rstrip("/")
SOURCE_PREFIX = "ridomovies:"
API_LANGUAGE = "en"

GENRES: Dict[str, str] = {
    "Action": "action",
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
    "Music": "music",
    "Mystery": "mystery",
    "Romance": "romance",
    "Sci-Fi": "sci-fi",
    "Thriller": "thriller",
    "TV Movie": "tvmovie",
    "War": "war",
    "Western": "western",
}

_KNOWN_HOSTS = frozenset({"ridomovies.su", "ridomovies.tv"})
_SITE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,190}$", re.I)
_MEDIA_PATH_RE = re.compile(
    r"/(?P<kind>movie|tv)/(?P<slug>[a-z0-9][a-z0-9-]*)/?",
    re.I,
)
_EPISODE_PATH_RE = re.compile(
    r"/tv/(?P<slug>[a-z0-9][a-z0-9-]*)/"
    r"season-(?P<season>\d{1,2})/episode-(?P<episode>\d{1,3})/?",
    re.I,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_ISO_DURATION_RE = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$",
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


class RidomoviesScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.base_url = BASE_URL
        self.session = cr.Session(impersonate="chrome136")
        base_host = (urlparse(self.base_url).hostname or "").casefold()
        self._allowed_hosts = set(_KNOWN_HOSTS)
        if base_host:
            self._allowed_hosts.add(base_host)

    # ------------------------------------------------------------------
    # Katalog und Suche
    # ------------------------------------------------------------------
    def search(self, query: str) -> List[FilmpalastSearchResult]:
        rows = self._search_rows(query)
        results = [
            self._movie_result(card)
            for card in (self._card_from_row(row) for row in rows)
            if card is not None and card.is_movie
        ]
        self._log(f"  Ridomovies: {len(results)} englische Film(e) gefunden")
        return results

    def search_series(self, query: str) -> List[FilmpalastSeriesResult]:
        rows = self._search_rows(query)
        results = [
            self._series_result(card)
            for card in (self._card_from_row(row) for row in rows)
            if card is not None and not card.is_movie
        ]
        self._log(f"  Ridomovies: {len(results)} englische Serie(n) gefunden")
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
            soup = self._get_soup("/home-rd1")
            cards = self._parse_cards(
                soup.select_one(".highlights-slider") or soup
            )
            return [
                self._movie_result(card)
                for card in cards
                if card.is_movie
            ]

        data = self._get_json(
            "/api/movies/latest",
            params={"page": page, "limit": 32, "lang": API_LANGUAGE},
        )
        rows = data.get("movies", []) if isinstance(data, dict) else []
        return [
            self._movie_result(card)
            for card in (
                self._card_from_row(row)
                for row in rows
                if isinstance(row, dict)
            )
            if card is not None and card.is_movie
        ]

    def list_series(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        page = max(1, int(page or 1))
        data = self._get_json(
            "/api/tv/latest",
            params={"page": page, "limit": 32, "lang": API_LANGUAGE},
        )
        rows = data.get("series", []) if isinstance(data, dict) else []
        return [
            self._series_result(card)
            for card in (
                self._card_from_row(row)
                for row in rows
                if isinstance(row, dict)
            )
            if card is not None and not card.is_movie
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
            (
                slug
                for label, slug in GENRES.items()
                if label.casefold() == genre_key
            ),
            "",
        )
        if not genre_slug:
            return []
        page = max(1, int(page or 1))
        suffix = f"/page-{page}" if page > 1 else ""
        cards = self._parse_cards(
            self._get_soup(f"/genre/{genre_slug}/movie{suffix}")
        )
        return [self._movie_result(card) for card in cards if card.is_movie]

    def _search_rows(self, query: str) -> List[dict]:
        query = " ".join(str(query or "").split()).strip()
        if not query:
            return []
        self._log(f"Ridomovies Suche: {query}")
        data = self._get_json(
            "/api/search",
            params={"q": query, "lang": API_LANGUAGE, "limit": 20},
        )
        rows = data.get("data", []) if isinstance(data, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    # ------------------------------------------------------------------
    # Details, Staffeln und Player
    # ------------------------------------------------------------------
    def get_movie(self, value: str) -> Optional[FilmpalastMovie]:
        site_slug, season, episode = self._value_parts(value)
        if not site_slug:
            return None

        if season is not None and episode is not None:
            path = (
                f"/tv/{site_slug}/season-{season}/episode-{episode}"
            )
        else:
            path = f"/movie/{site_slug}"
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        self._log(f"Lade Ridomovies: {url}")
        soup = self._get_soup(path)
        metadata = self._metadata(soup, episode=episode is not None)
        if not metadata["title"]:
            return None

        title = metadata["title"]
        if season is not None and episode is not None:
            title = f"{title} S{season:02d}E{episode:02d}"
        hosters = self._hosters(soup)
        if not hosters:
            self._log("  Ridomovies: keine Player für diesen Eintrag gefunden")
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

    def get_series(self, value: str) -> Optional[FilmpalastSeries]:
        site_slug = self._site_slug(value)
        if not site_slug:
            return None
        path = f"/tv/{site_slug}"
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        self._log(f"Lade Serie (Ridomovies): {url}")
        soup = self._get_soup(path)
        metadata = self._metadata(soup)
        if not metadata["title"]:
            return None

        season_numbers = sorted({
            self._positive_int(node.get("data-season-number"))
            for node in soup.select(
                ".season-tabs [data-season-number]"
            )
        } - {0})
        seasons: Dict[int, List[SeriesEpisode]] = {}
        initial_episodes = self._parse_episodes(soup, site_slug)
        for item in initial_episodes:
            seasons.setdefault(item.season, []).append(item)

        for season in season_numbers:
            if season in seasons:
                continue
            try:
                data = self._get_json(
                    f"{path}/season-{season}",
                    referer=url,
                    ajax=True,
                )
                html = (
                    str(data.get("episodesHtml") or "")
                    if isinstance(data, dict)
                    else ""
                )
                episode_soup = BeautifulSoup(html, "lxml")
                episodes = self._parse_episodes(
                    episode_soup,
                    site_slug,
                    expected_season=season,
                )
            except Exception as exc:
                self._log(
                    f"  Ridomovies Staffel {season} übersprungen: {exc}"
                )
                continue
            if episodes:
                seasons[season] = episodes

        seasons = {
            season: sorted(
                {item.episode: item for item in episodes}.values(),
                key=lambda item: item.episode,
            )
            for season, episodes in sorted(seasons.items())
            if episodes
        }
        if not seasons:
            return None
        total = sum(len(episodes) for episodes in seasons.values())
        self._log(
            f"  Serie (Ridomovies): «{metadata['title']}» – "
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

    def _hosters(self, soup: BeautifulSoup) -> List[HosterInfo]:
        config = soup.select_one("#detailConfig[data-videos]")
        rows: Iterable[dict] = ()
        imdb_id = ""
        if config:
            imdb_id = str(config.get("data-imdb-id") or "").strip()
            try:
                decoded = json.loads(str(config.get("data-videos") or "[]"))
                if isinstance(decoded, list):
                    rows = [row for row in decoded if isinstance(row, dict)]
            except (TypeError, ValueError, json.JSONDecodeError):
                rows = ()

        hosters: List[HosterInfo] = []
        seen = set()
        identities: Dict[tuple[str, str, str], HosterInfo] = {}
        for row in rows:
            video_id = str(
                row.get("video_id") or row.get("video") or ""
            ).strip()
            template = str(row.get("template") or "").strip()
            if not video_id or not template:
                continue
            embed = (
                template
                .replace("{{id}}", video_id)
                .replace("{id}", video_id)
                .replace("{url}", video_id)
            )
            url = self._embed_url(embed)
            if not url:
                continue
            url = self._with_imdb_id(url, imdb_id)
            if url in seen:
                continue
            seen.add(url)
            name = str(
                row.get("service_name")
                or row.get("title")
                or self._hoster_name(url)
            ).strip()
            hoster = HosterInfo(
                name=name or self._hoster_name(url),
                url=url,
                language="English",
                quality=str(row.get("quality") or "HD").strip(),
            )
            hosters.append(hoster)
            identities[self._embed_identity(url)] = hoster

        for node in soup.select(
            "#player-cover[data-embed], "
            ".server-dropdown-item[data-server-embed]"
        ):
            embed = str(
                node.get("data-embed")
                or node.get("data-server-embed")
                or ""
            )
            url = self._with_imdb_id(self._embed_url(embed), imdb_id)
            if not url:
                continue
            identity = self._embed_identity(url)
            existing = identities.get(identity)
            if existing is not None:
                if urlparse(url).query and not urlparse(existing.url).query:
                    seen.discard(existing.url)
                    existing.url = url
                    seen.add(url)
                continue
            if url in seen:
                continue
            seen.add(url)
            hoster = HosterInfo(
                name=self._hoster_name(url),
                url=url,
                language="English",
                quality="HD",
            )
            hosters.append(hoster)
            identities[identity] = hoster
        # Rapidrame liefert aktuell einen abfangbaren HLS-Request. Closeload
        # veröffentlicht dagegen zusätzlich eine veraltete master.txt-URL,
        # die generische Regex-Extraktoren als falschen Treffer lesen können.
        return sorted(
            hosters,
            key=lambda item: (
                0 if item.name.casefold() == "rapidrame" else 1,
            ),
        )

    def _parse_episodes(
        self,
        soup: BeautifulSoup,
        site_slug: str,
        expected_season: Optional[int] = None,
    ) -> List[SeriesEpisode]:
        episodes: List[SeriesEpisode] = []
        seen = set()
        for link in soup.select("a.episode-link[href], a[href*='/episode-']"):
            href = urljoin(self.base_url + "/", str(link.get("href") or ""))
            match = _EPISODE_PATH_RE.search(urlparse(href).path)
            if not match:
                continue
            if match.group("slug").casefold() != site_slug.casefold():
                continue
            season = int(match.group("season"))
            episode = int(match.group("episode"))
            if expected_season is not None and season != expected_season:
                continue
            identity = (season, episode)
            if identity in seen:
                continue
            seen.add(identity)
            name_node = link.select_one(".ep-name-row")
            release_name = (
                name_node.get_text(" ", strip=True)
                if name_node
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
        return sorted(episodes, key=lambda item: (item.season, item.episode))

    # ------------------------------------------------------------------
    # Parser- und HTTP-Helfer
    # ------------------------------------------------------------------
    def _request(
        self,
        url_or_path: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
    ):
        url = (
            str(url_or_path)
            if str(url_or_path).lower().startswith(("http://", "https://"))
            else urljoin(self.base_url + "/", str(url_or_path).lstrip("/"))
        )
        self._validate_source_url(url)
        request_headers = {
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.base_url + "/",
        }
        request_headers.update(headers or {})
        response = self.session.get(
            url,
            params=params or {},
            headers=request_headers,
            timeout=30,
            allow_redirects=True,
        )
        if response.status_code in (520, 521, 522, 523, 524):
            raise RuntimeError(
                f"Ridomovies-Domain nicht erreichbar ({response.status_code})"
            )
        response.raise_for_status()
        self._validate_source_url(str(response.url))
        return response

    def _get_soup(
        self,
        url_or_path: str,
        params: Optional[dict] = None,
    ) -> BeautifulSoup:
        response = self._request(
            url_or_path,
            params=params,
            headers={
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            },
        )
        soup = BeautifulSoup(response.text, "lxml")
        title = (
            soup.title.get_text(" ", strip=True).casefold()
            if soup.title
            else ""
        )
        if "just a moment" in title or "attention required" in title:
            raise RuntimeError("Ridomovies Cloudflare-Sperre aktiv")
        return soup

    def _get_json(
        self,
        url_or_path: str,
        params: Optional[dict] = None,
        referer: str = "",
        ajax: bool = False,
    ):
        headers = {"Accept": "application/json"}
        if referer:
            headers["Referer"] = referer
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["X-Content-Mode"] = "episodes_only"
        response = self._request(
            url_or_path,
            params=params,
            headers=headers,
        )
        try:
            return response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Ridomovies lieferte keine gültige JSON-Antwort"
            ) from exc

    def _validate_source_url(self, value: str) -> None:
        parsed = urlparse(str(value or ""))
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or host not in self._allowed_hosts:
            raise ValueError(
                "Ridomovies-URL liegt außerhalb der konfigurierten Domain"
            )

    def _parse_cards(self, container) -> List[_Card]:
        cards: List[_Card] = []
        seen = set()
        for item in container.select(".movie-card, .highlight-card"):
            link = item.select_one(
                "a[href*='/movie/'], a[href*='/tv/']"
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
            title_node = item.select_one(".movie-title, .highlight-title")
            title = (
                title_node.get_text(" ", strip=True)
                if title_node
                else str(link.get("aria-label") or "").strip()
            )
            if not title:
                continue
            year_node = item.select_one(".movie-year")
            year = (
                self._year(year_node.get_text(" ", strip=True))
                if year_node
                else ""
            )
            image = item.select_one("img")
            cover_url = self._asset_url(
                str(
                    image.get("src")
                    or image.get("data-src")
                    or ""
                ).strip()
                if image
                else ""
            )
            cards.append(_Card(
                title=title,
                site_slug=site_slug,
                url=href,
                year=year,
                cover_url=cover_url,
                is_movie=kind == "movie",
            ))
        return cards

    def _card_from_row(self, row: dict) -> Optional[_Card]:
        media_type = str(row.get("type") or "").strip().casefold()
        if media_type not in {"movie", "tv"}:
            return None
        site_slug = str(
            row.get("slug") or row.get("slug_en") or ""
        ).strip()
        if not _SITE_SLUG_RE.fullmatch(site_slug):
            return None
        title = " ".join(
            str(row.get("title") or row.get("original_title") or "").split()
        )
        if not title:
            return None
        path = str(row.get("url") or "").strip()
        if not path:
            path = f"/{'movie' if media_type == 'movie' else 'tv'}/{site_slug}"
        url = urljoin(self.base_url + "/", path)
        match = _MEDIA_PATH_RE.search(urlparse(url).path)
        if (
            not match
            or match.group("slug").casefold() != site_slug.casefold()
            or match.group("kind").casefold() != media_type
        ):
            return None
        return _Card(
            title=title,
            site_slug=site_slug,
            url=url,
            year=self._year(
                row.get("release_date") or row.get("first_air_date")
            ),
            cover_url=self._asset_url(row.get("poster_path")),
            is_movie=media_type == "movie",
        )

    def _metadata(self, soup: BeautifulSoup, episode: bool = False) -> dict:
        ld_items = self._json_ld_items(soup)
        primary_types = ("TVSeries",) if episode else ("Movie", "TVSeries")
        primary = next(
            (
                item
                for wanted in primary_types
                for item in ld_items
                if str(item.get("@type") or "").casefold()
                == wanted.casefold()
            ),
            {},
        )
        episode_data = next(
            (
                item
                for item in ld_items
                if str(item.get("@type") or "").casefold() == "tvepisode"
            ),
            {},
        )

        title = " ".join(str(primary.get("name") or "").split())
        if not title:
            title_node = soup.select_one(
                ".movie-title-main, #hero-section h1, main h1"
            )
            title = (
                title_node.get_text(" ", strip=True)
                if title_node
                else ""
            )
            title = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", title)

        year = self._year(
            primary.get("datePublished") or primary.get("startDate")
        )
        if not year:
            heading = soup.select_one(".movie-title-main, #hero-section h1")
            year = self._year(
                heading.get_text(" ", strip=True) if heading else ""
            )

        duration = (
            episode_data.get("timeRequired")
            if episode
            else primary.get("duration")
        )
        runtime = self._runtime(duration)
        if not runtime:
            for node in soup.select(".meta-info"):
                text = node.get_text(" ", strip=True)
                if re.match(r"^Duration:", text, re.I):
                    runtime = re.sub(
                        r"^Duration:\s*",
                        "",
                        text,
                        flags=re.I,
                    )
                    break

        description_node = soup.select_one(
            ".movie-overview, .overview-text"
        )
        description = (
            description_node.get_text(" ", strip=True)
            if description_node
            else " ".join(str(primary.get("description") or "").split())
        )

        genres = primary.get("genre") or []
        if isinstance(genres, str):
            genres = [item.strip() for item in genres.split(",")]
        genres = [
            " ".join(str(item).split())
            for item in genres
            if " ".join(str(item).split())
        ]
        if not genres:
            genres = [
                node.get_text(" ", strip=True)
                for node in soup.select(
                    "#hero-section a[href*='/genre/'], "
                    ".movie-details a[href*='/genre/']"
                )
                if node.get_text(" ", strip=True)
            ]

        image = soup.select_one(".movie-poster-img, .tv-poster")
        cover_url = self._asset_url(
            image.get("src") if image else primary.get("image")
        )
        return {
            "title": title,
            "year": year,
            "runtime": runtime,
            "cover_url": cover_url,
            "description": description,
            "genres": list(dict.fromkeys(genres)),
        }

    @staticmethod
    def _json_ld_items(soup: BeautifulSoup) -> List[dict]:
        result: List[dict] = []
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(node.get_text())
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            candidates = value if isinstance(value, list) else [value]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                graph = item.get("@graph")
                if isinstance(graph, list):
                    result.extend(
                        entry for entry in graph if isinstance(entry, dict)
                    )
                else:
                    result.append(item)
        return result

    def _movie_result(self, card: _Card) -> FilmpalastSearchResult:
        return FilmpalastSearchResult(
            title=f"{card.title}  [Ridomovies]",
            slug=f"{SOURCE_PREFIX}{card.site_slug}",
            url=card.url,
            year=card.year,
            is_movie=True,
        )

    def _series_result(self, card: _Card) -> FilmpalastSeriesResult:
        value = f"{SOURCE_PREFIX}{card.site_slug}"
        return FilmpalastSeriesResult(
            title=f"{card.title}  [Ridomovies]",
            base_slug=value,
            sample_slug=value,
            sample_url=card.url,
            year=card.year,
            cover_url=card.cover_url,
        )

    def _value_parts(
        self,
        value: str,
    ) -> tuple[str, Optional[int], Optional[int]]:
        raw = str(value or "").strip()
        if raw.lower().startswith(("http://", "https://")):
            path = urlparse(raw).path
            match = _EPISODE_PATH_RE.search(path)
            if match:
                return (
                    match.group("slug"),
                    int(match.group("season")),
                    int(match.group("episode")),
                )
            media_match = _MEDIA_PATH_RE.search(path)
            if media_match and media_match.group("kind").casefold() == "movie":
                return media_match.group("slug"), None, None
            return "", None, None

        parsed = parse_episode_slug(raw)
        if parsed:
            base, season, episode = parsed
            site_slug = self._site_slug(base)
            return site_slug, season, episode
        return self._site_slug(raw), None, None

    def _site_slug(self, value: str) -> str:
        raw = str(value or "").strip()
        if raw.casefold().startswith(SOURCE_PREFIX):
            raw = raw[len(SOURCE_PREFIX):]
        if raw.lower().startswith(("http://", "https://")):
            match = _MEDIA_PATH_RE.search(urlparse(raw).path)
            raw = match.group("slug") if match else ""
        raw = raw.strip().strip("/")
        return raw if _SITE_SLUG_RE.fullmatch(raw) else ""

    def _asset_url(self, value) -> str:
        url = str(value or "").strip()
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            return urljoin(self.base_url + "/", url.lstrip("/"))
        parsed = urlparse(url)
        return url if parsed.scheme in ("http", "https") and parsed.netloc else ""

    @staticmethod
    def _embed_url(embed: str) -> str:
        soup = BeautifulSoup(str(embed or ""), "lxml")
        iframe = soup.select_one("iframe")
        value = (
            str(iframe.get("src") or iframe.get("data-src") or "").strip()
            if iframe
            else ""
        )
        if value.startswith("//"):
            value = "https:" + value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return ""
        return value

    @staticmethod
    def _with_imdb_id(url: str, imdb_id: str) -> str:
        if not url or not imdb_id or "closeload" not in urlparse(url).netloc.casefold():
            return url
        split = urlsplit(url)
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        query.setdefault("imdb_id", imdb_id)
        return urlunsplit((
            split.scheme,
            split.netloc,
            split.path,
            urlencode(query),
            split.fragment,
        ))

    @staticmethod
    def _embed_identity(url: str) -> tuple[str, str, str]:
        parsed = urlparse(url)
        return (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/").casefold(),
        )

    @staticmethod
    def _hoster_name(url: str) -> str:
        host = (urlparse(url).hostname or "").casefold()
        if "ridorapid" in host:
            return "Rapidrame"
        if "closeload" in host:
            return "Closeload"
        return (
            host.removeprefix("www.").split(".")[0]
            .replace("-", " ").title()
            or "Ridomovies"
        )

    @staticmethod
    def _year(value) -> str:
        match = _YEAR_RE.search(str(value or ""))
        return match.group(0) if match else ""

    @staticmethod
    def _runtime(value) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        match = _ISO_DURATION_RE.fullmatch(text)
        if not match:
            return f"{text} min" if text.isdigit() else text
        minutes = (
            int(match.group("hours") or 0) * 60
            + int(match.group("minutes") or 0)
        )
        return f"{minutes} min" if minutes else ""

    @staticmethod
    def _positive_int(value) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0
