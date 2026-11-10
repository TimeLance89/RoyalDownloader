"""Side-effect controlled installation engine for RoyalDownloader.

No target changes are made during discovery and preflight. Both install paths
are fresh-install only. Existing directories, Docker stacks, and media files
must never be overwritten or recursively chowned by the installer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

Progress = Callable[[str], None]

PROJECT_NAME = "royaldownloader-easy"
MEDIA_PORT = 8765
SUPPORTED_NAS_ARCH = {"x86_64", "amd64"}
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$")
USER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.-]{0,63}$")
NAS_PATH_RE = re.compile(r"^/[a-zA-Z0-9_./ -]+$")
ENV_PATCH = {
    "JELLYFIN_URL": "",
    "JELLYFIN_API_KEY": "",
    "SEERR_ENABLED": "false",
    "UPDATE_CHANNEL": "stable",
    "UPDATE_GITHUB_BRANCH": "main",
    "UPDATE_MODE": "manual",
}


class InstallError(RuntimeError):
    """A recoverable, user-facing installation error."""


@dataclass(frozen=True)
class SourcePackage:
    archive: Path
    sha256: str
    ref: str
    commit: str


@dataclass(frozen=True)
class NasConfig:
    host: str
    port: int
    username: str
    project_path: str
    movies_path: str
    series_path: str
    password: str = ""
    private_key_path: str = ""


@dataclass(frozen=True)
class WindowsConfig:
    install_path: Path
    movies_path: Path
    series_path: Path
    python_executable: str = ""


def validate_nas(cfg: NasConfig, *, require_auth: bool = True) -> None:
    if not HOST_RE.fullmatch(cfg.host.strip()) or ":" in cfg.host:
        raise InstallError("NAS-Adresse: Bitte Hostname oder IPv4-Adresse eingeben (keine URL).")
    if not 1 <= cfg.port <= 65535:
        raise InstallError("Der SSH-Port muss zwischen 1 und 65535 liegen.")
    if not USER_RE.fullmatch(cfg.username):
        raise InstallError("Ungültiger SSH-Benutzername.")
    for label, value in (("Projektordner", cfg.project_path),
                         ("Filmordner", cfg.movies_path),
                         ("Serienordner", cfg.series_path)):
        if not NAS_PATH_RE.fullmatch(value) or ".." in PurePosixPath(value).parts or "//" in value:
            raise InstallError(f"{label}: Nur absolute, einfache Linux-Pfade ohne '..' verwenden.")
        if value.endswith("/") or value in ("/", "/root", "/etc", "/usr", "/var", "/home"):
            raise InstallError(f"{label}: Dieser Systempfad ist nicht zulässig.")
    if cfg.project_path == cfg.movies_path or cfg.project_path == cfg.series_path:
        raise InstallError("Programmordner und Medienordner müssen getrennt sein.")
    if cfg.movies_path.startswith(cfg.project_path + "/") or cfg.series_path.startswith(cfg.project_path + "/"):
        raise InstallError("Die Medien dürfen nicht innerhalb des App-Projektordners liegen.")
    if require_auth:
        if cfg.private_key_path and cfg.password:
            raise InstallError("Entweder SSH-Schlüssel oder Passwort verwenden, nicht beides.")
        if not cfg.password and not cfg.private_key_path:
            raise InstallError("Bitte SSH-Passwort oder Schlüsseldatei wählen.")


def validate_windows(cfg: WindowsConfig) -> None:
    base = cfg.install_path.expanduser().absolute()
    if not base.is_absolute() or base == Path(base.anchor) or base.name.strip() in ("", ".", ".."):
        raise InstallError("Bitte einen eigenen Programmordner auswählen.")
    if base.exists():
        raise InstallError("Der Programmordner existiert bereits. Bitte für die Neuinstallation einen neuen Ordner wählen.")
    for label, location in (("Filmordner", cfg.movies_path), ("Serienordner", cfg.series_path)):
        if not location.is_absolute() or location == Path(location.anchor):
            raise InstallError(f"{label}: Bitte einen absoluten Ordner statt eines Laufwerks angeben.")
        if base == location or base in location.parents:
            raise InstallError(f"{label}: Nicht innerhalb des Programmordners speichern.")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def packaged_source(kind: str) -> SourcePackage:
    if kind not in {"zip", "tar"}:
        raise ValueError("unsupported package kind")
    frozen = getattr(sys, "_MEIPASS", None)
    folder = (Path(frozen) / "installer" / "assets") if frozen else (Path(__file__).resolve().parent / "assets")
    manifest_file = folder / "source-manifest.json"
    if not manifest_file.is_file():
        raise InstallError("Quellpaket fehlt. Bitte die offizielle vollständige Installer-EXE verwenden.")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    filename = "royal-source.zip" if kind == "zip" else "royal-source.tar.gz"
    expected = manifest.get("archives", {}).get(filename, "")
    archive = folder / filename
    if not archive.is_file() or not re.fullmatch("[0-9a-f]{64}", expected):
        raise InstallError(f"Installationsarchiv fehlt oder hat keine Prüfsumme: {filename}.")
    digest = sha256_file(archive)
    if digest != expected:
        raise InstallError(f"Prüfsumme stimmt nicht: {filename}. Nichts wurde installiert.")
    if manifest.get("ref") not in ("overnight", "main", "stable") or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("commit", "")):
        raise InstallError("Ungültiges Versionsmanifest im Installationspaket.")
    return SourcePackage(archive, digest, manifest["ref"], manifest["commit"])


def _archive_entry(name: str) -> Path:
    normalized = name.replace("\\", "/")
    target = PurePosixPath(normalized)
    if (not normalized or normalized.startswith("/") or ":" in normalized or
            any(part in ("..", "") for part in target.parts)):
        raise InstallError(f"Unsicherer Archivpfad: {name}")
    return Path(*target.parts)


def extract_source_zip(archive: Path, dest: Path) -> None:
    """Extract only ordinary files/directories; reject Zip Slip and links."""
    with zipfile.ZipFile(archive) as source:
        bad = source.testzip()
        if bad:
            raise InstallError(f"Beschädigtes Quellarchiv: {bad}")
        for member in source.infolist():
            rel = _archive_entry(member.filename)
            mode = member.external_attr >> 16
            if ((mode & 0o170000) == 0o120000):
                raise InstallError("Symbolische Links im Quellarchiv sind nicht erlaubt.")
            file = dest / rel
            if member.is_dir():
                file.mkdir(parents=True, exist_ok=True)
            else:
                file.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as src, file.open("xb") as out:
                    shutil.copyfileobj(src, out)


def verify_source_tar(archive: Path) -> None:
    """Validate Git archive before sending to a remote NAS."""
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            _archive_entry(member.name)
            if not (member.isfile() or member.isdir()):
                raise InstallError(f"Unsicherer Archivtyp im NAS-Paket: {member.name}")


def generate_setup_token() -> str:
    return "RD-" + secrets.token_urlsafe(24)


def render_env(template: str, values: dict[str, str]) -> str:
    """Edit known keys without discarding other .env template defaults."""
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise InstallError("Ungültiger Umgebungsvariablenname.")
        if any(x in value for x in "\r\n\x00$#'\""):
            raise InstallError(f"Umgebungsvariable {key} enthält nicht unterstützte Sonderzeichen.")
    output = []
    used = set()
    for line in template.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match and match.group(1) in values:
            key = match.group(1)
            output.append(f"{key}={values[key]}")
            used.add(key)
        else:
            output.append(line)
    for key in sorted(values.keys() - used):
        output.append(f"{key}={values[key]}")
    return "\n".join(output).rstrip() + "\n"


def windows_env(template: str, cfg: WindowsConfig, token: str) -> str:
    return render_env(template, {
        "ROYAL_DEPLOYMENT_MODE": "desktop",
        "HOST": "127.0.0.1", "ROYAL_BIND_ADDRESS": "127.0.0.1", "OPEN_BROWSER": "1", "DNS_OVERRIDE": "0",
        "MOVIES_HOST_DIR": str(cfg.movies_path), "SERIES_HOST_DIR": str(cfg.series_path),
        "DOWNLOAD_DIR": str(cfg.movies_path), "SERIES_DIR": str(cfg.series_path),
        "ROYAL_SETUP_TOKEN": token, **ENV_PATCH,
    })


def nas_env(template: str, cfg: NasConfig, token: str, uid: int, gid: int) -> str:
    return render_env(template, {
        "ROYAL_DEPLOYMENT_MODE": "nas", "HOST": "0.0.0.0", "OPEN_BROWSER": "0",
        "ROYAL_BIND_ADDRESS": "0.0.0.0", "PUID": str(uid), "PGID": str(gid),
        "MOVIES_HOST_DIR": cfg.movies_path, "SERIES_HOST_DIR": cfg.series_path,
        "DOWNLOAD_DIR": "/movies", "SERIES_DIR": "/serien",
        "ROYAL_SETUP_TOKEN": token, **ENV_PATCH,
    })


def python_version(exe: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run([exe, "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                                capture_output=True, text=True, timeout=10, check=True)
        major, minor = (int(n) for n in result.stdout.strip().split("."))
        return major, minor
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def find_python_312() -> str | None:
    if os.name != "nt":
        return sys.executable if sys.version_info[:2] == (3, 12) else None
    options = []
    launcher = shutil.which("py")
    if launcher:
        # The Windows 'py' launcher is special: accept it only with -3.12.
        try:
            p = subprocess.run([launcher, "-3.12", "-c", "import sys; print(sys.executable)"],
                               capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                options.append(p.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    options += [shutil.which("python3.12"), shutil.which("python")]
    # A WinGet-installed Python may not yet be visible in the current process
    # PATH, but registry-based discovery works without reboot/reopening Setup.
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\Python\PythonCore\3.12\InstallPath") as key:
                    install_dir = winreg.QueryValueEx(key, "")[0]
                    options.append(str(Path(install_dir) / "python.exe"))
            except OSError:
                continue
    except ImportError:
        pass
    for path in options:
        if path and python_version(path) == (3, 12):
            return path
    return None


def install_prerequisites_via_winget(report: Progress, python=True, browser=True, ffmpeg=True):
    """Explicit opt-in, official WinGet package IDs; never invoked by preflight."""
    if os.name != "nt":
        raise InstallError("WinGet ist ausschließlich für Windows vorgesehen.")
    winget = shutil.which("winget")
    if not winget:
        raise InstallError("Windows Package Manager (winget) ist nicht vorhanden. Bitte Python 3.12, Chrome und FFmpeg manuell installieren.")
    packages = []
    if python and not find_python_312():
        packages.append(("Python 3.12", "Python.Python.3.12"))
    if browser and not (shutil.which("chrome") or any(Path(p, "Google/Chrome/Application/chrome.exe").exists()
                    for p in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                              os.environ.get("LOCALAPPDATA", "")) if p)):
        packages.append(("Google Chrome", "Google.Chrome"))
    if ffmpeg and not shutil.which("ffmpeg"):
        packages.append(("FFmpeg", "Gyan.FFmpeg"))
    for label, package in packages:
        report(f"Installiere {label} über den Windows Package Manager …")
        result = subprocess.run([winget, "install", "--id", package, "--exact", "--source", "winget",
                                 "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"],
                                text=True, capture_output=True, timeout=1200)
        if result.returncode:
            raise InstallError(f"WinGet konnte {label} nicht installieren (Exit {result.returncode}). "
                               "Du kannst die Voraussetzung manuell nachinstallieren.")
    if python and not find_python_312():
        raise InstallError("WinGet meldet Erfolg, aber Python 3.12 wurde noch nicht gefunden. "
                           "Bitte das Setup neu starten oder Python 3.12 manuell auswählen.")
    return [label for label, _ in packages]


def preflight_windows(cfg: WindowsConfig) -> dict[str, object]:
    validate_windows(cfg)
    interpreter = cfg.python_executable or find_python_312()
    if not interpreter or python_version(interpreter) != (3, 12):
        raise InstallError("Python 3.12 fehlt. Bitte Python 3.12 installieren (inklusive py-Launcher).")
    if not shutil.which("git"):
        pass  # No Git needed: exact source package is bundled.
    free = shutil.disk_usage(cfg.install_path.anchor or cfg.install_path.parent).free
    if free < 2 * 1024 ** 3:
        raise InstallError("Auf dem Installationslaufwerk sollten mindestens 2 GiB frei sein.")
    browser = bool(shutil.which("chrome") or shutil.which("chromium") or any(
        Path(os.environ.get(v, ""), "Google/Chrome/Application/chrome.exe").exists()
        for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
        if os.environ.get(v)))
    ffmpeg = bool(shutil.which("ffmpeg"))
    return {"python": interpreter, "chrome": browser, "ffmpeg": ffmpeg,
            "free_gib": round(free / 1024 ** 3, 1)}


def install_windows(cfg: WindowsConfig, source: SourcePackage, report: Progress,
                    run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict[str, str]:
    if os.name != "nt":
        raise InstallError("Die lokale Windows-Installation kann nur unter Windows ausgeführt werden.")
    if source.archive.suffix != ".zip":
        raise InstallError("Falsches Quellpaket für Windows.")
    info = preflight_windows(cfg)
    token = generate_setup_token()
    base = cfg.install_path
    # Verify/extract into an unique sibling before making any final target.
    stage = base.parent / ("." + base.name + ".install-" + secrets.token_hex(5))
    report("Quellpaket wird anhand der SHA-256-Prüfsumme geprüft …")
    committed = False
    try:
        stage.mkdir(parents=True, exist_ok=False)
        extract_source_zip(source.archive, stage)
        template = (stage / ".env.example").read_text(encoding="utf-8")
        (stage / ".env").write_text(windows_env(template, cfg, token), encoding="utf-8")
        (stage / "data").mkdir(exist_ok=True)
        launcher = ('@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
                    '"%~dp0.venv\\Scripts\\python.exe" "%~dp0server.py"\r\n'
                    'if errorlevel 1 pause\r\n')
        (stage / "RoyalDownloader starten.cmd").write_text(launcher, encoding="utf-8")
        for folder in (cfg.movies_path, cfg.series_path):
            folder.mkdir(parents=True, exist_ok=True)
        if base.exists():
            raise InstallError("Zielordner wurde während der Installation angelegt. Nichts überschrieben.")
        stage.rename(base)
        committed = True
        # Virtualenvs contain absolute paths and Windows entrypoints and MUST NOT
        # be created in a staging directory that is later renamed.
        report("Eigene Python-Umgebung wird im endgültigen Ordner erstellt …")
        run([info["python"], "-m", "venv", str(base / ".venv")], check=True)
        exe = base / ".venv" / "Scripts" / "python.exe"
        if not exe.exists():
            raise InstallError("Python hat keine gültige virtuelle Umgebung erstellt.")
        report("Abhängigkeiten werden in der isolierten Umgebung installiert …")
        run([str(exe), "-m", "pip", "install", "--disable-pip-version-check", "-r",
             str(base / "requirements.lock")], cwd=base, check=True)
        report("Installation abgeschlossen. Programmdateien sind bereit.")
        return {"url": "http://127.0.0.1:8765", "token": token, "path": str(base),
                "launcher": str(base / "RoyalDownloader starten.cmd"),
                "missing_optional": ", ".join(k for k in ("chrome", "ffmpeg") if not info[k])}
    except (OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        extra = (f" Der frisch angelegte Ordner {base} bleibt für die Diagnose erhalten; "
                 "es wurden keine bestehenden Dateien überschrieben." if committed else "")
        raise InstallError(f"Windows-Installation fehlgeschlagen: {exc}.{extra}") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def key_fingerprint(key) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def known_hosts_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config") / "RoyalDownloader"
    base.mkdir(parents=True, exist_ok=True)
    return base / "known_hosts"


def host_label(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


class NasSession:
    """SSH transport with explicit, persistently pinned host identity."""

    def __init__(self, cfg: NasConfig):
        self.cfg = cfg
        self.client = None

    def probe_key(self) -> tuple[str, str]:
        import paramiko
        validate_nas(self.cfg, require_auth=False)
        transport = paramiko.Transport((self.cfg.host, self.cfg.port))
        try:
            transport.start_client(timeout=12)
            key = transport.get_remote_server_key()
            if key is None:
                raise InstallError("NAS hat keinen SSH-Hostschlüssel gesendet.")
            hosts = paramiko.HostKeys()
            p = known_hosts_path()
            if p.exists():
                hosts.load(str(p))
            label = host_label(self.cfg.host, self.cfg.port)
            known = hosts.lookup(label)
            if known and key.get_name() in known and known[key.get_name()] != key:
                raise InstallError("SSH-HOSTSCHLÜSSEL GEÄNDERT! Verbindung abgebrochen. NAS separat überprüfen.")
            if known and key.get_name() not in known:
                raise InstallError("SSH-Hostschlüsseltyp hat sich geändert. Verbindung abgebrochen.")
            return key.get_name(), key_fingerprint(key)
        except (OSError, EOFError, paramiko.SSHException) as exc:
            raise InstallError(f"SSH-Hostschlüssel konnte nicht geprüft werden: {exc}") from exc
        finally:
            transport.close()

    def trust_and_connect(self, confirmed_fingerprint: str):
        import paramiko
        kind, actual = self.probe_key()
        if not confirmed_fingerprint or not secrets.compare_digest(actual, confirmed_fingerprint):
            raise InstallError("Der bestätigte SSH-Fingerabdruck stimmt nicht überein.")
        # Probe again through a live transport, and pin the same public key.
        transport = paramiko.Transport((self.cfg.host, self.cfg.port))
        try:
            transport.start_client(timeout=12)
            key = transport.get_remote_server_key()
            if key.get_name() != kind or not secrets.compare_digest(key_fingerprint(key), confirmed_fingerprint):
                raise InstallError("Der NAS-Hostschlüssel hat sich seit der Prüfung geändert.")
            hosts = paramiko.HostKeys()
            path = known_hosts_path()
            if path.exists():
                hosts.load(str(path))
            label = host_label(self.cfg.host, self.cfg.port)
            previous = hosts.lookup(label)
            if previous and (kind not in previous or previous[kind] != key):
                raise InstallError("Gespeicherter SSH-Schlüssel stimmt nicht mehr überein.")
            hosts.add(label, kind, key)
            # Pin after fingerprint confirmation; never use AutoAddPolicy.
            hosts.save(str(path))
            transport.close()
            client = paramiko.SSHClient()
            client.load_host_keys(str(path))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            kwargs = {"hostname": self.cfg.host, "port": self.cfg.port, "username": self.cfg.username,
                      "timeout": 15, "auth_timeout": 15, "banner_timeout": 15, "allow_agent": False,
                      "look_for_keys": False}
            if self.cfg.private_key_path:
                kwargs["key_filename"] = self.cfg.private_key_path
            else:
                kwargs["password"] = self.cfg.password
            client.connect(**kwargs)
            self.client = client
            return self
        except Exception:
            transport.close()
            raise

    def exec(self, command: str, timeout: float = 60, sensitive: bool = False) -> str:
        if self.client is None:
            raise InstallError("Keine bestätigte SSH-Verbindung vorhanden.")
        _stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        channel = stdout.channel
        output, errors = bytearray(), bytearray()
        deadline = time.monotonic() + timeout
        # Read stdout AND stderr at once: a long `docker compose build` may
        # otherwise deadlock on a full SSH stderr buffer while stdout.read()
        # is still waiting. Keep only a bounded tail for diagnostics.
        while True:
            ready = channel.recv_ready()
            error_ready = channel.recv_stderr_ready()
            if ready:
                output.extend(channel.recv(32768))
                if len(output) > 32768:
                    del output[:-32768]
            if error_ready:
                errors.extend(channel.recv_stderr(32768))
                if len(errors) > 32768:
                    del errors[:-32768]
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            if time.monotonic() > deadline:
                channel.close()
                raise InstallError("Der NAS-Befehl hat das Zeitlimit erreicht. "
                                   "Eine bereits laufende Docker-Aktion kann noch aktiv sein.")
            if not ready and not error_ready:
                time.sleep(0.08)
        code = channel.recv_exit_status()
        result = output.decode("utf-8", errors="replace")
        error = errors.decode("utf-8", errors="replace")
        if code:
            detail = "Prüfung fehlgeschlagen. Bitte NAS-Docker-Protokoll prüfen." if sensitive else error.strip()[:900]
            if "permission denied" in error.lower() and "docker" in command:
                detail = "SSH-Benutzer hat keine Docker-Berechtigung. Ohne sudo-Dauerrechte einrichten."
            raise InstallError(f"NAS-Befehl fehlgeschlagen (Exit {code}): {detail}")
        return result.strip()

    def put(self, local: Path, remote: str, mode: int = 0o600) -> None:
        if self.client is None:
            raise InstallError("Keine SSH-Verbindung vorhanden.")
        with self.client.open_sftp() as sftp:
            sftp.put(str(local), remote, confirm=True)
            sftp.chmod(remote, mode)

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None


def preflight_nas(cfg: NasConfig, session: NasSession) -> dict[str, object]:
    validate_nas(cfg)
    info = session.exec("set -eu; command -v docker >/dev/null; docker compose version; "
                        "docker info --format '{{.ServerVersion}}' >/dev/null; "
                        "command -v tar >/dev/null; command -v sha256sum >/dev/null; command -v curl >/dev/null; "
                        "uname -m; id -u; id -g; df -Pk / | tail -1",
                        timeout=20).splitlines()
    if len(info) < 5:
        raise InstallError("NAS-Voraussetzungen konnten nicht vollständig ermittelt werden.")
    arch = info[-4].strip()
    if arch not in SUPPORTED_NAS_ARCH:
        raise InstallError(f"NAS-Architektur {arch} ist noch nicht für den Installer freigegeben (nur x86_64).")
    uid, gid = int(info[-3]), int(info[-2])
    if uid == 0 or gid == 0:
        raise InstallError("Bitte mit einem normalen SSH-Benutzer anmelden, nicht als root.")
    paths = [cfg.project_path, cfg.movies_path, cfg.series_path]
    project, movies, series = map(shlex.quote, paths)
    # Test parent of new installation and MEDIA read/write, never change their permissions.
    session.exec(f"set -eu; test ! -e {project}; "
                 f"test -d {shlex.quote(str(PurePosixPath(cfg.project_path).parent))}; "
                 f"test -w {shlex.quote(str(PurePosixPath(cfg.project_path).parent))}; "
                 f"test -d {movies}; test -w {movies}; "
                 f"test -d {series}; test -w {series}; "
                 "! docker ps -a --format '{{.Names}}' | grep -Eq '^(seriendownloader|royal-browser)$'; "
                 "! docker compose ls --format json | grep -q '\"Name\":\"royaldownloader-easy\"'",
                 timeout=30)
    usage = session.exec(f"df -Pk {shlex.quote(str(PurePosixPath(cfg.project_path).parent))} | tail -1").split()
    if len(usage) < 4 or int(usage[3]) < 2 * 1024 * 1024:
        raise InstallError("Auf dem NAS-Installationsvolume sollten mindestens 2 GiB frei sein.")
    # Test port availability through docker listings and /proc/net/tcp; final compose start also enforces it.
    if session.exec("(command -v ss >/dev/null && ss -ltnH '( sport = :8765 )') || true"):
        raise InstallError("TCP-Port 8765 ist auf dem NAS bereits belegt.")
    return {"architecture": arch, "uid": uid, "gid": gid, "free_gib": round(int(usage[3])/1024**2, 1)}


def install_nas(cfg: NasConfig, session: NasSession, source: SourcePackage,
                report: Progress) -> dict[str, str]:
    if not source.archive.name.endswith(".tar.gz"):
        raise InstallError("Falsches Quellpaket für NAS.")
    verify_source_tar(source.archive)
    info = preflight_nas(cfg, session)
    token = generate_setup_token()
    parent = str(PurePosixPath(cfg.project_path).parent)
    stage = f"{parent}/.royal-staging-{secrets.token_hex(8)}"
    qstage, qtarget = shlex.quote(stage), shlex.quote(cfg.project_path)
    # Remote operations only affect the unique staged project and its newly created target.
    report("Projektordner und vorhandene Docker-Container wurden geprüft.")
    stage_created = False
    committed = False
    try:
        session.exec(f"set -eu; test ! -e {qstage}; test ! -e {qtarget}; mkdir -m 700 {qstage}")
        stage_created = True
        remote_archive = stage + "/royal-source.tar.gz"
        report("Verifiziertes Quellpaket wird verschlüsselt über SSH übertragen …")
        session.put(source.archive, remote_archive)
        actual = session.exec(f"sha256sum {shlex.quote(remote_archive)} | cut -d' ' -f1")
        if not secrets.compare_digest(actual, source.sha256):
            raise InstallError("NAS-Archivprüfung fehlgeschlagen. Keine Dateien installiert.")
        session.exec(f"set -eu; tar -xzf {shlex.quote(remote_archive)} -C {qstage} "
                     "--no-same-owner --no-same-permissions; "
                     f"rm -- {shlex.quote(remote_archive)}; mkdir -p {qstage}/data {qstage}/runtime")
        # Read template from locally bundled archive, don't trust arbitrary server files.
        with tarfile.open(source.archive, "r:gz") as tar:
            member = tar.extractfile(".env.example")
            if member is None:
                raise InstallError(".env.example fehlt im Installationspaket.")
            template = member.read().decode("utf-8")
        contents = nas_env(template, cfg, token, info["uid"], info["gid"])
        with tempfile.TemporaryDirectory(prefix="royal-env-") as tempdir:
            env_file = Path(tempdir) / ".env"
            env_file.write_text(contents, encoding="utf-8")
            session.put(env_file, stage + "/.env", 0o600)
        report("Docker-Konfiguration wird geprüft …")
        session.exec(f"set -eu; cd {qstage}; docker compose -p {PROJECT_NAME} config --quiet", timeout=40)
        # Publish only after complete staged validation; no existing target is removed.
        session.exec(f"set -eu; test ! -e {qtarget}; mv -- {qstage} {qtarget}")
        committed = True
        report("Docker-Images werden erstellt und die Royal-Dienste gestartet …")
        session.exec(f"set -eu; cd {qtarget}; docker compose -p {PROJECT_NAME} up -d --build seriendownloader",
                     timeout=3600, sensitive=True)
        report("Warte auf den Gesundheitscheck des Dienstes …")
        for attempt in range(18):
            try:
                response = session.exec("curl -fsS --max-time 4 http://127.0.0.1:8765/api/health", timeout=8)
                if '"ok"' in response or '"status"' in response:
                    break
            except InstallError:
                pass
            time.sleep(5)
        else:
            raise InstallError("Container wurde gestartet, aber der Gesundheitscheck blieb erfolglos. "
                               f"Projekt bleibt zur Fehlerdiagnose unter {cfg.project_path} erhalten.")
        return {"url": f"http://{cfg.host}:{MEDIA_PORT}", "token": token, "path": cfg.project_path,
                "launcher": "docker compose -p royaldownloader-easy logs -f seriendownloader"}
    finally:
        if stage_created and not committed:
            try:
                session.exec(f"test ! -e {qtarget} && rm -rf -- {qstage} || true", timeout=30)
            except InstallError:
                pass
