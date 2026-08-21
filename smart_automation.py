"""Smart policy for Royal Downloader's unattended NAS automation."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

import config as appconfig
import downloader as downloader_module

MIN_PARALLEL_DOWNLOADS = 1
MAX_PARALLEL_DOWNLOADS = 4
DEFAULT_PARALLEL_DOWNLOADS = 2
DEFAULT_JELLYFIN_STREAMING_MBPS = 5.0
DEFAULT_MOVIE_UPGRADE_START = 0
DEFAULT_MOVIE_UPGRADE_END = 6
JELLYFIN_SESSION_CACHE_SECONDS = 15.0
MAX_BANDWIDTH_MBPS = 10_000.0
MAX_MIN_FREE_SPACE_GB = 1_000_000.0

_ORIGINAL_LOAD_AUTOMATION = appconfig.load_automation
_ORIGINAL_SAVE_AUTOMATION = appconfig.save_automation
_BACKEND: ModuleType | None = None
_CONFIG_PATCHED = False
_DOWNLOADER_PATCHED = False
_RATE_LOCAL = threading.local()
_JELLYFIN_LOCK = threading.Lock()
_JELLYFIN_CACHE: dict[str, Any] = {
    "checked_at": 0.0,
    "signature": (),
    "reachable": False,
    "active_streams": 0,
    "error": "",
}


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return bool(default)
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "ja"}


def _optional_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _valid_hour(value: Any) -> int | None:
    parsed = _optional_int(value)
    return parsed if parsed is not None and 0 <= parsed <= 23 else None


def _stored_value(values: dict[str, str], key: str, env_name: str) -> tuple[Any, bool]:
    if key in values:
        return values.get(key), True
    env = os.environ.get(env_name)
    if env is not None and env.strip() != "":
        return env, True
    return None, False


def _stored_hour(values: dict[str, str], key: str, env_name: str) -> tuple[int | None, bool]:
    value, explicit = _stored_value(values, key, env_name)
    return _valid_hour(value), explicit


def _stored_number(
    values: dict[str, str],
    key: str,
    env_name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value, explicit = _stored_value(values, key, env_name)
    return _clamp_float(value if explicit else default, minimum, maximum, default)


def _stored_bool(values: dict[str, str], key: str, env_name: str, default: bool) -> bool:
    value, explicit = _stored_value(values, key, env_name)
    return _bool_value(value, default) if explicit else bool(default)


def _normalized_window(start: Any, end: Any) -> tuple[int | None, int | None]:
    start_hour = _valid_hour(start)
    end_hour = _valid_hour(end)
    if start_hour is None or end_hour is None:
        return None, None
    return start_hour, end_hour


def load_automation_policy() -> dict[str, Any]:
    """Load extended rules while preserving the old seven-day window."""
    legacy = dict(_ORIGINAL_LOAD_AUTOMATION())
    values = appconfig._read_all()

    weekday_start, weekday_start_explicit = _stored_hour(
        values, "weekday_window_start", "WEEKDAY_WINDOW_START",
    )
    weekday_end, weekday_end_explicit = _stored_hour(
        values, "weekday_window_end", "WEEKDAY_WINDOW_END",
    )
    weekend_start, weekend_start_explicit = _stored_hour(
        values, "weekend_window_start", "WEEKEND_WINDOW_START",
    )
    weekend_end, weekend_end_explicit = _stored_hour(
        values, "weekend_window_end", "WEEKEND_WINDOW_END",
    )
    legacy_window = _normalized_window(
        legacy.get("dl_window_start"), legacy.get("dl_window_end"),
    )
    if not (weekday_start_explicit or weekday_end_explicit):
        weekday_start, weekday_end = legacy_window
    else:
        weekday_start, weekday_end = _normalized_window(weekday_start, weekday_end)
    if not (weekend_start_explicit or weekend_end_explicit):
        weekend_start, weekend_end = legacy_window
    else:
        weekend_start, weekend_end = _normalized_window(weekend_start, weekend_end)

    parallel = int(_stored_number(
        values, "max_parallel_downloads", "MAX_PARALLEL_DOWNLOADS",
        DEFAULT_PARALLEL_DOWNLOADS, MIN_PARALLEL_DOWNLOADS, MAX_PARALLEL_DOWNLOADS,
    ))
    max_bandwidth = _stored_number(
        values, "max_bandwidth_mbps", "MAX_BANDWIDTH_MBPS",
        0.0, 0.0, MAX_BANDWIDTH_MBPS,
    )
    min_free = _stored_number(
        values, "min_free_space_gb", "MIN_FREE_SPACE_GB",
        0.0, 0.0, MAX_MIN_FREE_SPACE_GB,
    )
    playback_throttle = _stored_bool(
        values, "jellyfin_throttle_enabled", "JELLYFIN_THROTTLE_ENABLED", False,
    )
    streaming_budget = _stored_number(
        values, "jellyfin_streaming_bandwidth_mbps",
        "JELLYFIN_STREAMING_BANDWIDTH_MBPS",
        DEFAULT_JELLYFIN_STREAMING_MBPS, 0.1, MAX_BANDWIDTH_MBPS,
    )
    movie_night_only = _stored_bool(
        values, "movie_upgrades_night_only", "MOVIE_UPGRADES_NIGHT_ONLY", False,
    )
    movie_start, movie_start_explicit = _stored_hour(
        values, "movie_upgrade_window_start", "MOVIE_UPGRADE_WINDOW_START",
    )
    movie_end, movie_end_explicit = _stored_hour(
        values, "movie_upgrade_window_end", "MOVIE_UPGRADE_WINDOW_END",
    )
    if not (movie_start_explicit or movie_end_explicit):
        movie_start, movie_end = DEFAULT_MOVIE_UPGRADE_START, DEFAULT_MOVIE_UPGRADE_END
    else:
        movie_start, movie_end = _normalized_window(movie_start, movie_end)
        if movie_start is None or movie_end is None:
            movie_start, movie_end = DEFAULT_MOVIE_UPGRADE_START, DEFAULT_MOVIE_UPGRADE_END

    return {
        **legacy,
        "dl_window_start": weekday_start,
        "dl_window_end": weekday_end,
        "weekday_window_start": weekday_start,
        "weekday_window_end": weekday_end,
        "weekend_window_start": weekend_start,
        "weekend_window_end": weekend_end,
        "max_parallel_downloads": parallel,
        "max_bandwidth_mbps": round(max_bandwidth, 3),
        "min_free_space_gb": round(min_free, 3),
        "jellyfin_throttle_enabled": playback_throttle,
        "jellyfin_streaming_bandwidth_mbps": round(streaming_budget, 3),
        "movie_upgrades_night_only": movie_night_only,
        "movie_upgrade_window_start": movie_start,
        "movie_upgrade_window_end": movie_end,
    }


def save_automation_policy(
    *,
    auto_download: bool,
    check_interval_min: int,
    weekday_window_start: int | None,
    weekday_window_end: int | None,
    weekend_window_start: int | None,
    weekend_window_end: int | None,
    max_parallel_downloads: int,
    max_bandwidth_mbps: float,
    min_free_space_gb: float,
    jellyfin_throttle_enabled: bool,
    jellyfin_streaming_bandwidth_mbps: float,
    movie_upgrades_night_only: bool,
    movie_upgrade_window_start: int | None,
    movie_upgrade_window_end: int | None,
) -> bool:
    weekday_start, weekday_end = _normalized_window(
        weekday_window_start, weekday_window_end,
    )
    weekend_start, weekend_end = _normalized_window(
        weekend_window_start, weekend_window_end,
    )
    movie_start, movie_end = _normalized_window(
        movie_upgrade_window_start, movie_upgrade_window_end,
    )
    if movie_start is None or movie_end is None:
        movie_start, movie_end = DEFAULT_MOVIE_UPGRADE_START, DEFAULT_MOVIE_UPGRADE_END
    parallel = _clamp_int(
        max_parallel_downloads, MIN_PARALLEL_DOWNLOADS,
        MAX_PARALLEL_DOWNLOADS, DEFAULT_PARALLEL_DOWNLOADS,
    )
    bandwidth = _clamp_float(max_bandwidth_mbps, 0.0, MAX_BANDWIDTH_MBPS, 0.0)
    min_free = _clamp_float(min_free_space_gb, 0.0, MAX_MIN_FREE_SPACE_GB, 0.0)
    streaming = _clamp_float(
        jellyfin_streaming_bandwidth_mbps, 0.1, MAX_BANDWIDTH_MBPS,
        DEFAULT_JELLYFIN_STREAMING_MBPS,
    )
    interval = max(5, int(check_interval_min or 30))
    return bool(appconfig._update_all({
        "auto_download": "true" if auto_download else "false",
        "check_interval_min": str(interval),
        "dl_window_start": "" if weekday_start is None else str(weekday_start),
        "dl_window_end": "" if weekday_end is None else str(weekday_end),
        "weekday_window_start": "" if weekday_start is None else str(weekday_start),
        "weekday_window_end": "" if weekday_end is None else str(weekday_end),
        "weekend_window_start": "" if weekend_start is None else str(weekend_start),
        "weekend_window_end": "" if weekend_end is None else str(weekend_end),
        "max_parallel_downloads": str(parallel),
        "max_bandwidth_mbps": f"{bandwidth:g}",
        "min_free_space_gb": f"{min_free:g}",
        "jellyfin_throttle_enabled": "true" if jellyfin_throttle_enabled else "false",
        "jellyfin_streaming_bandwidth_mbps": f"{streaming:g}",
        "movie_upgrades_night_only": "true" if movie_upgrades_night_only else "false",
        "movie_upgrade_window_start": str(movie_start),
        "movie_upgrade_window_end": str(movie_end),
    }))


def save_automation_compat(
    auto_download: bool,
    check_interval_min: int,
    dl_window_start: int | None,
    dl_window_end: int | None,
) -> bool:
    """Keep four-field legacy clients safe without deleting advanced rules."""
    current = load_automation_policy()
    return save_automation_policy(
        auto_download=auto_download,
        check_interval_min=check_interval_min,
        weekday_window_start=dl_window_start,
        weekday_window_end=dl_window_end,
        weekend_window_start=dl_window_start,
        weekend_window_end=dl_window_end,
        max_parallel_downloads=current["max_parallel_downloads"],
        max_bandwidth_mbps=current["max_bandwidth_mbps"],
        min_free_space_gb=current["min_free_space_gb"],
        jellyfin_throttle_enabled=current["jellyfin_throttle_enabled"],
        jellyfin_streaming_bandwidth_mbps=current["jellyfin_streaming_bandwidth_mbps"],
        movie_upgrades_night_only=current["movie_upgrades_night_only"],
        movie_upgrade_window_start=current["movie_upgrade_window_start"],
        movie_upgrade_window_end=current["movie_upgrade_window_end"],
    )


def window_contains(hour: int, start: int | None, end: int | None) -> bool:
    if start is None or end is None or start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def schedule_is_open(policy: dict[str, Any], weekday: int, hour: int) -> bool:
    prefix = "weekday" if 0 <= int(weekday) <= 4 else "weekend"
    return window_contains(
        int(hour),
        _valid_hour(policy.get(f"{prefix}_window_start")),
        _valid_hour(policy.get(f"{prefix}_window_end")),
    )


def movie_upgrade_window_is_open(policy: dict[str, Any], hour: int) -> bool:
    if not policy.get("movie_upgrades_night_only"):
        return True
    return window_contains(
        int(hour),
        _valid_hour(policy.get("movie_upgrade_window_start")),
        _valid_hour(policy.get("movie_upgrade_window_end")),
    )


def bind_backend(backend: ModuleType) -> None:
    global _BACKEND
    _BACKEND = backend
    policy = load_automation_policy()
    backend.state.automation = policy
    apply_runtime_policy(backend.state, policy)


def backend() -> ModuleType | None:
    return _BACKEND


def current_policy() -> dict[str, Any]:
    if _BACKEND is not None and getattr(_BACKEND, "state", None) is not None:
        return dict(_BACKEND.state.automation)
    return load_automation_policy()


def apply_runtime_policy(state: Any, policy: dict[str, Any] | None = None) -> None:
    configured = policy or current_policy()
    queue = getattr(state, "dl_queue", None)
    if queue is not None and hasattr(queue, "set_max_parallel"):
        queue.set_max_parallel(
            configured.get("max_parallel_downloads", DEFAULT_PARALLEL_DOWNLOADS),
        )


def _nearest_existing_path(raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    try:
        candidate = Path(str(raw_path)).expanduser()
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return candidate if candidate.exists() else None
    except (OSError, TypeError, ValueError):
        return None


def storage_status(state: Any, media_type: str = "series") -> dict[str, Any]:
    policy = dict(getattr(state, "automation", {}) or current_policy())
    threshold = max(0.0, float(policy.get("min_free_space_gb") or 0.0))
    configured_path = (
        getattr(state, "save_path", "")
        if media_type == "movie"
        else getattr(state, "series_path", "")
    )
    path = _nearest_existing_path(configured_path)
    if threshold <= 0:
        return {
            "enabled": False, "ok": True, "threshold_gb": 0.0,
            "free_gb": None, "path": str(configured_path or ""), "error": "",
        }
    if path is None:
        return {
            "enabled": True, "ok": False, "threshold_gb": threshold,
            "free_gb": None, "path": str(configured_path or ""),
            "error": "Speicherpfad ist nicht erreichbar",
        }
    try:
        free_gb = shutil.disk_usage(path).free / (1024 ** 3)
        return {
            "enabled": True, "ok": free_gb >= threshold,
            "threshold_gb": round(threshold, 2), "free_gb": round(free_gb, 2),
            "path": str(path), "error": "",
        }
    except OSError as exc:
        return {
            "enabled": True, "ok": False, "threshold_gb": round(threshold, 2),
            "free_gb": None, "path": str(path),
            "error": f"Speicherstatus nicht lesbar: {exc}",
        }


def _jellyfin_signature(state: Any) -> tuple[str, str]:
    cfg = dict(getattr(state, "jellyfin_cfg", {}) or {})
    return str(cfg.get("url") or "").rstrip("/"), str(cfg.get("api_key") or "")


def jellyfin_playback_status(
    state: Any | None = None, *, force: bool = False,
) -> dict[str, Any]:
    if state is None:
        state = getattr(_BACKEND, "state", None)
    if state is None:
        return {"configured": False, "reachable": False, "active_streams": 0, "error": ""}
    base_url, api_key = _jellyfin_signature(state)
    if not base_url or not api_key:
        return {"configured": False, "reachable": False, "active_streams": 0, "error": ""}
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        return {
            "configured": True, "reachable": False, "active_streams": 0,
            "error": "Jellyfin-Adresse muss HTTP oder HTTPS verwenden",
        }

    signature = (base_url, api_key)
    now = time.monotonic()
    with _JELLYFIN_LOCK:
        if (
            not force
            and _JELLYFIN_CACHE["signature"] == signature
            and now - float(_JELLYFIN_CACHE["checked_at"]) < JELLYFIN_SESSION_CACHE_SECONDS
        ):
            return {
                "configured": True,
                "reachable": bool(_JELLYFIN_CACHE["reachable"]),
                "active_streams": int(_JELLYFIN_CACHE["active_streams"]),
                "error": str(_JELLYFIN_CACHE["error"]),
            }

    request = urllib.request.Request(
        f"{base_url}/Sessions",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
    )
    reachable = False
    active_streams = 0
    error = ""
    try:
        with urllib.request.urlopen(request, timeout=4.0) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Jellyfin lieferte keine Sitzungsliste")
        reachable = True
        for session in payload:
            if not isinstance(session, dict) or not session.get("NowPlayingItem"):
                continue
            play_state = session.get("PlayState") or {}
            if not bool(play_state.get("IsPaused", False)):
                active_streams += 1
    except Exception as exc:
        error = str(exc)[:180]

    with _JELLYFIN_LOCK:
        _JELLYFIN_CACHE.update({
            "checked_at": now, "signature": signature, "reachable": reachable,
            "active_streams": active_streams, "error": error,
        })
    return {
        "configured": True, "reachable": reachable,
        "active_streams": active_streams, "error": error,
    }


def effective_bandwidth(
    state: Any | None = None, policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configured = dict(policy or (
        getattr(state, "automation", {}) if state is not None else current_policy()
    ))
    normal_budget = max(0.0, float(configured.get("max_bandwidth_mbps") or 0.0))
    streaming_budget = max(
        0.1,
        float(configured.get("jellyfin_streaming_bandwidth_mbps") or DEFAULT_JELLYFIN_STREAMING_MBPS),
    )
    playback = jellyfin_playback_status(state)
    reduced = bool(
        configured.get("jellyfin_throttle_enabled")
        and playback.get("active_streams", 0) > 0
    )
    total = (
        streaming_budget if normal_budget <= 0 else min(normal_budget, streaming_budget)
    ) if reduced else normal_budget
    parallel = _clamp_int(
        configured.get("max_parallel_downloads"), MIN_PARALLEL_DOWNLOADS,
        MAX_PARALLEL_DOWNLOADS, DEFAULT_PARALLEL_DOWNLOADS,
    )
    per_download = total / parallel if total > 0 else 0.0
    return {
        "configured_mbps": round(normal_budget, 3),
        "effective_mbps": round(total, 3),
        "per_download_mbps": round(per_download, 3),
        "reduced_for_jellyfin": reduced,
        "jellyfin": playback,
    }


def effective_rate_limit_bps(state: Any | None = None) -> int:
    mbps = float(effective_bandwidth(state).get("per_download_mbps") or 0.0)
    return max(0, int(mbps * 1024 * 1024))


def automatic_series_decision(
    state: Any, *, now: time.struct_time | None = None,
) -> tuple[bool, str]:
    policy = dict(getattr(state, "automation", {}) or current_policy())
    if not policy.get("auto_download"):
        return False, "Auto-Download ist ausgeschaltet"
    local = now or time.localtime()
    if not schedule_is_open(policy, local.tm_wday, local.tm_hour):
        return False, "außerhalb des heutigen Automatik-Zeitfensters"
    disk = storage_status(state, "series")
    if not disk["ok"]:
        if disk.get("free_gb") is not None:
            return False, f"nur {disk['free_gb']:.1f} GB frei; Minimum {disk['threshold_gb']:.1f} GB"
        return False, disk.get("error") or "Speicherstatus unbekannt"
    return True, ""


def automatic_movie_upgrade_decision(
    state: Any, *, now: time.struct_time | None = None,
) -> tuple[bool, str]:
    policy = dict(getattr(state, "automation", {}) or current_policy())
    local = now or time.localtime()
    if not movie_upgrade_window_is_open(policy, local.tm_hour):
        return False, "Film-Upgrades warten auf das konfigurierte Nachtfenster"
    disk = storage_status(state, "movie")
    if not disk["ok"]:
        if disk.get("free_gb") is not None:
            return False, f"nur {disk['free_gb']:.1f} GB frei; Minimum {disk['threshold_gb']:.1f} GB"
        return False, disk.get("error") or "Speicherstatus unbekannt"
    return True, ""


def policy_payload(state: Any | None = None) -> dict[str, Any]:
    if state is None:
        state = getattr(_BACKEND, "state", None)
    policy = dict(getattr(state, "automation", {}) or current_policy())
    local = time.localtime()
    bandwidth = effective_bandwidth(state, policy)
    storage = storage_status(state, "series") if state is not None else {
        "enabled": bool(policy.get("min_free_space_gb")), "ok": True,
        "threshold_gb": float(policy.get("min_free_space_gb") or 0.0),
        "free_gb": None, "path": "", "error": "",
    }
    active_downloads = 0
    if state is not None and getattr(state, "dl_queue", None) is not None:
        try:
            active_downloads = sum(
                1 for job in state.dl_queue.active_jobs()
                if not getattr(job, "is_preparation_job", False)
            )
        except Exception:
            active_downloads = 0
    schedule_open = schedule_is_open(policy, local.tm_wday, local.tm_hour)
    return {
        **policy,
        "in_window": schedule_open,
        "policy_state": {
            "weekday": local.tm_wday,
            "hour": local.tm_hour,
            "schedule_open": schedule_open,
            "movie_upgrade_window_open": movie_upgrade_window_is_open(policy, local.tm_hour),
            "active_downloads": active_downloads,
            "storage": storage,
            "bandwidth": bandwidth,
        },
    }


def _queue_set_max_parallel(self, value: int) -> int:
    normalized = _clamp_int(
        value, MIN_PARALLEL_DOWNLOADS, MAX_PARALLEL_DOWNLOADS,
        DEFAULT_PARALLEL_DOWNLOADS,
    )
    with self._lock:
        self._max_parallel = normalized
    return normalized


class _SubprocessProxy:
    def __init__(self, module):
        self._module = module

    def __getattr__(self, name):
        return getattr(self._module, name)

    def Popen(self, command, *args, **kwargs):
        rate_bps = max(0, int(getattr(_RATE_LOCAL, "bps", 0) or 0))
        cmd = list(command) if isinstance(command, (list, tuple)) else command
        if (
            rate_bps > 0 and isinstance(cmd, list)
            and "yt_dlp" in cmd and "--limit-rate" not in cmd
        ):
            cmd[-1:-1] = ["--limit-rate", str(rate_bps)]
        return self._module.Popen(cmd, *args, **kwargs)


class _RateLimitedResponse:
    def __init__(self, response: Any, rate_bps: int):
        self._response = response
        self._rate_bps = max(1, int(rate_bps))

    def __getattr__(self, name):
        return getattr(self._response, name)

    def iter_content(self, *args, **kwargs):
        started = time.monotonic()
        delivered = 0
        for chunk in self._response.iter_content(*args, **kwargs):
            if chunk:
                delivered += len(chunk)
                target = started + delivered / self._rate_bps
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
            yield chunk


def _install_curl_rate_wrapper() -> None:
    try:
        from curl_cffi import requests as curl_requests
    except Exception:
        return
    if getattr(curl_requests, "__royal_smart_rate_wrapped__", False):
        return
    original_get = curl_requests.get

    def rate_aware_get(*args, **kwargs):
        response = original_get(*args, **kwargs)
        rate_bps = max(0, int(getattr(_RATE_LOCAL, "bps", 0) or 0))
        return _RateLimitedResponse(response, rate_bps) if rate_bps > 0 else response

    curl_requests.get = rate_aware_get
    curl_requests.__royal_smart_rate_wrapped__ = True


def _with_rate_limit(original):
    def wrapped(job, *args, **kwargs):
        previous = getattr(_RATE_LOCAL, "bps", None)
        state = getattr(_BACKEND, "state", None) if _BACKEND is not None else None
        _RATE_LOCAL.bps = effective_rate_limit_bps(state)
        try:
            return original(job, *args, **kwargs)
        finally:
            if previous is None:
                try:
                    delattr(_RATE_LOCAL, "bps")
                except AttributeError:
                    pass
            else:
                _RATE_LOCAL.bps = previous

    wrapped.__name__ = getattr(original, "__name__", "rate_limited_download")
    wrapped.__doc__ = getattr(original, "__doc__", None)
    return wrapped


def install() -> None:
    global _CONFIG_PATCHED, _DOWNLOADER_PATCHED
    if not _CONFIG_PATCHED:
        appconfig.load_automation = load_automation_policy
        appconfig.save_automation = save_automation_compat
        _CONFIG_PATCHED = True
    if not _DOWNLOADER_PATCHED:
        queue_class = downloader_module.DownloadQueue
        if not hasattr(queue_class, "set_max_parallel"):
            queue_class.set_max_parallel = _queue_set_max_parallel
        if not isinstance(downloader_module.subprocess, _SubprocessProxy):
            downloader_module.subprocess = _SubprocessProxy(downloader_module.subprocess)
        job_class = downloader_module.DownloadJob
        if not getattr(job_class, "__royal_smart_rate_wrapped__", False):
            job_class._download_ytdlp = _with_rate_limit(job_class._download_ytdlp)
            job_class._download_direct = _with_rate_limit(job_class._download_direct)
            job_class.__royal_smart_rate_wrapped__ = True
        _install_curl_rate_wrapper()
        _DOWNLOADER_PATCHED = True


install()
