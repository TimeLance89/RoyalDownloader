"""Content-language aware TMDB trailer selection.

Trailer audio follows the configured provider/content languages rather than the
UI translation language. German-only installations therefore never fall back
to an English trailer, while mixed German/English installations deliberately
prefer English.
"""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from application_services.runtime import import_backend_namespace, publish_service


globals().update(import_backend_namespace())

_TRAILER_CACHE_MAX_ENTRIES = 2048


def _preferred_trailer_language(languages) -> str:
    normalized = {
        str(language or "").strip().replace("_", "-").casefold().split("-", 1)[0]
        for language in (languages or [])
        if str(language or "").strip()
    }
    if "en" in normalized:
        return "en"
    if "de" in normalized:
        return "de"
    return "en"


def _trailer_locale(language: str) -> str:
    return {"de": "de-DE", "en": "en-US"}.get(language, language)


def _strict_youtube_trailer(videos: list, language: str) -> dict | None:
    wanted = str(language or "").strip().casefold()
    candidates = [
        video
        for video in (videos or [])
        if isinstance(video, dict)
        and str(video.get("site") or "").casefold() == "youtube"
        and str(video.get("key") or "").strip()
        and str(video.get("type") or "") in {"Trailer", "Teaser"}
        and str(video.get("iso_639_1") or "").strip().casefold() == wanted
    ]
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda video: (
            bool(video.get("official")),
            str(video.get("type") or "") == "Trailer",
            int(video.get("size") or 0),
            str(video.get("published_at") or ""),
        ),
    )
    return {
        "site": "YouTube",
        "key": str(best.get("key") or "").strip(),
        "name": str(best.get("name") or "Trailer"),
        "official": bool(best.get("official")),
        "language": wanted,
    }


class _TrailerAwareTMDBClient:
    """Proxy a TMDBClient while replacing only its selected trailer payload."""

    def __init__(self, client):
        self._client = client
        self._cache: OrderedDict[tuple[str, str, str], dict | None] = OrderedDict()
        self._cache_lock = threading.RLock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def _language(self) -> str:
        with state.provider_priority_lock:
            languages = set(state.content_languages)
        return _preferred_trailer_language(languages)

    def _fetch_trailer(self, media_type: str, tmdb_id, language: str) -> dict | None:
        key = (media_type, str(tmdb_id or "").strip(), language)
        if not key[1].isdigit():
            return None
        with self._cache_lock:
            if key in self._cache:
                cached = self._cache.pop(key)
                self._cache[key] = cached
                return dict(cached) if cached else None

        response = self._client._request(
            f"/{media_type}/{key[1]}/videos",
            {"language": _trailer_locale(language)},
        ) or {}
        trailer = _strict_youtube_trailer(response.get("results") or [], language)
        with self._cache_lock:
            self._cache[key] = dict(trailer) if trailer else None
            while len(self._cache) > _TRAILER_CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)
        return dict(trailer) if trailer else None

    def _with_trailer(self, payload: dict | None, media_type: str) -> dict | None:
        if payload is None:
            return None
        result = dict(payload)
        result["trailer"] = self._fetch_trailer(
            media_type,
            result.get("tmdb_id"),
            self._language(),
        )
        return result

    def movie(self, *args, **kwargs):
        return self._with_trailer(self._client.movie(*args, **kwargs), "movie")

    def movie_by_id(self, *args, **kwargs):
        return self._with_trailer(self._client.movie_by_id(*args, **kwargs), "movie")

    def series(self, *args, **kwargs):
        return self._with_trailer(self._client.series(*args, **kwargs), "tv")

    def series_by_id(self, *args, **kwargs):
        return self._with_trailer(self._client.series_by_id(*args, **kwargs), "tv")


_proxy_lock = threading.RLock()
_proxy_client = None
_proxy = None


def get_tmdb_client():
    """Return the runtime TMDB client with content-language trailer policy."""
    global _proxy_client, _proxy
    client = state.tmdb_client
    with _proxy_lock:
        if _proxy is None or _proxy_client is not client:
            _proxy_client = client
            _proxy = _TrailerAwareTMDBClient(client)
        return _proxy


_SERVICE_EXPORTS = ("get_tmdb_client",)
publish_service(globals(), _SERVICE_EXPORTS)
