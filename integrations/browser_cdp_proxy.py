"""Expose Chrome's loopback-only DevTools endpoint to its isolated network."""

from __future__ import annotations

import argparse
from contextlib import suppress
import socket
import socketserver
import threading

_MAX_REQUEST_HEAD_BYTES = 64 * 1024


def _read_request_head(connection: socket.socket) -> tuple[bytes, bytes]:
    received = bytearray()
    while b"\r\n\r\n" not in received:
        chunk = connection.recv(4096)
        if not chunk:
            raise ConnectionError("CDP client closed before sending an HTTP header")
        received.extend(chunk)
        if len(received) > _MAX_REQUEST_HEAD_BYTES:
            raise ValueError("CDP request header exceeds the configured limit")
    head, remainder = bytes(received).split(b"\r\n\r\n", 1)
    return head + b"\r\n\r\n", remainder


def _normalize_host_header(head: bytes, upstream_host: str, upstream_port: int) -> bytes:
    lines = head.removesuffix(b"\r\n\r\n").split(b"\r\n")
    if not lines or not lines[0].startswith((b"GET ", b"PUT ")):
        raise ValueError("Only CDP GET and PUT requests are allowed")
    normalized_host = f"Host: {upstream_host}:{upstream_port}".encode("ascii")
    host_found = False
    for index in range(1, len(lines)):
        if lines[index].lower().startswith(b"host:"):
            lines[index] = normalized_host
            host_found = True
    if not host_found:
        lines.append(normalized_host)
    return b"\r\n".join(lines) + b"\r\n\r\n"


class _CDPProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, listen_address, upstream_address):
        self.upstream_address = upstream_address
        super().__init__(listen_address, _CDPProxyHandler)


class _CDPProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            self.request.settimeout(5)
            request_head, remainder = _read_request_head(self.request)
            upstream = socket.create_connection(self.server.upstream_address, timeout=5)
            upstream.sendall(_normalize_host_header(
                request_head,
                self.server.upstream_address[0],
                self.server.upstream_address[1],
            ))
            if remainder:
                upstream.sendall(remainder)
        except (ConnectionError, OSError, ValueError):
            return
        upstream.settimeout(None)
        client = self.request
        client.settimeout(None)
        close_lock = threading.Lock()
        closed = False

        def close_connection() -> None:
            nonlocal closed
            with close_lock:
                if closed:
                    return
                closed = True
                for connection in (client, upstream):
                    with suppress(OSError):
                        connection.shutdown(socket.SHUT_RDWR)

        def relay(source: socket.socket, destination: socket.socket) -> None:
            try:
                while data := source.recv(64 * 1024):
                    destination.sendall(data)
            except OSError:
                pass
            finally:
                close_connection()

        response_thread = threading.Thread(
            target=relay,
            args=(upstream, client),
            name="royal-cdp-proxy-response",
            daemon=True,
        )
        response_thread.start()
        relay(client, upstream)
        response_thread.join(timeout=1)
        upstream.close()


def create_proxy_server(
    listen_host: str,
    listen_port: int,
    upstream_host: str,
    upstream_port: int,
) -> socketserver.ThreadingTCPServer:
    return _CDPProxyServer(
        (listen_host, listen_port),
        (upstream_host, upstream_port),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=9222)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=9223)
    args = parser.parse_args()
    with create_proxy_server(
        args.listen_host,
        args.listen_port,
        args.upstream_host,
        args.upstream_port,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
