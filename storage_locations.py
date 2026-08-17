"""Persisted multi-volume storage registry and safe scan/cleanup adapters."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import config as appconfig
from storage_manager import cleanup_candidate, scan_large_content, storage_status

MAX_STORAGE_LOCATIONS = 12
LOCATION_MODE_MONITOR = "monitor"
LOCATION_MODE_MEDIA = "media"
LOCATION_MODES = {LOCATION_MODE_MONITOR, LOCATION_MODE_MEDIA}
_STORAGE_FILE_NAME = "storage_locations.json"
_storage_lock = threading.RLock()


def _storage_file() -> Path:
    # sessions_file() is the public config-root seam and therefore keeps this
    # registry on the same persistent data volume in desktop and NAS mode.
    return appconfig.sessions_file().with_name(_STORAGE_FILE_NAME)


def _normalize_path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(str(value or "").strip()))


def _normalize_location(raw: dict, *, require_id: bool = True) -> dict | None:
    if not isinstance(raw, dict):
        return None
    location_id = str(raw.get("id") or "").strip().lower()
    label = str(raw.get("label") or "").strip()
    path = str(raw.get("path") or "").strip()
    mode = str(raw.get("mode") or LOCATION_MODE_MONITOR).strip().casefold()
    if require_id and (not location_id or len(location_id) > 64):
        return None
    if not label or len(label) > 80 or any(ch in label for ch in "\r\n\x00"):
        return None
    if not path or len(path) > 2048 or any(ch in path for ch in "\r\n\x00"):
        return None
    if mode not in LOCATION_MODES:
        mode = LOCATION_MODE_MONITOR
    return {
        "id": location_id,
        "label": label,
        "path": path,
        "mode": mode,
    }


def load_storage_locations() -> list[dict]:
    path = _storage_file()
    with _storage_lock:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError):
            return []
    if not isinstance(payload, list):
        return []
    result: list[dict] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for raw in payload:
        location = _normalize_location(raw)
        if not location:
            continue
        path_key = _normalize_path_key(location["path"])
        if location["id"] in seen_ids or path_key in seen_paths:
            continue
        seen_ids.add(location["id"])
        seen_paths.add(path_key)
        result.append(location)
        if len(result) >= MAX_STORAGE_LOCATIONS:
            break
    return result


def _write_storage_locations(locations: list[dict]) -> None:
    path = _storage_file()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with _storage_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(locations, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            try:
                path.chmod(0o600)
            except OSError:
                pass
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise


def save_storage_location(
    *,
    label: str,
    path: str,
    mode: str = LOCATION_MODE_MONITOR,
    location_id: str = "",
) -> dict:
    normalized = _normalize_location({
        "id": location_id or uuid.uuid4().hex,
        "label": label,
        "path": path,
        "mode": mode,
    })
    if not normalized:
        raise ValueError("Ungültiger Speicherort.")

    locations = load_storage_locations()
    requested_id = str(location_id or "").strip().lower()
    existing_index = next(
        (index for index, item in enumerate(locations) if item["id"] == requested_id),
        None,
    ) if requested_id else None
    if requested_id and existing_index is None:
        raise ValueError("Der Speicherort existiert nicht mehr.")
    if existing_index is None and len(locations) >= MAX_STORAGE_LOCATIONS:
        raise ValueError(f"Es können maximal {MAX_STORAGE_LOCATIONS} Speicherorte verwaltet werden.")

    path_key = _normalize_path_key(normalized["path"])
    for item in locations:
        if item["id"] == normalized["id"]:
            continue
        if _normalize_path_key(item["path"]) == path_key:
            raise ValueError("Dieser Speicherpfad ist bereits eingetragen.")

    if existing_index is None:
        locations.append(normalized)
    else:
        locations[existing_index] = normalized
    _write_storage_locations(locations)
    return normalized


def remove_storage_location(location_id: str) -> bool:
    normalized_id = str(location_id or "").strip().lower()
    if not normalized_id:
        return False
    locations = load_storage_locations()
    remaining = [item for item in locations if item["id"] != normalized_id]
    if len(remaining) == len(locations):
        return False
    _write_storage_locations(remaining)
    return True


def _custom_root_key(location_id: str) -> str:
    return f"location:{location_id}"


def _status_root_for_location(location: dict, deployment_mode: str) -> dict:
    payload = storage_status(
        {"movies": location["path"], "series": ""},
        deployment_mode,
    )
    source = dict(payload["roots"][0])
    source.update({
        "key": _custom_root_key(location["id"]),
        "label": location["label"],
        "path": location["path"],
        "source": "custom",
        "location_id": location["id"],
        "location_mode": location["mode"],
    })
    return source


def combined_storage_status(
    media_paths: dict[str, str],
    deployment_mode: str,
    locations: list[dict] | None = None,
) -> dict:
    """Return one live card per physical filesystem across all configured roots."""
    normalized_locations = list(locations if locations is not None else load_storage_locations())
    base = storage_status(media_paths, deployment_mode)
    roots: list[dict] = []
    for root in base.get("roots", []):
        item = dict(root)
        item.update({
            "source": "media",
            "location_id": "",
            "location_mode": LOCATION_MODE_MEDIA,
        })
        roots.append(item)
    for location in normalized_locations:
        roots.append(_status_root_for_location(location, deployment_mode))

    volume_by_id: dict[str, dict] = {}
    for root in roots:
        if not root.get("available") or not root.get("volume_id"):
            continue
        volume_id = str(root["volume_id"])
        volume = volume_by_id.setdefault(volume_id, {
            "id": volume_id,
            "total_bytes": int(root.get("total_bytes") or 0),
            "used_bytes": int(root.get("used_bytes") or 0),
            "free_bytes": int(root.get("free_bytes") or 0),
            "used_percent": float(root.get("used_percent") or 0.0),
            "measurement": root.get("measurement") or "local_filesystem",
            "members": [],
        })
        volume["members"].append({
            "key": root.get("key") or "",
            "label": root.get("label") or root.get("key") or "Speicher",
            "path": root.get("resolved_path") or root.get("path") or "",
            "source": root.get("source") or "media",
            "mode": root.get("location_mode") or LOCATION_MODE_MEDIA,
            "location_id": root.get("location_id") or "",
        })

    volumes = list(volume_by_id.values())
    for volume in volumes:
        members = volume["members"]
        custom = [member for member in members if member["source"] == "custom"]
        if custom:
            volume["label"] = custom[0]["label"]
        elif len(members) > 1:
            volume["label"] = "NAS Hauptspeicher" if base.get("deployment_mode") == "nas" else "Medienspeicher"
        else:
            volume["label"] = members[0]["label"] if members else "Speicher"
        volume["paths"] = list(dict.fromkeys(member["path"] for member in members if member["path"]))
        volume["mode"] = (
            LOCATION_MODE_MEDIA
            if any(member["mode"] == LOCATION_MODE_MEDIA for member in members)
            else LOCATION_MODE_MONITOR
        )

    total = sum(int(item["total_bytes"]) for item in volumes)
    used = sum(int(item["used_bytes"]) for item in volumes)
    free = sum(int(item["free_bytes"]) for item in volumes)
    percent = round(min(100.0, max(0.0, used * 100.0 / total)), 2) if total > 0 else 0.0
    return {
        "deployment_mode": base.get("deployment_mode"),
        "enabled": base.get("enabled", True),
        "observed_at": time.time(),
        "poll_interval_seconds": base.get("poll_interval_seconds", 5),
        "roots": roots,
        "volumes": volumes,
        "locations": normalized_locations,
        "location_modes": [LOCATION_MODE_MONITOR, LOCATION_MODE_MEDIA],
        "max_locations": MAX_STORAGE_LOCATIONS,
        "summary": {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_percent": percent,
            "volume_count": len(volumes),
        },
    }


def _resolved_directory(raw_path: str) -> Path | None:
    try:
        root = Path(str(raw_path or "").strip()).expanduser().resolve(strict=True)
        return root if root.is_dir() else None
    except (OSError, ValueError):
        return None


def _overlaps(root: Path, other: Path) -> bool:
    return root == other or root in other.parents or other in root.parents


def scan_configured_storage(
    media_paths: dict[str, str],
    locations: list[dict] | None = None,
    *,
    max_candidates: int = 40,
) -> dict:
    """Scan media roots plus custom locations explicitly marked as media."""
    normalized_locations = list(locations if locations is not None else load_storage_locations())
    base = scan_large_content(media_paths, max_candidates=max_candidates)
    candidates = list(base.get("candidates", []))
    errors = list(base.get("errors", []))
    scanned_files = int(base.get("scanned_files") or 0)
    truncated = bool(base.get("truncated"))
    medians = [int(base.get("media_file_median_bytes") or 0)]
    thresholds = [int(base.get("large_file_threshold_bytes") or 0)]

    scanned_roots: list[Path] = []
    for raw_path in media_paths.values():
        resolved = _resolved_directory(raw_path)
        if resolved is not None and not any(_overlaps(resolved, known) for known in scanned_roots):
            scanned_roots.append(resolved)

    for location in normalized_locations:
        if location.get("mode") != LOCATION_MODE_MEDIA:
            continue
        root = _resolved_directory(location.get("path", ""))
        custom_key = _custom_root_key(location["id"])
        if root is None:
            errors.append({"root": custom_key, "error": "Speicherpfad ist nicht erreichbar."})
            continue
        if any(_overlaps(root, known) for known in scanned_roots):
            continue
        scanned_roots.append(root)
        payload = scan_large_content(
            {"movies": str(root), "series": ""},
            max_candidates=max_candidates,
        )
        scanned_files += int(payload.get("scanned_files") or 0)
        truncated = truncated or bool(payload.get("truncated"))
        medians.append(int(payload.get("media_file_median_bytes") or 0))
        thresholds.append(int(payload.get("large_file_threshold_bytes") or 0))
        for item in payload.get("candidates", []):
            candidate = dict(item)
            candidate.update({
                "root": custom_key,
                "root_label": location["label"],
                "storage_location_id": location["id"],
            })
            candidates.append(candidate)
        for error in payload.get("errors", []):
            errors.append({
                "root": custom_key,
                "error": error.get("error") or "Scan fehlgeschlagen.",
            })

    ordered = sorted(
        candidates,
        key=lambda item: (float(item.get("score") or 0), int(item.get("size_bytes") or 0)),
        reverse=True,
    )[:max(5, min(int(max_candidates), 80))]
    nonzero_medians = [value for value in medians if value > 0]
    return {
        "observed_at": time.time(),
        "scanned_files": scanned_files,
        "truncated": truncated,
        "media_file_median_bytes": max(nonzero_medians) if nonzero_medians else 0,
        "large_file_threshold_bytes": max(thresholds) if thresholds else 0,
        "candidate_count": len(ordered),
        "candidates": ordered,
        "errors": errors,
    }


def cleanup_configured_candidate(
    media_paths: dict[str, str],
    locations: list[dict] | None = None,
    *,
    root_key: str,
    relative_path: str,
    token: str,
    expected_size: int,
    expires_at: int,
) -> dict:
    normalized_locations = list(locations if locations is not None else load_storage_locations())
    if root_key in {"movies", "series"}:
        return cleanup_candidate(
            media_paths,
            root_key=root_key,
            relative_path=relative_path,
            token=token,
            expected_size=expected_size,
            expires_at=expires_at,
        )

    prefix = "location:"
    if not str(root_key or "").startswith(prefix):
        raise ValueError("Unbekannter oder nicht konfigurierter Speicherbereich.")
    location_id = str(root_key)[len(prefix):]
    location = next(
        (item for item in normalized_locations if item["id"] == location_id),
        None,
    )
    if not location or location.get("mode") != LOCATION_MODE_MEDIA:
        raise ValueError("Dieser Speicherort ist nicht für Medien-Bereinigung freigegeben.")
    result = cleanup_candidate(
        {"movies": location["path"], "series": ""},
        root_key="movies",
        relative_path=relative_path,
        token=token,
        expected_size=expected_size,
        expires_at=expires_at,
    )
    result["root"] = root_key
    return result
