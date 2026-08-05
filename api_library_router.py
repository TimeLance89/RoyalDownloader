"""Cover proxy, movie subscriptions, and series watchlist routes."""

# Remote media/provider failures are contained and translated by this boundary.
# ruff: noqa: BLE001, S110

from __future__ import annotations

import ipaddress
import threading
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from jellyfin_client import JellyfinClient
from movie_subscription_policy import (
    MOVIE_CLEANUP_DEFAULT,
    MOVIE_CLEANUP_LABELS,
    MOVIE_CLEANUP_WATCHED,
    MOVIE_QUALITY_DEFAULT,
    MOVIE_QUALITY_LABELS,
    MOVIE_QUALITY_TARGETS,
    movie_quality_rank,
    normalize_movie_cleanup,
    normalize_movie_quality,
    select_upgrade_quality,
)
from network_guard import is_public_http_url
from providers.models import (
    FilmpalastMovie,
    FilmpalastSeries,
    parse_episode_slug,
)
from tmdb_client import SERIES_CACHE_TTL
from watchlist_policy import (
    CLEANUP_MODE_KEEP,
    CLEANUP_MODE_LABELS,
    WATCH_MODE_DEFAULT,
    WATCH_MODE_LABELS,
    WATCH_MODE_NEXT_SEASON,
    normalize_cleanup_mode,
    normalize_episode_history,
    normalize_watch_mode,
    select_cleanup_items,
    select_missing_episode_slugs,
    serialize_episode_history,
)

router = APIRouter(tags=["library"])


def _unbound_dependency(*_args, **_kwargs):
    raise RuntimeError("Library router dependencies are not configured")


state: Any = None
_auto_download_new_episodes = _unbound_dependency
_cancel_queue_slugs = _unbound_dependency
_cancel_withdrawn_watchlist_slugs = _unbound_dependency
_enqueue_automatic_downloads = _unbound_dependency
_job_queue_slugs = _unbound_dependency
_norm_title = _unbound_dependency
_persist_movie_subscriptions_background = _unbound_dependency
_persist_new_queue_claims = _unbound_dependency
_persist_watchlist_background = _unbound_dependency
_persistence_status = _unbound_dependency
_release_removed_queue_slugs = _unbound_dependency
_require_persistent_snapshot = _unbound_dependency
_seerr_terminal_without_job = _unbound_dependency
_telegram_terminal_without_job = _unbound_dependency
_unreleased_episode_keys = _unbound_dependency
_unreleased_episode_slugs = _unbound_dependency
broadcast = _unbound_dependency
build_queue_payload = _unbound_dependency
compute_downloaded_episodes = _unbound_dependency
find_movie_source_fallbacks = _unbound_dependency
get_fp_scraper = _unbound_dependency
get_jellyfin_client = _unbound_dependency
get_jellyfin_episodes = _unbound_dependency
get_jellyfin_library = _unbound_dependency
get_jellyfin_series = _unbound_dependency
get_jellyfin_user_episodes = _unbound_dependency
get_series_for_value = _unbound_dependency
get_sto_scraper = _unbound_dependency
get_tmdb_series = _unbound_dependency
hydrate_watchlist_artwork = _unbound_dependency
is_within_download_window = _unbound_dependency
load_movie_for_slug = _unbound_dependency
log = _unbound_dependency
resolve_tmdb_movie_sources = _unbound_dependency
series_to_dict = _unbound_dependency
watchlist_lookup = _unbound_dependency
watchlist_payload = _unbound_dependency

_DYNAMIC_CALLS = (
    "_auto_download_new_episodes",
    "_cancel_queue_slugs",
    "_cancel_withdrawn_watchlist_slugs",
    "_enqueue_automatic_downloads",
    "_job_queue_slugs",
    "_norm_title",
    "_persist_movie_subscriptions_background",
    "_persist_new_queue_claims",
    "_persist_watchlist_background",
    "_persistence_status",
    "_release_removed_queue_slugs",
    "_require_persistent_snapshot",
    "_seerr_terminal_without_job",
    "_telegram_terminal_without_job",
    "_unreleased_episode_keys",
    "_unreleased_episode_slugs",
    "broadcast",
    "build_queue_payload",
    "compute_downloaded_episodes",
    "find_movie_source_fallbacks",
    "get_fp_scraper",
    "get_jellyfin_client",
    "get_jellyfin_episodes",
    "get_jellyfin_library",
    "get_jellyfin_series",
    "get_jellyfin_user_episodes",
    "get_series_for_value",
    "get_sto_scraper",
    "get_tmdb_series",
    "hydrate_watchlist_artwork",
    "is_within_download_window",
    "load_movie_for_slug",
    "log",
    "resolve_tmdb_movie_sources",
    "series_to_dict",
    "watchlist_lookup",
    "watchlist_payload",
)


def create_library_router(backend) -> APIRouter:
    """Bind library services dynamically and return their domain router."""

    def dynamic(name):
        return lambda *args, **kwargs: getattr(backend, name)(*args, **kwargs)

    globals().update({name: dynamic(name) for name in _DYNAMIC_CALLS})
    globals()["state"] = backend.state
    return router


# ── Cover-Proxy ──────────────────────────────────────────────────────────────
def _safe_public_http_url(raw_url: str) -> bool:
    return is_public_http_url(raw_url)


COVER_FAIL_RETRY_SECONDS = 180.0
COVER_MAX_BYTES = 10 * 1024 * 1024
COVER_CACHE_MAX_BYTES = 64 * 1024 * 1024
COVER_CACHE_MAX_ENTRIES = 256
COVER_MAX_REDIRECTS = 3
COVER_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
COVER_IMAGE_TYPES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/x-png",
    "image/webp",
    "image/gif",
    "image/avif",
})


def _cover_log_target(raw_url: str) -> str:
    """Loggt nie Query, Fragment oder Zugangsdaten einer Bild-URL."""
    try:
        parsed = urlparse(raw_url)
        host = parsed.hostname or "unbekannter-host"
        path = (parsed.path or "/")[:160]
        return f"{host}{path}"
    except (TypeError, ValueError):
        return "ungültige-url"


def _close_cover_response(response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _fetch_cover_data(url: str) -> tuple | None:
    if not _safe_public_http_url(url):
        return None
    with state.cover_cache_lock:
        if url in state.cover_cache:
            state.cover_cache.move_to_end(url)
            return state.cover_cache[url]
        failed_at = state.cover_fail_cache.get(url)
        if failed_at is not None:
            if time.time() - failed_at < COVER_FAIL_RETRY_SECONDS:
                return None
            del state.cover_fail_cache[url]
    try:
        def _download(manager, curl_session, referer: str) -> tuple:
            current_url = url
            current_referer = referer
            for redirect_index in range(COVER_MAX_REDIRECTS + 1):
                # Jeden Hop vor dem Request erneut prüfen. Damit kann ein
                # öffentlicher Bildhost nicht auf localhost/private Netze umleiten.
                if not _safe_public_http_url(current_url):
                    raise RuntimeError("unsicheres Bildziel")
                headers = manager._browser_headers(current_url, current_referer)
                headers.update({
                    "Accept": "image/webp,image/png,image/jpeg,image/gif,*/*;q=0.1",
                    "Sec-Fetch-Dest": "image",
                    "Sec-Fetch-Mode": "no-cors",
                })
                headers.pop("Sec-Fetch-User", None)
                headers.pop("Upgrade-Insecure-Requests", None)
                resp = curl_session.get(
                    current_url,
                    headers=headers,
                    timeout=20,
                    stream=True,
                    allow_redirects=False,
                )
                try:
                    peer_ip = str(getattr(resp, "primary_ip", "") or "").strip()
                    if not peer_ip or not ipaddress.ip_address(peer_ip).is_global:
                        raise RuntimeError("unsichere Zieladresse nach DNS-Auflösung")
                    if resp.status_code in COVER_REDIRECT_STATUSES:
                        location = str(resp.headers.get("Location") or "").strip()
                        if not location or redirect_index >= COVER_MAX_REDIRECTS:
                            raise RuntimeError("ungültige oder zu tiefe Bildweiterleitung")
                        next_url = urljoin(current_url, location)
                        if not _safe_public_http_url(next_url):
                            raise RuntimeError("unsicheres Weiterleitungsziel")
                        current_referer = current_url
                        current_url = next_url
                        continue
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code}")
                    content_type = (
                        resp.headers.get("Content-Type") or ""
                    ).split(";", 1)[0].strip().lower()
                    if content_type not in COVER_IMAGE_TYPES:
                        raise RuntimeError("nicht unterstütztes Bildformat")
                    declared = int(resp.headers.get("Content-Length", 0) or 0)
                    if declared > COVER_MAX_BYTES:
                        raise RuntimeError("Bild ist größer als 10 MB")
                    content = bytearray()
                    for chunk in resp.iter_content(chunk_size=128 * 1024):
                        content.extend(chunk)
                        if len(content) > COVER_MAX_BYTES:
                            raise RuntimeError("Bild ist größer als 10 MB")
                    return bytes(content), content_type
                finally:
                    _close_cover_response(resp)
            raise RuntimeError("zu viele Bildweiterleitungen")

        parsed_url = urlparse(url)
        hostname = (parsed_url.hostname or "").casefold()
        referer = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        manager = (
            get_sto_scraper().session
            if hostname == "serienstream.to" or hostname.endswith(".serienstream.to")
            else get_fp_scraper().session
        )
        # Eine eigene Curl-Session pro Bild verhindert Datenrennen mit parallel
        # laufenden Provider-Scrapes und übernimmt dennoch gespeicherte Cookies.
        curl_session = manager._make_curl_session()
        try:
            data = _download(manager, curl_session, referer)
        finally:
            _close_cover_response(curl_session)
    except Exception as exc:
        reason = str(exc)[:160] if isinstance(exc, RuntimeError) else type(exc).__name__
        log(f"Cover-Laden fehlgeschlagen ({_cover_log_target(url)}): {reason}", "warn")
        with state.cover_cache_lock:
            state.cover_fail_cache[url] = time.time()
            state.cover_fail_cache.move_to_end(url)
            while len(state.cover_fail_cache) > 512:
                state.cover_fail_cache.popitem(last=False)
        return None
    with state.cover_cache_lock:
        state.cover_cache[url] = data
        state.cover_cache.move_to_end(url)
        cached_bytes = sum(len(item[0]) for item in state.cover_cache.values())
        while state.cover_cache and (
            len(state.cover_cache) > COVER_CACHE_MAX_ENTRIES
            or cached_bytes > COVER_CACHE_MAX_BYTES
        ):
            _old_url, old_data = state.cover_cache.popitem(last=False)
            cached_bytes -= len(old_data[0])
        state.cover_fail_cache.pop(url, None)
    return data


@router.get("/api/v1/cover")
@router.get("/api/cover")
async def api_cover(url: str):
    data = await run_in_threadpool(_fetch_cover_data, url)
    if not data:
        raise HTTPException(502, "Cover konnte nicht geladen werden.")
    content, content_type = data
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
    )


# ── Film-Abonnements ─────────────────────────────────────────────────────────
def movie_subscription_key(tmdb_id="", title: str = "", year: str = "") -> str:
    tmdb = str(tmdb_id or "").strip()
    if tmdb:
        return f"tmdb:{tmdb}"
    return f"title:{_norm_title(title)}:{str(year or '').strip()}"


def movie_subscription_lookup(key: str) -> dict | None:
    return next(
        (entry for entry in state.movie_subscriptions if entry.get("key") == key),
        None,
    )


def _movie_subscription_jellyfin_item(entry: dict, items: list[dict] | None) -> dict | None:
    if not items:
        return None
    tmdb_id = str(entry.get("tmdb_id") or "").strip()
    if tmdb_id:
        exact = next(
            (item for item in items if str(item.get("tmdb_id") or "") == tmdb_id),
            None,
        )
        if exact:
            return exact
    wanted = _norm_title(entry.get("title", ""))
    year = str(entry.get("year") or "")
    for item in items:
        aliases = (
            item.get("name", ""), item.get("original_title", ""), item.get("sort_name", ""),
        )
        if wanted not in {_norm_title(value) for value in aliases if value}:
            continue
        item_year = str(item.get("year") or "")
        if year and item_year and year != item_year:
            continue
        return item
    return None


def movie_subscriptions_payload() -> dict:
    with state.queue_claim_lock, state.movie_subscriptions_lock:
        items = []
        for stored in state.movie_subscriptions:
            entry = dict(stored)
            entry["cleanup_mode"] = normalize_movie_cleanup(entry.get("cleanup_mode"))
            entry["cleanup_mode_label"] = MOVIE_CLEANUP_LABELS[entry["cleanup_mode"]]
            entry["target_quality"] = normalize_movie_quality(entry.get("target_quality"))
            entry["target_quality_label"] = MOVIE_QUALITY_LABELS[entry["target_quality"]]
            entry["queued"] = bool(entry.get("pending_slug") in state.picked)
            if entry.get("watched_deleted"):
                entry["status"] = "watched_deleted"
            elif entry["queued"]:
                entry["status"] = "queued"
            elif entry.get("last_error"):
                entry["status"] = "failed"
            elif entry.get("upgrade_available_rank"):
                entry["status"] = "upgrade"
            else:
                entry["status"] = "current"
            items.append(entry)
    return {
        "movie_subscriptions": items,
        "persistence": _persistence_status("movie_subscriptions"),
    }


def _movie_subscription_sources(entry: dict) -> list[FilmpalastMovie]:
    tmdb_id = str(entry.get("tmdb_id") or "").strip()
    if tmdb_id:
        return resolve_tmdb_movie_sources(tmdb_id)
    slug = str(entry.get("source_slug") or "").strip()
    if not slug:
        return []
    movie = state.fp_movies.get(slug) or load_movie_for_slug(slug)
    if not movie:
        return []
    state.fp_movies[slug] = movie
    return [movie, *find_movie_source_fallbacks(movie, slug, {movie.url})]


def _prepare_movie_subscription_upgrade(
    entry: dict, sources: list[FilmpalastMovie],
) -> tuple[FilmpalastMovie | None, list[FilmpalastMovie], int, str]:
    current_rank = max(0, int(entry.get("current_quality_rank") or 0))
    target = normalize_movie_quality(entry.get("target_quality"))
    qualities = [
        hoster.quality
        for source in sources
        for hoster in source.hosters
    ]
    selected = select_upgrade_quality(qualities, current_rank, target)
    if not selected:
        return None, [], 0, ""
    selected_rank, selected_label = selected
    ceiling = MOVIE_QUALITY_TARGETS[target]
    prepared = []
    for source in sources:
        hosters = [
            hoster for hoster in source.hosters
            if current_rank < movie_quality_rank(hoster.quality) <= ceiling
        ]
        if not hosters:
            continue
        clone = replace(source, hosters=list(hosters))
        clone.hosters.sort(
            key=lambda hoster: (
                movie_quality_rank(hoster.quality) != selected_rank,
                -movie_quality_rank(hoster.quality),
            )
        )
        clone._preferred_quality = selected_label
        clone._allow_quality_upgrade = True
        prepared.append(clone)
    prepared.sort(
        key=lambda movie: max(
            (movie_quality_rank(hoster.quality) for hoster in movie.hosters),
            default=0,
        ) != selected_rank
    )
    return (prepared[0] if prepared else None), prepared[1:], selected_rank, selected_label


def check_movie_subscriptions(entries: list[dict] | None = None) -> int:
    """Prüft Gesehen-Regeln und reiht ausschließlich echte Upgrades ein."""
    if not state.movie_subscription_check_lock.acquire(blocking=False):
        return 0
    try:
        with state.movie_subscriptions_lock:
            selected_entries = list(entries if entries is not None else state.movie_subscriptions)
        jf_client = get_jellyfin_client()
        user_id = str(state.jellyfin_cfg.get("user_id") or "").strip()
        user_movies = (
            jf_client.list_movies_with_user_data(user_id)
            if jf_client.configured and user_id else None
        )
        library_movies = get_jellyfin_library(force=True) if jf_client.configured else None
        checked = 0
        for entry in selected_entries:
            with state.movie_subscriptions_lock:
                if not any(current is entry for current in state.movie_subscriptions):
                    continue
                if entry.get("pending_slug") in state.picked:
                    continue
            checked += 1
            now = time.time()
            jf_item = _movie_subscription_jellyfin_item(
                entry, user_movies if user_movies is not None else library_movies,
            )
            with state.movie_subscriptions_lock:
                if jf_item:
                    entry["current_quality_rank"] = max(
                        int(entry.get("current_quality_rank") or 0),
                        int(jf_item.get("quality_rank") or 0),
                    )
                    entry["existing_path"] = str(jf_item.get("path") or "")
                entry["last_checked"] = now

            if (
                normalize_movie_cleanup(entry.get("cleanup_mode")) == MOVIE_CLEANUP_WATCHED
                and jf_item and jf_item.get("played") and not entry.get("watched_deleted")
            ):
                if jf_client.delete_item(jf_item.get("id", "")):
                    with state.movie_subscriptions_lock:
                        entry["watched_deleted"] = True
                        entry["last_error"] = ""
                        entry["cleanup_last_error"] = ""
                        entry["cleanup_deleted_at"] = now
                    log(f"Film-Abo: «{entry['title']}» nach dem Ansehen gelöscht.")
                else:
                    with state.movie_subscriptions_lock:
                        entry["last_error"] = "Gesehener Film konnte in Jellyfin nicht gelöscht werden"
                continue
            if (
                normalize_movie_cleanup(entry.get("cleanup_mode")) == MOVIE_CLEANUP_WATCHED
                and jf_client.configured and not user_id
            ):
                with state.movie_subscriptions_lock:
                    entry["cleanup_last_error"] = "Jellyfin-Profil für den Gesehen-Status fehlt"
            elif user_id or normalize_movie_cleanup(entry.get("cleanup_mode")) != MOVIE_CLEANUP_WATCHED:
                with state.movie_subscriptions_lock:
                    entry["cleanup_last_error"] = ""

            if entry.get("watched_deleted") or not entry.get("upgrade_enabled", True):
                continue
            if jf_item and int(jf_item.get("quality_rank") or 0) <= 0:
                with state.movie_subscriptions_lock:
                    entry["last_error"] = "Jellyfin konnte die vorhandene Filmqualität nicht ermitteln"
                continue
            try:
                sources = _movie_subscription_sources(entry)
                primary, fallbacks, rank, label = _prepare_movie_subscription_upgrade(entry, sources)
            except Exception as exc:
                with state.movie_subscriptions_lock:
                    entry["last_error"] = str(exc)[:240]
                continue
            with state.movie_subscriptions_lock:
                entry["upgrade_available_rank"] = rank
                entry["upgrade_available_quality"] = label
                if not primary:
                    entry["last_error"] = ""
                    continue
                if not state.automation.get("auto_download") or not is_within_download_window():
                    entry["last_error"] = ""
                    continue
                slug = str(entry.get("source_slug") or entry.get("key") or "")
                entry["pending_slug"] = slug
                entry["last_error"] = ""
            state.fp_movies[slug] = primary
            with state.queue_lifecycle_lock, state.queue_claim_lock:
                if slug in state.picked:
                    continue
                state.picked.add(slug)
            if not _persist_new_queue_claims({slug}):
                with state.movie_subscriptions_lock:
                    entry["pending_slug"] = ""
                    entry["last_error"] = "Queue-Zustand konnte nicht gespeichert werden"
                continue
            accepted = _enqueue_automatic_downloads(
                [slug], movie_fallbacks={slug: fallbacks},
                taste_source="movie-subscription",
            )
            if slug not in accepted:
                with state.queue_claim_lock:
                    state.picked.discard(slug)
                with state.movie_subscriptions_lock:
                    entry["pending_slug"] = ""
                    entry["last_error"] = "Upgrade konnte nicht eingereiht werden"
            else:
                log(
                    f"Film-Abo: Qualitäts-Upgrade für «{entry['title']}» "
                    f"auf {label or f'{rank}p'} eingereiht."
                )
        with state.movie_subscriptions_lock:
            _persist_movie_subscriptions_background()
        payload = movie_subscriptions_payload()
        broadcast({"type": "movie_subscriptions_update", **payload})
        return checked
    finally:
        state.movie_subscription_check_lock.release()


class MovieSubscriptionBody(BaseModel):
    source_slug: str
    title: str
    year: str = ""
    tmdb_id: int | None = None
    cover_url: str = ""
    target_quality: str = MOVIE_QUALITY_DEFAULT
    cleanup_mode: str = MOVIE_CLEANUP_DEFAULT
    upgrade_enabled: bool = True


@router.post("/api/v1/movie-subscriptions")
@router.post("/api/movie-subscriptions")
async def api_movie_subscription_save(body: MovieSubscriptionBody):
    if body.target_quality not in MOVIE_QUALITY_LABELS:
        raise HTTPException(400, "Unbekannte Zielqualität.")
    if body.cleanup_mode not in MOVIE_CLEANUP_LABELS:
        raise HTTPException(400, "Unbekannte Löschregel.")
    def _work():
        key = movie_subscription_key(body.tmdb_id, body.title, body.year)
        with state.movie_subscriptions_lock:
            candidate = deepcopy(state.movie_subscriptions)
            entry = next((item for item in candidate if item.get("key") == key), None)
            if entry is None:
                entry = {
                    "key": key, "source_slug": body.source_slug,
                    "title": body.title.strip(), "year": body.year.strip(),
                    "tmdb_id": body.tmdb_id, "cover_url": body.cover_url,
                    "current_quality_rank": 0, "current_quality": "",
                    "last_error": "", "cleanup_last_error": "",
                    "pending_slug": "", "watched_deleted": False,
                }
                candidate.append(entry)
            entry.update({
                "source_slug": body.source_slug,
                "target_quality": normalize_movie_quality(body.target_quality),
                "cleanup_mode": normalize_movie_cleanup(body.cleanup_mode),
                "upgrade_enabled": bool(body.upgrade_enabled),
            })
            if entry["cleanup_mode"] != MOVIE_CLEANUP_WATCHED:
                entry["watched_deleted"] = False
                entry["cleanup_last_error"] = ""
            _require_persistent_snapshot("movie_subscriptions", candidate)
            state.movie_subscriptions = candidate
        movie = state.fp_movies.get(body.source_slug)
        state.taste_profile.record_event(
            "subscription", source="movie-subscription", media_type="movie",
            item_key=f"movie:{body.tmdb_id or body.source_slug or key}",
            title=body.title,
            metadata={
                "genres": list(movie.genres or []) if movie else [],
                "year": body.year,
                "runtime": movie.runtime if movie else "",
            },
        )
        threading.Thread(
            target=check_movie_subscriptions, args=([entry],), daemon=True,
        ).start()
        return movie_subscriptions_payload()

    return await run_in_threadpool(_work)


@router.get("/api/v1/movie-subscriptions")
@router.get("/api/movie-subscriptions")
async def api_movie_subscriptions_get():
    return movie_subscriptions_payload()


class MovieSubscriptionKeysBody(BaseModel):
    keys: list[str] | None = None


@router.post("/api/v1/movie-subscriptions/check")
@router.post("/api/movie-subscriptions/check")
async def api_movie_subscriptions_check(body: MovieSubscriptionKeysBody):
    with state.movie_subscriptions_lock:
        entries = (
            list(state.movie_subscriptions)
            if not body.keys
            else [entry for entry in state.movie_subscriptions if entry.get("key") in body.keys]
        )
    checked = await run_in_threadpool(check_movie_subscriptions, entries)
    return {"checked": checked, **movie_subscriptions_payload()}


@router.post("/api/v1/movie-subscriptions/remove")
@router.post("/api/movie-subscriptions/remove")
async def api_movie_subscriptions_remove(body: MovieSubscriptionKeysBody):
    def _work():
        keys = set(body.keys or [])
        with state.movie_subscriptions_lock:
            pending = {
                str(entry.get("pending_slug") or "")
                for entry in state.movie_subscriptions
                if entry.get("key") in keys and entry.get("pending_slug")
            }
            candidate = [
                entry for entry in state.movie_subscriptions
                if entry.get("key") not in keys
            ]
            _require_persistent_snapshot("movie_subscriptions", candidate)
            state.movie_subscriptions = candidate
        if pending:
            _cancel_queue_slugs(pending, "Film-Abo entfernt")
        return movie_subscriptions_payload()

    return await run_in_threadpool(_work)


# ── Bibliothek (Watchlist) ───────────────────────────────────────────────────
class WatchlistAddBody(BaseModel):
    base_slug: str
    title: str
    sample_url: str
    known_slugs: list[str]
    download_mode: str = WATCH_MODE_DEFAULT
    cleanup_mode: str | None = None
    tmdb_id: int | None = None
    aliases: list[str] | None = None
    season_episode_counts: dict[str, int] | None = None
    season_counts_checked_at: float = 0.0


@router.post("/api/v1/watchlist/add")
@router.post("/api/watchlist/add")
async def api_watchlist_add(body: WatchlistAddBody):
    if body.download_mode not in WATCH_MODE_LABELS:
        raise HTTPException(400, "Unbekannte Abo-Regel.")
    if body.cleanup_mode is not None and body.cleanup_mode not in CLEANUP_MODE_LABELS:
        raise HTTPException(400, "Unbekannte Löschregel.")
    incoming_id = str(body.tmdb_id or "").strip()
    incoming_tmdb = None
    if incoming_id:
        incoming_tmdb = await run_in_threadpool(
            get_tmdb_series, body.title, incoming_id,
        )

    def _work():
        entry = None
        with state.watchlist_lock:
            previous_watchlist = deepcopy(state.watchlist)
            if watchlist_lookup(body.base_slug) is None:
                direct_incoming_titles = {
                    _norm_title(value)
                    for value in (body.title, *(body.aliases or []))
                    if _norm_title(value)
                }
                canonical_incoming_titles = {
                    _norm_title(value)
                    for value in (
                        (incoming_tmdb or {}).get("title", ""),
                        (incoming_tmdb or {}).get("original_title", ""),
                    )
                    if _norm_title(value)
                }
                incoming_titles = direct_incoming_titles | canonical_incoming_titles
                duplicate = None
                duplicate_can_migrate = False
                for current in state.watchlist:
                    current_id = str(current.get("tmdb_id") or "").strip()
                    if incoming_id and current_id:
                        if incoming_id == current_id:
                            duplicate = current
                            break
                        continue
                    current_titles = {
                        _norm_title(value)
                        for value in (current.get("title", ""), *(current.get("aliases") or []))
                        if _norm_title(value)
                    }
                    if incoming_titles & current_titles:
                        duplicate = current
                        duplicate_can_migrate = bool(
                            incoming_id
                            and not current_id
                            and not (direct_incoming_titles & current_titles)
                            and (canonical_incoming_titles & current_titles)
                        )
                        break
                if duplicate is not None:
                    if duplicate_can_migrate:
                        duplicate["tmdb_id"] = body.tmdb_id
                        duplicate["aliases"] = list(dict.fromkeys(filter(None, (
                            duplicate.get("title", ""),
                            *(duplicate.get("aliases") or []),
                            body.title,
                            *(body.aliases or []),
                            (incoming_tmdb or {}).get("title", ""),
                            (incoming_tmdb or {}).get("original_title", ""),
                        ))))
                        if (incoming_tmdb or {}).get("season_episode_counts"):
                            duplicate["season_episode_counts"] = incoming_tmdb[
                                "season_episode_counts"
                            ]
                            duplicate["season_counts_checked_at"] = float(
                                incoming_tmdb.get("season_counts_checked_at") or 0
                            )
                        if (incoming_tmdb or {}).get("cover_url"):
                            duplicate["cover_url"] = incoming_tmdb["cover_url"]
                        if (incoming_tmdb or {}).get("backdrop_url"):
                            duplicate["backdrop_url"] = incoming_tmdb["backdrop_url"]
                        try:
                            _require_persistent_snapshot(
                                "watchlist", deepcopy(state.watchlist),
                            )
                        except HTTPException:
                            state.watchlist = previous_watchlist
                            raise
                    raise HTTPException(
                        409, f"Serie ist bereits als «{duplicate.get('title', body.title)}» abonniert.",
                    )
                entry = body.model_dump()
                entry["aliases"] = list(dict.fromkeys(
                    alias.strip() for alias in (body.aliases or []) if alias and alias.strip()
                ))
                entry["season_episode_counts"] = {
                    str(season): max(0, int(count))
                    for season, count in (body.season_episode_counts or {}).items()
                }
                entry["season_counts_checked_at"] = max(0.0, float(body.season_counts_checked_at or 0))
                entry["cover_url"] = (incoming_tmdb or {}).get("cover_url", "")
                entry["backdrop_url"] = (incoming_tmdb or {}).get("backdrop_url", "")
                entry["download_mode"] = normalize_watch_mode(body.download_mode)
                entry["cleanup_mode"] = normalize_cleanup_mode(
                    body.cleanup_mode
                    if body.cleanup_mode is not None
                    else state.jellyfin_cfg.get("cleanup_default")
                )
                entry["cleanup_history"] = []
                entry["cleanup_deleted_count"] = 0
                entry["cleanup_last_error"] = ""
                entry["failed_downloads"] = {}
                entry["last_error"] = ""
                entry["mode_generation"] = 0
                entry["check_generation"] = 0
                state.watchlist.append(entry)
                try:
                    _require_persistent_snapshot("watchlist", deepcopy(state.watchlist))
                except HTTPException:
                    state.watchlist = previous_watchlist
                    raise
        if entry is not None:
            log(f"«{body.title}» zur Bibliothek hinzugefügt.")
            state.taste_profile.record_event(
                "watchlist",
                source="watchlist",
                media_type="series",
                item_key=f"series:{body.tmdb_id or body.base_slug}",
                title=body.title,
                metadata={
                    "genres": (incoming_tmdb or {}).get("genres") or [],
                    "year": (incoming_tmdb or {}).get("year") or "",
                },
            )

            # Nicht erst bis zum nächsten 30-Minuten-Intervall warten: sofort prüfen
            # und bei eingeschalteter Automatik den Download anstoßen. Die Arbeit
            # läuft außerhalb des API-Requests, damit die Oberfläche direkt reagiert.
            def _initial_watchlist_check():
                try:
                    with state.watchlist_lock:
                        if entry not in state.watchlist:
                            return
                    check_watchlist_entries([entry])
                    broadcast({"type": "watchlist_update", **watchlist_payload()})
                    _auto_download_new_episodes()
                except Exception as exc:
                    log(f"Erstprüfung von «{body.title}» fehlgeschlagen: {exc}", "warn")

            threading.Thread(target=_initial_watchlist_check, daemon=True).start()
        return watchlist_payload()

    return await run_in_threadpool(_work)


class WatchlistModeBody(BaseModel):
    base_slug: str
    download_mode: str
    cleanup_mode: str | None = None


@router.post("/api/v1/watchlist/mode")
@router.post("/api/watchlist/mode")
async def api_watchlist_mode(body: WatchlistModeBody):
    if body.download_mode not in WATCH_MODE_LABELS:
        raise HTTPException(400, "Unbekannte Abo-Regel.")
    if body.cleanup_mode is not None and body.cleanup_mode not in CLEANUP_MODE_LABELS:
        raise HTTPException(400, "Unbekannte Löschregel.")
    def _mutate():
        with state.watchlist_lock:
            previous_watchlist = deepcopy(state.watchlist)
            entry = watchlist_lookup(body.base_slug)
            if entry is None:
                raise HTTPException(404, "Nicht in der Bibliothek.")
            previous_mode = normalize_watch_mode(entry.get("download_mode"))
            mode_changed = previous_mode != body.download_mode
            previous_pending = (
                set(state.watchlist_new_slugs.get(body.base_slug, set()))
                if mode_changed else set()
            )
            entry["download_mode"] = body.download_mode
            if body.cleanup_mode is not None:
                entry["cleanup_mode"] = normalize_cleanup_mode(body.cleanup_mode)
                if entry["cleanup_mode"] == CLEANUP_MODE_KEEP:
                    entry["cleanup_last_error"] = ""
            if mode_changed:
                entry["mode_generation"] = int(entry.get("mode_generation", 0)) + 1
            entry["check_generation"] = int(entry.get("check_generation", 0)) + 1
            entry["last_error"] = "Abo-Regel wird geprüft – Auto-Download pausiert"
            try:
                _require_persistent_snapshot("watchlist", deepcopy(state.watchlist))
            except HTTPException:
                state.watchlist = previous_watchlist
                raise
            return entry, previous_pending

    entry, previous_pending = await run_in_threadpool(_mutate)

    if previous_pending:
        _cancel_queue_slugs(previous_pending, "Abo-Regel geändert")

    def _mode_watchlist_check():
        try:
            check_watchlist_entries([entry])
            broadcast({"type": "watchlist_update", **watchlist_payload()})
            _auto_download_new_episodes()
            if previous_pending:
                def _reconcile_after_reap():
                    while any(
                        previous_pending & _job_queue_slugs(job)
                        for job in state.dl_queue.active_jobs()
                    ):
                        time.sleep(0.2)
                    _auto_download_new_episodes()

                threading.Thread(target=_reconcile_after_reap, daemon=True).start()
        except Exception as exc:
            log(f"Abo-Regel für «{entry['title']}» konnte nicht geprüft werden: {exc}", "warn")

    threading.Thread(target=_mode_watchlist_check, daemon=True).start()
    return watchlist_payload()


class WatchlistRemoveBody(BaseModel):
    base_slugs: list[str]


@router.post("/api/v1/watchlist/remove")
@router.post("/api/watchlist/remove")
async def api_watchlist_remove(body: WatchlistRemoveBody):
    def _work():
        pending_slugs: set[str] = set()
        with state.watchlist_lock:
            for base_slug in body.base_slugs:
                pending_slugs.update(state.watchlist_new_slugs.get(base_slug, set()))
            candidate = [
                w for w in state.watchlist if w["base_slug"] not in body.base_slugs
            ]
            _require_persistent_snapshot("watchlist", candidate)
            state.watchlist = candidate
            for base_slug in body.base_slugs:
                state.watchlist_new_slugs.pop(base_slug, None)
                state.series_cache.pop(base_slug, None)
        with state.queue_lifecycle_lock:
            removed = state.dl_queue.remove_pending(
                lambda job: bool(pending_slugs & _job_queue_slugs(job))
            )
            state.dl_queue.cancel_active(
                lambda job: bool(pending_slugs & _job_queue_slugs(job))
            )
            removed.extend(state.dl_queue.remove_pending(
                lambda job: bool(pending_slugs & _job_queue_slugs(job))
            ))
            _release_removed_queue_slugs(pending_slugs)
        for slug in pending_slugs:
            _telegram_terminal_without_job(slug, False, "Abo entfernt", Path(""))
            _seerr_terminal_without_job(slug, False, "Abo entfernt", Path(""))
        return build_queue_payload(), watchlist_payload()

    queue, payload = await run_in_threadpool(_work)
    broadcast({"type": "queue_update", "queue": queue})
    return payload


@router.get("/api/v1/watchlist")
@router.get("/api/watchlist")
async def api_watchlist_get():
    await run_in_threadpool(hydrate_watchlist_artwork)
    return watchlist_payload()


class WatchlistCheckBody(BaseModel):
    base_slugs: list[str] | None = None


def _calculate_watchlist_entry_state(
    entry: dict,
    series: FilmpalastSeries,
    jf_client: JellyfinClient,
    jf_episodes: list[dict] | None,
    jf_user_episodes: list[dict] | None,
    jf_series: list[dict] | None = None,
) -> dict:
    """Berechnet den Zustand ohne globale Watchlist-Daten zu verändern."""
    serienstream_entry = str(entry.get("base_slug") or "").startswith("serienstream:")
    previous_keys = {
        parsed[1:]
        for slug in entry.get("known_slugs", [])
        if (parsed := parse_episode_slug(slug)) is not None
        and not (serienstream_entry and parsed[1] <= 0)
    }
    current_keys = {(episode.season, episode.episode) for episode in series.all_episodes}
    vanished_keys = previous_keys - current_keys
    if vanished_keys:
        # Verschwundene Episoden sind nur dann unbedenklich, wenn TMDB
        # bestätigt, dass sie ohnehin noch nicht ausgestrahlt wurden (z.B. weil
        # ein Anbieter sie zuvor fälschlich als bereits verfügbar gelistet
        # hatte). Ohne diese Bestätigung bleibt der Schutz vor einer
        # unvollständigen Anbieterantwort bestehen.
        explained = _unreleased_episode_keys(entry.get("tmdb_id", ""), vanished_keys)
        if vanished_keys - explained:
            raise RuntimeError("Anbieterantwort unvollständig – bisher bekannte Episoden fehlen")

    downloaded = compute_downloaded_episodes(series)
    aliases = tuple(dict.fromkeys([
        entry.get("title", ""),
        *(entry.get("aliases") or []),
    ]))
    series_ids = jf_client.series_ids_for(
        series.title,
        tmdb_id=entry.get("tmdb_id", ""),
        aliases=aliases,
        items=jf_series,
    ) if jf_series is not None else set()
    if jf_client.configured and jf_series is None:
        raise RuntimeError("Jellyfin-Serienindex nicht verfügbar")
    if series_ids is None:
        raise RuntimeError("Jellyfin-Zuordnung mehrdeutig")
    jf_existing = (
        jf_client.episodes_for_series(
            series.title, items=jf_episodes, aliases=aliases, series_ids=series_ids,
        )
        if jf_episodes is not None else set()
    )
    cleanup_history = normalize_episode_history(entry.get("cleanup_history"))
    jf_existing.update(cleanup_history)
    jf_watched = (
        jf_client.watched_episodes_for_series(
            series.title, jf_user_episodes, aliases=aliases, series_ids=series_ids,
        )
        if jf_user_episodes is not None else None
    )
    if jf_watched is not None:
        jf_watched.update(cleanup_history)
    cleanup_mode = normalize_cleanup_mode(entry.get("cleanup_mode"))
    cleanup_items = []
    if cleanup_mode != CLEANUP_MODE_KEEP and jf_user_episodes is not None:
        cleanup_items = select_cleanup_items(
            jf_client.episode_items_for_series(
                series.title,
                jf_user_episodes,
                aliases=aliases,
                series_ids=series_ids,
            ),
            cleanup_mode,
            entry.get("season_episode_counts") or {},
            cleanup_history,
        )
    mode = normalize_watch_mode(entry.get("download_mode"))
    if mode == WATCH_MODE_NEXT_SEASON:
        counts_checked_at = float(entry.get("season_counts_checked_at") or 0)
        if (
            counts_checked_at <= 0
            or time.time() - counts_checked_at > SERIES_CACHE_TTL + 60
        ):
            raise RuntimeError("Staffelumfang nicht aktuell verifiziert – Auto-Download pausiert")
        expected_counts = {
            int(season): int(count)
            for season, count in (entry.get("season_episode_counts") or {}).items()
            if str(season).lstrip("-").isdigit() and str(count).isdigit()
        }
        source_seasons = sorted({episode.season for episode in series.all_episodes})
        regular_seasons = [season for season in source_seasons if season > 0]
        required_seasons = regular_seasons or source_seasons
        if any(expected_counts.get(season, 0) <= 0 for season in required_seasons):
            raise RuntimeError("Staffelumfang nicht verifizierbar – Auto-Download pausiert")
    unreleased_slugs = _unreleased_episode_slugs(series, entry.get("tmdb_id", ""))
    missing_slugs = select_missing_episode_slugs(
        series.all_episodes,
        mode,
        downloaded_slugs=downloaded,
        jellyfin_existing=jf_existing,
        jellyfin_watched=jf_watched,
        season_episode_counts=entry.get("season_episode_counts") or {},
        unreleased_slugs=unreleased_slugs,
    )
    return {
        "mode": mode,
        "cleanup_mode": cleanup_mode,
        "known_slugs": [episode.slug for episode in series.all_episodes],
        "missing_slugs": missing_slugs,
        "cleanup_items": cleanup_items,
    }


def _apply_watchlist_entry_state(entry: dict, calculated: dict) -> set[str]:
    """Übernimmt ein Ergebnis und meldet nicht mehr benötigte Queue-Slugs."""
    entry["download_mode"] = calculated["mode"]
    entry["cleanup_mode"] = calculated["cleanup_mode"]
    entry["known_slugs"] = calculated["known_slugs"]
    previous_slugs = set(state.watchlist_new_slugs.get(entry["base_slug"], set()))
    missing_slugs = set(calculated["missing_slugs"])
    if missing_slugs:
        state.watchlist_new_slugs[entry["base_slug"]] = missing_slugs
    else:
        state.watchlist_new_slugs.pop(entry["base_slug"], None)
    failed = entry.get("failed_downloads")
    if not isinstance(failed, dict):
        failed = {}
    entry["failed_downloads"] = {
        slug: failure for slug, failure in failed.items() if slug in missing_slugs
    }
    entry["last_checked"] = time.time()
    entry["last_error"] = ""
    return previous_slugs - missing_slugs


def _update_watchlist_entry_state(
    entry: dict,
    series: FilmpalastSeries,
    jf_client: JellyfinClient,
    jf_episodes: list[dict] | None,
    jf_user_episodes: list[dict] | None,
    jf_series: list[dict] | None = None,
) -> set[str]:
    calculated = _calculate_watchlist_entry_state(
        entry, series, jf_client, jf_episodes, jf_user_episodes, jf_series,
    )
    return _apply_watchlist_entry_state(entry, calculated)


def _execute_watchlist_cleanup(
    jobs: list[dict], jf_client: JellyfinClient, jellyfin_generation: int,
) -> int:
    """Löscht freigegebene Jellyfin-Episoden und merkt ihren Abo-Fortschritt.

    Die Historie verhindert, dass absichtlich gelöschte Folgen beim nächsten
    Abo-Lauf wieder als fehlend erkannt werden. Vor jedem externen DELETE wird
    geprüft, ob die Löschregel noch unverändert aktiv ist.
    """
    deleted_total = 0
    deleted_ids: set[str] = set()
    changed = False
    for job in jobs:
        entry = job["entry"]
        revision = int(job["revision"])
        cleanup_mode = normalize_cleanup_mode(job["cleanup_mode"])
        successful_pairs: set[tuple[int, int]] = set()
        failed = 0
        seen_ids: set[str] = set()

        for item in job.get("items") or []:
            item_id = str(item.get("id") or "").strip()
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            with state.jellyfin_cache_lock:
                config_is_current = jellyfin_generation == state.jellyfin_config_generation
                with state.watchlist_lock:
                    rule_is_current = bool(
                        any(current is entry for current in state.watchlist)
                        and int(entry.get("check_generation", 0)) == revision
                        and normalize_cleanup_mode(entry.get("cleanup_mode")) == cleanup_mode
                        and cleanup_mode != CLEANUP_MODE_KEEP
                    )
            if not config_is_current or not rule_is_current:
                break
            if jf_client.delete_item(item_id):
                successful_pairs.add((int(item["season"]), int(item["episode"])))
                deleted_ids.add(item_id)
                deleted_total += 1
            else:
                failed += 1

        with state.watchlist_lock:
            if not any(current is entry for current in state.watchlist):
                continue
            if successful_pairs:
                history = normalize_episode_history(entry.get("cleanup_history"))
                history.update(successful_pairs)
                entry["cleanup_history"] = serialize_episode_history(history)
                entry["cleanup_deleted_count"] = int(entry.get("cleanup_deleted_count", 0)) + len(
                    successful_pairs
                )
                changed = True
            if (
                int(entry.get("check_generation", 0)) == revision
                and normalize_cleanup_mode(entry.get("cleanup_mode")) == cleanup_mode
            ):
                entry["cleanup_last_run"] = time.time()
                entry["cleanup_last_error"] = (
                    f"{failed} Jellyfin-Element(e) konnten nicht gelöscht werden"
                    if failed else ""
                )
                changed = True

    if changed:
        with state.watchlist_lock:
            _persist_watchlist_background()
    if deleted_ids:
        with state.jellyfin_cache_lock:
            if state.jellyfin_episodes is not None:
                state.jellyfin_episodes = [
                    item for item in state.jellyfin_episodes
                    if str(item.get("id") or "") not in deleted_ids
                ]
            if state.jellyfin_user_episodes is not None:
                state.jellyfin_user_episodes = [
                    item for item in state.jellyfin_user_episodes
                    if str(item.get("id") or "") not in deleted_ids
                ]
            state.jellyfin_episodes_time = 0.0
            state.jellyfin_user_episodes_time = 0.0
            state.jellyfin_targeted_episodes.clear()
            state.jellyfin_episode_data_generation += 1
        log(f"Jellyfin-Aufräumen: {deleted_total} gesehene Episode(n) gelöscht.")
    return deleted_total


def check_watchlist_entries(entries: list[dict], refresh_jellyfin: bool = False) -> int:
    """Prüft die übergebenen Watchlist-Einträge auf fehlende Episoden und
    aktualisiert state.watchlist_new_slugs. Gibt die Anzahl erfolgreich
    geprüfter Einträge zurück. Wird sowohl vom manuellen Check-Endpoint
    als auch vom automatischen Hintergrund-Check genutzt.

    Welche fehlenden Episoden berücksichtigt werden, bestimmt die pro Serie
    gespeicherte Abo-Regel. Jellyfin und lokale Videodateien werden immer als
    bereits vorhanden behandelt."""
    with state.watchlist_lock:
        tracked = []
        for entry in entries:
            if not any(current is entry for current in state.watchlist):
                continue
            entry["check_generation"] = int(entry.get("check_generation", 0)) + 1
            entry["last_error"] = "Prüfung läuft – Auto-Download pausiert"
            tracked.append((entry, entry["check_generation"]))
    if not tracked:
        return 0

    with state.jellyfin_cache_lock:
        jellyfin_generation = state.jellyfin_config_generation
        cfg = dict(state.jellyfin_cfg)
    jf_client = JellyfinClient(cfg.get("url", ""), cfg.get("api_key", ""))
    jf_episodes = get_jellyfin_episodes(force=refresh_jellyfin) if jf_client.configured else None
    jf_series = get_jellyfin_series(force=refresh_jellyfin) if jf_client.configured else None
    with state.jellyfin_cache_lock:
        if jellyfin_generation != state.jellyfin_config_generation:
            return 0
        episodes_available = state.jellyfin_episodes_available
        series_available = state.jellyfin_series_available
        jellyfin_data_generation = state.jellyfin_episode_data_generation

    def _set_error(entry: dict, revision: int, message: str) -> bool:
        with state.jellyfin_cache_lock:
            if (
                jellyfin_generation != state.jellyfin_config_generation
                or jellyfin_data_generation != state.jellyfin_episode_data_generation
            ):
                return False
            with state.watchlist_lock:
                if (
                    not any(current is entry for current in state.watchlist)
                    or int(entry.get("check_generation", 0)) != revision
                ):
                    return False
                entry["last_checked"] = time.time()
                entry["last_error"] = message[:240]
                return True

    if jf_client.configured and (jf_episodes is None or not episodes_available):
        for entry, revision in tracked:
            _set_error(entry, revision, "Jellyfin nicht erreichbar – Auto-Download pausiert")
        with state.watchlist_lock:
            _persist_watchlist_background()
        log("Watchlist-Prüfung pausiert: Jellyfin ist nicht erreichbar.", "warn")
        return 0
    if jf_client.configured and (jf_series is None or not series_available):
        for entry, revision in tracked:
            _set_error(entry, revision, "Jellyfin-Serienindex nicht verfügbar")
        with state.watchlist_lock:
            _persist_watchlist_background()
        log("Watchlist-Prüfung pausiert: Jellyfin-Serienindex nicht verfügbar.", "warn")
        return 0

    needs_watched_status = any(
        normalize_watch_mode(entry.get("download_mode")) == WATCH_MODE_NEXT_SEASON
        or normalize_cleanup_mode(entry.get("cleanup_mode")) != CLEANUP_MODE_KEEP
        for entry, _revision in tracked
    )
    jf_user_episodes = get_jellyfin_user_episodes(force=refresh_jellyfin) if needs_watched_status else None
    with state.jellyfin_cache_lock:
        if jellyfin_generation != state.jellyfin_config_generation:
            return 0
        user_available = state.jellyfin_user_episodes_available
        jellyfin_data_generation = state.jellyfin_episode_data_generation

    checked = 0
    withdrawn_slugs: set[str] = set()
    cleanup_jobs: list[dict] = []
    for entry, revision in tracked:
        with state.jellyfin_cache_lock:
            if (
                jellyfin_generation != state.jellyfin_config_generation
                or jellyfin_data_generation != state.jellyfin_episode_data_generation
            ):
                break
            with state.watchlist_lock:
                if (
                    not any(current is entry for current in state.watchlist)
                    or int(entry.get("check_generation", 0)) != revision
                ):
                    continue
                entry_snapshot = dict(entry)
        mode = normalize_watch_mode(entry_snapshot.get("download_mode"))
        cleanup_mode = normalize_cleanup_mode(entry_snapshot.get("cleanup_mode"))
        cleanup_status_missing = bool(
            cleanup_mode != CLEANUP_MODE_KEEP
            and (jf_user_episodes is None or not user_available)
        )
        if mode == WATCH_MODE_NEXT_SEASON and (jf_user_episodes is None or not user_available):
            _set_error(entry, revision, "Jellyfin-Benutzerstatus nicht verfügbar")
            continue
        try:
            series = get_series_for_value(entry_snapshot["sample_url"])
            if series is None:
                _set_error(entry, revision, "Serie beim Anbieter nicht abrufbar")
                log(f"«{entry_snapshot['title']}»: konnte nicht geprüft werden.", "warn")
                continue
            tmdb = get_tmdb_series(
                series.title, entry_snapshot.get("tmdb_id", ""),
            )
            if tmdb:
                if not entry_snapshot.get("tmdb_id"):
                    entry_snapshot["tmdb_id"] = tmdb.get("tmdb_id")
                entry_snapshot["aliases"] = list(dict.fromkeys(filter(None, (
                    entry_snapshot.get("title", ""),
                    series.title,
                    tmdb.get("title", ""),
                    tmdb.get("original_title", ""),
                ))))
                entry_snapshot["season_episode_counts"] = tmdb.get("season_episode_counts") or {}
                entry_snapshot["season_counts_checked_at"] = float(
                    tmdb.get("season_counts_checked_at") or 0
                )
                entry_snapshot["cover_url"] = tmdb.get("cover_url") or series.cover_url
                entry_snapshot["backdrop_url"] = tmdb.get("backdrop_url") or ""
            elif series.cover_url:
                entry_snapshot["cover_url"] = series.cover_url
            calculated = _calculate_watchlist_entry_state(
                entry_snapshot, series, jf_client, jf_episodes, jf_user_episodes, jf_series,
            )
            with state.jellyfin_cache_lock:
                if (
                    jellyfin_generation != state.jellyfin_config_generation
                    or jellyfin_data_generation != state.jellyfin_episode_data_generation
                ):
                    break
                with state.watchlist_lock:
                    if (
                        not any(current is entry for current in state.watchlist)
                        or int(entry.get("check_generation", 0)) != revision
                    ):
                        continue
                    if entry_snapshot.get("tmdb_id"):
                        entry["tmdb_id"] = entry_snapshot["tmdb_id"]
                        entry["aliases"] = entry_snapshot.get("aliases", [])
                        entry["season_episode_counts"] = entry_snapshot.get("season_episode_counts", {})
                        entry["season_counts_checked_at"] = entry_snapshot.get(
                            "season_counts_checked_at", 0,
                        )
                    entry["cover_url"] = entry_snapshot.get("cover_url", "")
                    entry["backdrop_url"] = entry_snapshot.get("backdrop_url", "")
                    entry["cleanup_mode"] = cleanup_mode
                    entry["cleanup_last_error"] = (
                        "Jellyfin-Benutzerstatus nicht verfügbar"
                        if cleanup_status_missing else ""
                    )
                    state.series_cache[entry["base_slug"]] = series
                    withdrawn_slugs.update(
                        _apply_watchlist_entry_state(entry, calculated)
                    )
                    if not cleanup_status_missing and calculated.get("cleanup_items"):
                        cleanup_jobs.append({
                            "entry": entry,
                            "revision": revision,
                            "cleanup_mode": cleanup_mode,
                            "items": calculated["cleanup_items"],
                        })
                    checked += 1
        except Exception as exc:
            _set_error(entry, revision, str(exc))
            log(f"Fehler beim Prüfen von «{entry_snapshot.get('title', '')}»: {exc}", "warn")
    with state.jellyfin_cache_lock:
        data_is_current = (
            jellyfin_generation == state.jellyfin_config_generation
            and jellyfin_data_generation == state.jellyfin_episode_data_generation
        )
        if data_is_current:
            with state.watchlist_lock:
                _persist_watchlist_background()
    if data_is_current and withdrawn_slugs:
        _cancel_withdrawn_watchlist_slugs(
            withdrawn_slugs,
            "In Jellyfin vorhanden oder nicht mehr Teil der Abo-Regel",
        )
    if data_is_current and cleanup_jobs:
        _execute_watchlist_cleanup(cleanup_jobs, jf_client, jellyfin_generation)
    return checked


@router.post("/api/v1/watchlist/check")
@router.post("/api/watchlist/check")
async def api_watchlist_check(body: WatchlistCheckBody):
    def _work():
        with state.watchlist_lock:
            entries = list(state.watchlist) if not body.base_slugs else [
                w for w in state.watchlist if w["base_slug"] in body.base_slugs
            ]
        checked = check_watchlist_entries(entries, refresh_jellyfin=True)
        return checked, len(entries)

    checked, total = await run_in_threadpool(_work)
    payload = watchlist_payload()
    payload["checked"] = checked
    payload["total"] = total
    broadcast({"type": "watchlist_update", **payload})
    return payload


class WatchlistOpenBody(BaseModel):
    base_slug: str


@router.post("/api/v1/watchlist/open")
@router.post("/api/watchlist/open")
async def api_watchlist_open(body: WatchlistOpenBody):
    with state.watchlist_lock:
        entry = watchlist_lookup(body.base_slug)
        if not entry:
            raise HTTPException(404, "Nicht in der Bibliothek.")
        entry["check_generation"] = int(entry.get("check_generation", 0)) + 1
        entry["last_error"] = "Prüfung läuft – Auto-Download pausiert"
        open_revision = entry["check_generation"]

    def _work():
        series = state.series_cache.get(body.base_slug)
        if series is None:
            try:
                series = get_series_for_value(entry["sample_url"])
            except Exception as exc:
                log(f"Fehler beim Laden von «{entry['title']}»: {exc}", "warn")
                series = None
        return series

    series = await run_in_threadpool(_work)
    if series is None:
        raise HTTPException(500, "Serie konnte nicht geladen werden.")

    with state.watchlist_lock:
        if not any(current is entry for current in state.watchlist):
            raise HTTPException(404, "Nicht mehr in der Bibliothek.")
        state.series_cache[body.base_slug] = series

    payload = await run_in_threadpool(series_to_dict, series, True)
    with state.watchlist_lock:
        if (
            any(current is entry for current in state.watchlist)
            and int(entry.get("check_generation", 0)) == open_revision
        ):
            if payload.get("tmdb_id"):
                entry["tmdb_id"] = payload["tmdb_id"]
            if payload.get("aliases"):
                entry["aliases"] = payload["aliases"]
            if payload.get("season_episode_counts"):
                entry["season_episode_counts"] = payload["season_episode_counts"]
                entry["season_counts_checked_at"] = float(
                    payload.get("season_counts_checked_at") or 0
                )
            if payload.get("cover_url"):
                entry["cover_url"] = payload["cover_url"]
            if payload.get("backdrop_url"):
                entry["backdrop_url"] = payload["backdrop_url"]

    def _sync_entry_from_loaded_series():
        withdrawn_slugs: set[str] = set()
        cleanup_jobs: list[dict] = []
        with state.jellyfin_cache_lock:
            jellyfin_generation = state.jellyfin_config_generation
        jf_client = get_jellyfin_client()
        jf_episodes = get_jellyfin_episodes() if jf_client.configured else None
        jf_series = get_jellyfin_series() if jf_client.configured else None
        with state.watchlist_lock:
            if (
                not any(current is entry for current in state.watchlist)
                or int(entry.get("check_generation", 0)) != open_revision
            ):
                return
            snapshot = dict(entry)
        mode = normalize_watch_mode(snapshot.get("download_mode"))
        cleanup_mode = normalize_cleanup_mode(snapshot.get("cleanup_mode"))
        needs_user_status = (
            mode == WATCH_MODE_NEXT_SEASON or cleanup_mode != CLEANUP_MODE_KEEP
        )
        user_episodes = get_jellyfin_user_episodes() if needs_user_status else None
        with state.jellyfin_cache_lock:
            jellyfin_data_generation = state.jellyfin_episode_data_generation
            episodes_available = state.jellyfin_episodes_available
            series_available = state.jellyfin_series_available
            user_available = state.jellyfin_user_episodes_available
        if jf_client.configured and (jf_episodes is None or not episodes_available):
            error = "Jellyfin nicht erreichbar – Auto-Download pausiert"
            calculated = None
        elif jf_client.configured and (
            jf_series is None or not series_available
        ):
            error = "Jellyfin-Serienindex nicht verfügbar"
            calculated = None
        else:
            if mode == WATCH_MODE_NEXT_SEASON and (
                user_episodes is None or not user_available
            ):
                error = "Jellyfin-Benutzerstatus nicht verfügbar"
                calculated = None
            else:
                try:
                    calculated = _calculate_watchlist_entry_state(
                        snapshot, series, jf_client, jf_episodes, user_episodes,
                        jf_series,
                    )
                    error = ""
                except Exception as exc:
                    calculated = None
                    error = str(exc)[:240]
        with state.jellyfin_cache_lock:
            if (
                jellyfin_generation != state.jellyfin_config_generation
                or jellyfin_data_generation != state.jellyfin_episode_data_generation
            ):
                return
            with state.watchlist_lock:
                if (
                    not any(current is entry for current in state.watchlist)
                    or int(entry.get("check_generation", 0)) != open_revision
                    or normalize_watch_mode(entry.get("download_mode")) != mode
                ):
                    return
                if error:
                    entry["last_checked"] = time.time()
                    entry["last_error"] = error
                elif calculated is not None:
                    withdrawn_slugs.update(
                        _apply_watchlist_entry_state(entry, calculated)
                    )
                    entry["cleanup_last_error"] = (
                        "Jellyfin-Benutzerstatus nicht verfügbar"
                        if cleanup_mode != CLEANUP_MODE_KEEP
                        and (user_episodes is None or not user_available)
                        else ""
                    )
                    if not entry["cleanup_last_error"] and calculated.get("cleanup_items"):
                        cleanup_jobs.append({
                            "entry": entry,
                            "revision": open_revision,
                            "cleanup_mode": cleanup_mode,
                            "items": calculated["cleanup_items"],
                        })
                _persist_watchlist_background()
        if withdrawn_slugs:
            _cancel_withdrawn_watchlist_slugs(
                withdrawn_slugs,
                "In Jellyfin vorhanden oder nicht mehr Teil der Abo-Regel",
            )
        if cleanup_jobs:
            _execute_watchlist_cleanup(cleanup_jobs, jf_client, jellyfin_generation)

    await run_in_threadpool(_sync_entry_from_loaded_series)
    with state.watchlist_lock:
        new_slugs = set(state.watchlist_new_slugs.get(body.base_slug, set()))
    known_now = {episode.slug for episode in series.all_episodes}
    preselect = sorted(new_slugs & known_now)
    payload["preselect_slugs"] = preselect
    return payload
