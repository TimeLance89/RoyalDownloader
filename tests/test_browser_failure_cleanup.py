from types import SimpleNamespace

import pytest

from core import security_runtime
from integrations import browser_cdp_proxy


@pytest.mark.parametrize("failure", ["constructor", "configuration"])
def test_remote_target_is_closed_if_cdp_setup_fails(monkeypatch, failure):
    closed = []
    monkeypatch.setattr(security_runtime, "_remote_new_target", lambda: (
        {"id": "owned-target", "webSocketDebuggerUrl": "ws://fixture/devtools/page/owned-target"}, {"existing"},
    ))
    monkeypatch.setattr(security_runtime, "_rewrite_remote_websocket_url", lambda value: value)
    monkeypatch.setattr(security_runtime, "_remote_close_target", closed.append)

    def connect(_url):
        if failure == "constructor":
            raise ConnectionError("fixture connection failure")
        return object()

    def configure(_module, _cdp):
        raise TimeoutError("fixture configuration failure")

    with pytest.raises((ConnectionError, TimeoutError)):
        security_runtime._remote_configured_target(SimpleNamespace(_Cdp=connect), configure)
    assert closed == ["owned-target"]


def test_remote_target_ownership_is_transferred_only_after_successful_setup(monkeypatch):
    closed, configured = [], []
    cdp = object()
    monkeypatch.setattr(security_runtime, "_remote_new_target", lambda: (
        {"id": "owned-target", "webSocketDebuggerUrl": "ws://fixture/devtools/page/owned-target"}, {"existing"},
    ))
    monkeypatch.setattr(security_runtime, "_rewrite_remote_websocket_url", lambda value: value)
    monkeypatch.setattr(security_runtime, "_remote_close_target", closed.append)
    result, process, before = security_runtime._remote_configured_target(
        SimpleNamespace(_Cdp=lambda _url: cdp), lambda _module, value: configured.append(value),
    )
    assert result is cdp
    assert configured == [cdp]
    assert before == {"existing"}
    assert closed == []
    process.terminate()
    process.terminate()
    assert closed == ["owned-target"]


def test_incomplete_remote_target_response_still_releases_created_tab(monkeypatch):
    from core import egress

    closed = []
    monkeypatch.setattr(egress, "get_manager", lambda: SimpleNamespace(mode="direct"))
    monkeypatch.setattr(security_runtime, "_remote_browser_targets", lambda: [])
    monkeypatch.setattr(security_runtime, "_remote_browser_json", lambda *_args, **_kwargs: {"id": "owned-target"})
    monkeypatch.setattr(security_runtime, "_remote_close_target", closed.append)
    with pytest.raises(RuntimeError):
        security_runtime._remote_new_target()
    assert closed == ["owned-target"]


@pytest.mark.parametrize("fail_on_send", [1, 2])
def test_cdp_proxy_closes_upstream_when_handshake_forwarding_fails(monkeypatch, fail_on_send):
    class Connection:
        def __init__(self):
            self.closed = False
            self.sends = 0

        def settimeout(self, _seconds):
            pass

        def sendall(self, _data):
            self.sends += 1
            if self.sends == fail_on_send:
                raise OSError("fixture broken pipe")

        def close(self):
            self.closed = True

    upstream = Connection()
    monkeypatch.setattr(browser_cdp_proxy.socket, "create_connection", lambda *_args, **_kwargs: upstream)
    monkeypatch.setattr(browser_cdp_proxy, "_read_request_head", lambda *_: (b"GET / HTTP/1.1\r\n\r\n", b"remainder"))
    server = SimpleNamespace(upstream_address=("127.0.0.1", 9223))
    browser_cdp_proxy._CDPProxyHandler(Connection(), ("127.0.0.1", 1), server)
    assert upstream.closed


def test_cdp_proxy_closes_upstream_if_worker_creation_hits_process_limit(monkeypatch):
    closed = []
    connection = SimpleNamespace(settimeout=lambda *_: None, sendall=lambda *_: None,
                                 close=lambda: closed.append(True))

    def fail_start():
        raise RuntimeError("cannot start new thread")

    monkeypatch.setattr(browser_cdp_proxy.socket, "create_connection", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(browser_cdp_proxy, "_read_request_head", lambda *_: (b"GET / HTTP/1.1\r\n\r\n", b""))
    monkeypatch.setattr(browser_cdp_proxy.threading, "Thread", lambda **_: SimpleNamespace(start=fail_start))
    with pytest.raises(RuntimeError, match="cannot start new thread"):
        browser_cdp_proxy._CDPProxyHandler(connection, ("127.0.0.1", 1),
                                          SimpleNamespace(upstream_address=("127.0.0.1", 9223)))
    assert closed == [True]
