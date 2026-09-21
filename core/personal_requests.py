"""Durable, user-owned media request history independent from queue cleanup."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = 1
_TERMINAL = {"completed", "failed", "cancelled"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class PersonalRequestStore:
    """Atomic JSON store for intentional user requests, never queue snapshots."""

    def __init__(self, path: Path, *, clock=time.time):
        self._path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._requests = self._load()

    def _load(self) -> list[dict]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        values = raw.get("requests", []) if isinstance(raw, dict) else []
        if not isinstance(values, list):
            return []
        normalized = [self._normalize(item) for item in values]
        return [item for item in normalized if item]

    def _normalize(self, raw: Any) -> dict | None:
        if not isinstance(raw, dict):
            return None
        user_id = _text(raw.get("user_id") or raw.get("requested_by_user_id"))
        request_id = _text(raw.get("id"))
        media_key = _text(raw.get("media_key") or raw.get("slug"))
        if not user_id or not request_id or not media_key:
            return None
        status = _text(raw.get("status")) or "requested"
        return {
            "id": request_id,
            "user_id": user_id,
            "requested_by_user_id": user_id,
            "job_id": _text(raw.get("job_id")),
            "media_key": media_key,
            "media_type": _text(raw.get("media_type")) or "movie",
            "title": _text(raw.get("title")) or media_key,
            "year": _text(raw.get("year")),
            "cover_url": _text(raw.get("cover_url")),
            "request_source": _text(raw.get("request_source")) or "manual",
            "status": status,
            "requested_at": _number(raw.get("requested_at")),
            "completed_at": _number(raw.get("completed_at")),
            "failed_at": _number(raw.get("failed_at")),
            "updated_at": _number(raw.get("updated_at")),
        }

    def _save_locked(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        payload = {"schema_version": _SCHEMA_VERSION, "requests": self._requests}
        try:
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self._path)
            return True
        except OSError:
            return False
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def record(self, user_id: str, job: dict, movie=None, *, source: str = "manual") -> dict | None:
        """Record one conscious request; a queue retry retains its original job ID."""
        user_id = _text(user_id)
        job_id = _text(job.get("job_id"))
        slug = _text(job.get("slug"))
        if not user_id or not job_id or not slug:
            return None
        with self._lock:
            existing = next((item for item in self._requests if item["job_id"] == job_id), None)
            if existing:
                return deepcopy(existing)
            now = float(self._clock())
            status = _text(job.get("status")) or "queued"
            request = {
                "id": uuid.uuid4().hex,
                "user_id": user_id,
                "requested_by_user_id": user_id,
                "job_id": job_id,
                "media_key": slug,
                "media_type": _text(job.get("media_type")) or "movie",
                "title": _text(getattr(movie, "title", "")) or _text(job.get("title")) or slug,
                "year": _text(getattr(movie, "year", "")),
                "cover_url": _text(getattr(movie, "cover_url", "")),
                "request_source": _text(source) or "manual",
                "status": status,
                "requested_at": _number(job.get("created_at")) or now,
                "completed_at": _number(job.get("completed_at")),
                "failed_at": now if status in {"failed", "cancelled"} else 0.0,
                "updated_at": now,
            }
            self._requests.insert(0, request)
            if not self._save_locked():
                self._requests.pop(0)
                return None
            return deepcopy(request)

    def update_from_job(self, job: dict) -> bool:
        job_id = _text(job.get("job_id"))
        if not job_id:
            return False
        with self._lock:
            request = next((item for item in self._requests if item["job_id"] == job_id), None)
            if request is None:
                return False
            status = _text(job.get("status")) or request["status"]
            completed_at = _number(job.get("completed_at"))
            changed = request["status"] != status
            request["status"] = status
            if status == "completed" and completed_at:
                changed = changed or request["completed_at"] != completed_at
                request["completed_at"] = completed_at
            if status in {"failed", "cancelled"} and completed_at:
                changed = changed or request["failed_at"] != completed_at
                request["failed_at"] = completed_at
            if not changed:
                return True
            request["updated_at"] = float(self._clock())
            return self._save_locked()

    def mark_failed(self, job_id: str) -> bool:
        return self.update_from_job({"job_id": job_id, "status": "failed", "completed_at": self._clock()})

    def recent_for_user(self, user_id: str, *, limit: int = 8) -> list[dict]:
        with self._lock:
            entries = [item for item in self._requests if item["user_id"] == _text(user_id)]
            entries.sort(key=lambda item: item["requested_at"], reverse=True)
            return deepcopy(entries[:max(0, limit)])

    def count_for_user(self, user_id: str) -> int:
        with self._lock:
            return sum(item["user_id"] == _text(user_id) for item in self._requests)

    def delete_for_user(self, user_id: str) -> int:
        """Erase the durable personal request history for one account."""
        owner = _text(user_id)
        if not owner:
            return 0
        with self._lock:
            previous = self._requests
            remaining = [item for item in previous if item["user_id"] != owner]
            removed = len(previous) - len(remaining)
            if not removed:
                return 0
            self._requests = remaining
            if self._save_locked():
                return removed
            self._requests = previous
            raise OSError("Persönliche Anfragen konnten nicht gelöscht werden.")

    def backfill(self, jobs: list[dict]) -> None:
        """Import only historical jobs whose explicit manual source is trustworthy."""
        for job in jobs:
            owner = _text(job.get("requested_by_user_id"))
            source = _text(job.get("request_source"))
            if owner and source and source not in {"subscription", "system", "automation", "seerr"}:
                self.record(owner, job, source=source)
