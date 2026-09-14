"""Network boundary for URLs obtained from untrusted provider pages.

The validating proxy deliberately resolves and connects itself.  A separate
"check then request" is not sufficient: DNS can change between both steps and
redirects can point at a private service.  Keeping the check at the connection
boundary also protects subprocesses and Chromium, not only Python requests.
"""

from __future__ import annotations

import atexit
import ipaddress
import select
import socket
import socketserver
import threading
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import SplitResult, urlsplit


ALLOWED_PORTS = frozenset({80, 443})
MAX_HEADER_BYTES = 64 * 1024


class UnsafeNetworkTarget(ValueError):
    """Raised when an external URL could reach a non-public network."""


@dataclass(frozen=True)
class ResolvedTarget:
    family: int
    sockaddr: tuple
    ip: str


def _public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeNetworkTarget("Ungültige Zieladresse") from exc
    if (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise UnsafeNetworkTarget("Private oder reservierte Netzwerkziele sind gesperrt")
    return str(address)


def resolve_public_host(
    hostname: str,
    port: int,
    *,
    resolver: Callable = socket.getaddrinfo,
) -> tuple[ResolvedTarget, ...]:
    """Resolve a host and reject the entire answer when any address is unsafe."""
    if not hostname or port not in ALLOWED_PORTS:
        raise UnsafeNetworkTarget("Nur öffentliche HTTP(S)-Ziele auf Port 80/443 sind erlaubt")
    try:
        answers = resolver(hostname, port, 0, socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise UnsafeNetworkTarget("Ziel konnte nicht sicher aufgelöst werden") from exc
    targets = []
    seen = set()
    for family, socktype, _proto, _canonname, sockaddr in answers:
        if socktype not in (0, socket.SOCK_STREAM) or family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = _public_ip(sockaddr[0])
        key = (family, ip, int(port))
        if key in seen:
            continue
        seen.add(key)
        targets.append(ResolvedTarget(family, tuple(sockaddr), ip))
    if not targets:
        raise UnsafeNetworkTarget("Ziel besitzt keine öffentliche IP-Adresse")
    return tuple(targets)


def ensure_public_http_url(
    raw_url: str,
    *,
    resolver: Callable = socket.getaddrinfo,
) -> SplitResult:
    """Validate an untrusted URL and resolve every advertised address."""
    try:
        parsed = urlsplit(str(raw_url or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise UnsafeNetworkTarget("Ungültige URL") from exc
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise UnsafeNetworkTarget("Nur vollständige HTTP(S)-URLs sind erlaubt")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeNetworkTarget("Zugangsdaten in URLs sind nicht erlaubt")
    expected_port = 443 if parsed.scheme.casefold() == "https" else 80
    port = expected_port if port is None else port
    resolve_public_host(parsed.hostname, port, resolver=resolver)
    return parsed


def is_public_http_url(raw_url: str, *, resolver: Callable = socket.getaddrinfo) -> bool:
    try:
        ensure_public_http_url(raw_url, resolver=resolver)
        return True
    except UnsafeNetworkTarget:
        return False


def validate_peer_ip(peer_ip: str, expected_ip: str) -> None:
    """Reject rebinding/routing surprises after the TCP connection exists."""
    actual = _public_ip(peer_ip)
    if ipaddress.ip_address(actual) != ipaddress.ip_address(expected_ip):
        raise UnsafeNetworkTarget("Verbindung endete an einer unerwarteten IP-Adresse")


def _connect_public(hostname: str, port: int, timeout: float = 20.0) -> socket.socket:
    last_error: Optional[Exception] = None
    for target in resolve_public_host(hostname, port):
        upstream = socket.socket(target.family, socket.SOCK_STREAM)
        upstream.settimeout(timeout)
        try:
            upstream.connect(target.sockaddr)
            validate_peer_ip(upstream.getpeername()[0], target.ip)
            upstream.settimeout(None)
            return upstream
        except (OSError, UnsafeNetworkTarget) as exc:
            last_error = exc
            upstream.close()
    raise OSError("Kein sicheres öffentliches Ziel erreichbar") from last_error


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = (left, right)
    while True:
        readable, _, _ = select.select(sockets, (), (), 60)
        if not readable:
            return
        for source in readable:
            target = right if source is left else left
            data = source.recv(64 * 1024)
            if not data:
                return
            target.sendall(data)


def _read_headers(client: socket.socket) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = client.recv(8192)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_HEADER_BYTES:
            raise UnsafeNetworkTarget("HTTP-Header ist zu groß")
    head, separator, remainder = data.partition(b"\r\n\r\n")
    if not separator:
        raise UnsafeNetworkTarget("Unvollständige Proxy-Anfrage")
    return head, remainder


def _connect_authority(authority: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(f"//{authority}")
        port = parsed.port or 443
    except ValueError as exc:
        raise UnsafeNetworkTarget("Ungültiges CONNECT-Ziel") from exc
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise UnsafeNetworkTarget("Ungültiges CONNECT-Ziel")
    return parsed.hostname, port


class _GuardProxyHandler(socketserver.BaseRequestHandler):
    def _error(self, status: str) -> None:
        try:
            self.request.sendall(
                f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode("ascii")
            )
        except OSError:
            pass

    def handle(self) -> None:
        upstream = None
        try:
            head, body = _read_headers(self.request)
            lines = head.split(b"\r\n")
            method, target, version = lines[0].decode("latin-1").split(" ", 2)
            if method.upper() == "CONNECT":
                hostname, port = _connect_authority(target)
                resolve_public_host(hostname, port)
                upstream = _connect_public(hostname, port)
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                _relay(self.request, upstream)
                return

            parsed = ensure_public_http_url(target)
            port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
            if parsed.scheme.casefold() != "http":
                raise UnsafeNetworkTarget("HTTPS muss per CONNECT übertragen werden")
            upstream = _connect_public(parsed.hostname or "", port)
            origin_target = parsed.path or "/"
            if parsed.query:
                origin_target += "?" + parsed.query
            filtered = [
                line for line in lines[1:]
                if not line.lower().startswith((b"proxy-connection:", b"connection:"))
            ]
            request = b"\r\n".join(
                [f"{method} {origin_target} {version}".encode("latin-1"), *filtered, b"Connection: close"]
            ) + b"\r\n\r\n" + body
            upstream.sendall(request)
            _relay(self.request, upstream)
        except UnsafeNetworkTarget:
            self._error("403 Forbidden")
        except (OSError, UnicodeError, ValueError):
            self._error("502 Bad Gateway")
        finally:
            if upstream is not None:
                upstream.close()


class _GuardProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


_proxy_lock = threading.Lock()
_proxy_server: Optional[_GuardProxyServer] = None
_proxy_thread: Optional[threading.Thread] = None


def safe_proxy_url() -> str:
    global _proxy_server, _proxy_thread
    with _proxy_lock:
        if _proxy_server is None:
            _proxy_server = _GuardProxyServer(("127.0.0.1", 0), _GuardProxyHandler)
            _proxy_thread = threading.Thread(
                target=_proxy_server.serve_forever,
                name="safe-outbound-proxy",
                daemon=True,
            )
            _proxy_thread.start()
        return f"http://127.0.0.1:{_proxy_server.server_address[1]}"


def request_proxy_kwargs(url: str) -> dict:
    ensure_public_http_url(url)
    proxy = safe_proxy_url()
    return {"proxies": {"http": proxy, "https": proxy}}


def stop_safe_proxy() -> None:
    global _proxy_server, _proxy_thread
    with _proxy_lock:
        server, thread = _proxy_server, _proxy_thread
        _proxy_server = None
        _proxy_thread = None
    if server is not None:
        server.shutdown()
        server.server_close()
    if thread is not None:
        thread.join(timeout=2)


atexit.register(stop_safe_proxy)
