"""Install security guards that require the completed application graph."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any
from urllib.parse import urlparse

from application_services.runtime import _registered_backend
from security_runtime import install_post_state_security


@dataclass(frozen=True)
class SecurityHardeningDependencies:
    """Explicit seams required to harden the completed runtime graph."""

    get_jellyfin_client: Callable[[], Any]
    replace_jellyfin_client_getter: Callable[[Callable[[], Any]], None]
    install_post_state_security: Callable[[], None]


def _composition_dependencies() -> SecurityHardeningDependencies:
    backend = _registered_backend()
    return SecurityHardeningDependencies(
        get_jellyfin_client=backend.get_jellyfin_client,
        replace_jellyfin_client_getter=lambda getter: setattr(
            backend, "get_jellyfin_client", getter,
        ),
        install_post_state_security=lambda: install_post_state_security(backend),
    )


def install_security_hardening(
    dependencies: SecurityHardeningDependencies | None = None,
) -> Callable[[], Any]:
    """Install post-state security through explicit, independently testable seams."""
    deps = dependencies or _composition_dependencies()
    original_get_jellyfin_client = deps.get_jellyfin_client

    @wraps(original_get_jellyfin_client)
    def secure_get_jellyfin_client():
        """Only allow the explicit HTTP(S) schemes required by Jellyfin."""
        client = original_get_jellyfin_client()
        raw = str(getattr(client, "base_url", "") or "").strip()
        if not raw:
            return client
        try:
            parsed = urlparse(raw)
        except ValueError:
            parsed = None
        if (
            parsed is None
            or parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.hostname
        ):
            # Preserve the client API but make unsafe configurations
            # unconfigured so no urllib call can dispatch file:, data:, ftp:,
            # or a custom scheme.
            client.base_url = ""
            client.api_key = ""
        return client

    deps.replace_jellyfin_client_getter(secure_get_jellyfin_client)
    deps.install_post_state_security()
    return secure_get_jellyfin_client


install_security_hardening()
