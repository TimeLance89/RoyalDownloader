"""Validated storage autonomy; deletion is an independent explicit permission."""

from __future__ import annotations

import math
import re
from copy import deepcopy

GIB = 1024 ** 3
MODES = ("monitor", "advisor", "automatic", "full")
ROLES = ("primary", "overflow", "archive", "monitor")
MEDIA_TYPES = ("movies", "series", "anime")
DEFAULT_POLICY = {
    "mode": "monitor", "auto_delete": False, "delete_categories": [],
    "window_start": "02:00", "window_end": "07:00", "window_enabled": True,
    "interval_hours": 6, "cooldown_hours": 168, "max_moves": 1,
    "max_move_gib": 200, "unknown_download_gib": 8,
    "archive_age_days": 180, "allow_series_split": False,
}
DEFAULT_VOLUME = {
    "role": "primary", "media_types": list(MEDIA_TYPES),
    "target_percent": 75, "warning_percent": 85, "critical_percent": 92,
    "reserve_gib": 5, "allow_moves_in": True, "allow_moves_out": True,
}


def _number(value, low, high, name):
    if isinstance(value, bool):
        raise ValueError(f"Ungültiger Wert für {name}.")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Ungültiger Wert für {name}.") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"Ungültiger Wert für {name}.")
    return number


def validate_policy(raw: dict, previous: dict | None = None) -> dict:
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_POLICY):
        raise ValueError("Unbekannte Autopilot-Einstellung.")
    result = deepcopy(previous or DEFAULT_POLICY)
    result.update(raw)
    if result["mode"] not in MODES:
        raise ValueError("Ungültiger Autopilot-Modus.")
    for key in ("auto_delete", "window_enabled", "allow_series_split"):
        if not isinstance(result[key], bool):
            raise ValueError("Ungültige Freigabe.")
    if not isinstance(result["delete_categories"], list) or any(
        category not in ("royal_partials",)
        for category in result["delete_categories"]
    ):
        raise ValueError("Nur ausdrücklich freigegebene Royal-Artefakte sind zulässig.")
    result["delete_categories"] = sorted(set(result["delete_categories"]))
    for key in ("window_start", "window_end"):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(result[key])):
            raise ValueError("Ungültiges Zeitfenster.")
    for key, low, high in (
        ("interval_hours", 1, 168), ("cooldown_hours", 24, 8760),
        ("max_moves", 1, 5), ("max_move_gib", 1, 4096),
        ("unknown_download_gib", 1, 1024), ("archive_age_days", 30, 3650),
    ):
        result[key] = _number(result[key], low, high, key)
    return result


def validate_volume(raw: dict, previous: dict | None = None) -> dict:
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_VOLUME):
        raise ValueError("Unbekannte Volume-Einstellung.")
    result = deepcopy(previous or DEFAULT_VOLUME)
    result.update(raw)
    if result["role"] not in ROLES:
        raise ValueError("Ungültige Speicherrolle.")
    media = result["media_types"]
    if not isinstance(media, list) or not media or any(kind not in MEDIA_TYPES for kind in media):
        raise ValueError("Ungültige Medienarten.")
    result["media_types"] = sorted(set(media))
    for key in ("allow_moves_in", "allow_moves_out"):
        if not isinstance(result[key], bool):
            raise ValueError("Ungültiger Volume-Schutz.")
    for key in ("target_percent", "warning_percent", "critical_percent"):
        result[key] = _number(result[key], 1, 99, key)
    if not result["target_percent"] < result["warning_percent"] < result["critical_percent"]:
        raise ValueError("Ziel muss unter Warnung und Warnung unter der kritischen Schwelle liegen.")
    result["reserve_gib"] = _number(result["reserve_gib"], 1, 4096, "Reserve")
    return result


def volume_policy(root: dict, policies: dict) -> dict:
    defaults = deepcopy(DEFAULT_VOLUME)
    if root["key"] in ("movies", "series"):
        defaults["media_types"] = ["movies"] if root["key"] == "movies" else ["series", "anime"]
    allowed_media_types = [
        kind for kind in root.get("allowed_media_types", [])
        if kind in MEDIA_TYPES
    ]
    routing_explicit = bool(root.get("allowed_media_types_explicit"))
    if routing_explicit and allowed_media_types:
        defaults["media_types"] = allowed_media_types
    policy = validate_volume(policies.get(root["key"], {}), defaults)
    # Once the administrator explicitly chooses "what belongs here?" on an
    # additional location, that beginner-facing choice is authoritative.
    # Legacy locations keep any existing advanced media filter until they are
    # edited, avoiding a silent widening during upgrade.
    if routing_explicit and allowed_media_types:
        policy["media_types"] = allowed_media_types
    policy.update(root.get("_physical_policy", {}))
    if root.get("location_mode") == "monitor":
        policy["role"] = "monitor"
        policy["allow_moves_in"] = policy["allow_moves_out"] = False
    return policy
