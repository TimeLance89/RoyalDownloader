"""
Zentrale Auflösung des Verzeichnisses für persistenten App-State.

Damit dieselbe Codebasis unverändert unter Windows (Entwicklung) UND in einem
Docker-Container (NAS, 24/7) läuft, wird der Ablageort für persistente Dateien
(Cookies, Hoster-Intel, Einstellungen/Watchlist) über eine Umgebungsvariable
gesteuert:

    SERIENDL_DATA_DIR   – Zielordner für persistenten State (z.B. ein Docker-
                          Volume wie /app/data). Ist er NICHT gesetzt, bleibt das
                          bisherige Verhalten erhalten (Dateien neben dem Code).

Der Download-Zielordner ist NICHT hier, sondern in config.py (DOWNLOAD_DIR) –
er ist eine eigene, im UI änderbare Nutzereinstellung.
"""

import os
from pathlib import Path

_PROJECT_DIR = Path(__file__).parent.resolve()


def in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/1/cgroup").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _decode_mount_path(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def persistent_container_path(path: Path) -> bool:
    """Whether ``path`` resides on a non-root container mount.

    A writable directory in Docker's overlay layer is not a valid media target:
    it disappears when the container is recreated and is invisible to Jellyfin.
    """
    if not in_container():
        return True
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if len(fields) < 5:
            continue
        filesystem = after.split()[0] if separator and after.split() else ""
        if filesystem in {
            "tmpfs", "proc", "sysfs", "devpts", "mqueue", "cgroup", "cgroup2",
            "squashfs", "ramfs",
        }:
            continue
        target = Path(_decode_mount_path(fields[4]))
        if target == Path("/"):
            continue
        try:
            if resolved == target or resolved.is_relative_to(target):
                return True
        except (OSError, ValueError):
            continue
    return False


def data_dir() -> Path:
    """Verzeichnis für persistenten App-State. Über SERIENDL_DATA_DIR steuerbar;
    Default = Projektordner (unverändertes Verhalten ohne die Variable)."""
    env = os.environ.get("SERIENDL_DATA_DIR", "").strip()
    base = Path(env) if env else _PROJECT_DIR
    if env:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return base
