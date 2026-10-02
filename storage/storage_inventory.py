"""Bounded persistent storage inventory, reservations and audit journal.

Inventory metadata is not a filesystem scan and never proves ownership by size.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from copy import deepcopy
from pathlib import Path

import core.config as appconfig
from storage.storage_policy import DEFAULT_POLICY, validate_policy, validate_volume

_LOCK = threading.RLock()
LIMITS = {"inventory": 10000, "activity": 300, "recommendations": 80,
          "protections": 10000, "volumes": 24, "observations": 24}
MAX_STATE_BYTES = 8 * 1024 * 1024


def identity(root: str, relative: str) -> str:
    return hashlib.sha256(f"{root}\n{relative}".encode()).hexdigest()[:32]


def state_path() -> Path:
    return appconfig.sessions_file().with_name("storage_autopilot.json")


def _empty() -> dict:
    return {"schema_version": 1, "policy": deepcopy(DEFAULT_POLICY), "reservations": {},
            **{key: ([] if key == "activity" else {}) for key in LIMITS},
            "last_optimization_at": 0, "last_scan_at": 0}


def read_state() -> dict:
    with _LOCK:
        try:
            if state_path().stat().st_size > MAX_STATE_BYTES:
                raise ValueError("Storage state exceeds NAS budget")
            raw = json.loads(state_path().read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                raise ValueError("Unsupported storage state")
            result = _empty()
            result.update(raw)
            result["policy"] = validate_policy(result["policy"])
            for key, limit in LIMITS.items():
                if not isinstance(result[key], list if key == "activity" else dict) or len(result[key]) > limit:
                    raise ValueError("Invalid storage state")
            # Reservations exist only for in-flight jobs and are bounded by the
            # serialized state budget, not by the length of the waiting queue.
            if not isinstance(result["reservations"], dict):
                raise TypeError("Invalid storage state")
            result["volumes"] = {key: validate_volume(value) for key, value in result["volumes"].items()}
            for key in ("inventory", "reservations", "recommendations", "observations", "protections"):
                if any(not isinstance(value, dict) for value in result[key].values()):
                    raise ValueError("Invalid storage entry")
            for item in result["inventory"].values():
                if not all(isinstance(item.get(key), str) and item[key] for key in ("id", "root", "relative_path", "name")):
                    raise ValueError("Invalid inventory identity")
                relative = Path(item["relative_path"])
                if relative.is_absolute() or relative.drive or ".." in relative.parts or item.get("media_type") not in ("movies", "series", "anime"):
                    raise ValueError("Invalid inventory path")
                if not isinstance(item.get("owned", False), bool):
                    raise ValueError("Invalid ownership")
                files = item.get("owned_files", {})
                stamps = item.get("owned_stamps", {})
                if not isinstance(files, dict) or len(files) > 2000 or not isinstance(stamps, dict) or len(stamps) > 2000:
                    raise ValueError("Invalid ownership evidence")
                for value in [item.get("size_bytes", 0), item.get("modified_at", 0), item.get("last_moved_at", 0), *files.values()]:
                    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                        raise ValueError("Invalid inventory measurement")
            for reservation in result["reservations"].values():
                if not isinstance(reservation.get("root"), str) or not isinstance(reservation.get("size_bytes"), (int, float)) or reservation["size_bytes"] < 0 or not math.isfinite(reservation["size_bytes"]):
                    raise ValueError("Invalid storage reservation")
            if any(not isinstance(entry, dict) or not isinstance(entry.get("action"), str) for entry in result["activity"]):
                raise ValueError("Invalid activity")
            return result
        except FileNotFoundError:
            return _empty()
        except (OSError, ValueError, TypeError):
            return {**_empty(), "storage_error": True}


def transact(change):
    with _LOCK:
        document = read_state()
        if document.get("storage_error"):
            raise ValueError("Autopilot-Daten nicht lesbar; automatische Aktionen sind gesperrt.")
        result = change(document)
        for key, limit in LIMITS.items():
            if len(document[key]) > limit:
                raise ValueError("Speicherverwaltung hat ihr sicheres Eintragslimit erreicht.")
        payload = json.dumps(document, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > MAX_STATE_BYTES:
            raise ValueError("Speicherverwaltung hat ihr sicheres Datenbudget erreicht.")
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            os.replace(temporary, path)
            try:
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
        return deepcopy(result)


def record_activity(document: dict, action: str, **details) -> dict:
    entry = {"action": action, "timestamp": time.time(), **details}
    document["activity"].insert(0, entry)
    del document["activity"][LIMITS["activity"]:]
    return entry


def observe_scan(candidates: list[dict]) -> None:
    def update(document):
        for candidate in candidates[:80]:
            key = identity(candidate["root"], candidate["relative_path"])
            previous = document["inventory"].get(key, {})
            if key not in document["inventory"] and len(document["inventory"]) >= LIMITS["inventory"]:
                break
            document["inventory"][key] = {
                **previous, "id": key, "root": candidate["root"],
                "relative_path": candidate["relative_path"], "name": candidate["name"],
                "media_type": previous.get("media_type") or ("series" if candidate["kind"] in ("series", "directory") else "movies"),
                "series_name": previous.get("series_name") or (candidate["name"] if candidate["kind"] in ("series", "directory") else ""),
                "size_bytes": candidate["size_bytes"], "modified_at": candidate.get("modified_at", time.time()),
                "verified_at": time.time(), "owned": bool(previous.get("owned")),
            }
        document["last_scan_at"] = time.time()
    transact(update)


def protect_item(item_id: str, protection: dict) -> dict:
    allowed = {"no_move", "no_archive", "no_delete", "keep_volume"}
    if set(protection) - allowed or any(not isinstance(value, bool) for value in protection.values()):
        raise ValueError("Ungültiger Inhaltsschutz.")
    def update(document):
        if item_id not in document["inventory"]:
            raise ValueError("Inhalt ist nicht im Speicherinventar vorhanden.")
        document["protections"][item_id] = {**document["protections"].get(item_id, {}), **protection}
        return document["protections"][item_id]
    return transact(update)


def record_cleanup(result: dict) -> None:
    if not result.get("deleted") or not result.get("relative_path"):
        return
    def update(document):
        relative = result["relative_path"]
        removed = {key for key, item in document["inventory"].items() if item["root"] == result["root"]
                   and (item["relative_path"] == relative or item["relative_path"].startswith(relative + "/"))}
        for key in removed:
            document["inventory"].pop(key, None)
            document["protections"].pop(key, None)
        document["recommendations"] = {key: item for key, item in document["recommendations"].items()
                                       if item.get("item_id") not in removed or item.get("job_id")}
        record_activity(document, "manual_cleanup", root=result["root"], relative_path=relative,
                        freed_bytes=result.get("freed_bytes", 0))
    transact(update)


def record_move_completion(job: dict) -> None:
    def update(document):
        if any(entry.get("job_id") == job["job_id"] and entry["action"] == "move_finished" for entry in document["activity"]):
            return
        if job["status"] == "completed":
            for old_id, item in list(document["inventory"].items()):
                if item["root"] != job["source_root"] or item["relative_path"] != Path(job["source_path"]).name:
                    continue
                del document["inventory"][old_id]
                item.update(root=job["destination_root"], relative_path=Path(job["destination_path"]).name,
                            size_bytes=job["moved_bytes"], verified_at=time.time(), last_moved_at=time.time())
                item["id"] = identity(item["root"], item["relative_path"])
                # Refresh only known published files after the verified move;
                # do not turn a move event into a recursive library scan.
                target = Path(job["destination_path"])
                stamps = {}
                for relative in item.get("owned_files", {}):
                    path = target.parent / relative
                    try:
                        stat = path.stat(follow_symlinks=False)
                        if not path.is_symlink() and path.is_file():
                            stamps[relative] = [stat.st_mtime_ns, stat.st_ino]
                    except OSError:
                        pass
                item["owned_stamps"] = stamps
                document["inventory"][item["id"]] = item
                protection = document["protections"].pop(old_id, None)
                if protection:
                    document["protections"][item["id"]] = protection
        for recommendation in document["recommendations"].values():
            if recommendation.get("job_id") == job["job_id"] or recommendation["id"] == job.get("autopilot_id"):
                recommendation.update(job_id=job["job_id"], state=job["status"])
        record_activity(document, "move_finished", job_id=job["job_id"], result=job["status"],
                        source=job["source_path"], destination=job["destination_path"])
    transact(update)
