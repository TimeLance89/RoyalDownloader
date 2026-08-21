"""HTTP security policy shared by the web and native API surfaces.

The module owns routing policy and response hardening only. Authentication
storage and application setup remain injected dependencies so this boundary
does not import the server composition root or its global state.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from proxy_security import host_allowed, origin_matches


PUBLIC_API_METHODS = {
    "/api/health": frozenset({"GET"}),
    "/api/auth/status": frozenset({"GET"}),
    "/api/auth/login": frozenset({"POST"}),
    "/api/auth/logout": frozenset({"POST"}),
    "/api/ui/config": frozenset({"GET"}),
    "/api/ui/translate": frozenset({"POST"}),
    "/api/v1/capabilities": frozenset({"GET"}),
    "/api/v1/health": frozenset({"GET"}),
    "/api/v1/auth/status": frozenset({"GET"}),
    "/api/v1/auth/login": frozenset({"POST"}),
    "/api/v1/auth/logout": frozenset({"POST"}),
    "/api/v1/ui/config": frozenset({"GET"}),
}

# Early native clients use these legacy aliases with a mobile bearer. Admin,
# setup and updater routes deliberately remain excluded.
MOBILE_LEGACY_API_PATHS = frozenset({
    "/api/genres",
    "/api/movies",
    "/api/movies/preload",
    "/api/tmdb/movie",
    "/api/tmdb/movies",
    "/api/tmdb/series",
    "/api/jellyfin/matches",
    "/api/series",
    "/api/series/load",
    "/api/series/jellyfin-status",
    "/api/anime",
    "/api/queue",
    "/api/queue/add",
    "/api/queue/remove",
    "/api/queue/clear",
    "/api/download/cancel",
    "/api/watchlist",
    "/api/watchlist/add",
    "/api/watchlist/mode",
    "/api/watchlist/remove",
    "/api/watchlist/check",
    "/api/watchlist/open",
    "/api/movie-subscriptions",
    "/api/movie-subscriptions/check",
    "/api/movie-subscriptions/remove",
})

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_MAX_API_BODY_BYTES = 2 * 1024 * 1024
MIN_MAX_API_BODY_BYTES = 64 * 1024
MAX_MAX_API_BODY_BYTES = 16 * 1024 * 1024


class RequestBodyTooLarge(RuntimeError):
    pass


@dataclass(frozen=True)
class SecurityDependencies:
    """Callbacks supplied by the application composition root."""

    setup_required: Callable[[], bool]
    request_is_authenticated: Callable[..., bool]
    authenticated_mobile_token: Callable[..., str]
    bearer_token: Callable[[Any], str]
    session_token: Callable[[dict], str]
    client_key: Callable[[Request], str]
    request_is_secure: Callable[[Request], bool]
    public_translate_limiter: Any


def _max_api_body_bytes() -> int:
    try:
        configured = int(
            os.environ.get("ROYAL_MAX_API_BODY_BYTES", DEFAULT_MAX_API_BODY_BYTES)
        )
    except (TypeError, ValueError):
        configured = DEFAULT_MAX_API_BODY_BYTES
    return min(MAX_MAX_API_BODY_BYTES, max(MIN_MAX_API_BODY_BYTES, configured))


def same_origin(request: Request, request_is_secure: Callable[[Request], bool]) -> bool:
    """Validate an optional Origin header against the effective request host."""
    origin = request.headers.get("origin", "")
    if not origin:
        return True
    # ``request_is_secure`` remains in the signature for compatibility with
    # direct tests/callers; proxy_security owns the authoritative origin logic.
    del request_is_secure
    return origin_matches(request, origin)


def is_public_path(path: str, method: str, setup_required: Callable[[], bool]) -> bool:
    """Return whether a path/method pair is available without a session."""
    normalized_method = str(method or "GET").upper()
    if normalized_method in PUBLIC_API_METHODS.get(path, ()):
        return True
    if path.startswith("/api/setup/") and setup_required():
        return True
    if (
        path in {"/api/ui/config", "/api/v1/ui/config"}
        and normalized_method == "POST"
        and setup_required()
    ):
        return True
    return not path.startswith("/api/")


def is_mobile_legacy_path(path: str) -> bool:
    return (
        path in MOBILE_LEGACY_API_PATHS
        or path.startswith("/api/movie/")
        or path.startswith("/api/anime/")
    )


def _websocket_csp_source(request: Request, request_is_secure) -> str:
    if not host_allowed(request):
        return ""
    host = str(request.headers.get("host", "") or "").strip()
    if not host:
        return ""
    return ("wss://" if request_is_secure(request) else "ws://") + host


def harden_http_response(
    request: Request,
    response: Response,
    path: str,
    request_is_secure: Callable[[Request], bool],
) -> Response:
    """Apply browser and proxy-safe headers consistently to every response."""
    websocket_source = _websocket_csp_source(request, request_is_secure)
    connect_sources = "'self'" + (f" {websocket_source}" if websocket_source else "")
    csp = "; ".join((
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-ancestors 'self'",
        "frame-src https://www.youtube-nocookie.com",
        "form-action 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",
        f"connect-src {connect_sources}",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "manifest-src 'self'",
    ))
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=()",
    )
    response.headers.setdefault("Content-Security-Policy", csp)
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers.setdefault("Pragma", "no-cache")
    if request_is_secure(request):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000",
        )
    return response


def _content_length_too_large(request: Request, maximum: int) -> bool:
    raw = str(request.headers.get("content-length", "") or "").strip()
    if not raw:
        return False
    try:
        value = int(raw)
    except ValueError:
        return True
    return value < 0 or value > maximum


def _install_receive_limit(request: Request, maximum: int) -> None:
    original_receive = request._receive
    received = 0

    async def limited_receive():
        nonlocal received
        message = await original_receive()
        if message.get("type") == "http.request":
            received += len(message.get("body") or b"")
            if received > maximum:
                raise RequestBodyTooLarge("API-Anfrage überschreitet das Größenlimit.")
        return message

    request._receive = limited_receive


def install_authentication_middleware(
    app: FastAPI,
    dependencies: SecurityDependencies,
) -> Callable:
    """Register the authentication boundary and return it for direct tests."""

    async def require_authentication(request: Request, call_next):
        path = request.url.path
        is_v1 = path.startswith("/api/v1/")

        def hardened(response: Response) -> Response:
            return harden_http_response(
                request, response, path, dependencies.request_is_secure,
            )

        if not host_allowed(request):
            return hardened(JSONResponse(
                status_code=400,
                content={
                    "detail": "Unzulässiger Host-Header.",
                    "code": "invalid_host",
                },
            ))

        if path.startswith("/api/"):
            maximum = _max_api_body_bytes()
            if _content_length_too_large(request, maximum):
                return hardened(JSONResponse(
                    status_code=413,
                    content={
                        "detail": "Die API-Anfrage ist zu groß.",
                        "code": "request_too_large",
                    },
                ))
            _install_receive_limit(request, maximum)

        if request.method in UNSAFE_METHODS:
            fetch_site = str(request.headers.get("sec-fetch-site", "") or "").casefold()
            if fetch_site == "cross-site":
                return hardened(JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Cross-Site-Anfrage wurde abgewiesen.",
                        "code": "cross_site_blocked",
                    },
                ))
            if not same_origin(request, dependencies.request_is_secure):
                return hardened(JSONResponse(
                    status_code=403,
                    content={"detail": "Anfrage von einem fremden Ursprung wurde abgewiesen."},
                ))

        client = dependencies.client_key(request)
        if path == "/api/ui/translate" and not dependencies.request_is_authenticated(
            request.headers, request.cookies, client,
        ):
            if not dependencies.public_translate_limiter.allow(client):
                return hardened(JSONResponse(
                    status_code=429,
                    content={"detail": "Zu viele Übersetzungsanfragen. Bitte kurz warten."},
                    headers={"Retry-After": "60"},
                ))
        mobile_legacy = is_mobile_legacy_path(path)
        if is_public_path(path, request.method, dependencies.setup_required) or (
            dependencies.request_is_authenticated(
                request.headers,
                request.cookies,
                client,
                versioned=is_v1,
                allow_mobile_bearer=is_v1 or mobile_legacy,
                allow_basic=not is_v1,
            )
        ):
            try:
                return hardened(await call_next(request))
            except RequestBodyTooLarge:
                return hardened(JSONResponse(
                    status_code=413,
                    content={
                        "detail": "Die API-Anfrage ist zu groß.",
                        "code": "request_too_large",
                    },
                ))
        if (
            not is_v1
            and not mobile_legacy
            and dependencies.authenticated_mobile_token(request.headers, touch=False)
        ):
            return hardened(JSONResponse(
                status_code=403,
                content={
                    "detail": "Diese Route ist für Mobile-Sitzungen nicht freigegeben.",
                    "code": "access_denied",
                },
                headers={"Cache-Control": "no-store"},
            ))
        supplied_session = bool(
            dependencies.bearer_token(request.headers)
            if is_v1
            else (
                dependencies.bearer_token(request.headers)
                or dependencies.session_token(request.cookies)
            )
        )
        return hardened(JSONResponse(
            status_code=401,
            content={
                "detail": (
                    "Die Sitzung ist abgelaufen oder wurde widerrufen."
                    if supplied_session
                    else "Anmeldung erforderlich."
                ),
                "code": "session_expired" if supplied_session else "auth_required",
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        ))

    app.middleware("http")(require_authentication)
    return require_authentication
