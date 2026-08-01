"""Laufzeit-Updates für die per pip installierte stabile yt-dlp-Version."""

import importlib.metadata
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import requests


PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
_STABLE_VERSION_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?$")
_VERSION_PREFIX_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.(\d+))?")


class YtDlpRuntimeUpdater:
    def current_version(self) -> str:
        try:
            return importlib.metadata.version("yt-dlp")
        except importlib.metadata.PackageNotFoundError:
            return ""

    def latest_release(self) -> tuple[str, frozenset[str]]:
        response = requests.get(PYPI_URL, timeout=(10, 20))
        response.raise_for_status()
        payload = response.json()
        version = str((payload.get("info") or {}).get("version") or "").strip()
        if not _STABLE_VERSION_RE.fullmatch(version):
            raise RuntimeError(f"PyPI lieferte keine gültige stabile yt-dlp-Version: {version!r}")
        hashes = frozenset(
            str((item.get("digests") or {}).get("sha256") or "").casefold()
            for item in payload.get("urls") or []
            if str(item.get("filename") or "").endswith(".whl")
        ) - {""}
        if not hashes:
            raise RuntimeError("PyPI lieferte keinen prüfbaren yt-dlp-Wheel-Hash")
        return version, hashes

    def latest_version(self) -> str:
        return self.latest_release()[0]

    def check(self) -> dict:
        current = self.current_version()
        latest, hashes = self.latest_release()
        return {
            "current": current,
            "latest": latest,
            "update_available": not current or self._version_key(latest) > self._version_key(current),
            "wheel_sha256": sorted(hashes),
        }

    def download_wheel(
        self,
        version: str,
        destination: Path,
        allowed_sha256: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> Path:
        if not _STABLE_VERSION_RE.fullmatch(str(version or "")):
            raise ValueError("Ungültige yt-dlp-Version")
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        self._run_pip([
            "download",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-deps",
            "--only-binary=:all:",
            "--dest",
            str(destination),
            f"yt-dlp=={version}",
        ], timeout=300)
        wheels = sorted(destination.glob("yt_dlp-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("yt-dlp-Wheel wurde nicht eindeutig heruntergeladen")
        allowed = {
            str(value or "").strip().casefold() for value in (allowed_sha256 or [])
            if str(value or "").strip()
        }
        if not allowed:
            raise RuntimeError("Kein freigegebener yt-dlp-Wheel-Hash vorhanden")
        digest = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
        if digest not in allowed:
            wheels[0].unlink(missing_ok=True)
            raise RuntimeError("yt-dlp-Wheel stimmt nicht mit dem PyPI-Hash überein")
        return wheels[0]

    def install_wheel(self, wheel: Path) -> None:
        wheel = Path(wheel)
        if not wheel.is_file() or wheel.suffix.casefold() != ".whl":
            raise ValueError("Ungültiges yt-dlp-Wheel")
        self._run_pip([
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-deps",
            "--upgrade",
            str(wheel),
        ], timeout=300)

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        match = _VERSION_PREFIX_RE.match(str(version or ""))
        return tuple(int(part) for part in match.groups(default="0")) if match else ()

    @staticmethod
    def _run_pip(arguments: list[str], timeout: int) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            output = (completed.stderr or completed.stdout or "pip fehlgeschlagen").strip()
            detail = " ".join(output.splitlines()[-3:])
            raise RuntimeError(f"yt-dlp-Aktualisierung fehlgeschlagen: {detail}")
