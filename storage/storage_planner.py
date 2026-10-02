"""Bounded pure balancing proposals; execution belongs to the existing runtime."""

from __future__ import annotations

from storage.storage_inventory import identity
from storage.storage_policy import GIB, volume_policy
from storage.storage_score import score_target, storage_pressure


def plan_recommendations(roots: list[dict], document: dict, *, now: float,
                         reserved: dict[str, int] | None = None) -> list[dict]:
    policy = document["policy"]
    if policy["mode"] == "monitor" or document.get("storage_error"):
        return []
    reserved = reserved or {}
    by_key = {root["key"]: root for root in roots}
    proposals = []
    for item in list(document["inventory"].values())[:10000]:
        source = by_key.get(item["root"])
        protection = document["protections"].get(item["id"], {})
        if not source or not source.get("available") or protection.get("no_move") or protection.get("keep_volume"):
            continue
        source_policy = volume_policy(source, document["volumes"])
        if source_policy["role"] == "monitor" or not source_policy["allow_moves_out"]:
            continue
        if now - item.get("last_moved_at", 0) < policy["cooldown_hours"] * 3600:
            continue
        pressure = storage_pressure(source, source_policy, reserved.get(source.get("volume_id"), 0))
        age = max(0, now - item.get("modified_at", now)) / 86400
        archive = (source_policy["role"] != "archive" and policy["mode"] in ("advisor", "full")
                   and age >= policy["archive_age_days"] and not protection.get("no_archive"))
        if pressure not in ("warning", "critical", "emergency") and not archive:
            continue
        size = int(item.get("size_bytes", 0))
        if size <= 0 or size > policy["max_move_gib"] * GIB:
            continue
        options = []
        for target in roots:
            if target.get("volume_id") == source.get("volume_id"):
                continue
            target_policy = volume_policy(target, document["volumes"])
            if not target_policy["allow_moves_in"]:
                continue
            if archive and pressure == "normal" and target_policy["role"] != "archive":
                continue
            if target_policy["role"] == "archive" and (protection.get("no_archive") or not archive):
                continue
            scored = score_target(target, target_policy, media_type=item["media_type"], size=size,
                                  reserved=reserved.get(target.get("volume_id"), 0), overflow=True)
            if scored["eligible"] and scored["expected_percent"] <= target_policy["target_percent"]:
                options.append(scored)
        if not options:
            continue
        best = max(options, key=lambda option: (option["score"], option["root"]))
        proposal_id = identity(item["id"], best["root"])
        old = document["recommendations"].get(proposal_id, {})
        if old.get("dismissed_until", 0) > now or old.get("job_id"):
            continue
        reserved_bytes = reserved.get(source.get("volume_id"), 0)
        total_bytes = max(1, int(source.get("total_bytes", 0)))
        physical_percent = float(source.get("used_percent", 0))
        projected_percent = round(100 * (total_bytes - int(source.get("free_bytes", 0)) + reserved_bytes) / total_bytes, 2)
        proposals.append({
            "id": proposal_id, "item_id": item["id"], "name": item["name"],
            "source_root": item["root"], "destination_root": best["root"],
            "size_bytes": size, "score": best["score"], "reasons": best["reasons"],
            "reason": "Bibliotheksalter: Archiv geeignet" if archive and pressure == "normal" else "Geplante Speicherlast oberhalb der Warnschwelle",
            "before_percent": physical_percent,
            "after_percent": round(max(0, physical_percent - 100 * size / total_bytes), 2),
            "reserved_bytes": reserved_bytes,
            "projected_percent": projected_percent,
            "projected_after_percent": round(projected_percent - 100 * size / total_bytes, 2),
            "safe_remaining_bytes": max(0, int(source.get("free_bytes", 0)) - reserved_bytes - int(source_policy["reserve_gib"] * GIB)),
            "expected_target_percent": best["expected_percent"],
            "automatic_eligible": bool(item.get("owned") or item.get("owned_files")),
            "created_at": now, "state": "available", "archive": archive,
        })
    # Rank all bounded inventory candidates before truncation. A scan-order
    # cutoff could otherwise hide the moves that actually relieve the most GB.
    return sorted(proposals, key=lambda proposal: (-proposal["size_bytes"], -proposal["projected_percent"], proposal["id"]))[:80]
