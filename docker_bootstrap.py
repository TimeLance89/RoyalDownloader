"""Boot a persistent, versioned runtime with an atomic rollback path."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from runtime_release import activate_release, read_release_link, releases_dir, rollback_release


SKIP_NAMES = {".git", "data", "downloads", "debug", "runtime", "releases", "current", "previous"}


def _copy_source(source_root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for source in source_root.iterdir():
        if source.name in SKIP_NAMES or source.name.startswith(".update-write-"):
            continue
        target = destination / source.name
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, target)
        elif source.is_file():
            shutil.copy2(source, target)


def _python_for(release: Path) -> Path:
    return release / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _prepare_release(source: Path, release: Path) -> None:
    _copy_source(source, release)
    try:
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(release / ".venv")
        _smoke_release(release)
    except Exception:
        shutil.rmtree(release, ignore_errors=True)
        raise


def _smoke_release(release: Path) -> None:
    python = _python_for(release)
    completed = subprocess.run(
        [
            str(python), "-c",
            "import compileall,sys; "
            "sys.path.insert(0, sys.argv[1]); "
            "assert compileall.compile_dir(sys.argv[1], quiet=1); "
            "import config, downloader, extractor, update_checker",
            str(release),
        ],
        cwd=str(release),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "Importtest fehlgeschlagen").splitlines()
        raise RuntimeError("Runtime-Smoke-Test fehlgeschlagen: " + " ".join(detail[-3:]))


def _initial_release(bundle: Path, runtime_root: Path) -> Path:
    current = read_release_link(runtime_root, "current")
    if current is not None:
        return current
    source = runtime_root if (runtime_root / "server.py").is_file() else bundle
    marker = source / ".app_commit_sha"
    try:
        identity = marker.read_text(encoding="utf-8").strip()[:12]
    except OSError:
        identity = ""
    if not identity:
        identity = hashlib.sha256((source / "requirements.txt").read_bytes()).hexdigest()[:12]
    prefix = "legacy" if source == runtime_root else "bundled"
    release = releases_dir(runtime_root) / f"{prefix}-{identity}"
    if release.is_dir():
        try:
            _smoke_release(release)
        except Exception:
            # A hard power loss may leave the first copy or venv incomplete.
            # It was never linked as current, so rebuilding it is safe.
            shutil.rmtree(release, ignore_errors=True)
    if not release.exists():
        _prepare_release(source, release)
    activate_release(runtime_root, release)
    return release


def main() -> None:
    bundle = Path(__file__).resolve().parent
    configured = os.environ.get("APP_RUNTIME_DIR", "").strip()
    if not configured:
        os.chdir(bundle)
        os.execv(sys.executable, [sys.executable, str(bundle / "server.py")])
    runtime_root = Path(configured).resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    if "--rollback" in sys.argv:
        rollback_release(runtime_root)
    release = _initial_release(bundle, runtime_root)
    os.environ["APP_ACTIVE_RELEASE"] = str(release)
    os.environ["APP_BASE_PYTHON"] = sys.executable
    os.environ["APP_BOOTSTRAP_PATH"] = str(bundle / "docker_bootstrap.py")
    python = _python_for(release)
    os.chdir(release)
    os.execv(str(python), [str(python), str(release / "server.py")])


if __name__ == "__main__":
    main()
