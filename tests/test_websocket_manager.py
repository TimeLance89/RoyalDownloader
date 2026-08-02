import asyncio

from websocket_manager import WSManager


class FakeWebSocket:
    def __init__(self, *, block_sends=False):
        self.accepted = False
        self.sent = []
        self.closed = None
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()
        if not block_sends:
            self.release_send.set()

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.send_started.set()
        await self.release_send.wait()
        self.sent.append(payload)

    async def close(self, *, code, reason):
        self.closed = (code, reason)


def test_initial_snapshot_is_delivered_before_live_events():
    async def scenario():
        manager = WSManager(queue_size=4)
        websocket = FakeWebSocket()
        await manager.connect(websocket, initial_payload={"type": "snapshot"})
        manager.publish({"type": "live"})
        for _attempt in range(4):
            await asyncio.sleep(0)
        manager.disconnect(websocket)
        return websocket

    websocket = asyncio.run(scenario())

    assert websocket.accepted is True
    assert websocket.sent == [{"type": "snapshot"}, {"type": "live"}]


def test_slow_client_is_closed_instead_of_dropping_structural_events():
    async def scenario():
        manager = WSManager(queue_size=1)
        websocket = FakeWebSocket(block_sends=True)
        await manager.connect(websocket, initial_payload={"sequence": 1})
        await websocket.send_started.wait()
        manager.publish({"sequence": 2})
        manager.publish({"sequence": 3})
        for _attempt in range(4):
            await asyncio.sleep(0)
        websocket.release_send.set()
        return websocket, manager

    websocket, manager = asyncio.run(scenario())

    assert websocket.closed is not None
    assert websocket.closed[0] == 1013
    assert websocket not in manager.clients
