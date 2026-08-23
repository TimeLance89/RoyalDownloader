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
    original_title: str = ""
    tracks: tuple[str, ...] = ()
    hosters: tuple[str, ...] = ()
    kind: str = "episode"


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
    rating_count: int = 0
    alternative_titles: list[str] = field(default_factory=list)
    end_year: str = ""
    status: str = ""
    fsk: str = ""
    country: str = ""
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    producers: list[str] = field(default_factory=list)
    imdb_id: str = ""
    season_count: int = 0
    latest_season: int | None = None
    latest_episode: int | None = None
    latest_tracks: list[str] = field(default_factory=list)
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
        self._catalog_cache: tuple[float, list[AniWorldAnime]] | None = None

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
        letter: str = "",
        genre: str = "",
    ) -> dict:
        page = max(1, int(page))
        limit = max(1, min(50, int(limit)))
        mode = mode if mode in {
            "latest", "popular", "trending", "updates", "catalog", "search",
        } else "latest"
        if mode == "search":
            entries = self._search(query)
        elif mode == "catalog":
            entries = self._catalog()
            normalized_letter = str(letter or "").strip().upper()
            if normalized_letter and normalized_letter != "ALL":
                entries = [
                    entry for entry in entries
                    if self._title_letter(entry.title) == normalized_letter
                ]
            normalized_genre = str(genre or "").strip().casefold()
            if normalized_genre:
                entries = [
                    entry for entry in entries
                    if normalized_genre in {value.casefold() for value in entry.genres}
                ]
        elif mode == "updates":
            entries = self._parse_updates(self._soup(BASE_URL))
        else:
            url = {
                "latest": f"{BASE_URL}/neu",
                "popular": f"{BASE_URL}/beliebte-animes",
                "trending": BASE_URL,
            }[mode]
            soup = self._soup(url)
            if mode == "trending":
                heading = next(
                    (
                        node for node in soup.find_all(["h1", "h2", "h3"])
                        if "beliebt bei aniworld" in node.get_text(" ", strip=True).casefold()
                    ),
                    None,
                )
                container = heading.parent.find_next_sibling() if heading else soup
                entries = self._parse_cards(container or soup)
            else:
                entries = self._parse_cards(soup)
        start = (page - 1) * limit
        selected = entries[start : start + limit]
        payload = {
            "results": [entry.public_dict() for entry in selected],
            "page": page,
            "has_more": start + limit < len(entries),
            "total": len(entries),
        }
        if mode == "catalog":
            catalog = self._catalog()
            payload["facets"] = {
                "letters": self._facet_counts(
                    self._title_letter(entry.title) for entry in catalog
                ),
                "genres": self._facet_counts(
                    genre for entry in catalog for genre in entry.genres
                ),
            }
        return payload

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
        try:
            catalog = {entry.id: entry for entry in self._catalog()}
        except (requests.RequestException, RuntimeError, ValueError):
            catalog = {}
        for index, entry in enumerate(entries):
            if enriched := catalog.get(entry.id):
                entries[index] = enriched
        return entries

    def _catalog(self) -> list[AniWorldAnime]:
        cached = self._catalog_cache
        if cached and time.time() - cached[0] < 900:
            return cached[1]
        soup = self._soup(f"{BASE_URL}/animes")
        entries: dict[str, AniWorldAnime] = {}
        for group in soup.select("#seriesContainer .genre"):
            heading = group.select_one(".seriesGenreList h3")
            genre = heading.get_text(" ", strip=True) if heading else ""
            for anchor in group.select('a[href^="/anime/stream/"]'):
                match = re.fullmatch(
                    r"/anime/stream/([a-z0-9-]+)",
                    str(anchor.get("href") or "").rstrip("/"),
                )
                title = anchor.get_text(" ", strip=True)
                if not match or not title:
                    continue
                slug = match.group(1)
                entry = entries.setdefault(slug, AniWorldAnime(id=slug, title=title))
                if genre and genre not in entry.genres:
                    entry.genres.append(genre)
                alternatives = [
                    value.strip()
                    for value in str(anchor.get("data-alternative-title") or "").split(",")
                    if value.strip()
                ]
                entry.alternative_titles = list(dict.fromkeys(
                    [*entry.alternative_titles, *alternatives]
                ))
        result = sorted(entries.values(), key=lambda item: item.title.casefold())
        self._catalog_cache = (time.time(), result)
        return result

    @staticmethod
    def _title_letter(title: str) -> str:
        first = str(title or "").strip()[:1].upper()
        return first if first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else "#"

    @staticmethod
    def _facet_counts(values) -> dict[str, int]:
        counts: dict[str, int] = {}
        for raw in values:
            value = str(raw or "").strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: item[0].casefold()))

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
            genre_node = anchor.select_one("small")
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
                    genres=[genre_node.get_text(" ", strip=True)] if genre_node else [],
                )
            )
        return entries

    def _parse_updates(self, soup: BeautifulSoup) -> list[AniWorldAnime]:
        entries: dict[str, AniWorldAnime] = {}
        order: list[str] = []
        selector = '.newEpisodeList a[href*="/staffel-"][href*="/episode-"]'
        for anchor in soup.select(selector):
            match = re.fullmatch(
                r"/anime/stream/([a-z0-9-]+)/staffel-(\d+)/episode-(\d+)",
                str(anchor.get("href") or "").rstrip("/"),
            )
            if not match:
                continue
            slug, season_raw, episode_raw = match.groups()
            row = anchor.parent
            title_node = anchor.select_one("strong")
            title = title_node.get_text(" ", strip=True) if title_node else ""
            if not title:
                continue
            if slug not in entries:
                order.append(slug)
                entries[slug] = AniWorldAnime(
                    id=slug,
                    title=title,
                    latest_season=int(season_raw),
                    latest_episode=int(episode_raw),
                )
            entry = entries[slug]
            sources = " ".join(
                str(image.get("src") or image.get("data-src") or "")
                for image in row.select("img.flag")
            ).casefold()
            for track, marker in (
                ("dub", "german.svg"),
                ("sub", "japanese-german.svg"),
                ("eng", "japanese-english.svg"),
            ):
                if marker in sources and track not in entry.latest_tracks:
                    entry.latest_tracks.append(track)
        return [entries[slug] for slug in order]

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
        alternatives = [
            value.strip()
            for value in str(title_node.get("data-alternativetitles") or "").split(",")
            if value.strip()
        ]
        cover_node = soup.select_one(".seriesCoverBox img")
        cover = self._image_source(cover_node)
        backdrop = soup.select_one(".SeriesSection .backdrop")
        banner_match = re.search(
            r"url\(['\"]?([^'\")]+)",
            str(backdrop.get("style") if backdrop else ""),
        )
        year_node = soup.select_one("[itemprop=startDate]")
        year_match = re.search(
            r"\b(19|20)\d{2}\b", year_node.get_text(" ") if year_node else ""
        )
        end_year_node = soup.select_one("[itemprop=endDate]")
        end_year = end_year_node.get_text(" ", strip=True) if end_year_node else ""
        description_node = soup.select_one("[data-full-description]") or soup.select_one(
            "[itemprop=description]"
        )
        description = (
            str(description_node.get("data-full-description") or "").strip()
            or (description_node.get_text(" ", strip=True) if description_node else "")
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

        has_movies = bool(soup.select_one(
            f'a[href="/anime/stream/{anime_id}/filme"]'
        ))

        episodes: list[AniWorldEpisode] = []
        for season in season_numbers:
            season_soup = (
                soup if season == 1 else self._soup(f"{base_url}/staffel-{season}")
            )
            episodes.extend(self._episodes_from_soup(season_soup, season))
        if has_movies:
            movie_soup = self._soup(f"{base_url}/filme")
            episodes.extend(self._episodes_from_soup(movie_soup, 0))
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
            banner_url=self._abs(banner_match.group(1)) if banner_match else (
                self._abs(cover) if cover else ""
            ),
            description=description,
            genres=genres,
            rating=self._float_or_none(self._attr_or_text(
                soup.select_one("[itemprop=ratingValue]"), "content"
            )),
            rating_count=self._int_or_zero(self._attr_or_text(
                soup.select_one("[itemprop=ratingCount]"), "content"
            )),
            alternative_titles=alternatives,
            end_year=end_year,
            status="Laufend" if end_year.casefold() == "heute" else (
                f"Beendet {end_year}" if end_year else ""
            ),
            fsk=self._node_attr(soup.select_one(".fsk[data-fsk]"), "data-fsk"),
            country=next(iter(self._itemprop_names(soup, "countryOfOrigin")), ""),
            directors=self._itemprop_names(soup, "director"),
            cast=self._itemprop_names(soup, "actor"),
            producers=self._itemprop_names(soup, "creator"),
            imdb_id=self._node_attr(
                soup.select_one(".imdb-link[data-imdb]"), "data-imdb"
            ),
            season_count=len(season_numbers),
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
    def _attr_or_text(node, attribute: str) -> str:
        if node is None:
            return ""
        return str(node.get(attribute) or node.get_text(" ", strip=True) or "").strip()

    @staticmethod
    def _node_attr(node, attribute: str) -> str:
        return str(node.get(attribute) or "").strip() if node is not None else ""

    @staticmethod
    def _float_or_none(value: str) -> float | None:
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_or_zero(value: str) -> int:
        try:
            return int(str(value).replace(".", "").strip())
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _itemprop_names(soup: BeautifulSoup, itemprop: str) -> list[str]:
        return list(dict.fromkeys(
            node.get_text(" ", strip=True)
            for node in soup.select(f'[itemprop="{itemprop}"] [itemprop="name"]')
            if node.get_text(" ", strip=True)
        ))

    @staticmethod
    def _episodes_from_soup(soup: BeautifulSoup, season: int) -> list[AniWorldEpisode]:
        episodes: list[AniWorldEpisode] = []
        seen: set[int] = set()
        for row in soup.select("table.seasonEpisodesList tbody tr"):
            link = row.select_one('a[href*="/episode-"]') or row.select_one(
                'a[href*="/film-"]'
            )
            match = re.search(
                r"/(?:episode|film)-(\d+)",
                str(link.get("href") if link else ""),
            )
            if not match or int(match.group(1)) in seen:
                continue
            number = int(match.group(1))
            seen.add(number)
            title_node = row.select_one(".seasonEpisodeTitle strong")
            original_node = row.select_one(".seasonEpisodeTitle span")
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
                    original_title=(
                        original_node.get_text(" ", strip=True) if original_node else ""
                    ),
                    tracks=tracks,
                    hosters=tuple(dict.fromkeys(
                        str(icon.get("title") or "").strip()
                        for icon in row.select("i.icon[title]")
                        if str(icon.get("title") or "").strip()
                    )),
                    kind="movie" if season == 0 else "episode",
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
        url = (
            f"{BASE_URL}/anime/stream/{anime_id}/filme/film-{episode}"
            if season == 0
            else f"{BASE_URL}/anime/stream/{anime_id}/staffel-{season}/episode-{episode}"
        )
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
        episode_label = f"{episode:03d}" if season == 0 else f"{episode:02d}"
        return FilmpalastMovie(
            title=f"{anime.title} S{season:02d}E{episode_label}",
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
        f"-s{max(0, int(season)):02d}e{max(1, int(episode)):03d}"
    )


def aniworld_episode_page(
    anime: AniWorldAnime,
    track: str,
    page: int = 1,
    page_size: int = 100,
    season: int | None = None,
) -> dict:
    track = str(track or "").strip().casefold()
    matching = [episode for episode in anime.episodes if track in episode.tracks]
    if not matching:
        raise ValueError("Diese Sprachspur ist nicht verfügbar.")
    season_summaries = [
        {
            "season": season_number,
            "label": "Filme" if season_number == 0 else f"Staffel {season_number}",
            "count": sum(episode.season == season_number for episode in matching),
        }
        for season_number in sorted({episode.season for episode in matching})
    ]
    if season is not None:
        matching = [episode for episode in matching if episode.season == int(season)]
        if not matching:
            raise ValueError("Diese Staffel ist in der Sprachspur nicht verfügbar.")
    page_size = max(1, min(5000, int(page_size)))
    page_count = max(1, math.ceil(len(matching) / page_size))
    page = max(1, min(page_count, int(page)))
    selected = matching[(page - 1) * page_size : page * page_size]
    return {
        "page": page,
        "page_count": page_count,
        "page_size": page_size,
        "total": len(matching),
        "season": season,
        "seasons": season_summaries,
        "episodes": [
            {
                "season": episode.season,
                "number": episode.number,
                "label": (
                    f"Film {episode.number}" if episode.kind == "movie"
                    else f"Staffel {episode.season} · Episode {episode.number}"
                ),
                "title": episode.title,
                "original_title": episode.original_title,
                "hosters": list(episode.hosters),
                "kind": episode.kind,
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
