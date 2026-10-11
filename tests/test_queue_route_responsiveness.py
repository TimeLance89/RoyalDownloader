"""A large queue snapshot must not block unrelated event-loop requests."""
import asyncio
import threading

import pytest
import server  # noqa: F401
from api import api_queue_router
from api.api_system_router import legacy_health


@pytest.mark.parametrize('route,builder,key', [
    ('api_queue_get', 'build_queue_payload', 'queue'),
    ('api_queue_jobs', 'queue_jobs_payload', None),
    ('api_queue_history', 'queue_history_payload', None),
])
def test_slow_queue_snapshot_does_not_stall_health(monkeypatch, route, builder, key):
    entered, release = threading.Event(), threading.Event()
    snapshot = {'count': 5000, 'fixture': True}

    def blocked_snapshot():
        entered.set()
        if not release.wait(1):
            raise AssertionError('queue serialization blocked the event loop')
        return snapshot

    monkeypatch.setattr(api_queue_router, builder, blocked_snapshot)

    async def scenario():
        task = asyncio.create_task(getattr(api_queue_router, route)())
        try:
            assert await asyncio.to_thread(entered.wait, 0.5)
            health = await asyncio.wait_for(legacy_health(), timeout=0.1)
            assert health == {'status': 'ok'}
        finally:
            release.set()
        return await task

    result = asyncio.run(scenario())
    assert result == ({key: snapshot} if key else snapshot)
