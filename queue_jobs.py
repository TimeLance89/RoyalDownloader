"""Persistent logical download jobs and backwards-compatible queue migration."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
HISTORY_LIMIT = 500
ACTIVE_STATES = {
    "queued", "preparing", "waiting_provider", "downloading", "paused",
}
TERMINAL_STATES = {"completed", "failed", "cancelled"}
JOB_STATES = ACTIVE_STATES | TERMINAL_STATES
_MIGRATION_NAMESPACE = uuid.UUID("f9d1f659-685d-4ed8-a4d8-82764a904f3b")
_EPISODE_RE = re.compile(r"(?:^|[-_:])s\d{1,3}e\d{1,4}(?:$|[-_:])", re.I)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def stable_migration_id(slug: str) -> str:
    """Return the same ID until a migrated legacy queue can be persisted."""
    return uuid.uuid5(_MIGRATION_NAMESPACE, _text(slug)).hex


def media_type_for_slug(slug: str) -> str:
    normalized = _text(slug)
    if normalized.casefold().startswith("mkissa:"):
        return "anime"
    return "series" if _EPISODE_RE.search(normalized) else "movie"


def new_job(
    slug: str,
    *,
    job_id: str | None = None,
    title: str = "",
    created_at: float | None = None,
) -> dict[str, Any]:
    now = time.time() if created_at is None else float(created_at)
    return {
        "job_id": _text(job_id) or uuid.uuid4().hex,
        "media_type": media_type_for_slug(slug),
        "title": _text(title) or _text(slug),
        "slug": _text(slug),
        "provider": "",
        "hoster": "",
        "quality": "",
        "content_language": "",
        "status": "queued",
        "created_at": now,
        "started_at": 0.0,
        "completed_at": 0.0,
        "progress": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "speed_bps": 0.0,
        "eta_seconds": None,
        "error": "",
        "attempts": 0,
        "next_retry_at": 0.0,
        "final_path": "",
    }


def normalize_job(
    raw: Any, *, active: bool, recover_active: bool = True,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    slug = _text(raw.get("slug"))
    if not slug:
        return None
    fallback_id = stable_migration_id(slug)
    job = new_job(
        slug,
        job_id=_text(raw.get("job_id")) or fallback_id,
        title=_text(raw.get("title")),
        created_at=raw.get("created_at") or time.time(),
    )
    job.update({key: deepcopy(raw[key]) for key in job if key in raw})
    job["job_id"] = _text(job.get("job_id")) or fallback_id
    job["slug"] = slug
    job["media_type"] = (
        _text(job.get("media_type"))
        if _text(job.get("media_type")) in {"movie", "series", "anime"}
        else media_type_for_slug(slug)
    )
    status = _text(job.get("status"))
    if status not in JOB_STATES:
        status = "queued" if active else "failed"
    # A process cannot still be preparing/downloading after restart. It is
    # safely re-queued with the same logical identity and attempt counter.
    if active and recover_active and status in {"preparing", "downloading"}:
        status = "queued"
    job["status"] = status
    for key in ("created_at", "started_at", "completed_at", "progress", "speed_bps", "next_retry_at"):
        try:
            job[key] = float(job.get(key) or 0)
        except (TypeError, ValueError):
            job[key] = 0.0
    for key in ("downloaded_bytes", "attempts"):
        try:
            job[key] = max(0, int(job.get(key) or 0))
        except (TypeError, ValueError):
            job[key] = 0
    for key in ("total_bytes", "eta_seconds"):
        try:
            job[key] = max(0, int(job[key])) if job.get(key) is not None else None
        except (TypeError, ValueError):
            job[key] = None
    return job


def normalize_document(
    data: Any, *, recover_active: bool = True,
) -> tuple[dict[str, Any], bool]:
    """Normalize current data or migrate the legacy ``[slug, ...]`` format."""
    migrated = isinstance(data, list)
    if isinstance(data, list):
        active_raw = [
            new_job(slug, job_id=stable_migration_id(slug))
            for slug in dict.fromkeys(item for item in data if isinstance(item, str) and item.strip())
        ]
        history_raw: list[Any] = []
    elif isinstance(data, dict):
        active_raw = data.get("jobs", data.get("active_jobs", []))
        history_raw = data.get("history", [])
        if not isinstance(active_raw, list):
            active_raw = []
        if not isinstance(history_raw, list):
            history_raw = []
        migrated = _nonnegative_int(data.get("schema_version")) != SCHEMA_VERSION
    else:
        active_raw, history_raw, migrated = [], [], bool(data is not None)

    jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for raw in active_raw:
        job = normalize_job(raw, active=True, recover_active=recover_active)
        if not job or job["job_id"] in seen_ids or job["slug"] in seen_slugs:
            continue
        jobs.append(job)
        seen_ids.add(job["job_id"])
        seen_slugs.add(job["slug"])

    history: list[dict[str, Any]] = []
    for raw in history_raw:
        job = normalize_job(raw, active=False)
        if not job or job["job_id"] in seen_ids:
            continue
        if job["status"] not in TERMINAL_STATES:
            job["status"] = "failed"
        history.append(job)
        seen_ids.add(job["job_id"])
    history.sort(key=lambda item: float(item.get("completed_at") or 0), reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": _nonnegative_int(data.get("revision")) if isinstance(data, dict) else 0,
        "jobs": jobs,
        "history": history[:HISTORY_LIMIT],
    }, migrated


def load_document(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return normalize_document(None)
    return normalize_document(json.loads(path.read_text(encoding="utf-8")))


def atomic_save(path: Path, document: dict[str, Any]) -> None:
    normalized, _migrated = normalize_document(document, recover_active=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        payload = json.dumps(normalized, ensure_ascii=False, indent=2)
        with open(tmp, "w", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Some NAS/file-system combinations do not support directory fsync;
            # the atomic replace itself remains valid there.
            pass
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
