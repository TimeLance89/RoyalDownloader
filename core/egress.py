"""Central outbound policy. No proxy credentials cross the local guard boundary.

Local classification is lexical, never based on an external DNS answer. Provider
URLs still go through network_guard even when they resemble a local service.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlencode, urlsplit


class EgressError(OSError):
    """Sanitized policy/transport failure suitable for existing error paths."""


def _boolean(env, name, default=True):
    value = str(env.get(name, str(default))).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise EgressError(f"Ungültige Einstellung: {name}")
    return value in {"true", "1", "yes"}


def classify(url: str) -> str:
    """Recognize explicitly local names/IPs without doing DNS lookups."""
    host = ""
    try:
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
        if not host:
            raise ValueError
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        if not host or ":" in host:
            raise EgressError("Ungültiges Netzwerkziel") from None
        return (
            "local"
            if (
                "." not in host
                and ":" not in host
                or host == "localhost"
                or host.endswith(
                    (
                        ".localhost",
                        ".local",
                        ".lan",
                        ".home",
                        ".internal",
                        ".home.arpa",
                        ".fritz.box",
                    )
                )
            )
            else "external"
        )
    local = (
        address.is_loopback
        or address.is_link_local
        or any(
            address in network
            for network in _LOCAL_NETWORKS
            if address.version == network.version
        )
    )
    return "local" if local else "external"


_LOCAL_NETWORKS = tuple(
    map(
        ipaddress.ip_network,
        (
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "fc00::/7",
        ),
    )
)

_dns_cache = {}
_dns_lock = threading.Lock()


@dataclass(frozen=True)
class EgressManager:
    mode: str = "direct"
    proxy: str = field(default="", repr=False)
    local_bypass: bool = True

    @classmethod
    def from_environment(cls, env=None):
        env = os.environ if env is None else env
        mode = str(env.get("ROYAL_EGRESS_MODE", "direct")).strip().lower()
        if mode not in {"direct", "privacy"}:
            raise EgressError("ROYAL_EGRESS_MODE muss direct oder privacy sein")
        proxy = str(env.get("ROYAL_EGRESS_PROXY", "")).strip()
        secret_file = str(env.get("ROYAL_EGRESS_PROXY_FILE", "")).strip()
        if mode == "privacy" and secret_file:
            if proxy:
                raise EgressError("Nur eine Egress-Proxy-Quelle konfigurieren")
            try:
                proxy = Path(secret_file).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                raise EgressError("Egress-Proxy-Datei nicht lesbar") from None
        manager = cls(
            mode=mode,
            proxy=proxy,
            local_bypass=_boolean(env, "ROYAL_EGRESS_LOCAL_BYPASS"),
        )
        if mode == "privacy":
            manager._proxy_parts()
        return manager

    def _proxy_parts(self):
        try:
            parts = urlsplit(self.proxy)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.path not in {"", "/"}
                or parts.query
                or parts.fragment
                or any(char in self.proxy for char in "\r\n\x00")
                or not 1
                <= (parts.port or (443 if parts.scheme == "https" else 80))
                <= 65535
            ):
                raise ValueError
            return parts
        except ValueError:
            raise EgressError(
                "Privacy-Modus benötigt einen gültigen HTTP(S)-Egress-Proxy"
            ) from None

    def redacted_proxy(self):
        if not self.proxy:
            return ""
        parts = self._proxy_parts()
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        auth = "***:***@" if parts.username is not None else ""
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{auth}{host}{port}"

    def proxy_for(self, url, *, untrusted=False):
        if self.mode == "direct":
            return None
        if not untrusted and self.local_bypass and classify(url) == "local":
            return ""
        from core.network_guard import safe_proxy_url

        return safe_proxy_url()

    def request_options(self, url, *, untrusted=False):
        proxy = self.proxy_for(url, untrusted=untrusted)
        return (
            {}
            if proxy is None
            else {"proxies": {"http": proxy, "https": proxy, "all": ""}}
        )

    def subprocess_environment(self, url, *, untrusted=False, base=None):
        env = dict(os.environ if base is None else base)
        proxy = self.proxy_for(url, untrusted=untrusted)
        if proxy is not None:
            for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                env[key] = proxy
            for key in ("all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
                env[key] = ""
            # pip configuration must not override the policy or choose another index.
            env["PIP_PROXY"] = proxy
        return env

    def browser_proxy_args(self):
        from core.network_guard import safe_proxy_url

        args = [f"--proxy-server={safe_proxy_url()}"]
        if self.mode == "privacy":
            args += [
                "--proxy-bypass-list=<-loopback>",
                "--disable-quic",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                "--disable-background-networking",
                "--dns-prefetch-disable",
            ]
        return args

    def connect_tunnel(self, host, port, timeout=20.0):
        """CONNECT to a validated literal IP. TLS to HTTPS proxies is verified."""
        parts = self._proxy_parts()
        connection = None
        try:
            connection = socket.create_connection(
                (
                    parts.hostname,
                    parts.port or (443 if parts.scheme == "https" else 80),
                ),
                timeout,
            )
            if parts.scheme == "https":
                context = ssl.create_default_context()
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                connection = context.wrap_socket(
                    connection, server_hostname=parts.hostname
                )
            authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            headers = [f"CONNECT {authority} HTTP/1.1", f"Host: {authority}"]
            if parts.username is not None:
                username, password = (
                    unquote(parts.username),
                    unquote(parts.password or ""),
                )
                credentials = f"{username}:{password}".encode()
                headers.append(
                    "Proxy-Authorization: Basic "
                    + base64.b64encode(credentials).decode("ascii")
                )
            connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
            # Do not consume bytes beyond the CONNECT response (TLS may follow).
            head = bytearray()
            while not head.endswith(b"\r\n\r\n"):
                chunk = connection.recv(1)
                if not chunk or len(head) >= 65536:
                    raise EgressError("Ungültige Egress-Antwort")
                head.extend(chunk)
            if bytes(head).split(b"\r\n", 1)[0].split()[1] != b"200":
                raise EgressError("Egress-Tunnel abgelehnt")
            return connection
        except (OSError, ValueError, IndexError, UnicodeError):
            if connection is not None:
                connection.close()
            raise EgressError("Konfigurierter Egress nicht erreichbar") from None

    def ytdlp_args(self):
        if self.mode != "privacy":
            return []
        return [
            "--downloader-args",
            "ffmpeg:-protocol_whitelist file,http,https,tcp,tls,crypto",
        ]

    def _dns_query(self, hostname, record_type):
        """DoH through the same egress; literal resolver IP avoids bootstrap DNS."""
        key = (hashlib.sha256(self.proxy.encode()).digest(), hostname, record_type)
        with _dns_lock:
            cached = _dns_cache.get(key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])
        connection = self.connect_tunnel("1.1.1.1", 443)
        try:
            # SSL over an HTTPS-proxy TLS socket requires TLS-in-TLS. urllib3's
            # transport handles both plain sockets and this verified nesting.
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            if isinstance(connection, ssl.SSLSocket):
                from urllib3.util.ssltransport import SSLTransport

                connection = SSLTransport(
                    connection, context, server_hostname="cloudflare-dns.com"
                )
            else:
                connection = context.wrap_socket(
                    connection, server_hostname="cloudflare-dns.com"
                )
            path = "/dns-query?" + urlencode({"name": hostname, "type": record_type})
            connection.sendall(
                (
                    f"GET {path} HTTP/1.1\r\nHost: cloudflare-dns.com\r\n"
                    "Accept: application/dns-json\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
            )
            response = http.client.HTTPResponse(connection)
            response.begin()
            if response.status != 200:
                raise EgressError("Egress-DNS nicht erreichbar")
            payload = json.loads(response.read(65537))
            if payload.get("Status") != 0:
                raise EgressError("Egress-DNS konnte Ziel nicht auflösen")
            answers = payload.get("Answer", [])
            addresses = [row["data"] for row in answers if row.get("type") in {1, 28}]
            ttl = (
                min([60, *(max(0, int(row.get("TTL", 0))) for row in answers)])
                if answers
                else 0
            )
            if ttl:
                with _dns_lock:
                    if len(_dns_cache) >= 512:
                        _dns_cache.clear()
                    _dns_cache[key] = (time.monotonic() + ttl, tuple(addresses))
            return addresses
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            ImportError,
            http.client.HTTPException,
        ):
            raise EgressError("Egress-DNS konnte Ziel nicht sicher auflösen") from None
        finally:
            connection.close()

    def resolve(self, hostname, port, *_args):
        if self.mode == "direct":
            return socket.getaddrinfo(hostname, port, 0, socket.SOCK_STREAM)
        try:
            addresses = [str(ipaddress.ip_address(hostname))]
        except ValueError:
            hostname = hostname.encode("idna").decode("ascii")
            addresses = self._dns_query(hostname, "A") + self._dns_query(
                hostname, "AAAA"
            )
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, port, 0, 0) if ":" in ip else (ip, port),
            )
            for ip in addresses
        ]


def get_manager():
    """Read policy on use, including secret-file rotation. Never cache secrets."""
    return EgressManager.from_environment()
