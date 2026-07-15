"""Scraper fuer megakino.org.

MegaKino ist eine React-SPA. Katalog, Suche, Details, Staffeln und Hoster
kommen aus oeffentlichen JSON-Endpunkten; ein UI-Browser ist dafuer nicht
noetig. Die API fuehrt pro Serie einen Datensatz je Staffel.
"""

import logging
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import urlparse

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

BASE_URL = "https://megakino.org"
SOURCE_PREFIX = "megakino:"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
PAGE_SIZE = 32
MAX_HOSTERS_PER_EPISODE = 32
MAX_HOSTERS_PER_FAMILY = 8

GENRES = [
    "Action", "Abenteuer", "Animation", "Anime", "Dokumentarfilm", "Drama",
    "Familie", "Fantasy", "Geschichte", "Horror", "Komödie", "Krimi",
    "Musik", "Mystery", "Romantik", "Science Fiction", "Sci-Fi & Fantasy",
    "Thriller", "Western",
]

_ID_RE = re.compile(r"\b[0-9a-f]{24}\b", re.I)
_SEASON_SUFFIX_RE = re.compile(
    r"\s*(?:-|–|:)\s*(?:Staffel|Season)\s*\d+\s*$", re.I,
)
_SKIP_DOMAINS = {
    "bit.ly", "is.gd", "www.opensubtitles.org", "opensubtitles.org",
}


class MegaKinoScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.session = cr.Session(impersonate="chrome136")

    # -- Filme -------------------------------------------------------------
    def search(self, query: str) -> List[FilmpalastSearchResult]:
        query = " ".join(str(query or "").split())
        if not query:
            return []
        self._log(f"MegaKino Suche: {query}")
        rows = self._search_rows(query)
        results = [self._movie_result(row) for row in rows if not self._is_series(row)]
        self._log(f"  MegaKino: {len(results)} Film(e)")
        return results

    def list_movies(self, category: str = "new", page: int = 1) -> List[FilmpalastSearchResult]:
        rows = self._browse_rows(
            media_type="movies",
            order_by="views" if category == "top" else "releases",
            page=page,
        )
        return [self._movie_result(row) for row in rows]

    def list_genres(self) -> List[str]:
        return list(GENRES)

    def list_by_genre(self, genre: str, page: int = 1) -> List[FilmpalastSearchResult]:
        genre = " ".join(str(genre or "").split())
        if not genre:
            return []
        rows = self._browse_rows(
            media_type="movies", order_by="views", page=page, genre=genre,
        )
        return [self._movie_result(row) for row in rows]

    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        parsed_episode = parse_episode_slug(str(url_or_slug or ""))
        source_id = self._source_id(url_or_slug)
        if not source_id:
            return None
        if parsed_episode:
            _base, season, episode = parsed_episode
            return self._get_episode_movie(source_id, season, episode)

        row = self._watch(source_id)
        if not row or self._is_series(row):
            return None
        hosters = self._hosters(row.get("streams") or [])
        return self._movie_from_row(row, hosters)

    # -- Serien ------------------------------------------------------------
    def search_series(self, query: str) -> List[FilmpalastSeriesResult]:
        query = " ".join(str(query or "").split())
        if not query:
            return []
        self._log(f"MegaKino Serien-Suche: {query}")
        rows = [row for row in self._search_rows(query) if self._is_series(row)]
        results = self._series_results(rows)
        self._log(f"  MegaKino: {len(results)} Serie(n)")
        return results

    def list_series(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        rows = self._browse_rows(
            media_type="tvseries", order_by="updates", page=page,
        )
        return self._series_results(rows)

    def get_series(self, url_or_slug: str) -> Optional[FilmpalastSeries]:
        source_id = self._source_id(url_or_slug)
        if not source_id:
            return None
        first = self._watch(source_id)
        if not first or not self._is_series(first):
            return None

        title = self._series_title(first.get("title"))
        season_rows = self._season_rows(first, title)
        if not season_rows:
            season_rows = [first]
        season_rows.sort(key=self._season_number)

        root_row = season_rows[0]
        root_id = str(root_row.get("_id") or source_id)
        slug = self._slugify(title)
        base_slug = f"{SOURCE_PREFIX}{root_id}:{slug}"
        seasons: Dict[int, List[SeriesEpisode]] = {}
        details_by_id = {str(first.get("_id") or ""): first}

        for season_row in season_rows:
            season_id = str(season_row.get("_id") or "")
            detail = details_by_id.get(season_id)
            if detail is None and season_id:
                detail = self._watch(season_id)
                details_by_id[season_id] = detail
            detail = detail or season_row
            season = self._season_number(detail) or self._season_number(season_row)
            if season < 0:
                continue
            episode_numbers = self._episode_numbers(detail, season_row)
            if not episode_numbers:
                continue
            episodes = [
                SeriesEpisode(
                    season=season,
                    episode=episode,
                    slug=f"{base_slug}-s{season:02d}e{episode:02d}",
                    url=f"{BASE_URL}/watch/{slug}/{season_id or root_id}/{episode}",
                    release_name=self._episode_release(detail, episode),
                )
                for episode in episode_numbers
            ]
            seasons[season] = episodes

        if not seasons:
            self._log("  MegaKino: keine Episoden mit Hoster-Daten gefunden.")
            return None

        metadata = first
        total = sum(len(episodes) for episodes in seasons.values())
        self._log(
            f"  Serie (MegaKino): «{title}» – {len(seasons)} Staffel(n), {total} Episoden"
        )
        return FilmpalastSeries(
            title=title,
            base_slug=base_slug,
            url=f"{BASE_URL}/watch/{slug}/{root_id}",
            cover_url=self._cover_url(metadata),
            description=str(metadata.get("storyline") or metadata.get("overview") or "").strip(),
            genres=self._genres(metadata.get("genres")),
            seasons=seasons,
        )

    # -- API ---------------------------------------------------------------
    def _json(self, path: str, params: Optional[dict] = None):
        response = self.session.get(
            f"{BASE_URL}{path}",
            params=params or {},
            timeout=25,
            allow_redirects=True,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                "Referer": f"{BASE_URL}/",
            },
        )
        response.raise_for_status()
        return response.json()

    def _search_rows(self, query: str) -> List[dict]:
        data = self._json("/data/search/", {"lang": 2, "keyword": query})
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def _browse_rows(
        self, media_type: str, order_by: str, page: int, genre: str = "",
    ) -> List[dict]:
        data = self._json("/data/browse/", {
            "lang": 2,
            "keyword": "",
            "year": "",
            "rating": "",
            "votes": "",
            "genre": genre,
            "country": "",
            "cast": "",
            "directors": "",
            "type": media_type,
            "order_by": order_by,
            "page": max(1, int(page or 1)),
            "limit": PAGE_SIZE,
        })
        rows = data.get("movies") if isinstance(data, dict) else []
        return [row for row in rows or [] if isinstance(row, dict)]

    def _watch(self, source_id: str) -> dict:
        data = self._json("/data/watch/", {"_id": source_id})
        return data if isinstance(data, dict) and data.get("_id") else {}

    def _season_rows(self, first: dict, title: str) -> List[dict]:
        data = self._json("/data/seasons/", {
            "lang": first.get("lang") or 2,
            "original_title": title,
        })
        rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
        if not any(str(row.get("_id")) == str(first.get("_id")) for row in rows):
            rows.append(first)
        unique = {}
        for row in rows:
            source_id = str(row.get("_id") or "")
            if source_id:
                unique[source_id] = row
        return list(unique.values())

    # -- Konvertierung -----------------------------------------------------
    def _movie_result(self, row: dict) -> FilmpalastSearchResult:
        source_id = str(row.get("_id") or "")
        title = str(row.get("title") or source_id)
        slug = self._slugify(title)
        return FilmpalastSearchResult(
            title=f"{title}  [MegaKino]",
            slug=f"{SOURCE_PREFIX}{source_id}:{slug}",
            url=f"{BASE_URL}/watch/{slug}/{source_id}",
            year=self._year(row.get("year")),
            is_movie=True,
        )

    def _series_results(self, rows: Iterable[dict]) -> List[FilmpalastSeriesResult]:
        grouped: Dict[str, List[dict]] = defaultdict(list)
        for row in rows:
            title = self._series_title(row.get("title"))
            if row.get("_id") and title:
                grouped[self._title_key(title)].append(row)

        results = []
        for values in grouped.values():
            values.sort(key=self._season_number)
            root = values[0]
            source_id = str(root.get("_id"))
            title = self._series_title(root.get("title"))
            slug = self._slugify(title)
            base_slug = f"{SOURCE_PREFIX}{source_id}:{slug}"
            results.append(FilmpalastSeriesResult(
                title=f"{title}  [MegaKino]",
                base_slug=base_slug,
                sample_slug=base_slug,
                sample_url=f"{BASE_URL}/watch/{slug}/{source_id}",
                year=self._year(root.get("year")),
                cover_url=self._cover_url(root),
            ))
        return results

    def _get_episode_movie(
        self, root_id: str, season: int, episode: int,
    ) -> Optional[FilmpalastMovie]:
        first = self._watch(root_id)
        if not first:
            return None
        title = self._series_title(first.get("title"))
        season_rows = self._season_rows(first, title)
        season_row = next(
            (row for row in season_rows if self._season_number(row) == season),
            first if self._season_number(first) == season else None,
        )
        if not season_row:
            return None
        season_id = str(season_row.get("_id") or root_id)
        detail = first if season_id == str(first.get("_id")) else self._watch(season_id)
        if not detail:
            return None
        hosters = self._hosters(detail.get("streams") or [], episode=episode)
        slug = self._slugify(title)
        return FilmpalastMovie(
            title=f"{title} S{season:02d}E{episode:02d}",
            url=f"{BASE_URL}/watch/{slug}/{season_id}/{episode}",
            year=self._year(detail.get("year")),
            runtime=self._runtime(detail.get("runtime")),
            cover_url=self._cover_url(detail),
            description=str(detail.get("storyline") or detail.get("overview") or "").strip(),
            genres=self._genres(detail.get("genres")),
            hosters=hosters,
        )

    def _movie_from_row(self, row: dict, hosters: List[HosterInfo]) -> FilmpalastMovie:
        title = str(row.get("title") or "Unbekannt")
        source_id = str(row.get("_id") or "")
        slug = self._slugify(title)
        return FilmpalastMovie(
            title=title,
            url=f"{BASE_URL}/watch/{slug}/{source_id}",
            year=self._year(row.get("year")),
            runtime=self._runtime(row.get("runtime")),
            cover_url=self._cover_url(row),
            description=str(row.get("storyline") or row.get("overview") or "").strip(),
            genres=self._genres(row.get("genres")),
            hosters=hosters,
        )

    def _hosters(self, streams: Iterable[dict], episode: Optional[int] = None) -> List[HosterInfo]:
        candidates = []
        seen_urls = set()
        now = time.time()
        for stream in streams:
            if not isinstance(stream, dict) or stream.get("deleted"):
                continue
            if episode is not None and self._positive_int(stream.get("e")) != episode:
                continue
            released = self._positive_int(stream.get("released"))
            if released and released > now + 60:
                continue
            url = self._stream_url(stream.get("stream"))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            name = self._hoster_name(url)
            candidates.append((
                self._hoster_priority(name),
                self._timestamp(stream.get("added")),
                name,
                url,
                str(stream.get("release") or "").strip(),
            ))

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        family_counts: Dict[str, int] = defaultdict(int)
        file_counts: Dict[tuple, int] = defaultdict(int)
        hosters: List[HosterInfo] = []
        for _priority, _added, name, url, release in candidates:
            family = name.casefold()
            file_key = (family, urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
            if family_counts[family] >= MAX_HOSTERS_PER_FAMILY or file_counts[file_key] >= 4:
                continue
            family_counts[family] += 1
            file_counts[file_key] += 1
            hosters.append(HosterInfo(
                name=name,
                url=url,
                language="Deutsch",
                quality=self._quality(release),
            ))
            if len(hosters) >= MAX_HOSTERS_PER_EPISODE:
                break
        return hosters

    @staticmethod
    def _hoster_name(url: str) -> str:
        domain = (urlparse(url).hostname or "").casefold()
        if "firestream" in domain:
            return "FireStream"
        if any(part in domain for part in (
            "vidara", "vidmatrix", "vidchamp", "vidachamp", "vidavaca",
            "viewdara", "thebesthost",
        )):
            return "Vidara"
        if "voe" in domain:
            return "VOE"
        if any(part in domain for part in (
            "dood", "d000d", "d0o0d", "doood", "dsvplay", "ds2video",
        )):
            return "Doodstream"
        known = (
            ("streamruby", "StreamRuby"), ("streamtape", "Streamtape"),
            ("veev", "Veev"), ("filemoon", "Filemoon"),
            ("vidsonic", "Vidsonic"), ("flyfile", "Flyfile"),
            ("vidmoly", "Vidmoly"), ("vidoza", "Vidoza"),
            ("upstream", "Upstream"), ("vinovo", "Vinovo"),
            ("lulu", "Luluvid"),
        )
        for marker, name in known:
            if marker in domain:
                return name
        return domain.split(".")[0].title() if domain else "MegaKino"

    @staticmethod
    def _hoster_priority(name: str) -> int:
        return {
            "vidara": 120,
            "firestream": 115,
            "voe": 100,
            "streamruby": 90,
            "doodstream": 85,
            "veev": 80,
            "filemoon": 75,
            "vidmoly": 70,
            "vidoza": 68,
            "streamtape": 65,
            "vidsonic": 60,
            "flyfile": 45,
        }.get(name.casefold(), 30)

    @staticmethod
    def _stream_url(value) -> str:
        url = str(value or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url and not url.lower().startswith(("http://", "https://")):
            url = "https://" + url.lstrip("/")
        parsed = urlparse(url)
        domain = (parsed.hostname or "").casefold()
        if (
            parsed.scheme not in ("http", "https")
            or not domain
            or domain in _SKIP_DOMAINS
            or domain.endswith(".neocities.org")
            or not parsed.path.strip("/")
        ):
            return ""
        return url

    @staticmethod
    def _quality(release: str) -> str:
        match = re.search(r"\b(2160|1440|1080|720|480|360)p\b", release or "", re.I)
        if match:
            return f"{match.group(1)}p"
        return "HD" if re.search(r"\b(?:HD|WEB|BluRay)\b", release or "", re.I) else ""

    @staticmethod
    def _episode_numbers(detail: dict, summary: dict) -> List[int]:
        values = {
            MegaKinoScraper._positive_int(stream.get("e"))
            for stream in detail.get("streams") or []
            if isinstance(stream, dict) and not stream.get("deleted")
        }
        values.discard(0)
        if values:
            return sorted(values)
        last = MegaKinoScraper._positive_int(
            detail.get("last_updated_epi") or summary.get("last_updated_epi")
        )
        return list(range(1, min(last, 500) + 1)) if last else []

    @staticmethod
    def _episode_release(detail: dict, episode: int) -> str:
        releases = [
            " ".join(str(stream.get("release") or stream.get("e_title") or "").split())
            for stream in detail.get("streams") or []
            if isinstance(stream, dict)
            and not stream.get("deleted")
            and MegaKinoScraper._positive_int(stream.get("e")) == episode
        ]
        return next((release for release in releases if release), "")

    @staticmethod
    def _source_id(value: str) -> str:
        match = _ID_RE.search(str(value or ""))
        return match.group(0).lower() if match else ""

    @staticmethod
    def _is_series(row: dict) -> bool:
        return bool(row.get("tv"))

    @staticmethod
    def _series_title(value) -> str:
        return _SEASON_SUFFIX_RE.sub("", str(value or "")).strip()

    @staticmethod
    def _season_number(row: dict) -> int:
        value = MegaKinoScraper._positive_int(row.get("s"))
        if value:
            return value
        match = re.search(r"(?:Staffel|Season)\s*(\d+)", str(row.get("title") or ""), re.I)
        return int(match.group(1)) if match else -1

    @staticmethod
    def _positive_int(value) -> int:
        try:
            number = int(value)
            return number if number > 0 else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _timestamp(value) -> float:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _year(value) -> str:
        match = re.search(r"\b(?:19|20)\d{2}\b", str(value or ""))
        return match.group(0) if match else ""

    @staticmethod
    def _runtime(value) -> str:
        match = re.search(r"\d+", str(value or ""))
        return f"{match.group(0)} min" if match else ""

    @staticmethod
    def _genres(value) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [part.strip() for part in re.split(r"[,|]", str(value or "")) if part.strip()]

    @staticmethod
    def _cover_url(row: dict) -> str:
        value = str(row.get("poster_path_season") or row.get("poster_path") or "").strip()
        if not value:
            return ""
        return value if value.startswith("http") else f"{TMDB_IMAGE_BASE}/{value.lstrip('/')}"

    @staticmethod
    def _title_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.casefold())

    @staticmethod
    def _slugify(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
        text = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
        return text or "titel"
