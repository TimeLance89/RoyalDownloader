"""Boot a persistent, versioned runtime with an atomic rollback path."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from runtime_release import (
    activate_release,
    read_release_link,
    releases_dir,
    rollback_release,
)
try:
    from runtime_release import prune_releases
except ImportError:
    # Übergang von älteren NAS-Ständen: Wird docker_bootstrap.py vor
    # runtime_release.py kopiert, darf der Container nicht in einer
    # Neustartschleife hängen. Bereinigung ist optional und folgt nach dem
    # vollständigen Kopieren automatisch mit der neuen Runtime-Version.
    def prune_releases(_runtime_root: Path) -> list[Path]:
        return []

SKIP_NAMES = {
    ".git", ".downloading", "#recycle", "__pycache__", "data", "downloads",
    "debug", "runtime", "releases", "current", "previous", ".venv",
    ".pytest_cache", ".ruff_cache", ".bundle_identity", ".nas-update",
}
BUNDLE_IDENTITY_FILE = ".bundle_identity"
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def _valid_commit(value: str) -> str:
    value = str(value or "").strip()
    return value if COMMIT_RE.fullmatch(value) else ""


def _source_commit(source: Path) -> str:
    """Read a source revision without importing application dependencies."""
    for key in ("APP_COMMIT_SHA", "GIT_COMMIT", "SOURCE_COMMIT"):
        if commit := _valid_commit(os.environ.get(key, "")):
            return commit
    git_dir = source / ".git"
    if git_dir.is_file():
        try:
            raw = git_dir.read_text(encoding="utf-8").strip()
            if raw.startswith("gitdir:"):
                git_dir = (source / raw.split(":", 1)[1].strip()).resolve()
        except OSError:
            git_dir = source / ".git"
    if git_dir.is_dir():
        try:
            head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        except OSError:
            head = ""
        if commit := _valid_commit(head):
            return commit
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            try:
                if commit := _valid_commit((git_dir / ref).read_text(encoding="utf-8")):
                    return commit
            except OSError:
                pass
            try:
                for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
                    commit, _, packed_ref = line.partition(" ")
                    if packed_ref == ref and (valid := _valid_commit(commit)):
                        return valid
            except OSError:
                pass
    for filename in (".app_commit_sha", "BUILD_COMMIT"):
        try:
            if commit := _valid_commit((source / filename).read_text(encoding="utf-8")):
                return commit
        except OSError:
            pass
    return ""


def _copy_source(source_root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for source in source_root.iterdir():
        if (
            source.name in SKIP_NAMES
            or source.name.startswith((".update-write-", ".nas-update-staging."))
        ):
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
    source_commit = _source_commit(source)
    if source_commit:
        (release / ".app_commit_sha").write_text(source_commit + "\n", encoding="utf-8")
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
            (
                "import compileall,sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "assert compileall.compile_dir(sys.argv[1], quiet=1); "
                "import config, downloader, extractor, update_checker"
            ),
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


def _source_identity(source: Path) -> str:
    """Return a stable identity even when a mounted checkout has no build marker."""
    digest = hashlib.sha256()
    for candidate in sorted(source.rglob("*")):
        relative = candidate.relative_to(source)
        if any(part in SKIP_NAMES or part == "__pycache__" for part in relative.parts):
            continue
        if not candidate.is_file() or candidate.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(candidate.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _bundle_identity(runtime_root: Path) -> str:
    try:
        return (runtime_root / BUNDLE_IDENTITY_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _remember_bundle_identity(runtime_root: Path, identity: str) -> None:
    target = runtime_root / BUNDLE_IDENTITY_FILE
    temporary = runtime_root / f".{BUNDLE_IDENTITY_FILE}.new-{os.getpid()}"
    try:
        temporary.write_text(identity + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _initial_release(bundle: Path, runtime_root: Path) -> Path:
    source = runtime_root if (runtime_root / "server.py").is_file() else bundle
    marker = source / ".app_commit_sha"
    try:
        identity = marker.read_text(encoding="utf-8").strip()[:12]
    except OSError:
        identity = ""
    source_identity = _source_identity(source)
    identity = f"{identity}-{source_identity}" if identity else source_identity
    prefix = "legacy" if source == runtime_root else "bundled"
    current = read_release_link(runtime_root, "current")
    if current is not None:
        if source == runtime_root:
            return current
        # Das Bundle ist die manuell aufs NAS kopierte Projektfassung. Bleibt
        # es unverändert, darf ein In-App-Update in ``current`` aktiv bleiben.
        # Ändert sich das Bundle, ist die Kopie absichtlich neu und wird als
        # geprüftes Release aktiviert. Ältere Installationen ohne Marker
        # synchronisieren beim ersten Start mit dieser Bootstrap-Version einmal.
        if _bundle_identity(runtime_root) == identity:
            print(f"[bootstrap] Runtime bleibt aktiv: {current.name}", flush=True)
            return current
        print(
            f"[bootstrap] Neue kopierte Projektfassung erkannt: bundled-{identity}",
            flush=True,
        )
    release = releases_dir(runtime_root) / f"{prefix}-{identity}"
    if release.is_dir():
        try:
            _smoke_release(release)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            # A hard power loss may leave the first copy or venv incomplete.
            # It was never linked as current, so rebuilding it is safe.
            shutil.rmtree(release, ignore_errors=True)
    if not release.exists():
        _prepare_release(source, release)
    activate_release(runtime_root, release)
    if source != runtime_root:
        _remember_bundle_identity(runtime_root, identity)
    print(f"[bootstrap] Runtime aktiviert: {release.name}", flush=True)
    return release


def main() -> None:
    bundle = Path(__file__).resolve().parent
    os.environ["APP_SOURCE_DIR"] = str(bundle)
    configured = os.environ.get("APP_RUNTIME_DIR", "").strip()
    if not configured:
        os.chdir(bundle)
        os.execv(sys.executable, [sys.executable, str(bundle / "server.py")])
    runtime_root = Path(configured).resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    if "--rollback" in sys.argv:
        rollback_release(runtime_root)
    release = _initial_release(bundle, runtime_root)
    try:
        prune_releases(runtime_root)
    except OSError:
        pass
    os.environ["APP_ACTIVE_RELEASE"] = str(release)
    os.environ["APP_BASE_PYTHON"] = sys.executable
    os.environ["APP_BOOTSTRAP_PATH"] = str(bundle / "docker_bootstrap.py")
    python = _python_for(release)
    os.chdir(release)
    os.execv(str(python), [str(python), str(release / "server.py")])


if __name__ == "__main__":
    main()
