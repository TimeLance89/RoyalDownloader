"""Authenticated WebSocket routes and initial snapshot contract."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from proxy_security import client_ip, host_allowed, origin_matches


DEFAULT_WS_MAX_CONNECTIONS_PER_CLIENT = 4
DEFAULT_WS_MAX_MESSAGE_BYTES = 4096
DEFAULT_WS_MESSAGES_PER_MINUTE = 30
_connection_lock = threading.Lock()
_connections_by_client: dict[str, int] = {}


@dataclass(frozen=True)
class WebSocketDependencies:
    api_version: int
    event_schema_version: int
    auth_recheck_seconds: float
    state: Any
    manager: Any
    build_queue_payload: Callable[[], dict]
    watchlist_payload: Callable[[], dict]
    auth_required: Callable[[], bool]
    authenticated_mobile_token: Callable[..., str]
    authenticated_web_token: Callable[..., str]


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def websocket_origin_allowed(websocket: WebSocket) -> bool:
    """Cookie WebSockets require Royal's exact effective browser origin."""
    if not host_allowed(websocket):
        return False
    origin = str(websocket.headers.get("origin", "") or "").strip()
    if not origin:
        return False
    return origin_matches(websocket, origin)


def _acquire_client_slot(key: str) -> bool:
    maximum = _bounded_env_int(
        "ROYAL_WS_MAX_CONNECTIONS_PER_CLIENT",
        DEFAULT_WS_MAX_CONNECTIONS_PER_CLIENT,
        1,
        32,
    )
    with _connection_lock:
        current = int(_connections_by_client.get(key, 0))
        if current >= maximum:
            return False
        _connections_by_client[key] = current + 1
        return True


def _release_client_slot(key: str) -> None:
    with _connection_lock:
        current = int(_connections_by_client.get(key, 0))
        if current <= 1:
            _connections_by_client.pop(key, None)
        else:
            _connections_by_client[key] = current - 1


def create_websocket_router(
    dependencies: WebSocketDependencies,
) -> tuple[APIRouter, Callable[[], dict], Callable[..., bool]]:
    router = APIRouter(tags=["live-updates"])

    def snapshot_payload() -> dict:
        state = dependencies.state
        with state.download_state_lock:
            download = {
                "done_jobs": state.done_jobs,
                "total_jobs": state.total_jobs,
                "successful_jobs": len(state.done_slugs),
                "failed_jobs": max(0, state.done_jobs - len(state.done_slugs)),
                "active": state.dl_queue.active_count(),
                "pending": state.dl_queue.pending_count(),
            }
        return {
            "type": "snapshot",
            "api_version": dependencies.api_version,
            "event_schema_version": dependencies.event_schema_version,
            "timestamp": time.time(),
            "queue": dependencies.build_queue_payload(),
            "watchlist": dependencies.watchlist_payload()["watchlist"],
            "download": download,
        }

    def is_authenticated(
        websocket: WebSocket,
        *,
        versioned: bool,
        touch: bool,
    ) -> bool:
        if not host_allowed(websocket):
            return False
        if not dependencies.auth_required():
            return True
        if dependencies.authenticated_mobile_token(
            websocket.headers,
            touch=touch,
        ):
            return True
        if versioned:
            return False
        return bool(
            websocket_origin_allowed(websocket)
            and dependencies.authenticated_web_token(
                websocket.cookies,
                touch=touch,
            )
        )

    @router.websocket("/api/v1/ws")
    @router.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        is_v1 = websocket.scope.get("path") == "/api/v1/ws"
        if not is_authenticated(websocket, versioned=is_v1, touch=True):
            await websocket.close(code=1008, reason="Anmeldung erforderlich")
            return

        connection_key = client_ip(websocket)
        if not _acquire_client_slot(connection_key):
            await websocket.close(
                code=1013,
                reason="Zu viele gleichzeitige Live-Verbindungen",
            )
            return

        max_message_bytes = _bounded_env_int(
            "ROYAL_WS_MAX_MESSAGE_BYTES",
            DEFAULT_WS_MAX_MESSAGE_BYTES,
            256,
            64 * 1024,
        )
        messages_per_minute = _bounded_env_int(
            "ROYAL_WS_MESSAGES_PER_MINUTE",
            DEFAULT_WS_MESSAGES_PER_MINUTE,
            1,
            600,
        )
        message_times: deque[float] = deque()
        connected = False
        try:
            await dependencies.manager.connect(
                websocket,
                initial_payload_factory=snapshot_payload if is_v1 else None,
            )
            connected = True
            loop = asyncio.get_running_loop()
            recheck_interval = max(0.01, float(dependencies.auth_recheck_seconds))
            next_auth_check = loop.time() + recheck_interval
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=max(0.0, next_auth_check - loop.time()),
                    )
                    if len(message.encode("utf-8")) > max_message_bytes:
                        await websocket.close(code=1009, reason="WebSocket-Nachricht zu groß")
                        break
                    now = loop.time()
                    cutoff = now - 60.0
                    while message_times and message_times[0] < cutoff:
                        message_times.popleft()
                    message_times.append(now)
                    if len(message_times) > messages_per_minute:
                        await websocket.close(code=1008, reason="Zu viele WebSocket-Nachrichten")
                        break
                except asyncio.TimeoutError:
                    pass
                now = loop.time()
                if now >= next_auth_check:
                    if not is_authenticated(
                        websocket,
                        versioned=is_v1,
                        touch=False,
                    ):
                        await websocket.close(
                            code=1008,
                            reason="Sitzung abgelaufen",
                        )
                        break
                    next_auth_check = now + recheck_interval
        except WebSocketDisconnect:
            pass
        finally:
            if connected:
                dependencies.manager.disconnect(websocket)
            _release_client_slot(connection_key)

    return router, snapshot_payload, is_authenticated
