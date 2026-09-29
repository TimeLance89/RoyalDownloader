"""Conservative orchestration of existing signed, verified move jobs."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from itertools import islice
from pathlib import Path

from storage.storage_autopilot import get_autopilot, media_paths
from storage.storage_inventory import read_state, record_activity, transact
from storage.storage_locations import load_storage_locations
from storage.storage_manager import _safe_target, _token
from storage.storage_move import _guard_source_tree, _measure_move_source, _root_for_key
from storage.storage_move_runtime import create_move_job, list_move_jobs
from storage.storage_placement import reserved_by_volume
from storage.storage_planner import plan_recommendations
from storage.storage_policy import GIB, volume_policy
from storage.storage_score import score_target

_ACTION_LOCK = threading.RLock()


def in_window(policy: dict, now: datetime | None = None) -> bool:
    if not policy["window_enabled"]:
        return True
    now = now or datetime.now().astimezone()
    current = now.strftime("%H:%M")
    start, end = policy["window_start"], policy["window_end"]
    if start == end:
        return True
    return start <= current < end if start < end else current >= start or current < end


def next_window_start(policy: dict, now: datetime | None = None) -> float | None:
    if not policy["window_enabled"] or in_window(policy, now):
        return None
    now = now or datetime.now().astimezone()
    hour, minute = map(int, policy["window_start"].split(":"))
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)
    return start.timestamp()


def fresh_candidate(item: dict) -> tuple[dict, Path]:
    root = _root_for_key(media_paths(), load_storage_locations(), item["root"])
    source, relative = _safe_target(root.path, item["relative_path"])
    _guard_source_tree(source)
    measured = _measure_move_source(source)
    if not measured.complete or measured.size != item["size_bytes"]:
        raise ValueError("Inhalt verändert; vor einer Verschiebung erneut analysieren.")
    expires = int(time.time()) + 300
    return {"root_key": item["root"], "relative_path": relative,
            "expected_size": measured.size, "expires_at": expires,
            "token": _token(root.path, root.token_key, relative, measured.kind,
                            measured.size, measured.modified_ns, expires)}, source


def apply_recommendation(recommendation_id: str, *, queue_jobs: list[dict],
                         playback_check, automatic: bool = False, queue_check=None) -> dict:
    with _ACTION_LOCK:
        document = read_state()
        policy = document["policy"]
        recommendation = document["recommendations"].get(recommendation_id)
        if not recommendation or recommendation.get("state") != "available" or document.get("storage_error"):
            raise ValueError("Empfehlung ist nicht verfügbar; Speicherübersicht aktualisieren.")
        if policy["mode"] == "monitor" or automatic and policy["mode"] not in ("automatic", "full"):
            raise ValueError("Dieser Autopilot-Modus erlaubt keine automatische Aktion.")
        if automatic and not in_window(policy):
            raise ValueError("Außerhalb des freigegebenen Zeitfensters.")
        if automatic and recommendation.get("archive") and policy["mode"] != "full":
            raise ValueError("Automatische Archivierung ist nur im Modus Vollautomatisch freigegeben.")
        item = document["inventory"].get(recommendation["item_id"])
        if not item:
            raise ValueError("Inhalt ist nicht mehr im Inventar.")
        protection = document["protections"].get(item["id"], {})
        if protection.get("no_move") or protection.get("keep_volume") or recommendation.get("archive") and protection.get("no_archive"):
            raise ValueError("Inhalt ist gegen diese Speicheraktion geschützt.")
        if automatic and not item.get("owned") and not item.get("owned_files"):
            raise ValueError("Automatische Verschiebung erfordert bestätigte Ownership.")
        if queue_jobs:
            raise ValueError("Downloads oder Queue-Inhalte aktiv; Optimierung wird verschoben.")
        moves = list_move_jobs()
        existing = next((job for job in [*moves["jobs"], *moves["history"]]
                         if job.get("autopilot_id") == recommendation_id and job["status"] != "failed"), None)
        if existing:
            _attach_job(recommendation_id, existing, automatic)
            return existing
        if moves["active_count"]:
            raise ValueError("Ein Verschiebejob ist bereits aktiv; NAS-I/O bleibt seriell.")
        if not playback_check():
            raise ValueError("Wiedergabe aktiv oder nicht zuverlässig geprüft; Optimierung wird verschoben.")
        current = get_autopilot(queue_jobs=queue_jobs)
        source = next((root for root in current["roots"] if root["key"] == item["root"]), None)
        target = next((root for root in current["roots"] if root["key"] == recommendation["destination_root"]), None)
        if not source or not target or not source.get("available") or not target.get("available"):
            raise ValueError("Quell- oder Zielvolume offline.")
        source_policy = volume_policy(source, document["volumes"])
        target_policy = volume_policy(target, document["volumes"])
        if not source_policy["allow_moves_out"] or not target_policy["allow_moves_in"]:
            raise ValueError("Volume-Schutz verhindert diese Verschiebung.")
        budgets = reserved_by_volume(document, current["roots"], queue_jobs, moves["jobs"])
        if automatic and not any(proposal["id"] == recommendation_id for proposal in plan_recommendations(current["roots"], document, now=time.time(), reserved=budgets)):
            raise ValueError("Empfehlung passt nicht mehr zum aktuellen Speicherzustand; erneut planen.")
        score = score_target(target, target_policy, media_type=item["media_type"],
                             size=item["size_bytes"], reserved=budgets.get(target.get("volume_id"), 0), overflow=True)
        if not score["eligible"]:
            raise ValueError("Zielreserve oder kritische Zielauslastung verhindert diese Verschiebung.")
        if automatic and time.time() - item.get("last_moved_at", 0) < policy["cooldown_hours"] * 3600:
            raise ValueError("Inhalt befindet sich im Umorganisations-Cooldown.")
        if item["size_bytes"] > policy["max_move_gib"] * GIB:
            raise ValueError("Verschiebung überschreitet das Rundenbudget.")
        candidate, _source = fresh_candidate(item)
        if automatic:
            root_path = _root_for_key(media_paths(), load_storage_locations(), item["root"]).path
            paths = [_source] if _source.is_file() else list(islice((path for path in _source.rglob("*") if path.is_file()), 2001))
            if len(paths) > 2000:
                raise ValueError("Inhalt überschreitet das automatische Ownership-Prüfbudget.")
            stats = {path.relative_to(root_path).as_posix(): path.stat(follow_symlinks=False) for path in paths}
            files = {key: stat.st_size for key, stat in stats.items()}
            stamps = {key: [stat.st_mtime_ns, stat.st_ino] for key, stat in stats.items()}
            if files != item.get("owned_files") or stamps != item.get("owned_stamps"):
                raise ValueError("Inhalt enthält nicht bestätigte oder veränderte Dateien; automatische Verschiebung gesperrt.")
        # Source verification may take time. Recheck revocable permissions and
        # live queue state immediately before submitting to the serial runtime.
        latest = read_state()
        if latest["policy"] != policy or latest["volumes"] != document["volumes"] or latest["protections"] != document["protections"]:
            raise ValueError("Speicherregeln während der Prüfung geändert; erneut planen.")
        if queue_check and queue_check():
            raise ValueError("Downloads inzwischen aktiv; Optimierung wird verschoben.")
        job = create_move_job(media_paths(), load_storage_locations(), **candidate,
                              destination_root=target["key"], autopilot_id=recommendation_id,
                              minimum_reserve_bytes=int(target_policy["reserve_gib"] * GIB))
        _attach_job(recommendation_id, job, automatic)
        return job


def _attach_job(recommendation_id: str, job: dict, automatic: bool):
    def update(document):
        recommendation = document["recommendations"].get(recommendation_id)
        if not recommendation or recommendation.get("job_id") == job["job_id"]:
            return
        recommendation.update(job_id=job["job_id"], state=job["status"])
        record_activity(document, "move_planned", source=job["source_path"], destination=job["destination_path"],
                        job_id=job["job_id"], automatic=automatic, reason=recommendation["reason"],
                        score=recommendation["score"], policy=document["policy"]["mode"],
                        before_percent=recommendation["before_percent"], after_percent=recommendation["after_percent"])
    transact(update)


def optimize_storage(*, queue_jobs: list[dict], playback_check, manual: bool = False, queue_check=None) -> dict:
    with _ACTION_LOCK:
        document = read_state()
        policy = document["policy"]
        if policy["mode"] in ("monitor", "advisor"):
            return {"started": False, "reason": "Nur Überwachung oder Beratung aktiv"}
        if not in_window(policy):
            return {"started": False, "reason": "Außerhalb des Zeitfensters"}
        if not manual and time.time() - document["last_optimization_at"] < policy["interval_hours"] * 3600:
            return {"started": False, "reason": "Optimierungs-Cooldown aktiv"}
        # A single serial runtime job per round is intentionally stricter than
        # max_moves; the configured count is an upper bound, never parallelism.
        for proposal in document["recommendations"].values():
            if proposal.get("state") != "available" or not proposal.get("automatic_eligible"):
                continue
            try:
                job = apply_recommendation(proposal["id"], queue_jobs=queue_jobs,
                                           playback_check=playback_check, automatic=True, queue_check=queue_check)
            except (OSError, ValueError) as exc:
                return {"started": False, "reason": str(exc)}
            transact(lambda state: state.update(last_optimization_at=time.time()))
            return {"started": True, "job": job}
        return {"started": False, "reason": "Keine sichere automatische Verschiebung erforderlich"}
