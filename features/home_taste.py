"""Home-only interpretation of aggregate taste; legacy ranking stays stable."""
from __future__ import annotations

from typing import Any, Mapping


def home_profile(profile: Mapping[str, Any], kind: str = "") -> dict[str, Any]:
    preferences = profile.get("home_preferences") or {}
    contextual = (preferences.get("by_media_type") or {}).get(kind) or {}
    short = preferences.get("short_term") or {}
    dimensions = {}
    for axis, values in (profile.get("dimensions") or {}).items():
        local = contextual.get(axis) or {}
        recent = short.get(axis) or {}
        dimensions[axis] = {}
        for name in values.keys() | local.keys() | recent.keys():
            base = float(values.get(name, 0))
            # Negative explicit evidence is never offset by recent curiosity.
            if base >= 0:
                if local:
                    base = 0.25 * base + 0.75 * float(local.get(name, 0))
                if base >= 0:
                    base += min(3.0, max(0.0, float(recent.get(name, 0)))) * 0.35
            dimensions[axis][name] = base
    return {**profile, "dimensions": dimensions}
