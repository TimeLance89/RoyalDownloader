"""Vergleicht den lokalen Build mit dem neuesten Stand des GitHub-Repositories."""

import hashlib
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests


DEFAULT_REPOSITORY = "TimeLance89/SerienDownloader"
DEFAULT_BRANCH = "main"
RECENT_COMMIT_SCAN_LIMIT = 5
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def _valid_commit(value: str) -> str:
    value = str(value or "").strip()
    return value if _COMMIT_RE.fullmatch(value) else ""


def _detect_git_commit(root: Path) -> str:
    marker = root / ".git"
    if marker.is_file():
        try:
            raw = marker.read_text(encoding="utf-8").strip()
            if raw.startswith("gitdir:"):
                marker = (root / raw.split(":", 1)[1].strip()).resolve()
        except OSError:
            return ""
    if not marker.is_dir():
        return ""
    try:
        head = (marker / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    direct = _valid_commit(head)
    if direct:
        return direct
    if not head.startswith("ref:"):
        return ""
    ref = head.split(":", 1)[1].strip()
    try:
        direct = _valid_commit((marker / ref).read_text(encoding="utf-8").strip())
        if direct:
            return direct
    except OSError:
        pass
    try:
        for line in (marker / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.startswith(("#", "^")):
                continue
            commit, _, packed_ref = line.partition(" ")
            if packed_ref == ref:
                return _valid_commit(commit)
    except OSError:
        pass
    return ""


def detect_local_commit(app_dir: Optional[Path] = None) -> str:
    """Liest die Build-Revision aus Marker, Umgebung oder Git-Checkout."""
    root = Path(app_dir or Path(__file__).resolve().parent)
    for filename in (".app_commit_sha", "BUILD_COMMIT"):
        try:
            commit = _valid_commit((root / filename).read_text(encoding="utf-8"))
        except OSError:
            commit = ""
        if commit:
            return commit
    for key in ("APP_COMMIT_SHA", "GIT_COMMIT", "SOURCE_COMMIT"):
        commit = _valid_commit(os.environ.get(key, ""))
        if commit:
            return commit
    return _detect_git_commit(root)


def write_build_commit_marker(app_dir: Optional[Path] = None) -> str:
    """Schreibt die beim Image-Build erkannte Revision in den Anwendungsordner."""
    root = Path(app_dir or Path(__file__).resolve().parent)
    commit = next((
        value
        for key in ("APP_COMMIT_SHA", "GIT_COMMIT", "SOURCE_COMMIT")
        if (value := _valid_commit(os.environ.get(key, "")))
    ), "")
    commit = commit or _detect_git_commit(root) or detect_local_commit(root)
    if not commit:
        return ""
    try:
        (root / ".app_commit_sha").write_text(commit + "\n", encoding="utf-8")
    except OSError:
        return ""
    return commit


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


class UpdateChecker:
    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        branch: str = DEFAULT_BRANCH,
        app_dir: Optional[Path] = None,
        cache_seconds: int = 600,
    ):
        self.repository = (
            repository
            if re.fullmatch(r"[\w.-]+/[\w.-]+", repository)
            else DEFAULT_REPOSITORY
        )
        self.branch = branch.strip() or DEFAULT_BRANCH
        self.app_dir = Path(app_dir or Path(__file__).resolve().parent)
        self.cache_seconds = max(0, int(cache_seconds))
        self._cache: Optional[dict] = None
        self._cache_time = 0.0
        self._lock = threading.Lock()
        self._inferred_commit = self._read_inferred_commit()
        self._inferred_verified = False

    def _inferred_marker_path(self) -> Optional[Path]:
        explicit = os.environ.get("UPDATE_INSTALLED_COMMIT_FILE", "").strip()
        if explicit:
            return Path(explicit)
        data_root = os.environ.get("SERIENDL_DATA_DIR", "").strip()
        if data_root:
            return Path(data_root) / "FilmeDownloader" / "installed_commit"
        return None

    def _read_inferred_commit(self) -> str:
        marker = self._inferred_marker_path()
        if marker is None:
            return ""
        try:
            return _valid_commit(marker.read_text(encoding="utf-8"))
        except OSError:
            return ""

    def _remember_inferred_commit(self, commit: str) -> None:
        commit = _valid_commit(commit)
        if not commit:
            return
        self._inferred_commit = commit
        self._inferred_verified = True
        marker = self._inferred_marker_path()
        if marker is None:
            return
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(commit + "\n", encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _commit_tree_sha(commit_payload: dict) -> str:
        commit_data = commit_payload.get("commit") or {}
        tree_data = commit_data.get("tree") or {}
        return _valid_commit(tree_data.get("sha", ""))

    def _source_matches_tree(self, tree_payload: dict) -> bool:
        """Vergleicht Git-Blobs ohne lokale .git-Metadaten (NAS/ZIP-Deployment)."""
        if tree_payload.get("truncated"):
            return False
        entries = [
            item for item in tree_payload.get("tree", [])
            if isinstance(item, dict) and item.get("type") == "blob"
        ]
        if not entries:
            return False
        root = self.app_dir.resolve()
        for item in entries:
            relative = str(item.get("path") or "").replace("\\", "/")
            expected = _valid_commit(item.get("sha", ""))
            parts = tuple(part for part in relative.split("/") if part)
            if not expected or not parts or any(part in (".", "..") for part in parts):
                return False
            local_path = root.joinpath(*parts)
            try:
                if not local_path.is_file() or not local_path.resolve().is_relative_to(root):
                    return False
                content = local_path.read_bytes()
            except OSError:
                return False
            if _git_blob_sha(content) != expected:
                return False
        return True

    def _source_matches_commit(self, commit_payload: dict) -> bool:
        tree_sha = self._commit_tree_sha(commit_payload)
        if not tree_sha:
            return False
        return self._source_matches_tree(
            self._get_json(f"git/trees/{quote(tree_sha, safe='')}?recursive=1"),
        )

    def _infer_local_commit(self, latest_sha: str, latest_payload: dict) -> str:
        if self._inferred_commit and self._inferred_verified:
            return self._inferred_commit
        if self._source_matches_commit(latest_payload):
            self._remember_inferred_commit(latest_sha)
            return latest_sha
        if self._inferred_commit:
            stored_payload = self._get_json(
                f"commits/{quote(self._inferred_commit, safe='')}",
            )
            if self._source_matches_commit(stored_payload):
                self._inferred_verified = True
                return self._inferred_commit
        recent = self._get_list(
            f"commits?sha={quote(self.branch, safe='')}&per_page={RECENT_COMMIT_SCAN_LIMIT}",
        )
        ignored = {latest_sha, self._inferred_commit}
        for candidate in recent:
            candidate_sha = _valid_commit(candidate.get("sha", ""))
            if not candidate_sha or candidate_sha in ignored:
                continue
            if self._source_matches_commit(candidate):
                self._remember_inferred_commit(candidate_sha)
                return candidate_sha
        return ""

    @property
    def repository_url(self) -> str:
        return f"https://github.com/{self.repository}"

    def _request_json(self, path: str):
        response = requests.get(
            f"https://api.github.com/repos/{self.repository}/{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Royal-Downloader-Updater",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def _get_json(self, path: str) -> dict:
        payload = self._request_json(path)
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub hat eine ungültige Antwort geliefert")
        return payload

    def _get_list(self, path: str) -> list[dict]:
        payload = self._request_json(path)
        if not isinstance(payload, list):
            raise RuntimeError("GitHub hat eine ungültige Commitliste geliefert")
        return [item for item in payload if isinstance(item, dict)]

    def _check_uncached(self) -> dict:
        current = detect_local_commit(self.app_dir)
        base = {
            "repository": self.repository,
            "repository_url": self.repository_url,
            "branch": self.branch,
            "current_sha": current,
            "latest_sha": "",
            "latest_url": self.repository_url,
            "latest_message": "",
            "comparison": "unknown",
            "update_available": None,
            "ahead_by": 0,
            "behind_by": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": "",
        }
        try:
            latest = self._get_json(f"commits/{quote(self.branch, safe='')}")
            latest_sha = _valid_commit(latest.get("sha", ""))
            if not latest_sha:
                raise RuntimeError("GitHub lieferte keine gültige Revision")
            commit_data = latest.get("commit") or {}
            base.update({
                "latest_sha": latest_sha,
                "latest_url": latest.get("html_url") or self.repository_url,
                "latest_message": str(commit_data.get("message") or "").splitlines()[0],
            })
            if not current:
                try:
                    current = self._infer_local_commit(latest_sha, latest)
                except (requests.RequestException, RuntimeError, TypeError, ValueError):
                    current = ""
                base["current_sha"] = current
            if not current:
                return base
            if current == latest_sha:
                base.update({"comparison": "identical", "update_available": False})
                return base

            comparison = self._get_json(
                f"compare/{quote(current, safe='')}...{quote(latest_sha, safe='')}",
            )
            status = str(comparison.get("status") or "unknown")
            ahead_by = max(0, int(comparison.get("ahead_by") or 0))
            behind_by = max(0, int(comparison.get("behind_by") or 0))
            base.update({
                "comparison": status,
                "update_available": status in {"ahead", "diverged"} and ahead_by > 0,
                "ahead_by": ahead_by,
                "behind_by": behind_by,
            })
            return base
        except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
            base["error"] = str(exc)[:240]
            return base

    def check(self, force: bool = False) -> dict:
        with self._lock:
            now = time.monotonic()
            if (
                not force
                and self._cache is not None
                and (now - self._cache_time) < self.cache_seconds
            ):
                return dict(self._cache)
            result = self._check_uncached()
            self._cache = dict(result)
            self._cache_time = now
            return result
