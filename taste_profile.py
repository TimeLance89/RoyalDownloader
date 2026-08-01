"""Lokales, persistentes Geschmacksprofil für alle Royal-Downloader-Clients.

Das Profil bleibt auf dem Royal-Downloader-Server. Rohereignisse werden
begrenzt gespeichert; API-Antworten enthalten nur aggregierte Interessen.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


SCHEMA_VERSION = 1
MAX_EVENTS = 2000
MAX_JELLYFIN_ITEMS = 1000
HALF_LIFE_DAYS = 180.0

ACTION_WEIGHTS = {
    "search": 0.15,
    "open": 0.8,
    "remove": -1.0,
    "watchlist": 3.5,
    "subscription": 4.0,
    "download": 5.0,
    "dismiss": -5.0,
    "like": 6.0,
    "watch_complete": 7.0,
    "favorite": 8.0,
    "dislike": -10.0,
    "rating": 0.0,
}

DIMENSION_FACTORS = {
    "genres": 1.0,
    "tags": 0.45,
    "studios": 0.35,
    "directors": 0.65,
    "actors": 0.40,
    "languages": 0.25,
    "decades": 0.30,
    "runtime_buckets": 0.25,
    "media_types": 0.70,
}

_METADATA_ALIASES = {
    "genres": ("genres", "Genres"),
    "tags": ("tags", "Tags"),
    "studios": ("studios", "Studios"),
    "directors": ("directors", "Directors"),
    "actors": ("actors", "cast"),
    "languages": ("languages", "spoken_languages", "language"),
}


def _clean_text(value: Any, limit: int = 120) -> str:
    return " ".join(str(value or "").split())[:limit]


def _value_names(value: Any, limit: int = 12) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if isinstance(raw, Mapping):
            raw = raw.get("name") or raw.get("Name") or raw.get("title")
        text = _clean_text(raw, 80)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if len(result) >= limit:
            break
    return result


def normalize_metadata(metadata: Mapping[str, Any] | None, media_type: str = "") -> dict[str, list[str]]:
    """Reduziert beliebige Provider-/TMDB-/Jellyfin-Daten auf sichere Achsen."""
    source = metadata or {}
    result: dict[str, list[str]] = {}
    for dimension, aliases in _METADATA_ALIASES.items():
        values: list[str] = []
        for alias in aliases:
            if alias in source:
                values.extend(_value_names(source.get(alias)))
        if values:
            result[dimension] = _value_names(values)

    people = source.get("People") or []
    if isinstance(people, (list, tuple)):
        actors = _value_names([
            person for person in people
            if isinstance(person, Mapping) and str(person.get("Type") or "").casefold() == "actor"
        ])
        directors = _value_names([
            person for person in people
            if isinstance(person, Mapping) and str(person.get("Type") or "").casefold() == "director"
        ])
        if actors:
            result["actors"] = _value_names([*(result.get("actors") or []), *actors])
        if directors:
            result["directors"] = _value_names([*(result.get("directors") or []), *directors])

    year = source.get("year") or source.get("release_year") or source.get("ProductionYear")
    try:
        numeric_year = int(str(year)[:4])
    except (TypeError, ValueError):
        numeric_year = 0
    if 1880 <= numeric_year <= 2200:
        result["decades"] = [f"{numeric_year // 10 * 10}er"]

    runtime = source.get("runtime") or source.get("runtime_minutes")
    if not runtime and source.get("RunTimeTicks"):
        try:
            runtime = float(source["RunTimeTicks"]) / 600_000_000
        except (TypeError, ValueError):
            runtime = 0
    match = re.search(r"\d+(?:[.,]\d+)?", str(runtime or ""))
    try:
        minutes = int(float(match.group(0).replace(",", "."))) if match else 0
    except (TypeError, ValueError):
        minutes = 0
    if minutes > 0:
        bucket = "kurz" if minutes < 45 else "mittel" if minutes < 100 else "lang"
        result["runtime_buckets"] = [bucket]

    normalized_type = _clean_text(media_type or source.get("media_type") or source.get("Type"), 20).casefold()
    type_aliases = {"movie": "movie", "film": "movie", "series": "series", "serie": "series", "anime": "anime"}
    if normalized_type in type_aliases:
        result["media_types"] = [type_aliases[normalized_type]]
    return result


def _signal_for(action: str, value: Any = None) -> float:
    if action == "rating":
        try:
            rating = max(0.0, min(10.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
        return (rating - 5.0) * 1.4
    return ACTION_WEIGHTS.get(action, 0.0)


class TasteProfileStore:
    """Thread-sicherer Store mit atomaren Schreibvorgängen und Zeitverfall."""

    def __init__(self, path: Path | str, *, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.RLock()
        self._data = self._load()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "events": [],
            "feedback": {},
            "jellyfin": {"updated_at": 0.0, "items": []},
            "legacy": {"imported": False, "dimensions": {}},
            "updated_at": 0.0,
        }

    def _load(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                return self._empty()
            base = self._empty()
            base.update(loaded)
            base["events"] = [
                item for item in list(base.get("events") or []) if isinstance(item, dict)
            ][-MAX_EVENTS:]
            base["feedback"] = {
                str(key): value
                for key, value in dict(base.get("feedback") or {}).items()
                if isinstance(value, dict)
            }
            if not isinstance(base.get("jellyfin"), dict):
                base["jellyfin"] = {"updated_at": 0.0, "items": []}
            else:
                base["jellyfin"]["items"] = [
                    item for item in list(base["jellyfin"].get("items") or [])
                    if isinstance(item, dict)
                ][:MAX_JELLYFIN_ITEMS]
            if not isinstance(base.get("legacy"), dict):
                base["legacy"] = {"imported": False, "dimensions": {}}
            return base
        except (OSError, ValueError, TypeError):
            return self._empty()

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def record_event(
        self,
        action: str,
        *,
        source: str = "api",
        media_type: str = "",
        item_key: str = "",
        title: str = "",
        metadata: Mapping[str, Any] | None = None,
        value: Any = None,
        query: str = "",
        at: float | None = None,
    ) -> bool:
        action = _clean_text(action, 24).casefold()
        if action not in ACTION_WEIGHTS:
            raise ValueError(f"Unbekanntes Geschmackssignal: {action}")
        now = float(self.clock() if at is None else at)
        key = _clean_text(item_key, 240)
        source = _clean_text(source, 32).casefold() or "api"
        media_type = _clean_text(media_type, 20).casefold()
        dimensions = normalize_metadata(metadata, media_type)
        event = {
            "id": uuid.uuid4().hex,
            "at": now,
            "action": action,
            "source": source,
            "media_type": media_type,
            "item_key": key,
            "title": _clean_text(title, 160),
            "dimensions": dimensions,
            "value": value if isinstance(value, (int, float, bool)) else None,
            "query": _clean_text(query, 160),
        }
        # UI-Wiederholungen und Queue-Restores dürfen ein Signal nicht aufblasen.
        dedupe_seconds = 86400 if action in {"download", "watchlist", "subscription"} else 600
        with self._lock:
            for previous in reversed(self._data["events"][-80:]):
                if now - float(previous.get("at") or 0) > dedupe_seconds:
                    break
                if (
                    previous.get("action") == action
                    and previous.get("source") == source
                    and previous.get("item_key") == key
                    and previous.get("query") == event["query"]
                ):
                    return False
            self._data["events"].append(event)
            self._data["events"] = self._data["events"][-MAX_EVENTS:]
            self._data["updated_at"] = now
            self._save_locked()
        return True

    def set_feedback(
        self,
        item_key: str,
        action: str,
        *,
        media_type: str = "",
        title: str = "",
        metadata: Mapping[str, Any] | None = None,
        source: str = "web",
        value: Any = None,
    ) -> dict[str, Any]:
        action = _clean_text(action, 24).casefold()
        if action not in {"like", "dislike", "dismiss", "favorite", "rating"}:
            raise ValueError("Feedback muss like, dislike, dismiss, favorite oder rating sein")
        key = _clean_text(item_key, 240)
        if not key:
            raise ValueError("Für Feedback fehlt der Inhaltsschlüssel")
        now = float(self.clock())
        feedback = {
            "at": now,
            "action": action,
            "media_type": _clean_text(media_type, 20).casefold(),
            "title": _clean_text(title, 160),
            "dimensions": normalize_metadata(metadata, media_type),
            "source": _clean_text(source, 32).casefold(),
            "value": value if isinstance(value, (int, float, bool)) else None,
        }
        with self._lock:
            self._data["feedback"][key] = feedback
            self._data["updated_at"] = now
            self._save_locked()
        return feedback

    def clear_feedback(self, item_key: str) -> bool:
        with self._lock:
            removed = self._data["feedback"].pop(_clean_text(item_key, 240), None) is not None
            if removed:
                self._data["updated_at"] = float(self.clock())
                self._save_locked()
            return removed

    def replace_jellyfin_items(self, items: Iterable[Mapping[str, Any]]) -> int:
        """Übernimmt den gesehenen Jellyfin-Verlauf als ersetzbaren Snapshot."""
        now = float(self.clock())
        normalized: list[dict[str, Any]] = []
        for item in items:
            user_data = item.get("UserData") or {}
            played_at = user_data.get("LastPlayedDate") or item.get("DateLastPlayed") or ""
            signal = 5.0
            if user_data.get("IsFavorite"):
                signal += 3.0
            rating = user_data.get("Rating")
            if rating is not None:
                signal += _signal_for("rating", rating)
            normalized.append({
                "item_key": f"jellyfin:{_clean_text(item.get('Id'), 100)}",
                "title": _clean_text(item.get("Name"), 160),
                "at": played_at,
                "signal": max(-10.0, min(14.0, signal)),
                "dimensions": normalize_metadata(item, item.get("Type", "")),
            })
            if len(normalized) >= MAX_JELLYFIN_ITEMS:
                break
        with self._lock:
            self._data["jellyfin"] = {"updated_at": now, "items": normalized}
            self._data["updated_at"] = now
            self._save_locked()
        return len(normalized)

    def import_legacy(self, profile: Mapping[str, Any]) -> bool:
        """Importiert das alte Browserprofil genau einmal, ohne dessen Historie offenzulegen."""
        with self._lock:
            if self._data.get("legacy", {}).get("imported"):
                return False
            dimensions = {
                "genres": {
                    _clean_text(key, 80): max(-80.0, min(80.0, float(value)))
                    for key, value in list(dict(profile.get("genres") or {}).items())[:100]
                    if _clean_text(key, 80)
                },
                "media_types": {
                    _clean_text(key, 20): max(-80.0, min(80.0, float(value)))
                    for key, value in list(dict(profile.get("kinds") or {}).items())[:10]
                    if _clean_text(key, 20)
                },
            }
            self._data["legacy"] = {"imported": True, "dimensions": dimensions}
            self._data["updated_at"] = float(self.clock())
            self._save_locked()
            return True

    @staticmethod
    def _parsed_timestamp(value: Any, fallback: float) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value:
            try:
                from datetime import datetime
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except (ValueError, OverflowError):
                pass
        return fallback

    def public_profile(self) -> dict[str, Any]:
        now = float(self.clock())
        with self._lock:
            events = list(self._data["events"])
            feedback = dict(self._data["feedback"])
            jellyfin = dict(self._data.get("jellyfin") or {})
            legacy = dict(self._data.get("legacy") or {})
            updated_at = float(self._data.get("updated_at") or 0)

        scores: dict[str, dict[str, float]] = {name: {} for name in DIMENSION_FACTORS}

        def add(dimensions: Mapping[str, Any], signal: float, age_days: float = 0.0) -> None:
            decay = math.pow(0.5, max(0.0, age_days) / HALF_LIFE_DAYS)
            for dimension, values in dimensions.items():
                factor = DIMENSION_FACTORS.get(dimension)
                if factor is None:
                    continue
                for value in _value_names(values):
                    bucket = scores[dimension]
                    bucket[value] = bucket.get(value, 0.0) + signal * factor * decay

        for dimension, values in dict(legacy.get("dimensions") or {}).items():
            if dimension in scores:
                for name, value in dict(values or {}).items():
                    scores[dimension][_clean_text(name, 80)] = float(value)

        for event in events:
            age = (now - float(event.get("at") or now)) / 86400
            add(event.get("dimensions") or {}, _signal_for(event.get("action", ""), event.get("value")), age)
        for item in jellyfin.get("items") or []:
            item_at = self._parsed_timestamp(item.get("at"), float(jellyfin.get("updated_at") or now))
            add(item.get("dimensions") or {}, float(item.get("signal") or 0), (now - item_at) / 86400)
        for item in feedback.values():
            # Bewusst langsamerer Verfall: eine explizite Entscheidung zählt mehr als ein Klick.
            age = (now - float(item.get("at") or now)) / 86400 / 2
            add(item.get("dimensions") or {}, _signal_for(item.get("action", ""), item.get("value")), age)

        rounded = {
            dimension: {
                name: round(max(-100.0, min(100.0, value)), 3)
                for name, value in sorted(values.items(), key=lambda pair: (-pair[1], pair[0].casefold()))
                if abs(value) >= 0.01
            }
            for dimension, values in scores.items()
        }
        blocked = sorted(
            key for key, item in feedback.items()
            if item.get("action") in {"dislike", "dismiss"}
        )
        item_feedback = {
            key: str(item.get("action") or "")
            for key, item in feedback.items()
        }
        recent = [
            {"key": event.get("item_key", ""), "action": event.get("action", ""), "at": event.get("at", 0)}
            for event in reversed(events)
            if event.get("item_key")
        ][:60]
        favorites = {
            dimension: list(values)[:5]
            for dimension, values in rounded.items()
            if values
        }
        return {
            "version": SCHEMA_VERSION,
            "dimensions": rounded,
            "favorites": favorites,
            "genres": rounded["genres"],
            "kinds": rounded["media_types"],
            "recent": recent,
            "blocked_items": blocked,
            "item_feedback": item_feedback,
            "interactions": len(events) + len(feedback) + len(jellyfin.get("items") or []),
            "updated_at": updated_at,
            "jellyfin_updated_at": float(jellyfin.get("updated_at") or 0),
            "legacy_imported": bool(legacy.get("imported")),
        }

    def reset(self) -> None:
        with self._lock:
            self._data = self._empty()
            self._data["updated_at"] = float(self.clock())
            self._save_locked()
