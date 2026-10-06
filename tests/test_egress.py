"""Outbound-policy contracts, real local transport and fail-closed boundary."""

import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests
from curl_cffi import CurlOpt
from curl_cffi import requests as curl_requests

from core import egress_curl, egress_provider_requests, egress_requests, egress_urllib
from core import network_guard as guard
from core.egress import EgressError, EgressManager, classify, get_manager


@pytest.fixture
def privacy(monkeypatch):
    monkeypatch.setenv("ROYAL_EGRESS_MODE", "privacy")
    monkeypatch.setenv(
        "ROYAL_EGRESS_PROXY", "http://alice:private-password@127.0.0.1:9"
    )
    monkeypatch.delenv("ROYAL_EGRESS_PROXY_FILE", raising=False)
    monkeypatch.setenv("ROYAL_EGRESS_FAIL_CLOSED", "true")
    monkeypatch.setenv("ROYAL_EGRESS_LOCAL_BYPASS", "true")
    yield get_manager()
    guard.stop_safe_proxy()


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.25.1.1",
        "192.168.1.2",
        "10.0.0.1",
        "172.16.1.1",
        "172.31.1.1",
        "[::1]",
        "[fc00::1]",
        "[fe80::1]",
        "169.254.1.1",
        "localhost",
        "nas",
        "jellyfin",
        "seerr",
        "ollama",
        "nas.local",
        "nas.lan",
        "nas.home",
        "nas.internal",
        "nas.home.arpa",
        "nas.fritz.box",
        "NAS.LOCAL.",
    ],
)
def test_local_classification_without_dns(host, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_: pytest.fail("classification must not resolve DNS"),
    )
    assert classify(f"http://{host}/") == "local"


@pytest.mark.parametrize(
    "host",
    [
        "example.com",
        "93.184.216.34",
        "[2606:4700:4700::1111]",
        "172.32.0.1",
        "192.0.2.1",
        "0.0.0.0",
        "example.local.evil.com",
        "localhost.evil.com",
    ],
)
def test_external_classification(host):
    assert classify(f"https://{host}/") == "external"


def test_configuration_secret_file_and_redaction(tmp_path):
    secret = tmp_path / "egress-secret"
    secret.write_text("https://alice:private-password@proxy.example:8443\n")
    manager = EgressManager.from_environment(
        {"ROYAL_EGRESS_MODE": "privacy", "ROYAL_EGRESS_PROXY_FILE": str(secret)}
    )
    assert manager.redacted_proxy() == "https://***:***@proxy.example:8443"
    assert "alice" not in repr(manager) and "private-password" not in repr(manager)
    secret.write_text("http://rotated:secret@proxy.example")
    assert (
        "rotated"
        in EgressManager.from_environment(
            {"ROYAL_EGRESS_MODE": "privacy", "ROYAL_EGRESS_PROXY_FILE": str(secret)}
        ).proxy
    )


@pytest.mark.parametrize(
    "proxy",
    [
        "",
        "socks5://host:80",
        "http://:80",
        "http://host:bad",
        "http://host/path",
        "http://alice:private-password@host\n",
    ],
)
def test_invalid_configuration_fails_closed(proxy):
    # Strip only the harmless file trailing newline; embedded newlines rejected.
    if proxy.endswith("\n"):
        proxy = proxy[:-1] + "\nBAD"
    with pytest.raises(EgressError) as error:
        EgressManager.from_environment(
            {"ROYAL_EGRESS_MODE": "privacy", "ROYAL_EGRESS_PROXY": proxy}
        )
    assert "private-password" not in str(error.value)


def test_direct_policy_preserves_environment_and_options():
    manager = EgressManager()
    original = {"https_proxy": "old-proxy", "NO_PROXY": "localhost"}
    assert manager.request_options("https://example.com") == {}
    assert (
        manager.subprocess_environment("https://example.com", base=original) == original
    )
    assert manager.ytdlp_args() == []


def test_privacy_overrides_environment_and_untrusted_local(privacy):
    proxy = guard.safe_proxy_url()
    options = privacy.request_options("https://example.com")
    assert options["proxies"]["https"] == proxy
    assert privacy.proxy_for("http://nas:8096") == ""
    assert privacy.proxy_for("http://nas:8096", untrusted=True) == proxy
    env = privacy.subprocess_environment(
        "https://example.com", base={"ALL_PROXY": "evil", "NO_PROXY": "*"}
    )
    assert env["http_proxy"] == env["https_proxy"] == env["PIP_PROXY"] == proxy
    assert env["ALL_PROXY"] == env["NO_PROXY"] == ""
    assert "private-password" not in str(env)


def test_disabled_local_bypass_uses_guard(privacy, monkeypatch):
    monkeypatch.setenv("ROYAL_EGRESS_LOCAL_BYPASS", "false")
    assert get_manager().proxy_for("http://nas") == guard.safe_proxy_url()


def test_no_additional_application_http_clients_bypass_policy():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    allowed = {
        "core/egress_curl.py",
        "core/egress_requests.py",
        "core/egress_urllib.py",
    }
    files = [root / "server.py"]
    for directory in [
        "core",
        "providers",
        "integrations",
        "media",
        "updates",
        "application_services",
        "features",
        "api",
    ]:
        files.extend((root / directory).rglob("*.py"))
    for path in files:
        if path.relative_to(root).as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(
                    item.name
                    in {
                        "requests",
                        "curl_cffi.requests",
                        "urllib.request",
                        "httpx",
                        "aiohttp",
                    }
                    for item in node.names
                ), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in {
                    "requests",
                    "curl_cffi.requests",
                    "urllib.request",
                    "httpx",
                    "aiohttp",
                }, path
                assert not (
                    node.module == "curl_cffi"
                    and any(item.name == "requests" for item in node.names)
                ), path


def test_urllib_rejects_other_protocols_in_privacy(privacy):
    with pytest.raises(EgressError, match="HTTP"):
        egress_urllib.urlopen("ftp://example.com/media")


def test_requests_policy_enforced_at_send(privacy, monkeypatch):
    seen = []

    def send(_session, request, **kwargs):
        seen.append(kwargs["proxies"])
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(requests.Session, "send", send)
    for url in ["https://example.com", "http://nas:8096"]:
        with egress_requests.Session() as session:
            session.send(
                requests.Request("GET", url).prepare(), proxies={"https": "http://evil"}
            )
    assert seen[0]["https"] == guard.safe_proxy_url()
    assert seen[1]["https"] == ""
    with egress_provider_requests.Session() as session:
        session.send(requests.Request("GET", "http://127.0.0.1").prepare())
    assert seen[-1]["http"] == guard.safe_proxy_url()


def test_curl_policy_ignores_per_request_and_environment_bypass(privacy, monkeypatch):
    seen = []

    def request(session, method, url, **kwargs):
        seen.append((session.trust_env, session.curl_options[CurlOpt.NOPROXY], kwargs))
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(curl_requests.Session, "request", request)
    with egress_curl.Session(impersonate="chrome") as session:
        session.get("https://example.com", proxy="http://evil", proxies={"https": ""})
    assert seen[0][0:2] == (False, "")
    assert seen[0][2]["proxies"]["https"] == guard.safe_proxy_url()
    assert "proxy" not in seen[0][2]


def test_urllib_external_redirect_cannot_become_lan(privacy):
    handler = egress_urllib._PolicyProxyHandler()
    req = urllib.request.Request("https://example.com")
    handler.proxy_open(req, "ignored", "https")
    redirected = egress_urllib._PolicyRedirectHandler().redirect_request(
        req, None, 302, "Found", {}, "http://127.0.0.1/private"
    )
    handler.proxy_open(redirected, "ignored", "http")
    assert redirected.host == urllib.request.Request(guard.safe_proxy_url()).host
    assert redirected._egress_external is True


def test_browser_and_ytdlp_no_alternative_direct_route(privacy):
    args = privacy.browser_proxy_args()
    assert f"--proxy-server={guard.safe_proxy_url()}" in args
    assert "--proxy-bypass-list=<-loopback>" in args
    assert "--disable-quic" in args
    assert "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1" in args
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args
    assert "private-password" not in str(args)
    assert privacy.ytdlp_args() == [
        "--downloader-args",
        "ffmpeg:-protocol_whitelist file,http,https,tcp,tls,crypto",
    ]


def test_dns_uses_egress_not_system_resolver(privacy, monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_: pytest.fail("direct DNS"))

    def query(_self, host, kind):
        calls.append((host, kind))
        return ["93.184.216.34"] if kind == "A" else []

    monkeypatch.setattr(EgressManager, "_dns_query", query)
    assert guard.resolve_public_host("example.com", 443)[0].ip == "93.184.216.34"
    assert calls == [("example.com", "A"), ("example.com", "AAAA")]


def test_remote_dns_mixed_private_answers_rejected(privacy, monkeypatch):
    monkeypatch.setattr(
        EgressManager, "_dns_query", lambda *_: ["93.184.216.34", "127.0.0.1"]
    )
    with pytest.raises(guard.UnsafeNetworkTarget):
        guard.resolve_public_host("example.com", 443)


def test_proxy_connect_pins_public_ip(privacy, monkeypatch):
    monkeypatch.setattr(EgressManager, "_dns_query", lambda *_: ["93.184.216.34"])
    calls = []
    target = object()

    def connect(_self, host, port, timeout):
        calls.append((host, port))
        return target

    monkeypatch.setattr(EgressManager, "connect_tunnel", connect)
    assert guard._connect_public("example.com", 443) is target
    assert calls == [("93.184.216.34", 443)]


@pytest.mark.parametrize("transport", [egress_requests, egress_curl, egress_urllib])
def test_offline_proxy_no_direct_retry(privacy, monkeypatch, transport, caplog):
    calls = []
    original = socket.create_connection

    def connect(address, *args, **kwargs):
        calls.append(address)
        # The test client may connect only to the guard, and the guard to proxy.
        assert address[0] == "127.0.0.1"
        if address[1] == 9:
            raise OSError("offline")
        return original(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", connect)
    # Literal public IP needs no DNS; no external sockets are allowed.
    with pytest.raises(
        (
            OSError,
            requests.RequestException,
            curl_requests.RequestsError,
            urllib.error.URLError,
        )
    ):
        if transport is egress_urllib:
            transport.urlopen("http://93.184.216.34/", timeout=2)
        else:
            response = transport.get("http://93.184.216.34/", timeout=2)
            response.raise_for_status()
    assert ("127.0.0.1", 9) in calls
    assert "alice" not in caplog.text and "private-password" not in caplog.text


@pytest.fixture
def lan_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(2)


@pytest.mark.parametrize("service", ["jellyfin", "seerr", "ollama", "libretranslate"])
def test_actual_lan_request_stays_local_with_offline_proxy(
    privacy, lan_server, service
):
    assert egress_requests.get(f"{lan_server}/{service}", timeout=2).text == "ok"
    with egress_urllib.urlopen(f"{lan_server}/{service}", timeout=2) as response:
        assert response.read() == b"ok"


def test_provider_cannot_access_lan(privacy, lan_server):
    response = egress_provider_requests.get(lan_server, timeout=2)
    assert response.status_code == 403


def test_missing_proxy_raises_library_error_without_fallback(privacy, monkeypatch):
    monkeypatch.setenv("ROYAL_EGRESS_PROXY", "")
    with pytest.raises(requests.ConnectionError, match="Egress"):
        egress_requests.get("https://example.com", timeout=1)
    with pytest.raises(curl_requests.RequestsError, match="Egress"):
        egress_curl.get("https://example.com", timeout=1)


def test_unmanaged_remote_browser_fails_closed(privacy, monkeypatch):
    from core import security_runtime

    monkeypatch.setenv("ROYAL_BROWSER_CDP_URL", "http://unmanaged:9222")
    with pytest.raises(EgressError, match="verwalteten"):
        security_runtime._remote_new_target()


def test_ytdlp_probe_actual_command_and_child_environment(privacy, monkeypatch):
    from media import downloader

    captured = []
    monkeypatch.setattr(downloader, "ensure_public_http_url", lambda *_: None)

    def run(cmd, **kwargs):
        captured.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok")

    monkeypatch.setattr(downloader.subprocess, "run", run)
    assert downloader.probe_stream_url("http://93.184.216.34/video")[0]
    cmd, kwargs = captured[0]
    assert cmd[cmd.index("--proxy") + 1] == guard.safe_proxy_url()
    assert "--downloader-args" in cmd
    assert kwargs["env"]["https_proxy"] == guard.safe_proxy_url()
    assert kwargs["env"]["NO_PROXY"] == ""


def test_ffprobe_actual_child_environment(privacy, monkeypatch):
    from media import media_quality

    captured = []
    monkeypatch.setattr(media_quality, "ensure_public_http_url", lambda *_: None)

    def run(cmd, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"streams":[]}')

    monkeypatch.setattr(media_quality.subprocess, "run", run)
    media_quality.probe_media_profile("http://93.184.216.34/video")
    assert captured[0]["env"]["http_proxy"] == guard.safe_proxy_url()


def test_pip_actual_child_environment(privacy, monkeypatch):
    from updates import ytdlp_updater

    captured = []

    def run(cmd, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ytdlp_updater.subprocess, "run", run)
    ytdlp_updater.YtDlpRuntimeUpdater._run_pip(["download", "yt-dlp"], timeout=2)
    assert captured[0]["env"]["PIP_PROXY"] == guard.safe_proxy_url()


def test_managed_browser_launcher_policy(privacy):
    from core import browser_egress

    cmd = browser_egress.command(
        ["chromium", "--user-data-dir=/profile", "about:blank"]
    )
    assert cmd[:3] == ["chromium", "--user-data-dir=/profile", "about:blank"]
    assert "--proxy-bypass-list=<-loopback>" in cmd
    assert "private-password" not in str(cmd)


@pytest.mark.parametrize("tls", [False, True])
def test_real_authenticated_proxy_chain(privacy, monkeypatch, tmp_path, tls):
    import base64
    import datetime
    import ipaddress
    import socketserver
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    context = None
    if tls:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-proxy")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        monkeypatch.setenv("SSL_CERT_FILE", str(cert_path))

    captured = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            head, _ = guard._read_headers(self.request)
            captured.append(head)
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            request, _ = guard._read_headers(self.request)
            captured.append(request)
            self.request.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            )

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

        def get_request(self):
            connection, address = super().get_request()
            if context:
                connection = context.wrap_socket(connection, server_side=True)
            return connection, address

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    scheme = "https" if tls else "http"
    monkeypatch.setenv(
        "ROYAL_EGRESS_PROXY",
        f"{scheme}://alice:private-password@127.0.0.1:{server.server_address[1]}",
    )
    try:
        assert egress_requests.get("http://93.184.216.34/test", timeout=3).text == "ok"
        assert captured[0].startswith(b"CONNECT 93.184.216.34:80 HTTP/1.1")
        authorization = b"Proxy-Authorization: Basic " + base64.b64encode(
            b"alice:private-password"
        )
        assert authorization in captured[0]
        assert authorization not in captured[1]
        assert captured[1].startswith(b"GET /test HTTP/1.1")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_doh_transport_and_ttl_cache(privacy, monkeypatch):
    import io
    import json

    from core import egress

    egress._dns_cache.clear()

    payload = json.dumps(
        {"Status": 0, "Answer": [{"type": 1, "data": "93.184.216.34", "TTL": 30}]}
    ).encode()
    response = (
        b"HTTP/1.1 200 OK\r\nContent-Length: "
        + str(len(payload)).encode()
        + b"\r\n\r\n"
        + payload
    )
    captured = []

    class Connection:
        def makefile(self, *_):
            return io.BytesIO(response)

        def sendall(self, data):
            captured.append(data)

        def close(self):
            pass

    def connect(_manager, host, port, *_):
        assert (host, port) == ("1.1.1.1", 443)
        return Connection()

    monkeypatch.setattr(EgressManager, "connect_tunnel", connect)
    monkeypatch.setattr(
        egress.ssl,
        "create_default_context",
        lambda: SimpleNamespace(
            wrap_socket=lambda connection, server_hostname: connection
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_: pytest.fail("direct DNS"))
    assert privacy._dns_query("example.com", "A") == ["93.184.216.34"]
    assert privacy._dns_query("example.com", "A") == ["93.184.216.34"]
    assert len(captured) == 1
    assert b"name=example.com&type=A" in captured[0]
    assert b"Host: cloudflare-dns.com" in captured[0]
    assert "private-password" not in str(captured)
    egress._dns_cache.clear()


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_native_ffprobe_transfer_through_guard_and_egress(
    privacy, monkeypatch, tmp_path, scheme
):
    import datetime
    import ipaddress
    import shutil
    import socketserver
    import ssl
    import subprocess

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from media import media_quality

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("native ffmpeg/ffprobe unavailable")
    media = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=160x90:rate=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc",
            "-t",
            "0.2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(media),
        ],
        check=True,
        timeout=20,
    )
    data = media.read_bytes()
    context = None
    if scheme == "https":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-media")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("93.184.216.34"))]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
    captured = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            connection = self.request
            head, _ = guard._read_headers(connection)
            captured.append(head)
            connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if context:
                connection = context.wrap_socket(connection, server_side=True)
            try:
                head, _ = guard._read_headers(connection)
                captured.append(head)
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Length: "
                    + str(len(data)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + data
                )
            finally:
                connection.close()

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "ROYAL_EGRESS_PROXY", f"http://127.0.0.1:{server.server_address[1]}"
    )
    try:
        profile, error = media_quality.probe_media_profile(
            f"{scheme}://93.184.216.34/video.mp4", timeout=10
        )
        assert not error
        assert profile["height"] == 90 and profile["audio_codec"] == "aac"
        port = 443 if scheme == "https" else 80
        assert captured[0].startswith(f"CONNECT 93.184.216.34:{port} ".encode())
        assert any(head.startswith(b"GET /video.mp4 ") for head in captured)
        if scheme == "http":
            import sys

            destination = tmp_path / "downloaded.mp4"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "yt_dlp",
                    "--force-generic-extractor",
                    "--proxy",
                    guard.safe_proxy_url(),
                    "--output",
                    str(destination),
                    "http://93.184.216.34/video.mp4",
                ],
                env=privacy.subprocess_environment(
                    "http://93.184.216.34", untrusted=True
                ),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            assert destination.read_bytes() == data
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
