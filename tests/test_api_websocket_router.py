from starlette.websockets import WebSocket

from api_websocket_router import websocket_origin_allowed


async def _receive():
    return {"type": "websocket.disconnect"}


async def _send(_message):
    return None


def websocket(*, origin: str, host="royal.example", forwarded="https"):
    headers = [(b"host", host.encode()), (b"origin", origin.encode())]
    if forwarded:
        headers.append((b"x-forwarded-proto", forwarded.encode()))
    return WebSocket(
        {
            "type": "websocket",
            "path": "/ws",
            "scheme": "ws",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": (host, 443),
            "subprotocols": [],
        },
        _receive,
        _send,
    )


def test_websocket_origin_uses_effective_proxy_scheme_and_allowlisted_host(monkeypatch):
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "royal.example")
    assert websocket_origin_allowed(websocket(origin="https://royal.example"))
    assert not websocket_origin_allowed(websocket(origin="http://royal.example"))
    assert not websocket_origin_allowed(websocket(origin="https://other.example"))


def test_public_websocket_host_fails_closed_without_allowlist(monkeypatch):
    monkeypatch.delenv("ROYAL_ALLOWED_HOSTS", raising=False)
    assert not websocket_origin_allowed(websocket(origin="https://royal.example"))


def test_cookie_websocket_without_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "royal.example")
    assert not websocket_origin_allowed(websocket(origin=""))
