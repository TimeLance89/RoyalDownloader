"""Slow durable stores must not stop HTTP health or WebSocket progress."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import server  # noqa: F401 - initialize the application service seams

from api import api_library_router as library
from api.api_saved_media_router import create_saved_media_router
from api.api_system_router import legacy_health
from api.api_websocket_router import WebSocketDependencies, create_websocket_router
from core.websocket_manager import WSManager
from api.api_auth_router import create_auth_router
import core.auth as appauth


def blocked_reader():
    entered, release = threading.Event(), threading.Event()

    def read(*_args, **_kwargs):
        entered.set()
        if not release.wait(3):
            raise AssertionError("reader was not released while health remained responsive")
        return {"id": "fixture", "enabled": True}

    return read, entered, release


def health_during_request(app, path, entered, release):
    app.add_api_route("/health", legacy_health)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(client.get, path)
        try:
            assert entered.wait(1)
            health = workers.submit(client.get, "/health").result(timeout=0.75)
            assert health.json() == {"status": "ok"}
            assert not pending.done()
        finally:
            release.set()
        assert pending.result(timeout=2).status_code == 200


@pytest.mark.parametrize("route,builder", [
    ("api_watchlist_get", "watchlist_payload"),
    ("api_movie_subscriptions_get", "movie_subscriptions_payload"),
])
def test_library_snapshots_do_not_stop_health(monkeypatch, route, builder):
    read, entered, release = blocked_reader()
    monkeypatch.setattr(library, builder, read)
    monkeypatch.setattr(library, "hydrate_watchlist_artwork", lambda: None)
    monkeypatch.setattr(library, "broadcast", lambda *_: None)
    # Only the HTTP reader may trip the gate; the unrelated hydration thread
    # must not make this test pass before the HTTP handler actually runs.
    monkeypatch.setattr(library, "threading", SimpleNamespace(
        Thread=lambda **_kwargs: SimpleNamespace(start=lambda: None),
    ))
    app = FastAPI()
    app.add_api_route("/probe", getattr(library, route))
    health_during_request(app, "/probe", entered, release)


def test_profile_session_read_does_not_stop_health():
    read, entered, release = blocked_reader()
    app = FastAPI()
    app.include_router(create_auth_router(SimpleNamespace(
        appauth=appauth, current_user=read,
        user_store=lambda: SimpleNamespace(public=lambda value: value),
    )))
    health_during_request(app, "/api/me", entered, release)


def test_saved_media_owner_read_does_not_stop_health():
    read, entered, release = blocked_reader()
    app = FastAPI()
    app.include_router(create_saved_media_router(
        SimpleNamespace(items=lambda *_: []), read,
        SimpleNamespace(status=lambda *_: {"state": "unlinked", "ready": []}),
    ))
    health_during_request(app, "/api/me/saved-media", entered, release)


@pytest.mark.parametrize("block_on", [1, 2])
def test_websocket_handshake_and_revalidation_do_not_stop_health(block_on, monkeypatch):
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "testserver")
    read, entered, release = blocked_reader()
    calls = []

    def validate(*_args, **_kwargs):
        calls.append(1)
        if len(calls) >= block_on:
            read()
        return "fixture"

    app = FastAPI()
    dependencies = WebSocketDependencies(
        api_version=1, event_schema_version=1, auth_recheck_seconds=0.01,
        state=None, manager=WSManager(), build_queue_payload=lambda: {},
        watchlist_payload=lambda: {}, auth_required=lambda: True,
        authenticated_mobile_token=lambda *_args, **_kwargs: "",
        authenticated_web_token=validate,
    )
    router, _, _ = create_websocket_router(dependencies)
    app.include_router(router)
    app.add_api_route("/health", legacy_health)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as workers:
        def connect():
            with client.websocket_connect("/ws", headers={"origin": "http://testserver"}):
                assert release.wait(3)

        pending = workers.submit(connect)
        try:
            assert entered.wait(1)
            assert workers.submit(client.get, "/health").result(timeout=0.75).json() == {"status": "ok"}
        finally:
            release.set()
        pending.result(timeout=2)


def test_initial_snapshot_buffers_live_events_without_stopping_health():
    read, entered, release = blocked_reader()

    class Socket:
        def __init__(self):
            self.sent = []
        async def accept(self):
            pass
        async def send_json(self, payload):
            self.sent.append(payload)

    async def scenario():
        manager, socket = WSManager(), Socket()
        task = asyncio.create_task(manager.connect(socket, initial_payload_factory=read))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            manager.publish({"type": "live"})
            assert await asyncio.wait_for(legacy_health(), 0.1) == {"status": "ok"}
        finally:
            release.set()
        await task
        for _ in range(4):
            await asyncio.sleep(0)
        manager.disconnect(socket)
        assert socket.sent == [{"id": "fixture", "enabled": True}, {"type": "live"}]

    asyncio.run(scenario())
