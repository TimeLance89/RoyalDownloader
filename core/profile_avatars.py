"""Persistent administrator-managed household profile avatars."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

MAX_PROFILE_AVATAR_BYTES = 4 * 1024 * 1024

_IMAGE_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
)


def _detect_image_type(data: bytes) -> tuple[str, str]:
    for signature, extension, content_type in _IMAGE_TYPES:
        if data.startswith(signature):
            return extension, content_type
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise ValueError("Nur PNG-, JPEG- oder WebP-Bilder werden unterstützt.")


class ProfileAvatarStore:
    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._index_path = self._directory / "index.json"
        self._lock = threading.RLock()

    def _load_index(self) -> dict:
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_index(self, index: dict) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = self._directory / f".index.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._index_path)
        try:
            self._index_path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def is_custom_id(avatar_id: str) -> bool:
        value = str(avatar_id or "")
        return (
            value.startswith("custom-")
            and len(value) == 23
            and all(char in "0123456789abcdef" for char in value[7:])
        )

    def list(self) -> list[dict]:
        with self._lock:
            index = self._load_index()
            items = []
            dirty = False
            for avatar_id, metadata in list(index.items()):
                if not self.is_custom_id(avatar_id) or not isinstance(metadata, dict):
                    index.pop(avatar_id, None)
                    dirty = True
                    continue
                extension = str(metadata.get("extension") or "")
                path = self._directory / f"{avatar_id}.{extension}"
                if not path.is_file():
                    index.pop(avatar_id, None)
                    dirty = True
                    continue
                items.append({
                    "id": avatar_id,
                    "name": str(metadata.get("name") or "Eigenes Profilbild"),
                    "content_type": str(metadata.get("content_type") or "image/jpeg"),
                    "created_at": float(metadata.get("created_at") or 0),
                })
            if dirty:
                self._save_index(index)
            return sorted(items, key=lambda item: item["created_at"], reverse=True)

    def exists(self, avatar_id: str) -> bool:
        return any(item["id"] == avatar_id for item in self.list())

    def save(self, filename: str, declared_content_type: str, data: bytes) -> dict:
        if not data:
            raise ValueError("Das Bild ist leer.")
        if len(data) > MAX_PROFILE_AVATAR_BYTES:
            raise ValueError("Das Profilbild darf höchstens 4 MB groß sein.")
        extension, content_type = _detect_image_type(data)
        declared = str(declared_content_type or "").split(";", 1)[0].strip().lower()
        if declared and declared not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            raise ValueError("Nicht unterstützter Bildtyp.")

        display_name = Path(str(filename or "Profilbild")).name.strip()[:120] or "Profilbild"
        avatar_id = f"custom-{secrets.token_hex(8)}"
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{avatar_id}.{extension}"
        temporary = self._directory / f".{avatar_id}.{os.getpid()}.tmp"

        with self._lock:
            with open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            try:
                path.chmod(0o600)
            except OSError:
                pass
            index = self._load_index()
            metadata = {
                "name": display_name,
                "extension": extension,
                "content_type": content_type,
                "created_at": time.time(),
            }
            index[avatar_id] = metadata
            try:
                self._save_index(index)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return {"id": avatar_id, **metadata}

    def read(self, avatar_id: str) -> tuple[bytes, str] | None:
        if not self.is_custom_id(avatar_id):
            return None
        with self._lock:
            metadata = self._load_index().get(avatar_id)
            if not isinstance(metadata, dict):
                return None
            extension = str(metadata.get("extension") or "")
            path = self._directory / f"{avatar_id}.{extension}"
            try:
                data = path.read_bytes()
            except OSError:
                return None
            return data, str(metadata.get("content_type") or "application/octet-stream")

    def delete(self, avatar_id: str) -> dict:
        if not self.is_custom_id(avatar_id):
            raise ValueError("Unbekanntes Profilbild.")
        with self._lock:
            index = self._load_index()
            metadata = index.pop(avatar_id, None)
            if not isinstance(metadata, dict):
                raise ValueError("Profilbild nicht gefunden.")
            extension = str(metadata.get("extension") or "")
            path = self._directory / f"{avatar_id}.{extension}"
            try:
                path.unlink(missing_ok=True)
                self._save_index(index)
            except OSError as exc:
                raise OSError("Profilbild konnte nicht gelöscht werden.") from exc
            return {"id": avatar_id, "name": str(metadata.get("name") or "")}
