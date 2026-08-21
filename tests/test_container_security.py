from pathlib import Path
import os
import socket
import socketserver
import threading

import pytest

import container_entrypoint
from browser_cdp_proxy import create_proxy_server


ROOT = Path(__file__).resolve().parents[1]
requires_posix = pytest.mark.skipif(os.name != "posix", reason="requires POSIX user IDs")


def test_image_and_compose_run_unprivileged_with_reduced_privileges():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "USER royal" in dockerfile
    assert "--no-sandbox" not in dockerfile
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "APP_UID: ${PUID:-1000}" in compose
    assert "APP_GID: ${PGID:-1000}" in compose


def test_private_tmpfs_mounts_belong_to_the_unprivileged_runtime_user():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    for mount in (
        "/home/royal:rw,nosuid,nodev,size=256m,mode=0700",
        "/home/royal:rw,nosuid,nodev,size=128m,mode=0700",
        "/browser-profile:rw,nosuid,nodev,size=512m,mode=0700",
    ):
        assert f"{mount},uid=${{PUID:-1000}},gid=${{PGID:-1000}}" in compose
        assert f"{mount},uid=1000,gid=1000" in workflow


def test_browser_cdp_proxy_preserves_bidirectional_tcp():
    class EchoHandler(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(4096):
                self.request.sendall(data)

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), EchoHandler) as upstream:
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        with create_proxy_server(
            "127.0.0.1",
            0,
            "127.0.0.1",
            upstream.server_address[1],
        ) as proxy:
            proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
            proxy_thread.start()
            with socket.create_connection(proxy.server_address, timeout=2) as client:
                client.sendall(b"royal-cdp")
                assert client.recv(4096) == b"royal-cdp"
            proxy.shutdown()
        upstream.shutdown()


def test_browser_runtime_routes_loopback_cdp_through_isolated_proxy():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    for content in (compose, workflow):
        assert "python browser_cdp_proxy.py --listen-host 0.0.0.0 &" in content
        assert "--remote-debugging-port=9223" in content
        assert "--remote-debugging-address=0.0.0.0" not in content


@requires_posix
def test_smoke_check_writes_only_required_mounts(monkeypatch, tmp_path):
    for name in ("runtime", "data", "movies", "series"):
        monkeypatch.setenv(
            {
                "runtime": "APP_RUNTIME_DIR",
                "data": "SERIENDL_DATA_DIR",
                "movies": "DOWNLOAD_DIR",
                "series": "SERIES_DIR",
            }[name],
            str(tmp_path / name),
        )
    monkeypatch.setattr(container_entrypoint.os, "getuid", lambda: 1000)
    container_entrypoint.smoke_check()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data", "movies", "runtime", "series"]


@requires_posix
def test_smoke_check_rejects_root(monkeypatch):
    monkeypatch.setattr(container_entrypoint.os, "getuid", lambda: 0)
    try:
        container_entrypoint.smoke_check()
    except RuntimeError as exc:
        assert "nicht als root" in str(exc)
    else:
        raise AssertionError("root runtime was accepted")
