"""Atomic activation primitives for versioned application runtimes."""

from __future__ import annotations

import os
import re
from pathlib import Path


RELEASE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def releases_dir(runtime_root: Path) -> Path:
    path = Path(runtime_root).resolve() / "releases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _release_target(runtime_root: Path, release: Path) -> Path:
    root = Path(runtime_root).resolve()
    target = Path(release).resolve()
    if not target.is_relative_to(releases_dir(root)) or not target.is_dir():
        raise RuntimeError("Release liegt außerhalb des versionierten Runtime-Ordners")
    return target


def read_release_link(runtime_root: Path, name: str) -> Path | None:
    root = Path(runtime_root).resolve()
    link = root / name
    if not link.is_symlink():
        return None
    try:
        target = link.resolve(strict=True)
    except OSError:
        return None
    try:
        return _release_target(root, target)
    except RuntimeError:
        return None


def atomic_release_link(runtime_root: Path, name: str, release: Path) -> None:
    root = Path(runtime_root).resolve()
    target = _release_target(root, release)
    temporary = root / f".{name}.new-{os.getpid()}"
    try:
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target.relative_to(root), target_is_directory=True)
        os.replace(temporary, root / name)
    finally:
        temporary.unlink(missing_ok=True)


def activate_release(runtime_root: Path, release: Path) -> Path | None:
    """Switch current in one rename; keep the old complete runtime as previous."""
    root = Path(runtime_root).resolve()
    new_release = _release_target(root, release)
    old_release = read_release_link(root, "current")
    if old_release == new_release:
        return old_release
    if old_release is not None:
        atomic_release_link(root, "previous", old_release)
    atomic_release_link(root, "current", new_release)
    return old_release


def rollback_release(runtime_root: Path) -> Path:
    root = Path(runtime_root).resolve()
    current = read_release_link(root, "current")
    previous = read_release_link(root, "previous")
    if previous is None:
        raise RuntimeError("Kein vorheriges Runtime-Release für Rollback vorhanden")
    atomic_release_link(root, "current", previous)
    if current is not None:
        atomic_release_link(root, "previous", current)
    return previous
