"""Application-owned media scan coordinator and existing diagnostics seam."""
import logging
import threading

from application_services.runtime import backend_value
from core.runtime_paths import data_dir
from integrations.jellyfin_scans import ScanManager, interval

_lock = threading.Lock()
_manager = None
_closing = False
logger = logging.getLogger(__name__)


def media_scan_manager():
    global _manager
    with _lock:
        if _manager is None:
            _manager = ScanManager(
                data_dir() / "media_scans.sqlite3",
                lambda: backend_value("get_jellyfin_client")(),
                recognized=_recognized,
                on_submitted=lambda: backend_value("_refresh_jellyfin_after_download_once")(),
                debounce=interval("JELLYFIN_SCAN_DEBOUNCE_SECONDS", 60, 1),
                cooldown=interval("JELLYFIN_SCAN_COOLDOWN_SECONDS", 300, 300),
                retry_base=interval("JELLYFIN_SCAN_RETRY_SECONDS", 300, 60),
            )
        return _manager


def _recognized(evidence):
    state = backend_value("state")
    with state.jellyfin_cache_lock:
        generation = state.jellyfin_config_generation
    client = backend_value("get_jellyfin_client")()
    if not evidence.get("title"):
        return None
    if evidence.get("kind") == "movie":
        items = backend_value("get_jellyfin_library")()
        with state.jellyfin_cache_lock:
            available = state.jellyfin_library_available and generation == state.jellyfin_config_generation
        if items is None or not available:
            return None
        return bool(client.match(evidence["title"], evidence.get("year", ""), items=items, tmdb_id=evidence.get("tmdb_id", "")))
    items = backend_value("get_jellyfin_episodes")()
    series = backend_value("get_jellyfin_series")()
    with state.jellyfin_cache_lock:
        available = (state.jellyfin_episodes_available and state.jellyfin_series_available
                     and generation == state.jellyfin_config_generation)
    if items is None or series is None or not available:
        return None
    ids = client.series_ids_for(evidence["title"], tmdb_id=evidence.get("tmdb_id", ""), items=series)
    if ids is None:
        return None
    return (int(evidence.get("season", 0)), int(evidence.get("episode", 0))) in client.episodes_for_series(evidence["title"], items=items, series_ids=ids)


def _download_evidence(slug):
    state = backend_value("state")
    parsed = backend_value("parse_episode_slug")(slug)
    if parsed:
        series = state.series_cache.get(parsed[0])
        if series:
            return {"kind": "series", "title": series.title, "tmdb_id": getattr(series, "tmdb_id", ""), "season": parsed[1], "episode": parsed[2]}
    movie = state.fp_movies.get(slug)
    return {"kind": "movie", "title": movie.title, "year": str(getattr(movie, "year", ""))} if movie else {}


def request_media_scan(source, path, *, evidence=None, slug=""):
    try:
        manager = media_scan_manager()
        if not evidence and slug:
            try:
                evidence = _download_evidence(slug)
            except Exception:
                evidence = {}
        result = manager.request(source, path, evidence)
        if result in {"queued", "deduplicated"}:
            with _lock:
                if not _closing:
                    manager.start()
        return result
    except Exception:
        logger.warning("Media scan handoff failed source=%s; no scan was started", source)
        return "handoff_failed"


def media_scan_diagnostics():
    try:
        return media_scan_manager().snapshot()
    except Exception:
        return {"phase": "storage_unavailable"}


def start_media_scans():
    global _closing
    try:
        manager = media_scan_manager()
        with _lock:
            _closing = False
            manager.start()
    except Exception:
        logger.error("Media scan storage unavailable; no unchecked scans will be started")


def stop_media_scans():
    global _closing
    with _lock:
        _closing = True
        manager = _manager
    if manager is not None:
        manager.stop()
