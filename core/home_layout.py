"""Persistent, bounded home-page composition shared by all web clients."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
HOME_RAIL_IDS = (
    "personal", "top", "series", "genre", "explore", "gems", "fresh",
    "new_movies", "new_series", "high_rated", "movies", "library",
)
DEFAULT_VISIBLE_RAILS = HOME_RAIL_IDS[:7]


class HomeLayoutStore:
    """Thread-safe home layout with atomic persistence and strict rail IDs."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._layout = self._load()

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "hero_visible": True,
            "rail_order": list(HOME_RAIL_IDS),
            "hidden_rails": [
                rail_id for rail_id in HOME_RAIL_IDS
                if rail_id not in DEFAULT_VISIBLE_RAILS
            ],
        }

    @classmethod
    def normalize(cls, value: Mapping[str, Any] | None) -> dict[str, Any]:
        source = value if isinstance(value, Mapping) else {}
        allowed = set(HOME_RAIL_IDS)
        order: list[str] = []
        for raw in list(source.get("rail_order") or []):
            rail_id = str(raw or "").strip()
            if rail_id in allowed and rail_id not in order:
                order.append(rail_id)
        order.extend(rail_id for rail_id in HOME_RAIL_IDS if rail_id not in order)
        hidden = {
            str(raw or "").strip()
            for raw in list(source.get("hidden_rails") or [])
            if str(raw or "").strip() in allowed
        }
        if len(hidden) == len(HOME_RAIL_IDS):
            raise ValueError("Mindestens eine Startseiten-Reihe muss sichtbar bleiben.")
        return {
            "version": SCHEMA_VERSION,
            "hero_visible": source.get("hero_visible") is not False,
            "rail_order": order,
            "hidden_rails": [rail_id for rail_id in order if rail_id in hidden],
        }

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return self.normalize(value)
        except (OSError, ValueError, TypeError):
            return self.defaults()

    def public_layout(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self._layout["version"],
                "hero_visible": self._layout["hero_visible"],
                "rail_order": list(self._layout["rail_order"]),
                "hidden_rails": list(self._layout["hidden_rails"]),
            }

    def update(self, value: Mapping[str, Any]) -> dict[str, Any]:
        normalized = self.normalize(value)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(
                f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(normalized, handle, ensure_ascii=False, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                try:
                    self.path.chmod(0o600)
                except OSError:
                    pass
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self._layout = normalized
            return self.public_layout()
