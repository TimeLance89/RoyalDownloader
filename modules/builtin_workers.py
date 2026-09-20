"""Concrete built-in worker modules, isolated from the FastAPI composition root.

The application-services runtime bridge is intentionally used here because the
legacy workers still own their events and runtime references in the server
namespace.  New built-ins only need to register here (or in their own package),
not add lifecycle branches to ``server.py``.
"""

from __future__ import annotations

import threading
from typing import Callable

from application_services.runtime import backend_value, set_backend_value
from modules.runtime import WorkerModuleController


def _thread_alive(reference: str) -> bool:
    thread = backend_value(reference)
    return bool(thread and thread.is_alive())


def _start_thread(
    reference: str,
    target_name: str,
    thread_name: str,
    clear_events: tuple[str, ...],
) -> None:
    if _thread_alive(reference):
        return
    for event_name in clear_events:
        backend_value(event_name).clear()
    worker = threading.Thread(
        target=backend_value(target_name),
        name=thread_name,
        daemon=True,
    )
    set_backend_value(reference, worker)
    worker.start()


def _stop_threads(
    references: tuple[str, ...],
    signal_events: tuple[str, ...],
    timeout: float = 2.0,
) -> bool:
    for event_name in signal_events:
        backend_value(event_name).set()
    current = threading.current_thread()
    for reference in references:
        worker = backend_value(reference)
        if worker and worker is not current:
            worker.join(timeout)
    return not any(_thread_alive(reference) for reference in references)


def _configuration(
    key: str,
    configured: bool,
    missing_detail: str,
) -> tuple[bool, str]:
    return (True, f"{key} konfiguriert") if configured else (False, missing_detail)


def _jellyfin_configuration() -> tuple[bool, str]:
    config = backend_value("state").jellyfin_cfg
    return _configuration(
        "Jellyfin",
        bool(config.get("url") and config.get("api_key")),
        "Jellyfin-Zugangsdaten fehlen",
    )


def _seerr_configuration() -> tuple[bool, str]:
    config = backend_value("state").seerr_cfg
    return _configuration(
        "Seerr",
        bool(config.get("enabled") and config.get("url") and config.get("api_key")),
        "Seerr ist nicht eingerichtet oder in den Integrationseinstellungen deaktiviert",
    )


def _telegram_configuration() -> tuple[bool, str]:
    config = backend_value("state").telegram_cfg
    return _configuration(
        "Telegram",
        bool(config.get("enabled") and config.get("bot_token")),
        "Telegram ist nicht eingerichtet oder in den Integrationseinstellungen deaktiviert",
    )


def _updates_configuration() -> tuple[bool, str]:
    return True, "Automatische Prüfungen konfiguriert"


def _start_telegram() -> None:
    bot = backend_value("_telegram_bot")
    if bot is None:
        raise RuntimeError("Telegram wird noch initialisiert")
    bot.start()


def _stop_telegram() -> bool:
    bot = backend_value("_telegram_bot")
    return True if bot is None else bot.stop_and_wait()


def _telegram_alive() -> bool:
    bot = backend_value("_telegram_bot")
    return bool(bot and bot.is_running())


def _start_updates() -> None:
    backend_value("_updater_stop_event").clear()
    backend_value("_updater_wake_event").clear()
    backend_value("_ytdlp_updater_stop_event").clear()
    _start_thread(
        "_updater_thread",
        "automatic_update_loop",
        "automatic-updater",
        (),
    )
    _start_thread(
        "_ytdlp_updater_thread",
        "ytdlp_runtime_update_loop",
        "ytdlp-runtime-updater",
        (),
    )


def _updates_alive() -> bool:
    # yt-dlp runtime updates are an opt-in capability. A disabled updater must
    # not make the regular automatic-update worker look unhealthy.
    return _thread_alive("_updater_thread") and (
        not backend_value("YTDLP_AUTO_UPDATE")
        or _thread_alive("_ytdlp_updater_thread")
    )


def register_builtin_worker_controllers(manager) -> None:
    """Register all module-owned worker contracts with a generic manager."""
    manager.register_controller(
        "jellyfin-recommendations",
        WorkerModuleController(
            lambda: _start_thread(
                "_recommender_thread",
                "jellyfin_recommender_loop",
                "jellyfin-recommender",
                ("_recommender_stop_event", "_recommender_wake_event"),
            ),
            lambda: _stop_threads(
                ("_recommender_thread",),
                ("_recommender_stop_event", "_recommender_wake_event"),
            ),
            lambda: _thread_alive("_recommender_thread"),
            _jellyfin_configuration,
        ),
    )
    manager.register_controller(
        "seerr-sync",
        WorkerModuleController(
            lambda: _start_thread(
                "_seerr_thread",
                "seerr_poll_loop",
                "seerr-request-bridge",
                ("_seerr_stop_event", "_seerr_wake_event"),
            ),
            lambda: _stop_threads(
                ("_seerr_thread",),
                ("_seerr_stop_event", "_seerr_wake_event"),
            ),
            lambda: _thread_alive("_seerr_thread"),
            _seerr_configuration,
        ),
    )
    manager.register_controller(
        "telegram-control",
        WorkerModuleController(
            _start_telegram,
            _stop_telegram,
            _telegram_alive,
            _telegram_configuration,
        ),
    )
    manager.register_controller(
        "automatic-updates",
        WorkerModuleController(
            _start_updates,
            lambda: _stop_threads(
                ("_updater_thread", "_ytdlp_updater_thread"),
                ("_updater_stop_event", "_updater_wake_event", "_ytdlp_updater_stop_event"),
            ),
            _updates_alive,
            _updates_configuration,
        ),
    )
