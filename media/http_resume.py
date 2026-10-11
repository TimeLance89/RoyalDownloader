"""Private, restart-safe checkpoints for direct HTTP media transfers.

Only strong ETag validators and exact HTTP Content-Range responses permit
appending bytes. No URLs, cookies or authentication headers are persisted.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = 1
_MAX_METADATA_BYTES = 4096
_MAX_AGE_SECONDS = 7 * 24 * 3600
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$", re.I)


def strong_etag(value: str) -> str:
    value = str(value or "").strip()
    if not value or value[:2].casefold() == "w/" or len(value) > 256:
        return ""
    # Reject malformed or injected validators; HTTP strong ETag is quoted.
    if not re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', value):
        return ""
    return value


def range_matches(headers, offset: int, total: int, etag: str) -> bool:
    """Accept an append response only for exactly the same entity and offset."""
    if strong_etag(headers.get("ETag", "")) != etag:
        return False
    match = _CONTENT_RANGE.fullmatch(str(headers.get("Content-Range", "")).strip())
    if not match:
        return False
    start, end, reported_total = map(int, match.groups())
    if start != offset or end < start or end >= total or reported_total != total:
        return False
    length = str(headers.get("Content-Length", "")).strip()
    if length:
        try:
            if int(length) != end - start + 1:
                return False
        except ValueError:
            return False
    return True


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.stat(follow_symlinks=False).st_mode)
    except OSError:
        return False


@dataclass(frozen=True)
class Checkpoint:
    folder: Path
    offset: int
    total: int
    etag: str


class HTTPResumeStore:
    """One private checkpoint per durable queue job and output destination."""

    def __init__(self, out_path: Path, job_id: str, stream_url: str, fallback_root: Path):
        identity = str(job_id).strip() + "\0" + str(out_path.absolute())
        self.key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        self.source = hashlib.sha256(stream_url.encode("utf-8")).hexdigest()
        self.folders = (
            out_path.parent / ".downloading" / ".http-resume" / self.key,
            fallback_root / ".http-resume" / self.key,
        )

    @staticmethod
    def _trusted(folder: Path) -> bool:
        # Do not follow a substituted checkpoint directory or staging parent.
        return not any(path.is_symlink() for path in (
            folder, folder.parent, folder.parent.parent,
        ))

    def _owned(self, folder: Path) -> bool:
        marker = folder / ".royal-http-resume"
        try:
            return (
                self._trusted(folder)
                and _regular_file(marker)
                and marker.stat().st_size <= 64
                and marker.read_text(encoding="ascii") == self.key
            )
        except (OSError, UnicodeError):
            return False

    def load(self) -> Checkpoint | None:
        for folder in self.folders:
            if not self._owned(folder):
                continue
            meta = folder / "checkpoint.json"
            part = folder / "payload.part"
            if not _regular_file(meta) or not _regular_file(part):
                continue
            try:
                if meta.stat().st_size > _MAX_METADATA_BYTES:
                    continue
                data = json.loads(meta.read_text(encoding="utf-8"))
                size = part.stat().st_size
                total = data.get("total") if isinstance(data, dict) else None
                if (
                    not isinstance(data, dict)
                    or data.get("schema") != _SCHEMA
                    or data.get("key") != self.key
                    or data.get("source") != self.source
                    or not isinstance(total, int)
                    or isinstance(total, bool)
                    or total <= 0
                    or not 0 < size <= total
                    or time.time() - part.stat().st_mtime > _MAX_AGE_SECONDS
                ):
                    continue
                etag = strong_etag(data.get("etag", ""))
                if not etag:
                    continue
                return Checkpoint(folder, size, total, etag)
            except (OSError, ValueError, TypeError, UnicodeError):
                continue
        return None

    def discard(self) -> None:
        """Remove only our known files, never an unrelated staging directory."""
        for folder in self.folders:
            if not self._owned(folder):
                continue
            for name in ("payload.part", "checkpoint.json", ".royal-http-resume"):
                file = folder / name
                if _regular_file(file):
                    file.unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:
                pass

    def prepare(self, *, total: int, etag: str) -> Path:
        """Journal the entity identity before writing the first media byte."""
        if not isinstance(total, int) or total <= 0 or not strong_etag(etag):
            raise ValueError("HTTP resume requires a known size and strong ETag")
        previous = self.load()
        if previous and previous.total == total and previous.etag == etag:
            return previous.folder / "payload.part"
        self.discard()
        errors = []
        for folder in self.folders:
            try:
                if not self._trusted(folder):
                    raise OSError("Unsafe symlink in HTTP resume path")
                # Never take ownership of a pre-existing unmarked directory.
                if folder.exists() and not self._owned(folder):
                    raise OSError("Unowned HTTP resume directory")
                folder.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                folder.mkdir(mode=0o700, exist_ok=True)
                if not self._trusted(folder):
                    raise OSError("Unsafe HTTP resume directory")
                marker = folder / ".royal-http-resume"
                if not marker.exists():
                    with marker.open("x", encoding="ascii") as f:
                        f.write(self.key)
                        f.flush()
                        os.fsync(f.fileno())
                if not self._owned(folder):
                    raise OSError("HTTP resume directory belongs to a different job")
                meta = folder / "checkpoint.json"
                tmp = folder / f".checkpoint.{os.getpid()}.tmp"
                payload = json.dumps({
                    "schema": _SCHEMA,
                    "key": self.key,
                    "source": self.source,
                    "total": total,
                    "etag": etag,
                })
                try:
                    with tmp.open("x", encoding="utf-8") as f:
                        os.chmod(tmp, 0o600)
                        f.write(payload)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, meta)
                finally:
                    tmp.unlink(missing_ok=True)
                part = folder / "payload.part"
                if part.is_symlink():
                    raise OSError("Unsafe HTTP resume payload symlink")
                with part.open("wb") as file:
                    if hasattr(os, "fchmod"):
                        os.fchmod(file.fileno(), 0o600)
                return part
            except OSError as exc:
                errors.append(str(exc))
        raise OSError("Unable to store HTTP resume checkpoint: " + "; ".join(errors))

    @staticmethod
    def commit_to_staging(source: Path, target: Path) -> None:
        """Make a complete, checkpointed transfer available to existing validation."""
        if source.is_symlink() or not _regular_file(source):
            raise OSError("Unsafe resumed media file")
        try:
            os.replace(source, target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            # Cross-device fallback; an interrupted copy never publishes media.
            with source.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            source.unlink()


def cleanup_expired_http_resumes(staging_roots, *, preview=False, max_items=100):
    """Bounded, ownership-checked janitor for week-old abandoned checkpoints."""
    results = []
    removed = 0
    limit = max(1, min(1000, int(max_items)))
    for staging_root in staging_roots:
        base = Path(staging_root) / ".http-resume"
        if base.is_symlink() or not base.is_dir():
            continue
        try:
            children = list(base.iterdir())[:limit]
        except OSError:
            continue
        for folder in children:
            if (
                folder.is_symlink() or not folder.is_dir()
                or not re.fullmatch(r"[0-9a-f]{32}", folder.name)
            ):
                continue
            marker = folder / ".royal-http-resume"
            part = folder / "payload.part"
            meta = folder / "checkpoint.json"
            try:
                if (
                    not all(_regular_file(item) for item in (marker, part, meta))
                    or marker.stat().st_size > 64
                    or marker.read_text(encoding="ascii") != folder.name
                    or set(x.name for x in folder.iterdir()) != {
                        marker.name, part.name, meta.name,
                    }
                    or part.stat().st_mtime > time.time() - _MAX_AGE_SECONDS
                ):
                    continue
                if preview:
                    results.append({
                        "path": str(folder),
                        "category": "royal_http_resume",
                        "size_bytes": part.stat().st_size,
                        "modified_at": part.stat().st_mtime,
                    })
                    continue
                part.unlink()
                meta.unlink()
                marker.unlink()
                folder.rmdir()
                removed += 1
            except (OSError, UnicodeError):
                continue
        if not preview:
            try:
                base.rmdir()
            except OSError:
                pass
    return results if preview else removed
