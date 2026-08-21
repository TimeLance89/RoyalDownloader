from starlette.requests import Request
from starlette.responses import Response

from api_security import harden_http_response, is_mobile_legacy_path, is_public_path


def test_public_api_policy_is_method_aware():
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

    assert "frame-src https://www.youtube-nocookie.com" in directives
    assert "frame-ancestors 'self'" in directives
    assert not any(directive.startswith("frame-src *") for directive in directives)
    assert not any("youtube.com" in directive for directive in directives)
