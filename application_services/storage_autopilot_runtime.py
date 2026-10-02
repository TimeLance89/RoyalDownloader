"""Application lifecycle adapter for the storage planner, not another move engine."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import core.config as appconfig
from application_services.runtime import backend_value
from core.queue_jobs import media_type_for_slug
from integrations.jellyfin_client import JellyfinClient
from storage.storage_autopilot import (
    get_autopilot,
    observe_volumes,
    refresh_recommendations,
)
from storage.storage_inventory import identity, read_state, record_activity, transact
from storage.storage_move_runtime import list_move_jobs
from storage.storage_placement import reserve_download

logger = logging.getLogger(__name__)
_STOP = threading.Event()
_WAKE = threading.Event()
_THREAD = None
_START_LOCK = threading.Lock()


def wake():
    _WAKE.set()


def queue_context() -> list[dict]:
    try:
        state = backend_value("state")
    except RuntimeError:
        return []
    with state.queue_claim_lock:
        jobs = [dict(job) for job in state.queue_jobs.values() if job.get("status") not in ("completed", "failed", "cancelled")]
    ids = {job["job_id"] for job in jobs}
    for job in state.dl_queue.active_jobs() + state.dl_queue.pending_jobs():
        # Preparation jobs share the physical scheduler but are not media
        # downloads. They intentionally have no job_id/out_path/byte counters
        # and must never participate in storage reservation accounting.
        if getattr(job, "is_preparation_job", False):
            continue
        job_id = str(getattr(job, "job_id", "") or "")
        if not job_id or job_id in ids:
            continue
        jobs.append({
            "job_id": job_id,
            "attempt_id": str(getattr(job, "attempt_id", "") or ""),
            "status": "downloading",
            "final_path": str(getattr(job, "out_path", "") or ""),
            "media_type": (
                "anime"
                if str(getattr(job, "provider", "") or "").casefold() in ("aniworld", "mkissa")
                else media_type_for_slug(str(getattr(job, "queue_slug", "") or ""))
            ),
            "total_bytes": getattr(job, "total_bytes", None),
            "downloaded_bytes": int(getattr(job, "downloaded_bytes", 0) or 0),
        })
        ids.add(job_id)
    return jobs


def playback_idle() -> bool:
    config = appconfig.load_jellyfin()
    if config.get("url") and config.get("api_key"):
        try:
            parsed = urlparse(config["url"])
            if parsed.scheme.casefold() not in ("http", "https") or not parsed.hostname:
                return False
        except ValueError:
            return False
    client = JellyfinClient(config.get("url", ""), config.get("api_key", ""), timeout=5)
    if not client.configured:
        return True
    return client.has_active_playback() is False


def place_download(job: dict, path: Path, *, provider: str = "") -> Path:
    document = read_state()
    if document.get("storage_error"):
        raise ValueError("Speicher-Autopilot konnte seine Sicherheitsdaten nicht lesen.")
    if document["policy"]["mode"] not in ("automatic", "full"):
        return path
    jobs = queue_context()
    reconcile_reservations(jobs)
    current = get_autopilot(queue_jobs=jobs)
    if current["storage_error"]:
        raise ValueError("Speicher-Autopilot konnte seine Sicherheitsdaten nicht lesen.")
    media = "anime" if provider in ("aniworld", "mkissa") else "movies" if job.get("media_type") == "movie" else "series"
    result = reserve_download(job["job_id"], path, media, current["roots"], queue_context(),
                              list_move_jobs()["jobs"], size=int(job.get("total_bytes") or 0))
    return Path(result["path"])


def record_publication(job, path: Path) -> None:
    """Record the actual verified publication, including collision-renamed files."""
    current = get_autopilot()
    media_key = "movies" if media_type_for_slug(job.queue_slug) == "movie" and job.provider not in ("aniworld", "mkissa") else "series"
    for root in sorted(current["roots"], key=lambda root: (len(Path(root.get("path", "")).parts), root["key"] == media_key), reverse=True):
        if not root.get("available") or root["location_mode"] != "media":
            continue
        try:
            relative = path.absolute().relative_to(Path(root.get("resolved_path") or root["path"]))
            stat = path.stat(follow_symlinks=False)
        except (OSError, ValueError):
            continue
        if path.is_symlink() or not path.is_file():
            return
        series = media_key == "series"
        grouped = series and len(relative.parts) > 1
        item_relative = relative.parts[0] if grouped else relative.as_posix()
        item_id = identity(root["key"], item_relative)
        def update(document):
            old = document["inventory"].get(item_id, {})
            files = dict(old.get("owned_files", {}))
            stamps = dict(old.get("owned_stamps", {}))
            if len(files) < 2000 or relative.as_posix() in files:
                files[relative.as_posix()] = stat.st_size
                stamps[relative.as_posix()] = [stat.st_mtime_ns, stat.st_ino]
            item = {**old, "id": item_id, "root": root["key"], "relative_path": item_relative,
                    "name": relative.parts[0] if grouped else path.name, "series_name": relative.parts[0] if grouped else "",
                    "media_type": "anime" if job.provider in ("aniworld", "mkissa") else "series" if series else "movies",
                    "size_bytes": sum(files.values()), "modified_at": max(old.get("modified_at", 0), stat.st_mtime),
                    "verified_at": time.time(), "owned": bool(old.get("owned")) if series else True,
                    "owned_files": files, "owned_stamps": stamps}
            document["inventory"][item_id] = item
            document["reservations"].pop(job.job_id, None)
            record_activity(document, "download_completed", job_id=job.job_id, destination=str(path))
        try:
            transact(update)
            _WAKE.set()
        except (OSError, ValueError):
            logger.warning("Storage inventory publication unavailable")
        return


def reconcile_reservations(jobs: list[dict]) -> None:
    ids = {job["job_id"] for job in jobs if job.get("status") not in ("completed", "failed", "cancelled")}
    def update(document):
        document["reservations"] = {key: value for key, value in document["reservations"].items() if key in ids}
    transact(update)


def release_reservation(job_id: str) -> None:
    """Release capacity as soon as a logical queue job becomes terminal."""
    if not job_id or job_id not in read_state()["reservations"]:
        return

    def update(document):
        document["reservations"].pop(job_id, None)
    transact(update)


def optimize(*, manual: bool = False) -> dict:
    from storage.storage_actions import in_window, optimize_storage
    from storage.storage_cleanup_policy import run_cleanup
    jobs = queue_context()
    reconcile_reservations(jobs)
    observe_volumes()
    refresh_recommendations(jobs)
    result = optimize_storage(queue_jobs=jobs, playback_check=playback_idle, manual=manual, queue_check=queue_context)
    if in_window(read_state()["policy"]) and not list_move_jobs()["active_count"]:
        result["cleanup"] = run_cleanup(queue_context())
    return result


def _loop():
    next_run = 0
    previous_policy = None
    last_round = 0
    while not _STOP.is_set():
        try:
            policy = read_state()["policy"]
            if policy != previous_policy:
                next_run = min(next_run, time.time())
                previous_policy = policy
            if time.time() >= next_run:
                if policy["mode"] != "monitor":
                    optimize()
                else:
                    observe_volumes()
                next_run = time.time() + policy["interval_hours"] * 3600
                last_round = time.time()
                # A daily window must not be missed by a six-hour cadence.
                from storage.storage_actions import next_window_start
                window = next_window_start(policy)
                if window is not None:
                    next_run = min(next_run, window)
        except Exception:
            logger.exception("Storage Autopilot round deferred; normal downloads remain independent")
            next_run = time.time() + 3600
        event = _WAKE.wait(60)
        _WAKE.clear()
        if event and not _STOP.is_set():
            try:
                observe_volumes()
            except (OSError, ValueError):
                logger.warning("Storage observation deferred")
            # Replan metadata after relevant events, bounded to one round/hour.
            # Execution retains its independent interval and time-window guard.
            next_run = min(next_run, max(time.time(), last_round + 3600))



def start():
    global _THREAD
    with _START_LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="royal-storage-autopilot", daemon=True)
        _THREAD.start()


def stop():
    _STOP.set()
    _WAKE.set()
    if _THREAD:
        _THREAD.join(timeout=6)
