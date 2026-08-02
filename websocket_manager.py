"""Bounded, non-blocking WebSocket event delivery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class _WSClient:
    def __init__(self, websocket: WebSocket, queue_size: int):
        self.websocket = websocket
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self.sender_task: asyncio.Task | None = None
        self.close_task: asyncio.Task | None = None
        self.closing = False


class WSManager:
    """Serialize delivery through one bounded queue per WebSocket client."""

    def __init__(self, queue_size: int = 128):
        self.clients: dict[WebSocket, _WSClient] = {}
        self.queue_size = max(1, int(queue_size))

    async def connect(
        self,
        ws: WebSocket,
        initial_payload: dict | None = None,
        initial_payload_factory: Callable[[], dict] | None = None,
    ):
        await ws.accept()
        client = _WSClient(ws, self.queue_size)
        # There is deliberately no await between accept and registration. An
        # event announced by a worker therefore follows the initial snapshot.
        if initial_payload_factory is not None:
            initial_payload = initial_payload_factory()
        if initial_payload is not None:
            client.queue.put_nowait(initial_payload)
        self.clients[ws] = client
        client.sender_task = asyncio.create_task(self._sender(client))

    def disconnect(self, ws: WebSocket):
        client = self.clients.pop(ws, None)
        if client is None:
            return
        client.closing = True
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        for task in (client.sender_task, client.close_task):
            if task is not None and task is not current and not task.done():
                task.cancel()

    async def _sender(self, client: _WSClient):
        try:
            while True:
                payload = await client.queue.get()
                await client.websocket.send_json(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport failures end the client
            logger.debug("WebSocket sender stopped: %s", exc)
        finally:
            self.disconnect(client.websocket)

    async def _close_slow_client(self, client: _WSClient):
        try:
            await client.websocket.close(
                code=1013,
                reason="Live-Updates konnten nicht schnell genug zugestellt werden.",
            )
        except Exception as exc:  # noqa: BLE001 - socket may already be closed
            logger.debug("Slow WebSocket client close failed: %s", exc)
        finally:
            self.disconnect(client.websocket)

    def publish(self, data: dict):
        """Publish on the main loop without blocking producer threads."""
        for client in list(self.clients.values()):
            if client.closing:
                continue
            try:
                client.queue.put_nowait(data)
            except asyncio.QueueFull:
                # Structural events must not be dropped silently. Disconnect a
                # slow client so reconnect supplies a complete new snapshot.
                client.closing = True
                client.close_task = asyncio.create_task(
                    self._close_slow_client(client),
                )

    async def send_all(self, data: dict):
        """Compatibility wrapper for existing callers and tests."""
        self.publish(data)
        await asyncio.sleep(0)
