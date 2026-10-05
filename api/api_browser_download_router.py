"""Browser-delivered downloads with per-account daily traffic quotas.

This path deliberately does not enqueue the normal NAS/Jellyfin DownloadJob.
It reuses RoyalDownloader's provider/hoster resolution and then streams the
resolved media to the authenticated browser.
"""

from __future__ import annotations

import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import quote, urlparse

from curl_cffi import requests as curl_requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.network_guard import (
    UnsafeNetworkTarget,
    ensure_public_http_url,
    request_proxy_kwargs,
    safe_proxy_url,
)
from providers.models import parse_episode_slug, strip_episode_suffix


TICKET_TTL_SECONDS = 60 * 60
MAX_TICKETS = 500
MAX_PREPARE_SLUGS = 20
QUOTA_PERSIST_BYTES = 16 * 1024 * 1024
STREAM_CHUNK_BYTES = 256 * 1024


class BrowserDownloadPreference(BaseModel):
    provider: str = Field(default="", max_length=80)
    quality: str = Field(default="", max_length=40)
    hoster_url: str = Field(default="", max_length=2000)


class BrowserDownloadPrepareBody(BaseModel):
    slugs: list[str] = Field(min_length=1, max_length=MAX_PREPARE_SLUGS)
    preferences: dict[str, BrowserDownloadPreference] = Field(default_factory=dict)


@dataclass
class _Ticket:
    token: str
    user_id: str
    slug: str
    preference: BrowserDownloadPreference | None
    created_at: float = field(default_factory=time.time)
    last_used_at: float = 0.0


class _TicketStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tickets: dict[str, _Ticket] = {}

    def _cleanup_locked(self, now: float) -> None:
        cutoff = now - TICKET_TTL_SECONDS
        expired = [
            token for token, ticket in self._tickets.items()
            if ticket.created_at < cutoff
        ]
        for token in expired:
            self._tickets.pop(token, None)
        if len(self._tickets) <= MAX_TICKETS:
            return
        oldest = sorted(
            self._tickets.values(),
            key=lambda item: (item.last_used_at or item.created_at),
        )
        for ticket in oldest[: len(self._tickets) - MAX_TICKETS]:
            self._tickets.pop(ticket.token, None)

    def create(
        self,
        user_id: str,
        slug: str,
        preference: BrowserDownloadPreference | None,
    ) -> _Ticket:
        now = time.time()
        token = secrets.token_urlsafe(32)
        ticket = _Ticket(token, user_id, slug, preference, now, 0.0)
        with self._lock:
            self._cleanup_locked(now)
            self._tickets[token] = ticket
        return ticket

    def get(self, token: str, user_id: str) -> _Ticket | None:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            ticket = self._tickets.get(str(token or ""))
            if not ticket or ticket.user_id != str(user_id):
                return None
            if now - ticket.created_at > TICKET_TTL_SECONDS:
                self._tickets.pop(ticket.token, None)
                return None
            ticket.last_used_at = now
            return ticket


def create_browser_download_router(backend) -> APIRouter:
    router = APIRouter(tags=["browser-download"])
    tickets = _TicketStore()

    def require_user(request: Request) -> dict:
        user = backend.current_user(request.headers, request.cookies)
        if not user or not user.get("id") or not user.get("enabled", True):
            raise HTTPException(401, "Anmeldung erforderlich.")
        return user

    def quota_payload(user_id: str) -> dict:
        quota = backend.USER_STORE.download_quota(user_id)
        plans = backend.USER_STORE.download_plans()
        return {
            **quota,
            "plans": list(plans.values()),
        }

    @router.get("/api/browser-download/quota")
    async def browser_download_quota(request: Request):
        user = require_user(request)
        return await run_in_threadpool(quota_payload, str(user["id"]))

    @router.post("/api/browser-download/prepare")
    async def browser_download_prepare(
        body: BrowserDownloadPrepareBody,
        request: Request,
    ):
        user = require_user(request)
        user_id = str(user["id"])
        quota = await run_in_threadpool(quota_payload, user_id)
        if int(quota["remaining_today_bytes"]) <= 0:
            raise HTTPException(429, "Dein Browser-Download-Limit für heute ist aufgebraucht.")

        unique: list[str] = []
        seen: set[str] = set()
        for value in body.slugs:
            slug = str(value or "").strip()
            if not slug or len(slug) > 1200:
                raise HTTPException(400, "Ungültiger Download-Slug.")
            if slug in seen:
                continue
            seen.add(slug)
            unique.append(slug)

        if not unique:
            raise HTTPException(400, "Keine herunterladbaren Inhalte ausgewählt.")

        downloads = []
        for slug in unique:
            ticket = tickets.create(user_id, slug, body.preferences.get(slug))
            downloads.append({
                "slug": slug,
                "url": f"/api/browser-download/file/{ticket.token}",
                "expires_in_seconds": TICKET_TTL_SECONDS,
            })
        return {"downloads": downloads, "quota": quota}

    @router.get("/api/browser-download/file/{token}")
    async def browser_download_file(token: str, request: Request):
        user = require_user(request)
        user_id = str(user["id"])
        ticket = tickets.get(token, user_id)
        if ticket is None:
            raise HTTPException(404, "Dieser Download-Link ist abgelaufen oder ungültig.")

        quota = await run_in_threadpool(backend.USER_STORE.download_quota, user_id)
        if int(quota["remaining_today_bytes"]) <= 0:
            raise HTTPException(429, "Dein Browser-Download-Limit für heute ist aufgebraucht.")

        try:
            resolved = await run_in_threadpool(_resolve_ticket, backend, ticket)
        except HTTPException:
            raise
        except Exception as exc:
            backend.log(f"Browser-Download konnte nicht aufgelöst werden: {exc}", "warn")
            raise HTTPException(502, f"Downloadquelle konnte nicht vorbereitet werden: {exc}") from exc

        stream_url = str(resolved["url"])
        stream_type = str(resolved["stream_type"] or "").casefold()
        try:
            ensure_public_http_url(stream_url)
        except UnsafeNetworkTarget as exc:
            raise HTTPException(502, f"Unsicheres Downloadziel wurde blockiert: {exc}") from exc

        incoming_range = str(request.headers.get("range") or "").strip()
        if _direct_stream(stream_url, stream_type):
            return await run_in_threadpool(
                _direct_response,
                backend,
                user_id,
                resolved,
                incoming_range,
            )

        if incoming_range:
            raise HTTPException(
                416,
                "Resume ist für diese HLS/DASH-Quelle nicht verfügbar. Bitte den Download neu starten.",
            )
        return _adaptive_response(backend, user_id, resolved)

    return router


def _resolve_ticket(backend, ticket: _Ticket) -> dict[str, Any]:
    slug = ticket.slug
    episode_info = parse_episode_slug(slug)
    scheduled_reason = _scheduled_episode_reason(backend, slug)
    if scheduled_reason:
        raise RuntimeError(scheduled_reason)

    movie = backend.state.fp_movies.get(slug)
    if movie is None:
        if episode_info:
            try:
                movie = backend.load_movie_for_slug(slug)
            except Exception:
                movie = backend._episode_placeholder(slug)
        else:
            movie = backend.load_movie_for_slug(slug)

    if episode_info and (movie is None or not movie.hosters):
        try:
            refreshed = backend.load_movie_for_slug(slug)
        except Exception:
            refreshed = None
        if refreshed and refreshed.hosters:
            movie = refreshed

    if movie is None:
        raise RuntimeError("Inhalt konnte nicht geladen werden.")

    source_movies = [movie]
    if not episode_info:
        preferred, fallbacks = backend._preferred_movie_sources(
            slug, movie, ticket.preference,
        )
        movie = preferred
        source_movies = [movie]
        for fallback in fallbacks or []:
            if fallback.url not in {item.url for item in source_movies}:
                source_movies.append(fallback)

    original_title = (
        strip_episode_suffix(movie.title) or movie.title
        if episode_info
        else backend.clean_movie_title(movie.title)
    )

    unsupported_domains: set[str] = set()
    barren_hoster_urls: set[str] = set()
    result = None
    selected_movie = movie

    for candidate in source_movies:
        if not candidate.hosters:
            continue
        with backend.state.hoster_extract_lock:
            candidate_result = backend._extract_from_movie(
                candidate,
                unsupported_domains,
                barren_hoster_urls=barren_hoster_urls,
            )
        if candidate_result.stream_info:
            selected_movie = candidate
            result = candidate_result
            break

    if result is None:
        if episode_info:
            base_slug, season, episode = episode_info
            alternatives = backend.find_episode_fallbacks(
                original_title,
                season,
                episode,
                aliases=backend._episode_fallback_aliases(slug, original_title),
                source_slug=slug,
            )
        else:
            alternatives = backend.find_movie_source_fallbacks(
                source_movies[0],
                slug,
                {item.url for item in source_movies},
            )

        known_urls = {item.url for item in source_movies}
        for candidate in alternatives:
            if candidate.url in known_urls or not candidate.hosters:
                continue
            known_urls.add(candidate.url)
            with backend.state.hoster_extract_lock:
                candidate_result = backend._extract_from_movie(
                    candidate,
                    unsupported_domains,
                    barren_hoster_urls=barren_hoster_urls,
                )
            if candidate_result.stream_info:
                selected_movie = candidate
                result = candidate_result
                break

    if result is None or not result.stream_info:
        raise RuntimeError("kein nutzbarer Hoster oder Stream verfügbar")

    stream_url, stream_type = result.stream_info
    if episode_info:
        _base_slug, season, episode = episode_info
        filename = backend.build_filename(original_title, season, episode)
    else:
        primary = source_movies[0]
        filename = backend.build_movie_filename(
            backend.clean_movie_title(primary.title),
            str(primary.year or ""),
        )

    backend.log(
        f"Browser-Download bereit: {slug} · "
        f"{result.hoster_used or 'Hoster'} · {stream_type}"
    )
    return {
        "slug": slug,
        "url": str(stream_url),
        "stream_type": str(stream_type or ""),
        "referer": str(result.referer or ""),
        "origin": str(result.origin or ""),
        "headers": dict(getattr(result, "headers", {}) or {}),
        "audio_language": str(getattr(result, "audio_language", "") or ""),
        "provider": str(result.provider or backend._movie_provider(selected_movie, slug)),
        "hoster": str(result.hoster_used or ""),
        "filename": _safe_filename(filename),
    }


def _scheduled_episode_reason(backend, slug: str) -> str:
    parsed = parse_episode_slug(slug)
    if not parsed:
        return ""
    if parsed[1] <= 0:
        return "Staffel 0 wird nicht unterstützt"
    series = backend.state.series_cache.get(parsed[0])
    if series is None:
        return ""
    episode = next(
        (item for item in series.all_episodes if item.slug == slug),
        None,
    )
    if episode is None or episode.is_released:
        return ""
    return (
        f"noch nicht veröffentlicht (ab {episode.release_label})"
        if episode.release_label and episode.release_label != "Demnächst"
        else "noch nicht veröffentlicht"
    )


def _direct_stream(url: str, stream_type: str) -> bool:
    path = (urlparse(url).path or "").casefold()
    if path.endswith((".m3u8", ".mpd")):
        return False
    return stream_type in {"mp4", "mkv", "webm", "direct", "file"}


def _source_headers(resolved: dict[str, Any]) -> dict[str, str]:
    headers = {
        "Accept": "video/webm,video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    for key, value in dict(resolved.get("headers") or {}).items():
        key = str(key or "").strip()
        value = str(value or "")
        if re.fullmatch(r"[A-Za-z0-9-]{1,60}", key) and "\r" not in value and "\n" not in value:
            headers[key] = value
    if resolved.get("referer"):
        headers["Referer"] = str(resolved["referer"])
    if resolved.get("origin"):
        headers["Origin"] = str(resolved["origin"])
    return headers


def _direct_response(
    backend,
    user_id: str,
    resolved: dict[str, Any],
    incoming_range: str,
):
    stream_url = str(resolved["url"])
    headers = _source_headers(resolved)
    if incoming_range:
        headers["Range"] = incoming_range

    if urlparse(stream_url).hostname and urlparse(stream_url).hostname.endswith(".vincdn.net"):
        headers.pop("User-Agent", None)

    response = curl_requests.get(
        stream_url,
        stream=True,
        headers=headers,
        timeout=30,
        allow_redirects=True,
        impersonate="chrome136",
        **request_proxy_kwargs(stream_url),
    )

    if response.status_code not in {200, 206}:
        response.close()
        raise HTTPException(
            502,
            f"Downloadquelle antwortet mit HTTP {response.status_code}.",
        )

    content_type = str(response.headers.get("Content-Type") or "").casefold()
    if any(marker in content_type for marker in ("text/", "html", "json", "xml")):
        response.close()
        raise HTTPException(502, "Die Quelle lieferte keine Mediendatei.")

    content_length = _positive_int(response.headers.get("Content-Length"))
    quota = backend.USER_STORE.download_quota(user_id)
    remaining = int(quota["remaining_today_bytes"])
    if content_length and content_length > remaining:
        response.close()
        raise HTTPException(
            413,
            f"Der Download ist größer als dein verbleibendes Tagesvolumen "
            f"({_format_bytes(remaining)} verfügbar).",
        )

    status_code = 206 if response.status_code == 206 else 200
    outgoing_headers = {
        "Content-Disposition": _content_disposition(str(resolved["filename"])),
        "Cache-Control": "private, no-store",
        "Accept-Ranges": str(response.headers.get("Accept-Ranges") or "bytes"),
        "X-Royal-Download-Plan": str(quota["plan"]),
        "X-Royal-Quota-Remaining": str(remaining),
    }
    if content_length:
        outgoing_headers["Content-Length"] = str(content_length)
    content_range = str(response.headers.get("Content-Range") or "").strip()
    if content_range:
        outgoing_headers["Content-Range"] = content_range

    media_type = str(response.headers.get("Content-Type") or "application/octet-stream")
    return StreamingResponse(
        _quota_curl_iterator(backend, user_id, response),
        status_code=status_code,
        media_type=media_type,
        headers=outgoing_headers,
    )


def _quota_curl_iterator(backend, user_id: str, response) -> Iterator[bytes]:
    unflushed = 0
    try:
        for chunk in response.iter_content(chunk_size=STREAM_CHUNK_BYTES):
            if not chunk:
                continue
            accepted = int(
                backend.USER_STORE.consume_download_bytes(
                    user_id,
                    len(chunk),
                    persist=False,
                )
            )
            if accepted <= 0:
                break
            unflushed += accepted
            yield chunk[:accepted]
            if unflushed >= QUOTA_PERSIST_BYTES:
                backend.USER_STORE.flush_download_usage(user_id)
                unflushed = 0
            if accepted < len(chunk):
                break
    finally:
        try:
            response.close()
        finally:
            backend.USER_STORE.flush_download_usage(user_id)


def _adaptive_response(backend, user_id: str, resolved: dict[str, Any]):
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--no-playlist",
        "--socket-timeout", "15",
        "--retries", "2",
        "--fragment-retries", "2",
        "--concurrent-fragments", "8",
        "--extractor-args", "generic:impersonate",
        "--proxy", safe_proxy_url(),
        "-f", "best[height<=1080]/best",
        "-o", "-",
    ]

    referer = str(resolved.get("referer") or "")
    origin = str(resolved.get("origin") or "")
    if referer:
        command += ["--referer", referer]
    if origin:
        command += ["--add-header", f"Origin:{origin}"]
    for key, value in dict(resolved.get("headers") or {}).items():
        key = str(key or "").strip()
        value = str(value or "")
        if re.fullmatch(r"[A-Za-z0-9-]{1,60}", key) and "\r" not in value and "\n" not in value:
            command += ["--add-header", f"{key}:{value}"]

    command.append(str(resolved["url"]))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    quota = backend.USER_STORE.download_quota(user_id)
    headers = {
        "Content-Disposition": _content_disposition(str(resolved["filename"])),
        "Cache-Control": "private, no-store",
        "X-Royal-Download-Plan": str(quota["plan"]),
        "X-Royal-Quota-Remaining": str(quota["remaining_today_bytes"]),
    }
    return StreamingResponse(
        _quota_process_iterator(backend, user_id, process),
        media_type="application/octet-stream",
        headers=headers,
    )


def _quota_process_iterator(backend, user_id: str, process: subprocess.Popen) -> Iterator[bytes]:
    unflushed = 0
    try:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            accepted = int(
                backend.USER_STORE.consume_download_bytes(
                    user_id,
                    len(chunk),
                    persist=False,
                )
            )
            if accepted <= 0:
                break
            unflushed += accepted
            yield chunk[:accepted]
            if unflushed >= QUOTA_PERSIST_BYTES:
                backend.USER_STORE.flush_download_usage(user_id)
                unflushed = 0
            if accepted < len(chunk):
                break
    finally:
        _stop_process(process)
        backend.USER_STORE.flush_download_usage(user_id)


def _stop_process(process: subprocess.Popen) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _safe_filename(value: str) -> str:
    name = str(value or "RoyalDownloader.mp4").replace("\\", "_").replace("/", "_")
    name = "".join(char if ord(char) >= 32 else "_" for char in name).strip(" .")
    return name[:220] or "RoyalDownloader.mp4"


def _content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(_safe_filename(filename), safe='')}"


def _format_bytes(value: int) -> str:
    value = max(0, int(value or 0))
    if value >= 1024 ** 3:
        return f"{value / 1024 ** 3:.1f} GB"
    if value >= 1024 ** 2:
        return f"{value / 1024 ** 2:.1f} MB"
    return f"{value / 1024:.1f} KB"
