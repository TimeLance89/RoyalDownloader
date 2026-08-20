"""Runtime integration for Royal's smart unattended automation policy."""

from __future__ import annotations

import threading
import time

import smart_automation as smart_policy
from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
    _registered_backend,
)

# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821
globals().update(import_backend_namespace())

_ORIGINAL_AUTO_DOWNLOAD_NEW_EPISODES = backend_value("_auto_download_new_episodes")
_DEFER_LOG_INTERVAL_SECONDS = 30 * 60
_defer_log_lock = threading.Lock()
_defer_log_state: dict[str, tuple[str, float]] = {}


def _log_deferred(kind: str, reason: str) -> None:
    """Avoid flooding the live log while a persistent policy gate is closed."""

    now = time.monotonic()
    with _defer_log_lock:
        previous_reason, previous_at = _defer_log_state.get(kind, ("", 0.0))
        if reason == previous_reason and now - previous_at < _DEFER_LOG_INTERVAL_SECONDS:
            return
        _defer_log_state[kind] = (reason, now)
    log(f"{kind} zurückgestellt: {reason}.", "info")


def is_within_download_window() -> bool:
    """Compatibility seam: evaluate the weekday/weekend schedule."""

    policy = dict(state.automation)
    local = time.localtime()
    return smart_policy.schedule_is_open(policy, local.tm_wday, local.tm_hour)


def _auto_download_new_episodes() -> None:
    """Run automatic series scheduling only while every unattended gate is open."""

    allowed, reason = smart_policy.automatic_series_decision(state)
    if not allowed:
        if state.automation.get("auto_download") and reason:
            _log_deferred("Auto-Download", reason)
        return
    _ORIGINAL_AUTO_DOWNLOAD_NEW_EPISODES()


def movie_subscription_auto_check_loop() -> None:
    """Check quality subscriptions on their own optional nighttime schedule."""

    while True:
        interval_min = max(5, int(state.automation.get("check_interval_min", 30)))
        started = time.monotonic()
        allowed, reason = smart_policy.automatic_movie_upgrade_decision(state)
        if allowed:
            try:
                check_movie_subscriptions()
            except Exception as exc:
                log(f"Automatische Film-Abo-Prüfung fehlgeschlagen: {exc}", "warn")
        elif reason:
            _log_deferred("Film-Upgrades", reason)
        elapsed = time.monotonic() - started
        time.sleep(max(5.0, interval_min * 60.0 - elapsed))


# Keep existing diagnostics/tests that treat automation.py as the functional
# owner of schedule decisions compatible with the extracted policy layer.
is_within_download_window.__module__ = "application_services.automation"
_auto_download_new_episodes.__module__ = "application_services.automation"

# Bind the live queue and persisted policy only after AppState exists.
smart_policy.bind_backend(_registered_backend())


_SERVICE_EXPORTS = (
    "is_within_download_window",
    "_auto_download_new_episodes",
    "movie_subscription_auto_check_loop",
)
publish_service(globals(), _SERVICE_EXPORTS)
