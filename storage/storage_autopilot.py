"""Storage policy facade; lightweight telemetry never starts a recursive scan."""

from __future__ import annotations

import os
import time
from pathlib import Path

import core.config as appconfig
from storage.storage_inventory import identity, read_state, record_activity, transact
from storage.storage_locations import combined_storage_status, load_storage_locations
from storage.storage_move_runtime import list_move_jobs
from storage.storage_placement import advise_queued_downloads, reserved_by_volume
from storage.storage_planner import plan_recommendations
from storage.storage_policy import GIB, validate_policy, validate_volume, volume_policy
from storage.storage_score import score_target, storage_pressure


def media_paths() -> dict:
    movies = str(appconfig.load() or "")
    return {"movies": movies, "series": str(appconfig.load_series_path() or movies)}


def storage_snapshot() -> dict:
    result = combined_storage_status(media_paths(), appconfig.load_deployment_mode(), load_storage_locations())
    for root in result["roots"]:
        path = Path(root.get("path") or ".")
        root["writable"] = bool(root.get("available") and os.access(path, os.W_OK)
                                and not any(part.is_symlink() for part in (path, *path.parents)))
    return result


def get_autopilot(*, queue_jobs: list[dict] | None = None) -> dict:
    snapshot = storage_snapshot()
    document = read_state()
    jobs = list_move_jobs()
    for root in snapshot["roots"]:
        observation = document["observations"].get(root["key"], {})
        if observation.get("volume_id") and root.get("volume_id") != observation["volume_id"]:
            root["available"] = root["writable"] = False
            root["error"] = "Datenträgeridentität geändert; Mount prüfen und erneut bestätigen."
    budgets = reserved_by_volume(document, snapshot["roots"], queue_jobs or [], jobs["jobs"])
    statuses = []
    physical = {}
    for root in snapshot["roots"]:
        if not root.get("available") or root["location_mode"] != "media":
            continue
        policy = volume_policy(root, document["volumes"])
        shared = physical.setdefault(root["volume_id"], dict(policy))
        shared["reserve_gib"] = max(shared["reserve_gib"], policy["reserve_gib"])
        for key in ("target_percent", "warning_percent", "critical_percent"):
            shared[key] = min(shared[key], policy[key])
    for root in snapshot["roots"]:
        shared = physical.get(root.get("volume_id"), {})
        root["_physical_policy"] = {key: shared[key] for key in ("reserve_gib", "target_percent", "warning_percent", "critical_percent") if key in shared}
        policy = volume_policy(root, document["volumes"])
        observation = document["observations"].get(root["key"], {})
        # A surviving empty mount directory must not silently become a target
        # on the host/container filesystem after the original disk disappears.
        if observation.get("volume_id") and root.get("volume_id") != observation["volume_id"]:
            root["available"] = root["writable"] = False
            root["error"] = "Datenträgeridentität geändert; Mount prüfen und erneut bestätigen."
        reserved = budgets.get(root.get("volume_id"), 0)
        active_jobs = sum(1 for job in queue_jobs or [] if job.get("status") not in ("completed", "failed", "cancelled")
                          and job.get("final_path") and Path(root["path"]) in Path(job["final_path"]).parents)
        active_jobs += sum(1 for job in jobs["jobs"] if root["key"] in (job.get("source_root"), job.get("destination_root")))
        total_bytes = int(root.get("total_bytes") or 0)
        free_bytes = int(root.get("free_bytes") or 0)
        projected_free = free_bytes - reserved
        statuses.append({**root, "policy": policy, "reserved_bytes": reserved,
                         "projected_used_percent": round(100 * (total_bytes - projected_free) / total_bytes, 2) if total_bytes else 0,
                         "safe_remaining_bytes": max(0, projected_free - int(policy["reserve_gib"] * GIB)),
                         "active_jobs": active_jobs,
                         "pressure": storage_pressure(root, policy, reserved),
                         "last_seen_at": observation.get("last_seen_at", 0)})
    pressure_order = {"normal": 0, "offline": 1, "warning": 2, "critical": 3, "emergency": 4}
    worst = max((root["pressure"] for root in statuses if root["policy"]["role"] != "monitor"),
                key=lambda state: pressure_order[state], default="normal")
    automatic = document["policy"]["mode"] in ("automatic", "full")
    eligible_media = []
    for media in ("movies", "series", "anime"):
        candidates = (root for root in statuses if automatic or root["key"] == ("movies" if media == "movies" else "series"))
        if any(root["policy"]["role"] != "archive" and score_target(
            root, root["policy"], media_type=media,
            size=int(document["policy"]["unknown_download_gib"] * GIB),
            reserved=budgets.get(root.get("volume_id"), 0),
        )["eligible"] for root in candidates):
            eligible_media.append(media)
    if not eligible_media:
        pressure = "emergency"
    elif len(eligible_media) < 3:
        pressure = "limited"
    elif worst in ("emergency", "critical"):
        pressure = "diverted" if automatic else "warning"
    else:
        pressure = worst
    volumes = {root["volume_id"]: root for root in statuses if root.get("available") and root.get("volume_id")}
    total = sum(root.get("total_bytes", 0) for root in volumes.values())
    free = sum(root.get("free_bytes", 0) for root in volumes.values())
    summary = {"volume_count": len(volumes), "total_bytes": total, "free_bytes": free,
               "used_bytes": total - free, "used_percent": round(100 * (total - free) / total, 2) if total else 0,
               "reserved_bytes": sum(budgets.get(volume, 0) for volume in volumes),
               "projected_used_percent": round(100 * (total - free + sum(budgets.get(volume, 0) for volume in volumes)) / total, 2) if total else 0}
    return {"policy": document["policy"], "roots": statuses, "summary": summary,
            "pressure": pressure, "eligible_media_types": eligible_media,
            "queue_busy": bool(queue_jobs), "queue_job_count": len(queue_jobs or []),
            "storage_error": bool(document.get("storage_error")),
            "recommendations": list(document["recommendations"].values()),
            "placement_advice": advise_queued_downloads(document, statuses, queue_jobs or [], jobs["jobs"]),
            "activity": document["activity"][:100], "last_optimization_at": document["last_optimization_at"],
            "active_moves": jobs["active_count"], "last_scan_at": document["last_scan_at"]}


def observe_volumes() -> None:
    snapshot = storage_snapshot()
    now = time.time()
    def update(document):
        keys = {root["key"] for root in snapshot["roots"]}
        document["observations"] = {key: value for key, value in document["observations"].items() if key in keys}
        document["volumes"] = {key: value for key, value in document["volumes"].items() if key in keys}
        for root in snapshot["roots"]:
            if not root.get("available"):
                continue
            previous = document["observations"].get(root["key"], {})
            if previous.get("volume_id") and previous["volume_id"] != root.get("volume_id"):
                continue
            document["observations"][root["key"]] = {
                "volume_id": root["volume_id"], "last_seen_at": now,
            }
    transact(update)


def save_policy(changes: dict, *, delete_confirmed: bool = False) -> dict:
    def update(document):
        policy = validate_policy(changes, document["policy"])
        if policy["auto_delete"] and (
            not document["policy"]["auto_delete"] or policy["delete_categories"] != document["policy"]["delete_categories"]
        ) and not delete_confirmed:
            raise ValueError("Automatische Bereinigung erfordert eine bestätigte Vorschau.")
        document["policy"] = policy
        if policy["mode"] == "monitor":
            document["recommendations"] = {key: item for key, item in document["recommendations"].items() if item.get("job_id")}
        record_activity(document, "policy_changed", policy=policy)
        return policy
    return transact(update)


def save_volume(root_key: str, changes: dict, *, confirm_mount: bool = False) -> dict:
    snapshot = storage_snapshot()
    root = next((root for root in snapshot["roots"] if root["key"] == root_key), None)
    if root is None:
        raise ValueError("Speicherort ist nicht registriert.")
    def update(document):
        policy = validate_volume(changes, volume_policy(root, document["volumes"]))
        if root["location_mode"] == "monitor" and policy["role"] != "monitor":
            raise ValueError("Nur-überwachen-Speicherort muss zuerst ausdrücklich als Medienpfad freigegeben werden.")
        document["volumes"][root_key] = policy
        if confirm_mount:
            if not root.get("available"):
                raise ValueError("Offline-Volume kann nicht bestätigt werden.")
            document["observations"][root_key] = {"volume_id": root["volume_id"], "last_seen_at": time.time()}
        record_activity(document, "volume_policy_changed", root=root_key, policy=policy)
        return policy
    return transact(update)


def refresh_recommendations(queue_jobs: list[dict] | None = None) -> list[dict]:
    current = get_autopilot(queue_jobs=queue_jobs)
    moves = list_move_jobs()
    now = time.time()
    def update(document):
        _reconcile_moves(document, moves, now)
        budgets = reserved_by_volume(document, current["roots"], queue_jobs or [], moves["jobs"])
        proposals = plan_recommendations(current["roots"], document, now=now, reserved=budgets)
        retained = {key: item for key, item in document["recommendations"].items()
                    if item.get("job_id") and item.get("state") not in ("completed", "failed")
                    or item.get("dismissed_until", 0) > now}
        for proposal in proposals:
            if len(retained) >= 80:
                break
            retained[proposal["id"]] = proposal
        document["recommendations"] = retained
        return list(retained.values())
    return transact(update)


def _reconcile_moves(document: dict, moves: dict, now: float) -> None:
    history = {job["job_id"]: job for job in moves["history"]}
    active = {job["job_id"] for job in moves["jobs"]}
    for recommendation in list(document["recommendations"].values()):
        job_id = recommendation.get("job_id")
        if not job_id or job_id in active or recommendation.get("state") in ("completed", "failed"):
            continue
        job = history.get(job_id)
        if not job:
            continue
        recommendation["state"] = job["status"]
        if job["status"] == "completed":
            old_id = recommendation["item_id"]
            item = document["inventory"].pop(old_id, None)
            if item:
                item.update(root=job["destination_root"], relative_path=Path(job["destination_path"]).name,
                            size_bytes=job["moved_bytes"], verified_at=now, last_moved_at=now)
                item["id"] = identity(item["root"], item["relative_path"])
                document["inventory"][item["id"]] = item
                protection = document["protections"].pop(old_id, None)
                if protection:
                    document["protections"][item["id"]] = protection
        record_activity(document, "move_finished", job_id=job_id, result=job["status"],
                        source=job["source_path"], destination=job["destination_path"])


def dismiss_recommendation(recommendation_id: str) -> None:
    def update(document):
        recommendation = document["recommendations"].get(recommendation_id)
        if not recommendation or recommendation.get("job_id"):
            raise ValueError("Empfehlung nicht verfügbar.")
        recommendation.update(state="dismissed", dismissed_until=time.time() + document["policy"]["cooldown_hours"] * 3600)
        record_activity(document, "recommendation_dismissed", recommendation_id=recommendation_id)
    transact(update)
