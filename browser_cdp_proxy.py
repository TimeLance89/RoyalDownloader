"""Expose Chrome's loopback-only DevTools endpoint to its isolated network."""

from __future__ import annotations

import argparse
from contextlib import suppress
import socket
import socketserver
import threading


class _CDPProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, listen_address, upstream_address):
        self.upstream_address = upstream_address
        super().__init__(listen_address, _CDPProxyHandler)


class _CDPProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            upstream = socket.create_connection(self.server.upstream_address, timeout=5)
        except OSError:
            return
        upstream.settimeout(None)
        client = self.request
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
