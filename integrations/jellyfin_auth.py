"""Shared Jellyfin API authentication helpers.

Jellyfin 12 no longer accepts the legacy X-Emby-Token header by default.
Use the MediaBrowser Authorization scheme for all server-side API requests.
"""

from __future__ import annotations


def jellyfin_auth_headers(api_key: str, *, accept_json: bool = False) -> dict[str, str]:
    key = str(api_key or "").strip()
    headers = {
        "Authorization": f'MediaBrowser Token="{key}"',
    }
    if accept_json:
        headers["Accept"] = "application/json"
    return headers
