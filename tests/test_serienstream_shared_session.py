from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

import serienstream_shared_session as shared


class FakeCdp:
    def __init__(self):
        self.seed = []
        self.navigated = []
        self.clicked = []
        self._markers = {}

    def set_cookies(self, cookies):
        self.seed = list(cookies)

    def navigate(self, url):
        self.navigated.append(url)

    def click_hoster(self, url):
        self.clicked.append(url)
        return True

    def cookies(self):
        return [
            {
                "name": "session",
                "value": "abc",
                "domain": ".serienstream.to",
                "path": "/",
                "secure": True,
            },
            {
                "name": "foreign",
                "value": "ignored",
                "domain": "example.org",
                "path": "/",
                "secure": True,
            },
        ]

    def current_url(self):
        return "https://serienstream.to/r?t=token"

    def markers(self):
        return dict(self._markers)

    def html(self):
        return "<html>episode</html>"


class FakeRuntime:
    instances = []

    def __init__(self):
        self.cdp = FakeCdp()
        self.port = 12345
        self.closed = False
        FakeRuntime.instances.append(self)

    def start(self):
        return self.cdp

    def close(self):
        self.closed = True


def test_url_boundaries_only_allow_serienstream_provider_context():
    episode = "https://serienstream.to/serie/test/staffel-1/episode-2"
    assert shared.valid_episode_url(episode)
    assert shared.valid_provider_page_url(episode)
    assert shared.valid_provider_page_url("https://serienstream.to/serie/test")
    assert shared.valid_provider_page_url("https://serienstream.to/suche?term=test")
    assert shared.valid_redirect_url("https://serienstream.to/r?t=token")

    assert not shared.valid_episode_url("http://serienstream.to/serie/test/staffel-1/episode-2")
    assert not shared.valid_episode_url("https://evil.example/serie/test/staffel-1/episode-2")
    assert not shared.valid_episode_url("https://serienstream.to.evil.example/serie/test/staffel-1/episode-2")
    assert not shared.valid_episode_url("https://user:pass@serienstream.to/serie/test/staffel-1/episode-2")
    assert not shared.valid_redirect_url("https://serienstream.to/r?t=one&t=two")
    assert not shared.valid_redirect_url("https://serienstream.to/r?next=https://evil.example")
    assert not shared.valid_redirect_url("https://evil.example/r?t=token")
    assert not shared.valid_provider_page_url("https://serienstream.to/r?t=token")
    assert not shared.valid_provider_page_url("https://serienstream.to/serie/test#fragment")


def test_external_targets_and_cookie_filtering_are_provider_scoped():
    assert shared._external_http_url("https://voe.sx/e/final") == "https://voe.sx/e/final"
    assert shared._external_http_url("http://cdn.example/video") == "http://cdn.example/video"
    assert shared._external_http_url("https://serienstream.to/r?t=x") == ""
    assert shared._external_http_url("https://www.serienstream.to/r?t=x") == ""
    assert shared._external_http_url("https://challenges.cloudflare.com/turnstile") == ""
    assert shared._external_http_url("javascript:alert(1)") == ""
    assert shared._external_http_url("://bad") == ""

    cookies = shared._filtered_cookies([
        {"name": "session", "domain": ".serienstream.to"},
        {"name": "www", "domain": "www.serienstream.to"},
        {"name": "", "domain": ".serienstream.to"},
        {"name": "foreign", "domain": "example.org"},
    ])
    assert [cookie["name"] for cookie in cookies] == ["session", "www"]


def test_json_endpoint_is_fixed_to_loopback_and_closes_connection(monkeypatch):
    instances = []

    class Response:
        status = 200

        @staticmethod
        def read():
            return b'[{"type":"page"}]'

    class Connection:
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.requested = None
            self.closed = False
            instances.append(self)

        def request(self, method, path):
            self.requested = (method, path)

        def getresponse(self):
            return Response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(shared.http.client, "HTTPConnection", Connection)
    assert shared._json_endpoint(9222, "/json/list") == [{"type": "page"}]
    connection = instances[-1]
    assert (connection.host, connection.port, connection.timeout) == ("127.0.0.1", 9222, 3)
    assert connection.requested == ("GET", "/json/list")
    assert connection.closed

    with pytest.raises(ValueError):
        shared._json_endpoint(9222, "/not-devtools")


def test_json_endpoint_rejects_non_200_and_still_closes(monkeypatch):
    instance = SimpleNamespace(closed=False)

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args):
            pass

        def getresponse(self):
            return SimpleNamespace(status=500, read=lambda: b"error")

        def close(self):
            instance.closed = True

    monkeypatch.setattr(shared.http.client, "HTTPConnection", Connection)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        shared._json_endpoint(9222, "/json/list")
    assert instance.closed


def test_cdp_command_and_helpers_use_devtools_protocol(monkeypatch):
    sockets = []

    class Socket:
        def __init__(self):
            self.sent = []
            self.responses = []
            sockets.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send(self, payload):
            message = json.loads(payload)
            self.sent.append(message)
            method = message["method"]
            request_id = message["id"]
            if method == "Runtime.evaluate":
                expression = message["params"]["expression"]
                if "window.location.href" in expression:
                    value = "https://serienstream.to/episode"
                elif "document.documentElement" in expression:
                    value = "<html>turnstile playerPrepareModal challenges.cloudflare.com</html>"
                elif "data-play-url" in expression:
                    value = True
                else:
                    value = "ok"
                result = {"result": {"value": value}}
            elif method == "Network.getAllCookies":
                result = {"cookies": [{"name": "session"}]}
            else:
                result = {"ok": True}
            self.responses = [
                json.dumps({"id": request_id + 100, "result": {}}),
                json.dumps({"id": request_id, "result": result}),
            ]

        def recv(self, timeout):
            assert timeout == 10
            return self.responses.pop(0)

    monkeypatch.setattr(shared, "connect", lambda *args, **kwargs: Socket())
    cdp = shared._Cdp("ws://127.0.0.1/devtools/page/1")

    assert cdp.command("Page.enable") == {"ok": True}
    assert cdp.evaluate("1 + 1") == "ok"
    cdp.navigate("https://serienstream.to/serie/test")
    assert cdp.cookies() == [{"name": "session"}]
    cdp.set_cookies([{"name": "session", "value": "abc"}])
    cdp.set_cookies([])
    assert cdp.current_url() == "https://serienstream.to/episode"
    assert "turnstile" in cdp.html()
    assert cdp.markers() == {
        "turnstile": True,
        "gate_root": False,
        "prepare_modal": True,
        "challenge": True,
    }
    assert cdp.click_hoster("https://serienstream.to/r?t=exact")

    sent_methods = [sock.sent[0]["method"] for sock in sockets]
    assert "Page.navigate" in sent_methods
    assert "Network.getAllCookies" in sent_methods
    assert "Network.setCookies" in sent_methods


def test_cdp_command_surfaces_protocol_error(monkeypatch):
    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send(self, payload):
            self.request_id = json.loads(payload)["id"]

        def recv(self, timeout):
            return json.dumps({"id": self.request_id, "error": {"message": "boom"}})

    monkeypatch.setattr(shared, "connect", lambda *args, **kwargs: Socket())
    with pytest.raises(RuntimeError, match="boom"):
        shared._Cdp("ws://local").command("Page.navigate")


def test_page_and_external_target_selection(monkeypatch):
    targets = [
        {"type": "service_worker", "url": "https://voe.sx/ignored"},
        {"type": "page", "url": "https://serienstream.to/episode"},
        {
            "type": "page",
            "url": "https://voe.sx/e/final",
            "webSocketDebuggerUrl": "ws://page",
        },
    ]
    monkeypatch.setattr(shared, "_json_endpoint", lambda *_args: targets)
    assert shared._page_target(9222)["webSocketDebuggerUrl"] == "ws://page"
    assert shared._external_target(9222) == "https://voe.sx/e/final"

    monkeypatch.setattr(shared, "_json_endpoint", lambda *_args: (_ for _ in ()).throw(RuntimeError("down")))
    assert shared._external_target(9222) == ""


def test_browser_runtime_start_configures_persistent_profile_and_identity(monkeypatch, tmp_path):
    processes = []
    ports = iter([12340, 9222])

    class Process:
        def __init__(self, args, **kwargs):
            self.args = list(args)
            self.kwargs = kwargs
            self.terminated = False
            processes.append(self)

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            assert timeout == 3

        def kill(self):
            raise AssertionError("kill should not be needed")

    class StartCdp:
        def __init__(self, websocket_url):
            self.websocket_url = websocket_url
            self.commands = []

        def command(self, method, params=None):
            self.commands.append((method, params or {}))
            return {}

    monkeypatch.setattr(shared.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(shared, "_profile_dir", lambda: tmp_path / "profile")
    monkeypatch.setattr(shared, "_free_local_port", lambda: next(ports))
    monkeypatch.setattr(shared, "safe_proxy_url", lambda: "http://127.0.0.1:8080")
    monkeypatch.setattr(shared.subprocess, "Popen", Process)
    monkeypatch.setattr(
        shared,
        "_page_target",
        lambda port: {"webSocketDebuggerUrl": "ws://127.0.0.1/page"},
    )
    monkeypatch.setattr(shared, "_Cdp", StartCdp)

    runtime = shared._BrowserRuntime()
    cdp = runtime.start()
    assert runtime.port == 9222
    assert runtime.display == ":120"
    assert (tmp_path / "profile").is_dir()
    assert len(processes) == 2
    chrome_args = processes[1].args
    assert f"--user-agent={shared.SERIESSTREAM_USER_AGENT}" in chrome_args
    assert f"--user-data-dir={tmp_path / 'profile'}" in chrome_args
    assert "--proxy-server=http://127.0.0.1:8080" in chrome_args
    assert processes[1].kwargs["env"]["DISPLAY"] == ":120"
    methods = [method for method, _params in cdp.commands]
    assert methods == [
        "Network.enable",
        "Page.enable",
        "Runtime.enable",
        "Emulation.setDeviceMetricsOverride",
        "Network.setUserAgentOverride",
    ]
    runtime.close()
    assert all(process.terminated for process in processes)
    assert runtime.chrome is None and runtime.xvfb is None and runtime.cdp is None


def test_browser_runtime_requires_chromium_and_xvfb(monkeypatch):
    runtime = shared._BrowserRuntime()
    monkeypatch.setattr(shared.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="Chromium"):
        runtime.start()

    def only_chromium(name):
        return "/usr/bin/chromium" if name == "chromium" else None

    monkeypatch.setattr(shared.shutil, "which", only_chromium)
    with pytest.raises(RuntimeError, match="Xvfb"):
        shared._BrowserRuntime().start()


def test_browser_runtime_close_kills_process_after_timeout(monkeypatch):
    class Process:
        def __init__(self):
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("chrome", timeout)

        def kill(self):
            self.killed = True

    runtime = shared._BrowserRuntime()
    runtime.chrome = Process()
    runtime.xvfb = Process()
    chrome = runtime.chrome
    xvfb = runtime.xvfb
    runtime.close()
    assert chrome.killed and xvfb.killed


def test_wait_for_page_returns_first_normal_document(monkeypatch):
    class Page:
        def html(self):
            return "<html>ready</html>"

        def markers(self):
            return {"turnstile": False, "challenge": False}

    html, markers = shared._wait_for_page(Page(), timeout=1)
    assert html == "<html>ready</html>"
    assert not any(markers.values())


def test_wait_for_page_returns_last_gate_state_on_timeout(monkeypatch):
    clock = {"now": 0.0}

    def monotonic():
        clock["now"] += 0.4
        return clock["now"]

    class Page:
        def html(self):
            return "<html>turnstile</html>"

        def markers(self):
            return {"turnstile": True}

    monkeypatch.setattr(shared.time, "monotonic", monotonic)
    monkeypatch.setattr(shared.time, "sleep", lambda *_args: None)
    html, markers = shared._wait_for_page(Page(), timeout=1)
    assert html == "<html>turnstile</html>"
    assert markers["turnstile"]


def test_redirect_recovery_loads_episode_and_clicks_exact_hoster(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: ("<html>episode</html>", {}),
    )
    monkeypatch.setattr(shared, "_external_target", lambda _port: "https://voe.sx/e/final")

    seed = [{
        "name": "session",
        "value": "seed",
        "domain": "serienstream.to",
        "path": "/",
        "secure": True,
    }]
    redirect = "https://serienstream.to/r?t=token"
    episode = "https://serienstream.to/serie/test/staffel-1/episode-2"
    result = shared.resolve_provider_redirect(redirect, episode, seed)

    runtime = FakeRuntime.instances[-1]
    assert runtime.cdp.seed == seed
    assert runtime.cdp.navigated == [episode]
    assert runtime.cdp.clicked == [redirect]
    assert result.target == "https://voe.sx/e/final"
    assert [cookie["name"] for cookie in result.cookies] == ["session"]
    assert not result.gated
    assert runtime.closed


def test_redirect_recovery_never_clicks_when_interactive_challenge_is_present(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: (
            "<html>turnstile</html>",
            {"turnstile": True, "challenge": True},
        ),
    )

    result = shared.resolve_provider_redirect(
        "https://serienstream.to/r?t=token",
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    )

    runtime = FakeRuntime.instances[-1]
    assert runtime.cdp.clicked == []
    assert result.gated
    assert result.target == ""
    assert runtime.closed


def test_redirect_recovery_falls_back_to_validated_redirect_navigation(monkeypatch):
    class NoClickCdp(FakeCdp):
        def click_hoster(self, url):
            self.clicked.append(url)
            return False

        def current_url(self):
            return "https://voe.sx/e/from-current-tab"

    class NoClickRuntime(FakeRuntime):
        def __init__(self):
            self.cdp = NoClickCdp()
            self.port = 12345
            self.closed = False
            FakeRuntime.instances.append(self)

    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", NoClickRuntime)
    monkeypatch.setattr(shared, "_wait_for_page", lambda *_args, **_kwargs: ("<html>episode</html>", {}))
    monkeypatch.setattr(shared, "_external_target", lambda _port: "")

    redirect = "https://serienstream.to/r?t=token"
    episode = "https://serienstream.to/serie/test/staffel-1/episode-2"
    result = shared.resolve_provider_redirect(redirect, episode, [])
    runtime = FakeRuntime.instances[-1]
    assert runtime.cdp.navigated == [episode, redirect]
    assert result.target == "https://voe.sx/e/from-current-tab"
    assert runtime.closed


def test_redirect_recovery_rejects_unsafe_context_without_browser():
    assert shared.resolve_provider_redirect(
        "https://evil.example/r?t=token",
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    ).error == "unsafe_redirect_context"
    assert shared.resolve_provider_redirect(
        "https://serienstream.to/r?t=token",
        "https://evil.example/episode",
        [],
    ).error == "unsafe_redirect_context"


def test_redirect_recovery_returns_runtime_error_and_closes(monkeypatch):
    class BrokenRuntime(FakeRuntime):
        def start(self):
            raise RuntimeError("chrome failed")

    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", BrokenRuntime)
    result = shared.resolve_provider_redirect(
        "https://serienstream.to/r?t=token",
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    )
    assert result.error == "chrome failed"
    assert FakeRuntime.instances[-1].closed


def test_provider_html_recovers_normal_page_and_returns_shared_cookies(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: ("<html>normal episode</html>", {}),
    )

    result = shared.fetch_provider_html(
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    )

    assert result.html == "<html>normal episode</html>"
    assert not result.gated
    assert [cookie["name"] for cookie in result.cookies] == ["session"]
    assert FakeRuntime.instances[-1].closed


def test_provider_html_does_not_return_challenge_document(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: (
            "<html>turnstile</html>",
            {"turnstile": True, "gate_root": True},
        ),
    )

    result = shared.fetch_provider_html(
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    )

    assert result.html == ""
    assert result.gated
    assert FakeRuntime.instances[-1].closed


def test_provider_html_rejects_unsafe_url_and_returns_runtime_error(monkeypatch):
    assert shared.fetch_provider_html("https://evil.example/", []).error == "unsafe_provider_url"

    class BrokenRuntime(FakeRuntime):
        def start(self):
            raise RuntimeError("browser unavailable")

    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", BrokenRuntime)
    result = shared.fetch_provider_html("https://serienstream.to/serie/test", [])
    assert result.error == "browser unavailable"
    assert FakeRuntime.instances[-1].closed
