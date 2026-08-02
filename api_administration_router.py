"""Runtime configuration, updater, setup transaction, and integration settings."""

# External configuration probes are translated at this boundary.

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import auth as appauth
import config as appconfig
from api_setup_router import SetupCompleteBody
from jellyfin_client import JellyfinClient
from media_paths import prepare_media_directory, recover_misplaced_media
from providers.catalog import (
    provider_catalog_payload,
    provider_content_language,
    provider_language_payload,
)
from seerr_client import SeerrClient
from tmdb_client import TMDBClient
from ui_translator import (
    SUPPORTED_UI_LANGUAGES,
    normalize_ui_language,
)
from watchlist_policy import CLEANUP_MODE_LABELS, normalize_cleanup_mode

router = APIRouter(tags=["administration"])


def _unbound_dependency(*_args, **_kwargs):
    raise RuntimeError("Administration router dependencies are not configured")


class _DynamicObject:
    def __init__(self, backend, name: str):
        self._backend = backend
        self._name = name

    def __getattr__(self, attribute):
        return getattr(getattr(self._backend, self._name), attribute)


state: Any = None
PROVIDER_LABELS: dict = {}
PUBLIC_TRANSLATE_WORK_LIMITER: Any = None
SESSION_STORE: Any = None
UI_TRANSLATOR: Any = None
UPDATE_CHECKER: Any = None
UPDATE_INSTALLER: Any = None
_recommender_wake_event: Any = None
_seerr_wake_event: Any = None
_updater_wake_event: Any = None
_auto_download_new_episodes = _unbound_dependency
_cookie_file_for = _unbound_dependency
_execute_provider_probe = _unbound_dependency
_set_runtime_jellyfin_config = _unbound_dependency
_set_session_cookie = _unbound_dependency
_set_updater_runtime = _unbound_dependency
_start_update_when_idle = _unbound_dependency
_updater_config_payload = _unbound_dependency
auth_configured = _unbound_dependency
broadcast = _unbound_dependency
check_movie_subscriptions = _unbound_dependency
check_watchlist_entries = _unbound_dependency
client_key = _unbound_dependency
configure_moonfin_seerr = _unbound_dependency
in_container = _unbound_dependency
is_within_download_window = _unbound_dependency
log = _unbound_dependency
persistent_container_path = _unbound_dependency
provider_order = _unbound_dependency
request_is_authenticated = _unbound_dependency
seerr_poll_once = _unbound_dependency
serienstream_provider_status = _unbound_dependency
setup_required = _unbound_dependency
start_background_services = _unbound_dependency
watchlist_payload = _unbound_dependency

_DYNAMIC_CALLS = (
    "_auto_download_new_episodes",
    "_cookie_file_for",
    "_execute_provider_probe",
    "_set_runtime_jellyfin_config",
    "_set_session_cookie",
    "_set_updater_runtime",
    "_start_update_when_idle",
    "_updater_config_payload",
    "auth_configured",
    "broadcast",
    "check_movie_subscriptions",
    "check_watchlist_entries",
    "client_key",
    "configure_moonfin_seerr",
    "in_container",
    "is_within_download_window",
    "log",
    "persistent_container_path",
    "provider_order",
    "request_is_authenticated",
    "seerr_poll_once",
    "serienstream_provider_status",
    "setup_required",
    "start_background_services",
    "watchlist_payload",
)


def create_administration_router(backend) -> APIRouter:
    """Bind configuration services and return the administration router."""

    def dynamic(name):
        return lambda *args, **kwargs: getattr(backend, name)(*args, **kwargs)

    globals().update({name: dynamic(name) for name in _DYNAMIC_CALLS})
    globals().update({
        "state": backend.state,
        "PROVIDER_LABELS": backend.PROVIDER_LABELS,
        "PUBLIC_TRANSLATE_WORK_LIMITER": _DynamicObject(
            backend, "PUBLIC_TRANSLATE_WORK_LIMITER",
        ),
        "SESSION_STORE": _DynamicObject(backend, "SESSION_STORE"),
        "UI_TRANSLATOR": _DynamicObject(backend, "UI_TRANSLATOR"),
        "UPDATE_CHECKER": _DynamicObject(backend, "UPDATE_CHECKER"),
        "UPDATE_INSTALLER": _DynamicObject(backend, "UPDATE_INSTALLER"),
        "_recommender_wake_event": _DynamicObject(
            backend, "_recommender_wake_event",
        ),
        "_seerr_wake_event": _DynamicObject(backend, "_seerr_wake_event"),
        "_updater_wake_event": _DynamicObject(backend, "_updater_wake_event"),
    })
    return router


# ── Einstellungen ────────────────────────────────────────────────────────────


@router.get("/api/v1/updater/status")
@router.get("/api/updater/status")
async def api_updater_status(force: bool = False):
    payload = await run_in_threadpool(UPDATE_CHECKER.check, force)
    payload["installer"] = UPDATE_INSTALLER.status()
    payload["config"] = _updater_config_payload()
    return payload


class UpdateInstallBody(BaseModel):
    target_sha: str


@router.post("/api/v1/updater/install")
@router.post("/api/updater/install")
async def api_updater_install(body: UpdateInstallBody):
    update = await run_in_threadpool(UPDATE_CHECKER.check, True)
    target_sha = str(update.get("latest_sha") or "")
    if not target_sha or target_sha != body.target_sha.strip():
        raise HTTPException(409, "Der angebotene GitHub-Stand hat sich geändert; bitte erneut prüfen.")
    if update.get("update_available") is not True:
        raise HTTPException(409, "Für diesen Build ist kein installierbares Update verfügbar.")
    try:
        installer = _start_update_when_idle(target_sha)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"installer": installer}


@router.get("/api/v1/updater/install/status")
@router.get("/api/updater/install/status")
async def api_updater_install_status():
    return {"installer": UPDATE_INSTALLER.status()}


@router.post("/api/v1/updater/rollback")
@router.post("/api/updater/rollback")
async def api_updater_rollback():
    with state.queue_lifecycle_lock:
        if state.ytdlp_update_active:
            raise HTTPException(409, "yt-dlp wird gerade aktualisiert")
        try:
            installer = UPDATE_INSTALLER.rollback()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
    return {"installer": installer}


class UpdaterConfigBody(BaseModel):
    update_mode: str = appconfig.UPDATE_MODE_MANUAL
    auto_update_interval_hours: int = 6


@router.get("/api/v1/updater/config")
@router.get("/api/updater/config")
async def api_updater_config_get():
    return _updater_config_payload()


@router.post("/api/v1/updater/config")
@router.post("/api/updater/config")
async def api_updater_config_set(body: UpdaterConfigBody):
    mode = str(body.update_mode or "").strip().lower()
    if mode not in appconfig.UPDATE_MODES:
        raise HTTPException(400, "Update-Modus muss 'manual' oder 'automatic' sein.")
    interval = max(1, min(168, int(body.auto_update_interval_hours or 6)))
    if not await run_in_threadpool(appconfig.save_updater, mode, interval):
        raise HTTPException(500, "Update-Einstellungen konnten nicht gespeichert werden.")
    updater_cfg = await run_in_threadpool(appconfig.load_updater)
    with state.updater_config_lock:
        state.updater_cfg = updater_cfg
    if mode == appconfig.UPDATE_MODE_AUTOMATIC:
        _set_updater_runtime("scheduled", "Automatische Updateprüfung wird gestartet.")
    else:
        _set_updater_runtime("manual", "Updates werden nur manuell installiert.")
    _updater_wake_event.set()
    return {**_updater_config_payload(), "saved": True}


def _prepare_media_directory(raw_path: str, label: str) -> dict:
    return prepare_media_directory(
        raw_path,
        label,
        in_container_check=in_container,
        persistent_path_check=persistent_container_path,
    )


def _recover_misplaced_media(label: str, old_path: str, effective_path: str) -> dict:
    return recover_misplaced_media(
        label,
        old_path,
        effective_path,
        persistent_path_check=persistent_container_path,
    )


def _setup_status_payload() -> dict:
    return {
        "required": setup_required(),
        "config_path": str(appconfig.config_path()),
        "defaults": {
            "save_path": state.save_path,
            "series_path": state.series_path,
            "ui_language": state.ui_language,
            "ui_language_configured": appconfig.ui_language_configured(),
            "providers": _provider_priority_payload(),
            "jellyfin": {
                "url": state.jellyfin_cfg.get("url", ""),
                "api_key": "",
                "has_api_key": bool(state.jellyfin_cfg.get("api_key")),
                "user_id": state.jellyfin_cfg.get("user_id", ""),
                "user_name": state.jellyfin_cfg.get("user_name", ""),
                "cleanup_default": normalize_cleanup_mode(
                    state.jellyfin_cfg.get("cleanup_default")
                ),
            },
            "tmdb": {
                "api_key": "",
                "has_api_key": bool(state.tmdb_cfg.get("api_key")),
                "language": state.tmdb_cfg.get("language", "de-DE"),
            },
            "telegram": {
                "enabled": bool(state.telegram_cfg.get("enabled")),
                "bot_token": "",
                "has_bot_token": bool(state.telegram_cfg.get("bot_token")),
                "chat_id": state.telegram_cfg.get("chat_id", ""),
            },
            "automation": state.automation,
        },
    }



async def _api_setup_complete_locked(body: SetupCompleteBody, request: Request):
    # Bestehende Installation: der Assistent darf ein vorhandenes Konto nicht
    # überschreiben, nur ein Angemeldeter darf hier überhaupt landen.
    already_initialized = appconfig.is_initialized()
    account_was_configured = auth_configured()
    if already_initialized and account_was_configured and not request_is_authenticated(
        request.headers, request.cookies, client_key(request),
    ):
        raise HTTPException(401, "Anmeldung erforderlich.")
    account_hash = ""
    account_user = ""
    if not account_was_configured:
        # Neuinstallation: ohne Konto wird nicht abgeschlossen.
        try:
            account_user = appauth.validate_username(body.auth_username)
            account_password = appauth.validate_password(body.auth_password)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        account_hash = await run_in_threadpool(appauth.hash_password, account_password)
    movie_path = body.save_path.strip()
    series_path = body.series_path.strip() or movie_path
    jellyfin_url = body.jellyfin_url.strip()
    with state.jellyfin_cache_lock:
        previous_jellyfin = dict(state.jellyfin_cfg)
    same_jellyfin = (
        jellyfin_url.rstrip("/")
        and jellyfin_url.rstrip("/") == previous_jellyfin.get("url", "").rstrip("/")
    )
    jellyfin_api_key = body.jellyfin_api_key.strip() or (
        previous_jellyfin.get("api_key", "") if same_jellyfin else ""
    )
    jellyfin_user_id = body.jellyfin_user_id.strip()
    jellyfin_user_name = body.jellyfin_user_name.strip()
    movie_order = (
        [str(value).strip().casefold() for value in body.movie_provider_order]
        if body.movie_provider_order is not None
        else provider_order("movies")
    )
    series_order = (
        [str(value).strip().casefold() for value in body.series_provider_order]
        if body.series_provider_order is not None
        else provider_order("series")
    )
    anime_order = (
        [str(value).strip().casefold() for value in body.anime_provider_order]
        if body.anime_provider_order is not None
        else provider_order("anime")
    )
    movie_providers = (
        [str(value).strip().casefold() for value in body.movie_providers]
        if body.movie_providers is not None
        else list(state.provider_enabled.get("movies", appconfig.MOVIE_PROVIDER_DEFAULTS))
    )
    series_providers = (
        [str(value).strip().casefold() for value in body.series_providers]
        if body.series_providers is not None
        else list(state.provider_enabled.get("series", appconfig.SERIES_PROVIDER_DEFAULTS))
    )
    anime_providers = (
        [str(value).strip().casefold() for value in body.anime_providers]
        if body.anime_providers is not None
        else list(state.provider_enabled.get("anime", appconfig.ANIME_PROVIDER_DEFAULTS))
    )
    content_languages = (
        appconfig.normalize_content_languages(body.content_languages)
        if body.content_languages is not None
        else list(state.content_languages)
    )
    if not movie_path:
        raise HTTPException(400, "Ein Speicherordner für Filme fehlt.")
    if (
        len(movie_order) != len(set(movie_order))
        or set(movie_order) != set(appconfig.MOVIE_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Die Reihenfolge der Filmquellen ist ungültig.")
    if (
        len(series_order) != len(set(series_order))
        or set(series_order) != set(appconfig.SERIES_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Die Reihenfolge der Serienquellen ist ungültig.")
    if (
        len(anime_order) != len(set(anime_order))
        or set(anime_order) != set(appconfig.ANIME_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Die Reihenfolge der Anime-Quellen ist ungültig.")
    if (
        not movie_providers
        or len(movie_providers) != len(set(movie_providers))
        or not set(movie_providers).issubset(appconfig.MOVIE_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Mindestens eine gültige Filmquelle muss aktiv sein.")
    if (
        not series_providers
        or len(series_providers) != len(set(series_providers))
        or not set(series_providers).issubset(appconfig.SERIES_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Mindestens eine gültige Serienquelle muss aktiv sein.")
    if (
        len(anime_providers) != len(set(anime_providers))
        or not set(anime_providers).issubset(appconfig.ANIME_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Die Auswahl der Anime-Quellen ist ungültig.")
    if not content_languages:
        raise HTTPException(400, "Mindestens eine Inhaltssprache muss aktiv sein.")
    if any(
        provider_content_language(provider) not in content_languages
        for provider in movie_providers + series_providers + anime_providers
    ):
        raise HTTPException(400, "Aktive Quellen und Inhaltssprachen passen nicht zusammen.")
    if jellyfin_url and not jellyfin_api_key:
        raise HTTPException(400, "Für Jellyfin fehlt der API-Schlüssel.")
    if jellyfin_url:
        users = await run_in_threadpool(JellyfinClient(jellyfin_url, jellyfin_api_key).list_users)
        if users is None:
            raise HTTPException(502, "Jellyfin ist nicht erreichbar; Einstellungen wurden nicht gespeichert.")
        if jellyfin_user_id:
            selected = next((user for user in users if user["id"] == jellyfin_user_id), None)
            if selected is None:
                raise HTTPException(400, "Der gewählte Jellyfin-Benutzer ist nicht verfügbar.")
            jellyfin_user_name = selected["name"]
    if body.telegram_enabled and not (body.telegram_bot_token.strip() or state.telegram_cfg.get("bot_token", "")):
        raise HTTPException(400, "Für Telegram fehlt der Bot-Token.")
    for value, label in ((movie_path, "Filmordner"), (series_path, "Serienordner")):
        await run_in_threadpool(_prepare_media_directory, value, label)

    # Auch wenn alle Vorprüfungen lange gedauert haben, darf direkt vor dem
    # atomaren Konfigurations-Commit kein anderer Abschluss gewonnen haben.
    # Der Prozess-Lock wird über Prüfung, Commit und Sitzungserzeugung gehalten.
    if (
        (not already_initialized and appconfig.is_initialized())
        or (not account_was_configured and auth_configured())
    ):
        raise HTTPException(
            409,
            detail={
                "code": "setup_already_completed",
                "message": "Die Ersteinrichtung wurde bereits abgeschlossen.",
            },
        )

    ok = await run_in_threadpool(
        appconfig.save_initial_setup,
        movie_path,
        series_path,
        jellyfin_url,
        jellyfin_api_key,
        jellyfin_user_id,
        jellyfin_user_name,
        body.tmdb_api_key or state.tmdb_cfg.get("api_key", ""),
        body.telegram_enabled,
        body.telegram_bot_token or state.telegram_cfg.get("bot_token", ""),
        body.telegram_chat_id,
        body.auto_download,
        body.check_interval_min,
        body.dl_window_start,
        body.dl_window_end,
        body.ui_language,
        movie_order,
        series_order,
        movie_providers,
        series_providers,
        content_languages,
        anime_order,
        anime_providers,
        account_user,
        account_hash,
    )
    if not ok:
        raise HTTPException(500, f"Einstellungen konnten nicht unter {appconfig.config_path()} gespeichert werden.")

    def _load_setup_runtime():
        return {
            "save_path": appconfig.load(),
            "series_path": appconfig.load_series_path(),
            "ui_language": appconfig.load_ui_language(),
            "priorities": appconfig.load_provider_priorities(),
            "enabled": appconfig.load_provider_enabled(),
            "languages": appconfig.load_content_languages(),
            "jellyfin": appconfig.load_jellyfin(),
            "tmdb": appconfig.load_tmdb(),
            "telegram": appconfig.load_telegram(),
            "automation": appconfig.load_automation(),
        }

    runtime = await run_in_threadpool(_load_setup_runtime)
    state.save_path = runtime["save_path"]
    state.series_path = runtime["series_path"]
    with state.ui_language_lock:
        state.ui_language = runtime["ui_language"]
    with state.provider_priority_lock:
        state.provider_priorities = runtime["priorities"]
        state.provider_enabled = runtime["enabled"]
        state.content_languages = set(runtime["languages"])
    _set_runtime_jellyfin_config(runtime["jellyfin"])
    state.tmdb_cfg = runtime["tmdb"]
    state.tmdb_client = TMDBClient(**state.tmdb_cfg)
    state.telegram_cfg = runtime["telegram"]
    state.automation = runtime["automation"]
    start_background_services()
    payload = {
        "saved": True,
        "required": False,
        "config_path": str(appconfig.config_path()),
        "save_path": state.save_path,
        "series_path": state.series_path,
        "ui_language": state.ui_language,
        "auth_configured": auth_configured(),
    }
    if not account_hash:
        return payload
    # Ab jetzt greift die Anmeldepflicht. Der Browser, der gerade die
    # Einrichtung abgeschlossen hat, bekommt direkt eine Sitzung – sonst
    # stünde der Nutzer unmittelbar nach dem Abschluss vor der Anmeldemaske.
    response = JSONResponse(payload)
    _set_session_cookie(
        response,
        request,
        SESSION_STORE.create(
            label=request.headers.get("user-agent", "")[:120],
            kind=appauth.SESSION_KIND_WEB,
        ),
    )
    return response


class UILanguageBody(BaseModel):
    language: str = "de"


class UITranslationBody(BaseModel):
    target_language: str
    texts: list[str] = Field(max_length=120)


def _ui_language_payload(saved: bool = False) -> dict:
    with state.ui_language_lock:
        language = state.ui_language
    return {
        "language": language,
        "configured": appconfig.ui_language_configured(),
        "languages": SUPPORTED_UI_LANGUAGES,
        "translator": {
            "browser_preferred": True,
            "fallback_engine": UI_TRANSLATOR.engine,
        },
        "saved": saved,
    }


@router.get("/api/v1/ui/config")
@router.get("/api/ui/config")
async def api_ui_config_get():
    return _ui_language_payload()


@router.post("/api/v1/ui/config")
@router.post("/api/ui/config")
async def api_ui_config_set(body: UILanguageBody):
    language = normalize_ui_language(body.language)
    if not await run_in_threadpool(appconfig.save_ui_language, language):
        raise HTTPException(500, "Die Sprache konnte nicht gespeichert werden.")
    with state.ui_language_lock:
        state.ui_language = language
    tmdb_language = appconfig.tmdb_language_for_ui(language)
    state.tmdb_cfg = {
        **state.tmdb_cfg,
        "language": tmdb_language,
    }
    state.tmdb_client = TMDBClient(**state.tmdb_cfg)
    with state.movie_source_cache_lock:
        state.movie_source_cache.clear()
        for slug in [
            cached_slug for cached_slug in state.fp_movies
            if cached_slug.startswith("tmdb:")
        ]:
            state.fp_movies.pop(slug, None)
    return _ui_language_payload(saved=True)


@router.post("/api/ui/translate")
async def api_ui_translate(body: UITranslationBody, request: Request):
    target = normalize_ui_language(body.target_language)
    texts = [str(value or "") for value in body.texts]
    requested = str(body.target_language or "").strip().replace("_", "-").casefold()
    if target != requested.split("-", 1)[0]:
        raise HTTPException(400, "Nicht unterstützte Zielsprache.")
    if any(len(text) > 600 for text in texts) or sum(map(len, texts)) > 30_000:
        raise HTTPException(413, "Die Übersetzungsanfrage ist zu groß.")
    if not request_is_authenticated(
        request.headers,
        request.cookies,
        client_key(request),
        touch=False,
    ):
        work_units = max(1, len({text for text in texts if text.strip()}))
        if not PUBLIC_TRANSLATE_WORK_LIMITER.allow(
            client_key(request),
            cost=work_units,
        ):
            raise HTTPException(
                429,
                "Übersetzungsbudget ausgeschöpft. Bitte kurz warten.",
                headers={"Retry-After": "60"},
            )
    translated = await run_in_threadpool(
        UI_TRANSLATOR.translate_many,
        texts,
        target,
    )
    return {
        "source_language": "de",
        "target_language": target,
        "translations": translated,
        "engine": UI_TRANSLATOR.engine,
    }


class ConfigBody(BaseModel):
    save_path: str
    series_path: str | None = None


@router.get("/api/v1/config")
@router.get("/api/config")
async def api_config_get():
    return {"save_path": state.save_path, "series_path": state.series_path}


@router.post("/api/v1/config")
@router.post("/api/config")
async def api_config_set(body: ConfigBody):
    movie_path = body.save_path.strip()
    series = (body.series_path or "").strip() or movie_path
    if not movie_path:
        raise HTTPException(400, "Ein Speicherordner für Filme fehlt.")
    await run_in_threadpool(_prepare_media_directory, movie_path, "Filmordner")
    await run_in_threadpool(_prepare_media_directory, series, "Serienordner")
    def _save_paths():
        ok = appconfig.save(movie_path)
        # Serien-Pfad optional: leer/None -> gleicher Ordner wie Filme (Fallback).
        ok_series = appconfig.save_series_path(series)
        return ok, ok_series, appconfig.load_series_path()

    ok, ok_series, saved_series_path = await run_in_threadpool(_save_paths)
    if not (ok and ok_series):
        raise HTTPException(500, "Speicherorte konnten nicht gespeichert werden.")
    state.save_path = movie_path
    state.series_path = saved_series_path
    return {"save_path": state.save_path, "series_path": state.series_path, "saved": True}


class ProviderPriorityBody(BaseModel):
    movies: list[str]
    series: list[str]
    anime: list[str] | None = None
    enabled_movies: list[str] | None = None
    enabled_series: list[str] | None = None
    enabled_anime: list[str] | None = None
    content_languages: list[str] | None = None


def _provider_priority_payload(saved: bool = False) -> dict:
    movie_order = provider_order("movies")
    series_order = provider_order("series")
    anime_order = provider_order("anime")
    with state.provider_priority_lock:
        enabled_movie_ids = set(state.provider_enabled.get(
            "movies", appconfig.MOVIE_PROVIDER_DEFAULTS,
        ))
        enabled_series_ids = set(state.provider_enabled.get(
            "series", appconfig.SERIES_PROVIDER_DEFAULTS,
        ))
        enabled_anime_ids = set(state.provider_enabled.get(
            "anime", appconfig.ANIME_PROVIDER_DEFAULTS,
        ))
        content_languages = set(state.content_languages)
    return {
        "movies": movie_order,
        "series": series_order,
        "anime": anime_order,
        "enabled_movies": [
            provider for provider in movie_order if provider in enabled_movie_ids
        ],
        "enabled_series": [
            provider for provider in series_order if provider in enabled_series_ids
        ],
        "enabled_anime": [
            provider for provider in anime_order if provider in enabled_anime_ids
        ],
        "labels": PROVIDER_LABELS,
        "catalog": provider_catalog_payload(),
        "content_languages": [
            language
            for language in appconfig.CONTENT_LANGUAGE_DEFAULTS
            if language in content_languages
        ],
        "languages": provider_language_payload(),
        "saved": saved,
    }


@router.get("/api/v1/providers/status")
@router.get("/api/providers/status")
async def api_provider_status_get():
    return {"providers": {"serienstream": serienstream_provider_status()}}


@router.post("/api/v1/providers/serienstream/retry")
@router.post("/api/providers/serienstream/retry")
async def api_serienstream_retry():
    if not state.provider_health.begin_probe("serienstream", force=True):
        raise HTTPException(409, "Eine SerienStream-Probe läuft bereits.")
    with state.queue_claim_lock:
        item = next(iter(state.provider_waiting_jobs.values()), None)
    threading.Thread(
        target=_execute_provider_probe,
        args=(item,),
        name="serienstream-manual-probe",
        daemon=True,
    ).start()
    state.provider_retry_wake_event.set()
    return {
        "started": True,
        "provider": serienstream_provider_status(),
    }


@router.get("/api/v1/providers/config")
@router.get("/api/providers/config")
async def api_provider_priority_get():
    return _provider_priority_payload()


@router.post("/api/v1/providers/config")
@router.post("/api/providers/config")
async def api_provider_priority_set(body: ProviderPriorityBody):
    movie_ids = [str(value).strip().casefold() for value in body.movies]
    series_ids = [str(value).strip().casefold() for value in body.series]
    anime_ids = (
        [str(value).strip().casefold() for value in body.anime]
        if body.anime is not None
        else provider_order("anime")
    )
    if len(movie_ids) != len(set(movie_ids)) or set(movie_ids) != set(appconfig.MOVIE_PROVIDER_DEFAULTS):
        raise HTTPException(400, "Die Film-Anbieterliste ist unvollständig oder ungültig.")
    if len(series_ids) != len(set(series_ids)) or set(series_ids) != set(appconfig.SERIES_PROVIDER_DEFAULTS):
        raise HTTPException(400, "Die Serien-Anbieterliste ist unvollständig oder ungültig.")
    if len(anime_ids) != len(set(anime_ids)) or set(anime_ids) != set(appconfig.ANIME_PROVIDER_DEFAULTS):
        raise HTTPException(400, "Die Anime-Anbieterliste ist unvollständig oder ungültig.")
    current_enabled = await run_in_threadpool(appconfig.load_provider_enabled)
    enabled_movies = [
        str(value).strip().casefold()
        for value in (
            body.enabled_movies
            if body.enabled_movies is not None
            else current_enabled["movies"]
        )
    ]
    enabled_series = [
        str(value).strip().casefold()
        for value in (
            body.enabled_series
            if body.enabled_series is not None
            else current_enabled["series"]
        )
    ]
    enabled_anime = [
        str(value).strip().casefold()
        for value in (
            body.enabled_anime
            if body.enabled_anime is not None
            else current_enabled["anime"]
        )
    ]
    if body.content_languages is not None:
        content_languages = appconfig.normalize_content_languages(body.content_languages)
    else:
        content_languages = await run_in_threadpool(appconfig.load_content_languages)
    if (
        not enabled_movies
        or len(enabled_movies) != len(set(enabled_movies))
        or not set(enabled_movies).issubset(appconfig.MOVIE_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Mindestens eine gültige Filmquelle muss aktiv sein.")
    if (
        not enabled_series
        or len(enabled_series) != len(set(enabled_series))
        or not set(enabled_series).issubset(appconfig.SERIES_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Mindestens eine gültige Serienquelle muss aktiv sein.")
    if (
        len(enabled_anime) != len(set(enabled_anime))
        or not set(enabled_anime).issubset(appconfig.ANIME_PROVIDER_DEFAULTS)
    ):
        raise HTTPException(400, "Die Auswahl der Anime-Quellen ist ungültig.")
    if not content_languages:
        raise HTTPException(400, "Mindestens eine Inhaltssprache muss aktiv sein.")
    if any(
        provider_content_language(provider) not in content_languages
        for provider in enabled_movies + enabled_series + enabled_anime
    ):
        raise HTTPException(400, "Aktive Quellen und Inhaltssprachen passen nicht zusammen.")
    if not await run_in_threadpool(
        appconfig.save_provider_priorities,
        movie_ids,
        series_ids,
        enabled_movies,
        enabled_series,
        content_languages=content_languages,
        anime=anime_ids,
        enabled_anime=enabled_anime,
    ):
        raise HTTPException(500, "Anbieter-Prioritäten konnten nicht gespeichert werden.")
    def _load_provider_config():
        return (
            appconfig.load_provider_priorities(),
            appconfig.load_provider_enabled(),
            appconfig.load_content_languages(),
        )

    priorities, enabled, languages = await run_in_threadpool(_load_provider_config)
    with state.provider_priority_lock:
        state.provider_priorities = priorities
        state.provider_enabled = enabled
        state.content_languages = set(languages)
    with state.movie_list_cache_lock:
        state.movie_list_cache.clear()
    with state.movie_source_cache_lock:
        state.movie_source_cache.clear()
        for slug in [
            cached_slug for cached_slug in state.fp_movies
            if cached_slug.startswith("tmdb:")
        ]:
            state.fp_movies.pop(slug, None)
    with state.series_list_cache_lock:
        state.series_list_cache.clear()
    state.fallback_series_cache.clear()
    return _provider_priority_payload(saved=True)


class JellyfinConfigBody(BaseModel):
    url: str
    api_key: str
    user_id: str = ""
    user_name: str = ""
    cleanup_default: str | None = None


@router.get("/api/v1/jellyfin/config")
@router.get("/api/jellyfin/config")
async def api_jellyfin_config_get():
    return {
        "url": state.jellyfin_cfg.get("url", ""),
        "api_key": "",
        "has_api_key": bool(state.jellyfin_cfg.get("api_key")),
        "user_id": state.jellyfin_cfg.get("user_id", ""),
        "user_name": state.jellyfin_cfg.get("user_name", ""),
        "cleanup_default": normalize_cleanup_mode(
            state.jellyfin_cfg.get("cleanup_default")
        ),
    }


@router.post("/api/v1/jellyfin/config")
@router.post("/api/jellyfin/config")
async def api_jellyfin_config_set(body: JellyfinConfigBody):
    url = body.url.strip()
    with state.jellyfin_cache_lock:
        previous = dict(state.jellyfin_cfg)
    same_server = bool(url) and url.rstrip("/") == previous.get("url", "").rstrip("/")
    api_key = body.api_key.strip() or (previous.get("api_key", "") if same_server else "")
    user_id = body.user_id.strip()
    user_name = body.user_name.strip()
    if body.cleanup_default is not None and body.cleanup_default not in CLEANUP_MODE_LABELS:
        raise HTTPException(400, "Unbekannte Standard-Löschregel.")
    cleanup_default = normalize_cleanup_mode(
        body.cleanup_default
        if body.cleanup_default is not None
        else previous.get("cleanup_default")
    )
    if url and not api_key:
        raise HTTPException(400, "Für Jellyfin fehlt der API-Schlüssel.")
    if url and api_key:
        users = await run_in_threadpool(JellyfinClient(url, api_key).list_users)
        if users is None:
            raise HTTPException(502, "Jellyfin ist nicht erreichbar; Einstellungen wurden nicht geändert.")
        if user_id:
            selected = next((user for user in users if user["id"] == user_id), None)
            if selected is None:
                raise HTTPException(400, "Der gewählte Jellyfin-Benutzer ist nicht verfügbar.")
            user_name = selected["name"]
    def _save_jellyfin_config():
        with state.jellyfin_config_update_lock:
            ok = appconfig.save_jellyfin(
                url, api_key, user_id, user_name, cleanup_default,
            )
            if not ok:
                raise HTTPException(500, "Jellyfin-Einstellungen konnten nicht gespeichert werden.")
            _set_runtime_jellyfin_config({
                "url": url, "api_key": api_key, "user_id": user_id,
                "user_name": user_name, "cleanup_default": cleanup_default,
            })
            _recommender_wake_event.set()

    await run_in_threadpool(_save_jellyfin_config)

    def _recheck():
        with state.watchlist_lock:
            entries = list(state.watchlist)
        check_watchlist_entries(entries, refresh_jellyfin=True)
        broadcast({"type": "jellyfin_update", **watchlist_payload()})
        _auto_download_new_episodes()

    threading.Thread(target=_recheck, daemon=True).start()
    return {
        "url": url,
        "api_key": "",
        "has_api_key": bool(api_key),
        "user_id": user_id,
        "user_name": user_name,
        "cleanup_default": cleanup_default,
        "saved": True,
    }


class JellyfinUsersBody(BaseModel):
    url: str
    api_key: str


@router.post("/api/v1/jellyfin/users")
@router.post("/api/jellyfin/users")
async def api_jellyfin_users(body: JellyfinUsersBody):
    url = body.url.strip() or state.jellyfin_cfg.get("url", "")
    key = body.api_key.strip()
    if not key and url.rstrip("/") == state.jellyfin_cfg.get("url", "").rstrip("/"):
        key = state.jellyfin_cfg.get("api_key", "")
    client = JellyfinClient(url, key)
    if not client.configured:
        raise HTTPException(400, "Jellyfin-Adresse oder API-Schlüssel fehlt.")
    users = await run_in_threadpool(client.list_users)
    if users is None:
        raise HTTPException(502, "Jellyfin-Benutzer konnten nicht geladen werden.")
    return {"users": users}


class TMDBConfigBody(BaseModel):
    api_key: str = ""
    language: str = "de-DE"


@router.get("/api/v1/tmdb/config")
@router.get("/api/tmdb/config")
async def api_tmdb_config_get():
    return {
        "api_key": "",
        "has_api_key": bool(state.tmdb_cfg.get("api_key")),
        "language": state.tmdb_cfg.get("language", "de-DE"),
        "configured": bool(state.tmdb_cfg.get("api_key")),
    }


@router.post("/api/v1/tmdb/config")
@router.post("/api/tmdb/config")
async def api_tmdb_config_set(body: TMDBConfigBody):
    language = appconfig.tmdb_language_for_ui(state.ui_language)
    api_key = body.api_key.strip() or state.tmdb_cfg.get("api_key", "")
    def _save_tmdb_config():
        if not appconfig.save_tmdb(api_key, language):
            raise HTTPException(500, "TMDB-Einstellungen konnten nicht gespeichert werden.")
        return appconfig.load_tmdb()

    state.tmdb_cfg = await run_in_threadpool(_save_tmdb_config)
    state.tmdb_client = TMDBClient(**state.tmdb_cfg)
    with state.movie_source_cache_lock:
        state.movie_source_cache.clear()
        for slug in [
            cached_slug for cached_slug in state.fp_movies
            if cached_slug.startswith("tmdb:")
        ]:
            state.fp_movies.pop(slug, None)
    valid = await run_in_threadpool(state.tmdb_client.validate) if api_key else False
    return {
        "api_key": "",
        "has_api_key": bool(api_key),
        "language": language,
        "configured": bool(api_key),
        "valid": valid,
        "saved": True,
    }


class AutomationConfigBody(BaseModel):
    auto_download: bool = False
    check_interval_min: int = 30
    dl_window_start: int | None = None
    dl_window_end: int | None = None


@router.get("/api/v1/automation/config")
@router.get("/api/automation/config")
async def api_automation_config_get():
    return {**state.automation, "in_window": is_within_download_window()}


@router.post("/api/v1/automation/config")
@router.post("/api/automation/config")
async def api_automation_config_set(body: AutomationConfigBody):
    def _save_automation_config():
        ok = appconfig.save_automation(
            body.auto_download, body.check_interval_min,
            body.dl_window_start, body.dl_window_end,
        )
        if not ok:
            raise HTTPException(500, "Automatik-Einstellungen konnten nicht gespeichert werden.")
        return appconfig.load_automation()

    state.automation = await run_in_threadpool(_save_automation_config)
    if state.automation.get("auto_download"):
        threading.Thread(target=_auto_download_new_episodes, daemon=True).start()
        threading.Thread(target=check_movie_subscriptions, daemon=True).start()
    return {**state.automation, "in_window": is_within_download_window(), "saved": True}


class TelegramConfigBody(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


@router.get("/api/v1/telegram/config")
@router.get("/api/telegram/config")
async def api_telegram_config_get():
    return {
        "enabled": bool(state.telegram_cfg.get("enabled")),
        "bot_token": "",
        "has_bot_token": bool(state.telegram_cfg.get("bot_token")),
        "chat_id": state.telegram_cfg.get("chat_id", ""),
    }


@router.post("/api/v1/telegram/config")
@router.post("/api/telegram/config")
async def api_telegram_config_set(body: TelegramConfigBody):
    token = body.bot_token.strip() or state.telegram_cfg.get("bot_token", "")
    if body.enabled and not token:
        raise HTTPException(400, "Für Telegram fehlt der Bot-Token.")
    def _save_telegram_config():
        if not appconfig.save_telegram(body.enabled, token, body.chat_id):
            raise HTTPException(500, "Telegram-Einstellungen konnten nicht gespeichert werden.")
        return appconfig.load_telegram()

    state.telegram_cfg = await run_in_threadpool(_save_telegram_config)
    return {
        "enabled": bool(state.telegram_cfg.get("enabled")),
        "bot_token": "",
        "has_bot_token": bool(token),
        "chat_id": state.telegram_cfg.get("chat_id", ""),
        "saved": True,
    }


class SeerrConfigBody(BaseModel):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    poll_interval_seconds: int = 60


def _seerr_config_payload() -> dict:
    with state.seerr_requests_lock:
        records = list(state.seerr_requests.values())
    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "enabled": bool(state.seerr_cfg.get("enabled")),
        "url": state.seerr_cfg.get("url", ""),
        "api_key": "",
        "has_api_key": bool(state.seerr_cfg.get("api_key")),
        "poll_interval_seconds": int(state.seerr_cfg.get("poll_interval_seconds", 60)),
        "connected": bool(state.seerr_last_success and not state.seerr_last_error),
        "last_poll": state.seerr_last_poll or None,
        "last_success": state.seerr_last_success or None,
        "last_error": state.seerr_last_error,
        "moonfin_configured": state.seerr_moonfin_configured,
        "moonfin_error": state.seerr_moonfin_error,
        "requests": counts,
    }


@router.get("/api/v1/seerr/config")
@router.get("/api/seerr/config")
async def api_seerr_config_get():
    return _seerr_config_payload()


@router.post("/api/v1/seerr/config")
@router.post("/api/seerr/config")
async def api_seerr_config_set(body: SeerrConfigBody):
    url = body.url.strip().rstrip("/")
    previous = dict(state.seerr_cfg)
    same_server = bool(url) and url.casefold() == str(previous.get("url") or "").rstrip("/").casefold()
    api_key = body.api_key.strip() or (previous.get("api_key", "") if same_server else "")
    interval = max(15, min(3600, int(body.poll_interval_seconds or 60)))
    if body.enabled and not url and not api_key:
        raise HTTPException(400, "Für Seerr fehlen Adresse und API-Schlüssel.")
    if body.enabled and not url:
        raise HTTPException(400, "Für Seerr fehlt die Adresse.")
    if body.enabled and not api_key:
        raise HTTPException(
            400,
            "Für Seerr fehlt der API-Schlüssel: Es ist keiner gespeichert. "
            "Bitte aus Seerr → Einstellungen → Allgemein kopieren und einmal "
            "eintragen; danach darf das Feld wieder leer bleiben.",
        )
    if body.enabled:
        valid = await run_in_threadpool(SeerrClient(url, api_key).test_connection)
        if not valid:
            raise HTTPException(
                502,
                "Seerr ist nicht erreichbar oder der API-Schlüssel ist ungültig; Einstellungen wurden nicht geändert.",
            )
    def _save_seerr_config():
        if not appconfig.save_seerr(body.enabled, url, api_key, interval):
            raise HTTPException(500, "Seerr-Einstellungen konnten nicht gespeichert werden.")
        return appconfig.load_seerr()

    state.seerr_cfg = await run_in_threadpool(_save_seerr_config)
    state.seerr_last_error = ""
    if url:
        moonfin = await run_in_threadpool(configure_moonfin_seerr, url, body.enabled)
        state.seerr_moonfin_configured = bool(moonfin.get("configured"))
        state.seerr_moonfin_error = "" if state.seerr_moonfin_configured else str(moonfin.get("detail") or "")
    _seerr_wake_event.set()
    payload = _seerr_config_payload()
    payload["saved"] = True
    return payload


@router.post("/api/v1/seerr/sync")
@router.post("/api/seerr/sync")
async def api_seerr_sync():
    result = await run_in_threadpool(seerr_poll_once)
    if not result.get("ok"):
        raise HTTPException(502, result.get("detail") or "Seerr-Abgleich fehlgeschlagen.")
    return {**result, **_seerr_config_payload()}


@router.get("/api/seerr/requests")
async def api_seerr_requests():
    with state.seerr_requests_lock:
        records = [dict(record) for record in state.seerr_requests.values()]
    records.sort(key=lambda record: float(record.get("updated_at", 0) or 0), reverse=True)
    return {"requests": records[:100]}


@router.get("/api/v1/browse-dir")
@router.get("/api/browse-dir")
async def api_browse_dir(path: str = ""):
    def _work():
        p = Path(path) if path else Path(state.save_path)
        if not p.exists():
            p = Path.home()
        p = p.resolve()
        try:
            dirs = sorted(
                (d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")),
                key=lambda d: d.name.casefold(),
            )
        except OSError as exc:
            return {"path": str(p), "parent": None, "dirs": [], "error": str(exc)}
        parent = str(p.parent) if p.parent != p else None
        return {
            "path": str(p), "parent": parent,
            "dirs": [{"name": d.name, "path": str(d)} for d in dirs],
        }

    return await run_in_threadpool(_work)


@router.post("/api/session/clear-cookies")
async def api_clear_cookies():
    f = _cookie_file_for("filmpalast.to")
    cleared = False
    if f.exists():
        f.unlink()
        cleared = True
    if state.fp_scraper is not None:
        state.fp_scraper.session.clear_cookies()
    log("Cookies gelöscht." if cleared else "Keine Cookies vorhanden.")
    return {"cleared": cleared}
