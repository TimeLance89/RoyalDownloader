"""Atomic download placement and physical-filesystem reservation accounting."""

from __future__ import annotations

import os
import time
from pathlib import Path
from statistics import median

from storage.storage_inventory import record_activity, transact
from storage.storage_policy import GIB, volume_policy
from storage.storage_score import score_target

# Pending work is demand, not space already committed on its original volume.
# Reserve only the next scheduling window; each job gets a fresh, atomic
# reservation when it actually starts. Active work is always counted in full.
QUEUE_LOOKAHEAD = 32
ACTIVE_STATUSES = frozenset(("preparing", "downloading"))
FINISHED_STATUSES = frozenset(("completed", "failed", "cancelled"))


def _media_key(job: dict) -> str:
    return "movie" if job.get("media_type") in ("movie", "movies") else "series"


def _pending_estimates(policy: dict, jobs: list[dict]) -> dict[str, int]:
    """Use a cautious per-type median when providers supplied known sizes."""
    fallback = int(policy["unknown_download_gib"] * GIB)
    known = {"movie": [], "series": []}
    for job in jobs:
        size = int(job.get("total_bytes") or 0)
        if size > 0:
            known[_media_key(job)].append(size)
    estimates = {}
    for media, sizes in known.items():
        baseline = fallback if media == "movie" else min(fallback, 2 * GIB)
        minimum = 2 * GIB if media == "movie" else GIB // 2
        estimates[media] = max(minimum, int(median(sizes) * 1.5) if sizes else baseline)
    return estimates


def advise_queued_downloads(document: dict, roots: list[dict], queue_jobs: list[dict], move_jobs: list[dict]) -> list[dict]:
    """Explain targets for known pending paths without changing queue entries."""
    if document["policy"]["mode"] != "advisor":
        return []
    advice = []
    for job in queue_jobs[:20]:
        if job.get("status") not in ("queued", "preparing", "waiting_provider", "paused") or not job.get("final_path"):
            continue
        media = "movies" if job.get("media_type") == "movie" else "anime" if job.get("media_type") == "anime" else "series"
        size = int(job.get("total_bytes") or document["policy"]["unknown_download_gib"] * GIB)
        budgets = reserved_by_volume(document, roots, queue_jobs, move_jobs, exclude=job["job_id"])
        try:
            result = choose_destination(document, roots, original=Path(job["final_path"]), media_type=media,
                                        size=size, reserved=budgets)
        except ValueError:
            continue
        if result["root"] != result["original_root"]:
            advice.append({"job_id": job["job_id"], "name": job.get("title") or "Geplanter Download",
                           "destination_root": result["root"], "score": result["score"],
                           "reasons": result["reasons"], "size_bytes": size})
    return advice


def reserved_by_volume(document: dict, roots: list[dict], queue_jobs: list[dict],
                       move_jobs: list[dict], *, exclude: str = "") -> dict[str, int]:
    by_key = {root["key"]: root for root in roots}
    budgets = {}
    accounted = set()
    def add(key, size):
        volume = by_key.get(key, {}).get("volume_id")
        if volume:
            budgets[volume] = budgets.get(volume, 0) + max(0, int(size))
    for job_id, reservation in document["reservations"].items():
        if job_id != exclude:
            add(reservation["root"], reservation["size_bytes"])
        accounted.add(job_id)
    fallback = int(document["policy"]["unknown_download_gib"] * GIB)
    estimates = _pending_estimates(document["policy"], queue_jobs)
    pending_count = 0
    for job in queue_jobs:
        status = job.get("status")
        if job.get("job_id") in accounted or job.get("job_id") == exclude or status in FINISHED_STATUSES:
            continue
        if status not in ACTIVE_STATUSES:
            if pending_count >= QUEUE_LOOKAHEAD:
                continue
            pending_count += 1
        root_key = "movies" if _media_key(job) == "movie" else "series"
        if job.get("final_path"):
            matches = []
            for root in roots:
                try:
                    Path(job["final_path"]).absolute().relative_to(Path(root.get("resolved_path") or root["path"]))
                    matches.append(root)
                except ValueError:
                    continue
            if matches:
                root_key = max(matches, key=lambda root: (len(Path(root["path"]).parts), root["key"] == root_key))["key"]
        unknown = fallback if status in ACTIVE_STATUSES else estimates[_media_key(job)]
        add(root_key, max(0, int(job.get("total_bytes") or unknown) - int(job.get("downloaded_bytes") or 0)))
        accounted.add(job.get("job_id"))
    for move in move_jobs:
        add(move.get("destination_root"), int(move.get("size_bytes") or 0))
    return budgets


def choose_destination(document: dict, roots: list[dict], *, original: Path,
                       media_type: str, size: int, reserved: dict[str, int],
                       series_name: str = "") -> dict:
    original = original.absolute()
    sources = []
    for root in roots:
        path = Path(root.get("resolved_path") or root["path"])
        try:
            relative = original.relative_to(path)
        except ValueError:
            continue
        sources.append((len(path.parts), root, relative))
    if not sources:
        raise ValueError("Downloadziel liegt außerhalb verfügbarer registrierter Medienpfade.")
    _, source, relative = max(sources, key=lambda item: (item[0], item[1]["key"] == ("movies" if media_type == "movies" else "series")))
    if not relative.parts or ".." in relative.parts:
        raise ValueError("Ungültiges Downloadziel.")
    affinity_volumes = set()
    affinity_roots = set()
    for item in document["inventory"].values():
        if series_name and item.get("series_name") == series_name:
            known = next((root for root in roots if root["key"] == item["root"] and root.get("available")), None)
            if known:
                affinity_volumes.add(known.get("volume_id"))
                affinity_roots.add(known["key"])
    overflow = any(
        root.get("available") and volume_policy(root, document["volumes"])["role"] == "primary"
        and media_type in volume_policy(root, document["volumes"])["media_types"]
        and float(root.get("used_percent", 100)) >= volume_policy(root, document["volumes"])["target_percent"]
        for root in roots
    )
    scores = []
    for root in roots:
        policy = volume_policy(root, document["volumes"])
        score = score_target(root, policy, media_type=media_type, size=size,
                             reserved=reserved.get(root.get("volume_id"), 0),
                             affinity=root.get("volume_id") in affinity_volumes, overflow=overflow,
                             busy=int(root.get("active_jobs", 0)))
        if policy["role"] == "archive":
            score.update(eligible=False, score=None, reasons=["Archiv ist für ältere Inhalte vorgesehen"])
        if score["eligible"]:
            path = Path(root.get("resolved_path") or root["path"])
            target = path / relative
            if target.exists() or target.is_symlink() or any(part.is_symlink() for part in target.parents if part != path):
                score.update(eligible=False, score=None, reasons=["Ziel bereits belegt oder symbolischer Link"])
            else:
                score["path"] = str(target)
        scores.append(score)
    eligible = [score for score in scores if score["eligible"]]
    if affinity_roots and not document["policy"]["allow_series_split"]:
        together = [score for score in eligible if score["root"] in affinity_roots]
        # Split only when the existing root fails a hard safety condition.
        if together:
            eligible = together
    if not eligible:
        raise ValueError("Kein sicheres Medien-Volume mit ausreichender Reserve verfügbar.")
    best = max(eligible, key=lambda score: (score["score"], score["root"] == source["key"], score["root"]))
    return {**best, "alternatives": scores, "original_root": source["key"], "series_name": series_name}


def reserve_download(job_id: str, original: Path, media_type: str, roots: list[dict],
                     queue_jobs: list[dict], move_jobs: list[dict], *, size: int = 0) -> dict:
    if not job_id or len(job_id) > 128:
        raise ValueError("Ungültige Downloadidentität.")
    def update(document):
        if document["policy"]["mode"] not in ("automatic", "full"):
            return {"path": str(original), "changed": False}
        requested = max(size, int(document["policy"]["unknown_download_gib"] * GIB)) if size <= 0 else size
        previous = document["reservations"].get(job_id)
        if previous:
            # Retry reuses its logical reservation; new size still rechecks safety.
            original_path = Path(previous["path"])
        else:
            original_path = original
        series_name = ""
        if media_type in ("series", "anime"):
            for root in roots:
                try:
                    relative = original_path.relative_to(Path(root.get("resolved_path") or root["path"]))
                    if len(relative.parts) > 1:
                        series_name = relative.parts[0]
                        break
                except ValueError:
                    pass
        budgets = reserved_by_volume(document, roots, queue_jobs, move_jobs, exclude=job_id)
        if series_name and any(move.get("source_name") == series_name for move in move_jobs):
            raise ValueError("Diese Serie wird gerade sicher verschoben; Download vorübergehend zurückstellen.")
        result = choose_destination(document, roots, original=original_path, media_type=media_type,
                                    size=requested, reserved=budgets, series_name=series_name)
        root = next(root for root in roots if root["key"] == result["root"])
        reservation = {"root": result["root"], "volume_id": root["volume_id"],
                       "path": result["path"], "size_bytes": requested,
                       "series_name": series_name, "media_type": media_type,
                       "created_at": previous.get("created_at", time.time()) if previous else time.time()}
        document["reservations"][job_id] = reservation
        if not previous or previous["path"] != result["path"]:
            record_activity(document, "placement", job_id=job_id, source=str(original),
                            destination=result["path"], reasons=result["reasons"], score=result["score"],
                            policy=document["policy"]["mode"], expected_percent=result["expected_percent"])
        return {**result, "changed": os.path.normcase(str(original)) != os.path.normcase(result["path"])}
    return transact(update)
