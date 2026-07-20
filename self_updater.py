"""Sicherer In-App-Updater für persistente Quellordner."""

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Callable, Optional
from urllib.parse import quote

import requests


_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 250 * 1024 * 1024
_MANIFEST_NAME = ".update_files.json"
_PROTECTED_TOP_LEVEL = {".git", "data", "downloads", "debug", "runtime"}
_PROTECTED_FILE_NAMES = {".env", ".app_commit_sha", _MANIFEST_NAME, "settings.ini"}
_ACTIVE_STATES = {"downloading", "dependencies", "installing", "restarting"}


def _in_container() -> bool:
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


def _is_persistent_container_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        fields = line.split(" - ", 1)[0].split()
        if len(fields) < 5:
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


class SelfUpdater:
    def __init__(
        self,
        repository: str,
        app_dir: Path,
        on_state: Optional[Callable[[dict], None]] = None,
        restart_callback: Optional[Callable[[], None]] = None,
        persistent_override: Optional[bool] = None,
    ):
        self.repository = repository
        self.app_dir = Path(app_dir).resolve()
        self.on_state = on_state
        self.restart_callback = restart_callback
        self.persistent_override = persistent_override
        self._lock = threading.RLock()
        self._state = "idle"
        self._message = "Bereit"
        self._target_sha = ""
        self._error = ""

    def _support(self) -> tuple[bool, str]:
        if self.persistent_override is not None:
            return self.persistent_override, "" if self.persistent_override else "Testmodus: nicht persistent"
        if os.environ.get("UPDATE_ALLOW_EPHEMERAL", "").strip().lower() in {"1", "true", "yes"}:
            return True, ""
        if not _in_container():
            return True, ""
        if _is_persistent_container_path(self.app_dir):
            return True, ""
        return False, "Der Anwendungsordner ist im Container nicht persistent gemountet."

    def status(self) -> dict:
        supported, reason = self._support()
        with self._lock:
            return {
                "state": self._state,
                "active": self._state in _ACTIVE_STATES,
                "message": self._message,
                "target_sha": self._target_sha,
                "error": self._error,
                "supported": supported,
                "reason": reason,
            }

    def is_active(self) -> bool:
        with self._lock:
            return self._state in _ACTIVE_STATES

    def _set_state(self, state: str, message: str, error: str = "") -> None:
        with self._lock:
            self._state = state
            self._message = message
            self._error = error[:500]
            payload = self.status()
        if self.on_state:
            self.on_state(payload)

    def start(self, target_sha: str) -> dict:
        target_sha = str(target_sha or "").strip()
        if not _COMMIT_RE.fullmatch(target_sha):
            raise ValueError("Ungültige GitHub-Revision")
        supported, reason = self._support()
        if not supported:
            raise RuntimeError(reason)
        try:
            with tempfile.NamedTemporaryFile(dir=self.app_dir, prefix=".update-write-", delete=True):
                pass
        except OSError as exc:
            raise RuntimeError(f"Anwendungsordner ist nicht beschreibbar: {exc}") from exc
        with self._lock:
            if self._state in _ACTIVE_STATES:
                raise RuntimeError("Ein Update läuft bereits")
            self._target_sha = target_sha
            self._state = "downloading"
            self._message = "Update wird von GitHub geladen"
            self._error = ""
            payload = self.status()
        if self.on_state:
            self.on_state(payload)
        threading.Thread(target=self._worker, args=(target_sha,), daemon=True).start()
        return payload

    def _worker(self, target_sha: str) -> None:
        try:
            self._install(target_sha)
        except Exception as exc:
            self._set_state("error", "Update fehlgeschlagen", str(exc))
            return
        self._set_state("restarting", "Update installiert – Server startet neu")
        if self.restart_callback:
            self.restart_callback()

    def _download_archive(self, target_sha: str, destination: Path) -> None:
        url = f"https://github.com/{self.repository}/archive/{quote(target_sha, safe='')}.tar.gz"
        response = requests.get(url, stream=True, timeout=(10, 60))
        response.raise_for_status()
        expected = int(response.headers.get("Content-Length") or 0)
        if expected > _MAX_ARCHIVE_BYTES:
            raise RuntimeError("GitHub-Archiv ist unerwartet groß")
        received = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > _MAX_ARCHIVE_BYTES:
                    raise RuntimeError("GitHub-Archiv überschreitet das Größenlimit")
                handle.write(chunk)
        if not received:
            raise RuntimeError("GitHub hat ein leeres Archiv geliefert")

    def _extract_archive(self, archive: Path, destination: Path) -> Path:
        extracted_bytes = 0
        with tarfile.open(archive, mode="r:gz") as bundle:
            members = bundle.getmembers()
            if len(members) > 20_000:
                raise RuntimeError("GitHub-Archiv enthält zu viele Dateien")
            for member in members:
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("Unsicherer Pfad im GitHub-Archiv")
                if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    raise RuntimeError("Nicht unterstützter Dateityp im GitHub-Archiv")
                target = destination.joinpath(*relative.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("GitHub-Archiv verlässt den Update-Ordner")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                extracted_bytes += max(0, int(member.size))
                if extracted_bytes > _MAX_EXTRACTED_BYTES:
                    raise RuntimeError("Entpacktes Update überschreitet das Größenlimit")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError("Datei im GitHub-Archiv konnte nicht gelesen werden")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
        roots = [item for item in destination.iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise RuntimeError("GitHub-Archiv besitzt keine eindeutige Projektwurzel")
        root = roots[0]
        required_files = (
            "server.py",
            "requirements.txt",
            "ui_translator.py",
            "ytdlp_updater.py",
            "web/app.js",
            "web/i18n.js",
            "update_checker.py",
            "providers/__init__.py",
            "providers/catalog.py",
            "providers/models.py",
            "providers/filmfrei24.py",
            "providers/filmpalast.py",
            "providers/moflix.py",
            "providers/einschalten.py",
            "providers/kinox.py",
            "providers/kinoger.py",
            "providers/megakino.py",
            "providers/xcine.py",
            "providers/serienstream.py",
        )
        for required in required_files:
            if not (root / required).is_file():
                raise RuntimeError(f"Update ist unvollständig: {required} fehlt")
        return root

    @staticmethod
    def _safe_relative(value: str) -> Optional[Path]:
        relative = Path(str(value).replace("\\", "/"))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            return None
        if relative.parts[0] in _PROTECTED_TOP_LEVEL or relative.name in _PROTECTED_FILE_NAMES:
            return None
        return relative

    def _source_files(self, source_root: Path) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for source in source_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_root)
            safe = self._safe_relative(relative.as_posix())
            if safe is not None:
                files[safe.as_posix()] = source
        return files

    def _load_manifest(self) -> set[str]:
        try:
            values = json.loads((self.app_dir / _MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return set()
        if not isinstance(values, list):
            return set()
        return {
            safe.as_posix()
            for value in values
            if (safe := self._safe_relative(str(value))) is not None
        }

    def _destination(self, relative: str) -> Path:
        destination = self.app_dir.joinpath(*Path(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.parent.resolve().is_relative_to(self.app_dir):
            raise RuntimeError(f"Unsicheres Update-Ziel: {relative}")
        return destination

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        temp = destination.with_name(f".{destination.name}.update-{os.getpid()}-{threading.get_ident()}")
        try:
            shutil.copy2(source, temp)
            os.replace(temp, destination)
        finally:
            try:
                temp.unlink()
            except OSError:
                pass

    @staticmethod
    def _atomic_write(destination: Path, content: str) -> None:
        temp = destination.with_name(f".{destination.name}.update-{os.getpid()}-{threading.get_ident()}")
        try:
            temp.write_text(content, encoding="utf-8")
            os.replace(temp, destination)
        finally:
            try:
                temp.unlink()
            except OSError:
                pass

    def _install_dependencies(self, source_root: Path) -> None:
        staged = source_root / "requirements.txt"
        current = self.app_dir / "requirements.txt"
        try:
            unchanged = current.read_bytes() == staged.read_bytes()
        except OSError:
            unchanged = False
        if unchanged:
            return
        self._set_state("dependencies", "Python-Abhängigkeiten werden aktualisiert")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "-r",
                str(staged),
            ],
            cwd=str(source_root),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "pip fehlgeschlagen").strip().splitlines()
            raise RuntimeError("Abhängigkeiten konnten nicht installiert werden: " + " ".join(detail[-3:]))

    def _apply_source(self, source_root: Path, target_sha: str, backup_root: Path) -> None:
        new_files = self._source_files(source_root)
        obsolete = self._load_manifest() - set(new_files)
        backups: dict[str, Path] = {}
        created: set[str] = set()
        transaction_files = set(new_files) | obsolete | {".app_commit_sha", _MANIFEST_NAME}

        for relative in transaction_files:
            destination = self._destination(relative)
            if destination.exists():
                if not destination.is_file():
                    raise RuntimeError(f"Update-Ziel ist keine Datei: {relative}")
                backup = backup_root.joinpath(*Path(relative).parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
                backups[relative] = backup
            else:
                created.add(relative)

        try:
            for relative, source in sorted(new_files.items()):
                self._atomic_copy(source, self._destination(relative))
            for relative in sorted(obsolete):
                try:
                    self._destination(relative).unlink()
                except FileNotFoundError:
                    pass
            self._atomic_write(self.app_dir / ".app_commit_sha", target_sha + "\n")
            self._atomic_write(
                self.app_dir / _MANIFEST_NAME,
                json.dumps(sorted(new_files), ensure_ascii=False, indent=2) + "\n",
            )
        except Exception:
            for relative in created:
                try:
                    self._destination(relative).unlink()
                except OSError:
                    pass
            for relative, backup in backups.items():
                self._atomic_copy(backup, self._destination(relative))
            raise

    def _repair_nodriver(self) -> None:
        command = (
            "import sys; "
            f"sys.path.insert(0, {str(self.app_dir)!r}); "
            "import nodriver_patch; nodriver_patch.ensure_cdp_utf8()"
        )
        subprocess.run(
            [sys.executable, "-c", command],
            cwd=str(self.app_dir),
            capture_output=True,
            timeout=60,
            check=False,
        )

    def _install(self, target_sha: str) -> None:
        with tempfile.TemporaryDirectory(prefix="seriendownloader-update-") as tmp:
            temp_root = Path(tmp)
            archive = temp_root / "update.tar.gz"
            extracted = temp_root / "extracted"
            backup = temp_root / "backup"
            extracted.mkdir()
            backup.mkdir()
            self._download_archive(target_sha, archive)
            source_root = self._extract_archive(archive, extracted)
            self._install_dependencies(source_root)
            self._set_state("installing", "Anwendungsdateien werden installiert")
            self._apply_source(source_root, target_sha, backup)
            self._repair_nodriver()
