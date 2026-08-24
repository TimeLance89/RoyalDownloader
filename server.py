# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821
"""
Royal Downloader – lokaler Webserver.

Ersetzt die frühere customtkinter-GUI (main.py) durch eine HTML/CSS/JS-
Oberfläche, die im Standardbrowser läuft. Anbieteradapter liegen gebündelt im
Paket ``providers``; dieser Server bildet die REST-/WebSocket-Schicht darüber.

Start: python server.py  (öffnet automatisch den Browser)
"""

from environment_file import load_project_env

load_project_env()

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
from queue_jobs import HISTORY_LIMIT, new_job
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
from series_calendar_service import get_series_calendar_service
from network_guard import is_public_http_url
from providers.filmfrei24 import (
    BASE_URL as FILMFREI24_BASE_URL,
    FilmFrei24Scraper,
    SOURCE_PREFIX as FILMFREI24_PREFIX,
)
from providers.filmo import FilmoScraper, SOURCE_PREFIX as FILMO_PREFIX
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
from providers.aniworld import (
    AniWorldScraper,
    SOURCE_PREFIX as ANIWORLD_PREFIX,
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
from app_version import APP_VERSION
from update_channels import UPDATE_CHANNEL_BRANCHES

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
    branch=appconfig.load_updater()["update_branch"],
    app_dir=APP_DIR,
)
UI_TRANSLATOR = UITranslator()
PROVIDER_LABELS = {
    key: definition.label
    for key, definition in PROVIDER_CATALOG.items()
}
MOVIE_BROWSE_PAGE_SIZE = 32
MOVIE_PAGINATED_PROVIDERS = frozenset({
    "filmpalast", "filmo", "megakino", "kinoger", "xcine", "sflix", "ridomovies",
})
MOVIE_LIST_CACHE_TTL = 300
# Abgelaufene Providerlisten bleiben als sofortige Anzeige nutzbar, waehrend
# dieselbe Quellseite im Hintergrund aktualisiert wird. Das verhindert, dass
# alle fuenf Minuten wieder der langsamste Anbieter den gesamten Katalog
# blockiert.
MOVIE_LIST_STALE_TTL = 6 * 60 * 60
MOVIE_LIST_FAILURE_CACHE_TTL = 30
MOVIE_LIST_CACHE_MAX_ENTRIES = 1000
MOVIE_MAX_GLOBAL_PAGE = 50
MOVIE_MAX_SOURCE_PAGE = 50
MOVIE_MAX_COLD_WAVES_PER_REQUEST = 2
TMDB_MOVIE_BATCH_MAX_WORKERS = 8
TMDB_MOVIE_SEARCH_MAX_RESULTS = 40
MOVIE_GENRE_GROUPS = {
    "Abenteuer": ("Abenteuer", "Adventure"),
    "Animation": ("Animation", "Zeichentrick"),
    "Biografie": ("Biografie", "Biographie", "Biography"),
    "Dokumentation": ("Dokumentation", "Dokumentarfilm", "Documentary"),
    "Familie": ("Familie", "Family"),
    "Geschichte": ("Geschichte", "Historie"),
    "Komödie": ("Komödie", "Comedy"),
    "Krimi": ("Krimi", "Crime"),
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
SERIES_LIST_STALE_TTL = 6 * 60 * 60
SERIES_LIST_FAILURE_CACHE_TTL = 30
SERIES_LIST_CACHE_MAX_ENTRIES = 500
SERIES_MAX_GLOBAL_PAGE = 50
SERIES_MAX_SOURCE_PAGE = 50
SERIES_MAX_COLD_WAVES_PER_REQUEST = 2
SERIES_CATALOG_PAGE_BUDGET_SECONDS = 12.0


from application_services.runtime import register_backend, refresh_services
register_backend(sys.modules[__name__])
from application_services import auth as _auth_service

# ---------------------------------------------------------------------------
# App-State (Ein-Nutzer, in-memory – entspricht den Instanzvariablen der
# früheren tkinter-App-Klasse)
# ---------------------------------------------------------------------------
state = AppState()


from application_services import updater as _updater_service

from application_services import media_clients as _media_clients_service

from application_services import movie_catalog as _movie_catalog_service

from application_services import series_catalog as _series_catalog_service

from application_services import persistence as _persistence_service

from application_services import download_lifecycle as _download_lifecycle_service

from application_services import source_resolution as _source_resolution_service

from application_services import download_queue as _download_queue_service

from application_services import telegram_requests as _telegram_requests_service

from application_services import seerr as _seerr_service

from application_services import telegram_commands as _telegram_commands_service

from application_services import automation as _automation_service

refresh_services()

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
    threading.Thread(target=warm_home_series_cache, daemon=True).start()
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
    # Der Kalender aktualisiert sich unabhängig von Katalog-, Download- und
    # Browser-Sessions. Ein persistierter Stand ist sofort verfügbar.
    get_series_calendar_service().refresh_async()
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
        "application_version": APP_VERSION,
        "update_channels": dict(UPDATE_CHANNEL_BRANCHES),
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
            "aniworld": True,
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
