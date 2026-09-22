import asyncio
import threading

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from api.api_security import (
    SecurityDependencies,
    harden_http_response,
    install_authentication_middleware,
    is_mobile_legacy_path,
    is_public_path,
)


class _AllowAllLimiter:
    def allow(self, _key):
        return True


def test_public_api_policy_is_method_aware():
    assert is_public_path("/api/auth/first-login", "POST", lambda: False)
    assert not is_public_path("/api/auth/first-login", "GET", lambda: False)
    assert is_public_path("/api/ui/config", "GET", lambda: False)
    assert not is_public_path("/api/ui/config", "POST", lambda: False)
    assert is_public_path("/api/ui/config", "POST", lambda: True)
    assert not is_public_path("/api/config", "GET", lambda: False)


def test_mobile_legacy_policy_excludes_administration():
    assert is_mobile_legacy_path("/api/movie/example")
    assert is_mobile_legacy_path("/api/queue/add")
    assert not is_mobile_legacy_path("/api/updater/install")
    assert not is_mobile_legacy_path("/api/setup/complete")


def test_csp_allows_only_the_youtube_nocookie_trailer_frame():
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"host", b"localhost")],
        "scheme": "https",
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 443),
    })
    response = harden_http_response(
        request,
        Response(),
        "/",
        lambda _request: True,
    )
    directives = {
        directive.strip()
        for directive in response.headers["content-security-policy"].split(";")
    }

    frame_sources = next(
        directive.split()[1:]
        for directive in directives
        if directive.startswith("frame-src ")
    )
    assert frame_sources == ["https://www.youtube-nocookie.com"]
    assert "frame-ancestors 'self'" in directives
    connect_sources = next(
        directive.split()[1:]
        for directive in directives
        if directive.startswith("connect-src ")
    )
    assert connect_sources == ["'self'", "wss://localhost"]


def test_session_validation_runs_outside_the_event_loop(monkeypatch):
    monkeypatch.delenv("ROYAL_ALLOWED_HOSTS", raising=False)
    application = FastAPI()
    validation_threads = []
    middleware = install_authentication_middleware(
        application,
        SecurityDependencies(
            setup_required=lambda: False,
            request_is_authenticated=lambda *_args, **_kwargs: (
                validation_threads.append(threading.get_ident()) or True
            ),
            authenticated_mobile_token=lambda *_args, **_kwargs: "",
            bearer_token=lambda _headers: "",
            session_token=lambda _cookies: "",
            client_key=lambda _request: "test-client",
            request_is_secure=lambda _request: False,
            public_translate_limiter=_AllowAllLimiter(),
        ),
    )
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/private",
        "headers": [(b"host", b"localhost")],
        "scheme": "http",
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 80),
    })

    async def exercise():
        event_loop_thread = threading.get_ident()

        async def call_next(_request):
            return Response()

        response = await middleware(request, call_next)
        return event_loop_thread, response

    event_loop_thread, response = asyncio.run(exercise())
    assert response.status_code == 200
    assert validation_threads
    assert validation_threads[0] != event_loop_thread
