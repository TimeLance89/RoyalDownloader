"""Guarded move planning and execution for media across configured volumes."""

from __future__ import annotations

import hmac
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from storage_manager import (
    PROTECTED_NAMES,
    _ScanBudget,
    _measure_entry,
    _safe_target,
    _token,
)

LOCATION_MODE_MEDIA = "media"
_CUSTOM_PREFIX = "location:"
_MOVE_VERIFY_MAX_FILES = 500_000
_MIN_FREE_RESERVE = 64 * 1024 * 1024


@dataclass(frozen=True)
class _Root:
    key: str
    label: str
    path: Path
    token_key: str
    role: str


@dataclass(frozen=True)
class _ValidatedMove:
    source_root: _Root
    source: Path
    source_kind: str
    source_name: str
    size: int
    candidate_path: str


def _custom_root_key(location_id: str) -> str:
    return f"{_CUSTOM_PREFIX}{location_id}"


def _resolved_directory(raw_path: str) -> Path:
    root = Path(str(raw_path or "").strip()).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    return root


def _root_for_key(
    media_paths: dict[str, str],
    locations: list[dict],
    root_key: str,
) -> _Root:
    key = str(root_key or "").strip()
    if key == "movies":
        return _Root("movies", "Filme", _resolved_directory(media_paths.get("movies", "")), "movies", "movies")
    if key == "series":
        return _Root("series", "Serien", _resolved_directory(media_paths.get("series", "")), "series", "series")
    if not key.startswith(_CUSTOM_PREFIX):
        raise ValueError("Unbekannter oder nicht konfigurierter Speicherbereich.")
    location_id = key[len(_CUSTOM_PREFIX):]
    location = next((item for item in locations if str(item.get("id") or "") == location_id), None)
    if not location or location.get("mode") != LOCATION_MODE_MEDIA:
        raise ValueError("Dieser Speicherort ist nicht für Medienaktionen freigegeben.")
    return _Root(
        key,
        str(location.get("label") or "Medienspeicher"),
        _resolved_directory(location.get("path", "")),
        "movies",
        "custom",
    )


def _candidate_measurement(
    root: _Root,
    relative_path: str,
    *,
    token: str,
    expected_size: int,
    expires_at: int,
):
    if int(expires_at) < int(time.time()):
        raise ValueError("Der Scan-Treffer ist abgelaufen. Bitte erneut analysieren.")
    target, normalized_relative = _safe_target(root.path, relative_path)
    budget = _ScanBudget(_MOVE_VERIFY_MAX_FILES)
    measured = _measure_entry(target, budget, [], [])
    if budget.truncated or not measured.complete:
        raise ValueError("Inhalt konnte nicht vollständig und sicher verifiziert werden.")
    if measured.size != int(expected_size):
        raise ValueError("Der Inhalt hat sich seit dem Scan verändert. Bitte erneut analysieren.")
    expected_token = _token(
        root.path,
        root.token_key,
        normalized_relative,
        measured.kind,
        measured.size,
        measured.modified_ns,
        int(expires_at),
    )
    if not hmac.compare_digest(str(token or ""), expected_token):
        raise ValueError("Der Scan-Treffer ist abgelaufen oder ungültig. Bitte erneut analysieren.")
    return target, normalized_relative, measured


def _top_level_target(root: _Root, candidate: Path, normalized_relative: str, candidate_kind: str) -> tuple[Path, str]:
    pure = PurePosixPath(normalized_relative)
    if root.role == "series":
        top = root.path / pure.parts[0]
        if not top.is_dir():
            raise ValueError("Serien können nur als vollständiger Serienordner verschoben werden.")
        return top.resolve(strict=True), "series"
    if root.role == "movies":
        if candidate_kind != "file" or len(pure.parts) != 1:
            raise ValueError("Filme werden als einzelne Filmdatei verschoben. Dieser Treffer ist kein Film auf oberster Ebene.")
        return candidate, "movie"

    top = root.path / pure.parts[0]
    top = top.resolve(strict=True)
    if top.is_dir():
        return top, "series"
    if candidate_kind == "file" and top == candidate:
        return candidate, "movie"
    raise ValueError("Dieser Treffer kann nicht eindeutig als Filmdatei oder Serienordner verschoben werden.")


def _guard_source_tree(source: Path) -> None:
    if source.is_symlink():
        raise ValueError("Symbolische Links werden nicht automatisch verschoben.")
    if source.is_file():
        return
    for current, dirnames, filenames in os.walk(source, followlinks=False):
        current_path = Path(current)
        if current_path.is_symlink():
            raise ValueError("Ordner mit symbolischen Links werden nicht automatisch verschoben.")
        for name in dirnames + filenames:
            child = current_path / name
            if child.is_symlink():
                raise ValueError("Inhalte mit symbolischen Links werden nicht automatisch verschoben.")
            if name.casefold() in PROTECTED_NAMES:
                raise ValueError("Aktive oder geschützte Royal-Arbeitsdaten verhindern das Verschieben.")


def _measure_move_source(source: Path):
    budget = _ScanBudget(_MOVE_VERIFY_MAX_FILES)
    measured = _measure_entry(source, budget, [], [])
    if budget.truncated or not measured.complete:
        raise ValueError("Der zu verschiebende Inhalt ist zu groß oder konnte nicht vollständig geprüft werden.")
    if measured.kind not in {"file", "directory"}:
        raise ValueError("Dieser Inhaltstyp kann nicht verschoben werden.")
    return measured


def _validate_move_source(
    media_paths: dict[str, str],
    locations: list[dict],
    *,
    root_key: str,
    relative_path: str,
    token: str,
    expected_size: int,
    expires_at: int,
) -> _ValidatedMove:
    root = _root_for_key(media_paths, locations, root_key)
    candidate, normalized_relative, candidate_measure = _candidate_measurement(
        root,
        relative_path,
        token=token,
        expected_size=expected_size,
        expires_at=expires_at,
    )
    source, source_kind = _top_level_target(
        root,
        candidate,
        normalized_relative,
        candidate_measure.kind,
    )
    if source == root.path or root.path not in source.parents:
        raise ValueError("Zu verschiebender Inhalt liegt außerhalb des freigegebenen Medienordners.")
    _guard_source_tree(source)
    measured = _measure_move_source(source)
    if source_kind == "series" and measured.kind != "directory":
        raise ValueError("Serien müssen als vollständiger Ordner verschoben werden.")
    if source_kind == "movie" and measured.kind != "file":
        raise ValueError("Filme müssen als einzelne Datei verschoben werden.")
    return _ValidatedMove(
        source_root=root,
        source=source,
        source_kind=source_kind,
        source_name=source.name,
        size=measured.size,
        candidate_path=normalized_relative,
    )


def _root_candidates(media_paths: dict[str, str], locations: list[dict], source_kind: str) -> list[_Root]:
    keys = ["series"] if source_kind == "series" else ["movies"]
    roots: list[_Root] = []
    for key in keys:
        try:
            roots.append(_root_for_key(media_paths, locations, key))
        except (OSError, ValueError):
            pass
    for location in locations:
        if location.get("mode") != LOCATION_MODE_MEDIA:
            continue
        try:
            roots.append(_root_for_key(media_paths, locations, _custom_root_key(str(location.get("id") or ""))))
        except (OSError, ValueError):
            continue
    return roots


def _volume_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    usage = shutil.disk_usage(path)
    return int(stat.st_dev), int(usage.total)


def _path_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _target_payload(source: _ValidatedMove, target: _Root) -> dict:
    usage = shutil.disk_usage(target.path)
    destination = target.path / source.source_name
    same_volume = _volume_signature(source.source_root.path) == _volume_signature(target.path)
    overlaps = _path_overlap(source.source_root.path, target.path)
    collision = destination.exists() or destination.is_symlink()
    reserve = min(max(_MIN_FREE_RESERVE, int(source.size * 0.01)), 2 * 1024 * 1024 * 1024)
    required = source.size + reserve
    free = int(usage.free)
    eligible = not same_volume and not overlaps and not collision and free >= required
    if same_volume:
        reason = "Liegt auf demselben physischen Volume."
    elif overlaps:
        reason = "Quell- und Zielpfad überlappen sich."
    elif collision:
        reason = f"Im Ziel existiert bereits „{source.source_name}“."
    elif free < required:
        reason = "Nicht genügend freier Speicher für einen sicheren Transfer."
    else:
        reason = ""
    return {
        "root": target.key,
        "label": target.label,
        "path": str(target.path),
        "destination": str(destination),
        "free_bytes": free,
        "required_bytes": required,
        "eligible": eligible,
        "reason": reason,
    }


def plan_move_candidate(
    media_paths: dict[str, str],
    locations: list[dict],
    *,
    root_key: str,
    relative_path: str,
    token: str,
    expected_size: int,
    expires_at: int,
) -> dict:
    source = _validate_move_source(
        media_paths,
        locations,
        root_key=root_key,
        relative_path=relative_path,
        token=token,
        expected_size=expected_size,
        expires_at=expires_at,
    )
    targets = [
        _target_payload(source, target)
        for target in _root_candidates(media_paths, locations, source.source_kind)
        if target.key != source.source_root.key
    ]
    return {
        "source_root": source.source_root.key,
        "source_label": source.source_root.label,
        "source_name": source.source_name,
        "source_kind": source.source_kind,
        "source_path": str(source.source),
        "size_bytes": source.size,
        "targets": targets,
        "eligible_target_count": sum(1 for item in targets if item["eligible"]),
    }


def _cleanup_failed_partial(partial: Path, source: Path) -> None:
    if not source.exists() or not partial.exists():
        return
    try:
        if partial.is_dir() and not partial.is_symlink():
            shutil.rmtree(partial)
        else:
            partial.unlink()
    except OSError:
        pass


def move_candidate(
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
    source = _validate_move_source(
        media_paths,
        locations,
        root_key=root_key,
        relative_path=relative_path,
        token=token,
        expected_size=expected_size,
        expires_at=expires_at,
    )
    target = _root_for_key(media_paths, locations, destination_root)
    if source.source_kind == "series" and target.role == "movies":
        raise ValueError("Serien können nicht in den Filmordner verschoben werden.")
    if source.source_kind == "movie" and target.role == "series":
        raise ValueError("Filme können nicht in den Serienordner verschoben werden.")
    target_state = _target_payload(source, target)
    if not target_state["eligible"]:
        raise ValueError(target_state["reason"] or "Dieses Ziel ist für das Verschieben nicht verfügbar.")

    destination = target.path / source.source_name
    partial = target.path / f".royal-move-{uuid.uuid4().hex}.partial"
    if partial.exists() or partial.is_symlink():
        raise ValueError("Temporärer Verschiebepfad ist bereits belegt.")

    try:
        shutil.move(str(source.source), str(partial))
        if not partial.exists():
            raise OSError("Transfer wurde nicht vollständig im Ziel angelegt.")
        os.replace(partial, destination)
    except Exception as exc:
        if source.source.exists():
            _cleanup_failed_partial(partial, source.source)
        elif partial.exists() and not destination.exists():
            raise OSError(
                f"Verschieben konnte nicht abgeschlossen werden. Die Daten liegen sicher unter {partial}."
            ) from exc
        raise

    if source.source.exists():
        raise OSError("Quelle ist nach dem Verschieben weiterhin vorhanden. Vorgang wird als fehlgeschlagen gewertet.")
    if not destination.exists():
        raise OSError("Zieldaten konnten nach dem Verschieben nicht bestätigt werden.")

    final = _measure_move_source(destination)
    if final.size != source.size:
        raise OSError("Zielgröße stimmt nach dem Verschieben nicht mit der geprüften Quelle überein.")
    return {
        "moved": True,
        "source_root": source.source_root.key,
        "destination_root": target.key,
        "source_kind": source.source_kind,
        "name": source.source_name,
        "moved_bytes": source.size,
        "destination_path": str(destination),
        "completed_at": time.time(),
    }
