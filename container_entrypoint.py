"""Fail-closed startup checks for the unprivileged Docker runtime."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _assert_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".royal-write-test-", dir=path):
        pass


def smoke_check() -> None:
    if hasattr(os, "getuid") and os.getuid() == 0:
        raise RuntimeError("Royal Downloader darf im Container nicht als root laufen")
    required = (
        Path(os.environ.get("APP_RUNTIME_DIR", "/runtime")),
        Path(os.environ.get("SERIENDL_DATA_DIR", "/app/data")),
        Path(os.environ.get("DOWNLOAD_DIR", "/movies")),
        Path(os.environ.get("SERIES_DIR", "/serien")),
    )
    for path in required:
        try:
            _assert_writable(path)
        except OSError as exc:
            raise RuntimeError(
                f"Container-Benutzer {os.getuid()} kann nicht nach {path} schreiben; "
                "PUID/PGID oder Besitzrechte des Mounts korrigieren"
            ) from exc


def main() -> None:
    smoke_check()
    bootstrap = Path(__file__).resolve().with_name("docker_bootstrap.py")
    os.execv(sys.executable, [sys.executable, str(bootstrap)])


if __name__ == "__main__":
    main()
