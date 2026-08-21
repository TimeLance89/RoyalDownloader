"""Install security guards that require the completed application graph."""

from functools import wraps
from urllib.parse import urlparse

from application_services.runtime import _registered_backend
from security_runtime import install_post_state_security


backend = _registered_backend()
_original_get_jellyfin_client = backend.get_jellyfin_client


@wraps(_original_get_jellyfin_client)
def secure_get_jellyfin_client():
    """Only allow the explicit HTTP(S) schemes required by Jellyfin."""
    client = _original_get_jellyfin_client()
    raw = str(getattr(client, "base_url", "") or "").strip()
    if not raw:
        return client
    try:
        parsed = urlparse(raw)
    except ValueError:
        parsed = None
    if parsed is None or parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        # Preserve the client API but make unsafe configurations unconfigured so
        # no urllib call can dispatch file:, data:, ftp:, or custom schemes.
        client.base_url = ""
        client.api_key = ""
    return client


backend.get_jellyfin_client = secure_get_jellyfin_client
install_post_state_security(backend)
