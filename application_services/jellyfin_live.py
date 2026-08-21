"""Near-live Jellyfin ownership snapshots without request-path full scans.

A tiny one-page Jellyfin probe runs in the background. Only when the library
fingerprint changes do we rebuild the heavier movie/series/episode snapshots.
Interactive callers keep using the last verified snapshot immediately while a
single coalesced refresh runs in the background.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from application_services.runtime import backend_value, publish_service

logger = logging.getLogger(__name__)
state = backend_value("state")

# Preserve the established implementations before publishing live wrappers.
_legacy_get_jellyfin_library = backend_value("get_jellyfin_library")
_legacy_get_jellyfin_movie_identities = backend_value("get_jellyfin_movie_identities")
_legacy_get_jellyfin_episodes = backend_value("get_jellyfin_episodes")
_legacy_get_jellyfin_series = backend_value("get_jellyfin_series")
_legacy_get_jellyfin_targeted_episodes = backend_value("get_jellyfin_targeted_episodes")
_legacy_get_jellyfin_user_episodes = backend_value("get_jellyfin_user_episodes")
_legacy_set_runtime_jellyfin_config = backend_value("_set_runtime_jellyfin_config")
_legacy_stop_jellyfin_recommender = backend_value("stop_jellyfin_recommender")
_legacy_content_already_available = backend_value("_content_already_available")

_LIVE_PROBE_LIMIT = 12
_LIVE_MIN_INTERVAL_SECONDS = 0.5
_LIVE_DEFAULT_INTERVAL_SECONDS = 1.0
_LIVE_MAX_INTERVAL_SECONDS = 30.0
_LIVE_MAX_FAILURE_BACKOFF_SECONDS = 15.0

_live_lock = threading.RLock()
_live_wake_event = threading.Event()
_live_stop_event = threading.Event()
_live_thread: threading.Thread | None = None
_force_full_refresh = False
_last_revision = ""
_failure_count = 0


def _poll_interval_seconds() -> float:
    raw = os.environ.get("JELLYFIN_LIVE_POLL_SECONDS", str(_LIVE_DEFAULT_INTERVAL_SECONDS))
    try:
        interval = float(raw)
    except (TypeError, ValueError):
        interval = _LIVE_DEFAULT_INTERVAL_SECONDS
    return max(_LIVE_MIN_INTERVAL_SECONDS, min(_LIVE_MAX_INTERVAL_SECONDS, interval))


def _live_stale() -> bool:
    with state.jellyfin_cache_lock:
        return bool(getattr(state, "jellyfin_live_stale", False))


def _set_live_state(*, stale: bool, checked_at: float | None = None) -> None:
    with state.jellyfin_cache_lock:
        state.jellyfin_live_stale = bool(stale)
        if checked_at is not None:
            state.jellyfin_live_checked_at = float(checked_at)


def _wake_automation() -> None:
    try:
        backend_value("wake_watchlist_auto_check")()
    except Exception as exc:
        logger.warning("Jellyfin-Liveupdate konnte Automatik nicht wecken: %s", exc)


def _mark_probe_unavailable() -> None:
    """Keep visual snapshots but fail closed for download/automation safety."""
    with state.jellyfin_cache_lock:
        state.jellyfin_live_stale = True
        # Identity snapshots stay readable so catalog badges do not flicker.
        # Heavy safety caches become unavailable, so old ownership data cannot
        # be interpreted as proof that a title or episode is missing.
        if state.jellyfin_library is not None:
            state.jellyfin_library_available = False
        if state.jellyfin_episodes is not None:
            state.jellyfin_episodes_available = False
        if state.jellyfin_user_episodes is not None:
            state.jellyfin_user_episodes_available = False


def _mark_cached_snapshots_verified(now: float) -> None:
    """A successful unchanged probe proves cached ownership is still current."""
    with state.jellyfin_cache_lock:
        if state.jellyfin_library is not None:
            state.jellyfin_library_available = True
            state.jellyfin_library_time = now
            state.jellyfin_library_retry_after = 0.0
        if state.jellyfin_movie_identities is not None:
            state.jellyfin_movie_identities_available = True
            state.jellyfin_movie_identities_time = now
            state.jellyfin_movie_identities_retry_after = 0.0
        if state.jellyfin_episodes is not None:
            state.jellyfin_episodes_available = True
            state.jellyfin_episodes_time = now
            state.jellyfin_episodes_retry_after = 0.0
        if state.jellyfin_series is not None:
            state.jellyfin_series_available = True
            state.jellyfin_series_time = now
            state.jellyfin_series_retry_after = 0.0
        if state.jellyfin_user_episodes is not None:
            state.jellyfin_user_episodes_available = True
            state.jellyfin_user_episodes_time = now
            state.jellyfin_user_episodes_retry_after = 0.0
        state.jellyfin_live_stale = False
        state.jellyfin_live_checked_at = now


def _movie_identities_from_library(items: list[dict]) -> list[dict]:
    return [{
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "original_title": str(item.get("original_title") or ""),
        "sort_name": str(item.get("sort_name") or ""),
        "year": item.get("year"),
        "tmdb_id": str(item.get("tmdb_id") or ""),
    } for item in items]


def _probe_library_revision(client) -> str | None:
    """Fetch one tiny page whose count/recent IDs fingerprint library membership."""
    if not client.configured:
        return "unconfigured"
    params = {
        "IncludeItemTypes": "Movie,Series,Episode",
        "Recursive": "true",
        "ExcludeLocationTypes": "Virtual,Offline",
        "IsMissing": "false",
        "IsPlaceHolder": "false",
        "Fields": "DateCreated",
        "SortBy": "DateCreated",
        "SortOrder": "Descending",
        "StartIndex": "0",
        "Limit": str(_LIVE_PROBE_LIMIT),
        "EnableTotalRecordCount": "true",
    }
    try:
        response = requests.get(
            f"{client.base_url}/Items",
            params=params,
            headers={"X-Emby-Token": client.api_key},
            timeout=client.timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Jellyfin-Liveprobe fehlgeschlagen (%s): %s", client.base_url, exc)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("Items", []), list):
        return None
    recent = [
        (
            str(item.get("Id") or ""),
            str(item.get("Type") or ""),
            str(item.get("DateCreated") or ""),
        )
        for item in payload.get("Items", [])[:_LIVE_PROBE_LIMIT]
        if isinstance(item, dict)
    ]
    material = json.dumps(
        {"count": payload.get("TotalRecordCount"), "recent": recent},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _refresh_snapshot(client) -> bool:
    """Rebuild ownership data in parallel and publish one coherent generation."""
    with state.jellyfin_cache_lock:
        generation = state.jellyfin_config_generation
        user_id = str(state.jellyfin_cfg.get("user_id") or "").strip()

    loaders = {
        "movies": client.list_movies,
        "series": client.list_series,
        "episodes": client.list_episodes,
    }
    if user_id:
        loaders["user_episodes"] = lambda: client.list_episodes_with_user_data(user_id)

    results: dict[str, list[dict] | None] = {}
    with ThreadPoolExecutor(max_workers=len(loaders), thread_name_prefix="jellyfin-live-snapshot") as pool:
        futures = {name: pool.submit(loader) for name, loader in loaders.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:
                logger.warning("Jellyfin-Livesnapshot %s fehlgeschlagen: %s", name, exc)
                results[name] = None

    now = time.time()
    with state.jellyfin_cache_lock:
        if generation != state.jellyfin_config_generation:
            return False

        movies = results.get("movies")
        series = results.get("series")
        episodes = results.get("episodes")
        user_episodes = results.get("user_episodes") if user_id else []

        if movies is not None:
            state.jellyfin_movie_data_generation += 1
            state.jellyfin_library = movies
            state.jellyfin_library_time = now
            state.jellyfin_library_available = True
            state.jellyfin_library_retry_after = 0.0
            state.jellyfin_movie_identities = _movie_identities_from_library(movies)
            state.jellyfin_movie_identities_time = now
            state.jellyfin_movie_identities_available = True
            state.jellyfin_movie_identities_retry_after = 0.0
        else:
            state.jellyfin_library_available = False
            if state.jellyfin_movie_identities is None:
                state.jellyfin_movie_identities_available = False

        if series is not None:
            state.jellyfin_series = series
            state.jellyfin_series_time = now
            state.jellyfin_series_available = True
            state.jellyfin_series_retry_after = 0.0
        elif state.jellyfin_series is None:
            state.jellyfin_series_available = False

        if episodes is not None:
            state.jellyfin_episode_data_generation += 1
            state.jellyfin_episodes = episodes
            state.jellyfin_episodes_time = now
            state.jellyfin_episodes_available = True
            state.jellyfin_episodes_retry_after = 0.0
            state.jellyfin_targeted_episodes.clear()
        else:
            state.jellyfin_episodes_available = False

        if user_id:
            if user_episodes is not None:
                state.jellyfin_user_episodes = user_episodes
                state.jellyfin_user_episodes_time = now
                state.jellyfin_user_episodes_available = True
                state.jellyfin_user_episodes_retry_after = 0.0
            else:
                state.jellyfin_user_episodes_available = False
        else:
            state.jellyfin_user_episodes = None
            state.jellyfin_user_episodes_time = 0.0
            state.jellyfin_user_episodes_available = False
            state.jellyfin_user_episodes_retry_after = 0.0

        complete = movies is not None and series is not None and episodes is not None
        if user_id:
            complete = complete and user_episodes is not None
        state.jellyfin_live_stale = not complete
        state.jellyfin_live_checked_at = now
    return complete


def _broadcast_live_update() -> None:
    try:
        backend_value("broadcast")({
            "type": "jellyfin_update",
            **backend_value("watchlist_payload")(),
        })
    except Exception as exc:
        logger.warning("Jellyfin-Liveupdate konnte nicht verteilt werden: %s", exc)


def _monitor_cycle(*, force_full: bool = False) -> str:
    global _last_revision, _failure_count
    client = backend_value("get_jellyfin_client")()
    if not client.configured:
        _last_revision = ""
        _failure_count = 0
        _set_live_state(stale=False, checked_at=time.time())
        return "unconfigured"

    revision = _probe_library_revision(client)
    if revision is None:
        _failure_count += 1
        _mark_probe_unavailable()
        return "unavailable"

    previous_stale = _live_stale()
    changed = bool(_last_revision and revision != _last_revision)
    if force_full or not _last_revision or changed:
        complete = _refresh_snapshot(client)
        if complete:
            _last_revision = revision
            _failure_count = 0
            _wake_automation()
        else:
            _failure_count += 1
        _broadcast_live_update()
        return "changed" if changed else ("refreshed" if complete else "stale")

    _failure_count = 0
    _mark_cached_snapshots_verified(time.time())
    if previous_stale:
        _broadcast_live_update()
        _wake_automation()
        return "recovered"
    return "unchanged"


def request_jellyfin_live_refresh(*, force_full: bool = False) -> None:
    global _force_full_refresh
    with _live_lock:
        _force_full_refresh = _force_full_refresh or bool(force_full)
    _ensure_live_monitor()
    _live_wake_event.set()


def _consume_force_refresh() -> bool:
    global _force_full_refresh
    with _live_lock:
        forced = _force_full_refresh
        _force_full_refresh = False
        return forced


def _monitor_loop() -> None:
    while not _live_stop_event.is_set():
        try:
            _monitor_cycle(force_full=_consume_force_refresh())
        except Exception:
            logger.exception("Unerwarteter Fehler im Jellyfin-Livemonitor")
        if _live_stop_event.is_set():
            return
        if _failure_count:
            interval = min(
                _LIVE_MAX_FAILURE_BACKOFF_SECONDS,
                _poll_interval_seconds() * (2 ** min(_failure_count, 4)),
            )
        else:
            interval = _poll_interval_seconds()
        _live_wake_event.wait(interval)
        _live_wake_event.clear()


def _ensure_live_monitor() -> None:
    global _live_thread
    with _live_lock:
        if _live_thread is not None and _live_thread.is_alive():
            return
        _live_stop_event.clear()
        _live_wake_event.clear()
        _live_thread = threading.Thread(
            target=_monitor_loop,
            name="jellyfin-live-monitor",
            daemon=True,
        )
        _live_thread.start()


def _cached_snapshot(value_attr: str, force: bool, legacy):
    client = backend_value("get_jellyfin_client")()
    if not client.configured:
        return None
    if force:
        value = legacy(force=True)
        request_jellyfin_live_refresh()
        return value
    with state.jellyfin_cache_lock:
        value = getattr(state, value_attr)
        checked_at = float(getattr(state, "jellyfin_live_checked_at", 0.0) or 0.0)
        stale = bool(getattr(state, "jellyfin_live_stale", False))
    if value is None:
        request_jellyfin_live_refresh(force_full=True)
    elif stale or time.time() - checked_at > max(2.0, _poll_interval_seconds() * 2.5):
        request_jellyfin_live_refresh()
    return value


def get_jellyfin_library(force: bool = False):
    return _cached_snapshot("jellyfin_library", force, _legacy_get_jellyfin_library)


def get_jellyfin_movie_identities(force: bool = False):
    return _cached_snapshot(
        "jellyfin_movie_identities", force, _legacy_get_jellyfin_movie_identities,
    )


def get_jellyfin_episodes(force: bool = False):
    return _cached_snapshot("jellyfin_episodes", force, _legacy_get_jellyfin_episodes)


def get_jellyfin_series(force: bool = False):
    return _cached_snapshot("jellyfin_series", force, _legacy_get_jellyfin_series)


def get_jellyfin_user_episodes(force: bool = False):
    return _cached_snapshot(
        "jellyfin_user_episodes", force, _legacy_get_jellyfin_user_episodes,
    )


def get_jellyfin_targeted_episodes(series_ids: set[str], force: bool = False):
    wanted = {str(value).strip() for value in series_ids if str(value).strip()}
    if not wanted:
        return [], True, False, time.time()
    with state.jellyfin_cache_lock:
        episodes = state.jellyfin_episodes
        available = bool(state.jellyfin_episodes_available)
        checked_at = float(state.jellyfin_episodes_time or 0.0)
        stale = bool(getattr(state, "jellyfin_live_stale", False))

    # Preserve the old targeted first-load path until the shared snapshot exists.
    # This is both backwards compatible and avoids a misleading unavailable state
    # during the few moments before background warm-up completes.
    if episodes is None:
        result = _legacy_get_jellyfin_targeted_episodes(wanted, force=force)
        request_jellyfin_live_refresh(force_full=True)
        return result
    if force:
        if available and not stale:
            return (
                [item for item in episodes if str(item.get("series_id") or "") in wanted],
                True,
                False,
                checked_at,
            )
        result = _legacy_get_jellyfin_targeted_episodes(wanted, force=True)
        request_jellyfin_live_refresh(force_full=True)
        return result

    targeted = [
        item for item in episodes
        if str(item.get("series_id") or "") in wanted
    ]
    if stale:
        request_jellyfin_live_refresh()
    return targeted, available and not stale, stale, checked_at


def _set_runtime_jellyfin_config(cfg: dict) -> None:
    global _last_revision
    _legacy_set_runtime_jellyfin_config(cfg)
    with _live_lock:
        _last_revision = ""
    configured = backend_value("get_jellyfin_client")().configured
    _set_live_state(stale=configured, checked_at=0.0)
    _broadcast_live_update()
    request_jellyfin_live_refresh(force_full=True)


def _content_already_available(movie, slug: str):
    """Keep download safety fail-closed while visual surfaces may show stale data."""
    result = _legacy_content_already_available(movie, slug)
    if result[0]:
        return result
    if backend_value("get_jellyfin_client")().configured and _live_stale():
        return True, "Jellyfin-Livestatus veraltet – Sicherheitsprüfung läuft"
    return result


def warm_jellyfin_identity_cache() -> None:
    """Prime all ownership caches off the request path, then keep them live."""
    if backend_value("get_jellyfin_client")().configured:
        try:
            _monitor_cycle(force_full=True)
        except Exception:
            logger.exception("Jellyfin-Livesnapshot konnte beim Start nicht vorbereitet werden")
    _ensure_live_monitor()


def stop_jellyfin_recommender() -> None:
    global _live_thread
    _live_stop_event.set()
    _live_wake_event.set()
    thread = _live_thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=5)
    _live_thread = None
    _legacy_stop_jellyfin_recommender()


_SERVICE_EXPORTS = (
    "request_jellyfin_live_refresh",
    "get_jellyfin_library",
    "get_jellyfin_movie_identities",
    "get_jellyfin_episodes",
    "get_jellyfin_series",
    "get_jellyfin_targeted_episodes",
    "get_jellyfin_user_episodes",
    "_set_runtime_jellyfin_config",
    "_content_already_available",
    "warm_jellyfin_identity_cache",
    "stop_jellyfin_recommender",
)
publish_service(globals(), _SERVICE_EXPORTS)
