"""Safe live storage telemetry, large-content analysis, and cleanup helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import shutil
import statistics
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

GIB = 1024 ** 3
DEFAULT_MAX_SCAN_FILES = 200_000
DEFAULT_MAX_CANDIDATES = 40
DEFAULT_LARGE_FILE_FLOOR = 4 * GIB
DEFAULT_LARGE_FOLDER_FLOOR = 2 * GIB
SCAN_TOKEN_TTL_SECONDS = 15 * 60
PROTECTED_NAMES = {
    ".downloading",
    ".royal-trash",
    ".royal-downloader",
    "lost+found",
}
VIDEO_EXTENSIONS = {
    ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg",
    ".mpg", ".mts", ".ts", ".webm", ".wmv",
}
_SIGNING_KEY = secrets.token_bytes(32)
_LARGEST_FILES_LIMIT = 160


@dataclass
class _ScanBudget:
    maximum: int
    files: int = 0
    truncated: bool = False

    def claim(self) -> bool:
        if self.files >= self.maximum:
            self.truncated = True
            return False
        self.files += 1
        return True


@dataclass(frozen=True)
class _MeasuredEntry:
    path: Path
    kind: str
    size: int
    file_count: int
    media_file_count: int
    modified_ns: int
    complete: bool = True


def _configured_roots(paths: dict[str, str]) -> Iterable[tuple[str, str, str]]:
    yield "movies", "Filme", str(paths.get("movies") or "").strip()
    yield "series", "Serien", str(paths.get("series") or "").strip()


def _usage_percent(used: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(min(100.0, max(0.0, used * 100.0 / total)), 2)


def storage_status(paths: dict[str, str], deployment_mode: str) -> dict:
    """Return lightweight live capacity data for configured media mounts.

    ``shutil.disk_usage`` operates on the mounted path itself. In Docker/NAS
    deployments that means the bind-mounted host filesystem is measured rather
    than the container image filesystem.
    """
    roots: list[dict] = []
    volume_by_id: dict[str, dict] = {}
    mode = str(deployment_mode or "desktop").strip().casefold()

    for key, label, raw_path in _configured_roots(paths):
        payload = {
            "key": key,
            "label": label,
            "path": raw_path,
            "configured": bool(raw_path),
            "available": False,
            "measurement": "nas_mount" if mode == "nas" else "local_filesystem",
        }
        if not raw_path:
            payload["error"] = "Kein Speicherpfad konfiguriert."
            roots.append(payload)
            continue
        try:
            root = Path(raw_path).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise NotADirectoryError(str(root))
            usage = shutil.disk_usage(root)
            stat = root.stat()
            volume_id = f"{stat.st_dev}:{usage.total}"
        except (OSError, ValueError) as exc:
            payload["error"] = str(exc)
            roots.append(payload)
            continue

        used = max(0, int(usage.total) - int(usage.free))
        payload.update({
            "available": True,
            "resolved_path": str(root),
            "total_bytes": int(usage.total),
            "used_bytes": used,
            "free_bytes": int(usage.free),
            "used_percent": _usage_percent(used, int(usage.total)),
            "volume_id": volume_id,
        })
        roots.append(payload)
        volume = volume_by_id.setdefault(volume_id, {
            "id": volume_id,
            "total_bytes": int(usage.total),
            "used_bytes": used,
            "free_bytes": int(usage.free),
            "used_percent": _usage_percent(used, int(usage.total)),
            "roots": [],
        })
        volume["roots"].append(key)

    volumes = list(volume_by_id.values())
    total = sum(item["total_bytes"] for item in volumes)
    used = sum(item["used_bytes"] for item in volumes)
    free = sum(item["free_bytes"] for item in volumes)
    return {
        "deployment_mode": mode,
        "enabled": mode != "demo",
        "observed_at": time.time(),
        "poll_interval_seconds": 5,
        "roots": roots,
        "volumes": volumes,
        "summary": {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_percent": _usage_percent(used, total),
            "volume_count": len(volumes),
        },
    }


def _hidden_or_protected(name: str) -> bool:
    return not name or name.startswith(".") or name.casefold() in PROTECTED_NAMES


def _record_largest_file(
    largest_files: list[tuple[int, str, int]], size: int, path: Path, modified_ns: int,
) -> None:
    largest_files.append((size, str(path), modified_ns))
    if len(largest_files) > _LARGEST_FILES_LIMIT * 2:
        largest_files.sort(reverse=True)
        del largest_files[_LARGEST_FILES_LIMIT:]


def _measure_entry(
    path: Path,
    budget: _ScanBudget,
    largest_files: list[tuple[int, str, int]],
    media_sizes: list[int],
) -> _MeasuredEntry:
    if path.is_symlink():
        raise ValueError("Symbolische Links werden nicht analysiert.")
    stat = path.stat(follow_symlinks=False)
    if path.is_file():
        if not budget.claim():
            return _MeasuredEntry(path, "file", 0, 0, 0, stat.st_mtime_ns, complete=False)
        size = max(0, int(stat.st_size))
        _record_largest_file(largest_files, size, path, stat.st_mtime_ns)
        media = path.suffix.casefold() in VIDEO_EXTENSIONS
        if media:
            media_sizes.append(size)
        return _MeasuredEntry(path, "file", size, 1, int(media), stat.st_mtime_ns)
    if not path.is_dir():
        return _MeasuredEntry(path, "other", 0, 0, 0, stat.st_mtime_ns)

    total = 0
    files = 0
    media_files = 0
    complete = True
    stack = [path]
    while stack and not budget.truncated:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            complete = False
            continue
        for entry in entries:
            if _hidden_or_protected(entry.name) or entry.is_symlink():
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if not budget.claim():
                    break
                file_stat = entry.stat(follow_symlinks=False)
            except OSError:
                complete = False
                continue
            size = max(0, int(file_stat.st_size))
            file_path = Path(entry.path)
            total += size
            files += 1
            _record_largest_file(largest_files, size, file_path, file_stat.st_mtime_ns)
            if file_path.suffix.casefold() in VIDEO_EXTENSIONS:
                media_files += 1
                media_sizes.append(size)
    return _MeasuredEntry(
        path, "directory", total, files, media_files, stat.st_mtime_ns,
        complete=complete and not budget.truncated,
    )


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _token(
    root: Path,
    root_key: str,
    relative_path: str,
    kind: str,
    size: int,
    modified_ns: int,
    expires_at: int,
) -> str:
    material = "\0".join([
        str(root), root_key, relative_path, kind, str(int(size)),
        str(int(modified_ns)), str(int(expires_at)),
    ]).encode("utf-8")
    return hmac.new(_SIGNING_KEY, material, hashlib.sha256).hexdigest()


def _candidate(
    root: Path,
    root_key: str,
    label: str,
    measured: _MeasuredEntry,
    reason: str,
    score: float,
    expires_at: int,
) -> dict:
    relative_path = _relative(root, measured.path)
    return {
        "root": root_key,
        "root_label": label,
        "relative_path": relative_path,
        "name": measured.path.name,
        "kind": measured.kind,
        "size_bytes": measured.size,
        "file_count": measured.file_count,
        "media_file_count": measured.media_file_count,
        "modified_at": measured.modified_ns / 1_000_000_000,
        "reason": reason,
        "score": round(float(score), 2),
        "expires_at": int(expires_at),
        "token": _token(
            root, root_key, relative_path, measured.kind,
            measured.size, measured.modified_ns, expires_at,
        ),
    }


def scan_large_content(
    paths: dict[str, str],
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_files: int = DEFAULT_MAX_SCAN_FILES,
    large_file_floor_bytes: int = DEFAULT_LARGE_FILE_FLOOR,
    large_folder_floor_bytes: int = DEFAULT_LARGE_FOLDER_FLOOR,
) -> dict:
    """Analyze roots and return signed cleanup candidates without following links."""
    max_candidates = max(5, min(int(max_candidates), 80))
    max_files_per_root = max(100, int(max_files))
    scanned_files = 0
    truncated = False
    largest_files: list[tuple[int, str, int]] = []
    media_sizes: list[int] = []
    measured_roots: dict[str, tuple[Path, str, list[_MeasuredEntry]]] = {}
    seen_resolved_roots: dict[Path, str] = {}
    errors: list[dict] = []

    for root_key, label, raw_path in _configured_roots(paths):
        if not raw_path:
            continue
        try:
            root = Path(raw_path).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise NotADirectoryError(str(root))
            if root in seen_resolved_roots:
                continue
            seen_resolved_roots[root] = root_key
            entries: list[_MeasuredEntry] = []
            budget = _ScanBudget(max_files_per_root)
            for child in root.iterdir():
                if budget.truncated:
                    break
                if _hidden_or_protected(child.name) or child.is_symlink():
                    continue
                try:
                    measured = _measure_entry(child, budget, largest_files, media_sizes)
                except (OSError, ValueError):
                    continue
                if measured.complete and measured.kind in {"file", "directory"} and measured.size > 0:
                    entries.append(measured)
            measured_roots[root_key] = (root, label, entries)
            scanned_files += budget.files
            truncated = truncated or budget.truncated
        except (OSError, ValueError) as exc:
            errors.append({"root": root_key, "error": str(exc)})

    media_median = int(statistics.median(media_sizes)) if media_sizes else 0
    dynamic_file_threshold = max(
        int(large_file_floor_bytes),
        int(media_median * 2.5) if media_median else 0,
    )
    candidates: dict[tuple[str, str], dict] = {}
    expires_at = int(time.time()) + SCAN_TOKEN_TTL_SECONDS

    for root_key, (root, label, entries) in measured_roots.items():
        sizes = [entry.size for entry in entries if entry.size > 0]
        median_unit = int(statistics.median(sizes)) if sizes else 0
        ranked = sorted(entries, key=lambda item: item.size, reverse=True)
        for rank, measured in enumerate(ranked[:12], start=1):
            outlier_threshold = max(
                int(large_folder_floor_bytes),
                int(median_unit * 2.5) if median_unit else 0,
            )
            if measured.size < int(large_folder_floor_bytes) and rank > 5:
                continue
            if measured.size >= outlier_threshold and median_unit:
                reason = "Deutlich größer als vergleichbare Inhalte"
                score = measured.size / max(1, median_unit)
            elif measured.kind == "directory" and root_key == "series":
                reason = "Große Serie / Sammlung"
                score = 1.5 + max(0, 6 - rank) * 0.1
            elif measured.kind == "directory":
                reason = "Großer Medienordner"
                score = 1.4 + max(0, 6 - rank) * 0.1
            else:
                reason = "Große Mediendatei"
                score = 1.3 + max(0, 6 - rank) * 0.1
            payload = _candidate(root, root_key, label, measured, reason, score, expires_at)
            candidates[(root_key, payload["relative_path"])] = payload

    for size, raw_path, modified_ns in sorted(largest_files, reverse=True):
        path = Path(raw_path)
        if size < dynamic_file_threshold:
            continue
        matching_roots = sorted(
            measured_roots.items(), key=lambda item: len(item[1][0].parts), reverse=True,
        )
        for root_key, (root, label, _entries) in matching_roots:
            try:
                relative_path = _relative(root, path)
            except ValueError:
                continue
            measured = _MeasuredEntry(
                path=path, kind="file", size=size, file_count=1,
                media_file_count=int(path.suffix.casefold() in VIDEO_EXTENSIONS),
                modified_ns=modified_ns,
            )
            ratio = size / max(1, media_median or dynamic_file_threshold)
            payload = _candidate(
                root, root_key, label, measured,
                "Ungewöhnlich große Einzeldatei", max(2.0, ratio), expires_at,
            )
            candidates[(root_key, relative_path)] = payload
            break

    ordered = sorted(
        candidates.values(),
        key=lambda item: (item["score"], item["size_bytes"]),
        reverse=True,
    )[:max_candidates]
    return {
        "observed_at": time.time(),
        "scanned_files": scanned_files,
        "truncated": truncated,
        "media_file_median_bytes": media_median,
        "large_file_threshold_bytes": dynamic_file_threshold,
        "candidate_count": len(ordered),
        "candidates": ordered,
        "errors": errors,
    }


def _safe_target(root: Path, relative_path: str) -> tuple[Path, str]:
    pure = PurePosixPath(str(relative_path or ""))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("Ungültiger relativer Speicherpfad.")
    if any(_hidden_or_protected(part) for part in pure.parts):
        raise ValueError("Geschützte oder versteckte Pfade dürfen nicht bereinigt werden.")
    raw = root.joinpath(*pure.parts)
    if raw.is_symlink():
        raise ValueError("Symbolische Links dürfen nicht bereinigt werden.")
    target = raw.resolve(strict=True)
    if target == root or root not in target.parents:
        raise ValueError("Ziel liegt außerhalb des konfigurierten Medienordners.")
    return target, pure.as_posix()


def cleanup_candidate(
    paths: dict[str, str],
    *,
    root_key: str,
    relative_path: str,
    token: str,
    expected_size: int,
    expires_at: int,
    max_files: int = 500_000,
) -> dict:
    """Permanently delete one previously signed scan result after revalidation."""
    if int(expires_at) < int(time.time()):
        raise ValueError("Der Bereinigungstreffer ist abgelaufen. Bitte erneut scannen.")
    raw_root = str(paths.get(root_key) or "").strip()
    if root_key not in {"movies", "series"} or not raw_root:
        raise ValueError("Unbekannter oder nicht konfigurierter Speicherbereich.")
    root = Path(raw_root).expanduser().resolve(strict=True)
    target, normalized_relative = _safe_target(root, relative_path)

    budget = _ScanBudget(max(100, int(max_files)))
    largest_files: list[tuple[int, str, int]] = []
    media_sizes: list[int] = []
    measured = _measure_entry(target, budget, largest_files, media_sizes)
    if budget.truncated or not measured.complete:
        raise ValueError("Inhalt konnte nicht vollständig und sicher verifiziert werden. Bitte manuell prüfen.")
    if measured.size != int(expected_size):
        raise ValueError("Der Inhalt hat sich seit dem Scan verändert. Bitte erneut analysieren.")
    expected_token = _token(
        root, root_key, normalized_relative, measured.kind,
        measured.size, measured.modified_ns, expires_at,
    )
    if not hmac.compare_digest(str(token or ""), expected_token):
        raise ValueError("Der Bereinigungstreffer ist abgelaufen oder ungültig. Bitte erneut scannen.")

    if measured.kind == "directory":
        for current, dirnames, _filenames in os.walk(target, followlinks=False):
            current_path = Path(current)
            if current_path.is_symlink():
                raise ValueError("Ordner mit symbolischen Links werden nicht automatisch bereinigt.")
            for dirname in dirnames:
                child = current_path / dirname
                if child.is_symlink():
                    raise ValueError("Ordner mit symbolischen Links werden nicht automatisch bereinigt.")
                if dirname.casefold() in PROTECTED_NAMES:
                    raise ValueError("Aktive oder geschützte Royal-Arbeitsdaten verhindern die Bereinigung.")
        shutil.rmtree(target)
    elif measured.kind == "file":
        target.unlink()
    else:
        raise ValueError("Dieser Inhaltstyp kann nicht bereinigt werden.")
    return {
        "deleted": True,
        "root": root_key,
        "relative_path": normalized_relative,
        "freed_bytes": measured.size,
        "deleted_at": time.time(),
    }
