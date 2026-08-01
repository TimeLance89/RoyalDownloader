import socket

import pytest

import network_guard


def _resolver(*addresses):
    def resolve(_host, port, *_args):
        rows = []
        for value in addresses:
            family = socket.AF_INET6 if ":" in value else socket.AF_INET
            sockaddr = (value, port, 0, 0) if family == socket.AF_INET6 else (value, port)
            rows.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
        return rows
    return resolve


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "10.0.0.1", "172.16.1.1", "192.168.1.1",
        "169.254.1.1", "0.0.0.0", "192.0.2.1", "224.0.0.1",
        "::1", "fc00::1", "fe80::1", "2001:db8::1",
    ],
)
def test_rejects_non_public_ipv4_and_ipv6(address):
    with pytest.raises(network_guard.UnsafeNetworkTarget):
        network_guard.ensure_public_http_url(
            "https://provider.example/video", resolver=_resolver(address)
        )


def test_accepts_only_public_http_ports_without_credentials():
    resolver = _resolver("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")
    assert network_guard.ensure_public_http_url(
        "https://provider.example/video", resolver=resolver
    ).hostname == "provider.example"
    for url in (
        "ftp://provider.example/video",
        "https://user:secret@provider.example/video",
        "https://provider.example:8443/video",
        "http:///relative",
    ):
        with pytest.raises(network_guard.UnsafeNetworkTarget):
            network_guard.ensure_public_http_url(url, resolver=resolver)


def test_mixed_dns_answer_is_rejected_to_prevent_rebinding():
    with pytest.raises(network_guard.UnsafeNetworkTarget):
        network_guard.ensure_public_http_url(
            "https://provider.example/video",
            resolver=_resolver("93.184.216.34", "127.0.0.1"),
        )


def test_peer_must_still_match_resolved_public_address():
    with pytest.raises(network_guard.UnsafeNetworkTarget):
        network_guard.validate_peer_ip("127.0.0.1", "93.184.216.34")
    with pytest.raises(network_guard.UnsafeNetworkTarget):
        network_guard.validate_peer_ip("93.184.216.35", "93.184.216.34")
    network_guard.validate_peer_ip("93.184.216.34", "93.184.216.34")


def test_proxy_blocks_private_connect_and_http_redirect_targets():
    server = network_guard._GuardProxyServer(("127.0.0.1", 0), network_guard._GuardProxyHandler)
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for request in (
            b"CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
            b"GET http://169.254.169.254/latest/meta-data HTTP/1.1\r\nHost: 169.254.169.254\r\n\r\n",
        ):
            client = socket.create_connection(server.server_address, timeout=2)
            with client:
                client.sendall(request)
                assert b" 403 " in client.recv(256)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
