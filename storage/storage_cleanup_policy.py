"""Independent opt-in permission for narrowly recognized Royal staging artifacts."""

from pathlib import Path

from media.downloader import STAGING_DIR, cleanup_stale_staging
from storage.storage_autopilot import get_autopilot
from storage.storage_inventory import read_state, record_activity, transact


def cleanup_context(queue_jobs: list[dict]) -> dict:
    current = get_autopilot(queue_jobs=queue_jobs)
    document = read_state()
    roots = {root["key"]: Path(root.get("resolved_path") or root["path"])
             for root in current["roots"] if root.get("available") and root["location_mode"] == "media"}
    staging = {STAGING_DIR, *(root / ".downloading" for root in roots.values())}
    # Known inventory parents, not recursive NAS enumeration.
    for item in list(document["inventory"].values())[:10000]:
        root = roots.get(item["root"])
        if root is None:
            continue
        for relative in list(item.get("owned_files", {}))[:2000]:
            path = root / relative
            if path.is_absolute() and root in path.parents and ".." not in Path(relative).parts:
                staging.add(path.parent / ".downloading")
            if len(staging) >= 256:
                break
        if len(staging) >= 256:
            break
    return {"staging_roots": sorted(staging), "protected_attempts": {
        job.get("attempt_id") for job in queue_jobs if job.get("attempt_id")
    }, "strict": True, "max_items": 100, "older_than_seconds": 7 * 86400}


def preview_cleanup(queue_jobs: list[dict]) -> dict:
    candidates = cleanup_stale_staging(**cleanup_context(queue_jobs), preview=True)
    return {"categories": ["royal_partials"], "candidates": candidates,
            "size_bytes": sum(item["size_bytes"] for item in candidates),
            "description": "Nur eindeutig markierte, seit mindestens sieben Tagen verwaiste Royal-Transfers. Keine Medien, fremden Dateien oder Backups."}


def run_cleanup(queue_jobs: list[dict]) -> dict:
    policy = read_state()["policy"]
    if policy["mode"] not in ("automatic", "full") or not policy["auto_delete"] or "royal_partials" not in policy["delete_categories"]:
        return {"removed": 0}
    if queue_jobs:
        return {"removed": 0, "reason": "Queue aktiv"}
    removed = cleanup_stale_staging(**cleanup_context(queue_jobs))
    if removed:
        transact(lambda document: record_activity(document, "artifacts_cleaned", removed=removed,
                                                 category="royal_partials", policy=policy["mode"]))
    return {"removed": removed}
