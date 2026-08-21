"""Trusted-proxy, request-origin, and host validation helpers.

Security-sensitive forwarding headers are ignored unless the direct peer belongs
to an explicitly trusted proxy network.  Local loopback proxies are trusted by
default; every other proxy must be listed in ``ROYAL_TRUSTED_PROXIES``.
"""

from __future__ import annotations

import ipaddress
import os
import re
from functools import lru_cache
from urllib.parse import urlparse


_LOCAL_PROXY_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)
_LOCAL_HOST_SUFFIXES = (
    ".local",
    ".lan",
    ".home",
    ".internal",
    ".home.arpa",
    ".fritz.box",
)
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def _header(connection, name: str) -> str:
    headers = getattr(connection, "headers", {})
    return str(headers.get(name, "") or "").strip()


def _peer_ip(connection) -> ipaddress._BaseAddress | None:
    client = getattr(connection, "client", None)
    raw = str(getattr(client, "host", "") or "").strip()
    if not raw:
        return None
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


@lru_cache(maxsize=32)
def _parse_networks(raw: str) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = list(_LOCAL_PROXY_NETWORKS)
    for value in str(raw or "").replace(";", ",").split(","):
        value = value.strip()
        if not value:
            continue
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            continue
        if network not in networks:
            networks.append(network)
    return tuple(networks)


def trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    return _parse_networks(
        os.environ.get("ROYAL_TRUSTED_PROXIES", "")
        or os.environ.get("TRUSTED_PROXY_CIDRS", "")
    )


def is_trusted_proxy_peer(connection) -> bool:
    peer = _peer_ip(connection)
    return bool(
        peer is not None
        and any(peer.version == network.version and peer in network for network in trusted_proxy_networks())
    )


def _normalized_ip(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 64:
        return ""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def client_ip(connection) -> str:
    """Return a spoof-resistant client IP used for lockouts and budgets."""
    peer = _peer_ip(connection)
    peer_text = str(peer) if peer is not None else "unbekannt"
    if peer is None or not is_trusted_proxy_peer(connection):
        return peer_text

    if _truthy("TRUST_CLOUDFLARE_HEADERS"):
        raw_cf = _header(connection, "cf-connecting-ip")
        if "," not in raw_cf:
            normalized = _normalized_ip(raw_cf)
            if normalized:
                return normalized

    if not _truthy("TRUST_X_FORWARDED_FOR"):
        return peer_text

    raw_xff = _header(connection, "x-forwarded-for")
    if not raw_xff or len(raw_xff) > 2048:
        return peer_text
    chain: list[ipaddress._BaseAddress] = []
    for part in raw_xff.split(","):
        try:
            chain.append(ipaddress.ip_address(part.strip()))
        except ValueError:
            return peer_text
    chain.append(peer)
    networks = trusted_proxy_networks()
    for address in reversed(chain):
        if any(address.version == network.version and address in network for network in networks):
            continue
        return str(address)
    return str(chain[0]) if chain else peer_text


def effective_scheme(connection) -> str:
    """Return ``http`` or ``https`` while trusting forwarding only from proxies."""
    direct = str(getattr(getattr(connection, "url", None), "scheme", "") or "").casefold()
    if direct in {"https", "wss"}:
        direct = "https"
    else:
        direct = "http"
    if not is_trusted_proxy_peer(connection):
        return direct
    forwarded = _header(connection, "x-forwarded-proto").split(",", 1)[0].strip().casefold()
    if forwarded in {"https", "wss"}:
        return "https"
    if forwarded in {"http", "ws"}:
        return "http"
    return direct


def request_is_secure(connection) -> bool:
    return effective_scheme(connection) == "https"


def _split_host_header(value: str) -> tuple[str, int | None] | None:
    value = str(value or "").strip()
    if (
        not value
        or len(value) > 255
        or any(ord(char) < 33 for char in value)
        or any(char in value for char in "/\\@?#")
    ):
        return None
    try:
        parsed = urlparse("//" + value)
        host = str(parsed.hostname or "").strip().casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if not host or parsed.username is not None or parsed.password is not None:
        return None
    return host, port


def _explicit_host_allowed(host: str) -> bool | None:
    raw = str(os.environ.get("ROYAL_ALLOWED_HOSTS", "") or "").strip()
    if not raw:
        return None
    for pattern in raw.replace(";", ",").split(","):
        pattern = pattern.strip().casefold().rstrip(".")
        if not pattern:
            continue
        if pattern == "*":
            return True
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if host.endswith(suffix) and host != suffix[1:]:
                return True
        elif host == pattern:
            return True
    return False


def host_allowed(connection) -> bool:
    """Deny public-looking Host headers unless explicitly allowed.

    Private IP literals, localhost, single-label NAS names and common local DNS
    suffixes work without configuration.  Public reverse-proxy hostnames must be
    listed in ``ROYAL_ALLOWED_HOSTS``.
    """
    parsed = _split_host_header(_header(connection, "host"))
    if parsed is None:
        return False
    host, _port = parsed
    explicit = _explicit_host_allowed(host)
    if explicit is not None:
        return explicit
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return bool(address.is_private or address.is_loopback or address.is_link_local)
    if "." not in host:
        return bool(_HOSTNAME_RE.fullmatch(host))
    return any(host.endswith(suffix) for suffix in _LOCAL_HOST_SUFFIXES)


def origin_matches(connection, origin: str) -> bool:
    """Validate a browser Origin against the effective Royal origin."""
    parsed_host = _split_host_header(_header(connection, "host"))
    if parsed_host is None:
        return False
    try:
        parsed = urlparse(str(origin or "").strip())
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None or not parsed.hostname:
        return False
    origin_host = str(parsed.hostname).casefold().rstrip(".")
    origin_port = parsed.port
    request_host, request_port = parsed_host
    scheme = effective_scheme(connection)
    default_port = 443 if scheme == "https" else 80
    effective_request_port = request_port or default_port
    effective_origin_port = origin_port or (443 if parsed.scheme.casefold() == "https" else 80)
    return bool(
        parsed.scheme.casefold() == scheme
        and origin_host == request_host
        and effective_origin_port == effective_request_port
    )
