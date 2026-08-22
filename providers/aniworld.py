"""AniWorld.to provider for German anime and German subtitles."""

from __future__ import annotations

import html
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from providers.models import FilmpalastMovie, HosterInfo, parse_episode_slug

BASE_URL = "https://aniworld.to"
SOURCE_PREFIX = "aniworld:"
REDIRECT_MARKER = "/redirect/"
TRACK_LANGUAGE_IDS = {"dub": "1", "eng": "2", "sub": "3"}
TRACK_LABELS = {
    "dub": "Deutsch Dub",
    "sub": "Deutsch Sub",
    "eng": "Englisch",
}


@dataclass
class AniWorldEpisode:
    season: int
    number: int
    title: str = ""
    tracks: tuple[str, ...] = ()


@dataclass
class AniWorldAnime:
    id: str
    title: str
    media_type: str = "Anime"
    year: str = ""
    cover_url: str = ""
    banner_url: str = ""
    description: str = ""
    genres: list[str] = field(default_factory=list)
    rating: float | None = None
    translations: dict[str, int] = field(default_factory=dict)
    episodes: list[AniWorldEpisode] = field(default_factory=list)
    provider: str = "aniworld"
    content_language: str = "de"

    def public_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("episodes", None)
        payload["episode_count"] = len(self.episodes) or max(
            self.translations.values(),
            default=0,
        )
        return payload


class AniWorldScraper:
    def __init__(
        self,
        progress_cb: Callable[[str], None] | None = None,
        session: requests.Session | None = None,
    ):
        self._log = progress_cb or (lambda _message: None)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "Mozilla/5.0",
            }
        )
        self._detail_cache: dict[str, tuple[float, AniWorldAnime]] = {}
        self._detail_lock = threading.RLock()

    @staticmethod
    def _abs(value: str) -> str:
        return urljoin(f"{BASE_URL}/", str(value or "").strip())

    def _soup(self, url: str) -> BeautifulSoup:
        response = self.session.get(url, timeout=25)
        response.raise_for_status()
        return BeautifulSoup(response.content, "lxml")

    def browse(
        self,
        mode: str = "latest",
        query: str = "",
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        page = max(1, int(page))
        limit = max(1, min(50, int(limit)))
        mode = mode if mode in {"latest", "popular", "trending", "search"} else "latest"
        if mode == "search":
            entries = self._search(query)
        else:
            url = {
                "latest": f"{BASE_URL}/neu",
                "popular": f"{BASE_URL}/beliebte-animes",
                "trending": BASE_URL,
            }[mode]
            entries = self._parse_cards(self._soup(url))
        start = (page - 1) * limit
        selected = entries[start : start + limit]
        return {
            "results": [entry.public_dict() for entry in selected],
            "page": page,
            "has_more": start + limit < len(entries),
            "total": len(entries),
        }

    def _search(self, query: str) -> list[AniWorldAnime]:
        query = str(query or "").strip()
        if not query:
            return []
        response = self.session.post(
            f"{BASE_URL}/ajax/search",
            data={"keyword": query},
            headers={
                "Referer": f"{BASE_URL}/search",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=25,
        )
        response.raise_for_status()
        entries: list[AniWorldAnime] = []
        seen: set[str] = set()
        for item in response.json() or []:
            link = str(item.get("link") or "")
            match = re.fullmatch(r"/anime/stream/([a-z0-9-]+)", link)
            if not match or match.group(1) in seen:
                continue
            slug = match.group(1)
            title = BeautifulSoup(str(item.get("title") or ""), "html.parser").get_text(
                " ",
                strip=True,
            )
            if not title:
                continue
            seen.add(slug)
            entries.append(AniWorldAnime(id=slug, title=title))
        return entries

    def _parse_cards(self, soup: BeautifulSoup) -> list[AniWorldAnime]:
        entries: list[AniWorldAnime] = []
        seen: set[str] = set()
        for anchor in soup.select('a[href^="/anime/stream/"]'):
            match = re.fullmatch(
                r"/anime/stream/([a-z0-9-]+)",
                str(anchor.get("href") or "").rstrip("/"),
            )
            if not match or match.group(1) in seen:
                continue
            slug = match.group(1)
            heading = anchor.select_one("h3")
            image = anchor.select_one("img")
            title = (heading.get_text(" ", strip=True) if heading else "") or str(
                image.get("alt") if image else ""
            ).split(" Cover", 1)[0].strip()
            if not title:
                title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            cover = ""
            if image:
                cover = next(
                    (
                        str(image.get(key) or "").strip()
                        for key in ("data-src", "src")
                        if str(image.get(key) or "").strip()
                        and not str(image.get(key) or "").startswith("data:")
                    ),
                    "",
                )
            seen.add(slug)
            entries.append(
                AniWorldAnime(
                    id=slug,
                    title=title,
                    cover_url=self._abs(cover) if cover else "",
                )
            )
        return entries

    def get_anime(self, anime_id: str, force: bool = False) -> AniWorldAnime:
        anime_id = self._normalize_id(anime_id)
        with self._detail_lock:
            cached = self._detail_cache.get(anime_id)
            if cached and not force and time.time() - cached[0] < 300:
                return cached[1]

        base_url = f"{BASE_URL}/anime/stream/{anime_id}"
        soup = self._soup(base_url)
        title_node = soup.select_one("h1[itemprop=name]") or soup.find("h1")
        if not title_node:
            raise LookupError("AniWorld-Anime nicht gefunden.")
        title = title_node.get_text(" ", strip=True)
        cover_node = soup.select_one(".seriesCoverBox img")
        cover = self._image_source(cover_node)
        year_node = soup.select_one("[itemprop=startDate]")
        year_match = re.search(
            r"\b(19|20)\d{2}\b", year_node.get_text(" ") if year_node else ""
        )
        description_node = soup.select_one("[itemprop=description]")
        description = (
            description_node.get_text(" ", strip=True) if description_node else ""
        )
        genres = list(
            dict.fromkeys(
                anchor.get_text(" ", strip=True)
                for anchor in soup.select('a[href*="/genre/"]')
                if anchor.get_text(" ", strip=True)
            )
        )
        season_numbers = sorted(
            {
                int(match)
                for match in re.findall(
                    rf"/anime/stream/{re.escape(anime_id)}/staffel-(\d+)",
                    str(soup),
                )
                if int(match) > 0
            }
        ) or [1]

        episodes: list[AniWorldEpisode] = []
        for season in season_numbers:
            season_soup = (
                soup if season == 1 else self._soup(f"{base_url}/staffel-{season}")
            )
            episodes.extend(self._episodes_from_soup(season_soup, season))
        translations = {
            track: sum(track in episode.tracks for episode in episodes)
            for track in TRACK_LANGUAGE_IDS
        }
        translations = {key: value for key, value in translations.items() if value}
        anime = AniWorldAnime(
            id=anime_id,
            title=title,
            year=year_match.group(0) if year_match else "",
            cover_url=self._abs(cover) if cover else "",
            banner_url=self._abs(cover) if cover else "",
            description=description,
            genres=genres,
            translations=translations,
            episodes=episodes,
        )
        with self._detail_lock:
            self._detail_cache[anime_id] = (time.time(), anime)
        return anime

    @staticmethod
    def _image_source(node) -> str:
        if node is None:
            return ""
        return next(
            (
                str(node.get(key) or "").strip()
                for key in ("data-src", "src")
                if str(node.get(key) or "").strip()
                and not str(node.get(key) or "").startswith("data:")
            ),
            "",
        )

    @staticmethod
    def _episodes_from_soup(soup: BeautifulSoup, season: int) -> list[AniWorldEpisode]:
        episodes: list[AniWorldEpisode] = []
        seen: set[int] = set()
        for row in soup.select("table.seasonEpisodesList tbody tr"):
            link = row.select_one('a[href*="/episode-"]')
            match = re.search(r"/episode-(\d+)", str(link.get("href") if link else ""))
            if not match or int(match.group(1)) in seen:
                continue
            number = int(match.group(1))
            seen.add(number)
            title_node = row.select_one(".seasonEpisodeTitle")
            sources = " ".join(
                str(image.get("src") or "") for image in row.select("img.flag")
            ).casefold()
            tracks = tuple(
                track
                for track, marker in (
                    ("dub", "german.svg"),
                    ("sub", "japanese-german.svg"),
                    ("eng", "japanese-english.svg"),
                )
                if marker in sources
            )
            episodes.append(
                AniWorldEpisode(
                    season=season,
                    number=number,
                    title=title_node.get_text(" ", strip=True) if title_node else "",
                    tracks=tracks,
                )
            )
        return episodes

    def get_episode(self, slug: str) -> FilmpalastMovie:
        parsed = parse_episode_slug(slug)
        if not parsed or not parsed[0].startswith(SOURCE_PREFIX):
            raise ValueError(f"Ungültiger AniWorld-Episoden-Slug: {slug}")
        base, season, episode = parsed
        descriptor = base[len(SOURCE_PREFIX) :]
        anime_id, separator, track = descriptor.partition("|")
        if not separator or track not in TRACK_LANGUAGE_IDS:
            raise ValueError(f"Ungültige AniWorld-Sprachspur: {slug}")
        anime = self.get_anime(anime_id)
        url = f"{BASE_URL}/anime/stream/{anime_id}/staffel-{season}/episode-{episode}"
        soup = self._soup(url)
        language_id = TRACK_LANGUAGE_IDS[track]
        hosters: list[HosterInfo] = []
        seen: set[str] = set()
        for node in soup.select(f'[data-link-target][data-lang-key="{language_id}"]'):
            target = html.unescape(str(node.get("data-link-target") or "").strip())
            if not target or target in seen:
                continue
            seen.add(target)
            name_node = node.select_one("h4")
            hosters.append(
                HosterInfo(
                    name=name_node.get_text(" ", strip=True) if name_node else "Hoster",
                    url=self._abs(target),
                    language=TRACK_LABELS[track],
                )
            )
        return FilmpalastMovie(
            title=f"{anime.title} S{season:02d}E{episode:02d}",
            url=url,
            year=anime.year,
            cover_url=anime.cover_url,
            description=anime.description,
            genres=anime.genres,
            hosters=hosters,
            provider="aniworld",
            content_language="de",
        )

    @staticmethod
    def is_redirect_url(url: str) -> bool:
        return REDIRECT_MARKER in str(url or "") and "aniworld.to" in str(url or "")

    def resolve_play_url(self, url: str, referer: str = "") -> str | None:
        if not self.is_redirect_url(url):
            return url
        response = self.session.get(
            url,
            headers={"Referer": referer or f"{BASE_URL}/"},
            allow_redirects=False,
            timeout=20,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return None
        return self._abs(response.headers.get("Location", "")) or None

    @staticmethod
    def _normalize_id(value: str) -> str:
        anime_id = str(value or "").strip()
        if anime_id.startswith(SOURCE_PREFIX):
            anime_id = anime_id[len(SOURCE_PREFIX) :].split("|", 1)[0]
        if not re.fullmatch(r"[a-z0-9-]{1,160}", anime_id):
            raise ValueError("Ungültige AniWorld-ID.")
        return anime_id


def aniworld_episode_slug(anime_id: str, track: str, season: int, episode: int) -> str:
    anime_id = AniWorldScraper._normalize_id(anime_id)
    track = str(track or "").strip().casefold()
    if track not in TRACK_LANGUAGE_IDS:
        raise ValueError("Unbekannte AniWorld-Sprachspur.")
    return (
        f"{SOURCE_PREFIX}{anime_id}|{track}"
        f"-s{max(1, int(season)):02d}e{max(1, int(episode)):03d}"
    )


def aniworld_episode_page(
    anime: AniWorldAnime,
    track: str,
    page: int = 1,
    page_size: int = 100,
) -> dict:
    track = str(track or "").strip().casefold()
    matching = [episode for episode in anime.episodes if track in episode.tracks]
    if not matching:
        raise ValueError("Diese Sprachspur ist nicht verfügbar.")
    page_size = max(1, min(100, int(page_size)))
    page_count = max(1, math.ceil(len(matching) / page_size))
    page = max(1, min(page_count, int(page)))
    selected = matching[(page - 1) * page_size : page * page_size]
    return {
        "page": page,
        "page_count": page_count,
        "page_size": page_size,
        "total": len(matching),
        "episodes": [
            {
                "season": episode.season,
                "number": episode.number,
                "label": f"Staffel {episode.season} · Episode {episode.number}",
                "title": episode.title,
                "slug": aniworld_episode_slug(
                    anime.id,
                    track,
                    episode.season,
                    episode.number,
                ),
            }
            for episode in selected
        ],
    }
