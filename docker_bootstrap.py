"""Startet im Docker-Image einen persistenten, selbst aktualisierbaren Quellstand."""

import os
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _copy_initial_runtime(bundle: Path, runtime: Path) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    if (runtime / "server.py").is_file():
        return
    for source in bundle.iterdir():
        if source.name in {".git", "data", "downloads", "debug", "runtime"}:
            continue
        destination = runtime / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, destination)


def _install_runtime_requirements(bundle: Path, runtime: Path) -> None:
    bundled = bundle / "requirements.txt"
    active = runtime / "requirements.txt"
    if not active.is_file() or (bundled.is_file() and active.read_bytes() == bundled.read_bytes()):
        return
    digest = hashlib.sha256(active.read_bytes()).hexdigest()
    marker = Path(tempfile.gettempdir()) / "seriendownloader-runtime-requirements"
    try:
        if marker.read_text(encoding="utf-8").strip() == digest:
            return
    except OSError:
        pass
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", str(active)],
        check=True,
    )
    marker.write_text(digest + "\n", encoding="utf-8")


def main() -> None:
    bundle = Path(__file__).resolve().parent
    configured = os.environ.get("APP_RUNTIME_DIR", "").strip()
    runtime = Path(configured).resolve() if configured else bundle
    if runtime != bundle:
        _copy_initial_runtime(bundle, runtime)
        _install_runtime_requirements(bundle, runtime)
    os.chdir(runtime)
    os.execv(sys.executable, [sys.executable, str(runtime / "server.py")])


if __name__ == "__main__":
    main()
