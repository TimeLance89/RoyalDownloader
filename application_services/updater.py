"""Logging, WebSocket publication, and runtime update services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


# ---------------------------------------------------------------------------
# WebSocket-Broadcast (Log / Fortschritt / Queue-Events)
# ---------------------------------------------------------------------------
ws_manager = WSManager()
_main_loop = None  # wird in lifespan gesetzt
_telegram_bot: Optional[TelegramBot] = None
_background_services_started = False
_background_services_lock = threading.Lock()
_recommender_stop_event = threading.Event()
_recommender_wake_event = threading.Event()
_recommender_thread: Optional[threading.Thread] = None
_seerr_stop_event = threading.Event()
_seerr_wake_event = threading.Event()
_seerr_thread: Optional[threading.Thread] = None
_updater_stop_event = threading.Event()
_updater_wake_event = threading.Event()
_updater_thread: Optional[threading.Thread] = None
_ytdlp_updater_stop_event = threading.Event()
_ytdlp_updater_thread: Optional[threading.Thread] = None


def broadcast(data: dict):
    loop = backend_value("_main_loop")
    if loop is None or loop.is_closed():
        return
    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            ws_manager.publish(data)
        else:
            loop.call_soon_threadsafe(ws_manager.publish, data)
    except RuntimeError:
        pass


def log(msg: str, level: str = ""):
    logger.info(msg)
    broadcast({"type": "log", "message": msg, "level": level})


def _restart_after_update(queue_already_paused: bool = False) -> None:
    def _restart():
        preserved = 0 if queue_already_paused else _pause_downloads_for_update_restart()
        if preserved:
            log(
                f"Update-Neustart: {preserved} offene Queue-Einträge gespeichert; "
                "sie werden danach automatisch fortgesetzt."
            )
        time.sleep(1)
        bootstrap = os.environ.get("APP_BOOTSTRAP_PATH", "").strip()
        base_python = os.environ.get("APP_BASE_PYTHON", "").strip()
        if bootstrap and base_python and Path(bootstrap).is_file():
            os.chdir(Path(bootstrap).parent)
            os.execv(base_python, [base_python, bootstrap])
        os.chdir(APP_DIR)
        start_script = APP_DIR / "start.sh"
        bash = shutil.which("bash")
        if os.name != "nt" and Path("/.dockerenv").exists() and bash and start_script.is_file():
            os.execv(bash, [bash, str(start_script)])
        os.execv(sys.executable, [sys.executable, str(APP_DIR / "server.py")])

    threading.Thread(target=_restart, daemon=True).start()


UPDATE_INSTALLER = SelfUpdater(
    repository=UPDATE_CHECKER.repository,
    app_dir=APP_DIR,
    on_state=lambda payload: broadcast({"type": "updater_install", "installer": payload}),
    restart_callback=_restart_after_update,
)
YTDLP_UPDATER = YtDlpRuntimeUpdater()

AUTO_UPDATE_START_DELAY_SECONDS = 30
AUTO_UPDATE_DEFER_SECONDS = 5 * 60
AUTO_UPDATE_ERROR_RETRY_SECONDS = 15 * 60


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


YTDLP_UPDATE_START_DELAY_SECONDS = _bounded_env_int(
    "YTDLP_UPDATE_START_DELAY_SECONDS", 300, 30, 24 * 60 * 60,
)
YTDLP_UPDATE_INTERVAL_HOURS = _bounded_env_int(
    "YTDLP_UPDATE_INTERVAL_HOURS", 24, 1, 168,
)
YTDLP_AUTO_UPDATE = os.environ.get(
    "YTDLP_AUTO_UPDATE", "false",
).strip().casefold() not in {"0", "false", "no", "off"}


def _updater_config_payload() -> dict:
    # Die Datei ist die autoritative Quelle. Besonders direkt nach einem
    # Kanalwechsel darf ein älterer In-Memory-Snapshot die Oberfläche nicht
    # wieder von Overnight auf Stable zurücksetzen.
    persisted = appconfig.load_updater()
    with state.updater_config_lock:
        if state.updater_cfg != persisted:
            state.updater_cfg = dict(persisted)
        config = dict(persisted)
    channel = appconfig.normalize_update_channel(config.get("update_channel"))
    config["update_channel"] = channel
    config["update_branch"] = appconfig.update_branch_for_channel(channel)
    with state.updater_runtime_lock:
        runtime = dict(state.updater_runtime)
    return {**config, **runtime}


def _set_updater_runtime(result: str, message: str, *, checked: bool = False) -> None:
    with state.updater_runtime_lock:
        state.updater_runtime["auto_update_state"] = result
        state.updater_runtime["auto_update_message"] = str(message or "")[:500]
        if checked:
            state.updater_runtime["last_auto_check"] = time.time()
    broadcast({"type": "updater_config", "config": _updater_config_payload()})


def _update_block_reason_locked() -> str:
    if state.dl_queue.active_count() or state.dl_queue.pending_count():
        return "Laufende oder wartende Downloads"
    if state.queue_prepare_lock.locked():
        return "Downloadvorbereitung oder Wiederholungsversuch läuft"
    _reconcile_idle_queue_state_locked()
    if state.provider_waiting_jobs:
        return "Downloadvorbereitung oder Wiederholungsversuch läuft"
    return ""


def _start_update_when_idle(target_sha: str) -> dict:
    """Startet das Update auch bei aktiver Queue.

    Downloads dürfen während des Ladens weiterlaufen. Direkt vor dem Neustart
    werden alle noch offenen Slugs persistent gesichert und die Prozesse sauber
    gestoppt; der neue Server stellt sie automatisch wieder her.
    """
    with state.queue_lifecycle_lock:
        if state.ytdlp_update_active:
            raise RuntimeError("yt-dlp wird gerade aktualisiert")
        queued = bool(
            state.dl_queue.active_count()
            or state.dl_queue.pending_count()
            or bool(state.provider_waiting_jobs)
        )
        result = UPDATE_INSTALLER.start(target_sha)
    if queued:
        log("Update wird installiert; die aktive Queue wird erst zum Neustart pausiert.")
    return result


def _attempt_automatic_update() -> str:
    with state.updater_config_lock:
        config = dict(state.updater_cfg)
        if config.get("update_mode") != appconfig.UPDATE_MODE_AUTOMATIC:
            return "manual"
    channel = appconfig.normalize_update_channel(config.get("update_channel"))
    branch = appconfig.update_branch_for_channel(channel)

    try:
        update = UPDATE_CHECKER.check_branch(branch, True)
    except Exception as exc:
        message = f"GitHub-Prüfung fehlgeschlagen: {exc}"
        _set_updater_runtime("error", message, checked=True)
        log(f"Automatische Updateprüfung fehlgeschlagen: {exc}", "warn")
        return "error"

    if update.get("error"):
        message = str(update.get("error"))
        _set_updater_runtime("error", message, checked=True)
        log(f"Automatische Updateprüfung fehlgeschlagen: {message}", "warn")
        return "error"
    if update.get("quality_approved") is False:
        _set_updater_runtime(
            "unavailable",
            "Der Overnight-Build wird erst nach erfolgreichen Quality Gates angeboten.",
            checked=True,
        )
        return "unavailable"
    if (
        channel == "stable"
        and update.get("comparison") in {"behind", "diverged"}
        and update.get("current_sha")
        and update.get("latest_sha")
    ):
        _set_updater_runtime(
            "manual_required",
            "Der Wechsel zu Stable kann einen älteren Build aktivieren und muss bestätigt werden.",
            checked=True,
        )
        return "manual_required"
    if update.get("update_available") is not True:
        if update.get("comparison") in {"identical", "behind"}:
            _set_updater_runtime("current", "Kein Update verfügbar.", checked=True)
            return "current"
        _set_updater_runtime(
            "unavailable",
            "Lokaler Build konnte nicht sicher mit GitHub verglichen werden.",
            checked=True,
        )
        return "unavailable"
    if update.get("comparison") != "ahead":
        _set_updater_runtime(
            "manual_required",
            "Lokaler und GitHub-Stand sind verzweigt; manuelle Bestätigung erforderlich.",
            checked=True,
        )
        return "manual_required"

    target_sha = str(update.get("latest_sha") or "").strip()
    if not target_sha:
        _set_updater_runtime("error", "GitHub lieferte keine installierbare Revision.", checked=True)
        return "error"

    try:
        with state.updater_config_lock:
            if state.updater_cfg.get("update_mode") != appconfig.UPDATE_MODE_AUTOMATIC:
                _set_updater_runtime("manual", "Automatische Installation wurde deaktiviert.", checked=True)
                return "manual"
        _start_update_when_idle(target_sha)
    except (RuntimeError, ValueError) as exc:
        message = str(exc)
        result = "deferred" if "zurückgestellt" in message else "error"
        _set_updater_runtime(result, message, checked=True)
        if result == "error":
            log(f"Automatisches Update konnte nicht gestartet werden: {message}", "warn")
        return result

    _set_updater_runtime("installing", "Update wird automatisch installiert.", checked=True)
    log(f"Automatisches Update auf Build {target_sha[:8]} gestartet.")
    return "installing"


def automatic_update_loop() -> None:
    if _updater_stop_event.wait(AUTO_UPDATE_START_DELAY_SECONDS):
        return
    _updater_wake_event.clear()
    while not _updater_stop_event.is_set():
        with state.updater_config_lock:
            config = dict(state.updater_cfg)
        if config.get("update_mode") == appconfig.UPDATE_MODE_AUTOMATIC:
            result = _attempt_automatic_update()
            if result == "deferred":
                delay = AUTO_UPDATE_DEFER_SECONDS
            elif result == "error":
                delay = AUTO_UPDATE_ERROR_RETRY_SECONDS
            else:
                delay = int(config.get("auto_update_interval_hours") or 6) * 60 * 60
        else:
            delay = 60 * 60
        _updater_wake_event.wait(max(1, delay))
        _updater_wake_event.clear()


def _attempt_ytdlp_runtime_update() -> str:
    """Aktualisiert yt-dlp stabil und erhält dabei alle Queue-Claims."""
    if not YTDLP_AUTO_UPDATE:
        return "disabled"
    if UPDATE_INSTALLER.is_active() or state.ytdlp_update_active:
        return "busy"
    try:
        update = YTDLP_UPDATER.check()
    except Exception as exc:
        log(f"yt-dlp-Updateprüfung fehlgeschlagen: {exc}", "warn")
        return "error"
    if not update.get("update_available"):
        logger.info("yt-dlp ist aktuell (%s).", update.get("current") or "unbekannt")
        return "current"

    current = str(update.get("current") or "nicht installiert")
    latest = str(update.get("latest") or "")
    log(f"yt-dlp-Update verfügbar: {current} → {latest}; Paket wird vorbereitet.")
    paused = False
    try:
        with tempfile.TemporaryDirectory(prefix="seriendownloader-ytdlp-") as tmp:
            wheel = YTDLP_UPDATER.download_wheel(
                latest, Path(tmp), update.get("wheel_sha256") or [],
            )
            with state.queue_lifecycle_lock:
                if UPDATE_INSTALLER.is_active() or state.ytdlp_update_active:
                    return "busy"
                state.ytdlp_update_active = True
            preserved = _pause_downloads_for_update_restart()
            paused = True
            if preserved:
                log(
                    f"yt-dlp-Update: {preserved} offene Queue-Einträge gespeichert; "
                    "Fortsetzung nach Neustart."
                )
            YTDLP_UPDATER.install_wheel(wheel)
    except Exception as exc:
        if state.ytdlp_update_active:
            # Auch bei einem pip-/Pause-Fehler neu starten, damit die Queue mit
            # der bisherigen Version weiterläuft.
            _restart_after_update(queue_already_paused=paused)
        log(f"yt-dlp-Update fehlgeschlagen: {exc}", "warn")
        return "error"

    log(f"yt-dlp {latest} installiert – Server startet neu.")
    _restart_after_update(queue_already_paused=True)
    return "restarting"


def ytdlp_runtime_update_loop() -> None:
    if not YTDLP_AUTO_UPDATE:
        return
    if _ytdlp_updater_stop_event.wait(YTDLP_UPDATE_START_DELAY_SECONDS):
        return
    while not _ytdlp_updater_stop_event.is_set():
        result = _attempt_ytdlp_runtime_update()
        delay = (
            60 * 60
            if result in {"busy", "error"}
            else YTDLP_UPDATE_INTERVAL_HOURS * 60 * 60
        )
        if _ytdlp_updater_stop_event.wait(delay):
            return


_SERVICE_EXPORTS = (
    "ws_manager",
    "_main_loop",
    "_telegram_bot",
    "_background_services_started",
    "_background_services_lock",
    "_recommender_stop_event",
    "_recommender_wake_event",
    "_recommender_thread",
    "_seerr_stop_event",
    "_seerr_wake_event",
    "_seerr_thread",
    "_updater_stop_event",
    "_updater_wake_event",
    "_updater_thread",
    "_ytdlp_updater_stop_event",
    "_ytdlp_updater_thread",
    "broadcast",
    "log",
    "_restart_after_update",
    "UPDATE_INSTALLER",
    "YTDLP_UPDATER",
    "AUTO_UPDATE_START_DELAY_SECONDS",
    "AUTO_UPDATE_DEFER_SECONDS",
    "AUTO_UPDATE_ERROR_RETRY_SECONDS",
    "_bounded_env_int",
    "YTDLP_UPDATE_START_DELAY_SECONDS",
    "YTDLP_UPDATE_INTERVAL_HOURS",
    "YTDLP_AUTO_UPDATE",
    "_updater_config_payload",
    "_set_updater_runtime",
    "_update_block_reason_locked",
    "_start_update_when_idle",
    "_attempt_automatic_update",
    "automatic_update_loop",
    "_attempt_ytdlp_runtime_update",
    "ytdlp_runtime_update_loop",
)
publish_service(globals(), _SERVICE_EXPORTS)
