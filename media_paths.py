"""Validation and recovery helpers for persistent media directories."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

from runtime_paths import in_container, persistent_container_path


def prepare_media_directory(
    raw_path: str,
    label: str,
    *,
    in_container_check: Callable[[], bool] = in_container,
    persistent_path_check: Callable[[Path], bool] = persistent_container_path,
) -> dict:
    """Validate that a media directory is persistent, writable and usable."""
    path = Path(raw_path).expanduser()
    if in_container_check() and not persistent_path_check(path):
        env_name = "SERIES_DIR" if "Serie" in label else "DOWNLOAD_DIR"
        expected = os.environ.get(env_name, "").strip()
        suggestion = (
            f" Verwende den gemounteten Containerpfad {expected}."
            if expected
            else ""
        )
        raise HTTPException(
            400,
            f"{label} liegt nicht auf einem persistenten Docker-Mount.{suggestion}",
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise OSError("Pfad ist kein Ordner")
        with tempfile.NamedTemporaryFile(
            prefix=".royal-write-test-",
            dir=path,
            delete=True,
        ) as probe:
            probe.write(b"ok")
            probe.flush()
            os.fsync(probe.fileno())
        usage = shutil.disk_usage(path)
    except OSError as exc:
        raise HTTPException(400, f"{label} ist nicht beschreibbar: {exc}") from exc
    if usage.free < 512 * 1024 * 1024:
        raise HTTPException(400, f"{label} hat weniger als 512 MB freien Speicher.")
    return {"path": str(path), "free": usage.free}


def _recovery_destination(target: Path, relative: Path) -> Path:
    destination = target / relative
    if not destination.exists():
        return destination
    for number in range(1, 1000):
        candidate = destination.with_name(
            f"{destination.stem}~recovered-{number}{destination.suffix}",
        )
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Kein freier Wiederherstellungsname für {relative}")


def recover_misplaced_media(
    label: str,
    old_path: str,
    effective_path: str,
    *,
    persistent_path_check: Callable[[Path], bool] = persistent_container_path,
) -> dict:
    """Copy completed media out of an unsafe container layer without deleting it."""
    source = Path(old_path).expanduser().resolve(strict=False)
    target = Path(effective_path).expanduser().resolve(strict=False)
    result = {
        "label": label,
        "source": str(source),
        "target": str(target),
        "copied": 0,
        "errors": [],
    }
    if (
        source == target
        or not source.is_dir()
        or persistent_path_check(source)
        or not persistent_path_check(target)
    ):
        return result
    suffixes = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
    episode_pattern = re.compile(
        r"(?:^|[. _-])s\d{1,2}e\d{1,3}(?:$|[. _-])",
        re.IGNORECASE,
    )
    for media in source.rglob("*"):
        try:
            relative = media.relative_to(source)
            looks_like_episode = bool(
                episode_pattern.search(media.stem)
                or any(
                    re.match(
                        r"^(?:staffel|season|s)\s*0*\d+\b",
                        part,
                        re.IGNORECASE,
                    )
                    for part in relative.parts[:-1]
                )
            )
            if (
                not media.is_file()
                or media.is_symlink()
                or media.suffix.casefold() not in suffixes
                or ".downloading" in relative.parts
                or (label == "Serien" and not looks_like_episode)
                or (label == "Filme" and looks_like_episode)
            ):
                continue
            exact_destination = target / relative
            if (
                exact_destination.is_file()
                and exact_destination.stat().st_size == media.stat().st_size
            ):
                continue
            destination = _recovery_destination(target, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_name(
                f".{destination.name}.recover-{uuid.uuid4().hex}",
            )
            try:
                shutil.copy2(media, temp)
                # Windows requires a writable descriptor for fsync().
                with temp.open("rb+") as handle:
                    os.fsync(handle.fileno())
                if temp.stat().st_size != media.stat().st_size:
                    raise OSError("Wiederherstellungskopie ist unvollständig")
                os.link(temp, destination)
                temp.unlink()
                result["copied"] += 1
            finally:
                temp.unlink(missing_ok=True)
        except OSError as exc:
            result["errors"].append(f"{media}: {exc}")
    return result
