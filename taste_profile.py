"""Local, persistent taste profile shared by all Royal Downloader clients.

Raw interaction evidence stays on the Royal server.  Public API responses expose
only aggregate interests plus ranking metadata, never private search text or
watched-title history.
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

from taste_model import (
    RANKING_POLICY,
    canonical_value,
    canonical_values,
    score_profile_dimensions,
)


SCHEMA_VERSION = 2
MAX_EVENTS = 2000
MAX_JELLYFIN_ITEMS = 1000
HALF_LIFE_DAYS = 180.0
LEGACY_HALF_LIFE_DAYS = 120.0

ACTION_WEIGHTS = {
    "search": 0.15,
    "open": 0.8,
    "remove": -1.0,
    "watchlist": 3.5,
    "subscription": 4.0,
    "download": 5.0,
    "dismiss": -5.0,
    "less": -4.0,
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
    "franchises": 0.55,
}

_METADATA_ALIASES = {
    "genres": ("genres", "Genres"),
    "tags": ("tags", "Tags", "keywords", "Keywords"),
    "studios": ("studios", "Studios", "production_companies"),
    "directors": ("directors", "Directors"),
    "actors": ("actors", "cast"),
    "languages": ("languages", "spoken_languages", "language", "content_language"),
    "franchises": (
        "franchises", "franchise", "collection", "belongs_to_collection", "series_name",
    ),
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
            raw = raw.get("name") or raw.get("Name") or raw.get("title") or raw.get("Title")
        text = _clean_text(raw, 80)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _canonical_dimension_values(dimension: str, values: Any) -> list[str]:
    return canonical_values(dimension, _value_names(values), limit=12)


def normalize_metadata(
    metadata: Mapping[str, Any] | None,
    media_type: str = "",
) -> dict[str, list[str]]:
    """Reduce provider/TMDB/Jellyfin data to stable, bounded taste axes."""

    source = metadata or {}
    result: dict[str, list[str]] = {}
    for dimension, aliases in _METADATA_ALIASES.items():
        values: list[str] = []
        for alias in aliases:
            if alias in source:
                values.extend(_value_names(source.get(alias)))
        normalized = _canonical_dimension_values(dimension, values)
        if normalized:
            result[dimension] = normalized

    people = source.get("People") or []
    if isinstance(people, (list, tuple)):
        actors = _value_names([
            person for person in people
            if isinstance(person, Mapping)
            and str(person.get("Type") or "").casefold() == "actor"
        ])
        directors = _value_names([
            person for person in people
            if isinstance(person, Mapping)
            and str(person.get("Type") or "").casefold() == "director"
        ])
        if actors:
            result["actors"] = _canonical_dimension_values(
                "actors", [*(result.get("actors") or []), *actors],
            )
        if directors:
            result["directors"] = _canonical_dimension_values(
                "directors", [*(result.get("directors") or []), *directors],
            )

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

    normalized_type = canonical_value(
        "media_types", media_type or source.get("media_type") or source.get("Type"),
    )
    if normalized_type in {"movie", "series", "anime"}:
        result["media_types"] = [normalized_type]
    return result


def _signal_for(action: str, value: Any = None) -> float:
    if action == "rating":
        try:
            rating = max(0.0, min(10.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
        return (rating - 5.0) * 1.4
    return ACTION_WEIGHTS.get(action, 0.0)


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _jellyfin_completion(user_data: Mapping[str, Any], item: Mapping[str, Any]) -> float:
    direct = _finite_float(user_data.get("PlayedPercentage"), -1.0)
    if direct >= 0:
        return max(0.0, min(1.0, direct / 100.0))
    position = _finite_float(user_data.get("PlaybackPositionTicks"), 0.0)
    runtime = _finite_float(item.get("RunTimeTicks"), 0.0)
    if runtime > 0 and position > 0:
        return max(0.0, min(1.0, position / runtime))
    return 1.0 if user_data.get("Played") is True else 0.0


def jellyfin_taste_signal(item: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    """Turn Jellyfin playback state into evidence strength rather than +5 always."""

    user_data = item.get("UserData") or {}
    if not isinstance(user_data, Mapping):
        user_data = {}
    play_count = max(0, int(_finite_float(user_data.get("PlayCount"), 0.0)))
    completion = _jellyfin_completion(user_data, item)
    played = user_data.get("Played") is True or play_count > 0

    if user_data.get("Played") is True or completion >= 0.90:
        signal = 5.0
    elif completion >= 0.60:
        signal = 3.2
    elif completion >= 0.25:
        signal = 1.5
    elif played:
        signal = 0.6
    else:
        signal = 0.0

    if play_count > 1:
        signal += min(3.0, math.log2(play_count) * 1.2)
    if user_data.get("IsFavorite") is True:
        signal += 4.0
    rating = user_data.get("Rating")
    if rating is not None:
        signal += _signal_for("rating", rating)

    details = {
        "completion": round(completion, 4),
        "play_count": play_count,
        "favorite": bool(user_data.get("IsFavorite")),
        "rated": rating is not None,
    }
    return max(-10.0, min(14.0, signal)), details


def score_metadata_against_profile(
    profile: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
    media_type: str = "",
) -> dict[str, Any]:
    return score_profile_dimensions(profile, normalize_metadata(metadata, media_type))


class TasteProfileStore:
    """Thread-safe profile store with atomic persistence and evidence decay."""

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
            "legacy": {"imported": False, "imported_at": 0.0, "dimensions": {}},
            "updated_at": 0.0,
        }

    def _load(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                return self._empty()
            base = self._empty()
            base.update(loaded)
            base["version"] = SCHEMA_VERSION
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
                base["legacy"] = {"imported": False, "imported_at": 0.0, "dimensions": {}}
            elif base["legacy"].get("imported") and not base["legacy"].get("imported_at"):
                base["legacy"]["imported_at"] = float(base.get("updated_at") or time.time())
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
        event = {
            "id": uuid.uuid4().hex,
            "at": now,
            "action": action,
            "source": source,
            "media_type": media_type,
            "item_key": key,
            "title": _clean_text(title, 160),
            "dimensions": normalize_metadata(metadata, media_type),
            "value": value if isinstance(value, (int, float, bool)) else None,
            "query": _clean_text(query, 160),
        }
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
        if action not in {"like", "less", "dislike", "dismiss", "favorite", "rating"}:
            raise ValueError(
                "Feedback muss like, less, dislike, dismiss, favorite oder rating sein"
            )
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
        """Replace the watched Jellyfin snapshot using evidence-aware signals."""

        now = float(self.clock())
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            item_id = _clean_text(item.get("Id"), 100)
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            user_data = item.get("UserData") or {}
            if not isinstance(user_data, Mapping):
                user_data = {}
            signal, evidence = jellyfin_taste_signal(item)
            if abs(signal) < 0.01:
                continue
            played_at = user_data.get("LastPlayedDate") or item.get("DateLastPlayed") or ""
            normalized.append({
                "item_key": f"jellyfin:{item_id}",
                "title": _clean_text(item.get("Name"), 160),
                "at": played_at,
                "signal": signal,
                "evidence": evidence,
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
        """Import the old browser profile once and let it fade over time."""

        now = float(self.clock())
        with self._lock:
            if self._data.get("legacy", {}).get("imported"):
                return False
            dimensions = {
                "genres": {
                    canonical_value("genres", _clean_text(key, 80)): max(
                        -80.0, min(80.0, float(value)),
                    )
                    for key, value in list(dict(profile.get("genres") or {}).items())[:100]
                    if _clean_text(key, 80)
                },
                "media_types": {
                    canonical_value("media_types", _clean_text(key, 20)): max(
                        -80.0, min(80.0, float(value)),
                    )
                    for key, value in list(dict(profile.get("kinds") or {}).items())[:10]
                    if _clean_text(key, 20)
                },
            }
            self._data["legacy"] = {
                "imported": True,
                "imported_at": now,
                "dimensions": dimensions,
            }
            self._data["updated_at"] = now
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
                for value in _canonical_dimension_values(dimension, values):
                    bucket = scores[dimension]
                    bucket[value] = bucket.get(value, 0.0) + signal * factor * decay

        imported_at = float(legacy.get("imported_at") or now)
        legacy_decay = math.pow(
            0.5,
            max(0.0, (now - imported_at) / 86400) / LEGACY_HALF_LIFE_DAYS,
        )
        for dimension, values in dict(legacy.get("dimensions") or {}).items():
            if dimension in scores:
                for name, value in dict(values or {}).items():
                    canonical = canonical_value(dimension, _clean_text(name, 80))
                    if canonical:
                        scores[dimension][canonical] = float(value) * legacy_decay

        for event in events:
            age = (now - float(event.get("at") or now)) / 86400
            add(
                event.get("dimensions") or {},
                _signal_for(event.get("action", ""), event.get("value")),
                age,
            )
        for item in jellyfin.get("items") or []:
            item_at = self._parsed_timestamp(
                item.get("at"), float(jellyfin.get("updated_at") or now),
            )
            add(
                item.get("dimensions") or {},
                float(item.get("signal") or 0),
                (now - item_at) / 86400,
            )
        for item in feedback.values():
            # Explicit choices fade at half the speed of incidental behaviour.
            age = (now - float(item.get("at") or now)) / 86400 / 2
            add(
                item.get("dimensions") or {},
                _signal_for(item.get("action", ""), item.get("value")),
                age,
            )

        rounded = {
            dimension: {
                name: round(max(-100.0, min(100.0, value)), 3)
                for name, value in sorted(
                    values.items(), key=lambda pair: (-pair[1], pair[0].casefold()),
                )
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
            {
                "key": event.get("item_key", ""),
                "action": event.get("action", ""),
                "at": event.get("at", 0),
            }
            for event in reversed(events)
            if event.get("item_key")
        ][:60]
        favorites = {
            dimension: [name for name, value in values.items() if value > 0][:5]
            for dimension, values in rounded.items()
            if any(value > 0 for value in values.values())
        }
        avoid = {
            dimension: [
                name for name, value in sorted(values.items(), key=lambda pair: pair[1])
                if value < -0.25
            ][:5]
            for dimension, values in rounded.items()
            if any(value < -0.25 for value in values.values())
        }

        explicit_count = len(feedback)
        jellyfin_items = list(jellyfin.get("items") or [])
        strong_behaviour = sum(
            1 for event in events
            if event.get("action") in {
                "watchlist", "subscription", "download", "watch_complete", "favorite",
            }
        )
        strong_jellyfin = sum(
            1 for item in jellyfin_items if abs(float(item.get("signal") or 0)) >= 4.5
        )
        effective_evidence = (
            len(events) * 0.18
            + strong_behaviour * 1.4
            + len(jellyfin_items) * 0.32
            + strong_jellyfin * 0.8
            + explicit_count * 2.5
        )
        confidence = round(1.0 - math.exp(-effective_evidence / 38.0), 4)
        if confidence >= 0.82:
            confidence_label = "very_high"
        elif confidence >= 0.62:
            confidence_label = "high"
        elif confidence >= 0.35:
            confidence_label = "medium"
        else:
            confidence_label = "low"

        return {
            "version": SCHEMA_VERSION,
            "dimensions": rounded,
            "favorites": favorites,
            "avoid": avoid,
            "genres": rounded["genres"],
            "kinds": rounded["media_types"],
            "recent": recent,
            "blocked_items": blocked,
            "item_feedback": item_feedback,
            "interactions": len(events) + len(feedback) + len(jellyfin_items),
            "confidence": confidence,
            "confidence_label": confidence_label,
            "signal_breakdown": {
                "behavior": len(events),
                "explicit": explicit_count,
                "jellyfin": len(jellyfin_items),
                "strong": strong_behaviour + strong_jellyfin + explicit_count,
            },
            "ranking": dict(RANKING_POLICY),
            "updated_at": updated_at,
            "jellyfin_updated_at": float(jellyfin.get("updated_at") or 0),
            "legacy_imported": bool(legacy.get("imported")),
        }

    def score_metadata(
        self,
        metadata: Mapping[str, Any] | None,
        media_type: str = "",
    ) -> dict[str, Any]:
        return score_metadata_against_profile(self.public_profile(), metadata, media_type)

    def reset(self) -> None:
        with self._lock:
            self._data = self._empty()
            self._data["updated_at"] = float(self.clock())
            self._save_locked()
