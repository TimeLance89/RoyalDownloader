"""Serienadapter fuer die oeffentlichen JSON-Endpunkte von huhu.to.

Die API ordnet Serien ueber TMDB-IDs zu und liefert Quellen fuer eine exakt
angegebene Staffel/Episode. Schutz- und Rate-Limit-Antworten werden nur
erkannt und an den Aufrufer weitergereicht; es gibt keinen Browser- oder
CAPTCHA-Fallback.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from curl_cffi import requests as cr

from providers.models import (
    FilmpalastMovie,
    FilmpalastSeries,
    FilmpalastSeriesResult,
    HosterInfo,
    SeriesEpisode,
    parse_episode_slug,
)
from session_manager import ProviderBlockedError


BASE_URL = "https://huhu.to"
SOURCE_PREFIX = "huhu:"
_BLOCK_MARKERS = (
    "captcha", "turnstile", "cf-chl", "cloudflare", "just a moment",
    "checking your browser", "too many requests",
)


class HuhuScraper:
    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._log = progress_cb or (lambda _message: None)
        self.session = cr.Session(impersonate="chrome136")

    def search_series(self, query: str) -> List[FilmpalastSeriesResult]:
        query = " ".join(str(query or "").split()).strip()
        if not query:
            return []
        self._log(f"Huhu Serien-Suche: {query}")
        data = self._post("catalog", {
            "catalogId": "tmdb.series",
            "id": "",
            "adult": False,
            "search": query,
            "sort": "popularity",
            "filter": {},
            "cursor": None,
        })
        results = [
            self._series_result(item)
            for item in data.get("items", [])
            if isinstance(item, dict) and item.get("type") == "series"
        ]
        return [result for result in results if result is not None]

    def list_series(self, page: int = 1) -> List[FilmpalastSeriesResult]:
        if page != 1:
            return []
        data = self._post("catalog", {
            "catalogId": "tmdb.series",
            "id": "",
            "adult": False,
            "search": "",
            "sort": "popularity",
            "filter": {},
            "cursor": None,
        })
        return [
            result
            for item in data.get("items", [])
            if isinstance(item, dict) and item.get("type") == "series"
            for result in [self._series_result(item)]
            if result is not None
        ]

    def get_series(self, url_or_slug: str) -> Optional[FilmpalastSeries]:
        tmdb_id = self._tmdb_id(url_or_slug)
        if not tmdb_id:
            return None
        data = self._post("item", {
            "type": "series",
            "ids": {"tmdb_id": tmdb_id},
            "name": "",
        })
        if not isinstance(data, dict) or data.get("type") != "series":
            return None
        name = str(data.get("name") or data.get("originalName") or tmdb_id).strip()
        slug = self._slugify(name)
        seasons: Dict[int, List[SeriesEpisode]] = {}
        seen: set[tuple[int, int]] = set()
        for item in data.get("episodes") or []:
            if not isinstance(item, dict):
                continue
            try:
                season = int(item.get("season"))
                episode = int(item.get("episode"))
            except (TypeError, ValueError):
                continue
            if season < 0 or episode < 1 or (season, episode) in seen:
                continue
            seen.add((season, episode))
            episode_slug = (
                f"{SOURCE_PREFIX}{tmdb_id}:{slug}-s{season:02d}e{episode:02d}"
            )
            seasons.setdefault(season, []).append(SeriesEpisode(
                season=season,
                episode=episode,
                slug=episode_slug,
                url=f"{BASE_URL}/item?type=series&id={tmdb_id}",
                release_name=str(item.get("name") or ""),
            ))
        for episodes in seasons.values():
            episodes.sort(key=lambda item: item.episode)
        if not seasons:
            return None
        images = data.get("images") if isinstance(data.get("images"), dict) else {}
        return FilmpalastSeries(
            title=name,
            base_slug=f"{SOURCE_PREFIX}{tmdb_id}:{slug}",
            url=f"{BASE_URL}/item?type=series&id={tmdb_id}",
            cover_url=str(images.get("poster") or ""),
            description=str(data.get("description") or ""),
            genres=[str(value) for value in data.get("genres") or [] if value],
            seasons=seasons,
        )

    def get_movie(self, url_or_slug: str) -> Optional[FilmpalastMovie]:
        parsed = parse_episode_slug(url_or_slug)
        if not parsed:
            return None
        base_slug, season, episode = parsed
        tmdb_id = self._tmdb_id(base_slug)
        if not tmdb_id:
            return None
        title = self._title_from_slug(base_slug)
        sources = self._post("source", {
            "type": "series",
            "ids": {"tmdb_id": tmdb_id},
            "name": title,
            "episode": {
                "ids": {},
                "season": season,
                "episode": episode,
            },
        })
        if not isinstance(sources, list):
            return None
        hosters: List[HosterInfo] = []
        seen_urls: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or source.get("type") != "url":
                continue
            url = str(source.get("url") or "").strip()
            if not url.startswith(("http://", "https://")) or url in seen_urls:
                continue
            # Huhu liefert teils BS.to-Episodenseiten statt eines Hosters.
            # Diese benoetigen erneut den dortigen CAPTCHA-geschuetzten Klick
            # und sind daher keine zulaessige direkte Downloadquelle.
            host = (urlparse(url).hostname or "").casefold()
            if host == "bs.to" or host.endswith(".bs.to"):
                continue
            languages = [
                str(value or "").strip().casefold()
                for value in source.get("languages") or []
            ]
            if languages and not any(value == "de" or value.startswith("de-") for value in languages):
                continue
            seen_urls.add(url)
            hosters.append(HosterInfo(
                name=self._hoster_name(url, str(source.get("name") or "Huhu")),
                url=url,
                language="de" if not languages or "de" in languages else languages[0],
                quality=str(source.get("tag") or ""),
            ))
        if not hosters:
            return None
        display_title = title.replace("-", " ").strip().title() or "Serie"
        return FilmpalastMovie(
            title=f"{display_title} S{season:02d}E{episode:02d}",
            url=f"{BASE_URL}/item?type=series&id={tmdb_id}&season={season}&episode={episode}",
            hosters=hosters,
        )

    def _post(self, endpoint: str, payload: dict):
        response = self.session.post(
            f"{BASE_URL}/mediaurl-{endpoint}.json",
            json={"language": "de", "region": "DE", **payload},
            timeout=25,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json; charset=utf-8",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/",
            },
        )
        text = str(getattr(response, "text", "") or "")
        status = int(getattr(response, "status_code", 0) or 0)
        low = text[:20_000].casefold()
        looks_like_html = text.lstrip().startswith(("<", "<!"))
        if status in {403, 429, 503} or (
            looks_like_html and any(marker in low for marker in _BLOCK_MARKERS)
        ):
            reason = "rate_limit" if status == 429 or "too many requests" in low else "cloudflare_gate"
            raise ProviderBlockedError(reason, status)
        response.raise_for_status()
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Huhu lieferte keine gueltige JSON-Antwort ({endpoint})") from exc
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Huhu API-Fehler: {data['error']}")
        return data

    def _series_result(self, item: dict) -> Optional[FilmpalastSeriesResult]:
        ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        tmdb_id = str(ids.get("tmdb_id") or "").strip()
        name = str(item.get("name") or item.get("originalName") or "").strip()
        if not tmdb_id.isdigit() or not name:
            return None
        slug = self._slugify(name)
        images = item.get("images") if isinstance(item.get("images"), dict) else {}
        year_match = re.search(r"\b(19|20)\d{2}\b", str(item.get("releaseDate") or ""))
        base_slug = f"{SOURCE_PREFIX}{tmdb_id}:{slug}"
        return FilmpalastSeriesResult(
            title=f"{name}  [Huhu]",
            base_slug=base_slug,
            sample_slug=base_slug,
            sample_url=f"{BASE_URL}/item?type=series&id={tmdb_id}",
            year=year_match.group(0) if year_match else "",
            cover_url=str(images.get("poster") or ""),
        )

    @staticmethod
    def _tmdb_id(value: str) -> str:
        raw = str(value or "")
        if raw.startswith(SOURCE_PREFIX):
            raw = raw[len(SOURCE_PREFIX):]
        match = re.match(r"(\d+)(?::|$)", raw)
        if not match:
            match = re.search(r"[?&]id=(\d+)", raw)
        return match.group(1) if match else ""

    @staticmethod
    def _title_from_slug(value: str) -> str:
        raw = str(value or "")
        if raw.startswith(SOURCE_PREFIX):
            raw = raw[len(SOURCE_PREFIX):]
        return raw.split(":", 1)[1] if ":" in raw else ""

    @staticmethod
    def _slugify(value: str) -> str:
        value = str(value or "").casefold().replace("&", " und ")
        for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
            value = value.replace(source, target)
        value = re.sub(r"[^a-z0-9]+", "-", value)
        return value.strip("-") or "serie"

    @staticmethod
    def _hoster_name(url: str, fallback: str) -> str:
        host = (urlparse(url).hostname or "").casefold()
        labels = {
            "voe": "VOE",
            "dood": "Doodstream",
            "filemoon": "Filemoon",
            "vidoza": "Vidoza",
            "veev": "Veev",
        }
        for marker, label in labels.items():
            if marker in host:
                return label
        return fallback or host or "Huhu"
