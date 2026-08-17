"""Restart-safe execution runtime for guarded media move jobs.

A new job is accepted only after ``storage_move.plan_move_candidate`` validated
its signed scan token.  From that point onward we persist an immutable source
fingerprint and a deterministic hidden work path.  The source is never removed
until a complete destination has been verified, so a process/container restart
can safely continue a partially copied transfer without persisting the scan
secret.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path

from runtime_paths import data_dir
from storage_move import (
    _MIN_FREE_RESERVE,
    _guard_source_tree,
    _measure_move_source,
    _move_source_key,
    plan_move_candidate,
)

SCHEMA_VERSION = 2
HISTORY_LIMIT = 50
JOB_PATH = data_dir() / "storage_move_jobs.json"
COPY_CHUNK_BYTES = 8 * 1024 * 1024
PROGRESS_SAVE_SECONDS = 1.5
RESTART_ERROR = (
    "Royal wurde während dieses Verschiebe-Jobs neu gestartet. "
    "Der Vorgang wird aus Sicherheitsgründen nicht automatisch fortgesetzt."
)

_LOCK = threading.RLock()
_QUEUE: queue.Queue[str | None] = queue.Queue()
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
_ACTIVE: dict[str, dict] = {}
_HISTORY: list[dict] = []


def _public(job: dict) -> dict:
    return {
        key: deepcopy(value)
        for key, value in job.items()
        if not key.startswith("_") and key != "resume"
    }


def _persisted(job: dict) -> dict:
    payload = _public(job)
    resume = job.get("_resume") or job.get("resume")
    if isinstance(resume, dict):
        payload["resume"] = deepcopy(resume)
    return payload


def _save_locked() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "jobs": [_persisted(job) for job in _ACTIVE.values()],
        "history": [_public(job) for job in _HISTORY[:HISTORY_LIMIT]],
    }
    try:
        JOB_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = JOB_PATH.with_name(
            f".{JOB_PATH.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, JOB_PATH)
            try:
                directory_fd = os.open(JOB_PATH.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        # The guarded copy remains authoritative if only history persistence
        # fails.  We never delete the source merely because this write failed.
        pass


def _fingerprint(path: Path) -> dict:
    _guard_source_tree(path)
    measured = _measure_move_source(path)
    return {
        "size_bytes": int(measured.size),
        "file_count": int(measured.file_count),
        "media_file_count": int(measured.media_file_count),
        "modified_ns": int(measured.modified_ns),
        "entry_kind": str(measured.kind),
    }


def _expected_kind(job: dict) -> str:
    return "directory" if job.get("source_kind") == "series" else "file"


def _source_unchanged(job: dict, path: Path) -> bool:
    if not path.exists() or path.is_symlink():
        return False
    resume = job.get("_resume") or {}
    try:
        current = _fingerprint(path)
    except (OSError, ValueError):
        return False
    if current["entry_kind"] != _expected_kind(job):
        return False
    return all(
        int(current[key]) == int(resume.get(key) or 0)
        for key in ("size_bytes", "file_count", "media_file_count", "modified_ns")
    )


def _complete_payload(job: dict, path: Path) -> bool:
    if not path.exists() or path.is_symlink():
        return False
    try:
        measured = _measure_move_source(path)
    except (OSError, ValueError):
        return False
    resume = job.get("_resume") or {}
    return (
        str(measured.kind) == _expected_kind(job)
        and int(measured.size) == int(job.get("size_bytes") or 0)
        and int(measured.file_count) == int(resume.get("file_count") or 0)
        and int(measured.media_file_count) == int(resume.get("media_file_count") or 0)
    )


def _same_volume(source: Path, destination_root: Path) -> bool:
    return int(source.stat().st_dev) == int(destination_root.stat().st_dev)


def _reserve_bytes(size: int) -> int:
    return min(max(_MIN_FREE_RESERVE, int(size * 0.01)), 2 * 1024 * 1024 * 1024)


def _paths(job: dict) -> tuple[Path, Path, Path, Path]:
    resume = job.get("_resume") or {}
    source = Path(str(job.get("source_path") or "")).expanduser()
    destination = Path(str(job.get("destination_path") or "")).expanduser()
    work = Path(str(resume.get("work_path") or "")).expanduser()
    destination_root = Path(
        str(resume.get("destination_root_path") or destination.parent)
    ).expanduser()
    return source, destination, work, destination_root


def _validate_layout(job: dict) -> tuple[Path, Path, Path]:
    source, destination, work, destination_root = _paths(job)
    if not source.is_absolute() or not destination.is_absolute() or not work.is_absolute():
        raise ValueError("Persistierter Verschiebe-Job enthält keinen sicheren absoluten Pfad.")
    destination_root = destination_root.resolve(strict=True)
    if not destination_root.is_dir():
        raise ValueError("Zielspeicher ist nicht erreichbar.")
    if destination.parent.resolve(strict=True) != destination_root:
        raise ValueError("Persistierter Zielpfad liegt nicht mehr im freigegebenen Zielordner.")
    if work.parent.resolve(strict=True) != destination_root:
        raise ValueError("Temporärer Transferpfad liegt nicht im freigegebenen Zielordner.")
    if not work.name.startswith(".royal-move-") or not work.name.endswith(".partial"):
        raise ValueError("Temporärer Transferpfad ist ungültig.")
    if work.is_symlink() or destination.is_symlink():
        raise ValueError("Symbolische Links werden bei Verschiebe-Jobs nicht verwendet.")
    expected_name = str(job.get("source_name") or "")
    if not expected_name or source.name != expected_name or destination.name != expected_name:
        raise ValueError("Persistierter Quell- oder Zielname stimmt nicht mehr mit dem Job überein.")
    if destination.exists():
        if _complete_payload(job, destination):
            return source, destination, work
        raise ValueError("Im Ziel existiert bereits ein anderer oder unvollständiger Inhalt.")
    if not source.exists():
        raise FileNotFoundError("Die Quelle des Verschiebe-Jobs ist nicht mehr vorhanden.")
    source = source.resolve(strict=True)
    if not _source_unchanged(job, source):
        raise ValueError("Die Quelle hat sich seit dem Start des Verschiebe-Jobs verändert.")
    if _same_volume(source, destination_root):
        raise ValueError("Quelle und Ziel liegen inzwischen auf demselben physischen Volume.")
    return source, destination, work


def _tree_part_path(target_file: Path, job_id: str) -> Path:
    return target_file.with_name(f".{target_file.name}.royal-part-{job_id}")


def _existing_tree_file_bytes(source_file: Path, target_file: Path, job_id: str) -> int:
    try:
        source_size = max(0, int(source_file.stat().st_size))
    except OSError:
        return 0
    if target_file.is_file() and not target_file.is_symlink():
        try:
            return min(source_size, max(0, int(target_file.stat().st_size)))
        except OSError:
            return 0
    part = _tree_part_path(target_file, job_id)
    if part.is_file() and not part.is_symlink():
        try:
            return min(source_size, max(0, int(part.stat().st_size)))
        except OSError:
            return 0
    return 0


def _existing_bytes(job: dict, source: Path, work: Path) -> int:
    if not work.exists() or work.is_symlink():
        return 0
    total_expected = max(0, int(job.get("size_bytes") or 0))
    if job.get("source_kind") == "movie":
        if not work.is_file():
            return 0
        try:
            return min(total_expected, max(0, int(work.stat().st_size)))
        except OSError:
            return 0
    if not work.is_dir():
        return 0

    copied = 0
    job_id = str(job.get("job_id") or "")
    for current, _, filenames in os.walk(source, followlinks=False):
        current_path = Path(current)
        target_dir = work / current_path.relative_to(source)
        for name in filenames:
            copied += _existing_tree_file_bytes(
                current_path / name,
                target_dir / name,
                job_id,
            )
    return min(total_expected, max(0, copied))


def _progress(job_id: str, copied: int, *, force: bool = False) -> None:
    with _LOCK:
        job = _ACTIVE.get(job_id)
        if not job:
            return
        total = max(0, int(job.get("size_bytes") or 0))
        copied = max(0, int(copied))
        if total:
            copied = min(total, copied)
        job["moved_bytes"] = copied
        job["progress"] = round((copied * 100.0 / total) if total else 0.0, 2)
        now = time.time()
        if force or now - float(job.get("_last_progress_save") or 0) >= PROGRESS_SAVE_SECONDS:
            job["_last_progress_save"] = now
            _save_locked()


def _copy_movie(job_id: str, source: Path, work: Path) -> None:
    source_size = int(source.stat().st_size)
    if work.exists() and (not work.is_file() or work.is_symlink()):
        raise ValueError("Temporärer Transferpfad hat einen unerwarteten Inhaltstyp.")
    offset = int(work.stat().st_size) if work.exists() else 0
    if offset < 0 or offset > source_size:
        work.unlink(missing_ok=True)
        offset = 0
    copied = offset
    _progress(job_id, copied, force=True)
    with source.open("rb") as source_handle, work.open("ab" if offset else "wb") as target_handle:
        source_handle.seek(offset)
        while True:
            chunk = source_handle.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            target_handle.write(chunk)
            copied += len(chunk)
            _progress(job_id, copied)
        target_handle.flush()
        os.fsync(target_handle.fileno())
    if int(work.stat().st_size) != source_size:
        raise OSError("Temporäre Filmdatei ist nach dem Kopieren unvollständig.")
    shutil.copystat(source, work, follow_symlinks=False)
    _progress(job_id, source_size, force=True)


def _copy_tree_file(job_id: str, source_file: Path, target_file: Path, base_copied: int) -> int:
    source_size = int(source_file.stat().st_size)
    part = _tree_part_path(target_file, job_id)

    if target_file.exists():
        if not target_file.is_file() or target_file.is_symlink():
            raise ValueError(f"Unerwarteter Inhalt im Transferziel: {target_file.name}")
        target_size = int(target_file.stat().st_size)
        if target_size == source_size:
            shutil.copystat(source_file, target_file, follow_symlinks=False)
            _progress(job_id, base_copied + source_size)
            return base_copied + source_size
        if target_size < source_size and not part.exists():
            os.replace(target_file, part)
        else:
            target_file.unlink()

    if part.exists() and (not part.is_file() or part.is_symlink()):
        raise ValueError(f"Unerwarteter temporärer Inhalt: {part.name}")
    offset = int(part.stat().st_size) if part.exists() else 0
    if offset < 0 or offset > source_size:
        part.unlink(missing_ok=True)
        offset = 0

    copied = base_copied + offset
    _progress(job_id, copied)
    with source_file.open("rb") as source_handle, part.open("ab" if offset else "wb") as target_handle:
        source_handle.seek(offset)
        while True:
            chunk = source_handle.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            target_handle.write(chunk)
            copied += len(chunk)
            _progress(job_id, copied)
        target_handle.flush()
        os.fsync(target_handle.fileno())
    if int(part.stat().st_size) != source_size:
        raise OSError(f"Datei {source_file.name} wurde nicht vollständig kopiert.")
    shutil.copystat(source_file, part, follow_symlinks=False)
    os.replace(part, target_file)
    return base_copied + source_size


def _copy_series(job_id: str, source: Path, work: Path) -> None:
    if work.exists() and (not work.is_dir() or work.is_symlink()):
        raise ValueError("Temporärer Serienpfad hat einen unerwarteten Inhaltstyp.")
    work.mkdir(parents=False, exist_ok=True)
    copied = _existing_bytes(_ACTIVE[job_id], source, work)
    _progress(job_id, copied, force=True)

    for current, dirnames, filenames in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path.is_symlink():
            raise ValueError("Symbolische Links werden nicht automatisch verschoben.")
        target_dir = work / current_path.relative_to(source)
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in dirnames:
            child = current_path / name
            if child.is_symlink():
                raise ValueError("Symbolische Links werden nicht automatisch verschoben.")
            (target_dir / name).mkdir(exist_ok=True)
        for name in filenames:
            source_file = current_path / name
            if source_file.is_symlink():
                raise ValueError("Symbolische Links werden nicht automatisch verschoben.")
            target_file = target_dir / name
            already = _existing_tree_file_bytes(source_file, target_file, job_id)
            copied = max(0, copied - already)
            copied = _copy_tree_file(job_id, source_file, target_file, copied)

    for current, _, _ in os.walk(source, topdown=False, followlinks=False):
        directory = Path(current)
        shutil.copystat(
            directory,
            work / directory.relative_to(source),
            follow_symlinks=False,
        )
    measured = _measure_move_source(work)
    _progress(job_id, int(measured.size), force=True)


def _remove_source(job: dict, source: Path) -> None:
    if not source.exists():
        return
    if not _source_unchanged(job, source):
        raise ValueError("Quelle wurde vor dem Abschluss verändert und deshalb nicht gelöscht.")
    if source.is_dir() and not source.is_symlink():
        shutil.rmtree(source)
    else:
        source.unlink()
    if source.exists():
        raise OSError("Quelle konnte nach erfolgreicher Zielprüfung nicht entfernt werden.")


def _execute(job_id: str) -> dict:
    with _LOCK:
        live = _ACTIVE.get(job_id)
        if not live:
            raise LookupError("Verschiebe-Job existiert nicht mehr.")
        job = deepcopy(live)

    source, destination, work, _ = _paths(job)
    # Crash window: destination was atomically published, but source cleanup or
    # job persistence did not happen yet.  Verify and finish idempotently.
    if destination.exists() and _complete_payload(job, destination):
        if source.exists():
            source = source.resolve(strict=True)
            _remove_source(job, source)
        _progress(job_id, int(job.get("size_bytes") or 0), force=True)
        return {
            "moved": True,
            "moved_bytes": int(job.get("size_bytes") or 0),
            "destination_path": str(destination),
            "recovered": True,
        }

    source, destination, work = _validate_layout(job)
    existing = _existing_bytes(job, source, work)
    remaining = max(0, int(job.get("size_bytes") or 0) - existing)
    reserve = _reserve_bytes(int(job.get("size_bytes") or 0))
    if int(shutil.disk_usage(destination.parent).free) < remaining + reserve:
        raise OSError("Nicht genügend freier Speicher, um den Transfer sicher fortzusetzen.")
    _progress(job_id, existing, force=True)

    if job.get("source_kind") == "movie":
        _copy_movie(job_id, source, work)
    else:
        _copy_series(job_id, source, work)

    measured = _measure_move_source(work)
    resume = job.get("_resume") or {}
    if (
        str(measured.kind) != _expected_kind(job)
        or int(measured.size) != int(job.get("size_bytes") or 0)
        or int(measured.file_count) != int(resume.get("file_count") or 0)
        or int(measured.media_file_count) != int(resume.get("media_file_count") or 0)
    ):
        raise OSError("Temporärer Zielstand stimmt nicht mit der geprüften Quelle überein.")
    if not _source_unchanged(job, source):
        raise ValueError("Quelle hat sich während des Transfers verändert; Ziel wird nicht veröffentlicht.")
    if destination.exists() or destination.is_symlink():
        raise OSError("Ziel wurde während des Transfers anderweitig belegt.")

    os.replace(work, destination)
    if not _complete_payload(job, destination):
        raise OSError("Zieldaten konnten nach dem Transfer nicht vollständig bestätigt werden.")
    _remove_source(job, source)
    _progress(job_id, int(job.get("size_bytes") or 0), force=True)
    return {
        "moved": True,
        "moved_bytes": int(job.get("size_bytes") or 0),
        "destination_path": str(destination),
        "recovered": bool(job.get("recovered_after_restart")),
    }


def _finish(job_id: str, *, result: dict | None = None, error: str = "") -> None:
    with _LOCK:
        job = _ACTIVE.pop(job_id, None)
        if not job:
            return
        job["completed_at"] = time.time()
        if error:
            job["status"] = "failed"
            job["error"] = str(error)[:2000]
        else:
            job["status"] = "completed"
            job["progress"] = 100.0
            job["moved_bytes"] = int((result or {}).get("moved_bytes") or job.get("size_bytes") or 0)
            job["destination_path"] = str((result or {}).get("destination_path") or job.get("destination_path") or "")
            job["error"] = ""
        for key in ("_resume", "_source_key", "_last_progress_save"):
            job.pop(key, None)
        _HISTORY.insert(0, job)
        del _HISTORY[HISTORY_LIMIT:]
        _save_locked()


def _run(job_id: str) -> None:
    with _LOCK:
        job = _ACTIVE.get(job_id)
        if not job:
            return
        job["status"] = "running"
        if not float(job.get("started_at") or 0):
            job["started_at"] = time.time()
        job["error"] = ""
        _save_locked()
    try:
        result = _execute(job_id)
    except Exception as exc:
        _finish(job_id, error=str(exc) or exc.__class__.__name__)
        return
    _finish(job_id, result=result)


def _worker() -> None:
    while True:
        job_id = _QUEUE.get()
        try:
            if job_id is None:
                return
            _run(job_id)
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        thread = threading.Thread(
            target=_worker,
            name="royal-storage-resumable-move-worker",
            daemon=True,
        )
        thread.start()
        _WORKER_STARTED = True


def _enqueue(job_id: str) -> None:
    _ensure_worker()
    _QUEUE.put(job_id)


def create_move_job(
    media_paths: dict[str, str],
    locations: list[dict],
    *,
    root_key: str,
    relative_path: str,
    token: str,
    expected_size: int,
    expires_at: int,
    destination_root: str,
) -> dict:
    plan = plan_move_candidate(
        media_paths,
        locations,
        root_key=root_key,
        relative_path=relative_path,
        token=token,
        expected_size=expected_size,
        expires_at=expires_at,
    )
    target = next(
        (
            item for item in plan.get("targets", [])
            if item.get("root") == destination_root and item.get("eligible")
        ),
        None,
    )
    if target is None:
        raise ValueError("Dieses Ziel ist für das Verschieben nicht verfügbar.")

    source = Path(str(plan.get("source_path") or "")).resolve(strict=True)
    fingerprint = _fingerprint(source)
    if int(fingerprint["size_bytes"]) != int(plan.get("size_bytes") or 0):
        raise ValueError("Der Inhalt hat sich während der Job-Erstellung verändert.")
    source_key = _move_source_key(str(source))
    if not source_key:
        raise ValueError("Der zu verschiebende Inhalt konnte nicht eindeutig bestimmt werden.")

    destination_root_path = Path(str(target.get("path") or "")).resolve(strict=True)
    destination = Path(str(target.get("destination") or "")).absolute()
    job_id = uuid.uuid4().hex
    work = destination_root_path / f".royal-move-{job_id}.partial"
    if work.exists() or work.is_symlink():
        raise ValueError("Temporärer Verschiebepfad ist bereits belegt.")

    now = time.time()
    with _LOCK:
        if any(job.get("_source_key") == source_key for job in _ACTIVE.values()):
            raise ValueError("Für diesen Inhalt läuft bereits ein Verschiebe-Job.")
        job = {
            "job_id": job_id,
            "operation": "move",
            "status": "queued",
            "source_root": str(plan.get("source_root") or root_key),
            "source_label": str(plan.get("source_label") or root_key),
            "source_path": str(source),
            "source_name": str(plan.get("source_name") or source.name),
            "source_kind": str(plan.get("source_kind") or "movie"),
            "candidate_path": str(relative_path),
            "size_bytes": int(plan.get("size_bytes") or expected_size or 0),
            "destination_root": str(destination_root),
            "destination_label": str(target.get("label") or destination_root),
            "destination_path": str(destination),
            "created_at": now,
            "started_at": 0.0,
            "completed_at": 0.0,
            "progress": 0.0,
            "moved_bytes": 0,
            "error": "",
            "recovered_after_restart": False,
            "_source_key": source_key,
            "_resume": {
                **fingerprint,
                "work_path": str(work),
                "destination_root_path": str(destination_root_path),
            },
        }
        _ACTIVE[job_id] = job
        _save_locked()
    try:
        _enqueue(job_id)
    except Exception as exc:
        _finish(job_id, error=f"Verschiebe-Job konnte nicht gestartet werden: {exc}")
        raise OSError("Verschiebe-Job konnte nicht gestartet werden.") from exc
    return _public(job)


def list_move_jobs() -> dict:
    with _LOCK:
        jobs = sorted(
            (_public(job) for job in _ACTIVE.values()),
            key=lambda item: float(item.get("created_at") or 0),
        )
        history = [_public(job) for job in _HISTORY[:HISTORY_LIMIT]]
    return {"jobs": jobs, "history": history, "active_count": len(jobs)}


def _internalize(item: dict) -> dict:
    job = dict(item)
    resume = job.pop("resume", None)
    if isinstance(resume, dict):
        job["_resume"] = dict(resume)
    job["_source_key"] = _move_source_key(str(job.get("source_path") or ""))
    job["_last_progress_save"] = 0.0
    return job


def _legacy_work(job: dict, source: Path, destination: Path) -> Path | None:
    started = float(job.get("started_at") or 0)
    candidates: list[Path] = []
    try:
        for candidate in destination.parent.glob(".royal-move-*.partial"):
            if candidate.is_symlink():
                continue
            if job.get("source_kind") == "series" and not candidate.is_dir():
                continue
            if job.get("source_kind") == "movie" and not candidate.is_file():
                continue
            if started and candidate.stat().st_mtime < started - 300:
                continue
            try:
                measured = _measure_move_source(candidate)
            except (OSError, ValueError):
                continue
            if int(measured.size) <= int(job.get("size_bytes") or 0):
                candidates.append(candidate)
    except OSError:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return None
    return destination.parent / f".royal-move-{job.get('job_id') or uuid.uuid4().hex}.partial"


def _adopt_legacy_restart(item: dict) -> dict | None:
    if RESTART_ERROR not in str(item.get("error") or ""):
        return None
    source = Path(str(item.get("source_path") or ""))
    destination = Path(str(item.get("destination_path") or ""))
    if not source.is_absolute() or not destination.is_absolute():
        return None
    if destination.exists() or not source.exists() or source.is_symlink():
        return None
    try:
        source = source.resolve(strict=True)
        destination_root = destination.parent.resolve(strict=True)
        fingerprint = _fingerprint(source)
    except (OSError, ValueError):
        return None
    if int(fingerprint["size_bytes"]) != int(item.get("size_bytes") or 0):
        return None
    work = _legacy_work(item, source, destination)
    if work is None:
        return None

    job = dict(item)
    job["status"] = "queued"
    job["completed_at"] = 0.0
    job["error"] = ""
    job["recovered_after_restart"] = True
    job["_source_key"] = _move_source_key(str(source))
    job["_last_progress_save"] = 0.0
    job["_resume"] = {
        **fingerprint,
        "work_path": str(work),
        "destination_root_path": str(destination_root),
        "legacy_adopted": True,
    }
    copied = _existing_bytes(job, source, work)
    job["moved_bytes"] = copied
    total = max(1, int(job.get("size_bytes") or 1))
    job["progress"] = round(copied * 100.0 / total, 2)
    return job


def _recover() -> None:
    try:
        raw = json.loads(JOB_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(raw, dict):
        return

    active_input = [item for item in raw.get("jobs", []) if isinstance(item, dict)]
    history_input = [item for item in raw.get("history", []) if isinstance(item, dict)]
    recovered: list[dict] = []
    history: list[dict] = []

    for item in active_input + history_input:
        restart_failure = RESTART_ERROR in str(item.get("error") or "")
        if isinstance(item.get("resume"), dict) and (item in active_input or restart_failure):
            job = _internalize(item)
            job["status"] = "queued"
            job["completed_at"] = 0.0
            job["error"] = ""
            job["recovered_after_restart"] = True
            recovered.append(job)
            continue
        legacy = _adopt_legacy_restart(item) if restart_failure else None
        if legacy is not None:
            recovered.append(legacy)
            continue
        if item in active_input:
            failed = dict(item)
            failed.pop("resume", None)
            failed["status"] = "failed"
            failed["completed_at"] = time.time()
            failed["error"] = RESTART_ERROR
            history.insert(0, failed)
        else:
            clean = dict(item)
            clean.pop("resume", None)
            history.append(clean)

    unique: list[dict] = []
    source_keys: set[str] = set()
    for job in sorted(recovered, key=lambda value: float(value.get("created_at") or 0)):
        key = str(job.get("_source_key") or "")
        if not key or key in source_keys:
            job.pop("_resume", None)
            job["status"] = "failed"
            job["completed_at"] = time.time()
            job["error"] = "Persistierter Verschiebe-Job war doppelt oder unvollständig."
            history.insert(0, job)
            continue
        source_keys.add(key)
        unique.append(job)

    with _LOCK:
        _ACTIVE.clear()
        for job in unique:
            job_id = str(job.get("job_id") or uuid.uuid4().hex)
            job["job_id"] = job_id
            _ACTIVE[job_id] = job
        _HISTORY[:] = history[:HISTORY_LIMIT]
        _save_locked()

    for job in unique:
        _enqueue(str(job["job_id"]))


_recover()
