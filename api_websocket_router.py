"""Authenticated WebSocket routes and initial snapshot contract."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


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


def websocket_origin_allowed(websocket: WebSocket) -> bool:
    """Allow cookie WebSockets only from the web application's own origin."""
    origin = websocket.headers.get("origin", "")
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    forwarded = (
        websocket.headers.get("x-forwarded-proto", "")
        .split(",")[0]
        .strip()
        .casefold()
    )
    if forwarded in {"https", "wss"}:
        effective_scheme = "https"
    elif forwarded in {"http", "ws"}:
        effective_scheme = "http"
    else:
        effective_scheme = (
            "https"
            if websocket.url.scheme.casefold() in {"https", "wss"}
            else "http"
        )
    return bool(parsed.netloc) and (
        parsed.netloc.casefold() == websocket.headers.get("host", "").casefold()
        and parsed.scheme.casefold() == effective_scheme
    )


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
        await dependencies.manager.connect(
            websocket,
            initial_payload_factory=snapshot_payload if is_v1 else None,
        )
        loop = asyncio.get_running_loop()
        recheck_interval = max(0.01, float(dependencies.auth_recheck_seconds))
        next_auth_check = loop.time() + recheck_interval
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=max(0.0, next_auth_check - loop.time()),
                    )
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
            dependencies.manager.disconnect(websocket)

    return router, snapshot_payload, is_authenticated
