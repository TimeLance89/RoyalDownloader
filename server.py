"""
Royal Downloader – lokaler Webserver.

Ersetzt die frühere customtkinter-GUI (main.py) durch eine HTML/CSS/JS-
Oberfläche, die im Standardbrowser läuft. Anbieteradapter liegen gebündelt im
Paket ``providers``; dieser Server bildet die REST-/WebSocket-Schicht darüber.

Start: python server.py  (öffnet automatisch den Browser)
"""

import asyncio
import logging
import os
import re
import shutil
import threading
import time
import tempfile
import unicodedata
import uuid
import webbrowser
import base64
import ipaddress
import secrets
import socket
import sys
import requests
from copy import deepcopy
from contextlib import asynccontextmanager
from collections import Counter, OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from providers.filmpalast import FilmpalastScraper
from providers.models import (
    FilmpalastMovie, FilmpalastSearchResult,
    FilmpalastSeries, FilmpalastSeriesResult,
    parse_episode_slug, strip_episode_suffix,
)
from providers.catalog import (
    PROVIDER_CATALOG,
    normalize_content_language,
    provider_catalog_payload,
    provider_content_language,
    provider_for_source,
    provider_language_payload,
)
from extractor import (
    VOEBrowserPool, extract_stream_url, pre_check_voe, VOE_NOT_FOUND, extract_doodstream_url,
    extract_firestream_url, extract_vidara_url, extract_vidsonic_url,
)
from downloader import (
    DownloadJob, DownloadQueue, build_filename, build_movie_filename,
    probe_stream_url, validate_media_file, cleanup_stale_staging,
    _sanitize as sanitize_filename,
)
from session_manager import ProviderBlockedError, _cookie_file_for
from hoster_intel import HosterIntel
from provider_health import COOLDOWN, HEALTHY, PROBING, ProviderHealth
from resolved_link_cache import ResolvedLinkCache
from runtime_cache import BoundedTTLCache
from api_system_router import create_system_router
from api_domain_routers import install_domain_routers, register_domain_router
from api_auth_router import (
    ApiV1LoginBody,
    AuthConfigBody,
    AuthDependencies,
    LoginBody,
    create_auth_router,
)
from api_setup_router import SetupCompleteBody, SetupDependencies, create_setup_router
from api_discovery_router import (
    MovieMetadataBody,
    MovieMetadataItem,
    PreloadBody,
    SeriesJellyfinEpisodeBody,
    SeriesJellyfinStatusBody,
    SeriesLoadBody,
    SeriesMetadataBody,
    SeriesMetadataItem,
    create_discovery_router,
)
from api_queue_router import (
    MovieDownloadPreference,
    QueueAddBody,
    QueueRemoveBody,
    TasteEventBody,
    TasteFeedbackBody,
    TasteImportBody,
    _QueuePreparationJob,
    _cancel_queue_slugs,
    _cancel_withdrawn_watchlist_slugs,
    _drop_queue_claims,
    _enqueue_automatic_downloads,
    _job_queue_slugs,
    _preferred_movie_sources,
    _record_download_taste,
    _release_removed_queue_slugs,
    api_download_cancel,
    api_queue_add,
    api_queue_clear,
    api_queue_get,
    api_queue_remove,
    api_taste_event,
    api_taste_feedback,
    api_taste_import,
    api_taste_profile_get,
    api_taste_profile_reset,
    create_queue_router,
    restore_persisted_queue,
)
from api_library_router import (
    MovieSubscriptionBody,
    MovieSubscriptionKeysBody,
    WatchlistAddBody,
    WatchlistCheckBody,
    WatchlistModeBody,
    WatchlistOpenBody,
    WatchlistRemoveBody,
    _apply_watchlist_entry_state,
    _calculate_watchlist_entry_state,
    _execute_watchlist_cleanup,
    _fetch_cover_data,
    _prepare_movie_subscription_upgrade,
    _safe_public_http_url,
    _update_watchlist_entry_state,
    api_cover,
    api_movie_subscription_save,
    api_movie_subscriptions_check,
    api_movie_subscriptions_get,
    api_movie_subscriptions_remove,
    api_watchlist_add,
    api_watchlist_check,
    api_watchlist_get,
    api_watchlist_mode,
    api_watchlist_open,
    api_watchlist_remove,
    check_movie_subscriptions,
    check_watchlist_entries,
    create_library_router,
    movie_subscription_key,
    movie_subscription_lookup,
    movie_subscriptions_payload,
)
from api_administration_router import (
    AutomationConfigBody,
    ConfigBody,
    JellyfinConfigBody,
    JellyfinUsersBody,
    ProviderPriorityBody,
    SeerrConfigBody,
    TelegramConfigBody,
    TMDBConfigBody,
    UILanguageBody,
    UITranslationBody,
    UpdateInstallBody,
    UpdaterConfigBody,
    _api_setup_complete_locked,
    _prepare_media_directory,
    _provider_priority_payload,
    _recover_misplaced_media,
    _seerr_config_payload,
    _setup_status_payload,
    _ui_language_payload,
    api_automation_config_get,
    api_automation_config_set,
    api_browse_dir,
    api_clear_cookies,
    api_config_get,
    api_config_set,
    api_jellyfin_config_get,
    api_jellyfin_config_set,
    api_jellyfin_users,
    api_provider_priority_get,
    api_provider_priority_set,
    api_provider_status_get,
    api_seerr_config_get,
    api_seerr_config_set,
    api_seerr_requests,
    api_seerr_sync,
    api_serienstream_retry,
    api_telegram_config_get,
    api_telegram_config_set,
    api_tmdb_config_get,
    api_tmdb_config_set,
    api_ui_config_get,
    api_ui_config_set,
    api_ui_translate,
    api_updater_config_get,
    api_updater_config_set,
    api_updater_install,
    api_updater_install_status,
    api_updater_rollback,
    api_updater_status,
    create_administration_router,
)
from api_security import SecurityDependencies, install_authentication_middleware
from app_state import AppState, _PreparationSlots
from websocket_manager import WSManager, _WSClient
from api_websocket_router import (
    WebSocketDependencies,
    create_websocket_router,
    websocket_origin_allowed as _websocket_origin_allowed,
)
from media_paths import (
    prepare_media_directory,
    recover_misplaced_media,
)
from runtime_paths import data_dir, in_container, persistent_container_path
from network_guard import is_public_http_url
from providers.filmfrei24 import (
    BASE_URL as FILMFREI24_BASE_URL,
    FilmFrei24Scraper,
    SOURCE_PREFIX as FILMFREI24_PREFIX,
)
from providers.moflix import MoflixScraper, SOURCE_PREFIX as MOFLIX_PREFIX
from providers.huhu import (
    HuhuScraper,
    MOVIE_SOURCE_PREFIX as HUHU_MOVIE_PREFIX,
    SOURCE_PREFIX as HUHU_PREFIX,
)
from providers.einschalten import EinschaltenScraper, SOURCE_PREFIX as EINSCHALTEN_PREFIX
from providers.kinox import KinoxScraper, SOURCE_PREFIX as KINOX_PREFIX
from providers.kinoger import KinogerScraper, SOURCE_PREFIX as KINOGER_PREFIX
from providers.megakino import MegaKinoScraper, SOURCE_PREFIX as MEGAKINO_PREFIX
from providers.xcine import XcineScraper, SOURCE_PREFIX as XCINE_PREFIX
from providers.sflix import (
    BASE_URL as SFLIX_BASE_URL,
    SflixScraper,
    SOURCE_PREFIX as SFLIX_PREFIX,
)
from providers.ridomovies import (
    BASE_URL as RIDOMOVIES_BASE_URL,
    RidomoviesScraper,
    SOURCE_PREFIX as RIDOMOVIES_PREFIX,
)
from providers.mkissa import (
    BASE_URL as MKISSA_BASE_URL,
    MkissaScraper,
    SOURCE_PREFIX as MKISSA_PREFIX,
    anime_episode_page,
)
from providers.serienstream import SerienstreamScraper, SOURCE_PREFIX as SERIENSTREAM_PREFIX
from jellyfin_client import JellyfinClient
from jellyfin_recommender import (
    Config as JellyfinRecommenderConfig,
    ConfigurationError as JellyfinRecommenderConfigurationError,
    RecommenderError as JellyfinRecommenderError,
    run_once as run_jellyfin_recommender_once,
)
from tmdb_client import SERIES_CACHE_TTL, TMDBClient
from telegram_bot import TelegramBot
from seerr_client import SeerrClient, SeerrRequest
from update_checker import UpdateChecker, detect_local_commit
from self_updater import SelfUpdater
from ytdlp_updater import YtDlpRuntimeUpdater
from ui_translator import (
    SUPPORTED_UI_LANGUAGES,
    UITranslator,
    normalize_ui_language,
)
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
from taste_profile import TasteProfileStore
import config as appconfig
import auth as appauth

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
for noisy_logger in ("websockets", "nodriver", "urllib3"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# nodriver 0.50.3 liefert cdp/network.py mit ungültigem UTF-8 aus (siehe
# nodriver_patch). Auf frischen Installationen (Docker/NAS) scheitert sonst
# schon `import nodriver` → VOE-Extraktion tot. Einmal beim Start reparieren,
# BEVOR irgendein Codepfad nodriver importiert.
import nodriver_patch  # noqa: E402 - Reparatur muss vor dem ersten nodriver-Import laufen.
nodriver_patch.ensure_cdp_utf8()

APP_DIR = Path(__file__).parent
WEB_DIR = APP_DIR / "web"
API_VERSION = 1
EVENT_SCHEMA_VERSION = 1
WEBSOCKET_AUTH_RECHECK_SECONDS = 30.0
WEBSOCKET_CLIENT_QUEUE_SIZE = 128
SERVER_BUILD = detect_local_commit(APP_DIR)[:12]
SESSION_STORE = appauth.SessionStore(path=appconfig.sessions_file())
LOGIN_GUARD = appauth.LoginGuard()
BASIC_AUTH_GUARD = appauth.LoginGuard()
# Die Anmeldemaske wird wie die restliche Oberfläche übersetzt; dafür muss
# /api/ui/translate vor der Anmeldung erreichbar sein. Ein Budget je IP
# verhindert, dass daraus ein offener Übersetzungsproxy wird.
PUBLIC_TRANSLATE_LIMITER = appauth.RateLimiter(max_requests=60, window_seconds=300)
PUBLIC_TRANSLATE_WORK_LIMITER = appauth.RateLimiter(
    max_requests=600,
    window_seconds=300,
)
UPDATE_CHECKER = UpdateChecker(
    repository=os.environ.get("UPDATE_GITHUB_REPOSITORY", "TimeLance89/RoyalDownloader"),
    branch=os.environ.get("UPDATE_GITHUB_BRANCH", "main"),
    app_dir=APP_DIR,
)
UI_TRANSLATOR = UITranslator()
PROVIDER_LABELS = {
    key: definition.label
    for key, definition in PROVIDER_CATALOG.items()
}
MOVIE_BROWSE_PAGE_SIZE = 32
MOVIE_PAGINATED_PROVIDERS = frozenset({
    "filmpalast", "megakino", "kinoger", "xcine", "sflix", "ridomovies",
})
MOVIE_LIST_CACHE_TTL = 300
MOVIE_LIST_FAILURE_CACHE_TTL = 30
MOVIE_LIST_CACHE_MAX_ENTRIES = 1000
MOVIE_MAX_GLOBAL_PAGE = 50
MOVIE_MAX_SOURCE_PAGE = 50
MOVIE_MAX_COLD_WAVES_PER_REQUEST = 2
TMDB_MOVIE_BATCH_MAX_WORKERS = 8
TMDB_MOVIE_SEARCH_MAX_RESULTS = 40
MOVIE_GENRE_GROUPS = {
    "Animation": ("Animation", "Zeichentrick"),
    "Biografie": ("Biografie", "Biographie"),
    "Dokumentation": ("Dokumentation", "Dokumentarfilm"),
    "Geschichte": ("Geschichte", "Historie"),
    "Krieg": ("Krieg", "Kriegsfilm"),
    "Romantik": ("Romantik", "Romance", "Liebesfilm"),
    "Science-Fiction": ("Science-Fiction", "Science Fiction", "Sci-Fi"),
}
MOVIE_GENRE_CANONICAL_BY_KEY = {
    alias.casefold(): canonical
    for canonical, aliases in MOVIE_GENRE_GROUPS.items()
    for alias in aliases
}
SERIES_BROWSE_PAGE_SIZE = 32
SERIES_PAGINATED_PROVIDERS = frozenset({
    "filmpalast", "megakino", "kinoger", "xcine", "sflix", "ridomovies",
})
SERIES_ALPHA_PROVIDERS = frozenset({"serienstream", "filmpalast"})
SERIES_LIST_CACHE_TTL = 300
SERIES_LIST_FAILURE_CACHE_TTL = 30
SERIES_LIST_CACHE_MAX_ENTRIES = 500
SERIES_MAX_GLOBAL_PAGE = 50
SERIES_MAX_SOURCE_PAGE = 50
SERIES_MAX_COLD_WAVES_PER_REQUEST = 2


# ---------------------------------------------------------------------------
# Anmeldung
#
# Es gibt genau EIN Administratorkonto; die App ist durchgehend auf einen
# Nutzer ausgelegt (eine Watchlist, eine Queue, ein Jellyfin-Benutzer).
# Die Weboberfläche nutzt ein Sitzungs-Cookie. Native Clients können dasselbe
# widerrufbare, serverseitig gehashte Sitzungsformat als Bearer-Token verwenden.
# HTTP-Basic bleibt für bestehende Skripte und Health-Checks zusätzlich gültig.
# ---------------------------------------------------------------------------
def auth_account() -> dict:
    """Aktuell hinterlegtes Konto (settings.ini oder APP_USERNAME/APP_PASSWORD)."""
    return appconfig.load_auth()


def auth_configured() -> bool:
    return bool(auth_account().get("configured"))


def fail_closed_auth_enabled() -> bool:
    """Expliziter Schutz für öffentlich angebundene Installationen.

    Der Default bleibt für bestehende reine LAN-Installationen kompatibel. Wer
    den Dienst über einen Tunnel veröffentlicht, setzt `APP_REQUIRE_AUTH=1`;
    eine verlorene oder beschädigte Kontokonfiguration öffnet die API dann
    nicht stillschweigend.
    """
    return os.environ.get("APP_REQUIRE_AUTH", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def auth_required() -> bool:
    """Ob Anfragen abgewiesen werden, wenn keine Anmeldung vorliegt.

    Vor abgeschlossener Ersteinrichtung ist die Oberfläche offen – sonst wäre
    der Assistent, der das Konto erst anlegt, selbst nicht erreichbar.
    """
    if fail_closed_auth_enabled():
        return True
    if not appconfig.is_initialized():
        return False
    return auth_configured()


def setup_required() -> bool:
    """Ob die Erst- bzw. Sicherheitsmigration noch abgeschlossen werden muss."""
    return not appconfig.is_initialized() or not auth_configured()


def verify_credentials(username: str, password: str) -> bool:
    """Prüft Zugangsdaten gegen das hinterlegte Konto (zeitkonstant)."""
    account = auth_account()
    if not account.get("configured"):
        return False
    if not secrets.compare_digest(str(username or ""), str(account.get("username", ""))):
        # Trotzdem eine Hash-Runde rechnen, damit ein falscher Benutzername
        # nicht spürbar schneller beantwortet wird als ein falsches Passwort.
        appauth.verify_password(str(password or ""), account.get("password_hash", ""))
        return False
    if account.get("source") == "env":
        return secrets.compare_digest(str(password or ""), str(account.get("env_password", "")))
    return appauth.verify_password(str(password or ""), account.get("password_hash", ""))


def _authorized_basic_header(value: str, guard_key: str = "") -> bool:
    """Erlaubt weiterhin `Authorization: Basic` für Skripte und Monitoring."""
    if not value or not value.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(value[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return False
    key = guard_key or "basic-global"
    if BASIC_AUTH_GUARD.retry_after(key):
        return False
    authenticated = verify_credentials(username, password)
    if authenticated:
        BASIC_AUTH_GUARD.register_success(key)
    else:
        BASIC_AUTH_GUARD.register_failure(key)
    return authenticated


def _bearer_token(headers) -> str:
    """Liest ein Bearer-Token, ohne es zu protokollieren oder umzuschreiben."""
    value = str(headers.get("authorization", "") or "").strip()
    scheme, separator, credential = value.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    token = credential.strip()
    if not token or any(char.isspace() for char in token):
        return ""
    return token


def _session_token(scope_cookies: dict) -> str:
    return str(scope_cookies.get(appauth.SESSION_COOKIE_NAME) or "")


def authenticated_mobile_token(headers, *, touch: bool = True) -> str:
    """Gibt ausschließlich ein gültiges Mobile-Bearer-Token zurück."""
    bearer = _bearer_token(headers)
    if bearer and SESSION_STORE.validate(
        bearer, appauth.SESSION_KIND_MOBILE, touch=touch,
    ):
        return bearer
    return ""


def authenticated_web_token(cookies, *, touch: bool = True) -> str:
    """Gibt ausschließlich ein gültiges Browser-Cookie-Token zurück."""
    cookie = _session_token(cookies)
    if cookie and SESSION_STORE.validate(
        cookie, appauth.SESSION_KIND_WEB, touch=touch,
    ):
        return cookie
    return ""


def request_auth_method(
    headers,
    cookies,
    guard_key: str = "",
    *,
    versioned: bool = False,
    allow_mobile_bearer: bool = True,
    allow_basic: bool = True,
    touch: bool = True,
) -> str:
    """Authentifizierungsweg für Statusantworten; enthält nie Zugangsdaten."""
    if allow_mobile_bearer and authenticated_mobile_token(headers, touch=touch):
        return "bearer"
    if not versioned and authenticated_web_token(cookies, touch=touch):
        return "cookie"
    if (
        not versioned
        and allow_basic
        and _authorized_basic_header(headers.get("authorization", ""), guard_key)
    ):
        return "basic"
    return "none"


def request_is_authenticated(
    headers,
    cookies,
    guard_key: str = "",
    *,
    versioned: bool = False,
    allow_mobile_bearer: bool = True,
    allow_basic: bool = True,
    touch: bool = True,
) -> bool:
    """Gültiges Cookie-/Bearer-Token oder gültiger Basic-Header?"""
    if not auth_required():
        return True
    if allow_mobile_bearer and authenticated_mobile_token(headers, touch=touch):
        return True
    if not versioned and authenticated_web_token(cookies, touch=touch):
        return True
    return bool(
        not versioned
        and allow_basic
        and _authorized_basic_header(headers.get("authorization", ""), guard_key)
    )


def trust_cloudflare_headers_enabled() -> bool:
    """Nur explizit aktivieren, wenn der Origin ausschließlich den Tunnel sieht."""
    return os.environ.get("TRUST_CLOUDFLARE_HEADERS", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def client_key(request) -> str:
    """Herkunfts-IP für Sperren und Budgets."""
    client = getattr(request, "client", None)
    peer = getattr(client, "host", "") or "unbekannt"
    if not trust_cloudflare_headers_enabled():
        return peer
    raw = str(request.headers.get("cf-connecting-ip", "") or "").strip()
    # CF-Connecting-IP enthält exakt eine Adresse. Listen gehören zu XFF und
    # werden hier absichtlich nicht akzeptiert, damit kein frei wählbarer
    # erster Eintrag zum Umgehen der Login-Sperre wird.
    if not raw or "," in raw or len(raw) > 64:
        return peer
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return peer


# ---------------------------------------------------------------------------
# App-State (Ein-Nutzer, in-memory – entspricht den Instanzvariablen der
# früheren tkinter-App-Klasse)
# ---------------------------------------------------------------------------
state = AppState()


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
    loop = _main_loop
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
    with state.updater_config_lock:
        config = dict(state.updater_cfg)
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
        if state.updater_cfg.get("update_mode") != appconfig.UPDATE_MODE_AUTOMATIC:
            return "manual"

    try:
        update = UPDATE_CHECKER.check(True)
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


# ---------------------------------------------------------------------------
# Hilfsfunktionen (1:1 Logik aus der früheren main.py)
# ---------------------------------------------------------------------------
def get_fp_scraper() -> FilmpalastScraper:
    if state.fp_scraper is None:
        state.fp_scraper = FilmpalastScraper(progress_cb=log)
    return state.fp_scraper


def get_sto_scraper() -> SerienstreamScraper:
    if state.sto_scraper is None:
        state.sto_scraper = SerienstreamScraper(progress_cb=log)
    return state.sto_scraper


def get_moflix_scraper() -> MoflixScraper:
    if state.moflix_scraper is None:
        state.moflix_scraper = MoflixScraper(progress_cb=log)
    return state.moflix_scraper


def get_huhu_scraper() -> HuhuScraper:
    if state.huhu_scraper is None:
        state.huhu_scraper = HuhuScraper(progress_cb=log)
    return state.huhu_scraper


def get_mkissa_scraper() -> MkissaScraper:
    if state.mkissa_scraper is None:
        state.mkissa_scraper = MkissaScraper(progress_cb=log)
    return state.mkissa_scraper


def get_jellyfin_client() -> JellyfinClient:
    with state.jellyfin_cache_lock:
        cfg = dict(state.jellyfin_cfg)
    return JellyfinClient(cfg.get("url", ""), cfg.get("api_key", ""))


def _build_recommender_config() -> JellyfinRecommenderConfig:
    """Baut die Laufkonfiguration aus der persistenten settings.ini."""
    jellyfin = appconfig.load_jellyfin()
    env = {
        "JELLYFIN_URL": jellyfin.get("url", ""),
        "JELLYFIN_API_KEY": jellyfin.get("api_key", ""),
        "JELLYFIN_USER_ID": jellyfin.get("user_id", ""),
        "COLLECTION_NAME": os.environ.get("COLLECTION_NAME", "Für dich empfohlen"),
        "TOP_N": os.environ.get("TOP_N", "20"),
        "RECENCY_HALF_LIFE_DAYS": os.environ.get("RECENCY_HALF_LIFE_DAYS", "180"),
        "REQUEST_TIMEOUT_SECONDS": os.environ.get("REQUEST_TIMEOUT_SECONDS", "120"),
        "PAGE_SIZE": os.environ.get("PAGE_SIZE", "100"),
        # Das Intervall steuert der Server-Worker, nicht das Standalone-Script.
        "RUN_INTERVAL_SECONDS": "0",
    }
    return JellyfinRecommenderConfig.from_env(env)


def _run_recommender_once() -> bool:
    try:
        config = _build_recommender_config()
    except JellyfinRecommenderConfigurationError as exc:
        logger.info("Jellyfin-Empfehlungen übersprungen: %s", exc)
        return False

    try:
        recommendations = run_jellyfin_recommender_once(
            config,
            profile_callback=state.taste_profile.replace_jellyfin_items,
        )
    except JellyfinRecommenderError as exc:
        logger.warning("Jellyfin-Empfehlungen fehlgeschlagen: %s", exc)
        return False
    except Exception:
        logger.exception("Unerwarteter Fehler bei den Jellyfin-Empfehlungen")
        return False

    logger.info(
        "Jellyfin-Empfehlungen aktualisiert: %d Eintrag/Einträge",
        len(recommendations),
    )
    return True


def _recommender_interval_seconds() -> int:
    raw = os.environ.get("RECOMMENDER_INTERVAL_SECONDS", "86400").strip()
    try:
        interval = int(raw)
    except ValueError:
        logger.warning(
            "RECOMMENDER_INTERVAL_SECONDS=%r ist ungültig; nutze 86400", raw,
        )
        return 86400
    if interval < 60:
        logger.warning("RECOMMENDER_INTERVAL_SECONDS muss mindestens 60 sein; nutze 60")
        return 60
    return interval


def jellyfin_recommender_loop() -> None:
    while not _recommender_stop_event.is_set():
        successful = _run_recommender_once()
        regular_interval = _recommender_interval_seconds()
        interval = regular_interval if successful else min(regular_interval, 900)
        logger.info("Nächster Jellyfin-Empfehlungslauf in %d Sekunden", interval)
        _recommender_wake_event.wait(interval)
        _recommender_wake_event.clear()


def stop_jellyfin_recommender() -> None:
    _recommender_stop_event.set()
    _recommender_wake_event.set()
    thread = _recommender_thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=5)


def _set_runtime_jellyfin_config(cfg: dict) -> None:
    """Wechselt Konfiguration und Cache als eine atomare Generation."""
    normalized_cfg = dict(cfg)
    normalized_cfg["cleanup_default"] = normalize_cleanup_mode(
        normalized_cfg.get("cleanup_default")
    )
    with state.jellyfin_cache_lock:
        state.jellyfin_cfg = normalized_cfg
        state.jellyfin_config_generation += 1
        state.jellyfin_movie_data_generation += 1
        state.jellyfin_episode_data_generation += 1
        state.jellyfin_library = None
        state.jellyfin_library_time = 0.0
        state.jellyfin_library_available = False
        state.jellyfin_library_retry_after = 0.0
        state.jellyfin_episodes = None
        state.jellyfin_episodes_time = 0.0
        state.jellyfin_episodes_available = False
        state.jellyfin_episodes_retry_after = 0.0
        state.jellyfin_series = None
        state.jellyfin_series_time = 0.0
        state.jellyfin_series_available = False
        state.jellyfin_series_retry_after = 0.0
        state.jellyfin_targeted_episodes.clear()
        state.jellyfin_user_episodes = None
        state.jellyfin_user_episodes_time = 0.0
        state.jellyfin_user_episodes_available = False
        state.jellyfin_user_episodes_retry_after = 0.0
        with state.watchlist_lock:
            for entry in state.watchlist:
                entry["check_generation"] = int(entry.get("check_generation", 0)) + 1
                entry["last_error"] = "Jellyfin-Konfiguration wird geprüft"


def get_tmdb_client() -> TMDBClient:
    return state.tmdb_client


def get_tmdb_series(title: str, tmdb_id="", force: bool = False) -> Optional[dict]:
    """Eine gespeicherte TMDB-ID bleibt autoritativ; Titelsuche nur initial."""
    client = get_tmdb_client()
    if tmdb_id:
        return client.series_by_id(tmdb_id, title, force=force)
    return client.series(title, force=force)


def _unreleased_episode_keys(
    tmdb_id, keys: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """(Staffel, Episode)-Paare aus ``keys``, die laut TMDB-Ausstrahlungsdatum
    noch nicht erschienen sind oder unbekannt sind.

    Liefert eine leere Menge, wenn TMDB nicht konfiguriert ist oder keine
    Staffeldaten liefert (fail-open: dann bleibt das bisherige Verhalten
    unverändert, statt fälschlich alles zu sperren).
    """
    client = get_tmdb_client()
    if not client.configured or not tmdb_id or not keys:
        return set()
    today = time.strftime("%Y-%m-%d", time.localtime())
    unreleased: set[tuple[int, int]] = set()
    for season_number in {season for season, _episode in keys}:
        air_dates = client.season_air_dates(tmdb_id, season_number)
        if air_dates is None:
            continue
        for season, episode in keys:
            if season != season_number:
                continue
            air_date = air_dates.get(episode)
            if not air_date or air_date > today:
                unreleased.add((season, episode))
    return unreleased


def _unreleased_episode_slugs(series: FilmpalastSeries, tmdb_id) -> set[str]:
    """Episoden, die laut TMDB-Ausstrahlungsdatum noch nicht erschienen sind.

    Providerunabhängig, da manche Anbieter geplante Episoden schon vor dem
    eigentlichen Release listen.
    """
    by_key = {
        (ep.season, ep.episode): ep.slug
        for season_number in series.season_numbers
        for ep in series.seasons.get(season_number, [])
    }
    unreleased_keys = _unreleased_episode_keys(tmdb_id, set(by_key))
    return {by_key[key] for key in unreleased_keys}


JELLYFIN_CACHE_TTL = 300  # Sekunden – wie lange die komplette Filmliste gecacht wird
JELLYFIN_ERROR_RETRY_SECONDS = 30
JELLYFIN_TARGETED_CACHE_TTL = 60
JELLYFIN_TARGETED_ERROR_RETRY_SECONDS = 15


def get_jellyfin_library(force: bool = False) -> Optional[List[dict]]:
    """Liefert alle Filme aus Jellyfin (gecacht), damit auch Neu/Top/Genre-Listen
    ohne einen Live-Request pro Aufruf auf Duplikate geprüft werden können."""
    with state.jellyfin_library_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_library is None
                or (now - state.jellyfin_library_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured:
                return None
            if not force and now < state.jellyfin_library_retry_after:
                return state.jellyfin_library
            needs_fetch = needs_fetch or not state.jellyfin_library_available
            if not needs_fetch:
                return state.jellyfin_library
            state.jellyfin_movie_data_generation += 1
        fresh = jf_client.list_movies()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_library
            state.jellyfin_movie_data_generation += 1
            if fresh is not None:
                state.jellyfin_library = fresh
                state.jellyfin_library_time = time.time()
                state.jellyfin_library_available = True
                state.jellyfin_library_retry_after = 0.0
            else:
                state.jellyfin_library_available = False
                state.jellyfin_library_retry_after = time.time() + JELLYFIN_ERROR_RETRY_SECONDS
            return state.jellyfin_library


def get_jellyfin_episodes(force: bool = False) -> Optional[List[dict]]:
    """Liefert alle Serien-Episoden aus Jellyfin (gecacht) – damit die
    Watchlist-Prüfung weiß, ob eine neu gescrapete Episode tatsächlich
    noch fehlt oder bereits in der Bibliothek liegt."""
    with state.jellyfin_episodes_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_episodes is None
                or (now - state.jellyfin_episodes_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured:
                return None
            if not force and now < state.jellyfin_episodes_retry_after:
                return state.jellyfin_episodes
            needs_fetch = needs_fetch or not state.jellyfin_episodes_available
            if not needs_fetch:
                return state.jellyfin_episodes
            state.jellyfin_episode_data_generation += 1
        fresh = jf_client.list_episodes()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_episodes
            state.jellyfin_episode_data_generation += 1
            if fresh is not None:
                state.jellyfin_episodes = fresh
                state.jellyfin_episodes_time = time.time()
                state.jellyfin_episodes_available = True
                state.jellyfin_episodes_retry_after = 0.0
            else:
                state.jellyfin_episodes_available = False
                state.jellyfin_episodes_retry_after = time.time() + JELLYFIN_ERROR_RETRY_SECONDS
            return state.jellyfin_episodes


def get_jellyfin_series(force: bool = False) -> Optional[List[dict]]:
    """Liefert Jellyfin-Serien inklusive Provider-IDs für stabiles Matching."""
    with state.jellyfin_series_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_series is None
                or (now - state.jellyfin_series_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured:
                return None
            if not force and now < state.jellyfin_series_retry_after:
                return state.jellyfin_series
            needs_fetch = needs_fetch or not state.jellyfin_series_available
            if not needs_fetch:
                return state.jellyfin_series
            state.jellyfin_episode_data_generation += 1
        fresh = jf_client.list_series()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_series
            state.jellyfin_episode_data_generation += 1
            if fresh is not None:
                state.jellyfin_series = fresh
                state.jellyfin_series_time = time.time()
                state.jellyfin_series_available = True
                state.jellyfin_series_retry_after = 0.0
            else:
                state.jellyfin_series_available = False
                state.jellyfin_series_retry_after = time.time() + JELLYFIN_ERROR_RETRY_SECONDS
            return state.jellyfin_series


def get_jellyfin_targeted_episodes(
    series_ids: set[str], force: bool = False,
) -> tuple[Optional[List[dict]], bool, bool, float]:
    """Liefert Episoden nur für die eindeutig erkannte Jellyfin-Serie.

    Rückgabe: ``(items, live_available, stale, checked_at)``. Bei einem
    Netzwerkfehler bleibt ein letzter bekannter Stand sichtbar, wird aber als
    veraltet markiert und darf keine Downloadfreigabe vortäuschen.
    """
    clean_ids = tuple(sorted({str(value).strip() for value in series_ids if str(value).strip()}))
    if not clean_ids:
        return [], True, False, time.time()
    key = "|".join(clean_ids)

    def cached_result(now: float, allow_stale: bool = False):
        record = state.jellyfin_targeted_episodes.get(key)
        if not record:
            return None
        age = now - float(record.get("checked_at") or 0)
        if not force and age <= JELLYFIN_TARGETED_CACHE_TTL:
            return list(record.get("items") or []), True, False, float(record["checked_at"])
        if not force and now < float(record.get("retry_after") or 0):
            return (
                list(record.get("items") or []), False, True,
                float(record.get("checked_at") or 0),
            )
        if allow_stale:
            return (
                list(record.get("items") or []), False, True,
                float(record.get("checked_at") or 0),
            )
        return None

    with state.jellyfin_cache_lock:
        jf_client = get_jellyfin_client()
        generation = state.jellyfin_config_generation
        if not jf_client.configured:
            return None, False, False, 0.0
        cached = cached_result(time.time())
        if cached is not None:
            return cached

    with state.jellyfin_targeted_fetch_lock:
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return None, False, False, 0.0
            cached = cached_result(time.time())
            if cached is not None:
                return cached
        fresh: List[dict] = []
        succeeded = True
        for series_id in clean_ids:
            items = jf_client.list_episodes_for_series(series_id)
            if items is None:
                succeeded = False
                break
            fresh.extend(items)
        now = time.time()
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return None, False, False, 0.0
            if succeeded:
                state.jellyfin_targeted_episodes[key] = {
                    "items": fresh,
                    "checked_at": now,
                    "retry_after": 0.0,
                }
                return list(fresh), True, False, now
            previous = state.jellyfin_targeted_episodes.get(key)
            if previous:
                previous["retry_after"] = now + JELLYFIN_TARGETED_ERROR_RETRY_SECONDS
                return cached_result(now, allow_stale=True)
            return None, False, False, 0.0


def _series_jellyfin_status(
    title: str,
    *,
    tmdb_id="",
    aliases=(),
    episodes: List[dict],
    force: bool = False,
) -> dict:
    """Schneller, eigenständiger Jellyfin-Status einer geöffneten Serie."""
    client = get_jellyfin_client()
    empty = {str(item.get("slug") or ""): False for item in episodes if item.get("slug")}
    if not client.configured:
        return {
            "configured": False, "available": True, "stale": False,
            "checked_at": 0.0, "episodes": empty, "count": 0,
        }
    series_items = get_jellyfin_series(force=force)
    with state.jellyfin_cache_lock:
        series_index_available = bool(
            series_items is not None and state.jellyfin_series_available
        )
    if not series_index_available:
        return {
            "configured": True, "available": False, "stale": False,
            "checked_at": 0.0, "episodes": empty, "count": 0,
        }
    series_ids = client.series_ids_for(
        title, tmdb_id=tmdb_id, aliases=aliases, items=series_items,
    )
    if series_ids is None:
        return {
            "configured": True, "available": False, "stale": False,
            "checked_at": time.time(), "episodes": empty, "count": 0,
        }
    targeted, live_available, stale, checked_at = get_jellyfin_targeted_episodes(
        series_ids, force=force,
    )
    existing = (
        client.episodes_for_series(
            title, items=targeted, aliases=aliases, series_ids=series_ids,
        )
        if targeted is not None else set()
    )
    statuses = {
        str(item.get("slug") or ""): (
            int(item.get("season") or 0), int(item.get("episode") or 0)
        ) in existing
        for item in episodes if item.get("slug")
    }
    return {
        "configured": True,
        "available": live_available,
        "stale": stale,
        "checked_at": checked_at,
        "episodes": statuses,
        "count": sum(statuses.values()),
    }


def get_jellyfin_user_episodes(force: bool = False) -> Optional[List[dict]]:
    """Liefert Episoden mit Gesehen-Status des konfigurierten Benutzers."""
    with state.jellyfin_user_fetch_lock:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            user_id = state.jellyfin_cfg.get("user_id", "").strip()
            now = time.time()
            needs_fetch = (
                force
                or state.jellyfin_user_episodes is None
                or (now - state.jellyfin_user_episodes_time) > JELLYFIN_CACHE_TTL
            )
            if not jf_client.configured or not user_id:
                return None
            if not force and now < state.jellyfin_user_episodes_retry_after:
                return state.jellyfin_user_episodes
            needs_fetch = needs_fetch or not state.jellyfin_user_episodes_available
            if not needs_fetch:
                return state.jellyfin_user_episodes
            state.jellyfin_episode_data_generation += 1
        items = jf_client.list_episodes_with_user_data(user_id)
        with state.jellyfin_cache_lock:
            if generation != state.jellyfin_config_generation:
                return state.jellyfin_user_episodes
            state.jellyfin_episode_data_generation += 1
            if items is None:
                state.jellyfin_user_episodes_available = False
                state.jellyfin_user_episodes_retry_after = (
                    time.time() + JELLYFIN_ERROR_RETRY_SECONDS
                )
                return state.jellyfin_user_episodes
            state.jellyfin_user_episodes = items
            state.jellyfin_user_episodes_time = time.time()
            state.jellyfin_user_episodes_available = True
            state.jellyfin_user_episodes_retry_after = 0.0
            return state.jellyfin_user_episodes


def strip_source_suffix(title: str) -> str:
    """Entfernt die UI-Markierung ``[Anbieter]``."""
    return re.sub(r"\s*\[[^\]]+\]\s*$", "", title or "").strip()


def clean_movie_title(title: str) -> str:
    """Bereinigt Filmtitel für Anzeige, TMDB und Jellyfin.

    Quellseiten hängen teils Editionen oder Sprachmarker an, etwa
    ``(Black and Chrome Edition) [Moflix]`` oder ``ENGLISH\\Titel``.
    """
    value = " ".join(str(title or "").split()).strip()
    language = r"(?:ENGLISH|ENGLISCH|GERMAN|DEUTSCH|MULTI(?:LANGUAGE)?|OV|O-TON)"
    previous = None
    while value and value != previous:
        previous = value
        value = strip_source_suffix(value)
        value = re.sub(r"\s*\([^()]*\)\s*$", "", value).strip()
        value = re.sub(
            rf"^[\\/|:_-]*\s*{language}(?:\s+(?:DUB|SUB|DL))?"
            rf"\s*[\\/|:_-]+\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(
            rf"\s*[\\/|:_-]+\s*{language}(?:\s+(?:DUB|SUB|DL))?"
            rf"\s*[\\/|:_-]*\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        # Ein alleinstehender, großgeschriebener Release-Marker am Ende ist
        # ebenfalls kein Titelbestandteil. Normales „English Movie“ bleibt.
        value = re.sub(
            r"\s+(?:ENGLISH|ENGLISCH|GERMAN|DEUTSCH|MULTI|OV|O-TON)"
            r"(?:\s+(?:DUB|SUB|DL))?\s*$",
            "",
            value,
        ).strip()
    return value


def provider_order(media_type: str) -> List[str]:
    defaults = {
        "movies": appconfig.MOVIE_PROVIDER_DEFAULTS,
        "series": appconfig.SERIES_PROVIDER_DEFAULTS,
        "anime": appconfig.ANIME_PROVIDER_DEFAULTS,
    }.get(media_type, ())
    with state.provider_priority_lock:
        configured = state.provider_priorities.get(media_type, defaults)
        return appconfig.normalize_provider_order(configured, defaults)


def provider_priority(media_type: str) -> List[str]:
    """Aktive, sprachlich passende Quellen in Benutzer-Reihenfolge."""
    ordered = provider_order(media_type)
    with state.provider_priority_lock:
        configured = state.provider_enabled.get(media_type, ordered)
        enabled = set(appconfig.normalize_provider_selection(configured, ordered))
        languages = set(state.content_languages)
    matching = [
        provider
        for provider in ordered
        if provider_content_language(provider) in languages
    ]
    active = [provider for provider in matching if provider in enabled]
    if media_type == "anime":
        return active
    return active or matching[:1] or ordered[:1]


def provider_for_value(value: str) -> str:
    """Erkennt die Katalogquelle an den zentral hinterlegten Merkmalen."""
    return provider_for_source(value)


def _apply_provider_metadata(item, provider: str):
    """Ergänzt normalisierte Medienobjekte um Quelle und Standardsprache."""
    if item is None:
        return None
    key = str(provider or "").strip().casefold()
    if hasattr(item, "provider"):
        item.provider = key
    if hasattr(item, "content_language"):
        item.content_language = provider_content_language(key)
    return item


def _apply_provider_metadata_many(items, provider: str) -> list:
    return [
        _apply_provider_metadata(item, provider)
        for item in (items or [])
        if item is not None
    ]


def _movie_provider(movie: Optional[FilmpalastMovie], fallback: str = "") -> str:
    stored = str(getattr(movie, "provider", "") or "").strip().casefold()
    if stored in PROVIDER_CATALOG:
        return stored
    value = getattr(movie, "url", "") if movie is not None else fallback
    return provider_for_value(value or fallback)


def _movie_content_language(
    movie: Optional[FilmpalastMovie],
    hoster_language: str = "",
    fallback: str = "",
) -> str:
    explicit = normalize_content_language(hoster_language)
    if explicit:
        return explicit
    if movie is not None:
        stored = normalize_content_language(
            str(getattr(movie, "content_language", "") or "")
        )
        if stored:
            return stored
    return provider_content_language(_movie_provider(movie, fallback))


def _ordered_episode_sources(movies: List[FilmpalastMovie]) -> List[FilmpalastMovie]:
    positions = {provider: index for index, provider in enumerate(provider_priority("series"))}
    return sorted(
        movies,
        key=lambda movie: positions.get(provider_for_value(movie.url), len(positions)),
    )


def clean_genre(value: str) -> str:
    return " ".join(str(value or "").split())


def canonical_movie_genre(value: str) -> str:
    genre = clean_genre(value)
    return MOVIE_GENRE_CANONICAL_BY_KEY.get(genre.casefold(), genre)


def movie_genre_aliases(value: str) -> tuple[str, ...]:
    canonical = canonical_movie_genre(value)
    return MOVIE_GENRE_GROUPS.get(canonical, (canonical,))


def watchlist_lookup(base_slug: str) -> Optional[dict]:
    return next((w for w in state.watchlist if w["base_slug"] == base_slug), None)


def watchlist_match_series(
    base_slug: str, title: str = "", tmdb_id="", aliases=(),
) -> Optional[dict]:
    """Ordnet dieselbe Serie providerübergreifend ihrer Watchlist zu."""
    exact = watchlist_lookup(base_slug)
    if exact is not None:
        return exact
    wanted_tmdb = str(tmdb_id or "").strip()
    if wanted_tmdb:
        tmdb_matches = [
            entry for entry in state.watchlist
            if str(entry.get("tmdb_id") or "").strip() == wanted_tmdb
        ]
        if len(tmdb_matches) == 1:
            return tmdb_matches[0]
    wanted_titles = {
        _norm_title(value) for value in (title, *aliases) if _norm_title(value)
    }
    if not wanted_titles:
        return None
    title_matches = []
    for entry in state.watchlist:
        stored_tmdb = str(entry.get("tmdb_id") or "").strip()
        if wanted_tmdb and stored_tmdb and stored_tmdb != wanted_tmdb:
            continue
        stored_titles = {
            _norm_title(value)
            for value in (entry.get("title", ""), *(entry.get("aliases") or []))
            if _norm_title(value)
        }
        if wanted_titles & stored_titles:
            title_matches.append(entry)
    return title_matches[0] if len(title_matches) == 1 else None


def load_movie_for_slug(slug: str) -> Optional[FilmpalastMovie]:
    if re.fullmatch(r"tmdb:\d+", slug or "", flags=re.IGNORECASE):
        sources = resolve_tmdb_movie_sources(slug.split(":", 1)[1])
        return sources[0] if sources else None
    provider = provider_for_value(slug)
    if slug.startswith(FILMFREI24_PREFIX):
        movie = FilmFrei24Scraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(SERIENSTREAM_PREFIX):
        if not state.provider_health.request_allowed("serienstream"):
            raise RuntimeError("SerienStream befindet sich im Provider-Cooldown")
        with state.sto_lock:
            try:
                movie = get_sto_scraper().get_movie(slug)
            except ProviderBlockedError as exc:
                _mark_serienstream_blocked(exc.reason, str(exc))
                raise
    elif slug.startswith(MOFLIX_PREFIX):
        with state.moflix_lock:
            movie = get_moflix_scraper().get_movie(slug)
    elif slug.startswith((HUHU_PREFIX, HUHU_MOVIE_PREFIX)):
        with state.huhu_lock:
            movie = get_huhu_scraper().get_movie(slug)
    elif slug.startswith(EINSCHALTEN_PREFIX):
        movie = EinschaltenScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(KINOX_PREFIX):
        movie = KinoxScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(KINOGER_PREFIX):
        movie = KinogerScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(MEGAKINO_PREFIX):
        movie = MegaKinoScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(XCINE_PREFIX):
        movie = XcineScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(SFLIX_PREFIX):
        movie = SflixScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(RIDOMOVIES_PREFIX):
        movie = RidomoviesScraper(progress_cb=log).get_movie(slug)
    elif slug.startswith(MKISSA_PREFIX):
        with state.mkissa_lock:
            movie = get_mkissa_scraper().get_episode(slug)
    else:
        if slug.lower().startswith(("http://", "https://")):
            host = (urlparse(slug).hostname or "").casefold()
            if host != "filmpalast.to" and not host.endswith(".filmpalast.to"):
                raise ValueError("Direkte URLs sind nur für Filmpalast erlaubt.")
        scraper = get_fp_scraper()
        with state.fp_lock:
            movie = scraper.get_movie(slug)
    return _apply_provider_metadata(movie, provider)


def search_movie_candidates(query: str) -> List[FilmpalastSearchResult]:
    """Durchsucht alle Filmanbieter; gemeinsame Basis für Web und Telegram."""
    q = query.strip()
    if not q:
        return []
    def _fp():
        with state.fp_lock:
            return list(get_fp_scraper().search(q))

    def _huhu():
        with state.huhu_lock:
            return list(get_huhu_scraper().search(q))

    searches = {
        "filmfrei24": lambda: FilmFrei24Scraper(progress_cb=log).search(q),
        "filmpalast": _fp,
        "huhu": _huhu,
        "moflix": lambda: MoflixScraper(progress_cb=log).search(q),
        "einschalten": lambda: EinschaltenScraper(progress_cb=log).search(q),
        "kinox": lambda: KinoxScraper(progress_cb=log).search(q),
        "kinoger": lambda: KinogerScraper(progress_cb=log).search(q),
        "megakino": lambda: MegaKinoScraper(progress_cb=log).search(q),
        "xcine": lambda: XcineScraper(progress_cb=log).search(q),
        "sflix": lambda: SflixScraper(progress_cb=log).search(q),
        "ridomovies": lambda: RidomoviesScraper(progress_cb=log).search(q),
    }
    tasks = [
        (key, PROVIDER_LABELS[key], searches[key])
        for key in provider_priority("movies")
    ]
    results: List[FilmpalastSearchResult] = []
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [(key, name, pool.submit(fn)) for key, name, fn in tasks]
        for key, name, future in futures:
            try:
                results.extend(_apply_provider_metadata_many(future.result(), key))
            except Exception as exc:
                log(f"{name} Suche übersprungen: {exc}", "warn")
    return results


def _tmdb_search_results(query: str) -> List[dict]:
    """Formatiert TMDB-Treffer als providerunabhängige Filmkarten."""
    movies = get_tmdb_client().search_movies(
        query, max_results=TMDB_MOVIE_SEARCH_MAX_RESULTS,
    )
    return [
        {
            **movie,
            "slug": f"tmdb:{movie['tmdb_id']}",
            "url": f"https://www.themoviedb.org/movie/{movie['tmdb_id']}",
            "is_movie": True,
            "provider": "",
            "content_language": "",
        }
        for movie in movies
    ]


def _movie_title_match_keys(title: str) -> set[str]:
    raw = re.sub(
        r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$",
        "",
        clean_movie_title(title),
    ).strip()
    def _match_norm(value: str) -> str:
        ascii_value = (
            unicodedata.normalize("NFKD", value or "")
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())

    keys = {_match_norm(raw)}
    roman_to_number = {
        "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
        "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
    }
    match = re.search(r"\b(i{1,3}|iv|v|vi{0,3}|ix|x|\d{1,2})$", raw, re.IGNORECASE)
    if match:
        suffix = match.group(1).casefold()
        replacement = roman_to_number.get(suffix)
        if replacement:
            keys.add(_match_norm(raw[:match.start()] + replacement))
        elif suffix.isdigit():
            number_to_roman = {value: key for key, value in roman_to_number.items()}
            roman = number_to_roman.get(str(int(suffix)))
            if roman:
                keys.add(_match_norm(raw[:match.start()] + roman))
    keys.discard("")
    return keys


def _movie_matches_tmdb_choice(
    title: str,
    year: str,
    aliases: set[str],
    wanted_year: str,
) -> bool:
    if not (_movie_title_match_keys(title) & aliases):
        return False
    candidate_year = str(year or "").strip()
    return not (wanted_year and candidate_year and candidate_year != wanted_year)


def resolve_tmdb_movie_sources(tmdb_id) -> List[FilmpalastMovie]:
    """Sucht einen gewählten TMDB-Film bei allen aktiven Filmquellen.

    Das Ergebnis bleibt ein logischer Inhalt. Die erste Quelle folgt der
    Nutzerpriorität; jede weitere Quelle wird als echter Download-Fallback
    gespeichert und später automatisch durchprobiert.
    """
    key = str(tmdb_id or "").strip()
    if not key.isdigit():
        raise ValueError("Ungültige TMDB-Film-ID.")
    virtual_slug = f"tmdb:{int(key)}"
    with state.movie_source_cache_lock:
        cached = state.movie_source_cache.get(virtual_slug)
        if cached:
            return list(cached)

    tmdb = get_tmdb_client().movie_by_id(key)
    if not tmdb:
        raise LookupError("Der gewählte TMDB-Film ist nicht verfügbar.")
    search_titles = []
    for value in (tmdb.get("title"), tmdb.get("original_title")):
        value = " ".join(str(value or "").split()).strip()
        if value and _norm_title(value) not in {_norm_title(item) for item in search_titles}:
            search_titles.append(value)
    if not search_titles:
        raise LookupError("TMDB liefert keinen suchbaren Filmtitel.")

    aliases = {
        key
        for title in search_titles
        for key in _movie_title_match_keys(title)
    }
    wanted_year = str(tmdb.get("year") or "").strip()
    candidates: List[FilmpalastSearchResult] = []
    seen_candidates: set[str] = set()
    provider_candidate_counts: Counter = Counter()
    for search_title in search_titles:
        for candidate in search_movie_candidates(search_title):
            provider = str(candidate.provider or provider_for_value(candidate.slug)).casefold()
            if provider_candidate_counts[provider] >= 3 or candidate.slug in seen_candidates:
                continue
            if not candidate.is_movie or not _movie_matches_tmdb_choice(
                candidate.title, candidate.year, aliases, wanted_year,
            ):
                continue
            seen_candidates.add(candidate.slug)
            candidates.append(candidate)
            provider_candidate_counts[provider] += 1

    def _load(candidate: FilmpalastSearchResult):
        try:
            loaded = state.fp_movies.get(candidate.slug) or load_movie_for_slug(candidate.slug)
        except Exception as exc:
            log(f"Filmquelle {candidate.title} nicht ladbar: {exc}", "warn")
            return None
        if not loaded or not loaded.hosters:
            return None
        if not _movie_matches_tmdb_choice(
            loaded.title, loaded.year or candidate.year, aliases, wanted_year,
        ):
            return None
        state.fp_movies[candidate.slug] = loaded
        return loaded

    loaded_sources: List[FilmpalastMovie] = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            loaded_sources = [
                movie for movie in pool.map(_load, candidates)
                if movie is not None
            ]

    positions = {
        provider: index for index, provider in enumerate(provider_priority("movies"))
    }
    loaded_sources.sort(
        key=lambda movie: positions.get(_movie_provider(movie), len(positions)),
    )
    unique_sources: List[FilmpalastMovie] = []
    seen_providers: set[str] = set()
    for movie in loaded_sources:
        provider = _movie_provider(movie)
        if provider in seen_providers:
            continue
        seen_providers.add(provider)
        unique_sources.append(movie)
    if not unique_sources:
        raise LookupError(
            f"«{tmdb.get('title') or search_titles[0]}» wurde bei keinem aktiven Anbieter gefunden."
        )

    primary = replace(
        unique_sources[0],
        title=tmdb.get("title") or unique_sources[0].title,
        year=wanted_year or unique_sources[0].year,
        runtime=tmdb.get("runtime") or unique_sources[0].runtime,
        cover_url=tmdb.get("cover_url") or unique_sources[0].cover_url,
        description=tmdb.get("description") or unique_sources[0].description,
        genres=tmdb.get("genres") or unique_sources[0].genres,
    )
    sources = [primary, *unique_sources[1:]]
    with state.movie_source_cache_lock:
        existing = state.movie_source_cache.get(virtual_slug)
        if existing:
            return list(existing)
        state.movie_source_cache[virtual_slug] = list(sources)
        state.fp_movies[virtual_slug] = primary
    log(
        f"TMDB-Film «{primary.title}»: {len(sources)} Anbieterquelle(n) gebündelt."
    )
    return sources


class MovieCatalogColdLoadLimit(RuntimeError):
    """Verhindert teure Sprünge über viele noch ungecachte Quellseiten."""


def _cached_movie_provider_page(cache_key: tuple) -> Optional[List[FilmpalastSearchResult]]:
    with state.movie_list_cache_lock:
        cached = state.movie_list_cache.get(cache_key)
        ttl = cached[2] if cached and len(cached) > 2 else MOVIE_LIST_CACHE_TTL
        if cached and time.time() - cached[0] < ttl:
            return list(cached[1])
        if cached:
            state.movie_list_cache.pop(cache_key, None)
    return None


def _cache_movie_provider_page(
    cache_key: tuple,
    results: List[FilmpalastSearchResult],
    ttl: int = MOVIE_LIST_CACHE_TTL,
) -> None:
    now = time.time()
    with state.movie_list_cache_lock:
        expired = [
            key for key, cached in state.movie_list_cache.items()
            if now - cached[0] >= (
                cached[2] if len(cached) > 2 else MOVIE_LIST_CACHE_TTL
            )
        ]
        for key in expired:
            state.movie_list_cache.pop(key, None)
        while len(state.movie_list_cache) >= MOVIE_LIST_CACHE_MAX_ENTRIES:
            oldest = min(state.movie_list_cache, key=lambda key: state.movie_list_cache[key][0])
            state.movie_list_cache.pop(oldest, None)
        state.movie_list_cache[cache_key] = (now, list(results), ttl)


def _fetch_movie_provider_page(
    provider: str,
    mode: str,
    genre: str,
    source_page: int,
) -> List[FilmpalastSearchResult]:
    """Lädt genau eine Quellseite; nur markierte Anbieter paginieren."""
    if provider not in MOVIE_PAGINATED_PROVIDERS and source_page != 1:
        return []
    provider_genre = _movie_genre_for_provider(provider, genre) if mode == "genre" else genre

    if provider == "filmpalast":
        with state.fp_lock:
            scraper = get_fp_scraper()
            if mode == "genre":
                results = scraper.list_by_genre(provider_genre, source_page)
            else:
                results = scraper.list_movies(mode, source_page)
        return _apply_provider_metadata_many(results, provider)

    if provider == "huhu":
        with state.huhu_lock:
            scraper = get_huhu_scraper()
            results = (
                scraper.list_by_genre(provider_genre, source_page)
                if mode == "genre"
                else scraper.list_movies(mode, source_page)
            )
        return _apply_provider_metadata_many(results, provider)

    scraper_classes = {
        "filmfrei24": FilmFrei24Scraper,
        "moflix": MoflixScraper,
        "einschalten": EinschaltenScraper,
        "kinox": KinoxScraper,
        "kinoger": KinogerScraper,
        "megakino": MegaKinoScraper,
        "xcine": XcineScraper,
        "sflix": SflixScraper,
        "ridomovies": RidomoviesScraper,
    }
    scraper_class = scraper_classes.get(provider)
    if scraper_class is None:
        return []
    scraper = scraper_class(progress_cb=log)
    if mode == "genre":
        results = scraper.list_by_genre(provider_genre, source_page)
    else:
        results = scraper.list_movies(mode, source_page)
    return _apply_provider_metadata_many(results, provider)


def _load_movie_provider_pages(
    mode: str,
    genre: str,
    requests_to_load: List[tuple[str, int]],
    cold_wave_budget: Optional[List[int]] = None,
) -> Dict[tuple[str, int], List[FilmpalastSearchResult]]:
    """Lädt mehrere Quellseiten parallel und cached sie unabhängig voneinander."""
    loaded: Dict[tuple[str, int], List[FilmpalastSearchResult]] = {}
    missing: List[tuple[str, int, tuple]] = []
    genre_key = clean_genre(genre).casefold()

    for provider, source_page in dict.fromkeys(requests_to_load):
        cache_key = ("provider", mode, genre_key, provider, int(source_page))
        cached = _cached_movie_provider_page(cache_key)
        if cached is None:
            missing.append((provider, source_page, cache_key))
        else:
            loaded[(provider, source_page)] = cached

    if not missing:
        return loaded
    if cold_wave_budget is not None:
        if cold_wave_budget[0] <= 0:
            raise MovieCatalogColdLoadLimit(
                "Dieser Katalogabschnitt wird noch vorbereitet. Bitte kurz warten und erneut versuchen."
            )
        cold_wave_budget[0] -= 1

    with ThreadPoolExecutor(max_workers=min(len(missing), len(PROVIDER_LABELS))) as pool:
        futures = [
            (
                provider,
                source_page,
                cache_key,
                pool.submit(_fetch_movie_provider_page, provider, mode, genre, source_page),
            )
            for provider, source_page, cache_key in missing
        ]
        for provider, source_page, cache_key, future in futures:
            try:
                results = list(future.result())
            except Exception as exc:
                label = PROVIDER_LABELS.get(provider, provider)
                log(f"{label} Liste (Quellseite {source_page}) übersprungen: {exc}", "warn")
                results = []
                _cache_movie_provider_page(
                    cache_key, results, ttl=MOVIE_LIST_FAILURE_CACHE_TTL,
                )
            else:
                _cache_movie_provider_page(cache_key, results)
            loaded[(provider, source_page)] = results
    return loaded


def _movie_provider_genres(provider: str) -> set:
    return {
        "filmfrei24": state.filmfrei24_provider_genres,
        "filmpalast": state.fp_provider_genres,
        "huhu": state.huhu_provider_genres,
        "moflix": state.moflix_provider_genres,
        "einschalten": state.einschalten_provider_genres,
        "kinox": state.kinox_provider_genres,
        "kinoger": state.kinoger_provider_genres,
        "megakino": state.megakino_provider_genres,
        "xcine": state.xcine_provider_genres,
        "sflix": state.sflix_provider_genres,
        "ridomovies": state.ridomovies_provider_genres,
    }.get(provider, set())


def _movie_genre_for_provider(provider: str, genre: str) -> str:
    known_by_key = {
        clean_genre(item).casefold(): clean_genre(item)
        for item in _movie_provider_genres(provider)
    }
    for alias in movie_genre_aliases(genre):
        match = known_by_key.get(alias.casefold())
        if match:
            return match
    return clean_genre(genre)


def _provider_supports_movie_genre(provider: str, genre: str) -> bool:
    known_genres = _movie_provider_genres(provider)
    # Vor dem ersten Genre-Abruf sind die Mengen leer. Dann optimistisch laden;
    # der jeweilige Scraper kann ein unbekanntes Genre günstig mit [] ablehnen.
    if not known_genres:
        return True
    known_keys = {clean_genre(item).casefold() for item in known_genres}
    return any(alias.casefold() in known_keys for alias in movie_genre_aliases(genre))


def _movie_result_identity(
    result: FilmpalastSearchResult,
    provider: str,
    years_by_title: Dict[str, set[str]],
) -> tuple:
    title_key = _norm_title(clean_movie_title(result.title))
    if not title_key:
        return ("source", provider, str(result.slug or result.url))
    year = str(result.year or "").strip()
    known_years = years_by_title.get(title_key, set())
    # Fehlt bei nur einer Quelle das Jahr, kann sie sicher dem einzigen bekannten
    # Jahr zugeordnet werden. Bei Remakes bleiben jahrlose Treffer separat.
    if not year and len(known_years) == 1:
        year = next(iter(known_years))
    return ("movie", title_key, year)


def _mix_movie_provider_results(
    provider_results: Dict[str, List[FilmpalastSearchResult]],
    priority: List[str],
    claimed_identities: Optional[set[tuple]] = None,
) -> List[tuple[str, FilmpalastSearchResult]]:
    """Dedupliziert eine Quellwelle und mischt sie fair im Round-Robin."""
    years_by_title: Dict[str, set[str]] = defaultdict(set)
    for results in provider_results.values():
        for result in results:
            title_key = _norm_title(clean_movie_title(result.title))
            year = str(result.year or "").strip()
            if title_key and year:
                years_by_title[title_key].add(year)

    filtered: Dict[str, List[FilmpalastSearchResult]] = {provider: [] for provider in priority}
    seen_identities = claimed_identities if claimed_identities is not None else set()
    for provider in priority:
        for result in provider_results.get(provider, []):
            identity = _movie_result_identity(result, provider, years_by_title)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            filtered[provider].append(result)

    mixed: List[tuple[str, FilmpalastSearchResult]] = []
    longest = max((len(results) for results in filtered.values()), default=0)
    for index in range(longest):
        for provider in priority:
            results = filtered[provider]
            if index < len(results):
                mixed.append((provider, results[index]))
    return mixed


def movie_catalog_page(mode: str, page: int = 1, genre: str = "") -> dict:
    """Erzeugt eine stabile globale 32er-Seite aus allen Filmkatalogen.

    Einseitige Anbieter speisen ihren gesamten Startbestand in die globalen
    Seiten ein. Weitere Quellseiten werden jeweils als abgeschlossene Welle
    gemischt und nur hinten angehängt, damit frühere Seitengrenzen stabil bleiben.
    """
    page = max(1, min(int(page), MOVIE_MAX_GLOBAL_PAGE))
    mode = "genre" if mode == "genre" else mode if mode in {"new", "top"} else "new"
    genre = canonical_movie_genre(genre)
    priority = provider_priority("movies")
    active = [
        provider for provider in priority
        if mode != "genre" or _provider_supports_movie_genre(provider, genre)
    ]
    provider_seen: Dict[str, set[str]] = {provider: set() for provider in priority}

    def unique_page(
        provider: str,
        results: List[FilmpalastSearchResult],
    ) -> List[FilmpalastSearchResult]:
        unique: List[FilmpalastSearchResult] = []
        for result in results:
            source_key = str(result.slug or result.url or result.title or "").strip()
            key = f"{source_key}\0{str(result.year or '').strip()}"
            if key in provider_seen[provider]:
                continue
            provider_seen[provider].add(key)
            unique.append(result)
        return unique

    cold_wave_budget = [MOVIE_MAX_COLD_WAVES_PER_REQUEST]
    first_pages = _load_movie_provider_pages(
        mode, genre, [(provider, 1) for provider in active], cold_wave_budget,
    )
    first_wave = {
        provider: unique_page(provider, first_pages.get((provider, 1), []))
        for provider in active
    }
    # Priorität entscheidet innerhalb derselben Quellwelle. Bereits katalogisierte
    # Filme werden von späteren Wellen nicht ersetzt; sonst würden Seiten springen.
    claimed_identities: set[tuple] = set()
    catalog_entries = _mix_movie_provider_results(
        first_wave, priority, claimed_identities,
    )

    paginated = [provider for provider in active if provider in MOVIE_PAGINATED_PROVIDERS]
    exhausted = {provider for provider in paginated if not first_wave[provider]}
    duplicate_only_pages = {provider: 0 for provider in paginated}
    target_end = page * MOVIE_BROWSE_PAGE_SIZE
    next_source_page = 2
    has_more_unverified = False

    while len(catalog_entries) <= target_end and next_source_page <= MOVIE_MAX_SOURCE_PAGE:
        pending = [provider for provider in paginated if provider not in exhausted]
        if not pending:
            break
        try:
            next_pages = _load_movie_provider_pages(
                mode, genre, [(provider, next_source_page) for provider in pending],
                cold_wave_budget,
            )
        except MovieCatalogColdLoadLimit:
            if len(catalog_entries) < target_end:
                raise
            # Die angeforderte Seite ist vollständig. Der nächste Klick darf die
            # preiswerte Folgeseiten-Prüfung in einem neuen Request fortsetzen.
            has_more_unverified = True
            break
        wave: Dict[str, List[FilmpalastSearchResult]] = {}
        for provider in pending:
            results = next_pages.get((provider, next_source_page), [])
            wave[provider] = unique_page(provider, results)
            if not results:
                exhausted.add(provider)
            elif not wave[provider]:
                duplicate_only_pages[provider] += 1
                if duplicate_only_pages[provider] >= 2:
                    exhausted.add(provider)
            else:
                duplicate_only_pages[provider] = 0
        catalog_entries.extend(_mix_movie_provider_results(
            wave, priority, claimed_identities,
        ))
        next_source_page += 1

    start = (page - 1) * MOVIE_BROWSE_PAGE_SIZE
    page_entries = catalog_entries[start:target_end]
    source_counts = Counter(provider for provider, _result in page_entries)
    sources = [
        {
            "key": provider,
            "label": PROVIDER_LABELS[provider],
            "content_language": provider_content_language(provider),
            "language_label": PROVIDER_CATALOG[provider].language_label,
            "count": source_counts[provider],
        }
        for provider in priority
        if source_counts[provider]
    ]
    return {
        "results": [result for _provider, result in page_entries],
        "page": page,
        "has_more": page < MOVIE_MAX_GLOBAL_PAGE and (
            len(catalog_entries) > target_end or has_more_unverified
        ),
        "sources": sources,
    }


def list_movie_candidates(mode: str, page: int = 1) -> List[FilmpalastSearchResult]:
    """Kompatibler Listen-Zugriff auf die globale, gemischte Katalogseite."""
    return list(movie_catalog_page(mode, page)["results"])


def warm_home_movie_cache():
    """Bereitet Film- und Serien-Startansicht vor dem ersten Browser vor."""
    try:
        movies = list_movie_candidates("new", 1)
        tmdb = get_tmdb_client()
        if not tmdb.configured or not movies:
            return

        unique = {}
        for movie in movies:
            title = clean_movie_title(movie.title)
            unique.setdefault((_norm_title(title), str(movie.year or "")), (title, movie.year or ""))
        values = list(unique.values())
        # Das erste sichtbare Detail hat Vorrang. Erst danach den Rest mit
        # geringer Parallelität laden, damit die Startansicht nicht verhungert.
        tmdb.movie_summary(*values[0])
        remaining = values[1:]
        if remaining:
            with ThreadPoolExecutor(max_workers=min(3, len(remaining))) as pool:
                futures = [pool.submit(tmdb.movie_summary, title, year) for title, year in remaining]
                for future in futures:
                    try:
                        future.result()
                    except Exception as exc:
                        log(f"TMDB-Startcache: {exc}", "warn")
        log(f"Startansicht vorbereitet: {len(movies)} neue Filme.")
    except Exception as exc:
        log(f"Startansicht konnte nicht vorab geladen werden: {exc}", "warn")
    finally:
        warm_home_series_cache()


# --- Serienanbieter ----------------------------------------------------------
def _sto_get_series(value: str) -> Optional[FilmpalastSeries]:
    if not state.provider_health.request_allowed("serienstream"):
        raise RuntimeError("SerienStream befindet sich im Provider-Cooldown")
    with state.sto_lock:
        try:
            return get_sto_scraper().get_series(value)
        except ProviderBlockedError as exc:
            _mark_serienstream_blocked(exc.reason, str(exc))
            raise


def _sto_search_series(query: str) -> List[FilmpalastSeriesResult]:
    if not state.provider_health.request_allowed("serienstream"):
        raise RuntimeError("SerienStream befindet sich im Provider-Cooldown")
    with state.sto_lock:
        try:
            return get_sto_scraper().search_series(query)
        except ProviderBlockedError as exc:
            _mark_serienstream_blocked(exc.reason, str(exc))
            raise


def _search_series_for_provider(provider: str, query: str) -> List[FilmpalastSeriesResult]:
    if provider == "serienstream":
        return _sto_search_series(query)
    if provider == "filmpalast":
        with state.fp_lock:
            return get_fp_scraper().search_series(query)
    if provider == "moflix":
        with state.moflix_lock:
            return get_moflix_scraper().search_series(query)
    if provider == "huhu":
        with state.huhu_lock:
            return get_huhu_scraper().search_series(query)
    if provider == "kinoger":
        return KinogerScraper(progress_cb=log).search_series(query)
    if provider == "megakino":
        return MegaKinoScraper(progress_cb=log).search_series(query)
    if provider == "xcine":
        return XcineScraper(progress_cb=log).search_series(query)
    if provider == "sflix":
        return SflixScraper(progress_cb=log).search_series(query)
    if provider == "ridomovies":
        return RidomoviesScraper(progress_cb=log).search_series(query)
    return []


def _load_series_for_provider(provider: str, value: str) -> Optional[FilmpalastSeries]:
    if provider == "serienstream":
        return _sto_get_series(value)
    if provider == "filmpalast":
        with state.fp_lock:
            return get_fp_scraper().get_series(value)
    if provider == "moflix":
        with state.moflix_lock:
            return get_moflix_scraper().get_series(value)
    if provider == "huhu":
        with state.huhu_lock:
            return get_huhu_scraper().get_series(value)
    if provider == "kinoger":
        return KinogerScraper(progress_cb=log).get_series(value)
    if provider == "megakino":
        return MegaKinoScraper(progress_cb=log).get_series(value)
    if provider == "xcine":
        return XcineScraper(progress_cb=log).get_series(value)
    if provider == "sflix":
        return SflixScraper(progress_cb=log).get_series(value)
    if provider == "ridomovies":
        return RidomoviesScraper(progress_cb=log).get_series(value)
    return None


def _search_series_provider_results(
    query: str,
) -> Dict[str, List[FilmpalastSeriesResult]]:
    """Durchsucht alle Serienkataloge parallel und trennt die Treffer je Quelle."""
    q = query.strip()
    if not q:
        return {}
    priority = provider_priority("series")
    tasks = [
        (provider, lambda key=provider: _search_series_for_provider(key, q))
        for provider in priority
    ]
    provider_results: Dict[str, List[FilmpalastSeriesResult]] = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [(provider, pool.submit(fn)) for provider, fn in tasks]
        for provider, future in futures:
            try:
                provider_results[provider] = list(future.result())
            except Exception as exc:
                log(f"{PROVIDER_LABELS[provider]} Seriensuche übersprungen: {exc}", "warn")
                provider_results[provider] = []
    return provider_results


def search_series_candidates(query: str) -> List[FilmpalastSeriesResult]:
    """Durchsucht alle Serienkataloge und behält die konfigurierte Reihenfolge."""
    provider_results = _search_series_provider_results(query)
    results: List[FilmpalastSeriesResult] = []
    for provider in provider_priority("series"):
        results.extend(provider_results.get(provider, []))
    return results


@dataclass(frozen=True)
class _SeriesCatalogEntry:
    """Ein sichtbarer Serientreffer mit bevorzugter und alternativen Quellen."""

    provider: str
    result: FilmpalastSeriesResult
    providers: tuple[str, ...]


class SeriesCatalogColdLoadLimit(RuntimeError):
    """Verhindert teure Sprünge über viele noch ungecachte Serienseiten."""


def _series_result_identity(
    result: FilmpalastSeriesResult,
    provider: str,
    years_by_title: Dict[str, set[str]],
) -> tuple:
    title_key = _norm_title(strip_source_suffix(result.title))
    if not title_key:
        return ("source", provider, str(result.base_slug or result.sample_slug or result.sample_url))
    year = str(result.year or "").strip()
    known_years = years_by_title.get(title_key, set())
    if not year and len(known_years) == 1:
        year = next(iter(known_years))
    return ("series", title_key, year)


def _claim_series_identity(identity: tuple, claimed: set[tuple]) -> bool:
    """Reserviert eine Identität; True bedeutet, dass sie bereits sichtbar ist."""
    if identity in claimed:
        return True
    if len(identity) != 3 or identity[0] != "series":
        claimed.add(identity)
        return False

    _kind, title_key, year = identity
    unknown = ("series", title_key, "")
    known = {
        item for item in claimed
        if len(item) == 3 and item[0] == "series" and item[1] == title_key and item[2]
    }
    if year and unknown in claimed:
        # Ein früher jahrsloser Treffer wird durch den ersten eindeutigen
        # Jahrgang konkretisiert. Weitere Remakes dürfen danach sichtbar bleiben.
        claimed.remove(unknown)
        claimed.add(identity)
        return True
    if not year and len(known) == 1:
        return True
    claimed.add(identity)
    return False


def _mix_series_provider_results(
    provider_results: Dict[str, List[FilmpalastSeriesResult]],
    priority: List[str],
    claimed_identities: Optional[set[tuple]] = None,
) -> List[_SeriesCatalogEntry]:
    """Dedupliziert Serien und mischt die Leitquelle im Verhältnis 2:1 ein.

    Die erste konfigurierte Quelle erhält zwei Plätze je Runde. So bleibt die
    stärkste Quelle prägend, während jeder weitere Anbieter regelmäßig sichtbar
    wird. Identische Titel werden als eine Serie mit mehreren Quellen geführt.
    """
    years_by_title: Dict[str, set[str]] = defaultdict(set)
    for results in provider_results.values():
        for result in results:
            title_key = _norm_title(strip_source_suffix(result.title))
            year = str(result.year or "").strip()
            if title_key and year:
                years_by_title[title_key].add(year)

    grouped: Dict[tuple, List[tuple[str, FilmpalastSeriesResult]]] = OrderedDict()
    for provider in priority:
        for result in provider_results.get(provider, []):
            identity = _series_result_identity(result, provider, years_by_title)
            grouped.setdefault(identity, []).append((provider, result))

    seen = claimed_identities if claimed_identities is not None else set()
    per_provider: Dict[str, List[_SeriesCatalogEntry]] = {provider: [] for provider in priority}
    for identity, matches in grouped.items():
        if _claim_series_identity(identity, seen):
            continue
        primary_provider, primary_result = matches[0]
        source_set = {provider for provider, _result in matches}
        sources = tuple(provider for provider in priority if provider in source_set)

        # Fehlende Listenmetadaten dürfen von einer alternativen Quelle ergänzt
        # werden, ohne die bevorzugte, klickbare Quelle auszutauschen.
        year = str(primary_result.year or "").strip()
        cover_url = str(primary_result.cover_url or "").strip()
        if not year:
            year = next((str(result.year).strip() for _provider, result in matches if result.year), "")
        if not cover_url:
            cover_url = next(
                (str(result.cover_url).strip() for _provider, result in matches if result.cover_url),
                "",
            )
        visible_result = replace(primary_result, year=year, cover_url=cover_url)
        per_provider[primary_provider].append(_SeriesCatalogEntry(
            provider=primary_provider,
            result=visible_result,
            providers=sources or (primary_provider,),
        ))

    mixed: List[_SeriesCatalogEntry] = []
    positions = {provider: 0 for provider in priority}
    while True:
        progressed = False
        for index, provider in enumerate(priority):
            quota = 2 if index == 0 else 1
            entries = per_provider[provider]
            start = positions[provider]
            end = min(start + quota, len(entries))
            if end > start:
                mixed.extend(entries[start:end])
                positions[provider] = end
                progressed = True
        if not progressed:
            break
    return mixed


def _interleave_series_lists(
    *lists: List[FilmpalastSeriesResult],
) -> List[FilmpalastSeriesResult]:
    """Verzahnt mehrere Signallisten stabil und entfernt Quell-Dubletten."""
    merged: List[FilmpalastSeriesResult] = []
    seen: set[str] = set()
    longest = max((len(items) for items in lists), default=0)
    for index in range(longest):
        for items in lists:
            if index >= len(items):
                continue
            result = items[index]
            key = str(result.base_slug or result.sample_slug or result.sample_url or result.title)
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
    return merged


def _series_provider_is_paginated(provider: str, mode: str) -> bool:
    if mode == "alpha":
        return provider in SERIES_ALPHA_PROVIDERS
    return provider in SERIES_PAGINATED_PROVIDERS


def _cached_series_provider_page(
    cache_key: tuple,
) -> Optional[List[FilmpalastSeriesResult]]:
    with state.series_list_cache_lock:
        cached = state.series_list_cache.get(cache_key)
        ttl = cached[2] if cached and len(cached) > 2 else SERIES_LIST_CACHE_TTL
        if cached and time.time() - cached[0] < ttl:
            return list(cached[1])
        if cached:
            state.series_list_cache.pop(cache_key, None)
    return None


def _cache_series_provider_page(
    cache_key: tuple,
    results: List[FilmpalastSeriesResult],
    ttl: int = SERIES_LIST_CACHE_TTL,
) -> None:
    now = time.time()
    with state.series_list_cache_lock:
        expired = [
            key for key, cached in state.series_list_cache.items()
            if now - cached[0] >= (
                cached[2] if len(cached) > 2 else SERIES_LIST_CACHE_TTL
            )
        ]
        for key in expired:
            state.series_list_cache.pop(key, None)
        while len(state.series_list_cache) >= SERIES_LIST_CACHE_MAX_ENTRIES:
            oldest = min(
                state.series_list_cache,
                key=lambda key: state.series_list_cache[key][0],
            )
            state.series_list_cache.pop(oldest, None)
        state.series_list_cache[cache_key] = (now, list(results), ttl)


def _fetch_series_provider_page(
    provider: str,
    mode: str,
    letter: str,
    source_page: int,
) -> List[FilmpalastSeriesResult]:
    """Lädt eine Serien-Quellseite passend zum gewünschten Entdeckungsmodus."""
    if not _series_provider_is_paginated(provider, mode) and source_page != 1:
        return []

    if provider == "serienstream":
        if not state.provider_health.request_allowed("serienstream"):
            return []
        with state.sto_lock:
            scraper = get_sto_scraper()
            try:
                if mode == "alpha":
                    return list(scraper.list_series_alpha(letter, source_page))
                if source_page != 1:
                    return []
                if mode == "new":
                    return list(scraper.list_new(1))
                if mode == "trending":
                    return list(scraper.list_trending(1))
                return _interleave_series_lists(
                    list(scraper.list_trending(1)),
                    list(scraper.list_new(1)),
                )
            except ProviderBlockedError as exc:
                _mark_serienstream_blocked(exc.reason, str(exc))
                return []

    if provider == "filmpalast":
        with state.fp_lock:
            scraper = get_fp_scraper()
            if mode == "alpha":
                return list(scraper.list_series_alpha(letter, source_page))
            return list(scraper.list_series(source_page))

    if mode == "alpha":
        return []
    scraper_classes = {
        "moflix": MoflixScraper,
        "kinoger": KinogerScraper,
        "megakino": MegaKinoScraper,
        "xcine": XcineScraper,
        "sflix": SflixScraper,
        "ridomovies": RidomoviesScraper,
    }
    if provider == "huhu":
        with state.huhu_lock:
            return list(get_huhu_scraper().list_series(source_page))
    scraper_class = scraper_classes.get(provider)
    if scraper_class is None:
        return []
    return list(scraper_class(progress_cb=log).list_series(source_page))


def _load_series_provider_pages(
    mode: str,
    letter: str,
    requests_to_load: List[tuple[str, int]],
    cold_wave_budget: Optional[List[int]] = None,
) -> Dict[tuple[str, int], List[FilmpalastSeriesResult]]:
    loaded: Dict[tuple[str, int], List[FilmpalastSeriesResult]] = {}
    missing: List[tuple[str, int, tuple]] = []
    letter_key = str(letter or "").strip().upper()
    for provider, source_page in dict.fromkeys(requests_to_load):
        cache_mode = (
            "updates"
            if provider != "serienstream" and mode in {"discover", "new"}
            else mode
        )
        cache_key = ("series-provider", cache_mode, letter_key, provider, int(source_page))
        cached = _cached_series_provider_page(cache_key)
        if cached is None:
            missing.append((provider, source_page, cache_key))
        else:
            loaded[(provider, source_page)] = cached

    if not missing:
        return loaded
    if cold_wave_budget is not None:
        if cold_wave_budget[0] <= 0:
            raise SeriesCatalogColdLoadLimit(
                "Dieser Serienabschnitt wird noch vorbereitet. Bitte kurz warten und erneut versuchen."
            )
        cold_wave_budget[0] -= 1

    with ThreadPoolExecutor(max_workers=min(len(missing), len(PROVIDER_LABELS))) as pool:
        futures = [
            (
                provider,
                source_page,
                cache_key,
                pool.submit(
                    _fetch_series_provider_page,
                    provider,
                    mode,
                    letter,
                    source_page,
                ),
            )
            for provider, source_page, cache_key in missing
        ]
        for provider, source_page, cache_key, future in futures:
            try:
                results = list(future.result())
            except Exception as exc:
                log(
                    f"{PROVIDER_LABELS.get(provider, provider)} Serienliste "
                    f"(Quellseite {source_page}) übersprungen: {exc}",
                    "warn",
                )
                results = []
                _cache_series_provider_page(
                    cache_key,
                    results,
                    ttl=SERIES_LIST_FAILURE_CACHE_TTL,
                )
            else:
                _cache_series_provider_page(cache_key, results)
            loaded[(provider, source_page)] = results
    return loaded


def _series_catalog_sources(entries: List[_SeriesCatalogEntry], priority: List[str]) -> List[dict]:
    counts = Counter(provider for entry in entries for provider in entry.providers)
    return [
        {
            "key": provider,
            "label": PROVIDER_LABELS[provider],
            "content_language": provider_content_language(provider),
            "language_label": PROVIDER_CATALOG[provider].language_label,
            "count": counts[provider],
        }
        for provider in priority
        if counts[provider]
    ]


def _series_entry_to_dict(entry: _SeriesCatalogEntry) -> dict:
    payload = asdict(entry.result)
    payload["title"] = strip_source_suffix(entry.result.title)
    payload["provider"] = entry.provider
    payload["provider_label"] = PROVIDER_LABELS.get(entry.provider, entry.provider)
    payload["content_language"] = provider_content_language(entry.provider)
    payload["language_label"] = PROVIDER_CATALOG[entry.provider].language_label
    payload["sources"] = [
        {
            "key": provider,
            "label": PROVIDER_LABELS.get(provider, provider),
            "content_language": provider_content_language(provider),
        }
        for provider in entry.providers
    ]
    return payload


def _series_catalog_page_locked(mode: str, page: int = 1, letter: str = "") -> dict:
    """Erzeugt eine stabile, gemischte Serienseite aus den verfügbaren Katalogen."""
    page = max(1, min(int(page), SERIES_MAX_GLOBAL_PAGE))
    mode = mode if mode in {"discover", "new", "trending", "alpha"} else "discover"
    priority = provider_priority("series")
    if mode == "trending":
        # Nur Serienstream liefert ein echtes Popularitätssignal. Andere
        # Aktualitätslisten werden bewusst nicht als „angesagt“ ausgegeben.
        active = [provider for provider in priority if provider == "serienstream"]
    elif mode == "alpha":
        active = [provider for provider in priority if provider in SERIES_ALPHA_PROVIDERS]
    else:
        active = list(priority)

    provider_seen: Dict[str, set[str]] = {provider: set() for provider in priority}

    def unique_page(
        provider: str,
        results: List[FilmpalastSeriesResult],
    ) -> List[FilmpalastSeriesResult]:
        unique: List[FilmpalastSeriesResult] = []
        for result in results:
            source_key = str(
                result.base_slug or result.sample_slug or result.sample_url or result.title
            ).strip()
            key = f"{source_key}\0{str(result.year or '').strip()}"
            if key in provider_seen[provider]:
                continue
            provider_seen[provider].add(key)
            unique.append(result)
        return unique

    cold_wave_budget = [SERIES_MAX_COLD_WAVES_PER_REQUEST]
    first_pages = _load_series_provider_pages(
        mode,
        letter,
        [(provider, 1) for provider in active],
        cold_wave_budget,
    )
    first_wave = {
        provider: unique_page(provider, first_pages.get((provider, 1), []))
        for provider in active
    }
    claimed_identities: set[tuple] = set()
    catalog_entries = _mix_series_provider_results(
        first_wave,
        priority,
        claimed_identities,
    )

    paginated = [
        provider for provider in active if _series_provider_is_paginated(provider, mode)
    ]
    exhausted = {provider for provider in paginated if not first_wave[provider]}
    duplicate_only_pages = {provider: 0 for provider in paginated}
    target_end = page * SERIES_BROWSE_PAGE_SIZE
    next_source_page = 2
    has_more_unverified = False

    while len(catalog_entries) <= target_end and next_source_page <= SERIES_MAX_SOURCE_PAGE:
        pending = [provider for provider in paginated if provider not in exhausted]
        if not pending:
            break
        try:
            next_pages = _load_series_provider_pages(
                mode,
                letter,
                [(provider, next_source_page) for provider in pending],
                cold_wave_budget,
            )
        except SeriesCatalogColdLoadLimit:
            if len(catalog_entries) < target_end:
                raise
            has_more_unverified = True
            break
        wave: Dict[str, List[FilmpalastSeriesResult]] = {}
        for provider in pending:
            results = next_pages.get((provider, next_source_page), [])
            wave[provider] = unique_page(provider, results)
            if not results:
                exhausted.add(provider)
            elif not wave[provider]:
                duplicate_only_pages[provider] += 1
                if duplicate_only_pages[provider] >= 2:
                    exhausted.add(provider)
            else:
                duplicate_only_pages[provider] = 0
        catalog_entries.extend(_mix_series_provider_results(
            wave,
            priority,
            claimed_identities,
        ))
        next_source_page += 1

    start = (page - 1) * SERIES_BROWSE_PAGE_SIZE
    page_entries = catalog_entries[start:target_end]
    return {
        "entries": page_entries,
        "page": page,
        "has_more": page < SERIES_MAX_GLOBAL_PAGE and (
            len(catalog_entries) > target_end or has_more_unverified
        ),
        "sources": _series_catalog_sources(page_entries, priority),
    }


def series_catalog_page(mode: str, page: int = 1, letter: str = "") -> dict:
    """Single-Flight-Wrapper für Warmup und gleichzeitig öffnende Browser."""
    with state.series_catalog_lock:
        return _series_catalog_page_locked(mode, page, letter)


def series_search_catalog(query: str) -> dict:
    """Gruppiert die freie Suche nach Titel und zeigt alternative Quellen an."""
    priority = provider_priority("series")
    entries = _mix_series_provider_results(
        _search_series_provider_results(query),
        priority,
    )
    wanted = _norm_title(query)
    entries.sort(key=lambda entry: (
        _norm_title(entry.result.title) != wanted,
        wanted not in _norm_title(entry.result.title),
        abs(len(_norm_title(entry.result.title)) - len(wanted)),
        strip_source_suffix(entry.result.title).casefold(),
    ))
    return {
        "entries": entries,
        "page": 1,
        "has_more": False,
        "sources": _series_catalog_sources(entries, priority),
    }


def warm_home_series_cache() -> None:
    """Bereitet die gemischte Serien-Startansicht im Hintergrund vor."""
    try:
        catalog = series_catalog_page("discover", 1)
        log(f"Serien-Startansicht vorbereitet: {len(catalog['entries'])} Serien.")
    except Exception as exc:
        log(f"Serien-Startansicht konnte nicht vorab geladen werden: {exc}", "warn")


def warm_jellyfin_identity_cache() -> None:
    """Bereitet den kleinen Serienindex für sofortige Detailabgleiche vor."""
    if not get_jellyfin_client().configured:
        return
    started = time.monotonic()
    items = get_jellyfin_series()
    if items is not None:
        logger.info(
            "Jellyfin-Serienindex vorbereitet: %d Serie(n) in %.2fs",
            len(items), time.monotonic() - started,
        )


def _norm_title(title: str) -> str:
    """Titel für Matching normalisieren: Provider-Suffix + Sonderzeichen weg."""
    t = re.sub(r"\s*\[[^\]]+\]\s*$", "", title or "")
    return re.sub(r"[^a-z0-9]+", "", t.casefold())


def _series_search_title(value: str) -> str:
    """Leitet aus einem Serien-Wert (Slug/URL) einen Such-Titel ab – auch aus
    Alt-/Fremdwerten (Moflix/Filmpalast), damit alte Watchlist-Einträge auf
    serienstream.to gematcht werden können."""
    v = value or ""
    is_kinoger = v.startswith(KINOGER_PREFIX) or "kinoger.com" in v.casefold()
    is_megakino = v.startswith(MEGAKINO_PREFIX) or "megakino.org" in v.casefold()
    is_xcine = v.startswith(XCINE_PREFIX) or "xcine.ru" in v.casefold()
    for pfx in (
        SERIENSTREAM_PREFIX, HUHU_PREFIX, MOFLIX_PREFIX, EINSCHALTEN_PREFIX, KINOX_PREFIX,
        KINOGER_PREFIX, MEGAKINO_PREFIX, XCINE_PREFIX,
        SFLIX_PREFIX, RIDOMOVIES_PREFIX,
    ):
        if v.startswith(pfx):
            v = v[len(pfx):]
            break
    if ":" in v and v.split(":", 1)[0].isdigit():   # moflix "123:the-bear"
        v = v.split(":", 1)[1]
    if is_megakino:
        v = re.sub(r"^[0-9a-f]{24}:", "", v, flags=re.I)
    if v.startswith("http"):
        m = re.search(r"/(?:serie|stream|titles|watch)/(?:stream/|\d+/)?([^/?#]+)", v)
        v = m.group(1) if m else v
    if is_kinoger:
        v = re.sub(r"^\d+-", "", v)
        v = re.sub(r"\.html$", "", v, flags=re.I)
    if is_xcine and ":" in v:
        v = v.split(":", 1)[1]
    parsed = parse_episode_slug(v)
    if parsed:
        v = parsed[0]
    return v.replace("-", " ").strip()


def _episode_placeholder(slug: str, series_title: str = "") -> FilmpalastMovie:
    """Behält eine vorübergehend nicht ladbare Episode als Queue-Job."""
    parsed = parse_episode_slug(slug)
    if not parsed:
        raise ValueError(f"Kein Episoden-Slug: {slug}")
    base_slug, season, episode = parsed
    if not series_title:
        with state.watchlist_lock:
            entry = watchlist_lookup(base_slug)
            if entry:
                series_title = str(entry.get("title") or "")
    if not series_title:
        cached = state.series_cache.get(base_slug)
        if cached:
            series_title = cached.title
    if not series_title:
        series_title = _series_search_title(base_slug).title() or "Unbekannte Serie"
    return FilmpalastMovie(
        title=f"{series_title} S{season:02d}E{episode:02d}",
        url=slug,
        hosters=[],
    )


def _best_title_match(title: str, results: List[FilmpalastSeriesResult]) -> Optional[FilmpalastSeriesResult]:
    want = _norm_title(title)
    if not want or not results:
        return None
    exact = [r for r in results if _norm_title(r.title) == want]
    if exact:
        return exact[0]
    partial = [r for r in results if want in _norm_title(r.title) or _norm_title(r.title) in want]
    return partial[0] if partial else None


def _find_series_by_title(
    value: str, providers: Optional[List[str]] = None,
) -> Optional[FilmpalastSeries]:
    """Sucht und lädt dieselbe Serie nach konfigurierter Anbieterpriorität."""
    title = _series_search_title(value)
    if not title:
        return None
    for provider in providers or provider_priority("series"):
        label = PROVIDER_LABELS[provider]
        log(f"Serie nicht direkt ladbar – suche «{title}» bei {label} …")
        try:
            results = _search_series_for_provider(provider, title)
            best = _best_title_match(title, results)
            series = _load_series_for_provider(provider, best.sample_slug) if best else None
        except Exception as exc:
            log(f"  {label}-Suche/Laden fehlgeschlagen: {exc}", "warn")
            continue
        if series and series.seasons:
            log(f"  Gefunden bei {label} ({len(series.all_episodes)} Episoden).")
            return series
    return None


def _sto_find_by_title(value: str) -> Optional[FilmpalastSeries]:
    """Kompatibilitätshelfer für gezielte Serienstream-Suche."""
    return _find_series_by_title(value, ["serienstream"])


def get_series_for_value(value: str) -> Optional[FilmpalastSeries]:
    """Lädt eine explizite Quelle direkt, danach greifen die Prioritäts-Fallbacks."""
    provider = provider_for_value(value)
    try:
        series = _load_series_for_provider(provider, value)
    except Exception as exc:
        log(f"{PROVIDER_LABELS[provider]} Serien-Laden fehlgeschlagen: {exc}", "warn")
        series = None
    if series and series.seasons:
        return series
    fallbacks = [key for key in provider_priority("series") if key != provider]
    if provider in appconfig.SERIES_PROVIDER_DEFAULTS:
        fallbacks.append(provider)
    return _find_series_by_title(value, fallbacks)


def movie_to_dict(
    movie: FilmpalastMovie,
    tmdb_override: Optional[dict] = None,
) -> dict:
    ranked = state.hoster_intel.rank(movie.hosters) if movie.hosters else []
    provider = _movie_provider(movie)
    content_language = _movie_content_language(movie)
    payload = {
        "title": clean_movie_title(movie.title),
        "url": movie.url, "year": movie.year,
        "runtime": movie.runtime, "cover_url": movie.cover_url,
        "description": movie.description, "genres": movie.genres,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "content_language": content_language,
        "language_label": PROVIDER_CATALOG[provider].language_label,
        "hosters": [asdict(h) for h in movie.hosters],
        "hoster_label": state.hoster_intel.best_label(movie.hosters) if movie.hosters else "kein Hoster",
        "hoster_route": state.hoster_intel.route_text(movie.hosters) if movie.hosters else "keine Route",
        "hoster_score": round(state.hoster_intel.score(ranked[0])) if ranked else None,
        "hoster_fallback_count": max(0, len(ranked) - 1) if ranked else 0,
        "metadata_source": "Anbieter",
    }
    tmdb = tmdb_override or get_tmdb_client().movie(
        clean_movie_title(movie.title), movie.year,
    )
    if tmdb:
        for field in (
            "title", "year", "runtime", "cover_url", "backdrop_url", "description", "genres",
            "original_title", "release_date", "rating", "vote_count", "tagline",
            "certification", "certification_country", "status", "original_language",
            "spoken_languages", "countries", "directors", "writers", "cast",
            "production_companies", "keywords", "collection", "budget", "revenue",
            "trailer", "tmdb_url",
        ):
            if tmdb.get(field):
                payload[field] = tmdb[field]
        payload["metadata_source"] = "TMDB"
        payload["tmdb_id"] = tmdb["tmdb_id"]
    return payload


def movie_detail_to_dict(slug: str, movie: FilmpalastMovie) -> dict:
    """Ergänzt einen Film um seine gebündelten Anbieterquellen."""
    tmdb_match = re.fullmatch(r"tmdb:(\d+)", slug or "", flags=re.IGNORECASE)
    tmdb = (
        get_tmdb_client().movie_by_id(tmdb_match.group(1))
        if tmdb_match else None
    )
    payload = movie_to_dict(movie, tmdb_override=tmdb)
    if tmdb_match:
        if tmdb:
            for field in (
                "title", "year", "runtime", "cover_url", "backdrop_url",
                "description", "genres", "original_title", "release_date",
                "rating", "vote_count", "tagline", "certification",
                "certification_country", "status", "original_language",
                "spoken_languages", "countries", "directors", "writers", "cast",
                "production_companies", "keywords", "collection", "budget",
                "revenue", "trailer", "tmdb_url",
            ):
                if tmdb.get(field):
                    payload[field] = tmdb[field]
            payload["metadata_source"] = "TMDB"
            payload["tmdb_id"] = tmdb["tmdb_id"]

    with state.movie_source_cache_lock:
        sources = list(state.movie_source_cache.get(slug) or [movie])
    provider_sources = []
    for source in sources:
        provider = _movie_provider(source)
        provider_sources.append({
            "key": provider,
            "label": PROVIDER_LABELS.get(provider, provider),
            "content_language": _movie_content_language(source),
            "hoster_count": len(source.hosters),
            "hosters": [asdict(hoster) for hoster in source.hosters],
        })
    payload["source_providers"] = provider_sources
    payload["provider_count"] = len(provider_sources)
    payload["provider_fallback_count"] = max(0, len(provider_sources) - 1)
    payload["hoster_total"] = sum(source["hoster_count"] for source in provider_sources)
    payload["provider_route"] = " → ".join(
        source["label"] for source in provider_sources
    )
    return payload


def cached_movie_source_fallbacks(slug: str) -> Optional[List[FilmpalastMovie]]:
    with state.movie_source_cache_lock:
        sources = state.movie_source_cache.get(slug)
        return list(sources[1:]) if sources else None


def _series_folder_key(name: str) -> str:
    """Vergleichsschlüssel für vorhandene Serienordner.

    Linux unterscheidet Groß-/Kleinschreibung. Ohne diese Normalisierung würde
    z.B. neben "The rookie" ein zweiter Ordner "The Rookie" entstehen.
    """
    without_year = re.sub(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", name or "")
    return re.sub(r"[^a-z0-9]+", "", without_year.casefold())


def _existing_series_dir(out_root: Path, desired_name: str) -> Path:
    desired = out_root / desired_name
    if not out_root.is_dir():
        return desired
    wanted = _series_folder_key(desired_name)
    cache_key = (str(out_root.resolve()), wanted)
    cached = state.series_dir_cache.get(cache_key)
    if cached is not None and cached.is_dir():
        return cached
    try:
        matches = [
            child for child in out_root.iterdir()
            if child.is_dir() and _series_folder_key(child.name) == wanted
        ]
    except OSError:
        return desired
    if not matches:
        return desired

    # Gibt es durch eine frühere Groß-/Kleinschreibungs-Abweichung bereits zwei
    # Ordner, gewinnt der etablierte Ordner mit den meisten Mediendateien.
    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}

    def _content_score(path: Path) -> tuple:
        videos = 0
        dirs = 0
        try:
            for child in path.rglob("*"):
                if child.is_dir():
                    dirs += 1
                elif child.suffix.casefold() in video_suffixes:
                    videos += 1
        except OSError:
            pass
        return videos, dirs, path.name == desired_name

    chosen = max(matches, key=_content_score)
    state.series_dir_cache[cache_key] = chosen
    return chosen


def _season_output_dir(series_dir: Path, season: int) -> Path:
    """Übernimmt die vorhandene Staffelstruktur einer Serie.

    Unterstützt "Staffel 8", "Staffel 08", "Season 08" und "S08". Liegen
    vorhandene Episoden flach im Serienordner, bleibt auch die neue Episode dort.
    """
    preferred = series_dir / f"Staffel {season:02d}"
    if preferred.exists() or not series_dir.is_dir():
        return preferred

    season_re = re.compile(r"^(?:staffel|season|s)\s*0*(\d+)\b", re.IGNORECASE)
    season_dirs: List[tuple] = []
    has_flat_episodes = False
    episode_re = re.compile(r"(?:^|[. _-])s\d{1,2}e\d{1,3}(?:$|[. _-])", re.IGNORECASE)
    try:
        for child in series_dir.iterdir():
            if child.is_dir():
                match = season_re.match(child.name.strip())
                if match:
                    season_dirs.append((int(match.group(1)), child))
            elif child.is_file() and episode_re.search(child.stem):
                has_flat_episodes = True
    except OSError:
        return preferred

    for number, folder in season_dirs:
        if number == season:
            return folder
    if has_flat_episodes and not season_dirs:
        return series_dir
    return preferred


def series_episode_out_path(series_title: str, season: int, episode: int) -> Path:
    # Serien landen im SEPARATEN Serien-Ordner (state.series_path), Filme im
    # Film-Ordner (state.save_path). Vorhandene NAS-Strukturen werden bewahrt.
    out_root = Path(state.series_path)
    desired_name = sanitize_filename(series_title).strip() or "Serie"
    series_dir = _existing_series_dir(out_root, desired_name)
    season_dir = _season_output_dir(series_dir, season)
    return season_dir / build_filename(series_title, season, episode)


def _valid_media_cached(path: Path) -> tuple[bool, str]:
    """Validiert lokale Medien nur erneut, wenn Größe oder mtime sich ändern."""
    try:
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
    except OSError as exc:
        return False, f"Datei nicht lesbar: {exc}"
    key = str(path.resolve(strict=False))
    with state.media_validation_lock:
        cached = state.media_validation_cache.get(key)
        if cached and cached[:2] == signature:
            return bool(cached[2]), str(cached[3])
    valid, detail = validate_media_file(path)
    with state.media_validation_lock:
        state.media_validation_cache[key] = (*signature, valid, detail)
    return valid, detail


def compute_downloaded_episodes(series: FilmpalastSeries) -> set:
    """Scannt den Serienordner einmal statt eines NAS-Glob pro Episode."""
    out_root = Path(state.series_path)
    desired_name = sanitize_filename(series.title).strip() or "Serie"
    series_dir = _existing_series_dir(out_root, desired_name)
    if not series_dir.is_dir():
        return set()

    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
    candidates: List[tuple[Path, tuple[int, int]]] = []
    try:
        for path in series_dir.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in video_suffixes:
                continue
            match = re.search(r"(?:^|[. _-])s(\d{1,2})e(\d{1,3})(?:$|[. _-])", path.stem, re.I)
            if match:
                candidates.append((path, (int(match.group(1)), int(match.group(2)))))
    except OSError:
        pass

    existing: set[tuple[int, int]] = set()
    if candidates:
        with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
            futures = [(pair, pool.submit(_valid_media_cached, path)) for path, pair in candidates]
            for pair, future in futures:
                try:
                    valid, _detail = future.result()
                except Exception:
                    valid = False
                if valid:
                    existing.add(pair)

    return {
        ep.slug for ep in series.all_episodes
        if (ep.season, ep.episode) in existing
    }


def series_to_dict(
    series: FilmpalastSeries,
    refresh_jellyfin: bool = False,
    defer_checks: bool = False,
) -> dict:
    """Serialisiert eine Serie, optional ohne blockierende Verfügbarkeitschecks.

    Beim ersten Öffnen werden damit Staffel- und Episodenstruktur sofort nach
    dem Anbieterabruf ausgeliefert. Lokaler Bestand, TMDB und Jellyfin dürfen
    anschließend in einem getrennten Request nachziehen.
    """
    downloaded = set() if defer_checks else compute_downloaded_episodes(series)
    with state.watchlist_lock:
        stored_entry = watchlist_match_series(series.base_slug, series.title)
        watchlist_entry = dict(stored_entry) if stored_entry else None
    stored_tmdb_id = watchlist_entry.get("tmdb_id") if watchlist_entry else ""
    tmdb_client = get_tmdb_client()
    tmdb = None if defer_checks else get_tmdb_series(series.title, stored_tmdb_id)
    aliases = list(dict.fromkeys(filter(None, (
        watchlist_entry.get("title", "") if watchlist_entry else "",
        *(watchlist_entry.get("aliases", []) if watchlist_entry else []),
        tmdb.get("title", "") if tmdb else "",
        tmdb.get("original_title", "") if tmdb else "",
    ))))
    tmdb_id = stored_tmdb_id or (tmdb or {}).get("tmdb_id")
    with state.watchlist_lock:
        refined_entry = watchlist_match_series(
            series.base_slug, series.title, tmdb_id=tmdb_id, aliases=aliases,
        )
        if refined_entry is not None:
            watchlist_entry = dict(refined_entry)
    if watchlist_entry:
        stored_tmdb_id = watchlist_entry.get("tmdb_id") or stored_tmdb_id
        tmdb_id = stored_tmdb_id or tmdb_id
        aliases = list(dict.fromkeys(filter(None, (
            watchlist_entry.get("title", ""),
            *(watchlist_entry.get("aliases") or []),
            *aliases,
        ))))
    season_episode_counts = (tmdb or {}).get("season_episode_counts") or (
        watchlist_entry.get("season_episode_counts", {}) if watchlist_entry else {}
    )
    season_counts_checked_at = (tmdb or {}).get("season_counts_checked_at") or (
        watchlist_entry.get("season_counts_checked_at", 0) if watchlist_entry else 0
    )
    unreleased_slugs = (
        _unreleased_episode_slugs(series, tmdb_id)
        if not defer_checks and tmdb_id else set()
    )
    jf_client = get_jellyfin_client()
    jellyfin_pending = bool(defer_checks and jf_client.configured)
    jf_identity_available: Optional[bool] = None if jellyfin_pending else True
    jf_existing: set[tuple[int, int]] = set()
    jf_stale = False
    jf_checked_at = 0.0
    if jf_client.configured and not jellyfin_pending:
        quick_status = _series_jellyfin_status(
            series.title,
            tmdb_id=tmdb_id,
            aliases=aliases,
            episodes=[
                {"slug": episode.slug, "season": episode.season, "episode": episode.episode}
                for episode in series.all_episodes
            ],
            force=refresh_jellyfin,
        )
        jf_identity_available = bool(quick_status["available"])
        jf_stale = bool(quick_status["stale"])
        jf_checked_at = float(quick_status["checked_at"] or 0)
        jf_existing = {
            (episode.season, episode.episode)
            for episode in series.all_episodes
            if quick_status["episodes"].get(episode.slug)
        }
    seasons = []
    for s in series.season_numbers:
        episodes = []
        for ep in series.seasons[s]:
            in_jellyfin = (ep.season, ep.episode) in jf_existing
            episodes.append({
                "season": ep.season, "episode": ep.episode, "slug": ep.slug,
                "url": ep.url, "release_name": ep.release_name,
                "queued": ep.slug in state.picked,
                "downloaded": ep.slug in downloaded,
                "in_jellyfin": in_jellyfin,
                "unreleased": ep.slug in unreleased_slugs,
            })
        seasons.append({"season": s, "episodes": episodes})
    provider = provider_for_value(series.url or series.base_slug)
    payload = {
        "title": series.title, "base_slug": series.base_slug, "url": series.url,
        "cover_url": series.cover_url, "description": series.description,
        "genres": series.genres, "seasons": seasons,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "content_language": provider_content_language(provider),
        "language_label": PROVIDER_CATALOG[provider].language_label,
        "episode_count": len(series.all_episodes),
        "watchlisted": watchlist_entry is not None,
        "availability_pending": defer_checks,
        "enrichment_pending": bool(
            defer_checks and (tmdb_client.configured or jf_client.configured)
        ),
        "jellyfin_configured": jf_client.configured,
        "jellyfin_pending": jellyfin_pending,
        "jellyfin_available": jf_identity_available,
        "jellyfin_stale": jf_stale,
        "jellyfin_checked_at": jf_checked_at,
        "watch_mode": normalize_watch_mode(
            watchlist_entry.get("download_mode") if watchlist_entry else None
        ),
        "cleanup_mode": normalize_cleanup_mode(
            watchlist_entry.get("cleanup_mode") if watchlist_entry else None
        ),
        "metadata_source": "Anbieter",
    }
    if tmdb:
        for field in (
            "title", "year", "first_air_date", "runtime", "cover_url",
            "backdrop_url", "description", "genres", "original_title",
            "rating", "vote_count", "status", "trailer", "cast", "creators",
            "networks",
        ):
            if tmdb.get(field):
                payload[field] = tmdb[field]
        payload["metadata_source"] = "TMDB"
        payload["tmdb_id"] = tmdb["tmdb_id"]
    if tmdb_id:
        payload["tmdb_id"] = tmdb_id
    if aliases:
        payload["aliases"] = aliases
    if season_episode_counts:
        payload["season_episode_counts"] = season_episode_counts
    if season_counts_checked_at:
        payload["season_counts_checked_at"] = season_counts_checked_at
    return payload


def queue_group_name(slug: str) -> str:
    parsed = parse_episode_slug(slug)
    if not parsed:
        return "Filme"
    movie = state.fp_movies.get(slug)
    if movie and movie.title:
        stripped = strip_episode_suffix(movie.title)
        if stripped:
            return stripped
    return parsed[0]


def queue_content_key(slug: str, movie: Optional[FilmpalastMovie] = None) -> str:
    """Provider-unabhängiger Schlüssel gegen doppelte logische Downloads."""
    movie = movie or state.fp_movies.get(slug)
    if movie is None:
        return ""
    parsed = parse_episode_slug(slug)
    if parsed:
        base_slug, season, episode = parsed
        title = strip_episode_suffix(movie.title) or movie.title
        with state.watchlist_lock:
            entry = watchlist_lookup(base_slug)
            tmdb_id = str((entry or {}).get("tmdb_id") or "")
        if not tmdb_id:
            tmdb = get_tmdb_series(title)
            tmdb_id = str((tmdb or {}).get("tmdb_id") or "")
        identity = f"tmdb:{tmdb_id}" if tmdb_id else f"title:{_norm_title(title)}"
        return f"series:{identity}:s{season}:e{episode}"
    title = clean_movie_title(movie.title)
    tmdb = get_tmdb_client().movie_summary(title, movie.year)
    tmdb_id = str((tmdb or {}).get("tmdb_id") or "")
    identity = f"tmdb:{tmdb_id}" if tmdb_id else f"title:{_norm_title(title)}:{movie.year or ''}"
    return f"movie:{identity}"


def episode_sort_key(slug: str):
    parsed = parse_episode_slug(slug)
    return (parsed[1], parsed[2]) if parsed else (0, 0)


PERSISTENCE_RETRY_DELAYS = (1, 5, 15, 30, 60)


def _persistence_saver(resource: str):
    return {
        "queue": appconfig.save_queue,
        "watchlist": appconfig.save_watchlist,
        "movie_subscriptions": appconfig.save_movie_subscriptions,
    }[resource]


def _persistence_status(resource: str) -> dict:
    with state.persistence_status_lock:
        error = dict(state.persistence_errors.get(resource) or {})
        pending = resource in state.persistence_pending
    return {
        "ok": not error,
        "pending_retry": pending,
        "attempts": int(error.get("attempts") or 0),
        "last_failed_at": float(error.get("last_failed_at") or 0),
        "next_retry_at": float(error.get("next_retry_at") or 0),
    }


def _mark_persistence_success(resource: str) -> None:
    with state.persistence_status_lock:
        state.persistence_pending.pop(resource, None)
        state.persistence_errors.pop(resource, None)


def _mark_persistence_failure(resource: str, *, pending: bool) -> None:
    now = time.time()
    with state.persistence_status_lock:
        previous = state.persistence_errors.get(resource) or {}
        attempts = int(previous.get("attempts") or 0) + 1
        delay = PERSISTENCE_RETRY_DELAYS[
            min(attempts - 1, len(PERSISTENCE_RETRY_DELAYS) - 1)
        ] if pending else 0
        state.persistence_errors[resource] = {
            "attempts": attempts,
            "last_failed_at": now,
            "next_retry_at": now + delay if pending else 0,
        }


def _write_persistent_snapshot(resource: str, snapshot) -> bool:
    with state.persistence_write_locks[resource]:
        try:
            saved = bool(_persistence_saver(resource)(snapshot))
        except Exception as exc:
            log(f"{resource}: Persistenzfehler: {exc}", "warn")
            saved = False
    if saved:
        _mark_persistence_success(resource)
    return saved


def _retry_persistence_once(resource: str) -> bool:
    with state.persistence_status_lock:
        pending = state.persistence_pending.get(resource)
        if pending is None:
            return True
        generation = int(pending["generation"])
        snapshot = deepcopy(pending["snapshot"])
    with state.persistence_write_locks[resource]:
        # Ein neuerer API-/Worker-Commit darf nie durch einen alten Retry
        # überschrieben werden.
        with state.persistence_status_lock:
            current = state.persistence_pending.get(resource)
            if current is None or int(current["generation"]) != generation:
                return False
        try:
            saved = bool(_persistence_saver(resource)(snapshot))
        except Exception as exc:
            log(f"{resource}: Persistenz-Retry fehlgeschlagen: {exc}", "warn")
            saved = False
    if saved:
        with state.persistence_status_lock:
            current = state.persistence_pending.get(resource)
            if current is not None and int(current["generation"]) == generation:
                state.persistence_pending.pop(resource, None)
                state.persistence_errors.pop(resource, None)
        return True
    _mark_persistence_failure(resource, pending=True)
    return False


def _persistence_retry_loop(resource: str) -> None:
    try:
        while True:
            with state.persistence_status_lock:
                pending = state.persistence_pending.get(resource)
                if pending is None:
                    return
                retry_at = float(
                    (state.persistence_errors.get(resource) or {}).get("next_retry_at")
                    or time.time()
                )
            time.sleep(max(0.05, retry_at - time.time()))
            _retry_persistence_once(resource)
    finally:
        with state.persistence_status_lock:
            state.persistence_retrying.discard(resource)
            restart = resource in state.persistence_pending
            if restart:
                state.persistence_retrying.add(resource)
        if restart:
            threading.Thread(
                target=_persistence_retry_loop,
                args=(resource,),
                name=f"persistence-retry-{resource}",
                daemon=True,
            ).start()


def _schedule_persistence_retry(resource: str, snapshot) -> None:
    with state.persistence_status_lock:
        generation = int(state.persistence_generations.get(resource) or 0) + 1
        state.persistence_generations[resource] = generation
        state.persistence_pending[resource] = {
            "generation": generation,
            "snapshot": deepcopy(snapshot),
        }
        should_start = resource not in state.persistence_retrying
        if should_start:
            state.persistence_retrying.add(resource)
    _mark_persistence_failure(resource, pending=True)
    if should_start:
        threading.Thread(
            target=_persistence_retry_loop,
            args=(resource,),
            name=f"persistence-retry-{resource}",
            daemon=True,
        ).start()


def _persist_background_snapshot(resource: str, snapshot) -> bool:
    if _write_persistent_snapshot(resource, snapshot):
        return True
    _schedule_persistence_retry(resource, snapshot)
    log(
        f"{resource}: Zustand konnte nicht gespeichert werden; Retry vorgemerkt.",
        "warn",
    )
    return False


def _persistence_unavailable(resource: str) -> HTTPException:
    _mark_persistence_failure(resource, pending=False)
    return HTTPException(
        503,
        detail={
            "code": "state_persistence_failed",
            "resource": resource,
            "message": "Die Änderung konnte nicht dauerhaft gespeichert werden.",
        },
        headers={"Retry-After": "5"},
    )


def _require_persistent_snapshot(resource: str, snapshot) -> None:
    if not _write_persistent_snapshot(resource, snapshot):
        raise _persistence_unavailable(resource)


def _persist_watchlist_background() -> bool:
    with state.watchlist_lock:
        snapshot = deepcopy(state.watchlist)
    return _persist_background_snapshot("watchlist", snapshot)


def _persist_movie_subscriptions_background() -> bool:
    with state.movie_subscriptions_lock:
        snapshot = deepcopy(state.movie_subscriptions)
    return _persist_background_snapshot("movie_subscriptions", snapshot)


def _persist_queue_state() -> bool:
    with state.queue_claim_lock:
        snapshot = set(state.picked)
        # Lock bis nach dem atomaren Replace halten. Sonst kann ein älterer
        # Snapshot einen neueren Abschluss nachträglich überschreiben.
        return _persist_background_snapshot("queue", snapshot)


def _persist_new_queue_claims(slugs) -> bool:
    """Persistiert neue Claims oder gibt sie frei, bevor Jobs starten dürfen."""
    claimed = set(slugs)
    if not claimed or _persist_queue_state():
        return True
    with state.queue_claim_lock:
        state.picked.difference_update(claimed)
        state.preparing_queue_slugs.difference_update(claimed)
        for slug in claimed:
            state.provider_waiting_jobs.pop(slug, None)
    # Der erste Fehlversuch enthielt noch die neuen Claims. Der Retry-Snapshot
    # muss deshalb sofort durch den zurückgerollten Zustand ersetzt werden.
    _persist_queue_state()
    return False


def _queue_slug_claimed(slug: str) -> bool:
    with state.queue_claim_lock:
        return slug in state.picked


def serienstream_provider_status() -> dict:
    active_jobs = state.dl_queue.active_jobs()
    pending_jobs = (
        state.dl_queue.pending_jobs()
        if hasattr(state.dl_queue, "pending_jobs") else []
    )
    active_download_slugs = {
        slug
        for job in active_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    pending_download_slugs = {
        slug
        for job in pending_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    download_slugs = active_download_slugs | pending_download_slugs
    with state.queue_claim_lock:
        claimed = set(state.picked)
        waiting_slugs = set(state.provider_waiting_jobs) & claimed
        preparing_slugs = set(state.preparing_queue_slugs) & claimed
        with state.download_state_lock:
            counted = set(state.counted_queue_slugs)
        fallback_slugs = {
            slug for slug in claimed & counted
            if slug not in waiting_slugs
            and slug not in download_slugs
            and parse_episode_slug(slug) is not None
            and provider_for_value(slug) == "serienstream"
        }
    status = state.provider_health.status(
        "serienstream", waiting_episode_count=len(waiting_slugs),
    )
    status["fallback_episode_count"] = len(fallback_slugs)
    status["checking_episode_count"] = len(fallback_slugs & preparing_slugs)
    status["queued_fallback_episode_count"] = len(fallback_slugs - preparing_slugs)
    status["active_fallback_download_count"] = sum(
        parse_episode_slug(slug) is not None
        and provider_for_value(slug) == "serienstream"
        for slug in active_download_slugs & claimed
    )
    status["ready_fallback_download_count"] = sum(
        parse_episode_slug(slug) is not None
        and provider_for_value(slug) == "serienstream"
        for slug in pending_download_slugs & claimed
    )
    status["cached_redirect_count"] = state.resolved_link_cache.count()
    return status


def build_queue_payload() -> dict:
    with state.queue_claim_lock:
        slugs = sorted(state.picked)
    if not slugs:
        return {
            "count": 0,
            "groups": [],
            "providers": {"serienstream": serienstream_provider_status()},
            "persistence": _persistence_status("queue"),
            "activity": {
                "active_preparations": 0,
                "pending_preparations": 0,
                "active_downloads": state.dl_queue.active_count(),
                "pending_downloads": 0,
            },
        }
    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for slug in slugs:
        groups.setdefault(queue_group_name(slug), []).append(slug)
    active_jobs = state.dl_queue.active_jobs()
    pending_jobs = (
        state.dl_queue.pending_jobs()
        if hasattr(state.dl_queue, "pending_jobs") else []
    )
    active_download_slugs = {
        slug
        for job in active_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    pending_download_slugs = {
        slug
        for job in pending_jobs
        if not getattr(job, "is_preparation_job", False)
        for slug in _job_queue_slugs(job)
    }
    with state.queue_claim_lock:
        preparing_slugs = set(state.preparing_queue_slugs)
    result_groups = []
    provider_status = serienstream_provider_status()
    serienstream_paused = provider_status.get("state") != HEALTHY
    for name, gslugs in groups.items():
        items = []
        for slug in sorted(gslugs, key=episode_sort_key):
            movie = state.fp_movies.get(slug)
            title = movie.title if movie else slug
            label = state.hoster_intel.best_label(movie.hosters) if movie and movie.hosters else "—"
            provider = _movie_provider(movie, slug)
            waiting_provider = slug in state.provider_waiting_jobs
            preparing_source = (
                not waiting_provider
                and slug in preparing_slugs
                and slug in state.counted_queue_slugs
            )
            checking_fallback = (
                serienstream_paused
                and preparing_source
                and parse_episode_slug(slug) is not None
                and provider_for_value(slug) == "serienstream"
            )
            queued_fallback = (
                serienstream_paused
                and not waiting_provider
                and not checking_fallback
                and slug not in active_download_slugs
                and slug not in pending_download_slugs
                and parse_episode_slug(slug) is not None
                and provider_for_value(slug) == "serienstream"
                and slug in state.counted_queue_slugs
            )
            items.append({
                "slug": slug, "title": title, "hoster_label": label,
                "provider": provider,
                "content_language": _movie_content_language(movie, fallback=slug),
                "done": slug in state.done_slugs,
                "status": (
                    "downloading" if slug in active_download_slugs
                    else "download_ready" if slug in pending_download_slugs
                    else "waiting_provider" if waiting_provider
                    else "checking_fallback" if checking_fallback
                    else "preparing_source" if preparing_source
                    else "queued_fallback" if queued_fallback
                    else "waiting"
                ),
                "next_probe_at": (
                    state.provider_health.next_probe_at("serienstream")
                    if waiting_provider else 0
                ),
            })
        result_groups.append({"name": name, "items": items})
    return {
        "count": len(slugs),
        "groups": result_groups,
        "providers": {"serienstream": provider_status},
        "persistence": _persistence_status("queue"),
        "activity": {
            # Auch der separate kontrollierte Fallback-Retry ist eine aktive
            # Vorbereitung, obwohl er nicht als DownloadQueue-Job läuft.
            "active_preparations": len(preparing_slugs & set(slugs)),
            "pending_preparations": sum(
                bool(getattr(job, "is_preparation_job", False)) for job in pending_jobs
            ),
            "active_downloads": len(active_download_slugs),
            "pending_downloads": len(pending_download_slugs),
        },
    }


def watchlist_payload() -> dict:
    items = []
    with state.queue_claim_lock, state.watchlist_lock:
        for w in state.watchlist:
            pending = set(state.watchlist_new_slugs.get(w["base_slug"], set()))
            queued_count = len(pending & state.picked)
            failures = w.get("failed_downloads") if isinstance(w.get("failed_downloads"), dict) else {}
            failed_count = len(set(failures) & pending)
            mode = normalize_watch_mode(w.get("download_mode"))
            cleanup_mode = normalize_cleanup_mode(w.get("cleanup_mode"))
            error = str(w.get("last_error") or "")
            if error:
                status = "blocked"
            elif failed_count:
                status = "failed"
            elif queued_count:
                status = "queued"
            elif pending and state.automation.get("auto_download") and not is_within_download_window():
                status = "waiting_window"
            elif pending:
                status = "missing"
            else:
                status = "current"
            items.append({
                **w,
                "download_mode": mode,
                "download_mode_label": WATCH_MODE_LABELS[mode],
                "cleanup_mode": cleanup_mode,
                "cleanup_mode_label": CLEANUP_MODE_LABELS[cleanup_mode],
                "cleanup_mode_ready": (
                    cleanup_mode == CLEANUP_MODE_KEEP
                    or bool(
                        state.jellyfin_cfg.get("url", "").strip()
                        and state.jellyfin_cfg.get("api_key", "").strip()
                        and state.jellyfin_cfg.get("user_id", "").strip()
                        and state.jellyfin_user_episodes_available
                        and not str(w.get("cleanup_last_error") or "")
                    )
                ),
                "download_mode_ready": (
                    mode != WATCH_MODE_NEXT_SEASON
                    or bool(
                        state.jellyfin_cfg.get("url", "").strip()
                        and state.jellyfin_cfg.get("api_key", "").strip()
                        and state.jellyfin_cfg.get("user_id", "").strip()
                        and state.jellyfin_user_episodes_available
                        and not error
                    )
                ),
                "new_count": len(pending),
                "queued_count": queued_count,
                "failed_count": failed_count,
                "status": status,
            })
    return {
        "watchlist": items,
        "persistence": _persistence_status("watchlist"),
    }


def hydrate_watchlist_artwork() -> None:
    """Ergänzt Bilder alter Abo-Einträge unabhängig von Jellyfin-Prüfungen."""
    if not get_tmdb_client().configured:
        return
    with state.watchlist_lock:
        missing = [
            {
                "base_slug": str(entry.get("base_slug") or ""),
                "title": str(entry.get("title") or ""),
                "tmdb_id": entry.get("tmdb_id") or "",
            }
            for entry in state.watchlist
            if not entry.get("backdrop_url") or not entry.get("cover_url")
        ]
    if not missing:
        return

    artwork = {}
    for item in missing:
        metadata = get_tmdb_series(item["title"], item["tmdb_id"])
        if not metadata:
            continue
        artwork[item["base_slug"]] = {
            "tmdb_id": metadata.get("tmdb_id"),
            "cover_url": metadata.get("cover_url") or "",
            "backdrop_url": metadata.get("backdrop_url") or "",
        }

    changed = False
    with state.watchlist_lock:
        for entry in state.watchlist:
            images = artwork.get(str(entry.get("base_slug") or ""))
            if not images:
                continue
            for field in ("tmdb_id", "cover_url", "backdrop_url"):
                if not entry.get(field) and images.get(field):
                    entry[field] = images[field]
                    changed = True
        if changed:
            _persist_watchlist_background()


# ---------------------------------------------------------------------------
# Download-Pipeline (1:1 aus main.py._build_and_start_queue portiert)
# ---------------------------------------------------------------------------
def on_job_progress(pct: float, msg: str, label: str):
    payload = {"type": "progress", "label": label, "msg": msg}
    if pct >= 0:
        payload["pct"] = pct
    broadcast(payload)


def _failure_record(previous, message: str) -> dict:
    attempts = int(previous.get("attempts", 0)) if isinstance(previous, dict) else 0
    attempts += 1
    retry_delay = min(6 * 60 * 60, 5 * 60 * (2 ** min(attempts - 1, 6)))
    return {
        "message": str(message)[:240],
        "attempts": attempts,
        "next_retry": time.time() + retry_delay,
    }


def _watchlist_retry_allowed(slug: str) -> bool:
    with state.watchlist_lock:
        for entry in state.watchlist:
            failure = (entry.get("failed_downloads") or {}).get(slug)
            if isinstance(failure, dict):
                return time.time() >= float(failure.get("next_retry", 0) or 0)
    return True


def on_job_done(ok: bool, msg: str, label: str, out_path: Path, hoster_url: str = "", slug: str = ""):
    # Der Counter-Eintrag ist das einmalige Abschlusstoken. Entfernen/Abbruch
    # kann es vor einem verspäteten Callback konsumieren; dieser wird dann
    # vollständig ignoriert und kann done/total nicht mehr verfälschen.
    with state.queue_claim_lock:
        with state.download_state_lock:
            if slug and slug not in state.counted_queue_slugs:
                return False
            if slug:
                state.provider_waiting_jobs.pop(slug, None)
            if ok and slug:
                state.done_slugs.add(slug)
            state.done_jobs += 1
            if slug:
                state.counted_queue_slugs.discard(slug)
                state.picked.discard(slug)
            done_jobs = state.done_jobs
            total_jobs = state.total_jobs
            successful_jobs = len(state.done_slugs)
            failed_jobs = max(0, done_jobs - successful_jobs)
    if hoster_url:
        state.hoster_intel.record_download(hoster_url, ok)
    if ok:
        log(f"Fertig: {label} -> {out_path}")
    else:
        log(f"Fehler {label}: {msg}", "err")
    if slug:
        # `picked` bildet ausschließlich noch offene Warteschlangen-Einträge ab.
        # Erst hier entfernen: Laufzeit-Fallbacks erreichen diese Funktion erst
        # nach Erfolg oder nachdem wirklich alle Anbieter ausgeschöpft sind.
        _persist_queue_state()
        watchlist_changed = False
        with state.watchlist_lock:
            for entry in state.watchlist:
                base_slug = entry.get("base_slug", "")
                pending = state.watchlist_new_slugs.get(base_slug, set())
                failures = entry.get("failed_downloads")
                if not isinstance(failures, dict):
                    failures = {}
                    entry["failed_downloads"] = failures
                if slug not in pending and slug not in failures:
                    continue
                if ok:
                    pending.discard(slug)
                    failures.pop(slug, None)
                    if not pending:
                        state.watchlist_new_slugs.pop(base_slug, None)
                elif msg != "Abgebrochen":
                    failures[slug] = _failure_record(failures.get(slug), msg)
                else:
                    failures.pop(slug, None)
                watchlist_changed = True
            if watchlist_changed:
                _persist_watchlist_background()
        if watchlist_changed:
            broadcast({"type": "watchlist_update", **watchlist_payload()})
        if not ok and not parse_episode_slug(slug):
            _movie_subscription_download_failed(slug, msg)
        with state.telegram_jobs_lock:
            telegram_job = state.telegram_jobs.pop(slug, None)
        if telegram_job:
            if telegram_job.get("kind") == "series":
                _telegram_series_job_result(telegram_job, slug, ok, msg, out_path)
            else:
                threading.Thread(
                    target=_telegram_finish_job,
                    args=(telegram_job, ok, msg, out_path),
                    daemon=True,
                ).start()
        with state.seerr_jobs_lock:
            seerr_jobs = state.seerr_jobs.pop(slug, [])
        for seerr_job in seerr_jobs:
            _seerr_job_result(seerr_job, slug, ok, msg, out_path)
    broadcast({
        "type": "job_done", "ok": ok, "label": label, "slug": slug, "msg": msg,
        "done_jobs": done_jobs, "total_jobs": total_jobs,
        "successful_jobs": successful_jobs, "failed_jobs": failed_jobs,
        "active": state.dl_queue.active_count(), "pending": state.dl_queue.pending_count(),
    })
    return True


def _refresh_jellyfin_after_download_once():
    """Scan anstoßen und den UI-Cache während des Jellyfin-Imports erneuern."""
    if not state.jellyfin_refresh_lock.acquire(blocking=False):
        log("Jellyfin-Aktualisierung läuft bereits.")
        return
    try:
        with state.jellyfin_cache_lock:
            jf_client = get_jellyfin_client()
            generation = state.jellyfin_config_generation
            user_id = state.jellyfin_cfg.get("user_id", "").strip()
        if not jf_client.configured:
            return
        if not jf_client.refresh_library():
            log("Jellyfin-Bibliotheksscan konnte nicht gestartet werden.", "warn")
            return
        log("Jellyfin-Bibliotheksscan gestartet.")
        started = time.monotonic()
        for deadline in (5, 15, 30, 60, 120):
            time.sleep(max(0.0, deadline - (time.monotonic() - started)))
            withdrawn_slugs: set[str] = set()
            with state.jellyfin_cache_lock:
                if generation != state.jellyfin_config_generation:
                    log("Jellyfin-Aktualisierung verworfen: Konfiguration wurde geändert.", "warn")
                    return

            get_jellyfin_library(force=True)
            # Der globale Bestand und der benutzerspezifische Gesehen-Status
            # dürfen sich nicht gegenseitig überschreiben.
            get_jellyfin_episodes(force=True)
            get_jellyfin_series(force=True)
            if user_id:
                get_jellyfin_user_episodes(force=True)
            with state.jellyfin_cache_lock:
                # Ein Bibliotheksscan kann die Episoden jeder einzelnen Serie
                # verändert haben. Detail-Caches werden deshalb atomar
                # verworfen und beim nächsten Öffnen gezielt neu aufgebaut.
                state.jellyfin_targeted_episodes.clear()
                if generation != state.jellyfin_config_generation:
                    log("Jellyfin-Aktualisierung verworfen: Konfiguration wurde geändert.", "warn")
                    return
                global_episodes = state.jellyfin_episodes
                global_series = state.jellyfin_series
                global_available = state.jellyfin_episodes_available
                global_series_available = state.jellyfin_series_available
                user_episodes = state.jellyfin_user_episodes if user_id else None
                user_available = state.jellyfin_user_episodes_available if user_id else False
                data_generation = state.jellyfin_episode_data_generation

            # NAS-Scan/Policy außerhalb des Watchlist-Locks berechnen. Sonst
            # blockieren Bell, Abo-Aktionen und fertige Download-Callbacks.
            with state.watchlist_lock:
                snapshots = []
                for entry in state.watchlist:
                    entry["check_generation"] = int(entry.get("check_generation", 0)) + 1
                    entry["last_error"] = "Prüfung läuft – Auto-Download pausiert"
                    snapshots.append((
                        entry,
                        dict(entry),
                        state.series_cache.get(entry["base_slug"]),
                        entry["check_generation"],
                    ))
            calculated_updates = []
            for entry, snapshot, series, revision in snapshots:
                needs_user = normalize_watch_mode(snapshot.get("download_mode")) == WATCH_MODE_NEXT_SEASON
                if global_episodes is None or not global_available:
                    calculated_updates.append((entry, revision, None, "Jellyfin nicht erreichbar – Auto-Download pausiert"))
                elif global_series is None or not global_series_available:
                    calculated_updates.append((entry, revision, None, "Jellyfin-Serienindex nicht verfügbar"))
                elif needs_user and (not user_id or user_episodes is None or not user_available):
                    calculated_updates.append((entry, revision, None, "Jellyfin-Benutzerstatus nicht verfügbar"))
                elif series is not None:
                    try:
                        calculated = _calculate_watchlist_entry_state(
                            snapshot, series, jf_client, global_episodes, user_episodes,
                            global_series,
                        )
                        calculated_updates.append((entry, revision, calculated, ""))
                    except Exception as exc:
                        calculated_updates.append((entry, revision, None, str(exc)[:240]))
            with state.jellyfin_cache_lock:
                data_is_current = (
                    generation == state.jellyfin_config_generation
                    and data_generation == state.jellyfin_episode_data_generation
                )
                with state.watchlist_lock:
                    if data_is_current:
                        for entry, revision, calculated, error in calculated_updates:
                            if not any(current is entry for current in state.watchlist):
                                continue
                            if int(entry.get("check_generation", 0)) != revision:
                                continue
                            if error:
                                entry["last_checked"] = time.time()
                                entry["last_error"] = error
                            elif calculated is not None:
                                withdrawn_slugs.update(
                                    _apply_watchlist_entry_state(entry, calculated)
                                )
                    _persist_watchlist_background()
            if withdrawn_slugs:
                _cancel_withdrawn_watchlist_slugs(
                    withdrawn_slugs,
                    "In Jellyfin vorhanden oder nicht mehr Teil der Abo-Regel",
                )
            broadcast({"type": "jellyfin_update", **watchlist_payload()})
    finally:
        state.jellyfin_refresh_lock.release()


def refresh_jellyfin_after_download():
    """Fasst parallele Scan-Anforderungen zusammen, ohne eine zu verlieren."""
    with state.jellyfin_refresh_request_lock:
        state.jellyfin_refresh_pending = True
        if state.jellyfin_refresh_running:
            log("Jellyfin-Aktualisierung wurde vorgemerkt.")
            return
        state.jellyfin_refresh_running = True
    try:
        while True:
            with state.jellyfin_refresh_request_lock:
                state.jellyfin_refresh_pending = False
            _refresh_jellyfin_after_download_once()
            with state.jellyfin_refresh_request_lock:
                if state.jellyfin_refresh_pending:
                    continue
                state.jellyfin_refresh_running = False
                return
    except Exception:
        with state.jellyfin_refresh_request_lock:
            state.jellyfin_refresh_running = False
        raise


def on_queue_done():
    with state.queue_lifecycle_lock:
        _on_queue_done_locked()


def _reconcile_idle_queue_state_locked() -> int:
    """Beendet verwaiste Zaehltoken und entfernt alte Gate-Sperrmarker."""
    if (
        state.dl_queue.active_count()
        or state.dl_queue.pending_count()
        or state.queue_prepare_lock.locked()
    ):
        return 0

    with state.queue_claim_lock:
        with state.download_state_lock:
            counted = set(state.counted_queue_slugs)
        claimed = set(state.picked)
        valid_retries = set(state.provider_waiting_jobs) & counted & claimed
        for slug in set(state.provider_waiting_jobs) - valid_retries:
            state.provider_waiting_jobs.pop(slug, None)
        orphaned = counted - valid_retries
        restart_retry_worker = bool(valid_retries) and not state.provider_retry_worker_running

    if restart_retry_worker:
        _ensure_provider_retry_worker()

    for slug in sorted(orphaned):
        movie = state.fp_movies.get(slug)
        label = movie.title if movie is not None else slug
        on_job_done(
            False,
            "Downloadvorbereitung ohne Abschluss beendet",
            label,
            Path(""),
            slug=slug,
        )
    return len(orphaned)


def _on_queue_done_locked():
    # Ein alter Scheduler kann auslaufen, während bereits ein neuer
    # Vorbereitungsjob eingereiht wurde. Dann gehört dieses Done-Ereignis noch
    # nicht zum tatsächlichen Ende der gemeinsamen Auto-Queue.
    if state.dl_queue.active_count() or state.dl_queue.pending_count():
        return
    _reconcile_idle_queue_state_locked()
    # Während eines Provider-Cooldowns noch nicht „fertig" melden: Die offenen
    # Claims werden nach einer einzelnen erfolgreichen Probe fortgesetzt.
    if state.provider_waiting_jobs:
        log("Downloadlauf pausiert – Episoden warten auf den SerienStream-Provider.")
        return
    if state.voe_pool is not None:
        log("Schließe Browser-Pool …")
        try:
            state.voe_pool.close()
        except Exception as exc:
            log(f"Browser-Close Fehler: {exc}", "warn")
        finally:
            state.voe_pool = None
    if state.embed_pool is not None:
        log("Schließe Embed-Pool …")
        try:
            state.embed_pool.close()
        except Exception as exc:
            log(f"Embed-Close Fehler: {exc}", "warn")
        finally:
            state.embed_pool = None
    successful_jobs = len(state.done_slugs)
    failed_jobs = max(0, state.done_jobs - successful_jobs)
    log(f"Downloadlauf beendet: {successful_jobs} erfolgreich, {failed_jobs} fehlgeschlagen.")
    if successful_jobs:
        threading.Thread(target=refresh_jellyfin_after_download, daemon=True).start()
    broadcast({
        "type": "queue_done",
        "done_jobs": state.done_jobs,
        "total_jobs": state.total_jobs,
        "successful_jobs": successful_jobs,
        "failed_jobs": failed_jobs,
    })
    _updater_wake_event.set()


state.dl_queue.on_queue_done = on_queue_done


def _pause_downloads_for_update_restart() -> int:
    """Stoppt die physische Queue, ohne ihre persistenten Claims zu verlieren."""
    with state.queue_lifecycle_lock:
        with state.queue_claim_lock:
            preserved = set(state.picked)
            with state.download_state_lock:
                previous_counted = set(state.counted_queue_slugs)
                # Abbruch-Callbacks dürfen die gespeicherten Slugs nicht als
                # fachlich abgeschlossen verbuchen.
                state.counted_queue_slugs.clear()
            previous_waiting = dict(state.provider_waiting_jobs)
            state.provider_waiting_jobs.clear()
            if not _persist_queue_state():
                with state.download_state_lock:
                    state.counted_queue_slugs.update(previous_counted)
                state.provider_waiting_jobs.update(previous_waiting)
                raise RuntimeError(
                    "Queue-Zustand konnte vor dem Update nicht gesichert werden."
                )
        state.dl_queue.cancel_all()

    # Laufende yt-dlp-Prozesse und Browser-Tabs möglichst sauber beenden, bevor
    # execv den Server ersetzt. Nach spätestens 20 Sekunden übernimmt der
    # Prozessneustart; die Queue-Claims sind zu diesem Zeitpunkt bereits sicher.
    deadline = time.monotonic() + 20
    while state.dl_queue.active_count() and time.monotonic() < deadline:
        time.sleep(0.1)

    if state.hoster_extract_lock.acquire(timeout=10):
        try:
            for attr in ("voe_pool", "embed_pool"):
                pool = getattr(state, attr)
                if pool is None:
                    continue
                try:
                    pool.close()
                except Exception as exc:
                    log(f"Browser-Close vor Update fehlgeschlagen: {exc}", "warn")
                finally:
                    setattr(state, attr, None)
        finally:
            state.hoster_extract_lock.release()
    return len(preserved)


def _canonical_hoster_name(provider_name: str, resolved_url: str) -> str:
    """Bestimmt den Extraktor-Zweig (voe/doodstream/…) aus Provider-Label +
    aufgelöster Domain. VOE nutzt rotierende Mirror-Domains, daher zählt hier
    zuerst das Label."""
    p = (provider_name or "").lower()
    dom = urlparse(resolved_url or "").netloc.lower()
    if "voe" in p or "voe" in dom:
        return "voe"
    if "dood" in p or any(k in dom for k in ("dood", "vide0", "d000d", "d0o0d", "dooood", "ds2play")):
        return "doodstream"
    if "vidara" in p or any(key in dom for key in (
        "vidara", "vidmatrix", "vidchamp", "vidachamp", "vidavaca",
        "viewdara", "thebesthost",
    )):
        return "vidara"
    if "vidsonic" in p or "vidsonic" in dom:
        return "vidsonic"
    if "firestream" in p or "firestream" in dom:
        return "firestream"
    if (
        "fsst" in p or "vidhide" in p or "embed4me" in p or "seekplays" in p
        or any(key in dom for key in (
            "fsst", "incvideo", "kinoger.be", "embed4me", "seekplays",
        ))
    ):
        return "kinoger"
    return p


def _mark_serienstream_blocked(reason: str, error: str = "") -> dict:
    current = state.provider_health.status("serienstream")
    if current["state"] == COOLDOWN and current["remaining_seconds"] > 0:
        return current
    updated = state.provider_health.mark_blocked("serienstream", reason, error)
    minutes = max(1, int((updated["next_probe_at"] - time.time() + 59) // 60))
    label = "erneut blockiert" if int(updated["failure_count"]) > 1 else "Gate erkannt"
    log(f"SerienStream-{label} – Provider für {minutes} Minuten pausiert.", "warn")
    broadcast({"type": "provider_status", "provider": serienstream_provider_status()})
    return updated


def _probe_serienstream_once(item: Optional[dict]) -> bool:
    """Führt genau einen kontrollierten SerienStream-Netzwerkrequest aus."""
    try:
        sto = get_sto_scraper()
        if item is not None:
            movie = item["movie"]
            redirect = next(
                (hoster for hoster in movie.hosters if sto.is_redirect_url(hoster.url)),
                None,
            )
            if redirect is not None:
                with state.sto_lock:
                    sto.reset_gate()
                    target = sto.resolve_play_url(redirect.url, referer=movie.url)
                    if target:
                        state.resolved_link_cache.put(redirect.url, target)
                if not target:
                    _mark_serienstream_blocked(
                        sto.last_block_reason or "captcha_gate", "Provider-Probe blockiert",
                    )
                    return False
                # Das erfolgreiche Probe-Ergebnis wiederverwenden, ohne die
                # Quell-URL im Movie zu verlieren. Ein Download-Retry kann den
                # Cache dadurch gezielt verwerfen und genau einmal neu auflösen.
                item["probe_verified_redirect"] = True
                state.fp_movies[item["slug"]] = movie
                return True
            with state.sto_lock:
                sto.reset_gate()
                movie = _apply_provider_metadata(
                    sto.get_movie(item["slug"]), "serienstream",
                )
            if movie and movie.hosters:
                item["movie"] = movie
                state.fp_movies[item["slug"]] = movie
                return True
            raise RuntimeError("Episodenseite lieferte keine Hoster")
        with state.sto_lock:
            sto.reset_gate()
            html = sto.session.get("https://serienstream.to/", fast=True)
        if not html:
            raise RuntimeError("Leere Provider-Antwort")
        return True
    except ProviderBlockedError as exc:
        _mark_serienstream_blocked(exc.reason, str(exc))
    except Exception as exc:
        _mark_serienstream_blocked("probe_failed", str(exc))
    return False


def _resume_waiting_provider_jobs(first_item: Optional[dict] = None) -> None:
    preferred = first_item
    while state.provider_health.request_allowed("serienstream"):
        with state.queue_claim_lock:
            item = preferred
            preferred = None
            if item is None:
                item = next(iter(state.provider_waiting_jobs.values()), None)
            if item is None:
                return
            slug = item["slug"]
            state.provider_waiting_jobs.pop(slug, None)
            claimed = slug in state.picked and slug in state.counted_queue_slugs
        if not claimed:
            continue
        try:
            with state.queue_prepare_lock:
                run_download_queue(
                    [(item["movie"], slug)],
                    item["out_root"],
                    movie_fallbacks=item["movie_fallbacks"],
                )
        except Exception as exc:
            log(f"Provider-Retry für «{slug}» fehlgeschlagen: {exc}", "warn")
            _mark_serienstream_blocked("probe_failed", str(exc))
            _defer_provider_episode(
                item["movie"], slug, item["out_root"], item["movie_fallbacks"],
            )
            return


def _execute_provider_probe(item: Optional[dict]) -> None:
    log("SerienStream-Probe gestartet.")
    with state.queue_prepare_lock:
        successful = _probe_serienstream_once(item)
    if not successful:
        return
    state.provider_health.mark_success(
        "serienstream",
        reset_failures=bool(item and item.pop("probe_verified_redirect", False)),
    )
    log("SerienStream-Probe erfolgreich – Provider wieder verfügbar.")
    broadcast({"type": "provider_status", "provider": serienstream_provider_status()})
    _resume_waiting_provider_jobs(item)


def _retry_one_waiting_fallback() -> bool:
    """Prüft genau eine wartende Episode erneut ausschließlich bei Fallbacks.

    SerienStream bleibt dabei im Cooldown und wird von ``run_download_queue``
    nicht angefragt. Das verhindert, dass ein kurzer Huhu-/Moflix-Aussetzer eine
    Episode unnötig bis zur deutlich späteren SerienStream-Probe festhält.
    """
    if not state.queue_prepare_lock.acquire(blocking=False):
        return False
    item = None
    slug = ""
    try:
        if state.provider_health.status("serienstream")["state"] != COOLDOWN:
            return False
        with state.queue_claim_lock:
            item = next(iter(state.provider_waiting_jobs.values()), None)
            if item is None:
                return False
            slug = item["slug"]
            state.provider_waiting_jobs.pop(slug, None)
            if slug not in state.picked or slug not in state.counted_queue_slugs:
                return False
            state.preparing_queue_slugs.add(slug)
        parsed = parse_episode_slug(slug)
        label = (
            f"S{parsed[1]:02d}E{parsed[2]:02d}" if parsed else slug
        )
        log(f"Fallback wird kontrolliert erneut geprüft: {label}.")
        broadcast({"type": "queue_update", "queue": build_queue_payload()})
        run_download_queue(
            [(item["movie"], slug)],
            item["out_root"],
            movie_fallbacks=item["movie_fallbacks"],
        )
        return True
    except Exception as exc:
        log(f"Fallback-Wiederholung für «{slug}» fehlgeschlagen: {exc}", "warn")
        if item is not None and slug:
            _defer_provider_episode(
                item["movie"], slug, item["out_root"], item["movie_fallbacks"],
            )
        return True
    finally:
        if slug:
            with state.queue_claim_lock:
                state.preparing_queue_slugs.discard(slug)
            broadcast({"type": "queue_update", "queue": build_queue_payload()})
        state.queue_prepare_lock.release()


def _provider_retry_worker() -> None:
    next_fallback_retry = time.monotonic() + appconfig.SERIES_FALLBACK_RETRY_SECONDS
    try:
        while True:
            with state.queue_claim_lock:
                item = next(iter(state.provider_waiting_jobs.values()), None)
            if item is None:
                return
            status = state.provider_health.status("serienstream")
            if status["state"] == HEALTHY:
                _resume_waiting_provider_jobs()
                continue
            if status["state"] == PROBING:
                state.provider_retry_wake_event.wait(1)
                state.provider_retry_wake_event.clear()
                continue
            if status["remaining_seconds"] > 0:
                delay = max(0.0, next_fallback_retry - time.monotonic())
                if delay <= 0:
                    if _retry_one_waiting_fallback():
                        next_fallback_retry = (
                            time.monotonic() + appconfig.SERIES_FALLBACK_RETRY_SECONDS
                        )
                    else:
                        # Eine normale Episodenvorbereitung hat Vorrang. Kurz
                        # danach erneut versuchen, ohne im Sekundentakt zu loggen.
                        next_fallback_retry = time.monotonic() + 5
                    continue
                state.provider_retry_wake_event.wait(min(
                    30, status["remaining_seconds"], delay,
                ))
                state.provider_retry_wake_event.clear()
                continue
            if state.provider_health.begin_probe("serienstream"):
                _execute_provider_probe(item)
            else:
                state.provider_retry_wake_event.wait(1)
                state.provider_retry_wake_event.clear()
    finally:
        with state.queue_claim_lock:
            state.provider_retry_worker_running = False
            restart = bool(state.provider_waiting_jobs)
        if restart:
            _ensure_provider_retry_worker()


def _ensure_provider_retry_worker() -> None:
    with state.queue_claim_lock:
        if state.provider_retry_worker_running or not state.provider_waiting_jobs:
            return
        state.provider_retry_worker_running = True
    threading.Thread(target=_provider_retry_worker, daemon=True).start()


def _defer_provider_episode(
    movie: FilmpalastMovie,
    slug: str,
    out_root: Path,
    movie_fallbacks: Optional[Dict[str, List[FilmpalastMovie]]] = None,
) -> bool:
    """Behält eine Episode bis zur nächsten einzelnen Provider-Probe offen."""
    with state.queue_claim_lock:
        if slug not in state.picked or slug not in state.counted_queue_slugs:
            return False
        state.provider_waiting_jobs[slug] = {
            "movie": movie,
            "slug": slug,
            "out_root": Path(out_root),
            "movie_fallbacks": movie_fallbacks,
        }
    _persist_queue_state()
    broadcast({"type": "queue_update", "queue": build_queue_payload()})
    _ensure_provider_retry_worker()
    return True


def _episode_fallback_aliases(movie_slug: str, title: str) -> tuple[str, ...]:
    """Liefert alternative Katalogtitel fuer eine Episode.

    serienstream zeigt haeufig den deutschen Titel, waehrend ein Backup den
    Originaltitel fuehrt. Der Serien-Slug, Watchlist-Aliase und TMDB schliessen
    diese Luecke, ohne unscharfe Episodenmatches zuzulassen.
    """
    values: List[str] = []
    parsed = parse_episode_slug(movie_slug)
    base_slug = parsed[0] if parsed else movie_slug
    slug_title = _series_search_title(base_slug)
    if slug_title:
        values.append(slug_title)

    tmdb_id = ""
    with state.watchlist_lock:
        entry = watchlist_lookup(base_slug)
        if entry:
            tmdb_id = str(entry.get("tmdb_id") or "")
            values.append(str(entry.get("title") or ""))
            values.extend(str(value or "") for value in entry.get("aliases") or [])
    try:
        tmdb = get_tmdb_series(title, tmdb_id)
    except Exception as exc:
        log(f"  TMDB-Aliase fuer Serien-Fallback nicht ladbar: {exc}", "warn")
        tmdb = None
    if tmdb:
        values.extend((
            str(tmdb.get("title") or ""),
            str(tmdb.get("original_title") or ""),
        ))

    seen = {_norm_title(title)}
    aliases: List[str] = []
    for value in values:
        value = " ".join(value.split()).strip()
        key = _norm_title(value)
        if not key or key in seen:
            continue
        seen.add(key)
        aliases.append(value)
    return tuple(aliases)


def _fallback_get_series(
    provider: str, title: str, tmdb_id: str = "",
) -> Optional[FilmpalastSeries]:
    """Sucht die Serie «title» beim Fallback-Anbieter per Titel-Match und lädt sie.
    Ergebnis (auch None) wird pro Download-Lauf gecacht, damit nicht jede Episode
    denselben Anbieter erneut durchsucht."""
    exact_tmdb_id = str(tmdb_id or "").strip() if provider == "huhu" else ""
    if exact_tmdb_id and not exact_tmdb_id.isdigit():
        exact_tmdb_id = ""
    key = (
        f"{provider}:tmdb:{exact_tmdb_id}"
        if exact_tmdb_id else f"{provider}:{_norm_title(title)}"
    )
    now = time.time()
    with state.fallback_series_cache_lock:
        provider_error = state.fallback_provider_errors.get(provider)
        if provider_error and provider_error[0] > now:
            return None
        state.fallback_provider_errors.pop(provider, None)
        cached = state.fallback_series_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        state.fallback_series_cache.pop(key, None)
    series: Optional[FilmpalastSeries] = None
    matched = False
    try:
        if exact_tmdb_id:
            matched = True
            series = _load_series_for_provider(
                provider, f"{HUHU_PREFIX}{exact_tmdb_id}:tmdb",
            )
        else:
            results = _search_series_for_provider(provider, title)
            wanted = _norm_title(title)
            best = next(
                (result for result in results if _norm_title(result.title) == wanted),
                None,
            )
            matched = best is not None
            series = _load_series_for_provider(provider, best.sample_slug) if best else None
    except Exception as exc:
        label = PROVIDER_LABELS.get(provider, provider)
        log(f"  {label}-Fallback-Suche vorübergehend nicht erreichbar: {exc}", "warn")
        # Netzwerk-/Cloudflare-Fehler sind kein bestaetigtes "nicht vorhanden".
        # Nur eine kurze providerweite Sperre verhindert, dass derselbe Fehler
        # fuer jeden Alias und jede Episode sofort erneut ausgelöst wird.
        with state.fallback_series_cache_lock:
            state.fallback_provider_errors[provider] = (
                now + appconfig.SERIES_PROVIDER_TRANSIENT_ERROR_TTL_SECONDS,
                str(exc),
            )
        return None
    with state.fallback_series_cache_lock:
        state.fallback_provider_errors.pop(provider, None)
    if series and not series.seasons:
        return None
    if matched and series is None:
        # Treffer vorhanden, Detailseite aber temporaer nicht ladbar.
        return None
    with state.fallback_series_cache_lock:
        state.fallback_series_cache[key] = (
            now + appconfig.SERIES_PROVIDER_FALLBACK_CACHE_TTL_SECONDS,
            series,
        )
    return series


# Nur als überschreibbarer Kompatibilitätspunkt für bestehende Integrationen;
# None bedeutet: immer die live konfigurierte Reihenfolge verwenden.
SERIES_FALLBACK_PROVIDERS: Optional[tuple[str, ...]] = None


def find_episode_fallbacks(
    title: str,
    season: int,
    episode: int,
    aliases: tuple[str, ...] = (),
    source_slug: str = "",
    excluded_providers: Optional[set[str]] = None,
    limit: int = 0,
) -> List[FilmpalastMovie]:
    """Lädt dieselbe Episode bei allen passenden Fallback-Katalogen.

    ``limit=1`` startet den ersten exakten Treffer sofort. Weitere Kataloge
    werden erst bei einem Laufzeitfehler dieses Treffers nachgeladen; so hält
    ein langsamer oder gesperrter späterer Anbieter den Download nicht auf.
    """
    movies: List[FilmpalastMovie] = []
    seen_urls: set[str] = set()
    search_titles: List[str] = []
    seen_titles: set[str] = set()
    for candidate in (title, *aliases):
        candidate = " ".join(str(candidate or "").split()).strip()
        key = _norm_title(candidate)
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        search_titles.append(candidate)

    source_provider = provider_for_value(source_slug) if source_slug else ""
    skipped_providers = {
        str(provider or "").strip().casefold()
        for provider in (excluded_providers or set())
        if str(provider or "").strip()
    }
    tmdb_id = ""
    parsed_source = parse_episode_slug(source_slug)
    source_base_slug = parsed_source[0] if parsed_source else source_slug
    with state.watchlist_lock:
        watch_entry = watchlist_lookup(source_base_slug)
        if watch_entry:
            tmdb_id = str(watch_entry.get("tmdb_id") or "").strip()
    fallback_providers = SERIES_FALLBACK_PROVIDERS or tuple(provider_priority("series"))
    searched_labels = [
        PROVIDER_LABELS.get(provider, provider)
        for provider in fallback_providers
        if provider != source_provider
    ]
    if searched_labels:
        log(
            f"  Fallback-Suche S{season:02d}E{episode:02d}: "
            + " → ".join(searched_labels)
        )
    for provider in fallback_providers:
        if provider == source_provider or provider in skipped_providers:
            continue
        series = None
        for search_title in search_titles:
            series = _fallback_get_series(provider, search_title, tmdb_id=tmdb_id)
            if series:
                break
        if not series:
            continue
        ep = next((e for e in series.seasons.get(season, []) if e.episode == episode), None)
        if not ep:
            label = PROVIDER_LABELS.get(provider, provider)
            log(f"  {label}: S{season:02d}E{episode:02d} nicht im Katalog", "warn")
            continue
        label = PROVIDER_LABELS.get(provider, provider)
        log(f"  → Fallback {label}: S{season:02d}E{episode:02d} gefunden, lade Hoster …")
        try:
            movie = load_movie_for_slug(ep.slug)
        except Exception as exc:
            log(f"  {label}-Fallback Laden fehlgeschlagen: {exc}", "warn")
            movie = None
        if movie and movie.hosters and movie.url not in seen_urls:
            seen_urls.add(movie.url)
            movies.append(movie)
            if limit > 0 and len(movies) >= limit:
                break
            continue
        log(f"  {label}: keine nutzbaren Hoster für die Episode", "warn")
    return movies


class _HosterResult:
    """Ergebnis eines Hoster-Extraktionsversuchs für genau einen Movie/Episode."""
    __slots__ = (
        "stream_info", "hoster_used", "hoster_url_used", "source_hoster_url",
        "referer", "origin", "gated", "provider", "content_language", "quality",
        "resolved_from_cache",
    )

    def __init__(self):
        self.stream_info = None
        self.hoster_used = ""
        self.hoster_url_used = ""
        self.source_hoster_url = ""
        self.referer = "https://filmpalast.to/"
        self.origin = ""
        self.gated = False   # serienstream Captcha-Gate war aktiv
        self.provider = ""
        self.content_language = ""
        self.quality = ""
        self.resolved_from_cache = False


def _extract_from_movie(
    movie: FilmpalastMovie,
    unsupported_domains: set,
    excluded_hoster_urls: Optional[set] = None,
    barren_hoster_urls: Optional[set] = None,
) -> _HosterResult:
    """Probiert der Reihe nach die Hoster eines Movies (nach hoster_intel-Ranking)
    durch, löst serienstream-Redirects lazy auf und liefert den ersten nutzbaren
    Stream. Funktioniert für alle konfigurierten Katalogquellen, da Nicht-s.to-
    Hoster einfach ihre direkte URL verwenden."""
    res = _HosterResult()
    res.provider = _movie_provider(movie)
    if (
        res.provider == "serienstream"
        and not state.provider_health.request_allowed("serienstream")
    ):
        # Direkte/cached Hoster duerfen weiterlaufen. Falls sie scheitern, muss
        # der logische Job aber bis zur Provider-Probe vorgemerkt bleiben.
        res.gated = True
    res.content_language = _movie_content_language(movie)
    session = state.fp_scraper.session._curl if state.fp_scraper else None
    excluded_hoster_urls = excluded_hoster_urls or set()
    # Ergebnislose Extraktionen dieses Laufs. Ein Embed, das schon einmal die
    # komplette Browser-Kette ohne Stream-URL durchlaufen hat, liefert Sekunden
    # später dasselbe Nichts – kostet aber erneut die volle Wartezeit.
    if barren_hoster_urls is None:
        barren_hoster_urls = set()

    ranked_hosters = state.hoster_intel.rank(movie.hosters)
    preferred_quality_value = getattr(movie, "_preferred_quality", None)
    if preferred_quality_value is not None:
        preferred_quality = str(preferred_quality_value or "").strip().casefold()
        ranked_hosters.sort(
            key=lambda hoster: str(hoster.quality or "").strip().casefold() != preferred_quality
        )
    for hoster in ranked_hosters:
        if not hoster.url:
            continue
        if hoster.url in excluded_hoster_urls:
            log(f"  Überspringe {hoster.name}: Download zuvor fehlgeschlagen", "warn")
            continue
        if hoster.url in barren_hoster_urls:
            log(f"  Überspringe {hoster.name}: lieferte zuvor keine Stream-URL", "warn")
            continue
        name = hoster.name.lower()
        if hoster.url in unsupported_domains:
            log(f"  Überspringe {hoster.name}: Link nicht unterstützt", "warn")
            continue
        cooldown, _reason = state.hoster_intel.cooldown(
            hoster.url, hoster_name=hoster.name,
        )
        if cooldown:
            minutes = max(1, (cooldown + 59) // 60)
            log(
                f"  Überspringe {hoster.name}: nach Ausfällen noch "
                f"{minutes} Min. pausiert",
                "warn",
            )
            continue
        res.hoster_used = hoster.name
        res.quality = str(getattr(hoster, "quality", "") or "").strip()
        res.source_hoster_url = hoster.url
        res.content_language = _movie_content_language(
            movie,
            str(getattr(hoster, "language", "") or ""),
        )
        log(f"  Versuche Hoster: {hoster.name}")

        # serienstream.to liefert Hoster als lazy /r?t=-Redirect. Erst JETZT,
        # für genau diesen Versuch, zur echten Embed-URL auflösen. So bleibt
        # die Zahl der s.to-Requests minimal (meist genau 1) und das Captcha
        # wird gar nicht erst provoziert. Fällt ein Hoster durch, wird nur der
        # nächste aufgelöst.
        was_sto = SerienstreamScraper.is_redirect_url(hoster.url)
        play_url = hoster.url
        resolved_by_provider = False
        if was_sto:
            cached_target = state.resolved_link_cache.get(hoster.url)
            if cached_target:
                play_url = cached_target
                res.resolved_from_cache = True
                # Der bekannte Ziel-Link ist weiterhin nutzbar, obwohl keine
                # neue Provider-Anfrage erlaubt ist. Merken, dass ein spaeterer
                # Fehlschlag trotzdem bis zur naechsten Probe warten muss.
                if not state.provider_health.request_allowed("serienstream"):
                    res.gated = True
                log(f"  {hoster.name}: bereits aufgelösten Hoster-Link verwenden")
            else:
                # Ein Cache-Treffer benötigt keinen Provider-Request und darf
                # deshalb auch im Cooldown weiter zum Hoster. Nur Cache-Misses
                # durchlaufen den Circuit-Breaker.
                if not state.provider_health.request_allowed("serienstream"):
                    res.gated = True
                    break
                sto = get_sto_scraper()
                with state.sto_lock:
                    # Double-check nach dem Lock: Ein paralleler Worker kann
                    # denselben Redirect inzwischen bereits aufgeloest haben.
                    locked_target = state.resolved_link_cache.get(hoster.url)
                    if locked_target:
                        play_url = locked_target
                        res.resolved_from_cache = True
                    else:
                        # Zwischen Statusprüfung und Lock kann eine andere
                        # Anfrage das Gate erkannt haben. Vor dem Redirect
                        # deshalb atomar noch einmal prüfen.
                        if not state.provider_health.request_allowed("serienstream"):
                            res.gated = True
                            break
                        # Ist das Captcha-Gate aktiv, sind ALLE Hoster blockiert
                        # – nicht weiter hämmern, sondern sofort abbrechen.
                        if sto.gated:
                            _mark_serienstream_blocked(
                                sto.last_block_reason or "captcha_gate",
                                "SerienStream-Gate ist bereits aktiv",
                            )
                            res.gated = True
                            break
                        play_url = sto.resolve_play_url(hoster.url, referer=movie.url)
                        if play_url:
                            resolved_by_provider = True
                            state.resolved_link_cache.put(hoster.url, play_url)
                if not play_url:
                    if sto.gated:
                        _mark_serienstream_blocked(
                            sto.last_block_reason or "captcha_gate",
                            "SerienStream-Redirect-Gate blockiert",
                        )
                        res.gated = True
                        break
                    log(f"  {hoster.name}: S.to-Link nicht auflösbar – nächster Hoster", "warn")
                    continue
                if (
                    resolved_by_provider
                    and state.provider_health.status("serienstream")["failure_count"]
                ):
                    state.provider_health.mark_success("serienstream")
            name = _canonical_hoster_name(hoster.name, play_url)
            if play_url in unsupported_domains:
                log(f"  Überspringe {hoster.name}: Link nicht unterstützt", "warn")
                continue
            if play_url in barren_hoster_urls:
                # s.to rotiert die Redirect-URLs, das Embed-Ziel bleibt gleich.
                log(f"  Überspringe {hoster.name}: lieferte zuvor keine Stream-URL", "warn")
                continue
        name = _canonical_hoster_name(hoster.name, play_url)
        res.hoster_url_used = play_url
        cooldown, _reason = state.hoster_intel.cooldown(
            play_url, hoster_name=hoster.name,
        )
        if cooldown:
            minutes = max(1, (cooldown + 59) // 60)
            log(
                f"  Überspringe {hoster.name}: Zielhost noch "
                f"{minutes} Min. pausiert",
                "warn",
            )
            continue

        if name == "voe":
            if state.voe_pool is None:
                log("Starte Browser-Pool für VOE-Fallback …")
                try:
                    state.voe_pool = VOEBrowserPool(log_cb=log)
                except Exception as exc:
                    log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                    state.voe_pool = None
                    continue
            check = pre_check_voe(play_url, session=session)
            if check == VOE_NOT_FOUND:
                log("  VOE 404 – nächster Hoster", "warn")
                continue
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=state.voe_pool,
                )
            except Exception as exc:
                log(f"  VOE-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else "https://voe.sx"
        elif (
            name.startswith("filmfrei24")
            or provider_for_value(movie.url) == "filmfrei24"
        ):
            # Eigener öffentlicher VOD-HLS-Stream; kein Embed- oder
            # Browser-Extraktor nötig. Der Scraper liefert zuerst den offiziellen
            # Proxy und danach den direkten TV-Endpunkt als Ausweichroute.
            res.stream_info = (play_url, "hls")
            res.referer = movie.url or f"{FILMFREI24_BASE_URL}/"
            res.origin = FILMFREI24_BASE_URL
        elif name in ("moflix", "veev"):
            embed_referer = (
                movie.url if provider_for_value(movie.url) == "megakino"
                else "https://moflix-stream.xyz/"
            )
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=None,
                    referer=embed_referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für Embed-Fallback …")
                        try:
                            state.embed_pool = VOEBrowserPool(log_cb=log, setup_voe=False)
                        except Exception as exc:
                            log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                            state.embed_pool = None
                            continue
                    res.stream_info = extract_stream_url(
                        play_url, session=session, log_cb=log, pool=state.embed_pool,
                        referer=embed_referer,
                        browser_wait_seconds=12,
                    )
            except Exception as exc:
                log(f"  Embed-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        elif name == "kinoger":
            referer = movie.url or "https://kinoger.com/"
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für KinoGer-Mirror …")
                        try:
                            state.embed_pool = VOEBrowserPool(log_cb=log, setup_voe=False)
                        except Exception as exc:
                            log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                            state.embed_pool = None
                            continue
                    res.stream_info = extract_stream_url(
                        play_url, session=session, log_cb=log, pool=state.embed_pool,
                        referer=referer,
                        browser_wait_seconds=12,
                    )
            except Exception as exc:
                log(f"  KinoGer-Mirror fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        elif name == "doodstream":
            try:
                res.stream_info = extract_doodstream_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  Doodstream-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif name == "vidara":
            # VIDARA (vidmatrixa.com u.a.) – von yt-dlp nicht unterstützt, eigener
            # Extraktor (POST /api/stream → streaming_url, HLS).
            try:
                res.stream_info = extract_vidara_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  VIDARA-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif name == "vidsonic":
            # Vidsonic (vidsonic.net) – von yt-dlp nicht unterstützt, eigener
            # Extraktor (hex-kodierte + umgekehrte URL im HTML, HLS).
            try:
                res.stream_info = extract_vidsonic_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  Vidsonic-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif name == "firestream":
            try:
                res.stream_info = extract_firestream_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  FireStream-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif provider_for_value(movie.url) == "megakino":
            # MegaKino nimmt regelmaessig neue Player-Domains auf. Erst wird
            # ohne Browser nach direkten HLS-/MP4-Quellen gesucht, danach faengt
            # der gemeinsame Embed-Pool Medienrequests ab. Als letzter Weg darf
            # yt-dlp die unveraenderte Player-URL versuchen.
            referer = movie.url or "https://megakino.org/"
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für MegaKino-Hoster …")
                        try:
                            state.embed_pool = VOEBrowserPool(log_cb=log, setup_voe=False)
                        except Exception as exc:
                            log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                            state.embed_pool = None
                    if state.embed_pool is not None:
                        res.stream_info = extract_stream_url(
                            play_url, session=session, log_cb=log, pool=state.embed_pool,
                            referer=referer,
                            browser_wait_seconds=10,
                        )
            except Exception as exc:
                log(f"  MegaKino-Hoster fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            if res.stream_info is None:
                res.stream_info = (play_url, "web")
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        elif provider_for_value(movie.url) == "sflix":
            # Die SFlix-Player (UpCloud/Vidsrc/…) sind generische Embed-Seiten.
            # Direkte Regex-Auflösung bleibt billig; der gemeinsame Browser-Pool
            # fängt als Fallback den signierten HLS-Request des Players ab.
            referer = movie.url or f"{SFLIX_BASE_URL}/"
            try:
                res.stream_info = extract_stream_url(
                    play_url,
                    session=session,
                    log_cb=log,
                    pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für SFlix-Hoster …")
                        try:
                            state.embed_pool = VOEBrowserPool(
                                log_cb=log,
                                setup_voe=False,
                            )
                        except Exception as exc:
                            log(
                                f"Browser-Pool konnte nicht starten: {exc}",
                                "warn",
                            )
                            state.embed_pool = None
                    if state.embed_pool is not None:
                        res.stream_info = extract_stream_url(
                            play_url,
                            session=session,
                            log_cb=log,
                            pool=state.embed_pool,
                            referer=referer,
                            browser_wait_seconds=12,
                        )
            except Exception as exc:
                log(f"  SFlix-Hoster fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            if res.stream_info is None:
                res.stream_info = (play_url, "web")
            res.referer = referer
            res.origin = SFLIX_BASE_URL
        elif provider_for_value(movie.url) == "ridomovies":
            # Closeload/Rapidrame sind generische Embed-Player. Erst die
            # günstige HTML-Auflösung probieren, dann den gemeinsamen
            # Browser-Pool für signierte Medienrequests verwenden.
            referer = movie.url or f"{RIDOMOVIES_BASE_URL}/"
            try:
                res.stream_info = extract_stream_url(
                    play_url,
                    session=session,
                    log_cb=log,
                    pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für Ridomovies-Hoster …")
                        try:
                            state.embed_pool = VOEBrowserPool(
                                log_cb=log,
                                setup_voe=False,
                            )
                        except Exception as exc:
                            log(
                                f"Browser-Pool konnte nicht starten: {exc}",
                                "warn",
                            )
                            state.embed_pool = None
                    if state.embed_pool is not None:
                        res.stream_info = extract_stream_url(
                            play_url,
                            session=session,
                            log_cb=log,
                            pool=state.embed_pool,
                            referer=referer,
                            browser_wait_seconds=12,
                        )
            except Exception as exc:
                log(f"  Ridomovies-Hoster fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            if res.stream_info is None:
                res.stream_info = (play_url, "web")
            res.referer = referer
            res.origin = RIDOMOVIES_BASE_URL
        elif provider_for_value(movie.url) == "mkissa":
            # MKissa liefert direkte Streams und generische Anime-Embeds.
            # Direkte Medien bleiben unangetastet; Embed-Player durchlaufen
            # zunächst die billige Extraktion und danach den Browser-Pool.
            referer = f"{MKISSA_BASE_URL}/"
            parsed = urlparse(play_url)
            if parsed.path.casefold().endswith((".m3u8", ".mp4")):
                res.stream_info = (play_url, "web")
            else:
                try:
                    res.stream_info = extract_stream_url(
                        play_url,
                        session=session,
                        log_cb=log,
                        pool=None,
                        referer=referer,
                    )
                    if res.stream_info is None:
                        if state.embed_pool is None:
                            log("Starte Browser-Pool für MKissa-Hoster …")
                            try:
                                state.embed_pool = VOEBrowserPool(
                                    log_cb=log,
                                    setup_voe=False,
                                )
                            except Exception as exc:
                                log(
                                    f"Browser-Pool konnte nicht starten: {exc}",
                                    "warn",
                                )
                                state.embed_pool = None
                        if state.embed_pool is not None:
                            res.stream_info = extract_stream_url(
                                play_url,
                                session=session,
                                log_cb=log,
                                pool=state.embed_pool,
                                referer=referer,
                                browser_wait_seconds=12,
                            )
                except Exception as exc:
                    log(f"  MKissa-Hoster fehlgeschlagen: {exc}", "warn")
                    res.stream_info = None
                if res.stream_info is None:
                    res.stream_info = (play_url, "web")
            res.referer = referer
            res.origin = "https://mkissa.to"
        else:
            # Generischer Hoster (Streamtape/Vidoza/Vidmoly/Filemoon/…):
            # yt-dlp probieren lassen. Referer = eigene Hoster-Domain
            # (bei s.to-Auflösung), sonst filmpalast wie gehabt.
            res.stream_info = (play_url, "web")
            if was_sto:
                parsed = urlparse(play_url)
                res.referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else "https://filmpalast.to/"
            else:
                res.referer = "https://filmpalast.to/"
            res.origin = ""

        if res.stream_info:
            stream_url, _stream_type = res.stream_info
            log(f"  Prüfe Hoster: {hoster.name}")
            ok, probe_msg = probe_stream_url(stream_url, referer=res.referer, origin=res.origin)
            state.hoster_intel.record_probe(
                play_url, ok, probe_msg, hoster_name=hoster.name,
            )
            if not ok:
                log(f"  {hoster.name} nicht nutzbar: {probe_msg}", "warn")
                if "unsupported url" in probe_msg.lower():
                    unsupported_domains.add(play_url)
                res.stream_info = None
                continue
            break
        else:
            # Der Extraktor lief vollständig durch, ohne eine Stream-URL zu
            # finden. Innerhalb dieses Laufs nicht erneut versuchen.
            barren_hoster_urls.add(hoster.url)
            if play_url:
                barren_hoster_urls.add(play_url)

    return res


def find_movie_source_fallbacks(
    movie: FilmpalastMovie,
    selected_slug: str,
    excluded_urls: set,
) -> List[FilmpalastMovie]:
    """Sucht denselben Film erst dann bei anderen Katalogquellen, wenn alle
    Hoster des ausgewählten Treffers zur Laufzeit gescheitert sind."""
    title = clean_movie_title(movie.title)
    wanted = _norm_title(title)
    wanted_year = str(movie.year or "")
    if not wanted:
        return []
    log(f"  Suche alternative Filmquellen für «{title}» …", "warn")
    alternatives: List[FilmpalastMovie] = []
    seen_urls = set(excluded_urls)
    try:
        candidates = search_movie_candidates(title)
    except Exception as exc:
        log(f"  Alternative Filmquellen nicht durchsuchbar: {exc}", "warn")
        return []

    for candidate in candidates:
        if not candidate.is_movie or candidate.slug == selected_slug:
            continue
        if _norm_title(candidate.title) != wanted:
            continue
        candidate_year = str(candidate.year or "")
        if wanted_year and candidate_year and candidate_year != wanted_year:
            continue
        if candidate.url in seen_urls:
            continue
        try:
            loaded = state.fp_movies.get(candidate.slug) or load_movie_for_slug(candidate.slug)
        except Exception as exc:
            log(f"  Filmquelle {candidate.title} nicht ladbar: {exc}", "warn")
            continue
        if not loaded or not loaded.hosters or _norm_title(loaded.title) != wanted:
            continue
        loaded_year = str(loaded.year or candidate_year or "")
        if wanted_year and loaded_year and loaded_year != wanted_year:
            continue
        if loaded.url in seen_urls:
            continue
        state.fp_movies[candidate.slug] = loaded
        seen_urls.add(loaded.url)
        alternatives.append(loaded)
        if len(alternatives) >= 6:
            break

    if alternatives:
        log(f"  {len(alternatives)} alternative Filmquelle(n) vorbereitet.")
    else:
        log("  Keine weitere Filmquelle mit exakt passendem Titel/Jahr gefunden.", "warn")
    return alternatives


def _enqueue_hoster_attempt(
    movie: FilmpalastMovie,
    movie_slug: str,
    out_path: Path,
    result: _HosterResult,
    unsupported_domains: set,
    failed_hoster_urls: set,
    attempt_errors: List[str],
    source_movies: List[FilmpalastMovie],
    source_index: int,
    source_fallbacks_loaded: List[bool],
    refreshed_hoster_urls: set,
    barren_hoster_urls: Optional[set] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    gate_seen: Optional[List[bool]] = None,
    gate_retry: Optional[Callable[[], bool]] = None,
    slow_candidates: Optional[List[tuple]] = None,
    last_resort: bool = False,
):
    """Startet einen Downloadversuch und schaltet bei Laufzeitfehlern auf den
    nächsten Hoster um. Ein logischer Job wird erst nach Erfolg oder nach dem
    letzten Anbieter als abgeschlossen gemeldet."""
    if (cancelled and cancelled()) or not _queue_slug_claimed(movie_slug):
        return False
    gate_seen = gate_seen or [bool(result.gated)]
    gate_seen[0] = gate_seen[0] or bool(result.gated)
    if barren_hoster_urls is None:
        barren_hoster_urls = set()
    if slow_candidates is None:
        slow_candidates = []
    stream_url, stream_type = result.stream_info
    hoster_used = result.hoster_used
    label = f"{movie.title}  ({hoster_used})"
    log(f"  Stream bereit ({hoster_used}): {stream_url[:60]}…")

    def _attempt_done(ok: bool, msg: str):
        if result.hoster_url_used:
            state.hoster_intel.record_download(
                result.hoster_url_used,
                ok,
                hoster_name=hoster_used,
                speed_bps=getattr(job, "average_speed_bps", 0),
                failure_kind=getattr(job, "failure_kind", ""),
            )
        if ok:
            if not parse_episode_slug(movie_slug):
                _movie_subscription_download_finished(movie_slug, out_path, result.quality)
            on_job_done(True, msg, label, out_path, slug=movie_slug)
            return
        if msg == "Abgebrochen":
            on_job_done(False, msg, label, out_path, slug=movie_slug)
            return
        if (cancelled and cancelled()) or not _queue_slug_claimed(movie_slug):
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug)
            return

        is_slow = getattr(job, "failure_kind", "") == "slow"
        if last_resort:
            final_msg = "; ".join(attempt_errors + [f"Letzte langsame Reserve: {msg}"])
            on_job_done(False, final_msg, label, out_path, slug=movie_slug)
            return
        if is_slow:
            source_key = result.source_hoster_url or result.hoster_url_used
            if not any(
                (candidate_result.source_hoster_url or candidate_result.hoster_url_used) == source_key
                for _candidate_movie, candidate_result, _speed in slow_candidates
            ):
                slow_candidates.append((
                    movie,
                    result,
                    float(getattr(job, "average_speed_bps", 0) or 0),
                ))

        # Signierte CDN-Links können zwischen Probe und Download ablaufen. Den
        # gleichen Hoster genau einmal frisch extrahieren, bevor er ausscheidet.
        source_url = result.source_hoster_url
        if not is_slow and source_url and source_url not in refreshed_hoster_urls:
            refreshed_hoster_urls.add(source_url)
            log(f"  {hoster_used}: Link wird einmal frisch aufgelöst …", "warn")
            # Ein abgelaufener Hoster-/CDN-Link darf genau einen Cache-Miss
            # erzeugen. Bei aktivem SerienStream-Cooldown bricht die folgende
            # Extraktion vor jedem Provider-Request ab und nutzt Fallbacks.
            state.resolved_link_cache.invalidate(
                source_url, result.hoster_url_used,
            )
            with state.hoster_extract_lock:
                refreshed = _extract_from_movie(
                    movie,
                    unsupported_domains,
                    excluded_hoster_urls=failed_hoster_urls,
                    barren_hoster_urls=barren_hoster_urls,
                )
            gate_seen[0] = gate_seen[0] or bool(refreshed.gated)
            if refreshed.stream_info and refreshed.stream_info[0] == stream_url:
                # Identischer Link: die Signatur war nicht abgelaufen, der Fehler
                # lag am Abruf selbst. Ein zweiter Versuch scheitert genauso.
                log(
                    f"  {hoster_used}: unveränderter Link – kein zweiter Versuch",
                    "warn",
                )
            elif refreshed.stream_info:
                if _enqueue_hoster_attempt(
                    movie, movie_slug, out_path, refreshed, unsupported_domains,
                    failed_hoster_urls, attempt_errors, source_movies, source_index,
                    source_fallbacks_loaded, refreshed_hoster_urls,
                    barren_hoster_urls, cancelled,
                    gate_seen, gate_retry, slow_candidates, last_resort,
                ):
                    return
                on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug)
                return

        attempt_errors.append(f"{hoster_used}: {msg}")
        if result.source_hoster_url:
            failed_hoster_urls.add(result.source_hoster_url)
        log(f"  {hoster_used}-Download fehlgeschlagen – versuche nächsten Anbieter", "warn")
        on_job_progress(-1, f"{hoster_used} ausgefallen · wechsle Anbieter …", label)

        with state.hoster_extract_lock:
            next_result = _extract_from_movie(
                movie,
                unsupported_domains,
                excluded_hoster_urls=failed_hoster_urls,
                barren_hoster_urls=barren_hoster_urls,
            )
        gate_seen[0] = gate_seen[0] or bool(next_result.gated)
        if next_result.stream_info:
            if _enqueue_hoster_attempt(
                movie, movie_slug, out_path, next_result, unsupported_domains,
                failed_hoster_urls, attempt_errors, source_movies, source_index,
                source_fallbacks_loaded, refreshed_hoster_urls,
                barren_hoster_urls, cancelled,
                gate_seen, gate_retry, slow_candidates, last_resort,
            ):
                return
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug)
            return

        # Alle Hoster dieses Katalogtreffers sind verbraucht. Nun denselben Inhalt
        # bei weiteren Katalogquellen testen – für Filme UND Episoden.
        ep_info = parse_episode_slug(movie_slug)
        if not source_fallbacks_loaded[0]:
            source_fallbacks_loaded[0] = True
            on_job_progress(-1, "Hoster erschöpft · suche alternative Quellen …", label)
            if ep_info:
                series_title = strip_episode_suffix(source_movies[0].title) or source_movies[0].title
                tried_providers = {
                    _movie_provider(candidate, movie_slug)
                    for candidate in source_movies
                }
                tried_providers.discard("")
                alternatives = find_episode_fallbacks(
                    series_title,
                    ep_info[1],
                    ep_info[2],
                    aliases=_episode_fallback_aliases(movie_slug, series_title),
                    source_slug=movie_slug,
                    excluded_providers=tried_providers,
                )
                seen = {m.url for m in source_movies}
                source_movies.extend(m for m in alternatives if m.url not in seen)
            else:
                source_movies.extend(find_movie_source_fallbacks(
                    source_movies[0], movie_slug, {m.url for m in source_movies},
                ))
        for next_index in range(source_index + 1, len(source_movies)):
            next_movie = source_movies[next_index]
            log(f"  Wechsle Filmquelle: {clean_movie_title(next_movie.title)}", "warn")
            with state.hoster_extract_lock:
                source_result = _extract_from_movie(
                    next_movie,
                    unsupported_domains,
                    excluded_hoster_urls=failed_hoster_urls,
                    barren_hoster_urls=barren_hoster_urls,
                )
            gate_seen[0] = gate_seen[0] or bool(source_result.gated)
            if not source_result.stream_info:
                continue
            if _enqueue_hoster_attempt(
                next_movie, movie_slug, out_path, source_result, unsupported_domains,
                failed_hoster_urls, attempt_errors, source_movies, next_index,
                source_fallbacks_loaded, refreshed_hoster_urls,
                barren_hoster_urls, cancelled,
                gate_seen, gate_retry, slow_candidates, last_resort,
            ):
                return
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug)
            return

        if ep_info and gate_seen[0] and gate_retry and gate_retry():
            log("  serienstream-Captcha aktiv – Episode nach Cooldown erneut versuchen.", "warn")
            on_job_progress(-1, "Captcha-Cooldown · Wiederholung vorgemerkt …", label)
            return

        if slow_candidates:
            reserve_movie, reserve_result, _reserve_speed = max(
                slow_candidates,
                key=lambda candidate: candidate[2],
            )
            reserve_label = reserve_result.hoster_used or "langsame Quelle"
            log(
                f"  Alle schnelleren Quellen erschoepft – {reserve_label} "
                "wird als langsame Reserve ohne Speed-Limit fortgesetzt.",
                "warn",
            )
            on_job_progress(
                -1,
                f"Keine schnellere Quelle · nutze {reserve_label} als Reserve …",
                label,
            )
            if _enqueue_hoster_attempt(
                reserve_movie,
                movie_slug,
                out_path,
                reserve_result,
                unsupported_domains,
                failed_hoster_urls,
                attempt_errors,
                source_movies,
                source_index,
                source_fallbacks_loaded,
                refreshed_hoster_urls,
                barren_hoster_urls,
                cancelled,
                gate_seen,
                gate_retry,
                [],
                True,
            ):
                return
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug)
            return

        reason = "serienstream-Captcha aktiv" if gate_seen[0] else "alle Anbieter und Filmquellen ausgeschöpft"
        final_msg = "; ".join(attempt_errors + [reason])
        on_job_done(False, final_msg, label, out_path, slug=movie_slug)

    job = DownloadJob(
        stream_url=stream_url,
        stream_type=stream_type,
        out_path=out_path,
        queue_slug=movie_slug,
        provider=result.provider or _movie_provider(movie, movie_slug),
        content_language=(
            result.content_language
            or _movie_content_language(movie, fallback=movie_slug)
        ),
        referer=result.referer,
        origin=result.origin,
        on_progress=lambda pct, msg: on_job_progress(pct, msg, label),
        on_done=_attempt_done,
        allow_slow=last_resort,
        queue_priority=0 if not parse_episode_slug(movie_slug) else 100,
    )
    with state.queue_lifecycle_lock:
        with state.queue_claim_lock:
            if (cancelled and cancelled()) or movie_slug not in state.picked:
                return False
            add_front = getattr(state.dl_queue, "add_front", None)
            # Langsame Reserven ohne Speed-Limit koennen stundenlang kriechen.
            # Sie kommen ans Queue-Ende, damit schnelle Downloads nicht hinter
            # ihnen verhungern; normale Folgeversuche behalten ihren Slot vorn.
            if add_front and not last_resort:
                add_front(job)
            else:
                state.dl_queue.add(job)
    return True


def _existing_valid_movie_path(out_root: Path, movie: FilmpalastMovie) -> Optional[Path]:
    """Findet eine bereits vollständig geladene Filmdatei dieses Titels."""
    titles = [clean_movie_title(movie.title)]
    if movie.title not in titles:
        titles.append(movie.title)
    checked: set = set()
    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
    for title in titles:
        expected = out_root / build_movie_filename(title, movie.year)
        try:
            candidates = expected.parent.glob(expected.stem + ".*")
            for candidate in candidates:
                if candidate in checked or candidate.suffix.casefold() not in video_suffixes:
                    continue
                checked.add(candidate)
                valid, detail = validate_media_file(candidate)
                if valid:
                    log(f"  Bereits vollständig vorhanden: {candidate.name} ({detail})")
                    return candidate
                log(f"  Vorhandene Datei ist ungültig und wird ersetzt: {candidate.name} ({detail})", "warn")
        except OSError as exc:
            log(f"  Vorhandene Filmdatei konnte nicht geprüft werden: {exc}", "warn")
    return None


def _movie_subscription_download_finished(
    movie_slug: str, out_path: Path, quality: str,
) -> None:
    """Bucht ein erfolgreiches Upgrade und entfernt erst danach die alte Datei."""
    changed = False
    subscription = None
    old_media_path = ""
    with state.movie_subscriptions_lock:
        subscription = next(
            (
                entry for entry in state.movie_subscriptions
                if entry.get("pending_slug") == movie_slug
                or entry.get("source_slug") == movie_slug
            ),
            None,
        )
        if subscription is None:
            return
        rank = movie_quality_rank(quality)
        subscription["current_quality_rank"] = max(
            int(subscription.get("current_quality_rank") or 0), rank,
        )
        subscription["current_quality"] = quality or (
            f"{rank}p" if rank else "Qualität unbekannt"
        )
        subscription["pending_slug"] = ""
        subscription["last_error"] = ""
        subscription["upgrade_available_rank"] = 0
        subscription["upgrade_available_quality"] = ""
        subscription["last_upgraded"] = time.time()
        old_media_path = str(subscription.get("existing_path") or "")
        changed = True
        _persist_movie_subscriptions_background()

    # DownloadJob hat die neue Datei bereits atomar committed. Bei abweichender
    # Container-Endung bleibt die alte Datei daneben liegen; nur dann bereinigen.
    try:
        candidates = [
            path for path in out_path.parent.glob(out_path.stem + ".*")
            if path.suffix.casefold() in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
            and path.is_file()
        ]
        valid_candidates = [
            path for path in candidates if validate_media_file(path)[0]
        ]
        if valid_candidates:
            newest = max(valid_candidates, key=lambda path: path.stat().st_mtime_ns)
            old_path = Path(old_media_path)
            if old_path.is_absolute():
                root = Path(state.save_path).expanduser().resolve(strict=False)
                resolved_old = old_path.expanduser().resolve(strict=False)
                try:
                    resolved_old.relative_to(root)
                    old_is_safe = True
                except ValueError:
                    old_is_safe = False
                if old_is_safe and resolved_old != newest.resolve(strict=False):
                    resolved_old.unlink(missing_ok=True)
                    log(f"Qualitäts-Upgrade: alte Filmdatei gelöscht: {resolved_old.name}")
            for candidate in candidates:
                if candidate != newest:
                    candidate.unlink(missing_ok=True)
                    log(f"Qualitäts-Upgrade: alte Filmdatei gelöscht: {candidate.name}")
    except OSError as exc:
        log(f"Qualitäts-Upgrade: alte Filmdatei konnte nicht bereinigt werden: {exc}", "warn")
    if changed:
        broadcast({"type": "movie_subscriptions_update", **movie_subscriptions_payload()})


def _movie_subscription_download_failed(movie_slug: str, message: str) -> None:
    changed = False
    with state.movie_subscriptions_lock:
        for entry in state.movie_subscriptions:
            if entry.get("pending_slug") != movie_slug:
                continue
            entry["pending_slug"] = ""
            entry["last_error"] = "" if message == "Abgebrochen" else str(message)[:240]
            entry["last_checked"] = time.time()
            changed = True
        if changed:
            _persist_movie_subscriptions_background()
    if changed:
        broadcast({"type": "movie_subscriptions_update", **movie_subscriptions_payload()})


def _existing_valid_episode_path(series_title: str, season: int, episode: int) -> Optional[Path]:
    expected = series_episode_out_path(series_title, season, episode)
    if not expected.parent.exists():
        return None
    video_suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
    for candidate in expected.parent.glob(expected.stem + ".*"):
        if candidate.suffix.casefold() not in video_suffixes:
            continue
        valid, detail = _valid_media_cached(candidate)
        if valid:
            return candidate
        log(f"  Vorhandene Episode ist ungültig und wird ersetzt: {candidate.name} ({detail})", "warn")
    return None


def _episode_jellyfin_identity(
    base_slug: str,
    series_title: str,
    jf_client: JellyfinClient,
    jf_series: Optional[List[dict]],
) -> tuple[tuple[str, ...], set[str], str]:
    """Ermittelt eine eindeutige Serienidentität; Mehrdeutigkeit blockiert."""
    with state.watchlist_lock:
        stored = watchlist_lookup(base_slug)
        entry = dict(stored) if stored else {}
    tmdb_id = str(entry.get("tmdb_id") or "")
    aliases = list(dict.fromkeys(filter(None, (
        series_title,
        entry.get("title", ""),
        *(entry.get("aliases") or []),
    ))))
    tmdb = get_tmdb_series(series_title, tmdb_id)
    if tmdb:
        tmdb_id = str(tmdb_id or tmdb.get("tmdb_id") or "")
        aliases = list(dict.fromkeys(filter(None, (
            *aliases,
            tmdb.get("title", ""),
            tmdb.get("original_title", ""),
        ))))
    series_ids = jf_client.series_ids_for(
        series_title, tmdb_id=tmdb_id, aliases=aliases, items=jf_series,
    )
    if series_ids is None:
        raise RuntimeError("Jellyfin-Zuordnung mehrdeutig")
    return tuple(aliases), series_ids, tmdb_id


def _is_jellyfin_safety_block(reason: str) -> bool:
    return str(reason or "").startswith("Jellyfin")


def _content_already_available(movie: FilmpalastMovie, slug: str) -> tuple[bool, str]:
    """Serverseitiger Duplikatschutz für manuelle und automatische Queue-Adds."""
    episode_info = parse_episode_slug(slug)
    jf_client = get_jellyfin_client()
    if episode_info:
        series_title = strip_episode_suffix(movie.title) or movie.title
        if _existing_valid_episode_path(series_title, episode_info[1], episode_info[2]):
            return True, "lokal vorhanden"
        if jf_client.configured:
            jf_series = get_jellyfin_series()
            with state.jellyfin_cache_lock:
                config_generation = state.jellyfin_config_generation
                data_generation = state.jellyfin_episode_data_generation
                series_available = state.jellyfin_series_available
            if jf_series is None or not series_available:
                return True, "Jellyfin-Serienindex nicht verfügbar"
            try:
                aliases, series_ids, _tmdb_id = _episode_jellyfin_identity(
                    episode_info[0], series_title, jf_client, jf_series,
                )
            except RuntimeError as exc:
                return True, str(exc)
            items, live_available, _stale, _checked_at = get_jellyfin_targeted_episodes(
                series_ids,
            )
            if items is None or not live_available:
                return True, "Jellyfin nicht erreichbar"
            with state.jellyfin_cache_lock:
                if (
                    config_generation != state.jellyfin_config_generation
                    or data_generation != state.jellyfin_episode_data_generation
                ):
                    return True, "Jellyfin-Daten werden gerade aktualisiert"
            if jf_client.has_episode(
                series_title, episode_info[1], episode_info[2], items=items,
                aliases=aliases, series_ids=series_ids,
            ):
                return True, "in Jellyfin vorhanden"
        return False, ""

    if _existing_valid_movie_path(Path(state.save_path), movie) is not None:
        return True, "lokal vorhanden"
    if jf_client.configured:
        items = get_jellyfin_library()
        with state.jellyfin_cache_lock:
            config_generation = state.jellyfin_config_generation
            data_generation = state.jellyfin_movie_data_generation
            library_available = state.jellyfin_library_available
        if items is None or not library_available:
            return True, "Jellyfin nicht erreichbar"
        title = clean_movie_title(movie.title)
        tmdb = get_tmdb_client().movie_summary(title, movie.year)
        with state.jellyfin_cache_lock:
            if (
                config_generation != state.jellyfin_config_generation
                or data_generation != state.jellyfin_movie_data_generation
            ):
                return True, "Jellyfin-Daten werden gerade aktualisiert"
        if jf_client.match(
            title, movie.year, items=items, tmdb_id=(tmdb or {}).get("tmdb_id", ""),
        ):
            return True, "in Jellyfin vorhanden"
    return False, ""


def run_download_queue(
    jobs: List[tuple],
    out_root: Path,
    movie_fallbacks: Optional[Dict[str, List[FilmpalastMovie]]] = None,
    start_queue: bool = True,
    cancelled: Optional[Callable[[], bool]] = None,
):
    """jobs: Liste von (movie, slug)-Paaren. Der slug ist der Queue-Schlüssel
    (z.B. 'serienstream:the-last-of-us-s01e01') – daraus wird die Serie/Staffel/
    Episode erkannt. Wichtig: NICHT aus movie.url ableiten, denn bei s.to/moflix
    ist das letzte URL-Segment 'episode-1'/'1' und würde die Serie fälschlich als
    Film in den Wurzelordner legen.

    SerienStream-Episoden werden erst hier unmittelbar vor der Verarbeitung
    geladen. Provider-Sperren lassen ihren logischen Queue-Claim offen."""
    out_root.mkdir(parents=True, exist_ok=True)
    unsupported_domains: set = set()
    gated_jobs: List[tuple] = []   # (movie, slug) die am Captcha-Gate hingen
    queued_slugs: set = set()

    for movie, movie_slug in jobs:
        if (cancelled and cancelled()) or not _queue_slug_claimed(movie_slug):
            continue
        log(f"─── {movie.title} ───")

        # Bereits vorhandene Episode NICHT erneut auflösen/laden. Spart /r?t=-
        # Requests (wichtig fürs Gate) und macht das erneute Anstoßen nach einem
        # Captcha-Cooldown praktikabel: nur die noch fehlenden Folgen werden
        # verarbeitet statt der ganzen Staffel.
        ep_info = parse_episode_slug(movie_slug)
        if ep_info:
            # Originalen Serientitel EIN EINZIGES MAL festhalten (vor einem
            # etwaigen Hoster-Refresh oder Fallback), damit der "schon
            # vorhanden?"-Check und der tatsächliche Zielordner garantiert
            # denselben Serien-/Staffel-Ordner verwenden. Würde man den Titel
            # später aus einem inzwischen ersetzten movie-Objekt neu ableiten,
            # könnte eine leicht abweichende Anbieter-Formatierung die Episode
            # in einem zweiten, abweichenden Ordner landen lassen.
            orig_series_title = strip_episode_suffix(movie.title) or movie.title
            existing_file = _existing_valid_episode_path(orig_series_title, ep_info[1], ep_info[2])
            if existing_file is not None:
                if not (cancelled and cancelled()) and _queue_slug_claimed(movie_slug):
                    on_job_done(True, "bereits vorhanden", movie.title, existing_file, slug=movie_slug)
                continue

            # Konnte bereits die Episodenseite während der Vorbereitung nicht
            # geladen werden, bleibt der logische Job trotzdem erhalten. Vor
            # jedem Versuch die gewählte Quelle erneut laden; danach folgen die
            # Katalog-Fallbacks und bei Serienstream gegebenenfalls Cooldowns.
            primary_unavailable = False
            if not movie.hosters:
                refreshed_movie = None
                is_sto = provider_for_value(movie_slug) == "serienstream"
                if is_sto and not state.provider_health.request_allowed("serienstream"):
                    log(
                        f"SerienStream befindet sich im Cooldown – Episode "
                        f"S{ep_info[1]:02d}E{ep_info[2]:02d} bleibt vorgemerkt."
                    )
                else:
                    try:
                        refreshed_movie = load_movie_for_slug(movie_slug)
                    except ProviderBlockedError as exc:
                        _mark_serienstream_blocked(exc.reason, str(exc))
                        log(f"  Episodenseite blockiert: {exc}", "warn")
                    except Exception as exc:
                        log(f"  Episodenseite noch nicht ladbar: {exc}", "warn")
                        if is_sto:
                            _mark_serienstream_blocked("provider_error", str(exc))
                if refreshed_movie and refreshed_movie.hosters:
                    movie = refreshed_movie
                    state.fp_movies[movie_slug] = refreshed_movie
                elif movie_slug.startswith(SERIENSTREAM_PREFIX):
                    primary_unavailable = True
        else:
            primary_unavailable = False
            existing_movie = (
                None
                if bool(getattr(movie, "_allow_quality_upgrade", False))
                else _existing_valid_movie_path(out_root, movie)
            )
            if existing_movie is not None:
                if not (cancelled and cancelled()) and _queue_slug_claimed(movie_slug):
                    on_job_done(True, "bereits vorhanden", movie.title, existing_movie, slug=movie_slug)
                continue

        source_movies = [movie]
        seen_source_urls = {movie.url}
        known_fallbacks = (movie_fallbacks or {}).get(movie_slug, [])
        for fallback_movie in known_fallbacks:
            if fallback_movie.url in seen_source_urls:
                continue
            source_movies.append(fallback_movie)
            seen_source_urls.add(fallback_movie.url)
        # Ein leerer, früher aufgebauter Episoden-Fallback-Eintrag beweist
        # nicht, dass alle Anbieter im jetzigen Moment erfolglos sind. Gerade
        # bei einer späteren SerienStream-Sperre muss die exakte Laufzeitsuche
        # (Moflix/Huhu/weitere) noch einmal stattfinden dürfen. Erst dieser
        # Lauf markiert die Suche für den aktuellen Versuch als vollständig.
        source_fallbacks_loaded = [
            movie_fallbacks is not None and movie_slug in movie_fallbacks
            if not ep_info else False
        ]
        # Gilt für den kompletten Versuch dieses Slugs, quellenübergreifend:
        # ein Embed ohne Stream-URL bleibt für diesen Lauf ausgeschlossen.
        barren_hoster_urls: set = set()
        # Watchlist-Einträge behalten ihren ursprünglichen Katalog-Slug. Wurde
        # später eine andere Primärquelle konfiguriert, laden wir deren Treffer
        # vorab und sortieren die tatsächlich nutzbaren Quellen neu.
        if (
            ep_info
            and provider_for_value(movie_slug) != provider_priority("series")[0]
            and not source_fallbacks_loaded[0]
        ):
            source_fallbacks_loaded[0] = True
            alternatives = find_episode_fallbacks(
                orig_series_title,
                ep_info[1],
                ep_info[2],
                aliases=_episode_fallback_aliases(movie_slug, orig_series_title),
                source_slug=movie_slug,
            )
            for candidate in alternatives:
                if candidate.url not in seen_source_urls:
                    source_movies.append(candidate)
                    seen_source_urls.add(candidate.url)
        if ep_info:
            source_movies = _ordered_episode_sources(source_movies)
            movie = source_movies[0]
        source_index = 0

        with state.hoster_extract_lock:
            result = _extract_from_movie(
                movie, unsupported_domains, barren_hoster_urls=barren_hoster_urls,
            )
        if primary_unavailable:
            # Eine temporaer nicht lesbare s.to-Episodenseite wird wie das
            # Redirect-Gate behandelt und nicht sofort terminal gezaehlt.
            if state.provider_health.request_allowed("serienstream"):
                _mark_serienstream_blocked(
                    "provider_error", "SerienStream-Episodenseite nicht ladbar",
                )
            result.gated = True
        gate_seen = [bool(result.gated)]

        # Scheitert bereits die Extraktion/Probe, denselben Inhalt sofort beim
        # ersten exakten Katalog-Fallback versuchen. Das gilt nicht nur bei Captcha.
        if not result.stream_info:
            if not source_fallbacks_loaded[0]:
                if ep_info:
                    alternatives = find_episode_fallbacks(
                        orig_series_title,
                        ep_info[1],
                        ep_info[2],
                        aliases=_episode_fallback_aliases(movie_slug, orig_series_title),
                        source_slug=movie_slug,
                        limit=1,
                    )
                    source_movies.extend(
                        candidate for candidate in alternatives
                        if candidate.url not in {m.url for m in source_movies}
                    )
                    # Ein erster exakter Treffer wird sofort versucht. Erst
                    # wenn dessen Extraktion oder Download scheitert, werden
                    # die übrigen Kataloge geladen.
                    source_fallbacks_loaded[0] = not bool(alternatives)
                else:
                    source_fallbacks_loaded[0] = True
                    source_movies.extend(find_movie_source_fallbacks(
                        source_movies[0], movie_slug, {m.url for m in source_movies},
                    ))
            next_index = 1
            while next_index < len(source_movies):
                next_movie = source_movies[next_index]
                log(f"  Wechsle Quelle: {strip_source_suffix(next_movie.title)}", "warn")
                with state.hoster_extract_lock:
                    source_result = _extract_from_movie(
                        next_movie,
                        unsupported_domains,
                        barren_hoster_urls=barren_hoster_urls,
                    )
                gate_seen[0] = gate_seen[0] or bool(source_result.gated)
                next_index += 1
                if not source_result.stream_info:
                    continue
                movie = next_movie
                result = source_result
                source_index = next_index - 1
                break

            # Der schnellste Katalogtreffer hatte zwar Hoster, ließ sich aber
            # nicht extrahieren. Jetzt erst die restlichen Provider laden und
            # in derselben Vorbereitung weiterprobieren.
            if ep_info and not result.stream_info and not source_fallbacks_loaded[0]:
                source_fallbacks_loaded[0] = True
                tried_providers = {
                    _movie_provider(candidate, movie_slug)
                    for candidate in source_movies
                }
                tried_providers.discard("")
                alternatives = find_episode_fallbacks(
                    orig_series_title,
                    ep_info[1],
                    ep_info[2],
                    aliases=_episode_fallback_aliases(movie_slug, orig_series_title),
                    source_slug=movie_slug,
                    excluded_providers=tried_providers,
                )
                known_urls = {candidate.url for candidate in source_movies}
                source_movies.extend(
                    candidate for candidate in alternatives
                    if candidate.url not in known_urls
                )
                while next_index < len(source_movies):
                    next_movie = source_movies[next_index]
                    log(
                        f"  Wechsle Quelle: {strip_source_suffix(next_movie.title)}",
                        "warn",
                    )
                    with state.hoster_extract_lock:
                        source_result = _extract_from_movie(
                            next_movie,
                            unsupported_domains,
                            barren_hoster_urls=barren_hoster_urls,
                        )
                    gate_seen[0] = gate_seen[0] or bool(source_result.gated)
                    next_index += 1
                    if not source_result.stream_info:
                        continue
                    movie = next_movie
                    result = source_result
                    source_index = next_index - 1
                    break

        if not result.stream_info:
            if gate_seen[0]:
                # s.to-Gate aktiv UND kein Fallback nutzbar – bis zur nächsten
                # Provider-Probe zurückstellen (NICHT als erledigt zählen).
                gated_jobs.append((source_movies[0], movie_slug))
                log("  Zurückgestellt – serienstream Captcha-Gate aktiv (Fallback erfolglos)", "warn")
            else:
                if not (cancelled and cancelled()) and _queue_slug_claimed(movie_slug):
                    on_job_done(False, "kein Hoster extrahierbar", movie.title, Path(""), slug=movie_slug)
            continue

        # Episode vs. Film aus dem Queue-Slug erkennen (NICHT aus movie.url –
        # s.to/moflix haben dort 'episode-1'/'1' als letztes Segment).
        episode_info = parse_episode_slug(movie_slug)
        if episode_info:
            _base_slug, season, episode = episode_info
            out_path = series_episode_out_path(orig_series_title, season, episode)
        else:
            primary_movie = source_movies[0]
            out_path = out_root / build_movie_filename(
                clean_movie_title(primary_movie.title), primary_movie.year,
            )

        enqueued = _enqueue_hoster_attempt(
            movie=movie,
            movie_slug=movie_slug,
            out_path=out_path,
            result=result,
            unsupported_domains=unsupported_domains,
            failed_hoster_urls=set(),
            attempt_errors=[],
            source_movies=source_movies,
            source_index=source_index,
            source_fallbacks_loaded=source_fallbacks_loaded,
            refreshed_hoster_urls=set(),
            barren_hoster_urls=barren_hoster_urls,
            cancelled=cancelled,
            gate_seen=gate_seen,
            gate_retry=lambda primary=source_movies[0], slug=movie_slug: _defer_provider_episode(
                primary, slug, out_root, movie_fallbacks,
            ),
        )
        if enqueued:
            queued_slugs.add(movie_slug)

    # Am Captcha-Gate hängengebliebene Episoden zentral sammeln. Das gilt auch
    # für einen einzelnen Vorbereitungsjob ohne Erfolg.
    if gated_jobs:
        deferred = 0
        for gated_movie, gated_slug in gated_jobs:
            if (cancelled and cancelled()) or not _queue_slug_claimed(gated_slug):
                continue
            if _defer_provider_episode(
                gated_movie, gated_slug, out_root, movie_fallbacks,
            ):
                deferred += 1
                queued_slugs.add(gated_slug)
                continue
            # Ein zurückgestellter Provider-Job ist nie ein terminaler Fehler.
        if deferred:
            log(
                f"⏳ {deferred} Episode(n) warten auf die nächste einzelne "
                f"SerienStream-Probe."
            )

    # Erst nach der Gate-Entscheidung starten. on_queue_done sieht dadurch
    # entweder den wartenden Provider-Job oder einen terminalen Versuch.
    if start_queue:
        log("─── Starte Queue (max. 2 parallel) ───")
        state.dl_queue.start()

    # Telegram benötigt die konkreten Slugs, um bei Mehrfachanfragen sofort zu
    # erkennen, welche Episoden tatsächlich gestartet/zurückgestellt wurden.
    return queued_slugs


# ---------------------------------------------------------------------------
# Telegram-Filmwünsche
# ---------------------------------------------------------------------------
TELEGRAM_JELLYFIN_WAIT_SECONDS = 30 * 60
TELEGRAM_SERIES_CHOICE_TTL_SECONDS = 10 * 60
TELEGRAM_SERIES_LOADING_TTL_SECONDS = 30 * 60
TELEGRAM_SERIES_PAGE_SIZE = 6
TELEGRAM_SERIES_MAX_PENDING = 20


def _telegram_send(chat_id: str, text: str):
    if _telegram_bot is not None:
        _telegram_bot.send(chat_id, text)


def _rank_telegram_series_results(
    query: str, results: List[FilmpalastSeriesResult],
) -> List[FilmpalastSeriesResult]:
    wanted = _norm_title(query)
    unique: Dict[str, FilmpalastSeriesResult] = {}
    for result in results:
        key = result.base_slug or result.sample_slug
        if key and key not in unique:
            unique[key] = result
    ranked = sorted(
        unique.values(),
        key=lambda result: (
            _norm_title(result.title) != wanted,
            wanted not in _norm_title(result.title),
            abs(len(_norm_title(result.title)) - len(wanted)),
            not _norm_title(result.title).startswith(wanted),
            clean_movie_title(result.title).casefold(),
        ),
    )
    # Identische Titel verschiedener Anbieter sind keine Auswahlvarianten. Der
    # erste Treffer folgt der Nutzerpriorität; weitere Quellen bleiben Fallbacks.
    deduped: List[FilmpalastSeriesResult] = []
    seen_titles: set[str] = set()
    for result in ranked:
        title_key = _norm_title(result.title)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        deduped.append(result)
    return deduped


def _prune_telegram_series_choices_locked(
    now: float, reserve_slot: bool = False,
) -> None:
    expired = [
        token for token, entry in state.telegram_series_choices.items()
        if float(entry.get("expires_at", 0)) <= now
    ]
    for token in expired:
        state.telegram_series_choices.pop(token, None)
    limit = TELEGRAM_SERIES_MAX_PENDING - (1 if reserve_slot else 0)
    while len(state.telegram_series_choices) > limit:
        oldest = min(
            state.telegram_series_choices,
            key=lambda token: float(
                state.telegram_series_choices[token].get("created_at", 0),
            ),
        )
        state.telegram_series_choices.pop(oldest, None)


def _telegram_series_choice_markup(token: str, index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Diese Serie auswählen",
        "callback_data": f"sr:{token}:{index}",
    }]]}


def _telegram_series_next_markup(token: str, next_index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Weitere Treffer anzeigen",
        "callback_data": f"srn:{token}:{next_index}",
    }]]}


def _telegram_movie_choice_markup(token: str, index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Diesen Film auswählen",
        "callback_data": f"mr:{token}:{index}",
    }]]}


def _telegram_movie_next_markup(token: str, next_index: int) -> dict:
    return {"inline_keyboard": [[{
        "text": "Weitere Treffer anzeigen",
        "callback_data": f"mrn:{token}:{next_index}",
    }]]}


def _send_telegram_series_choice_page_locked(token: str, entry: dict) -> bool:
    bot = _telegram_bot
    if bot is None:
        return False
    chat_id = entry["chat_id"]
    candidates = entry["candidates"]
    start = int(entry.get("next_index", 0))
    end = min(start + TELEGRAM_SERIES_PAGE_SIZE, len(candidates))
    sent_message_ids = []
    sent_candidate_count = 0

    for index in range(start, end):
        with state.telegram_choices_lock:
            if state.telegram_series_choices.get(token) is not entry:
                break
        candidate = candidates[index]
        title = clean_movie_title(candidate.title) or candidate.title
        caption = f"{index + 1}. {title}"
        if candidate.year:
            caption += f" ({candidate.year})"
        caption = caption[:1024]
        markup = _telegram_series_choice_markup(token, index)
        message_id = None
        cover_data = _fetch_cover_data(candidate.cover_url) if candidate.cover_url else None
        if cover_data:
            content, content_type = cover_data
            message_id = bot.send_photo(
                chat_id, content, caption, markup, content_type,
            )
        if message_id is None and candidate.cover_url:
            message_id = bot.send_photo(
                chat_id, candidate.cover_url, caption, markup,
            )
        if message_id is None:
            message_id = bot.send_message(
                chat_id, f"🖼️ {caption}\n(Cover nicht verfügbar)", markup,
            )
        if message_id is not None:
            sent_message_ids.append(message_id)
            sent_candidate_count += 1

    with state.telegram_choices_lock:
        current = state.telegram_series_choices.get(token)
    if current is not entry:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False

    if sent_candidate_count and end < len(candidates):
        remaining = len(candidates) - end
        message_id = bot.send_message(
            chat_id,
            f"Noch {remaining} Treffer.",
            _telegram_series_next_markup(token, end),
        )
        if message_id is not None:
            sent_message_ids.append(message_id)

    with state.telegram_choices_lock:
        if state.telegram_series_choices.get(token) is not entry:
            stale = True
        else:
            stale = False
            entry["message_ids"].extend(sent_message_ids)
            entry["next_index"] = end if sent_candidate_count else start
            entry["ready"] = True
            entry["expires_at"] = (
                time.monotonic() + TELEGRAM_SERIES_CHOICE_TTL_SECONDS
            )
    if stale:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False
    return bool(sent_candidate_count)


def _publish_telegram_series_choices_locked(
    chat_id: str,
    request: dict,
    results: List[FilmpalastSeriesResult],
) -> None:
    candidates = list(results)
    if not candidates or _telegram_bot is None:
        _telegram_send(chat_id, "❌ Telegram-Auswahl konnte nicht erstellt werden.")
        return

    now = time.monotonic()
    token = secrets.token_urlsafe(9)
    entry = {
        "kind": "series",
        "chat_id": chat_id,
        "request": dict(request),
        "candidates": candidates,
        "created_at": now,
        "expires_at": now + TELEGRAM_SERIES_LOADING_TTL_SECONDS,
        "message_ids": [],
        "next_index": 0,
        "ready": False,
    }
    old_message_ids = []
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        for old_token, old_entry in list(state.telegram_series_choices.items()):
            if old_entry.get("chat_id") == chat_id:
                old_message_ids.extend(old_entry.get("message_ids", []))
                state.telegram_series_choices.pop(old_token, None)
        _prune_telegram_series_choices_locked(now, reserve_slot=True)
        state.telegram_series_choices[token] = entry
    if old_message_ids:
        threading.Thread(
            target=_clear_telegram_choice_keyboards,
            args=(chat_id, old_message_ids),
            daemon=True,
        ).start()

    _telegram_send(
        chat_id,
        f"🔎 {len(results)} Serien gefunden. Bitte die richtige auswählen:",
    )
    if not _send_telegram_series_choice_page_locked(token, entry):
        with state.telegram_choices_lock:
            if state.telegram_series_choices.get(token) is entry:
                state.telegram_series_choices.pop(token, None)
        _telegram_send(chat_id, "❌ Treffer konnten nicht an Telegram gesendet werden.")


def _publish_telegram_series_choices(
    chat_id: str,
    request: dict,
    results: List[FilmpalastSeriesResult],
) -> None:
    with state.telegram_choices_publish_lock:
        _publish_telegram_series_choices_locked(chat_id, request, results)


def _consume_telegram_series_choice(
    chat_id: str, token: str, index: int,
) -> tuple[str, Optional[dict], Optional[FilmpalastSeriesResult]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None, None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None, None
        if entry.get("kind", "series") != "series":
            return "invalid", None, None
        if not entry.get("ready"):
            return "loading", None, None
        candidates = entry.get("candidates") or []
        if index < 0 or index >= len(candidates):
            return "invalid", None, None
        state.telegram_series_choices.pop(token, None)
        return "ok", entry, candidates[index]


def _prepare_telegram_series_next_page(
    chat_id: str, token: str, next_index: int,
) -> tuple[str, Optional[dict]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None
        if entry.get("kind", "series") != "series":
            return "invalid", None
        if not entry.get("ready"):
            return "loading", None
        candidates = entry.get("candidates") or []
        if next_index != entry.get("next_index") or next_index >= len(candidates):
            return "invalid", None
        entry["ready"] = False
        entry["expires_at"] = now + TELEGRAM_SERIES_LOADING_TTL_SECONDS
        return "ok", entry


def _build_telegram_movie_options(
    query: str, results: List[FilmpalastSearchResult],
) -> List[dict]:
    """Lädt Film-Treffer und bündelt identische Titel/Jahre als Fallbacks."""
    grouped: Dict[tuple, dict] = {}
    seen_urls: set[str] = set()
    for candidate in _telegram_best_result(query, results):
        if not candidate.is_movie:
            continue
        try:
            loaded = load_movie_for_slug(candidate.slug)
        except Exception as exc:
            log(f"Telegram-Filmtreffer nicht ladbar ({candidate.slug}): {exc}", "warn")
            continue
        if not loaded or not loaded.hosters or loaded.url in seen_urls:
            continue
        seen_urls.add(loaded.url)
        title = clean_movie_title(loaded.title) or clean_movie_title(candidate.title)
        year = str(loaded.year or candidate.year or "")
        key = (_norm_title(title), year)
        option = grouped.get(key)
        if option is None:
            grouped[key] = {
                "result": candidate,
                "movie": loaded,
                "fallback_movies": [],
                "title": title,
                "year": year,
                "cover_url": loaded.cover_url,
            }
        else:
            option["fallback_movies"].append(loaded)
            if not option.get("cover_url") and loaded.cover_url:
                option["cover_url"] = loaded.cover_url
    return list(grouped.values())


def _filter_existing_telegram_movie_options(
    options: List[dict],
) -> tuple[Optional[List[dict]], List[dict], str]:
    """Entfernt vorhandene Filme, bevor Telegram Download-Buttons anzeigt."""
    jf_items = get_jellyfin_library(force=True)
    with state.jellyfin_cache_lock:
        library_available = state.jellyfin_library_available
    if jf_items is None or not library_available:
        return None, [], "Jellyfin ist nicht erreichbar"

    downloadable = []
    existing = []
    for option in options:
        movie = option["movie"]
        result = option["result"]
        already_available, reason = _content_already_available(movie, result.slug)
        if already_available:
            if _is_jellyfin_safety_block(reason):
                return None, existing, reason
            existing.append(option)
        else:
            downloadable.append(option)
    return downloadable, existing, ""


def _send_telegram_movie_choice_page_locked(token: str, entry: dict) -> bool:
    bot = _telegram_bot
    if bot is None:
        return False
    chat_id = entry["chat_id"]
    candidates = entry["candidates"]
    start = int(entry.get("next_index", 0))
    end = min(start + TELEGRAM_SERIES_PAGE_SIZE, len(candidates))
    sent_message_ids = []
    sent_candidate_count = 0

    for index in range(start, end):
        with state.telegram_choices_lock:
            if state.telegram_series_choices.get(token) is not entry:
                break
        option = candidates[index]
        caption = f"{index + 1}. {option['title']}"
        if option.get("year"):
            caption += f" ({option['year']})"
        source_count = 1 + len(option.get("fallback_movies", []))
        if source_count > 1:
            caption += f" · {source_count} Quellen"
        markup = _telegram_movie_choice_markup(token, index)
        message_id = None
        cover_url = str(option.get("cover_url") or "")
        cover_data = _fetch_cover_data(cover_url) if cover_url else None
        if cover_data:
            content, content_type = cover_data
            message_id = bot.send_photo(chat_id, content, caption[:1024], markup, content_type)
        if message_id is None and cover_url:
            message_id = bot.send_photo(chat_id, cover_url, caption[:1024], markup)
        if message_id is None:
            message_id = bot.send_message(
                chat_id, f"🖼️ {caption}\n(Cover nicht verfügbar)", markup,
            )
        if message_id is not None:
            sent_message_ids.append(message_id)
            sent_candidate_count += 1

    with state.telegram_choices_lock:
        current = state.telegram_series_choices.get(token)
    if current is not entry:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False

    if sent_candidate_count and end < len(candidates):
        remaining = len(candidates) - end
        message_id = bot.send_message(
            chat_id,
            f"Noch {remaining} Treffer.",
            _telegram_movie_next_markup(token, end),
        )
        if message_id is not None:
            sent_message_ids.append(message_id)

    with state.telegram_choices_lock:
        if state.telegram_series_choices.get(token) is not entry:
            stale = True
        else:
            stale = False
            entry["message_ids"].extend(sent_message_ids)
            entry["next_index"] = end if sent_candidate_count else start
            entry["ready"] = True
            entry["expires_at"] = time.monotonic() + TELEGRAM_SERIES_CHOICE_TTL_SECONDS
    if stale:
        for message_id in sent_message_ids:
            bot.clear_inline_keyboard(chat_id, message_id)
        return False
    return bool(sent_candidate_count)


def _publish_telegram_movie_choices(
    chat_id: str, query: str, options: List[dict],
) -> None:
    with state.telegram_choices_publish_lock:
        if not options or _telegram_bot is None:
            _telegram_send(chat_id, "❌ Telegram-Auswahl konnte nicht erstellt werden.")
            return
        now = time.monotonic()
        token = secrets.token_urlsafe(9)
        entry = {
            "kind": "movie",
            "chat_id": chat_id,
            "query": query,
            "candidates": list(options),
            "created_at": now,
            "expires_at": now + TELEGRAM_SERIES_LOADING_TTL_SECONDS,
            "message_ids": [],
            "next_index": 0,
            "ready": False,
        }
        old_message_ids = []
        with state.telegram_choices_lock:
            _prune_telegram_series_choices_locked(now)
            for old_token, old_entry in list(state.telegram_series_choices.items()):
                if old_entry.get("chat_id") == chat_id:
                    old_message_ids.extend(old_entry.get("message_ids", []))
                    state.telegram_series_choices.pop(old_token, None)
            _prune_telegram_series_choices_locked(now, reserve_slot=True)
            state.telegram_series_choices[token] = entry
        if old_message_ids:
            threading.Thread(
                target=_clear_telegram_choice_keyboards,
                args=(chat_id, old_message_ids),
                daemon=True,
            ).start()
        _telegram_send(
            chat_id,
            f"🔎 {len(options)} Filme gefunden. Bitte den richtigen auswählen:",
        )
        if not _send_telegram_movie_choice_page_locked(token, entry):
            with state.telegram_choices_lock:
                if state.telegram_series_choices.get(token) is entry:
                    state.telegram_series_choices.pop(token, None)
            _telegram_send(chat_id, "❌ Treffer konnten nicht an Telegram gesendet werden.")


def _consume_telegram_movie_choice(
    chat_id: str, token: str, index: int,
) -> tuple[str, Optional[dict], Optional[dict]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None, None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None, None
        if entry.get("kind") != "movie":
            return "invalid", None, None
        if not entry.get("ready"):
            return "loading", None, None
        candidates = entry.get("candidates") or []
        if index < 0 or index >= len(candidates):
            return "invalid", None, None
        state.telegram_series_choices.pop(token, None)
        return "ok", entry, candidates[index]


def _prepare_telegram_movie_next_page(
    chat_id: str, token: str, next_index: int,
) -> tuple[str, Optional[dict]]:
    now = time.monotonic()
    with state.telegram_choices_lock:
        _prune_telegram_series_choices_locked(now)
        entry = state.telegram_series_choices.get(token)
        if not entry:
            return "expired", None
        if entry.get("chat_id") != chat_id:
            return "forbidden", None
        if entry.get("kind") != "movie":
            return "invalid", None
        if not entry.get("ready"):
            return "loading", None
        candidates = entry.get("candidates") or []
        if next_index != entry.get("next_index") or next_index >= len(candidates):
            return "invalid", None
        entry["ready"] = False
        entry["expires_at"] = now + TELEGRAM_SERIES_LOADING_TTL_SECONDS
        return "ok", entry


def _telegram_finish_job(job: dict, ok: bool, message: str, out_path: Path):
    chat_id = job["chat_id"]
    title = job["title"]
    year = job.get("year", "")
    if not ok:
        _telegram_send(chat_id, f"❌ Download von „{title}“ fehlgeschlagen: {message}")
        return

    jf_client = get_jellyfin_client()
    with state.jellyfin_cache_lock:
        jellyfin_generation = state.jellyfin_config_generation
    if not jf_client.configured:
        _telegram_send(chat_id, f"✅ „{title}“ wurde geladen: {out_path}\nJellyfin ist nicht konfiguriert.")
        return

    log(f"Telegram: Jellyfin-Scan für «{title}» gestartet.")
    jf_client.refresh_library()
    deadline = time.monotonic() + TELEGRAM_JELLYFIN_WAIT_SECONDS
    while time.monotonic() < deadline:
        items = get_jellyfin_library(force=True)
        with state.jellyfin_cache_lock:
            data_generation = state.jellyfin_movie_data_generation
            library_available = state.jellyfin_library_available
            current_generation = state.jellyfin_config_generation
        if current_generation != jellyfin_generation:
            jellyfin_generation = current_generation
            jf_client = get_jellyfin_client()
            if not jf_client.configured:
                _telegram_send(
                    chat_id,
                    f"✅ „{title}“ wurde geladen: {out_path}\nJellyfin ist nicht konfiguriert.",
                )
                return
            jf_client.refresh_library()
        if items is None or not library_available:
            time.sleep(15)
            continue
        if jf_client.match(
            title, year, items=items, tmdb_id=job.get("tmdb_id", ""),
        ):
            with state.jellyfin_cache_lock:
                stale = (
                    jellyfin_generation != state.jellyfin_config_generation
                    or data_generation != state.jellyfin_movie_data_generation
                )
            if stale:
                continue
            _telegram_send(chat_id, f"✅ „{title}“ ist jetzt in Jellyfin verfügbar.")
            return
        time.sleep(15)

    _telegram_send(
        chat_id,
        f"⚠️ „{title}“ wurde nach {out_path} geladen, ist aber nach 30 Minuten noch nicht in Jellyfin erschienen.",
    )


def _telegram_series_job_result(job: dict, slug: str, ok: bool, message: str, out_path: Path):
    """Sammelt Einzelergebnisse einer Telegram-Serienanfrage."""
    finished_group = None
    with state.telegram_jobs_lock:
        group = state.telegram_series_requests.get(job.get("request_id", ""))
        if not group:
            return
        group["pending_slugs"].discard(slug)
        label = f"S{job['season']:02d}E{job['episode']:02d}"
        if ok:
            group["completed"].append({
                "season": job["season"], "episode": job["episode"],
                "label": label, "path": str(out_path),
            })
        else:
            group["failed"].append(f"{label}: {message}")
        if not group["pending_slugs"]:
            finished_group = state.telegram_series_requests.pop(job["request_id"], None)
    if finished_group:
        threading.Thread(
            target=_telegram_finish_series_request,
            args=(finished_group,),
            daemon=True,
        ).start()


def _telegram_terminal_without_job(slug: str, ok: bool, message: str, out_path: Path):
    """Beendet Telegram-Tracking, wenn kein DownloadJob erzeugt wurde."""
    with state.queue_claim_lock:
        state.picked.discard(slug)
    _persist_queue_state()
    with state.telegram_jobs_lock:
        job = state.telegram_jobs.pop(slug, None)
    if not job:
        return
    if job.get("kind") == "series":
        _telegram_series_job_result(job, slug, ok, message, out_path)
    elif ok:
        threading.Thread(
            target=_telegram_finish_job,
            args=(job, True, message, out_path),
            daemon=True,
        ).start()
    else:
        _telegram_send(job["chat_id"], f"❌ Download von „{job['title']}“ fehlgeschlagen: {message}")


def _telegram_finish_series_request(group: dict):
    chat_id = group["chat_id"]
    title = group["title"]
    completed = group["completed"]
    failed = group["failed"]
    if not completed:
        detail = f"\n{failed[0]}" if failed else ""
        _telegram_send(chat_id, f"❌ Für „{title}“ konnte keine Episode geladen werden.{detail}")
        return

    jf_client = get_jellyfin_client()
    with state.jellyfin_cache_lock:
        jellyfin_generation = state.jellyfin_config_generation
    if not jf_client.configured:
        suffix = f" · {len(failed)} fehlgeschlagen" if failed else ""
        _telegram_send(chat_id, f"✅ {len(completed)} Episode(n) von „{title}“ geladen{suffix}.")
        return

    log(f"Telegram: Jellyfin-Scan für Serie «{title}» gestartet.")
    jf_client.refresh_library()
    deadline = time.monotonic() + TELEGRAM_JELLYFIN_WAIT_SECONDS
    while time.monotonic() < deadline:
        items = get_jellyfin_episodes(force=True)
        series_items = get_jellyfin_series(force=True)
        with state.jellyfin_cache_lock:
            data_generation = state.jellyfin_episode_data_generation
            current_generation = state.jellyfin_config_generation
            episodes_available = state.jellyfin_episodes_available
            series_available = state.jellyfin_series_available
        if current_generation != jellyfin_generation:
            jellyfin_generation = current_generation
            jf_client = get_jellyfin_client()
            if not jf_client.configured:
                suffix = f" · {len(failed)} fehlgeschlagen" if failed else ""
                _telegram_send(
                    chat_id,
                    f"✅ {len(completed)} Episode(n) von „{title}“ geladen{suffix}. "
                    "Jellyfin ist nicht konfiguriert.",
                )
                return
            jf_client.refresh_library()
        if (
            items is None or series_items is None
            or not episodes_available
            or not series_available
        ):
            time.sleep(15)
            continue
        series_ids = jf_client.series_ids_for(
            title,
            tmdb_id=group.get("tmdb_id", ""),
            aliases=group.get("aliases", ()),
            items=series_items,
        )
        if series_ids is None:
            time.sleep(15)
            continue
        if all(
            jf_client.has_episode(
                title, item["season"], item["episode"], items=items,
                aliases=group.get("aliases", ()), series_ids=series_ids,
            )
            for item in completed
        ):
            with state.jellyfin_cache_lock:
                stale = (
                    jellyfin_generation != state.jellyfin_config_generation
                    or data_generation != state.jellyfin_episode_data_generation
                )
            if stale:
                continue
            suffix = f" · {len(failed)} fehlgeschlagen" if failed else ""
            _telegram_send(
                chat_id,
                f"✅ „{title}“: {len(completed)} Episode(n) sind jetzt in Jellyfin verfügbar{suffix}.",
            )
            return
        time.sleep(15)

    suffix = f" {len(failed)} Download(s) sind fehlgeschlagen." if failed else ""
    _telegram_send(
        chat_id,
        f"⚠️ {len(completed)} Episode(n) von „{title}“ wurden geladen, sind aber nach 30 Minuten noch nicht vollständig in Jellyfin erschienen.{suffix}",
    )


# ---------------------------------------------------------------------------
# Seerr-Anfragen (Moonfin/Fire TV -> Seerr -> Royal Downloader)
# ---------------------------------------------------------------------------
SEERR_MEDIA_AVAILABLE = 5
SEERR_SCAN_RETRY_SECONDS = 5 * 60


def configure_moonfin_seerr(seerr_url: str, enabled: bool) -> dict:
    """Konfiguriert Plugin 1.9.1 und aktuelle Versionen ohne andere Werte zu löschen."""
    jf_url = str(state.jellyfin_cfg.get("url") or "").strip().rstrip("/")
    api_key = str(state.jellyfin_cfg.get("api_key") or "").strip()
    user_id = str(state.jellyfin_cfg.get("user_id") or "").strip()
    if not jf_url or not api_key:
        return {"configured": False, "detail": "Jellyfin ist nicht konfiguriert."}
    session = requests.Session()
    headers = {"X-Emby-Token": api_key, "Accept": "application/json"}
    try:
        response = session.get(f"{jf_url}/Plugins", headers=headers, timeout=10)
        response.raise_for_status()
        plugins = response.json()
        plugin = next(
            (item for item in plugins if str(item.get("Name") or "").casefold() == "moonfin"),
            None,
        )
        if not plugin or not plugin.get("Id"):
            return {"configured": False, "detail": "Moonfin-Plugin ist nicht installiert."}
        plugin_id = plugin["Id"]
        config_url = f"{jf_url}/Plugins/{plugin_id}/Configuration"
        response = session.get(config_url, headers=headers, timeout=10)
        response.raise_for_status()
        plugin_config = response.json()
        if "SeerrEnabled" in plugin_config or "SeerrUrl" in plugin_config:
            plugin_config.update({
                "SeerrEnabled": bool(enabled),
                "SeerrUrl": seerr_url,
                "SeerrDisplayName": "Seerr",
            })
        else:
            plugin_config.update({
                "JellyseerrEnabled": bool(enabled),
                "JellyseerrUrl": seerr_url,
                "JellyseerrDisplayName": "Seerr",
            })
        # Benutzerprofil zuerst speichern. Das anschließende Admin-Config-POST
        # kann das Plugin kurz neu laden; umgekehrt wäre das Profil-POST racy.
        if user_id:
            settings_url = f"{jf_url}/Moonfin/Settings/{user_id}"
            response = session.get(settings_url, headers=headers, timeout=10)
            current = response.json() if response.status_code == 200 else {}
            settings = dict(current) if isinstance(current, dict) else {}
            settings["schemaVersion"] = 2
            settings["syncEnabled"] = True
            for profile_name in ("global", "tv"):
                profile = settings.get(profile_name)
                profile = dict(profile) if isinstance(profile, dict) else {}
                profile["jellyseerrEnabled"] = bool(enabled)
                settings[profile_name] = profile
            response = session.post(
                settings_url,
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "settings": settings,
                    "clientId": "royal-downloader",
                    "mergeMode": "merge",
                },
                timeout=10,
            )
            response.raise_for_status()
        response = session.post(
            config_url, headers={**headers, "Content-Type": "application/json"},
            json=plugin_config, timeout=10,
        )
        response.raise_for_status()
        return {"configured": True, "detail": "Moonfin wurde konfiguriert."}
    except (requests.RequestException, ValueError, TypeError) as exc:
        return {"configured": False, "detail": f"Moonfin-Konfiguration fehlgeschlagen: {exc}"}


def _seerr_client() -> SeerrClient:
    return SeerrClient(
        state.seerr_cfg.get("url", ""),
        state.seerr_cfg.get("api_key", ""),
    )


def _save_seerr_requests_locked() -> bool:
    snapshot = {key: dict(value) for key, value in state.seerr_requests.items()}
    return appconfig.save_seerr_requests(snapshot)


def _seerr_update_record(request_id, **updates) -> dict:
    key = str(request_id)
    with state.seerr_requests_lock:
        record = state.seerr_requests.setdefault(key, {"request_id": int(request_id)})
        record.update(updates)
        record["updated_at"] = time.time()
        _save_seerr_requests_locked()
        return dict(record)


def _seerr_mark_failure(request_id, message: str, status: str = "failed") -> None:
    key = str(request_id)
    with state.seerr_requests_lock:
        record = state.seerr_requests.setdefault(key, {"request_id": int(request_id)})
        attempts = int(record.get("attempts", 0) or 0) + 1
        retry_delay = min(6 * 60 * 60, 5 * 60 * (2 ** min(attempts - 1, 6)))
        if status == "needs_review":
            retry_delay = max(retry_delay, 24 * 60 * 60)
        record.update({
            "status": status,
            "message": str(message)[:400],
            "attempts": attempts,
            "next_retry": time.time() + retry_delay,
            "pending_slugs": [],
            "updated_at": time.time(),
        })
        _save_seerr_requests_locked()
    log(f"Seerr #{request_id}: {message}", "warn")


def _seerr_job_result(job: dict, slug: str, ok: bool, message: str, out_path: Path) -> None:
    request_id = str(job.get("request_id", ""))
    if not request_id:
        return
    with state.seerr_requests_lock:
        record = state.seerr_requests.get(request_id)
        if not record:
            return
        pending = [value for value in record.get("pending_slugs", []) if value != slug]
        completed = list(record.get("completed_slugs", []))
        failures = list(record.get("failures", []))
        if ok:
            if slug not in completed:
                completed.append(slug)
        else:
            failures.append({"slug": slug, "message": str(message)[:240]})
        record.update({
            "pending_slugs": pending,
            "completed_slugs": completed,
            "failures": failures[-50:],
            "updated_at": time.time(),
        })
        if not pending:
            if failures:
                record["status"] = "partial" if completed else "failed"
                attempts = int(record.get("attempts", 0) or 0) + 1
                record["attempts"] = attempts
                record["next_retry"] = time.time() + min(
                    6 * 60 * 60, 5 * 60 * (2 ** min(attempts - 1, 6)),
                )
                record["message"] = (
                    f"{len(completed)} erfolgreich, {len(failures)} fehlgeschlagen"
                    if completed else str(message)[:400]
                )
            else:
                record["status"] = "completed"
                record["message"] = "Download abgeschlossen; Seerr wartet auf den Jellyfin-Scan."
                record["next_retry"] = 0
        _save_seerr_requests_locked()
    if not record.get("pending_slugs"):
        log(
            f"Seerr #{request_id}: {record.get('status')} "
            f"({len(record.get('completed_slugs', []))} Download(s))"
        )


def _seerr_terminal_without_job(slug: str, ok: bool, message: str, out_path: Path) -> None:
    with state.queue_claim_lock:
        state.picked.discard(slug)
    _persist_queue_state()
    with state.seerr_jobs_lock:
        jobs = state.seerr_jobs.pop(slug, [])
    for job in jobs:
        _seerr_job_result(job, slug, ok, message, out_path)


def _seerr_register_request_jobs(request_id, items: dict, title: str, **record_values) -> None:
    pending_slugs = list(items)
    _seerr_update_record(
        request_id,
        status="queued",
        title=title,
        pending_slugs=pending_slugs,
        slugs=sorted(set(record_values.pop("slugs", [])) | set(pending_slugs)),
        items=items,
        failures=[],
        message=f"{len(pending_slugs)} Download(s) eingeplant.",
        **record_values,
    )
    with state.seerr_jobs_lock:
        for slug, item in items.items():
            job = {
                "request_id": str(request_id),
                "title": title,
                **item,
            }
            jobs = state.seerr_jobs.setdefault(slug, [])
            jobs[:] = [
                existing for existing in jobs
                if str(existing.get("request_id", "")) != str(request_id)
            ]
            jobs.append(job)


def _seerr_movie_title_key(value: str) -> str:
    """Normalisiert Quelltitel inklusive optional angehängtem Erscheinungsjahr."""
    title = clean_movie_title(str(value or "").strip())
    title = re.sub(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$", "", title).strip()
    return _norm_title(title)


def _seerr_movie_aliases(title: str, original_title: str) -> List[tuple[str, str]]:
    """Liefert nur Aliase, die von den überwiegend lateinischen Katalogen suchbar sind."""
    aliases: List[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_value in (title, original_title):
        value = " ".join(str(raw_value or "").split()).strip()
        key = _seerr_movie_title_key(value)
        # CJK-/sonstige Originaltitel wurden bisher zu einem leeren Schlüssel
        # und ließen dadurch beliebige Treffer wie exakte Matches aussehen.
        if not value or not key or key in seen:
            continue
        seen.add(key)
        aliases.append((value, key))
    return aliases


def _seerr_http_status(exc: Exception) -> int:
    response = getattr(exc, "response", None)
    for value in (getattr(response, "status_code", None), getattr(exc, "code", None)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return 0


def _seerr_explicitly_non_german(movie: FilmpalastMovie) -> bool:
    """True, wenn jeder Hoster explizit oder über seinen Anbieter nichtdeutsch ist."""
    hosters = list(movie.hosters or [])
    return bool(hosters) and all(
        (
            language := _movie_content_language(
                movie,
                str(getattr(hoster, "language", "") or ""),
            )
        )
        and language != "de"
        for hoster in hosters
    )


def _seerr_find_movie_sources(metadata: dict, tmdb_id: int) -> List[tuple]:
    """Findet wenige, exakt passende und TMDB-bestätigte deutsche Filmquellen."""
    title = str(metadata.get("title") or "").strip()
    original_title = str(metadata.get("original_title") or "").strip()
    year = str(metadata.get("year") or "").strip()
    aliases = _seerr_movie_aliases(title, original_title)
    if not aliases:
        raise RuntimeError(f"Kein durchsuchbarer Titel für „{title or tmdb_id}“ vorhanden")

    movie_options: List[tuple] = []
    attempted_slugs: set[str] = set()
    seen_urls: set[str] = set()
    rate_limited = False
    non_german_found = False
    tmdb_client = get_tmdb_client()
    max_detail_requests = 8

    for query, query_key in aliases:
        candidates = []
        for candidate in search_movie_candidates(query):
            if not candidate.is_movie or candidate.slug in attempted_slugs:
                continue
            if _seerr_movie_title_key(candidate.title) != query_key:
                continue
            candidate_year = str(candidate.year or "").strip()
            if year and candidate_year and candidate_year != year:
                continue
            candidates.append(candidate)
        candidates.sort(key=lambda candidate: (
            bool(year) and str(candidate.year or "").strip() != year,
            not bool(str(candidate.year or "").strip()),
            clean_movie_title(candidate.title).casefold(),
        ))

        for candidate in candidates:
            if len(attempted_slugs) >= max_detail_requests:
                break
            # Vor dem Netzaufruf markieren, damit derselbe Slug über einen
            # zweiten Alias nicht erneut geladen wird.
            attempted_slugs.add(candidate.slug)
            try:
                loaded = load_movie_for_slug(candidate.slug)
            except Exception as exc:
                status = _seerr_http_status(exc)
                rate_limited = rate_limited or status == 429
                suffix = f" (HTTP {status})" if status else f": {exc}"
                log(f"Seerr-Filmquelle übersprungen: {candidate.slug}{suffix}", "warn")
                continue
            if not loaded or not loaded.hosters:
                continue

            loaded_title = clean_movie_title(loaded.title)
            loaded_key = _seerr_movie_title_key(loaded_title)
            if loaded_key not in {key for _value, key in aliases}:
                continue
            loaded_year = str(loaded.year or candidate.year or "").strip()
            if year and loaded_year and loaded_year != year:
                continue
            try:
                summary = tmdb_client.movie_summary(loaded_title, loaded_year or year)
            except Exception as exc:
                status = _seerr_http_status(exc)
                rate_limited = rate_limited or status == 429
                log(f"TMDB-Prüfung für „{loaded_title}“ übersprungen: {exc}", "warn")
                continue
            if not summary or int(summary.get("tmdb_id") or 0) != int(tmdb_id):
                continue
            if _seerr_explicitly_non_german(loaded):
                non_german_found = True
                log(f"Seerr-Filmquelle ohne deutsche Tonspur übersprungen: {loaded_title}", "warn")
                continue
            if loaded.url in seen_urls:
                continue
            seen_urls.add(loaded.url)
            movie_options.append((candidate, loaded))

        # Der lokalisierte Titel hatte bestätigte Quellen. Den Originaltitel
        # nicht zusätzlich über alle vier Anbieter schicken.
        if movie_options:
            break
        if len(attempted_slugs) >= max_detail_requests:
            break

    if movie_options:
        movie_options.sort(key=lambda value: not any(
            bool(getattr(hoster, "is_de", False))
            for hoster in (value[1].hosters or [])
        ))
        return movie_options
    if rate_limited:
        raise RuntimeError("Filmquellen vorübergehend begrenzt (HTTP 429); neuer Versuch folgt")
    if non_german_found:
        raise RuntimeError(f"„{title}“ gefunden, aber derzeit ohne deutsche Tonspur")
    raise RuntimeError(f"Keine eindeutige Downloadquelle für „{title}“ gefunden")


def _seerr_process_movie(request: SeerrRequest, metadata: dict) -> None:
    request_id = request.request_id
    jf_client = get_jellyfin_client()
    jf_items = get_jellyfin_library(force=True)
    with state.jellyfin_cache_lock:
        library_available = state.jellyfin_library_available
    if not jf_client.configured or jf_items is None or not library_available:
        raise RuntimeError("Jellyfin ist für den sicheren Duplikat-Check nicht erreichbar")

    title = str(metadata.get("title") or "").strip()
    year = str(metadata.get("year") or "")
    if jf_client.match(title, year, items=jf_items, tmdb_id=request.tmdb_id):
        _seerr_update_record(
            request_id, status="available", title=title,
            message="Bereits in Jellyfin vorhanden.", next_retry=0,
        )
        return

    movie_options = _seerr_find_movie_sources(metadata, request.tmdb_id)

    chosen, movie = movie_options[0]
    fallbacks = [value for _candidate, value in movie_options[1:]]
    already_available, reason = _content_already_available(movie, chosen.slug)
    if already_available:
        if _is_jellyfin_safety_block(reason):
            raise RuntimeError(reason)
        _seerr_update_record(
            request_id, status="completed", title=title,
            message=f"Bereits {reason}.", next_retry=0,
        )
        return

    with state.queue_lifecycle_lock:
        active = any(chosen.slug in _job_queue_slugs(job) for job in state.dl_queue.active_jobs())
        with state.queue_claim_lock:
            with state.download_state_lock:
                already_queued = (
                    chosen.slug in state.picked
                    or chosen.slug in state.counted_queue_slugs
                    or active
                )
            if not already_queued:
                state.picked.add(chosen.slug)
    state.fp_movies[chosen.slug] = movie
    item = {
        "kind": "movie", "year": year,
        "tmdb_id": request.tmdb_id,
    }
    _seerr_register_request_jobs(
        request_id, {chosen.slug: item}, title,
        media_type="movie", tmdb_id=request.tmdb_id,
        seasons=[], is_4k=request.is_4k,
    )
    if not already_queued and not _persist_new_queue_claims({chosen.slug}):
        _seerr_terminal_without_job(
            chosen.slug, False, "Queue-Zustand konnte nicht gespeichert werden", Path(""),
        )
        return
    if already_queued:
        log(f"Seerr #{request_id}: „{title}“ an laufenden Download angehängt.")
        return
    accepted = _enqueue_automatic_downloads(
        [chosen.slug], movie_fallbacks={chosen.slug: fallbacks}, taste_source="seerr",
    )
    if chosen.slug not in accepted:
        _seerr_terminal_without_job(
            chosen.slug, False, "Downloadstart fehlgeschlagen", Path(""),
        )


def _seerr_find_series(metadata: dict) -> Optional[FilmpalastSeries]:
    titles = list(dict.fromkeys(filter(None, (
        str(metadata.get("title") or "").strip(),
        str(metadata.get("original_title") or "").strip(),
    ))))
    wanted = {_norm_title(value) for value in titles if _norm_title(value)}
    matches: Dict[str, FilmpalastSeriesResult] = {}
    for query in titles:
        for candidate in search_series_candidates(query):
            if _norm_title(candidate.title) in wanted:
                matches.setdefault(candidate.sample_slug, candidate)
    if not matches:
        return None
    candidates = list(matches.values())
    year = str(metadata.get("year") or "")
    if year:
        same_year = [candidate for candidate in candidates if str(candidate.year or "") == year]
        if same_year:
            candidates = same_year
        else:
            unknown_year = [candidate for candidate in candidates if not candidate.year]
            if unknown_year:
                candidates = unknown_year
            else:
                raise RuntimeError(
                    "Serientreffer hat ein abweichendes Erscheinungsjahr und muss geprüft werden"
                )
    wanted_tmdb_id = str(metadata.get("tmdb_id") or "").strip()
    tmdb = get_tmdb_client()
    verified = [
        candidate for candidate in candidates
        if tmdb.series_matches_id(
            strip_source_suffix(candidate.title), wanted_tmdb_id, year,
        )
    ]
    if not verified:
        raise RuntimeError(
            "Serientreffer ist ohne bestätigte TMDB-ID mehrdeutig und muss geprüft werden"
        )
    # Mehrere bestätigte Treffer derselben TMDB-Serie sind Anbieter-Fallbacks;
    # search_series_candidates liefert sie bereits in Nutzerpriorität.
    return get_series_for_value(verified[0].sample_slug)


def _seerr_process_series(request: SeerrRequest, metadata: dict) -> None:
    request_id = request.request_id
    jf_client = get_jellyfin_client()
    if not jf_client.configured:
        raise RuntimeError("Jellyfin ist nicht konfiguriert")
    series = _seerr_find_series(metadata)
    if series is None or not series.all_episodes:
        raise RuntimeError(
            f"Keine eindeutige Downloadquelle für „{metadata.get('title') or request.tmdb_id}“ gefunden"
        )

    requested_seasons = set(request.seasons)
    unreleased_slugs = _unreleased_episode_slugs(series, request.tmdb_id)
    selected = [
        episode for episode in series.all_episodes
        if (not requested_seasons or episode.season in requested_seasons)
        and episode.slug not in unreleased_slugs
    ]
    if not selected:
        raise RuntimeError("Die angeforderten Staffeln sind beim Anbieter nicht vorhanden")

    downloaded = compute_downloaded_episodes(series)
    jf_episodes = get_jellyfin_episodes(force=True)
    jf_series = get_jellyfin_series(force=True)
    with state.jellyfin_cache_lock:
        jf_available = state.jellyfin_episodes_available and state.jellyfin_series_available
    if jf_episodes is None or jf_series is None or not jf_available:
        raise RuntimeError("Jellyfin ist für den sicheren Duplikat-Check nicht erreichbar")
    aliases = tuple(dict.fromkeys(filter(None, (
        series.title,
        metadata.get("title", ""),
        metadata.get("original_title", ""),
    ))))
    series_ids = jf_client.series_ids_for(
        series.title, tmdb_id=request.tmdb_id, aliases=aliases, items=jf_series,
    )
    if series_ids is None:
        raise RuntimeError("Jellyfin-Zuordnung der Serie ist mehrdeutig")
    missing = [
        episode for episode in selected
        if episode.slug not in downloaded
        and not jf_client.has_episode(
            series.title, episode.season, episode.episode,
            items=jf_episodes, aliases=aliases, series_ids=series_ids,
        )
    ]
    if not missing:
        pending_unreleased = sum(
            1 for episode in series.all_episodes
            if (not requested_seasons or episode.season in requested_seasons)
            and episode.slug in unreleased_slugs
        )
        if pending_unreleased:
            _seerr_update_record(
                request_id, status="queued", title=series.title,
                message=(
                    f"{pending_unreleased} Episode(n) noch nicht erschienen – "
                    "wird automatisch nachgeladen, sobald verfügbar."
                ),
                next_retry=0,
            )
        else:
            _seerr_update_record(
                request_id, status="available", title=series.title,
                message="Alle angeforderten Episoden sind bereits vorhanden.", next_retry=0,
            )
        return

    movies: Dict[str, FilmpalastMovie] = {}
    episode_items: Dict[str, dict] = {}
    for episode in missing:
        try:
            movie = load_movie_for_slug(episode.slug)
        except Exception as exc:
            movie = None
            log(f"Seerr-Serie: {episode.label} nicht direkt ladbar: {exc}", "warn")
        if not movie or not movie.hosters:
            movie = _episode_placeholder(episode.slug, series.title)
        movies[episode.slug] = movie
        episode_items[episode.slug] = {
            "kind": "series", "season": episode.season,
            "episode": episode.episode, "tmdb_id": request.tmdb_id,
        }

    candidate_slugs = set(movies)
    with state.queue_lifecycle_lock:
        active_slugs = {
            slug for job in state.dl_queue.active_jobs() for slug in _job_queue_slugs(job)
        }
        with state.queue_claim_lock:
            with state.download_state_lock:
                existing = candidate_slugs & (
                    set(state.picked) | set(state.counted_queue_slugs) | active_slugs
                )
                new_slugs = candidate_slugs - existing
            state.picked.update(new_slugs)
    tracked_slugs = existing | new_slugs
    for slug in tracked_slugs:
        state.fp_movies[slug] = movies[slug]
    items = {slug: episode_items[slug] for slug in tracked_slugs}
    _seerr_register_request_jobs(
        request_id, items, series.title,
        media_type="tv", tmdb_id=request.tmdb_id,
        seasons=list(request.seasons), is_4k=request.is_4k,
    )
    if new_slugs and not _persist_new_queue_claims(new_slugs):
        for slug in new_slugs:
            _seerr_terminal_without_job(
                slug, False, "Queue-Zustand konnte nicht gespeichert werden", Path(""),
            )
        return
    if new_slugs:
        accepted = _enqueue_automatic_downloads(sorted(new_slugs), taste_source="seerr")
        for slug in new_slugs - set(accepted):
            _seerr_terminal_without_job(
                slug, False, "Downloadstart fehlgeschlagen", Path(""),
            )
    if existing:
        log(f"Seerr #{request_id}: {len(existing)} Episode(n) an laufende Downloads angehängt.")


def _seerr_retry_completed_scan(request: SeerrRequest, previous: dict) -> None:
    """Stößt den Jellyfin-Scan erneut an, bis Seerr das Medium als verfügbar meldet."""
    now = time.time()
    last_retry = float(previous.get("last_scan_retry", 0) or 0)
    if now - last_retry < SEERR_SCAN_RETRY_SECONDS:
        return
    with state.seerr_scan_retry_lock:
        if now - state.seerr_last_scan_retry < SEERR_SCAN_RETRY_SECONDS:
            return
        state.seerr_last_scan_retry = now
    jellyfin = get_jellyfin_client()
    started = bool(jellyfin.configured and jellyfin.refresh_library())
    message = (
        "Download abgeschlossen; Jellyfin-Scan erneut gestartet."
        if started
        else "Download abgeschlossen; Jellyfin-Scan konnte nicht gestartet werden."
    )
    _seerr_update_record(
        request.request_id,
        status="completed",
        last_scan_retry=now,
        message=message,
    )
    if not started:
        log(f"Seerr #{request.request_id}: {message}", "warn")


def _seerr_record_matches_request(record: dict, request: SeerrRequest) -> bool:
    required = {"media_type", "tmdb_id", "seasons", "is_4k"}
    if not required.issubset(record):
        return False
    try:
        stored_seasons = tuple(sorted(int(value) for value in record.get("seasons", [])))
    except (TypeError, ValueError, OverflowError):
        return False
    stored_4k = record.get("is_4k")
    if isinstance(stored_4k, str):
        stored_4k = stored_4k.strip().casefold() in {"1", "true", "yes", "on"}
    return (
        str(record.get("media_type") or "").casefold() == request.media_type
        and str(record.get("tmdb_id") or "") == str(request.tmdb_id)
        and stored_seasons == tuple(request.seasons)
        and bool(stored_4k) == request.is_4k
    )


def _seerr_reset_reused_request(request_id: str) -> None:
    """Entkoppelt lokalen Altzustand, wenn Seerr eine Request-ID neu verwendet."""
    with state.seerr_jobs_lock:
        for slug, jobs in list(state.seerr_jobs.items()):
            remaining = [
                job for job in jobs
                if str(job.get("request_id", "")) != request_id
            ]
            if remaining:
                state.seerr_jobs[slug] = remaining
            else:
                state.seerr_jobs.pop(slug, None)
    with state.seerr_requests_lock:
        state.seerr_requests.pop(request_id, None)
        _save_seerr_requests_locked()
    log(f"Seerr #{request_id}: geänderte Anfrage erkannt; Altzustand verworfen.")


def _seerr_process_request(request: SeerrRequest) -> None:
    request_id = str(request.request_id)
    with state.seerr_requests_lock:
        previous = dict(state.seerr_requests.get(request_id, {}))
    if previous and not _seerr_record_matches_request(previous, request):
        _seerr_reset_reused_request(request_id)
        previous = {}
    status = previous.get("status", "")
    if request.media_status == SEERR_MEDIA_AVAILABLE:
        if status != "available":
            _seerr_update_record(
                request.request_id, status="available", media_type=request.media_type,
                tmdb_id=request.tmdb_id, seasons=list(request.seasons),
                is_4k=request.is_4k, message="In Jellyfin verfügbar.", next_retry=0,
            )
        return
    if request.is_4k:
        if previous.get("seerr_declined"):
            return
        now = time.time()
        if status == "unsupported" and now < float(previous.get("next_retry", 0) or 0):
            return
        try:
            client = _seerr_client()
            declined = client.decline_request(request.request_id)
            decline_error = getattr(client, "last_error", "")
        except Exception as exc:
            declined = False
            decline_error = str(exc)
        message = (
            "4K-Anfrage in Seerr abgelehnt: Die Downloadquelle garantiert keine 4K-Qualität."
            if declined
            else (
                "4K wird nicht geladen; Seerr-Ablehnung wird erneut versucht"
                + (f": {decline_error}" if decline_error else ".")
            )
        )
        _seerr_update_record(
            request.request_id,
            status="unsupported",
            media_type=request.media_type,
            tmdb_id=request.tmdb_id,
            seasons=list(request.seasons),
            is_4k=True,
            seerr_declined=declined,
            message=message,
            next_retry=0 if declined else now + SEERR_SCAN_RETRY_SECONDS,
        )
        if not declined:
            log(f"Seerr #{request.request_id}: {message}", "warn")
        return
    if status == "completed":
        _seerr_retry_completed_scan(request, previous)
        return
    if status in ("available", "unsupported"):
        return
    if status == "queued":
        pending = set(previous.get("pending_slugs", []))
        with state.queue_claim_lock:
            active = pending & set(state.picked)
        if active:
            return
    if status in ("failed", "partial", "needs_review"):
        if time.time() < float(previous.get("next_retry", 0) or 0):
            return

    _seerr_update_record(
        request.request_id,
        status="resolving",
        media_type=request.media_type,
        tmdb_id=request.tmdb_id,
        seasons=list(request.seasons),
        is_4k=request.is_4k,
        message="Quelle und Jellyfin-Bestand werden geprüft.",
        pending_slugs=[],
    )
    try:
        tmdb = get_tmdb_client()
        if not tmdb.configured:
            raise RuntimeError("TMDB ist nicht konfiguriert")
        if request.media_type == "movie":
            metadata = tmdb.movie_by_id(request.tmdb_id)
            if not metadata:
                raise RuntimeError(f"TMDB-Film {request.tmdb_id} wurde nicht gefunden")
            _seerr_process_movie(request, metadata)
        else:
            metadata = tmdb.series_by_id(request.tmdb_id)
            if not metadata:
                raise RuntimeError(f"TMDB-Serie {request.tmdb_id} wurde nicht gefunden")
            _seerr_process_series(request, metadata)
    except Exception as exc:
        detail = str(exc).casefold()
        kind = (
            "needs_review"
            if "mehrdeutig" in detail or "abweichendes erscheinungsjahr" in detail
            else "failed"
        )
        _seerr_mark_failure(request.request_id, str(exc), kind)


def _hydrate_seerr_jobs() -> None:
    """Verknüpft persistierte Seerr-Wünsche wieder mit der Queue."""
    stale = []
    with state.seerr_requests_lock:
        records = [(key, dict(value)) for key, value in state.seerr_requests.items()]
    with state.queue_claim_lock:
        picked = set(state.picked)
    with state.seerr_jobs_lock:
        for request_id, record in records:
            if record.get("status") != "queued":
                continue
            pending = set(record.get("pending_slugs", []))
            active = pending & picked
            item_map = record.get("items") if isinstance(record.get("items"), dict) else {}
            for slug in active:
                item = item_map.get(slug) if isinstance(item_map.get(slug), dict) else {}
                job = {
                    "request_id": request_id,
                    "title": record.get("title", ""),
                    **item,
                }
                jobs = state.seerr_jobs.setdefault(slug, [])
                if not any(
                    str(existing.get("request_id", "")) == str(request_id)
                    for existing in jobs
                ):
                    jobs.append(job)
            if pending and not active:
                stale.append(request_id)
    for request_id in stale:
        _seerr_mark_failure(request_id, "Offene Queue-Zuordnung nach Neustart verloren")


def seerr_poll_once() -> dict:
    if not state.seerr_poll_lock.acquire(blocking=False):
        return {"ok": False, "detail": "Seerr-Abgleich läuft bereits."}
    try:
        state.seerr_last_poll = time.time()
        cfg = dict(state.seerr_cfg)
        client = _seerr_client()
        if not cfg.get("enabled"):
            return {"ok": False, "detail": "Seerr-Integration ist deaktiviert."}
        if not client.configured:
            state.seerr_last_error = "Seerr-URL oder API-Schlüssel fehlt."
            return {"ok": False, "detail": state.seerr_last_error}
        if not client.test_connection():
            state.seerr_last_error = (
                getattr(client, "last_error", "")
                or "Seerr ist nicht erreichbar oder der API-Schlüssel ist ungültig."
            )
            return {"ok": False, "detail": state.seerr_last_error}
        requests = client.approved_requests()
        if getattr(client, "last_error", ""):
            state.seerr_last_error = client.last_error
            return {"ok": False, "detail": state.seerr_last_error}
        state.seerr_last_success = time.time()
        state.seerr_last_error = ""
        for request in requests:
            _seerr_process_request(request)
        if requests:
            log(f"Seerr-Abgleich: {len(requests)} genehmigte Anfrage(n) geprüft.")
        return {"ok": True, "requests": len(requests)}
    except Exception as exc:
        state.seerr_last_error = str(exc)[:300]
        log(f"Seerr-Abgleich fehlgeschlagen: {exc}", "warn")
        return {"ok": False, "detail": state.seerr_last_error}
    finally:
        state.seerr_poll_lock.release()


def seerr_poll_loop() -> None:
    _hydrate_seerr_jobs()
    while not _seerr_stop_event.is_set():
        if state.seerr_cfg.get("enabled"):
            seerr_poll_once()
        interval = max(15, int(state.seerr_cfg.get("poll_interval_seconds", 60) or 60))
        _seerr_wake_event.wait(interval)
        _seerr_wake_event.clear()


def _parse_telegram_series_request(text: str) -> Optional[dict]:
    if re.match(r"^/film(?:\s|$)", text.strip(), flags=re.IGNORECASE):
        return None
    value = re.sub(r"^/serie\s+", "", text.strip(), flags=re.IGNORECASE)
    match = re.match(
        r"^(?P<title>.+?)\s+(?:(?P<all>alles)|staffel\s*0*(?P<season>\d+)"
        r"(?:\s*(?:ep|e|episode|folge)\s*0*(?P<episode>\d+))?)\s*$",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    title = match.group("title").strip().strip('"„“')
    if not title:
        return None
    if match.group("all"):
        return {"title": title, "mode": "all", "season": None, "episode": None}
    season = int(match.group("season"))
    episode = int(match.group("episode")) if match.group("episode") else None
    return {
        "title": title,
        "mode": "episode" if episode is not None else "season",
        "season": season,
        "episode": episode,
    }


def _telegram_series_scope_label(request: dict) -> str:
    if request["mode"] == "all":
        return "alle fehlenden Episoden"
    if request["mode"] == "season":
        return f"Staffel {request['season']}"
    return f"Staffel {request['season']} Episode {request['episode']}"


def _telegram_best_result(query: str, results: List[FilmpalastSearchResult]) -> List[FilmpalastSearchResult]:
    wanted = _norm_title(query)
    return sorted(
        results,
        key=lambda result: (
            _norm_title(result.title) != wanted,
            wanted not in _norm_title(result.title),
            strip_source_suffix(result.title).casefold(),
        ),
    )


def _format_storage_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024 or unit == "PiB":
            return f"{size:.0f} {unit}" if unit in ("B", "KiB", "MiB") else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PiB"


def _telegram_storage_text() -> str:
    lines = ["💾 NAS-Speicher"]
    seen_volumes = {}
    for label, raw_path in (("Filme", state.save_path), ("Serien", state.series_path)):
        path = Path(raw_path)
        try:
            usage = shutil.disk_usage(path)
            device = os.stat(path).st_dev
            if device in seen_volumes:
                lines.append(f"{label}: gemeinsames Volume mit {seen_volumes[device]} ({path})")
                continue
            seen_volumes[device] = label
            percent = (usage.used / usage.total * 100) if usage.total else 0
            lines.append(
                f"{label} ({path})\n"
                f"  {_format_storage_size(usage.free)} frei von {_format_storage_size(usage.total)} · {percent:.1f}% belegt"
            )
        except OSError as exc:
            lines.append(f"{label} ({path}): nicht erreichbar ({exc})")
    return "\n".join(lines)


def _telegram_paths_text() -> str:
    lines = ["📁 Speicherpfade"]
    for label, raw_path in (("Filme", state.save_path), ("Serien", state.series_path)):
        path = Path(raw_path)
        status = "erreichbar" if path.is_dir() else "nicht erreichbar"
        lines.append(f"{label}: {path} · {status}")
    return "\n".join(lines)


def _telegram_watchlist_text() -> str:
    if not state.watchlist:
        return "📺 Keine Serien abonniert."
    lines = [f"📺 Abonnierte Serien: {len(state.watchlist)}"]
    for entry in state.watchlist[:25]:
        new_count = len(state.watchlist_new_slugs.get(entry["base_slug"], set()))
        suffix = f" · {new_count} neu" if new_count else ""
        lines.append(f"• {entry['title']}{suffix}")
    if len(state.watchlist) > 25:
        lines.append(f"… und {len(state.watchlist) - 25} weitere")
    return "\n".join(lines)


def _telegram_help_text() -> str:
    return (
        "Royal Downloader\n"
        "Filmtitel – Film prüfen und herunterladen\n"
        "/film Filmtitel – Film ausdrücklich auswählen\n"
        "Serientitel ALLES\n"
        "Serientitel Staffel 2\n"
        "Serientitel Staffel 2 EP 5\n"
        "Mehrere Film- und Serientreffer werden mit Cover zur Auswahl angezeigt.\n"
        "/status – laufende Downloads\n"
        "/speicher – freier NAS-Speicher\n"
        "/pfade – Film- und Serienpfad\n"
        "/abos – abonnierte Serien\n"
        "/jellyfin – Bibliotheksstatus\n"
        "/hilfe – diese Übersicht"
    )


def _run_telegram_series_request(
    chat_id: str,
    request: dict,
    series_value: str,
    wait_for_lock: bool = False,
):
    if not state.telegram_request_lock.acquire(blocking=wait_for_lock):
        _telegram_send(chat_id, "Ein anderer Telegram-Wunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    try:
        jf_client = get_jellyfin_client()
        if not jf_client.configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return

        scope_label = _telegram_series_scope_label(request)
        _telegram_send(chat_id, f"🔎 Lade Serie „{request['title']}“ · {scope_label} …")
        series = get_series_for_value(series_value)
        if series is None or not series.all_episodes:
            _telegram_send(chat_id, f"❌ Serie „{request['title']}“ nicht gefunden.")
            return

        selected = list(series.all_episodes)
        if request["mode"] in ("season", "episode"):
            selected = [ep for ep in selected if ep.season == request["season"]]
        if request["mode"] == "episode":
            selected = [ep for ep in selected if ep.episode == request["episode"]]
        if not selected:
            _telegram_send(chat_id, f"❌ „{series.title}“ enthält {scope_label} nicht.")
            return

        downloaded = compute_downloaded_episodes(series)
        jf_episodes = get_jellyfin_episodes(force=True)
        jf_series = get_jellyfin_series(force=True)
        with state.jellyfin_cache_lock:
            jf_available = (
                state.jellyfin_episodes_available and state.jellyfin_series_available
            )
        if jf_episodes is None or jf_series is None or not jf_available:
            _telegram_send(chat_id, "Jellyfin ist nicht erreichbar. Download wurde zum Duplikatschutz nicht gestartet.")
            return
        try:
            aliases, series_ids, tmdb_id = _episode_jellyfin_identity(
                series.base_slug, series.title, jf_client, jf_series,
            )
        except RuntimeError as exc:
            _telegram_send(chat_id, f"{exc}. Download wurde zum Duplikatschutz nicht gestartet.")
            return
        missing = [
            ep for ep in selected
            if ep.slug not in downloaded
            and not jf_client.has_episode(
                series.title, ep.season, ep.episode, items=jf_episodes,
                aliases=aliases, series_ids=series_ids,
            )
        ]
        if not missing:
            _telegram_send(chat_id, f"✅ „{series.title}“ · {scope_label} ist bereits vollständig vorhanden.")
            return

        _telegram_send(chat_id, f"⬇️ {len(missing)} fehlende Episode(n) werden vorbereitet …")
        jobs: List[tuple] = []
        initial_failures: List[str] = []
        episode_by_slug = {ep.slug: ep for ep in missing}
        for ep in missing:
            try:
                movie = load_movie_for_slug(ep.slug)
            except Exception as exc:
                movie = None
                log(f"Telegram-Serie: {ep.label} nicht ladbar: {exc}", "warn")
            if not movie or not movie.hosters:
                movie = _episode_placeholder(ep.slug, series.title)
                log(
                    f"Telegram-Serie: {ep.label} wird trotz blockierter "
                    "Episodenseite fuer Fallback/Retry eingeplant.",
                    "warn",
                )
            already_available, reason = _content_already_available(movie, ep.slug)
            if already_available:
                initial_failures.append(f"{ep.label}: {reason}")
                continue
            state.fp_movies[ep.slug] = movie
            jobs.append((movie, ep.slug))

        if not jobs:
            _telegram_send(
                chat_id,
                f"❌ Für „{series.title}“ konnte keine der {len(missing)} fehlenden Episoden gestartet werden.",
            )
            return

        request_id = f"{chat_id}:{time.time_ns()}"
        candidate_slugs = {slug for _movie, slug in jobs}
        with state.queue_lifecycle_lock:
            active_slugs = {
                slug for job in state.dl_queue.active_jobs() for slug in _job_queue_slugs(job)
            }
            with state.queue_claim_lock:
                with state.download_state_lock:
                    pending_slugs = {
                        slug for slug in candidate_slugs
                        if slug not in state.picked
                        and slug not in state.counted_queue_slugs
                        and slug not in active_slugs
                    }
                state.picked.update(pending_slugs)
        jobs = [(movie, slug) for movie, slug in jobs if slug in pending_slugs]
        if not jobs:
            _telegram_send(chat_id, "Alle fehlenden Episoden sind bereits eingeplant.")
            return
        group = {
            "chat_id": chat_id,
            "title": series.title,
            "scope_label": scope_label,
            "pending_slugs": set(pending_slugs),
            "completed": [],
            "failed": list(initial_failures),
            "aliases": list(aliases),
            "tmdb_id": tmdb_id,
        }
        with state.telegram_jobs_lock:
            state.telegram_series_requests[request_id] = group
            for _movie, slug in jobs:
                ep = episode_by_slug[slug]
                state.telegram_jobs[slug] = {
                    "kind": "series",
                    "request_id": request_id,
                    "chat_id": chat_id,
                    "title": series.title,
                    "season": ep.season,
                    "episode": ep.episode,
                }

        if not _persist_new_queue_claims(pending_slugs):
            for slug in pending_slugs:
                _telegram_terminal_without_job(
                    slug, False, "Queue-Zustand konnte nicht gespeichert werden", Path(""),
                )
            return
        _telegram_send(chat_id, f"▶️ „{series.title}“ · {scope_label}: {len(jobs)} Download(s) starten.")

        try:
            accepted = _enqueue_automatic_downloads(list(pending_slugs), taste_source="telegram")
        except Exception:
            for slug in pending_slugs:
                _telegram_terminal_without_job(slug, False, "Downloadstart fehlgeschlagen", Path(""))
            raise
        for slug in pending_slugs - set(accepted):
            _telegram_terminal_without_job(slug, False, "kein Stream startbar", Path(""))
    except Exception as exc:
        log(f"Telegram-Serienwunsch fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Serienwunsch fehlgeschlagen: {exc}")
    finally:
        state.telegram_request_lock.release()


def _handle_telegram_series_request(chat_id: str, request: dict):
    title = str(request.get("title") or "").strip()
    if (
        title.startswith((
            SERIENSTREAM_PREFIX, HUHU_PREFIX, MOFLIX_PREFIX, EINSCHALTEN_PREFIX,
            KINOX_PREFIX, KINOGER_PREFIX, MEGAKINO_PREFIX, XCINE_PREFIX,
        ))
        or title.startswith("http://")
        or title.startswith("https://")
    ):
        _run_telegram_series_request(chat_id, request, title)
        return

    if not state.telegram_request_lock.acquire(blocking=False):
        _telegram_send(chat_id, "Ein anderer Telegram-Wunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    try:
        if not get_jellyfin_client().configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return
        scope_label = _telegram_series_scope_label(request)
        _telegram_send(chat_id, f"🔎 Suche Serie „{title}“ · {scope_label} …")
        results = _rank_telegram_series_results(title, search_series_candidates(title))
        if not results:
            _telegram_send(chat_id, f"❌ Serie „{title}“ nicht gefunden.")
            return
        if len(results) > 1:
            _publish_telegram_series_choices(chat_id, request, results)
            return
        selected_value = results[0].sample_slug
    except Exception as exc:
        log(f"Telegram-Seriensuche fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Seriensuche fehlgeschlagen: {exc}")
        return
    finally:
        state.telegram_request_lock.release()

    _run_telegram_series_request(chat_id, request, selected_value)


def _run_telegram_movie_request(
    chat_id: str,
    query: str,
    option: dict,
    wait_for_lock: bool = False,
):
    if not state.telegram_request_lock.acquire(blocking=wait_for_lock):
        _telegram_send(chat_id, "Ein anderer Telegram-Wunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    try:
        jf_client = get_jellyfin_client()
        if not jf_client.configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return

        movie = option["movie"]
        chosen_result = option["result"]
        fallback_movies = list(option.get("fallback_movies", []))
        title = str(option.get("title") or clean_movie_title(movie.title)).strip()
        year = str(option.get("year") or movie.year or chosen_result.year or "")
        _telegram_send(chat_id, f"🔎 Prüfe „{title}“{f' ({year})' if year else ''} …")

        jf_items = get_jellyfin_library(force=True)
        if jf_items is None or not state.jellyfin_library_available:
            _telegram_send(chat_id, "Jellyfin ist nicht erreichbar. Download wurde zum Duplikatschutz nicht gestartet.")
            return
        tmdb = get_tmdb_client().movie_summary(title, year)
        if jf_client.match(
            title, year, items=jf_items, tmdb_id=(tmdb or {}).get("tmdb_id", ""),
        ):
            _telegram_send(chat_id, f"✅ „{title}“ ist bereits in Jellyfin vorhanden.")
            return
        already_available, reason = _content_already_available(movie, chosen_result.slug)
        if already_available:
            _telegram_send(chat_id, f"Download nicht gestartet: „{title}“ ist {reason}.")
            return

        with state.queue_lifecycle_lock:
            physically_active = any(
                chosen_result.slug in _job_queue_slugs(job)
                for job in state.dl_queue.active_jobs()
            )
            with state.queue_claim_lock:
                with state.download_state_lock:
                    already_queued = (
                        chosen_result.slug in state.picked
                        or chosen_result.slug in state.counted_queue_slugs
                        or physically_active
                    )
                if not already_queued:
                    state.picked.add(chosen_result.slug)
        if already_queued:
            _telegram_send(chat_id, f"„{title}“ ist bereits eingeplant.")
            return

        state.fp_movies[chosen_result.slug] = movie
        if not _persist_new_queue_claims({chosen_result.slug}):
            _telegram_send(
                chat_id,
                "❌ Download nicht gestartet: Queue-Zustand konnte nicht gespeichert werden.",
            )
            return
        with state.telegram_jobs_lock:
            state.telegram_jobs[chosen_result.slug] = {
                "chat_id": chat_id,
                "query": query,
                "title": title,
                "year": year,
                "tmdb_id": (tmdb or {}).get("tmdb_id", ""),
            }

        source_count = 1 + len(fallback_movies)
        source_note = f" · {source_count} Filmquellen" if source_count > 1 else ""
        _telegram_send(
            chat_id,
            f"⬇️ Gefunden: „{title}“{f' ({year})' if year else ''}{source_note}. Download startet.",
        )
        try:
            accepted = _enqueue_automatic_downloads(
                [chosen_result.slug],
                movie_fallbacks={chosen_result.slug: fallback_movies},
                taste_source="telegram",
            )
        except Exception:
            _telegram_terminal_without_job(
                chosen_result.slug, False, "Downloadstart fehlgeschlagen", Path(""),
            )
            raise
        if chosen_result.slug not in accepted:
            _telegram_terminal_without_job(
                chosen_result.slug, False, "Downloadstart fehlgeschlagen", Path(""),
            )
    except Exception as exc:
        log(f"Telegram-Filmwunsch fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Filmwunsch fehlgeschlagen: {exc}")
    finally:
        state.telegram_request_lock.release()


def _handle_telegram_movie_request(chat_id: str, query: str):
    if not state.telegram_request_lock.acquire(blocking=False):
        _telegram_send(chat_id, "Ein anderer Telegram-Filmwunsch wird gerade verarbeitet. Versuche es gleich erneut.")
        return
    selected = None
    try:
        if not get_jellyfin_client().configured:
            _telegram_send(chat_id, "Jellyfin-URL oder API-Schlüssel fehlt in den Einstellungen.")
            return
        _telegram_send(chat_id, f"🔎 Suche Film „{query}“ …")
        results = search_movie_candidates(query)
        if not results:
            _telegram_send(chat_id, f"❌ Kein Film zu „{query}“ gefunden.")
            return
        options = _build_telegram_movie_options(query, results)
        if not options:
            _telegram_send(
                chat_id,
                f"❌ „{query}“ wurde gefunden, aber kein funktionierender Hoster ist verfügbar.",
            )
            return
        requires_selection = len(options) > 1
        options, existing_options, check_error = _filter_existing_telegram_movie_options(options)
        if options is None:
            _telegram_send(
                chat_id,
                f"{check_error}. Download wurde zum Duplikatschutz nicht angeboten.",
            )
            return
        if not options:
            _telegram_send(chat_id, f"✅ „{query}“ ist bereits vorhanden.")
            return
        if existing_options:
            count = len(existing_options)
            message = (
                "✅ 1 bereits vorhandener Treffer wird nicht zum Download angeboten."
                if count == 1
                else f"✅ {count} bereits vorhandene Treffer werden nicht zum Download angeboten."
            )
            _telegram_send(chat_id, message)
        if requires_selection or len(options) > 1:
            _publish_telegram_movie_choices(chat_id, query, options)
            return
        selected = options[0]
    except Exception as exc:
        log(f"Telegram-Filmsuche fehlgeschlagen: {exc}", "warn")
        _telegram_send(chat_id, f"❌ Filmsuche fehlgeschlagen: {exc}")
        return
    finally:
        state.telegram_request_lock.release()

    _run_telegram_movie_request(chat_id, query, selected)


def _clear_telegram_choice_keyboards(chat_id: str, message_ids: List[int]) -> None:
    bot = _telegram_bot
    if bot is None:
        return
    for message_id in message_ids:
        bot.clear_inline_keyboard(chat_id, message_id)


def handle_telegram_callback(
    chat_id: str, callback_query_id: str, data: str, sender_name: str = "",
):
    bot = _telegram_bot
    if bot is None:
        return
    allowed_chat = str(state.telegram_cfg.get("chat_id", "")).strip()
    if not allowed_chat or chat_id != allowed_chat:
        bot.answer_callback(callback_query_id, "Nicht erlaubt.")
        log(f"Telegram-Callback von nicht erlaubter Chat-ID {chat_id} verworfen.", "warn")
        return

    movie_next_match = re.fullmatch(r"mrn:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if movie_next_match:
        token, raw_index = movie_next_match.groups()
        status, entry = _prepare_telegram_movie_next_page(chat_id, token, int(raw_index))
        if status == "loading":
            bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
            return
        if status == "forbidden":
            bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
            return
        if status != "ok" or entry is None:
            bot.answer_callback(callback_query_id, "Seite abgelaufen oder bereits geladen.")
            return
        bot.answer_callback(callback_query_id, "Weitere Treffer werden geladen.")
        with state.telegram_choices_publish_lock:
            if not _send_telegram_movie_choice_page_locked(token, entry):
                _telegram_send(chat_id, "❌ Weitere Treffer konnten nicht gesendet werden.")
        return

    movie_match = re.fullmatch(r"mr:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if movie_match:
        token, raw_index = movie_match.groups()
        status, entry, option = _consume_telegram_movie_choice(
            chat_id, token, int(raw_index),
        )
        if status == "loading":
            bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
            return
        if status == "forbidden":
            bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
            return
        if status != "ok" or entry is None or option is None:
            bot.answer_callback(callback_query_id, "Auswahl abgelaufen oder bereits verwendet.")
            return
        title = str(option.get("title") or "Film")
        bot.answer_callback(callback_query_id, f"Ausgewählt: {title}")
        threading.Thread(
            target=_clear_telegram_choice_keyboards,
            args=(chat_id, list(entry.get("message_ids", []))),
            daemon=True,
        ).start()
        _telegram_send(chat_id, f"✅ Ausgewählt: „{title}“.")
        _run_telegram_movie_request(
            chat_id, entry["query"], option, wait_for_lock=True,
        )
        return

    next_match = re.fullmatch(r"srn:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if next_match:
        token, raw_index = next_match.groups()
        status, entry = _prepare_telegram_series_next_page(
            chat_id, token, int(raw_index),
        )
        if status == "loading":
            bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
            return
        if status == "forbidden":
            bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
            return
        if status != "ok" or entry is None:
            bot.answer_callback(callback_query_id, "Seite abgelaufen oder bereits geladen.")
            return
        bot.answer_callback(callback_query_id, "Weitere Treffer werden geladen.")
        with state.telegram_choices_publish_lock:
            if not _send_telegram_series_choice_page_locked(token, entry):
                _telegram_send(chat_id, "❌ Weitere Treffer konnten nicht gesendet werden.")
        return

    match = re.fullmatch(r"sr:([A-Za-z0-9_-]{8,32}):(\d{1,4})", data or "")
    if not match:
        bot.answer_callback(callback_query_id, "Unbekannte Auswahl.")
        return
    token, raw_index = match.groups()
    status, entry, candidate = _consume_telegram_series_choice(
        chat_id, token, int(raw_index),
    )
    if status == "loading":
        bot.answer_callback(callback_query_id, "Treffer werden noch geladen.")
        return
    if status == "forbidden":
        bot.answer_callback(callback_query_id, "Diese Auswahl gehört zu einem anderen Chat.")
        return
    if status != "ok" or entry is None or candidate is None:
        bot.answer_callback(callback_query_id, "Auswahl abgelaufen oder bereits verwendet.")
        return

    title = strip_source_suffix(candidate.title).strip() or candidate.title
    bot.answer_callback(callback_query_id, f"Ausgewählt: {title}")
    threading.Thread(
        target=_clear_telegram_choice_keyboards,
        args=(chat_id, list(entry.get("message_ids", []))),
        daemon=True,
    ).start()
    _telegram_send(chat_id, f"✅ Ausgewählt: „{title}“.")
    _run_telegram_series_request(
        chat_id,
        entry["request"],
        candidate.sample_slug,
        wait_for_lock=True,
    )


def handle_telegram_message(chat_id: str, text: str, sender_name: str = ""):
    cfg = state.telegram_cfg
    allowed_chat = str(cfg.get("chat_id", "")).strip()

    # Sicherer Einrichtungsmodus: Ohne Whitelist werden keine Downloads erlaubt,
    # der Bot verrät dem Absender lediglich dessen Chat-ID.
    if not allowed_chat:
        _telegram_send(
            chat_id,
            f"Deine Chat-ID ist {chat_id}. Trage sie in Royal Downloader → Einstellungen → Telegram ein.",
        )
        return
    if chat_id != allowed_chat:
        log(f"Telegram-Zugriff von nicht erlaubter Chat-ID {chat_id} verworfen.", "warn")
        return

    command = text.split(maxsplit=1)[0].split("@", 1)[0].casefold()
    if command in ("/start", "/help", "/hilfe"):
        _telegram_send(chat_id, _telegram_help_text())
        return
    if command == "/status":
        active = state.dl_queue.active_count()
        pending = state.dl_queue.pending_count()
        with state.telegram_jobs_lock:
            titles = sorted({job["title"] for job in state.telegram_jobs.values()})
        detail = f"\nTelegram: {', '.join(titles)}" if titles else ""
        _telegram_send(chat_id, f"⬇️ Downloader: {active} aktiv, {pending} wartend.{detail}")
        return
    if command in ("/speicher", "/storage", "/disk"):
        _telegram_send(chat_id, _telegram_storage_text())
        return
    if command == "/pfade":
        _telegram_send(chat_id, _telegram_paths_text())
        return
    if command in ("/abos", "/serien"):
        _telegram_send(chat_id, _telegram_watchlist_text())
        return
    if command == "/jellyfin":
        jf_client = get_jellyfin_client()
        if not jf_client.configured:
            _telegram_send(chat_id, "Jellyfin ist nicht konfiguriert.")
            return
        movies = jf_client.list_movies()
        episodes = jf_client.list_episodes()
        if movies is None or episodes is None:
            _telegram_send(chat_id, "⚠️ Jellyfin ist derzeit nicht erreichbar.")
            return
        _telegram_send(
            chat_id,
            f"🎞️ Jellyfin\n{len(movies)} Filme · {len(episodes)} Episoden\n{jf_client.base_url}",
        )
        return

    series_request = _parse_telegram_series_request(text)
    if series_request:
        _handle_telegram_series_request(chat_id, series_request)
        return
    if command == "/serie":
        _telegram_send(
            chat_id,
            "Format: /serie The Rookie ALLES · /serie The Rookie Staffel 8 · /serie The Rookie Staffel 8 EP 3",
        )
        return

    query = re.sub(r"^/film\s+", "", text, flags=re.IGNORECASE).strip()
    if not query or query.startswith("/"):
        _telegram_send(chat_id, "Sende einen Filmtitel oder nutze /status.")
        return

    _handle_telegram_movie_request(chat_id, query)


# ---------------------------------------------------------------------------
# Automatische Bibliotheks-Prüfung (Benachrichtigungs-Glocke)
# ---------------------------------------------------------------------------
def is_within_download_window() -> bool:
    """True, wenn die aktuelle Uhrzeit im konfigurierten Download-Zeitfenster
    liegt. Ist kein Fenster gesetzt (start/end None), gilt: jederzeit. start>end
    bedeutet über Mitternacht (z.B. 1–7 Uhr = nachts)."""
    start = state.automation.get("dl_window_start")
    end = state.automation.get("dl_window_end")
    if start is None or end is None:
        return True
    now_h = time.localtime().tm_hour   # nutzt die Container-Zeitzone (TZ)
    if start == end:
        return True
    if start < end:
        return start <= now_h < end
    return now_h >= start or now_h < end   # Fenster über Mitternacht


def _auto_download_new_episodes():
    """Lädt alle als neu erkannten Episoden abonnierter Serien automatisch
    herunter (nutzt dieselbe Pipeline wie der manuelle Download inkl.
    konfigurierter Anbieter-Fallbacks). Neue Jobs werden auch
    während eines laufenden Downloads an dieselbe 2-Slot-Queue angehängt."""
    # Trigger nicht verwerfen: Ein direkt danach abgeschlossener Abo-/JF-Check
    # kann zusätzliche Slugs geliefert haben, die der erste Snapshot nicht sah.
    state.auto_download_lock.acquire()
    claimed: List[str] = []
    try:
        if not state.automation.get("auto_download"):
            return
        if not is_within_download_window():
            log("Auto-Download: außerhalb des Zeitfensters – warte.")
            broadcast({"type": "watchlist_update", **watchlist_payload()})
            return
        with state.watchlist_lock:
            pending = sorted(
                {
                    slug
                    for entry in state.watchlist
                    if not entry.get("last_error")
                    for slug in state.watchlist_new_slugs.get(entry.get("base_slug", ""), set())
                },
                key=episode_sort_key,
            )
        if not pending:
            return

        prepared_slugs: List[str] = []
        for slug in pending:
            if not _watchlist_retry_allowed(slug):
                continue
            with state.watchlist_lock:
                if not any(
                    not entry.get("last_error")
                    and slug in state.watchlist_new_slugs.get(entry.get("base_slug", ""), set())
                    for entry in state.watchlist
                ):
                    continue
            with state.queue_lifecycle_lock:
                physically_active = any(
                    slug in _job_queue_slugs(job) for job in state.dl_queue.active_jobs()
                )
                with state.queue_claim_lock:
                    with state.download_state_lock:
                        already_owned = (
                            slug in state.picked or slug in state.counted_queue_slugs
                        )
                    if physically_active or already_owned:
                        continue
                    state.picked.add(slug)
                    claimed.append(slug)
            try:
                movie = load_movie_for_slug(slug)
            except Exception as exc:
                log(f"Auto-Download: «{slug}» nicht ladbar: {exc}", "warn")
                movie = None
            if not movie or not movie.hosters:
                movie = _episode_placeholder(slug)
                log(
                    f"Auto-Download: «{slug}» wird trotz blockierter "
                    "Episodenseite fuer Fallback/Retry eingeplant.",
                    "warn",
                )

            already_available, reason = _content_already_available(movie, slug)
            if already_available:
                with state.queue_claim_lock:
                    state.picked.discard(slug)
                claimed.remove(slug)
                with state.watchlist_lock:
                    for entry in state.watchlist:
                        base_slug = entry.get("base_slug", "")
                        pending_for_entry = state.watchlist_new_slugs.get(base_slug, set())
                        if slug not in pending_for_entry:
                            continue
                        if _is_jellyfin_safety_block(reason):
                            entry["last_error"] = f"{reason} – Auto-Download pausiert"
                            continue
                        pending_for_entry.discard(slug)
                        failures = entry.get("failed_downloads")
                        if isinstance(failures, dict):
                            failures.pop(slug, None)
                        if not pending_for_entry:
                            state.watchlist_new_slugs.pop(base_slug, None)
                log(f"Auto-Download übersprungen: «{slug}» ist {reason}.")
                continue
            state.fp_movies[slug] = movie
            prepared_slugs.append(slug)
            with state.watchlist_lock:
                for entry in state.watchlist:
                    failures = entry.get("failed_downloads")
                    if isinstance(failures, dict):
                        failures.pop(slug, None)

        if not prepared_slugs:
            with state.watchlist_lock:
                _persist_watchlist_background()
            broadcast({"type": "watchlist_update", **watchlist_payload()})
            return

        with state.watchlist_lock:
            still_pending = {
                slug
                for entry in state.watchlist
                if not entry.get("last_error")
                for slug in state.watchlist_new_slugs.get(entry.get("base_slug", ""), set())
            }
        withdrawn = set(prepared_slugs) - still_pending
        if withdrawn:
            with state.queue_claim_lock:
                state.picked.difference_update(withdrawn)
            prepared_slugs = [slug for slug in prepared_slugs if slug in still_pending]
        if not prepared_slugs:
            return

        if not _persist_new_queue_claims(prepared_slugs):
            log(
                "Auto-Download pausiert: Queue-Zustand konnte nicht gespeichert werden.",
                "warn",
            )
            return
        accepted = _enqueue_automatic_downloads(prepared_slugs, taste_source="watchlist")
        if len(accepted) != len(prepared_slugs):
            with state.queue_claim_lock:
                state.picked.difference_update(set(prepared_slugs) - accepted)
            _persist_queue_state()
        with state.watchlist_lock:
            _persist_watchlist_background()
        log(f"⬇ Auto-Download: {len(accepted)} neue Episode(n) eingereiht …")
        broadcast({"type": "watchlist_update", **watchlist_payload()})
    except Exception as exc:
        with state.download_state_lock:
            counted = set(state.counted_queue_slugs)
        with state.queue_claim_lock:
            state.picked.difference_update(slug for slug in claimed if slug not in counted)
        _persist_queue_state()
        log(f"Auto-Download konnte nicht eingeplant werden: {exc}", "err")
    finally:
        state.auto_download_lock.release()


WATCHLIST_JELLYFIN_RETRY_SECONDS = 15
WATCHLIST_QUICK_RETRY_ERRORS = (
    "Jellyfin nicht erreichbar",
    "Jellyfin-Serienindex nicht verfügbar",
    "Jellyfin-Benutzerstatus nicht verfügbar",
    "Jellyfin-Konfiguration wird geprüft",
    "Prüfung läuft",
)


def _watchlist_auto_check_once() -> tuple[int, int]:
    with state.watchlist_lock:
        entries = list(state.watchlist)
        before = {slug: set(eps) for slug, eps in state.watchlist_new_slugs.items()}
    if not entries:
        return 0, 0

    checked = check_watchlist_entries(entries, refresh_jellyfin=True)
    with state.watchlist_lock:
        found_new = any(
            state.watchlist_new_slugs.get(slug, set()) - before.get(slug, set())
            for slug in state.watchlist_new_slugs
        )
    broadcast({"type": "watchlist_update", **watchlist_payload()})
    if found_new:
        log("Neue Episode(n) in der Bibliothek verfügbar.")
    _auto_download_new_episodes()
    return checked, len(entries)


def _watchlist_auto_check_delay(checked: int, total: int, interval_min: int) -> int:
    if checked < total:
        with state.watchlist_lock:
            retry_jellyfin = any(
                any(
                    str(entry.get("last_error") or "").startswith(prefix)
                    for prefix in WATCHLIST_QUICK_RETRY_ERRORS
                )
                for entry in state.watchlist
            )
        if retry_jellyfin:
            return WATCHLIST_JELLYFIN_RETRY_SECONDS
    return max(5, int(interval_min)) * 60


def watchlist_auto_check_loop():
    """Prüft abonnierte Serien periodisch im Hintergrund auf neue Episoden,
    pusht das Ergebnis per WebSocket (Glocke) und lädt – falls Auto-Download
    aktiv ist und wir im Zeitfenster sind – die neuen Folgen direkt herunter.
    Das Intervall ist über die Automatik-Einstellungen konfigurierbar."""
    while True:
        interval_min = state.automation.get("check_interval_min", 30)
        checked = total = 0
        try:
            checked, total = _watchlist_auto_check_once()
        except Exception as exc:
            log(f"Automatische Bibliotheks-Prüfung fehlgeschlagen: {exc}", "warn")
        try:
            check_movie_subscriptions()
        except Exception as exc:
            log(f"Automatische Film-Abo-Prüfung fehlgeschlagen: {exc}", "warn")
        time.sleep(_watchlist_auto_check_delay(checked, total, interval_min))


# ---------------------------------------------------------------------------
# FastAPI-App
# ---------------------------------------------------------------------------
def start_background_services():
    """Startet Server-Hintergrunddienste genau einmal nach dem Setup."""
    global _background_services_started, _recommender_thread, _seerr_thread
    global _updater_thread, _ytdlp_updater_thread
    with _background_services_lock:
        if _background_services_started:
            return
        _background_services_started = True
    threading.Thread(target=warm_home_movie_cache, daemon=True).start()
    threading.Thread(target=warm_jellyfin_identity_cache, daemon=True).start()
    threading.Thread(target=watchlist_auto_check_loop, daemon=True).start()
    threading.Thread(target=restore_persisted_queue, daemon=True).start()
    _recommender_stop_event.clear()
    _recommender_wake_event.clear()
    _recommender_thread = threading.Thread(
        target=jellyfin_recommender_loop,
        name="jellyfin-recommender",
        daemon=True,
    )
    _recommender_thread.start()
    _seerr_stop_event.clear()
    _seerr_wake_event.clear()
    _seerr_thread = threading.Thread(
        target=seerr_poll_loop,
        name="seerr-request-bridge",
        daemon=True,
    )
    _seerr_thread.start()
    _updater_stop_event.clear()
    _updater_wake_event.clear()
    _updater_thread = threading.Thread(
        target=automatic_update_loop,
        name="automatic-updater",
        daemon=True,
    )
    _updater_thread.start()
    _ytdlp_updater_stop_event.clear()
    _ytdlp_updater_thread = threading.Thread(
        target=ytdlp_runtime_update_loop,
        name="ytdlp-runtime-updater",
        daemon=True,
    )
    _ytdlp_updater_thread.start()


async def _runtime_cache_maintenance_loop() -> None:
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(state.maintain_runtime_caches)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop, _telegram_bot
    import asyncio
    _main_loop = asyncio.get_event_loop()
    bind_host = os.environ.get("HOST", "127.0.0.1")
    # Im Fail-closed-Modus bleibt der Prozess für Erstsetup und Migration
    # erreichbar, die Middleware sperrt aber alle fachlichen APIs. So kann eine
    # Bestandsinstallation ohne Konto sicher nachgerüstet werden.
    if bind_host not in ("127.0.0.1", "localhost", "::1") and not auth_configured():
        if fail_closed_auth_enabled():
            logger.warning(
                "APP_REQUIRE_AUTH ist aktiv: Bis ein Administratorkonto "
                "eingerichtet wurde, sind nur Setup- und Liveness-Routen erreichbar."
            )
        else:
            logger.warning(
                "SICHERHEIT: Webserver ist im Netzwerk ohne Anmeldung erreichbar. "
                "Konto einrichten oder APP_REQUIRE_AUTH=true setzen."
            )
    corrections = appconfig.media_path_corrections()
    recovery_results = []
    for label, old_path, effective_path in corrections:
        logger.error(
            "Unsicherer alter %s-Pfad erkannt: %s; Wiederherstellung nach %s",
            label, old_path, effective_path,
        )
        recovery_results.append(await asyncio.to_thread(
            _recover_misplaced_media, label, old_path, effective_path,
        ))
    if corrections:
        if not await asyncio.to_thread(
            appconfig.save_media_paths, state.save_path, state.series_path,
        ):
            logger.error("Korrigierte Medienpfade konnten nicht gespeichert werden.")
        for result in recovery_results:
            logger.warning(
                "%s-Wiederherstellung: %s Datei(en) von %s nach %s kopiert; %s Fehler",
                result["label"], result["copied"], result["source"], result["target"],
                len(result["errors"]),
            )
    removed_staging = await asyncio.to_thread(
        cleanup_stale_staging, [state.save_path, state.series_path], 24 * 60 * 60,
    )
    if removed_staging:
        logger.info("%s altes Staging-Artefakt(e) entfernt.", removed_staging)
    if appconfig.is_initialized():
        start_background_services()
    _telegram_bot = TelegramBot(
        lambda: state.telegram_cfg,
        handle_telegram_message,
        log,
        callback_cb=handle_telegram_callback,
    )
    _telegram_bot.start()
    cache_maintenance_task = asyncio.create_task(_runtime_cache_maintenance_loop())
    yield
    # Ab hier dürfen Worker-Threads keine neuen WebSocket-Callbacks mehr auf
    # den auslaufenden Event-Loop einstellen.
    _main_loop = None
    _seerr_stop_event.set()
    _seerr_wake_event.set()
    _updater_stop_event.set()
    _updater_wake_event.set()
    _ytdlp_updater_stop_event.set()
    cache_maintenance_task.cancel()
    stop_jellyfin_recommender()
    if _telegram_bot is not None:
        _telegram_bot.stop()
    if state.voe_pool is not None:
        try:
            state.voe_pool.close()
        except Exception:
            pass
    if state.embed_pool is not None:
        try:
            state.embed_pool.close()
        except Exception:
            pass
    try:
        if appconfig.is_initialized():
            await asyncio.to_thread(appconfig.save, state.save_path)
    except Exception:
        pass


def _capabilities_payload():
    """Stabiler, öffentlicher Kompatibilitäts-Handshake für native Clients."""
    return {
        "name": "Royal Downloader",
        "api_version": API_VERSION,
        "supported_api_versions": [API_VERSION],
        "minimum_api_version": API_VERSION,
        "build": SERVER_BUILD or None,
        "initialized": appconfig.is_initialized(),
        "setup_required": setup_required(),
        "authentication": {
            "configured": auth_configured(),
            "required": auth_required(),
            "methods": ["bearer"],
            "legacy_methods": ["cookie", "basic"],
            "token_ttl_seconds": appauth.DEFAULT_SESSION_TTL_SECONDS,
            "token_idle_timeout_seconds": appauth.DEFAULT_SESSION_IDLE_SECONDS,
        },
        "features": {
            "movies": True,
            "series": True,
            "anime": True,
            "queue": True,
            "watchlist": True,
            "taste_profile": True,
            "jellyfin_matching": True,
            "tmdb_metadata": True,
            "cover_proxy": True,
            "websocket": True,
            "settings": True,
        },
        "websocket": {
            "path": "/api/v1/ws",
            "legacy_path": "/ws",
            "event_schema_version": EVENT_SCHEMA_VERSION,
            "initial_snapshot": True,
            "authorization_header": True,
            "authentication": ["bearer"],
        },
    }


app = FastAPI(lifespan=lifespan)
app.include_router(
    create_system_router(state.runtime_cache_diagnostics, _capabilities_payload),
)
install_authentication_middleware(
    app,
    SecurityDependencies(
        setup_required=setup_required,
        request_is_authenticated=request_is_authenticated,
        authenticated_mobile_token=authenticated_mobile_token,
        bearer_token=_bearer_token,
        session_token=_session_token,
        client_key=client_key,
        request_is_secure=lambda request: _request_is_secure(request),
        public_translate_limiter=PUBLIC_TRANSLATE_LIMITER,
    ),
)


@app.exception_handler(Exception)
async def handle_exc(request, exc):
    log(f"Serverfehler: {exc}", "err")
    return JSONResponse(status_code=500, content={"error": "Interner Serverfehler."})


@app.exception_handler(appauth.SessionPersistenceError)
async def handle_session_persistence_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Die Sitzungsverwaltung ist vorübergehend nicht verfügbar.",
            "code": "session_store_unavailable",
        },
        headers={"Retry-After": "30", "Cache-Control": "no-store"},
    )


# ── Anmeldung ───────────────────────────────────────────────────────────────
def _request_is_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return forwarded == "https" or request.url.scheme == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        appauth.SESSION_COOKIE_NAME,
        token,
        max_age=appauth.DEFAULT_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        # Hinter einem HTTPS-Reverse-Proxy wird das Cookie auf `Secure`
        # gesetzt; im reinen LAN-Betrieb über http würde das Flag verhindern,
        # dass der Browser das Cookie überhaupt speichert.
        secure=_request_is_secure(request),
        path="/",
    )


app.include_router(create_auth_router(AuthDependencies(
    api_version=API_VERSION,
    appauth=appauth,
    appconfig=appconfig,
    login_guard=lambda: LOGIN_GUARD,
    session_store=lambda: SESSION_STORE,
    client_key=lambda request: client_key(request),
    auth_account=lambda: auth_account(),
    auth_required=lambda: auth_required(),
    auth_configured=lambda: auth_configured(),
    setup_required=lambda: setup_required(),
    request_is_authenticated=lambda *args, **kwargs: request_is_authenticated(
        *args, **kwargs,
    ),
    request_auth_method=lambda *args, **kwargs: request_auth_method(
        *args, **kwargs,
    ),
    verify_credentials=lambda username, password: verify_credentials(
        username, password,
    ),
    authenticated_web_token=lambda cookies: authenticated_web_token(cookies),
    authenticated_mobile_token=lambda *args, **kwargs: authenticated_mobile_token(
        *args, **kwargs,
    ),
    bearer_token=lambda headers: _bearer_token(headers),
    session_token=lambda cookies: _session_token(cookies),
    request_is_secure=lambda request: _request_is_secure(request),
    log=lambda *args, **kwargs: log(*args, **kwargs),
)))


discovery_router = create_discovery_router(sys.modules[__name__])
register_domain_router("discovery", discovery_router)
app.router.routes.extend(discovery_router.routes)


queue_router = create_queue_router(sys.modules[__name__])
register_domain_router("queue", queue_router)
app.router.routes.extend(queue_router.routes)


administration_router = create_administration_router(sys.modules[__name__])
register_domain_router("administration", administration_router)
app.router.routes.extend(administration_router.routes)
app.include_router(create_setup_router(SetupDependencies(
    status_payload=lambda: _setup_status_payload(),
    completion_lock=lambda: state.setup_completion_lock,
    complete=lambda body, request: _api_setup_complete_locked(body, request),
)))


library_router = create_library_router(sys.modules[__name__])
register_domain_router("library", library_router)
app.router.routes.extend(library_router.routes)


(
    websocket_router,
    websocket_snapshot_payload,
    _websocket_is_authenticated,
) = create_websocket_router(WebSocketDependencies(
    api_version=API_VERSION,
    event_schema_version=EVENT_SCHEMA_VERSION,
    auth_recheck_seconds=WEBSOCKET_AUTH_RECHECK_SECONDS,
    state=state,
    manager=ws_manager,
    build_queue_payload=lambda: build_queue_payload(),
    watchlist_payload=lambda: watchlist_payload(),
    auth_required=lambda: auth_required(),
    authenticated_mobile_token=lambda *args, **kwargs: authenticated_mobile_token(
        *args, **kwargs,
    ),
    authenticated_web_token=lambda *args, **kwargs: authenticated_web_token(
        *args, **kwargs,
    ),
))
register_domain_router("live_updates", websocket_router)
app.router.routes.extend(websocket_router.routes)


# Statische Web-Oberfläche (muss NACH allen /api- und /ws-Routen gemountet
# werden, sonst würde der Catch-all-Mount sie verdecken).
install_domain_routers(app)


class NoCacheStaticFiles(StaticFiles):
    """Liefert die Oberfläche mit `Cache-Control: no-cache` aus. Grund: die
    Dateien (index.html/app.js/style.css) werden bei Updates einfach im
    gemounteten Ordner überschrieben. Ohne no-cache serviert der Browser die
    ALTE app.js aus dem Cache (Button da, aber Handler fehlt) → „Einstellungen
    öffnen sich nicht". `no-cache` erzwingt eine Revalidierung (per ETag/
    Last-Modified → 304 wenn unverändert), sodass Updates sofort greifen."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app.mount("/", NoCacheStaticFiles(directory=str(WEB_DIR), html=True), name="web")


def _open_browser(port: int):
    time.sleep(1.0)
    webbrowser.open(f"http://127.0.0.1:{port}")


if __name__ == "__main__":
    import os
    import uvicorn
    # Env-gesteuert, damit dieselbe Datei lokal (Windows: Browser öffnet sich,
    # nur lokal erreichbar) UND im Docker-Container (kein Browser, im Netzwerk
    # erreichbar) läuft.
    PORT = int(os.environ.get("PORT", "8765"))
    HOST = os.environ.get("HOST", "127.0.0.1")
    open_browser = os.environ.get("OPEN_BROWSER", "1").lower() not in ("0", "false", "no")
    if open_browser:
        threading.Thread(target=_open_browser, args=(PORT,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
