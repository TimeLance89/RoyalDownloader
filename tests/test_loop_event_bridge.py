import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from core.loop_event_bridge import LoopEventBridge
from core.websocket_manager import WSManager


class QueuedLoop:
    def __init__(self):
        self.callbacks = deque()
        self.closed = False
        self.scheduled = 0

    def is_closed(self):
        return self.closed

    def call_soon_threadsafe(self, callback, *args):
        self.scheduled += 1
        self.callbacks.append((callback, args))

    def call_soon(self, callback, *args):
        self.callbacks.append((callback, args))

    def step(self):
        callback, args = self.callbacks.popleft()
        callback(*args)

    def drain(self):
        while self.callbacks:
            self.step()


def test_blocked_loop_retains_bounded_events_and_one_callback():
    loop, received, resyncs = QueuedLoop(), [], []
    bridge = LoopEventBridge(received.append, lambda: resyncs.append(True), capacity=8)
    for sequence in range(10_000):
        bridge.submit(loop, {"sequence": sequence})
    assert len(bridge.pending) <= 8
    assert len(loop.callbacks) == loop.scheduled == 1
    loop.drain()
    assert received == []
    assert resyncs == [True]
    bridge.submit(loop, {"sequence": "fresh"})
    loop.drain()
    assert received == [{"sequence": "fresh"}]


def test_concurrent_producers_keep_order_per_producer_and_yield_between_batches():
    loop, received = QueuedLoop(), []
    bridge = LoopEventBridge(received.append, lambda: None, capacity=512, batch_size=16)

    def produce(producer):
        for sequence in range(100):
            bridge.submit(loop, (producer, sequence))

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(produce, range(4)))
    assert loop.scheduled == len(loop.callbacks) == 1
    loop.step()
    assert len(received) == 16
    assert len(loop.callbacks) == 1
    loop.drain()
    assert len(received) == 400
    for producer in range(4):
        assert [sequence for owner, sequence in received if owner == producer] == list(range(100))


def test_callbacks_from_a_closed_lifespan_cannot_drain_the_next_loop():
    old, new, received = QueuedLoop(), QueuedLoop(), []
    bridge = LoopEventBridge(received.append, lambda: None)
    bridge.submit(old, "old")
    old.closed = True
    bridge.submit(new, "new")
    old.drain()
    assert received == []
    new.drain()
    assert received == ["new"]


def test_scheduling_failure_releases_stale_pending_data():
    class ClosingLoop(QueuedLoop):
        def call_soon_threadsafe(self, *_args):
            raise RuntimeError("loop closed while scheduling")

    received = []
    bridge = LoopEventBridge(received.append, lambda: None)
    bridge.submit(ClosingLoop(), "stale")
    assert not bridge.pending
    assert not bridge.scheduled
    new = QueuedLoop()
    bridge.submit(new, "new")
    new.drain()
    assert received == ["new"]


def test_worker_ingress_overflow_closes_clients_for_snapshot_resync():
    class Socket:
        closed = None

        async def accept(self):
            pass

        async def send_json(self, _payload):
            pass

        async def close(self, *, code, reason):
            self.closed = code

    async def scenario():
        manager, socket = WSManager(), Socket()
        manager._ingress = LoopEventBridge(manager.publish, manager._resync_clients, capacity=2)
        await manager.connect(socket)
        loop = asyncio.get_running_loop()
        for sequence in range(10):
            manager.publish_threadsafe(loop, {"sequence": sequence})
        for _ in range(8):
            await asyncio.sleep(0)
        assert socket.closed == 1013
        assert socket not in manager.clients

    asyncio.run(scenario())


def test_unresponsive_socket_close_cannot_retain_client_forever(monkeypatch):
    from core import websocket_manager

    monkeypatch.setattr(websocket_manager, "CLOSE_TIMEOUT_SECONDS", 0.01)

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, _payload):
            await asyncio.Event().wait()

        async def close(self, **_kwargs):
            await asyncio.Event().wait()

    async def scenario():
        manager, socket = WSManager(queue_size=1), Socket()
        await manager.connect(socket)
        manager.publish({"sequence": 1})
        manager.publish({"sequence": 2})
        client = manager.clients[socket]
        await asyncio.wait_for(client.close_task, timeout=0.5)
        assert socket not in manager.clients
        await asyncio.sleep(0)
        assert client.sender_task.done()

    asyncio.run(scenario())


def test_send_failure_closes_socket_instead_of_leaving_stale_connected_ui():
    class Socket:
        closed = None

        async def accept(self):
            pass

        async def send_json(self, _payload):
            raise ValueError("fixture encoding failure")

        async def close(self, *, code, reason):
            self.closed = code

    async def scenario():
        manager, socket = WSManager(), Socket()
        await manager.connect(socket, initial_payload={"type": "snapshot"})
        sender = manager.clients[socket].sender_task
        await asyncio.wait_for(sender, 0.5)
        assert socket.closed == 1013
        assert socket not in manager.clients

    asyncio.run(scenario())
