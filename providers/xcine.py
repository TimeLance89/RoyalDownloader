"""Scraper fuer xcine.ru (deutsche Filme und Serien).

XCine ist eine React-Anwendung. Katalog, Suche, Staffeln und Hoster kommen aus
oeffentlich erreichbaren JSON-Endpunkten; ein Browser ist daher nicht noetig.
Serien werden bei XCine pro Staffel gespeichert. Dieser Adapter fasst diese
Datensaetze zu einer Serie zusammen und erzeugt stabile Episoden-Slugs.
"""

import logging
import re
import unicodedata
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple
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

BASE_URL = "https://xcine.ru"
SOURCE_PREFIX = "xcine:"
API_LANGUAGE = 2  # Deutsch
MAX_HOSTERS_PER_DOMAIN = 3

GENRES: Dict[str, str] = {
    "Action": "Action",
    "Abenteuer": "Abenteuer",
    "Animation": "Animation",
    "Anime": "Anime",
    "Biografie": "Biografie",
    "Dokumentation": "Dokumentation",
    "Drama": "Drama",
    "Familie": "Familie",
    "Fantasy": "Fantasy",
    "Geschichte": "Geschichte",
    "Horror": "Horror",
    "Komödie": "Komödie",
    "Krimi": "Krimi",
    "Krieg": "Krieg",
    "Musik": "Musik",
    "Mystery": "Mystery",
    "Romance": "Romance",
    "Sci-Fi": "Sci-Fi",
    "Sport": "Sport",
    "Thriller": "Thriller",
    "Western": "Western",
}

_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{24}$", re.I)
_SEASON_SUFFIX_RE = re.compile(
    r"\s*(?:-|–|:)\s*(?:Staffel|Season)\s+\d+\s*$", re.I,
)


class XcineScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or logger.info
        self.session = cr.Session(impersonate="chrome136")
        self._detail_cache: Dict[str, dict] = {}
        self._seasons_cache: Dict[str, List[dict]] = {}

    # ------------------------------------------------------------------
    # Suche / Katalog
    # ------------------------------------------------------------------
    def search(self, query: str) -> List[FilmpalastSearchResult]:
        rows = self._search_rows(query)
        results = [self._movie_result(row) for row in rows if not self._is_series(row)]
        self._log(f"  XCine: {len(results)} Film(e) gefunden")
        return results

    def search_series(self, query: str) -> List[FilmpalastSeriesResult]:
        rows = [row for row in self._search_rows(query) if self._is_series(row)]
        grouped: Dict[str, dict] = {}
        for row in rows:
            title = self._series_title(row)
            key = self._title_key(title)
            if not key:
                continue
            current = grouped.get(key)
            if current is None or self._season_number(row) < self._season_number(current):
                grouped[key] = row

        results = [self._series_result(row) for row in grouped.values()]
        self._log(f"  XCine: {len(results)} Serie(n) gefunden")
        return results

    def list_movies(self, category: str = "new", page: int = 1) -> List[FilmpalastSearchResult]:
        rows = self._browse("movies", category, "", page)
        return [self._movie_result(row) for row in rows]

    def list_series(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        rows = self._browse("tvseries", "new", "", page)
        return [self._series_result(row) for row in rows]

    def list_genres(self) -> List[str]:
        return list(GENRES.keys())

    def list_by_genre(self, genre: str, page: int = 1) -> List[FilmpalastSearchResult]:
        source_genre = GENRES.get((genre or "").strip())
        if not source_genre:
            return []
        rows = self._browse("movies", "new", source_genre, page)
        return [self._movie_result(row) for row in rows]

    def _search_rows(self, query: str) -> List[dict]:
        query = " ".join((query or "").split()).strip()
        if not query:
            return []
        self._log(f"XCine Suche: {query}")
        data = self._get_json("/data/search/", {"lang": API_LANGUAGE, "keyword": query})
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def _browse(self, media_type: str, category: str, genre: str, page: int) -> List[dict]:
        data = self._get_json("/data/browse/", {
            "lang": API_LANGUAGE,
            "keyword": "",
            "year": "",
            "rating": "",
            "votes": "",
            "genre": genre,
            "country": "",
            "cast": "",
            "directors": "",
            "type": media_type,
            "order_by": "rating" if category == "top" else "latest",
            "page": max(1, int(page)),
            "limit": 32,
        })
        rows = data.get("movies", []) if isinstance(data, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    # ------------------------------------------------------------------
    # Filme / Serien / Episoden
    # ------------------------------------------------------------------
    def get_movie(self, value: str) -> Optional[FilmpalastMovie]:
        root_id, season, episode = self._value_parts(value)
        if not root_id:
            return None
        root = self._detail(root_id)
        if not root:
            return None
        if episode is not None and season is None and self._is_series(root):
            season = self._season_number(root)

        detail = root
        detail_id = root_id
        if season is not None and episode is not None:
            detail_id, detail = self._detail_for_season(root, season)
            if not detail:
                return None

        hosters = self._extract_hosters(detail.get("streams") or [], episode)
        title = self._series_title(detail) if season is not None else self._clean_title(detail)
        if season is not None and episode is not None:
            title = f"{title} S{season:02d}E{episode:02d}"
        if not hosters:
            self._log("  XCine: keine Hoster für diesen Eintrag gefunden")

        return FilmpalastMovie(
            title=title or "Unbekannt",
            url=self._watch_url(detail_id, title, episode),
            year=self._year(detail),
            runtime=self._runtime(detail.get("runtime")),
            cover_url=self._cover_url(detail),
            description=str(detail.get("storyline") or detail.get("overview") or "").strip(),
            genres=self._genres(detail.get("genres")),
            hosters=hosters,
        )

    def get_series(self, value: str) -> Optional[FilmpalastSeries]:
        root_id, _season, _episode = self._value_parts(value)
        if not root_id:
            return None
        root = self._detail(root_id)
        if not root or not self._is_series(root):
            return None

        title = self._series_title(root)
        season_rows = self._season_rows(title)
        if not season_rows:
            season_rows = [{"_id": root_id, "s": self._season_number(root)}]

        seasons: Dict[int, List[SeriesEpisode]] = {}
        for row in sorted(season_rows, key=self._season_number):
            season = self._season_number(row)
            detail_id = str(row.get("_id") or "")
            if season <= 0 or not _OBJECT_ID_RE.fullmatch(detail_id):
                continue
            detail = root if detail_id == root_id else self._detail(detail_id)
            if not detail:
                continue
            streams = detail.get("streams") or []
            episode_numbers = sorted({
                number for number in (self._stream_episode(item) for item in streams)
                if number > 0
            })
            if not episode_numbers:
                continue
            latest_release: Dict[int, str] = {}
            for item in sorted(streams, key=lambda entry: str(entry.get("_id") or ""), reverse=True):
                number = self._stream_episode(item)
                if number > 0 and number not in latest_release:
                    latest_release[number] = str(item.get("release") or "").strip()
            episodes: List[SeriesEpisode] = []
            for episode in episode_numbers:
                slug = f"{self._source_value(root_id, title)}-s{season:02d}e{episode:02d}"
                episodes.append(SeriesEpisode(
                    season=season,
                    episode=episode,
                    slug=slug,
                    url=self._watch_url(detail_id, title, episode),
                    release_name=latest_release.get(episode, ""),
                ))
            seasons[season] = episodes

        if not seasons:
            return None
        base_slug = self._source_value(root_id, title)
        return FilmpalastSeries(
            title=title,
            base_slug=base_slug,
            url=self._watch_url(root_id, title),
            cover_url=self._cover_url(root),
            description=str(root.get("storyline") or root.get("overview") or "").strip(),
            genres=self._genres(root.get("genres")),
            seasons=seasons,
        )

    def _detail_for_season(self, root: dict, season: int) -> Tuple[str, Optional[dict]]:
        root_id = str(root.get("_id") or "")
        if self._season_number(root) == season:
            return root_id, root
        for row in self._season_rows(self._series_title(root)):
            if self._season_number(row) != season:
                continue
            detail_id = str(row.get("_id") or "")
            return detail_id, self._detail(detail_id)
        return "", None

    # ------------------------------------------------------------------
    # JSON / Konvertierung
    # ------------------------------------------------------------------
    def _get_json(self, path: str, params: dict):
        response = self.session.get(
            BASE_URL + path,
            params=params,
            headers={"Accept": "application/json", "Referer": BASE_URL + "/"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _detail(self, object_id: str) -> Optional[dict]:
        if not _OBJECT_ID_RE.fullmatch(object_id or ""):
            return None
        if object_id not in self._detail_cache:
            data = self._get_json("/data/watch/", {"_id": object_id})
            self._detail_cache[object_id] = data if isinstance(data, dict) else {}
        return self._detail_cache[object_id] or None

    def _season_rows(self, title: str) -> List[dict]:
        key = self._title_key(title)
        if key not in self._seasons_cache:
            data = self._get_json(
                "/data/seasons/", {"lang": API_LANGUAGE, "original_title": title},
            )
            self._seasons_cache[key] = (
                [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
            )
        return self._seasons_cache[key]

    def _movie_result(self, row: dict) -> FilmpalastSearchResult:
        object_id = str(row.get("_id") or "")
        title = self._clean_title(row)
        return FilmpalastSearchResult(
            title=f"{title}  [XCine]",
            slug=self._source_value(object_id, title),
            url=self._watch_url(object_id, title),
            year=self._year(row),
            is_movie=True,
        )

    def _series_result(self, row: dict) -> FilmpalastSeriesResult:
        object_id = str(row.get("_id") or "")
        title = self._series_title(row)
        value = self._source_value(object_id, title)
        return FilmpalastSeriesResult(
            title=f"{title}  [XCine]",
            base_slug=value,
            sample_slug=value,
            sample_url=self._watch_url(object_id, title),
            year=self._year(row),
            cover_url=self._cover_url(row),
        )

    def _extract_hosters(self, streams, episode: Optional[int]) -> List[HosterInfo]:
        candidates = [item for item in streams if isinstance(item, dict)]
        candidates.sort(key=lambda item: str(item.get("_id") or ""), reverse=True)
        seen_urls = set()
        domain_counts = defaultdict(int)
        hosters: List[HosterInfo] = []
        for item in candidates:
            if episode is not None and self._stream_episode(item) != episode:
                continue
            url = self._normalize_stream_url(item.get("stream"))
            if not url or url in seen_urls:
                continue
            host = (urlparse(url).hostname or "").casefold().removeprefix("www.")
            if not host or domain_counts[host] >= MAX_HOSTERS_PER_DOMAIN:
                continue
            seen_urls.add(url)
            domain_counts[host] += 1
            release = str(item.get("release") or "")
            hosters.append(HosterInfo(
                name=self._hoster_name(host),
                url=url,
                language="Deutsch",
                quality=self._quality(release),
            ))
        return hosters

    @staticmethod
    def _normalize_stream_url(value) -> str:
        url = str(value or "").replace("\u200b", "").replace("\xa0", "").strip()
        if url.startswith("//"):
            url = "https:" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return ""
        return url

    @staticmethod
    def _hoster_name(host: str) -> str:
        names = (
            ("streamtape", "Streamtape"),
            ("vidsonic", "Vidsonic"),
            ("vidara", "Vidara"),
            ("voe", "VOE"),
            ("dood", "Doodstream"),
            ("upstream", "Upstream"),
            ("waaw", "Netu"),
            ("netu", "Netu"),
            ("firestream", "Firestream"),
            ("flyfile", "Flyfile"),
            ("vidmoly", "Vidmoly"),
            ("vidoza", "Vidoza"),
            ("filemoon", "Filemoon"),
        )
        for marker, name in names:
            if marker in host:
                return name
        return host.split(".")[0].replace("-", " ").title() or "Hoster"

    @staticmethod
    def _quality(release: str) -> str:
        match = re.search(r"\b(2160p|1080p|720p|480p|4K|UHD|HD|SD)\b", release or "", re.I)
        return match.group(1).upper().replace("P", "p") if match else ""

    @staticmethod
    def _genres(value) -> List[str]:
        if isinstance(value, list):
            values = [item.get("name", "") if isinstance(item, dict) else str(item) for item in value]
        else:
            values = re.split(r"[,|/]", str(value or ""))
        result: List[str] = []
        for item in values:
            item = " ".join(str(item).split()).strip()
            if item and item not in result:
                result.append(item)
        return result

    @staticmethod
    def _runtime(value) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        return f"{text} min" if text.isdigit() else text

    @staticmethod
    def _stream_episode(item: dict) -> int:
        try:
            return int(item.get("e") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _season_number(row: dict) -> int:
        try:
            return int(row.get("s") or 0)
        except (TypeError, ValueError):
            match = _SEASON_SUFFIX_RE.search(str(row.get("title") or ""))
            return int(re.search(r"\d+", match.group(0)).group()) if match else 0

    @staticmethod
    def _is_series(row: dict) -> bool:
        return bool(row.get("tv") or row.get("s") or _SEASON_SUFFIX_RE.search(str(row.get("title") or "")))

    @staticmethod
    def _clean_title(row: dict) -> str:
        return " ".join(str(row.get("title") or row.get("original_title") or "Unbekannt").split())

    @staticmethod
    def _series_title(row: dict) -> str:
        title = str(row.get("original_title") or row.get("title") or "Unbekannte Serie")
        return _SEASON_SUFFIX_RE.sub("", " ".join(title.split())).strip()

    @staticmethod
    def _year(row: dict) -> str:
        year = str(row.get("year") or "").strip()
        return year if re.fullmatch(r"(?:19|20)\d{2}", year) else ""

    @staticmethod
    def _cover_url(row: dict) -> str:
        path = str(row.get("poster_path_season") or row.get("poster_path") or "").strip()
        if path.startswith("http"):
            return path
        if path.startswith("/"):
            return "https://image.tmdb.org/t/p/w500" + path
        return ""

    @staticmethod
    def _title_key(title: str) -> str:
        normalized = unicodedata.normalize("NFKD", title or "")
        return re.sub(r"[^a-z0-9]+", "", normalized.casefold())

    @staticmethod
    def _slugify(title: str) -> str:
        normalized = unicodedata.normalize("NFKD", title or "")
        ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_title.casefold())).strip("-")

    @classmethod
    def _source_value(cls, object_id: str, title: str) -> str:
        return f"{SOURCE_PREFIX}{object_id}:{cls._slugify(title)}"

    @classmethod
    def _watch_url(cls, object_id: str, title: str, episode: Optional[int] = None) -> str:
        url = f"{BASE_URL}/watch/{cls._slugify(title)}/{object_id}"
        return f"{url}/{episode}" if episode is not None else url

    @staticmethod
    def _value_parts(value: str) -> Tuple[str, Optional[int], Optional[int]]:
        raw = str(value or "").strip()
        if raw.startswith(("http://", "https://")):
            parts = [part for part in urlparse(raw).path.split("/") if part]
            if "watch" not in parts:
                return "", None, None
            index = parts.index("watch")
            if len(parts) <= index + 2:
                return "", None, None
            object_id = parts[index + 2]
            episode = int(parts[index + 3]) if len(parts) > index + 3 and parts[index + 3].isdigit() else None
            return (object_id, None, episode) if _OBJECT_ID_RE.fullmatch(object_id) else ("", None, None)

        if raw.startswith(SOURCE_PREFIX):
            raw = raw[len(SOURCE_PREFIX):]
        parsed = parse_episode_slug(raw)
        if parsed:
            base, season, episode = parsed
            object_id = base.split(":", 1)[0]
            return (object_id, season, episode) if _OBJECT_ID_RE.fullmatch(object_id) else ("", None, None)
        object_id = raw.split(":", 1)[0]
        return (object_id, None, None) if _OBJECT_ID_RE.fullmatch(object_id) else ("", None, None)
