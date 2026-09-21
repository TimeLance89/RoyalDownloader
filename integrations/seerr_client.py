"""Kleiner Client fuer genehmigte Medienanfragen aus Seerr."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Optional

import requests


logger = logging.getLogger(__name__)


def _normalize_base_url(value: str) -> str:
    """Akzeptiert sowohl die Seerr-Basis-URL als auch eine API-v1-URL."""
    url = str(value or "").strip().rstrip("/")
    suffix = "/api/v1"
    if url.casefold().endswith(suffix):
        url = url[: -len(suffix)].rstrip("/")
    return url


def _int_value(value: Any, *, minimum: int = 1) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return result if result >= minimum else None


def _bool_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass(frozen=True)
class SeerrRequest:
    """Die fuer den Downloader relevanten Felder einer Seerr-Anfrage."""

    request_id: int
    media_type: str
    tmdb_id: int
    seasons: tuple[int, ...] = ()
    is_4k: bool = False
    media_status: int = 0

    @classmethod
    def from_payload(cls, payload: Any) -> Optional["SeerrRequest"]:
        if not isinstance(payload, dict):
            return None

        request_id = _int_value(payload.get("id"))
        media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
        raw_type = (
            payload.get("type") or payload.get("mediaType") or media.get("mediaType")
        )
        media_type = str(raw_type or "").strip().casefold()
        if media_type == "series":
            media_type = "tv"
        if request_id is None or media_type not in {"movie", "tv"}:
            return None

        tmdb_id = _int_value(
            media.get("tmdbId")
            or media.get("tmdb_id")
            or payload.get("tmdbId")
            or payload.get("tmdb_id")
        )
        if tmdb_id is None:
            return None

        season_numbers: set[int] = set()
        raw_seasons = payload.get("seasons")
        if isinstance(raw_seasons, (list, tuple)):
            for season in raw_seasons:
                raw_number = (
                    season.get("seasonNumber") if isinstance(season, dict) else season
                )
                number = _int_value(raw_number, minimum=0)
                if number is not None:
                    season_numbers.add(number)

        is_4k = _bool_value(payload.get("is4k", payload.get("is4K", False)))
        raw_media_status = (
            media.get("status4k", media.get("status4K"))
            if is_4k
            else media.get("status")
        )
        return cls(
            request_id=request_id,
            media_type=media_type,
            tmdb_id=tmdb_id,
            seasons=tuple(sorted(season_numbers)) if media_type == "tv" else (),
            is_4k=is_4k,
            media_status=_int_value(raw_media_status, minimum=0) or 0,
        )


class SeerrClient:
    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        timeout: float = 8.0,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = _normalize_base_url(base_url)
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        self._session = session or requests.Session()
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _get_json(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        if not self.configured:
            self.last_error = "Seerr-URL oder API-Schlüssel fehlt"
            return None
        url = f"{self.base_url}/api/v1/{path.lstrip('/')}"
        try:
            response = self._session.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "RoyalDownloader/1.0",
                    "X-Api-Key": self.api_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            self.last_error = str(exc)
            logger.warning("Seerr-Anfrage fehlgeschlagen (%s): %s", url, exc)
            return None
        if not isinstance(payload, dict):
            self.last_error = "Seerr lieferte keine JSON-Objektantwort"
            logger.warning("Seerr lieferte ungueltige JSON-Daten (%s)", url)
            return None
        self.last_error = ""
        return payload

    def _post_json(self, path: str) -> Optional[dict]:
        if not self.configured:
            self.last_error = "Seerr-URL oder API-Schlüssel fehlt"
            return None
        url = f"{self.base_url}/api/v1/{path.lstrip('/')}"
        try:
            response = self._session.post(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "RoyalDownloader/1.0",
                    "X-Api-Key": self.api_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            self.last_error = str(exc)
            logger.warning("Seerr-Anfrage fehlgeschlagen (%s): %s", url, exc)
            return None
        if not isinstance(payload, dict):
            self.last_error = "Seerr lieferte keine JSON-Objektantwort"
            return None
        self.last_error = ""
        return payload

    def status(self) -> dict:
        """Liest den Seerr-Status; ein API-Fehler ergibt ein leeres Mapping."""
        return self._get_json("status") or {}

    def test_connection(self) -> bool:
        payload = self._get_json(
            "request",
            {
                "take": 1,
                "skip": 0,
                "filter": "approved",
                "sort": "added",
                "sortDirection": "asc",
            },
        )
        if payload is None or not isinstance(payload.get("results"), list):
            if payload is not None:
                self.last_error = "Seerr-API-Key hat keinen Zugriff auf Anfragen"
            return False
        return True

    def decline_request(self, request_id: int) -> bool:
        """Lehnt einen nicht unterstützten Wunsch sichtbar in Seerr ab."""
        normalized_id = _int_value(request_id)
        if normalized_id is None:
            self.last_error = "Ungültige Seerr-Request-ID"
            return False
        return self._post_json(f"request/{normalized_id}/decline") is not None

    @staticmethod
    def _total_results(page_info: Any) -> Optional[int]:
        if not isinstance(page_info, dict):
            return None
        for key in ("results", "totalResults", "total", "totalItems"):
            total = _int_value(page_info.get(key), minimum=0)
            if total is not None:
                return total
        return None

    def approved_requests(self, page_size: int = 100) -> list[SeerrRequest]:
        """Liest alle genehmigten Requests, auch wenn Seerr sie paginiert."""
        if not self.configured:
            self.last_error = "Seerr-URL oder API-Schlüssel fehlt"
            return []
        try:
            take = max(1, min(int(page_size), 100))
        except (TypeError, ValueError, OverflowError):
            take = 100

        skip = 0
        parsed: list[SeerrRequest] = []
        seen_ids: set[int] = set()
        while True:
            payload = self._get_json(
                "request",
                {
                    "take": take,
                    "skip": skip,
                    "filter": "approved",
                    "sort": "added",
                    "sortDirection": "asc",
                },
            )
            if payload is None:
                return []
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                self.last_error = "Seerr-Requestliste enthält kein gültiges results-Feld"
                logger.warning(
                    "Seerr-Requestliste enthielt kein gueltiges results-Feld"
                )
                return []

            for raw_request in raw_results:
                request = SeerrRequest.from_payload(raw_request)
                if request is None:
                    logger.warning("Ungueltige Seerr-Anfrage wird ignoriert")
                    continue
                if request.request_id not in seen_ids:
                    seen_ids.add(request.request_id)
                    parsed.append(request)

            page_count = len(raw_results)
            skip += page_count
            total = self._total_results(payload.get("pageInfo"))
            if not page_count or (total is not None and skip >= total):
                break
            if total is None and page_count < take:
                break

        return parsed
