"""Shared, fail-closed Jellyfin profile and user-scoped item validation."""

from integrations.jellyfin_saved import jellyfin_id


class JellyfinPermissionError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def _invalid():
    return JellyfinPermissionError(502, "invalid_jellyfin_response", "Jellyfin lieferte ungültige Berechtigungsdaten.")


def require_jellyfin_profile(user, profile_id):
    try:
        valid = isinstance(user, dict) and jellyfin_id(user.get("Id")) == jellyfin_id(profile_id)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid or not isinstance(user.get("Policy"), dict):
        raise _invalid()
    policy = user["Policy"]
    if policy.get("IsDisabled", True) is not False or policy.get("EnableMediaPlayback", True) is not True:
        raise JellyfinPermissionError(403, "profile_forbidden", "Das Jellyfin-Profil hat keinen Wiedergabezugriff.")
    return user


def require_jellyfin_item(payload, item_id, *, types=("Movie", "Episode")):
    if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list):
        raise _invalid()
    items = payload["Items"]
    item = items[0] if len(items) == 1 else None
    try:
        valid = isinstance(item, dict) and jellyfin_id(item.get("Id")) == jellyfin_id(item_id)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if (not valid or item.get("Type") not in types or item.get("LocationType") in ("Virtual", "Offline")
            or item.get("IsPlaceHolder") is True):
        raise JellyfinPermissionError(404, "media_not_found", "Dieser Inhalt ist im verknüpften Jellyfin-Profil nicht verfügbar.")
    return item
