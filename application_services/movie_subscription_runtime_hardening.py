"""Runtime hardening for subscription scheduling and public payloads."""

from __future__ import annotations

import threading
import time

import api_library_router as library_router
import application_services.movie_subscription_quality as quality_service
from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())

# ruff: noqa: F821

_ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS = backend_value("check_movie_subscriptions")
_ORIGINAL_MOVIE_SUBSCRIPTIONS_PAYLOAD = backend_value("movie_subscriptions_payload")
_ORIGINAL_WATCHLIST_CHECK_ONCE = backend_value("_watchlist_auto_check_once")
_ORIGINAL_WATCHLIST_CHECK_DELAY = backend_value("_watchlist_auto_check_delay")
_BACKEND_GET_JELLYFIN_LIBRARY = backend_value("get_jellyfin_library")

_check_gate = threading.RLock()
_check_runner_active = False
_pending_keys: set[str] = set()
_pending_all = False
_movie_loop_lock = threading.RLock()
_movie_loop_started = False

_INTERNAL_SUBSCRIPTION_FIELDS = {
    "quality_probe_cache",
    "upgrade_probe_baseline_profile",
    "upgrade_available_profile",
    "_upgrade_candidate_signature",
    "_upgrade_candidate_from_rank",
    "_upgrade_candidate_advertised_rank",
    "_upgrade_delivery_fingerprint",
    "upgrade_last_delivered_fingerprint",
    "upgrade_last_delivered_profile",
    "upgrade_last_delivered_at",
}


def _entry_key(entry: dict) -> str:
    return str(entry.get("key") or entry.get("source_slug") or "").strip()


def _entries_for_keys(keys: set[str]) -> list[dict]:
    with state.movie_subscriptions_lock:
        if not keys:
            return []
        return [
            entry
            for entry in state.movie_subscriptions
            if _entry_key(entry) in keys
        ]


def _queue_followup(entries: list[dict] | None) -> None:
    global _pending_all
    if entries is None:
        _pending_all = True
        _pending_keys.clear()
        return
    if _pending_all:
        return
    _pending_keys.update(
        key
        for entry in entries
        if (key := _entry_key(entry))
    )


def check_movie_subscriptions(entries: list[dict] | None = None) -> int:
    """Coalesce overlapping movie checks instead of silently dropping them."""
    global _check_runner_active, _pending_all

    with _check_gate:
        if _check_runner_active:
            _queue_followup(entries)
            return 0
        _check_runner_active = True

    total = 0
    current = entries
    try:
        while True:
            total += int(_ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS(current) or 0)
            with _check_gate:
                if _pending_all:
                    _pending_all = False
                    _pending_keys.clear()
                    current = None
                    continue
                if _pending_keys:
                    keys = set(_pending_keys)
                    _pending_keys.clear()
                    current = _entries_for_keys(keys)
                    continue
                _check_runner_active = False
                return total
    finally:
        with _check_gate:
            if _check_runner_active:
                _check_runner_active = False


def movie_subscriptions_payload() -> dict:
    """Expose only client-facing subscription state, never raw probe caches."""
    payload = _ORIGINAL_MOVIE_SUBSCRIPTIONS_PAYLOAD()
    items = []
    for raw in payload.get("movie_subscriptions") or []:
        item = dict(raw)
        cache = item.get("quality_probe_cache")
        if isinstance(cache, dict):
            item["quality_probe_cache_entries"] = len(cache)
        for key in tuple(item):
            if key in _INTERNAL_SUBSCRIPTION_FIELDS or key.startswith("_upgrade_"):
                item.pop(key, None)
        items.append(item)
    return {
        **payload,
        "movie_subscriptions": items,
    }


def _cached_jellyfin_library(force: bool = False):
    # The underlying legacy movie-subscription pass performs the authoritative
    # forced refresh later in the same cycle.  The quality synchronization pass
    # reuses the existing cache to avoid two back-to-back Jellyfin scans.
    return _BACKEND_GET_JELLYFIN_LIBRARY(force=False)


quality_service.get_jellyfin_library = _cached_jellyfin_library


def movie_subscription_auto_check_loop():
    """Run movie quality inventories independently from the series watchlist."""
    while True:
        interval_min = max(5, int(state.automation.get("check_interval_min", 30)))
        started = time.monotonic()
        try:
            check_movie_subscriptions()
        except Exception as exc:
            log(f"Automatische Film-Abo-Prüfung fehlgeschlagen: {exc}", "warn")
        elapsed = time.monotonic() - started
        time.sleep(max(5.0, interval_min * 60.0 - elapsed))


def _ensure_movie_loop() -> None:
    global _movie_loop_started
    with _movie_loop_lock:
        if _movie_loop_started:
            return
        _movie_loop_started = True
        threading.Thread(
            target=movie_subscription_auto_check_loop,
            name="movie-subscription-check",
            daemon=True,
        ).start()


def watchlist_auto_check_loop():
    """Keep series checks responsive while movie inventories run separately."""
    _ensure_movie_loop()
    while True:
        interval_min = state.automation.get("check_interval_min", 30)
        checked = total = 0
        try:
            checked, total = _ORIGINAL_WATCHLIST_CHECK_ONCE()
        except Exception as exc:
            log(f"Automatische Bibliotheks-Prüfung fehlgeschlagen: {exc}", "warn")
        time.sleep(_ORIGINAL_WATCHLIST_CHECK_DELAY(checked, total, interval_min))


# Preserve the established service-ownership contract for diagnostics/tests.
watchlist_auto_check_loop.__module__ = "application_services.automation"

# Library routes resolve these names in their own module globals.
library_router.check_movie_subscriptions = check_movie_subscriptions
library_router.movie_subscriptions_payload = movie_subscriptions_payload

_SERVICE_EXPORTS = (
    "check_movie_subscriptions",
    "movie_subscriptions_payload",
    "movie_subscription_auto_check_loop",
    "watchlist_auto_check_loop",
)
publish_service(globals(), _SERVICE_EXPORTS)
