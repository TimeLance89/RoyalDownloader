"""Atomic personal wishes and server-scoped managed playlist bindings."""

import json
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile


class SavedMediaStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        try:
            self.document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(self.document, dict) or not isinstance(self.document.get("wishes"), list):
                raise ValueError("Invalid saved media store")
        except FileNotFoundError:
            self.document = {"wishes": [], "playlists": {}}

    def _commit(self, document):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(document, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        self.document = document

    def snapshot(self):
        with self.lock:
            return deepcopy(self.document)

    def items(self, owner):
        return [item for item in self.snapshot()["wishes"] if item["owner"] == owner]

    def set(self, owner, media_type, tmdb_id, title, saved):
        with self.lock:
            document = deepcopy(self.document)
            wishes = document["wishes"]
            key = (owner, media_type, tmdb_id)
            existing = next((item for item in wishes if (item["owner"], item["media_type"], item["tmdb_id"]) == key), None)
            if saved and not existing:
                if sum(item["owner"] == owner for item in wishes) >= 500:
                    raise ValueError("Maximal 500 Vormerkungen pro Profil.")
                wishes.append({"owner": owner, "media_type": media_type, "tmdb_id": tmdb_id,
                               "title": title, "created_at": time.time()})
            elif not saved and existing:
                wishes.remove(existing)
            self._commit(document)

    def bind(self, server, user, playlist_id):
        with self.lock:
            document = deepcopy(self.document)
            document.setdefault("playlists", {}).setdefault(server, {})[user] = playlist_id
            self._commit(document)

    def delete_for_user(self, owner):
        with self.lock:
            document = deepcopy(self.document)
            before = len(document["wishes"])
            document["wishes"] = [item for item in document["wishes"] if item["owner"] != owner]
            self._commit(document)
            return before - len(document["wishes"])
