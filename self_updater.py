"""Sicherer In-App-Updater für persistente Quellordner."""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Optional
from urllib.parse import quote

import requests


logger = logging.getLogger(__name__)

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 250 * 1024 * 1024
_MANIFEST_NAME = ".update_files.json"
_BACKUP_META_NAME = "meta.json"
_PROTECTED_TOP_LEVEL = {".git", "data", "downloads", "debug", "runtime"}
_PROTECTED_FILE_NAMES = {".env", ".app_commit_sha", _MANIFEST_NAME, "settings.ini"}
_ACTIVE_STATES = {"downloading", "verifying", "dependencies", "installing", "restarting", "restoring"}


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


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
        state_dir: Optional[Path] = None,
    ):
        self.repository = repository
        self.app_dir = Path(app_dir).resolve()
        self.on_state = on_state
        self.restart_callback = restart_callback
        self.persistent_override = persistent_override
        self.state_dir = Path(state_dir) if state_dir else self._default_state_dir()
        self._lock = threading.RLock()
        self._state = "idle"
        self._message = "Bereit"
        self._target_sha = ""
        self._error = ""

    def _default_state_dir(self) -> Path:
        """Backup + Audit-Log liegen im persistenten Datenverzeichnis;
        ``data`` gehört zu den geschützten Pfaden, die Updates nie anfassen."""
        env = os.environ.get("SERIENDL_DATA_DIR", "").strip()
        base = Path(env) if env else (self.app_dir / "data")
        return base / "FilmeDownloader"

    @property
    def _backup_root(self) -> Path:
        return self.state_dir / "update_backup"

    @property
    def _audit_path(self) -> Path:
        return self.state_dir / "update_audit.log"

    def _audit(self, event: str, **details) -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(), "event": event}
        entry.update(details)
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self._audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Update-Audit-Log nicht schreibbar: %s", exc)

    def _read_current_sha(self) -> str:
        try:
            value = (self.app_dir / ".app_commit_sha").read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return value if _COMMIT_RE.fullmatch(value) else ""

    def _read_backup_meta(self) -> dict:
        try:
            meta = json.loads(
                (self._backup_root / _BACKUP_META_NAME).read_text(encoding="utf-8"),
            )
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(meta, dict) or meta.get("restored"):
            return {}
        return meta

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
        meta = self._read_backup_meta()
        with self._lock:
            return {
                "state": self._state,
                "active": self._state in _ACTIVE_STATES,
                "message": self._message,
                "target_sha": self._target_sha,
                "error": self._error,
                "supported": supported,
                "reason": reason,
                "rollback_available": bool(meta.get("replaced") or meta.get("created")),
                "rollback_sha": str(meta.get("previous_sha") or ""),
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
            self._audit("install_failed", target_sha=target_sha, error=str(exc)[:300])
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

    def _github_api_json(self, path: str) -> dict:
        response = requests.get(
            f"https://api.github.com/repos/{self.repository}/{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Royal-Downloader-Updater",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub-API lieferte eine ungültige Antwort")
        return payload

    def _expected_tree(self, target_sha: str) -> dict:
        commit = self._github_api_json(f"commits/{quote(target_sha, safe='')}")
        tree_sha = str(((commit.get("commit") or {}).get("tree") or {}).get("sha") or "")
        if not _COMMIT_RE.fullmatch(tree_sha):
            raise RuntimeError("GitHub lieferte keinen gültigen Commit-Tree")
        tree = self._github_api_json(f"git/trees/{quote(tree_sha, safe='')}?recursive=1")
        if tree.get("truncated"):
            raise RuntimeError("GitHub-Tree ist zu groß für die Verifikation")
        expected: dict = {}
        for item in tree.get("tree") or []:
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            if str(item.get("mode") or "") == "120000":
                raise RuntimeError("Update enthält symbolische Links")
            relative = str(item.get("path") or "")
            sha = str(item.get("sha") or "")
            if not relative or not _COMMIT_RE.fullmatch(sha):
                raise RuntimeError("GitHub-Tree enthält ungültige Einträge")
            expected[relative] = sha.lower()
        if not expected:
            raise RuntimeError("GitHub-Tree ist leer")
        return expected

    def _verify_source_against_tree(self, source_root: Path, target_sha: str) -> None:
        """Verifiziert das codeload-Archiv unabhängig über api.github.com.

        Jede entpackte Datei muss exakt dem Git-Blob des Ziel-Commits
        entsprechen; das Dateiset muss vollständig übereinstimmen. Damit kann
        ein manipuliertes oder unvollständiges Archiv nicht installiert
        werden, solange nicht beide Auslieferungswege gleichzeitig dieselbe
        Fälschung liefern. Fehler brechen das Update ab (fail closed).
        """
        expected = self._expected_tree(target_sha)
        actual = {
            path.relative_to(source_root).as_posix(): path
            for path in source_root.rglob("*")
            if path.is_file()
        }
        missing = sorted(set(expected) - set(actual))
        if missing:
            raise RuntimeError(f"Update-Archiv ist unvollständig: {missing[0]} fehlt")
        unexpected = sorted(set(actual) - set(expected))
        if unexpected:
            raise RuntimeError(f"Update-Archiv enthält unerwartete Datei: {unexpected[0]}")
        for relative, sha in expected.items():
            content = actual[relative].read_bytes()
            if _git_blob_sha(content) == sha:
                continue
            # git archive liefert eol=crlf-Dateien (.bat/.cmd/.ps1 laut
            # .gitattributes) mit CRLF aus, der Blob speichert LF.
            if _git_blob_sha(content.replace(b"\r\n", b"\n")) == sha:
                continue
            raise RuntimeError(f"Integritätsfehler im Update-Archiv: {relative}")

    @staticmethod
    def _verify_staged_python(source_root: Path) -> None:
        """Syntaxprüfung aller Python-Dateien VOR der Installation.

        compile() führt keinen Code aus; ein defektes oder nur teilweise
        ausgeliefertes Update wird abgelehnt, bevor es Dateien ersetzt.
        """
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(source_root).as_posix()
            try:
                compile(path.read_bytes(), relative, "exec")
            except (SyntaxError, ValueError) as exc:
                raise RuntimeError(
                    f"Update enthält fehlerhaften Python-Code: {relative} ({exc})"
                ) from exc

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
        self._audit("dependencies_updated", requirements="requirements.txt")

    def _apply_source(
        self, source_root: Path, target_sha: str, backup_root: Path,
    ) -> tuple[dict, set]:
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
        return backups, created

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

    def _prepare_backup_root(self) -> Path:
        root = self._backup_root
        if root.exists():
            shutil.rmtree(root)
        files_root = root / "files"
        files_root.mkdir(parents=True)
        return files_root

    def _write_backup_meta(
        self, previous_sha: str, target_sha: str, backups: dict, created: set,
    ) -> None:
        meta = {
            "previous_sha": previous_sha,
            "target_sha": target_sha,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "replaced": sorted(backups),
            "created": sorted(created),
            "restored": False,
        }
        (self._backup_root / _BACKUP_META_NAME).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    def _install(self, target_sha: str) -> None:
        previous_sha = self._read_current_sha()
        self._audit("update_started", target_sha=target_sha, repository=self.repository)
        with tempfile.TemporaryDirectory(prefix="seriendownloader-update-") as tmp:
            temp_root = Path(tmp)
            archive = temp_root / "update.tar.gz"
            extracted = temp_root / "extracted"
            extracted.mkdir()
            self._download_archive(target_sha, archive)
            source_root = self._extract_archive(archive, extracted)
            self._set_state("verifying", "Update wird gegen GitHub verifiziert")
            try:
                self._verify_source_against_tree(source_root, target_sha)
                self._verify_staged_python(source_root)
            except Exception as exc:
                self._audit(
                    "verification_failed", target_sha=target_sha, error=str(exc)[:300],
                )
                raise
            self._audit("verification_ok", target_sha=target_sha)
            self._install_dependencies(source_root)
            self._set_state("installing", "Anwendungsdateien werden installiert")
            backup_files_root = self._prepare_backup_root()
            backups, created = self._apply_source(source_root, target_sha, backup_files_root)
            self._write_backup_meta(previous_sha, target_sha, backups, created)
            self._repair_nodriver()
        self._audit(
            "install_completed", previous_sha=previous_sha, target_sha=target_sha,
        )

    # ── Rollback auf die letzte funktionierende Version ─────────────────────

    @staticmethod
    def _rollback_safe_relative(value: str) -> Optional[Path]:
        """Wie ``_safe_relative``, erlaubt aber die Update-Markerdateien.

        ``meta.json`` gilt als nicht vertrauenswürdige Eingabe: Pfade dürfen
        weder den Anwendungsordner verlassen noch geschützte Laufzeitdaten
        (.env, settings.ini, data/, downloads/) berühren.
        """
        relative = Path(str(value).replace("\\", "/"))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            return None
        if relative.parts[0] in _PROTECTED_TOP_LEVEL:
            return None
        if relative.name in {".env", "settings.ini"}:
            return None
        return relative

    def rollback(self) -> dict:
        """Stellt die vor dem letzten Update gesicherten Dateien wieder her.

        Python-Abhängigkeiten werden dabei NICHT zurückgestuft; die
        wiederhergestellte requirements.txt greift erst bei der nächsten
        regulären Installation.
        """
        meta = self._read_backup_meta()
        if not meta.get("replaced") and not meta.get("created"):
            raise RuntimeError("Kein Rollback verfügbar")
        with self._lock:
            if self._state in _ACTIVE_STATES:
                raise RuntimeError("Ein Update läuft bereits")
            self._state = "restoring"
            self._message = "Letzte funktionierende Version wird wiederhergestellt"
            self._target_sha = str(meta.get("previous_sha") or "")
            self._error = ""
            payload = self.status()
        if self.on_state:
            self.on_state(payload)
        threading.Thread(target=self._rollback_worker, args=(meta,), daemon=True).start()
        return payload

    def _rollback_worker(self, meta: dict) -> None:
        try:
            self._perform_rollback(meta)
        except Exception as exc:
            self._audit("rollback_failed", error=str(exc)[:300])
            self._set_state("error", "Rollback fehlgeschlagen", str(exc))
            return
        self._set_state("restarting", "Rollback abgeschlossen – Server startet neu")
        if self.restart_callback:
            self.restart_callback()

    def _perform_rollback(self, meta: dict) -> None:
        restore_sha = str(meta.get("previous_sha") or "")
        self._audit(
            "rollback_started",
            restore_sha=restore_sha,
            rolled_back_sha=str(meta.get("target_sha") or ""),
        )
        files_root = self._backup_root / "files"
        planned: list = []
        for value in meta.get("replaced") or []:
            relative = self._rollback_safe_relative(str(value))
            if relative is None:
                raise RuntimeError(f"Unsicherer Rollback-Pfad: {value}")
            source = files_root.joinpath(*relative.parts)
            if not source.is_file():
                raise RuntimeError(f"Rollback-Sicherung fehlt: {value}")
            planned.append((relative, source))
        for relative, source in planned:
            self._atomic_copy(source, self._destination(relative.as_posix()))
        for value in meta.get("created") or []:
            relative = self._rollback_safe_relative(str(value))
            if relative is None:
                raise RuntimeError(f"Unsicherer Rollback-Pfad: {value}")
            try:
                self.app_dir.joinpath(*relative.parts).unlink()
            except FileNotFoundError:
                pass
        meta["restored"] = True
        (self._backup_root / _BACKUP_META_NAME).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        self._repair_nodriver()
        self._audit("rollback_completed", restored_sha=restore_sha)
