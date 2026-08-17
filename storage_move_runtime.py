"""Restart-safe execution runtime for guarded cross-volume media moves.

New jobs are accepted only after :func:`storage_move.plan_move_candidate` has
validated the signed scan result.  After acceptance we persist a non-secret
source fingerprint and a deterministic hidden work path.  The source stays
untouched until the destination has been copied, verified, and atomically
published, which makes interrupted transfers safe to continue after a Royal or
container restart without persisting the short-lived scan token.
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
        # A history write must never make an otherwise guarded copy destructive.
        # Source deletion is protected separately by the source fingerprint.
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


def _source_unchanged(job: dict, source: Path) -> bool:
    if not source.exists() or source.is_symlink():
        return False
    resume = job.get("_resume") or {}
    try:
        current = _fingerprint(source)
    except (OSError, ValueError):
        return False
    if current["entry_kind"] != _expected_kind(job):
        return False
    return all(
        int(current[key]) == int(resume.get(key) or 0)
        for key in ("size_bytes", "file_count", "media_file_count", "modified_ns")
    )


def _complete_destination(job: dict, destination: Path) -> bool:
    """Verify a published destination using its real media name/extensions."""
    if not destination.exists() or destination.is_symlink():
        return False
    try:
        measured = _measure_move_source(destination)
    except (OSError, ValueError):
        return False
    resume = job.get("_resume") or {}
    return (
        str(measured.kind) == _expected_kind(job)
        and int(measured.size) == int(job.get("size_bytes") or 0)
        and int(measured.file_count) == int(resume.get("file_count") or 0)
        and int(measured.media_file_count) == int(resume.get("media_file_count") or 0)
    )


def _complete_work(job: dict, work: Path) -> bool:
    """Verify the hidden work payload before it is atomically published.

    A movie work file intentionally ends in ``.partial``.  The storage scanner
    therefore does not count that hidden filename as a media file.  Its kind,
    byte size, and file count are authoritative here; after ``os.replace`` the
    real movie filename is restored and ``_complete_destination`` performs the
    full media-file-count check.  Directory work keeps the original filenames,
    so all counters can be checked before publication.
    """
    if not work.exists() or work.is_symlink():
        return False
    try:
        measured = _measure_move_source(work)
    except (OSError, ValueError):
        return False
    resume = job.get("_resume") or {}
    if (
        str(measured.kind) != _expected_kind(job)
        or int(measured.size) != int(job.get("size_bytes") or 0)
        or int(measured.file_count) != int(resume.get("file_count") or 0)
    ):
        return False
    if job.get("source_kind") == "series":
        return int(measured.media_file_count) == int(resume.get("media_file_count") or 0)
    return True


def _same_volume(source: Path, destination_root: Path) -> bool:
    return int(source.stat().st_dev) == int(destination_root.stat().st_dev)


def _reserve_bytes(size: int) -> int:
    return min(max(_MIN_FREE_RESERVE, int(size * 0.01)), 2 * 1024 * 1024 * 1024)


def _job_paths(job: dict) -> tuple[Path, Path, Path, Path]:
    resume = job.get("_resume") or {}
    source = Path(str(job.get("source_path") or "")).expanduser()
    destination = Path(str(job.get("destination_path") or "")).expanduser()
    work = Path(str(resume.get("work_path") or "")).expanduser()
    destination_root = Path(
        str(resume.get("destination_root_path") or destination.parent)
    ).expanduser()
    return source, destination, work, destination_root


def _validate_layout(job: dict) -> tuple[Path, Path, Path]:
    source, destination, work, destination_root = _job_paths(job)
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
        if _complete_destination(job, destination):
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


def _part_path(target_file: Path, job_id: str) -> Path:
    return target_file.with_name(f".{target_file.name}.royal-part-{job_id}")


def _same_copied_file(source_file: Path, target_file: Path) -> bool:
    """Recognize files that Royal already completed before an interruption."""
    if not target_file.is_file() or target_file.is_symlink():
        return False
    try:
        source_stat = source_file.stat()
        target_stat = target_file.stat()
    except OSError:
        return False
    return (
        int(source_stat.st_size) == int(target_stat.st_size)
        and int(source_stat.st_mtime_ns) == int(target_stat.st_mtime_ns)
    )


def _partial_prefix_matches(source_file: Path, partial: Path) -> bool:
    """Reject an unrelated same-name partial before appending to it."""
    if not partial.exists():
        return True
    if not partial.is_file() or partial.is_symlink():
        return False
    try:
        partial_size = int(partial.stat().st_size)
        source_size = int(source_file.stat().st_size)
    except OSError:
        return False
    if partial_size < 0 or partial_size > source_size:
        return False
    if partial_size == 0:
        return True
    sample = min(64 * 1024, partial_size)
    offsets = {0, max(0, partial_size - sample)}
    try:
        with source_file.open("rb") as source_handle, partial.open("rb") as partial_handle:
            for offset in offsets:
                source_handle.seek(offset)
                partial_handle.seek(offset)
                if source_handle.read(sample) != partial_handle.read(sample):
                    return False
    except OSError:
        return False
    return True


def _existing_tree_file_bytes(source_file: Path, target_file: Path, job_id: str) -> int:
    if _same_copied_file(source_file, target_file):
        return int(source_file.stat().st_size)
    part = _part_path(target_file, job_id)
    if not _partial_prefix_matches(source_file, part):
        return 0
    try:
        return min(int(source_file.stat().st_size), int(part.stat().st_size)) if part.exists() else 0
    except OSError:
        return 0


def _existing_bytes(job: dict, source: Path, work: Path) -> int:
    total_expected = max(0, int(job.get("size_bytes") or 0))
    if not work.exists() or work.is_symlink():
        return 0
    if job.get("source_kind") == "movie":
        if not _partial_prefix_matches(source, work):
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


def _set_progress(job_id: str, copied: int, *, force: bool = False) -> None:
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
    if work.exists() and not _partial_prefix_matches(source, work):
        work.unlink()
    offset = int(work.stat().st_size) if work.exists() else 0
    copied = offset
    _set_progress(job_id, copied, force=True)
    with source.open("rb") as source_handle, work.open("ab" if offset else "wb") as target_handle:
        source_handle.seek(offset)
        while True:
            chunk = source_handle.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            target_handle.write(chunk)
            copied += len(chunk)
            _set_progress(job_id, copied)
        target_handle.flush()
        os.fsync(target_handle.fileno())
    if int(work.stat().st_size) != source_size:
        raise OSError("Temporäre Filmdatei ist nach dem Kopieren unvollständig.")
    shutil.copystat(source, work, follow_symlinks=False)
    _set_progress(job_id, source_size, force=True)


def _copy_tree_file(
    job_id: str,
    source_file: Path,
    target_file: Path,
    completed_before: int,
) -> int:
    source_size = int(source_file.stat().st_size)
    if _same_copied_file(source_file, target_file):
        completed = completed_before + source_size
        _set_progress(job_id, completed)
        return completed

    part = _part_path(target_file, job_id)
    if target_file.exists():
        if not target_file.is_file() or target_file.is_symlink():
            raise ValueError(f"Unerwarteter Inhalt im Transferziel: {target_file.name}")
        target_file.unlink()
    if part.exists() and (not part.is_file() or part.is_symlink()):
        raise ValueError(f"Unerwarteter temporärer Inhalt: {part.name}")
    if part.exists() and not _partial_prefix_matches(source_file, part):
        part.unlink()
    offset = int(part.stat().st_size) if part.exists() else 0
    copied = completed_before + offset
    _set_progress(job_id, copied)

    with source_file.open("rb") as source_handle, part.open("ab" if offset else "wb") as target_handle:
        source_handle.seek(offset)
        while True:
            chunk = source_handle.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            target_handle.write(chunk)
            copied += len(chunk)
            _set_progress(job_id, copied)
        target_handle.flush()
        os.fsync(target_handle.fileno())
    if int(part.stat().st_size) != source_size:
        raise OSError(f"Datei {source_file.name} wurde nicht vollständig kopiert.")
    shutil.copystat(source_file, part, follow_symlinks=False)
    os.replace(part, target_file)
    return completed_before + source_size


def _source_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path.is_symlink():
            raise ValueError("Symbolische Links werden nicht automatisch verschoben.")
        for name in dirnames:
            if (current_path / name).is_symlink():
                raise ValueError("Symbolische Links werden nicht automatisch verschoben.")
        for name in filenames:
            child = current_path / name
            if child.is_symlink():
                raise ValueError("Symbolische Links werden nicht automatisch verschoben.")
            files.append(child)
    return sorted(files, key=lambda item: item.relative_to(source).as_posix().casefold())


def _copy_series(job_id: str, source: Path, work: Path) -> None:
    if work.exists() and (not work.is_dir() or work.is_symlink()):
        raise ValueError("Temporärer Serienpfad hat einen unerwarteten Inhaltstyp.")
    work.mkdir(parents=False, exist_ok=True)
    completed = 0
    for source_file in _source_files(source):
        relative = source_file.relative_to(source)
        target_file = work / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        completed = _copy_tree_file(job_id, source_file, target_file, completed)

    for current, _, _ in os.walk(source, topdown=False, followlinks=False):
        directory = Path(current)
        target_dir = work / directory.relative_to(source)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copystat(directory, target_dir, follow_symlinks=False)
    _set_progress(job_id, int(job_id and _measure_move_source(work).size), force=True)


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

    source, destination, work, _ = _job_paths(job)
    # Crash window: destination was already atomically published, but source
    # cleanup or the final history write did not happen yet.
    if destination.exists() and _complete_destination(job, destination):
        if source.exists():
            source = source.resolve(strict=True)
            _remove_source(job, source)
        _set_progress(job_id, int(job.get("size_bytes") or 0), force=True)
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
    _set_progress(job_id, existing, force=True)

    if job.get("source_kind") == "movie":
        _copy_movie(job_id, source, work)
    else:
        _copy_series(job_id, source, work)

    if not _complete_work(job, work):
        raise OSError("Temporärer Zielstand stimmt nicht mit der geprüften Quelle überein.")
    if not _source_unchanged(job, source):
        raise ValueError("Quelle hat sich während des Transfers verändert; Ziel wird nicht veröffentlicht.")
    if destination.exists() or destination.is_symlink():
        raise OSError("Ziel wurde während des Transfers anderweitig belegt.")

    os.replace(work, destination)
    if not _complete_destination(job, destination):
        raise OSError("Zieldaten konnten nach dem Transfer nicht vollständig bestätigt werden.")
    _remove_source(job, source)
    _set_progress(job_id, int(job.get("size_bytes") or 0), force=True)
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
        threading.Thread(
            target=_worker,
            name="royal-storage-resumable-move-worker",
            daemon=True,
        ).start()
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


def source_has_active_move(source_path: str) -> bool:
    key = _move_source_key(source_path)
    if not key:
        return False
    with _LOCK:
        return any(job.get("_source_key") == key for job in _ACTIVE.values())


def _internalize(item: dict) -> dict:
    job = dict(item)
    resume = job.pop("resume", None)
    if isinstance(resume, dict):
        job["_resume"] = dict(resume)
    job["_source_key"] = _move_source_key(str(job.get("source_path") or ""))
    job["_last_progress_save"] = 0.0
    return job


def _refresh_recovered_progress(job: dict) -> None:
    source, _, work, _ = _job_paths(job)
    try:
        source = source.resolve(strict=True)
        if not _source_unchanged(job, source):
            return
        copied = _existing_bytes(job, source, work)
    except (OSError, ValueError):
        return
    total = max(1, int(job.get("size_bytes") or 1))
    job["moved_bytes"] = copied
    job["progress"] = round(copied * 100.0 / total, 2)


def _legacy_work(job: dict, destination: Path) -> Path | None:
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
    work = _legacy_work(item, destination)
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
    _refresh_recovered_progress(job)
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
            _refresh_recovered_progress(job)
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
