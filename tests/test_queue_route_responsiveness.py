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


def test_concurrent_queue_readers_share_one_cpu_slot_and_preserve_results(monkeypatch):
    import time
    lock = threading.Lock()
    active = peak = 0
    def snapshot():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(.02)
            return {'count': 5000, 'fixture': True}
        finally:
            with lock:
                active -= 1
    for name in ('build_queue_payload', 'queue_jobs_payload', 'queue_history_payload'):
        monkeypatch.setattr(api_queue_router, name, snapshot)
    async def scenario():
        routes = [api_queue_router.api_queue_get, api_queue_router.api_queue_jobs,
                  api_queue_router.api_queue_history, api_queue_router.api_queue_get]
        tasks = [asyncio.create_task(route()) for route in routes]
        assert await asyncio.wait_for(legacy_health(), .1) == {'status': 'ok'}
        return await asyncio.gather(*tasks)
    result = asyncio.run(scenario())
    assert peak == 1 and active == 0
    assert result == [{'queue': {'count': 5000, 'fixture': True}},
                      {'count': 5000, 'fixture': True}, {'count': 5000, 'fixture': True},
                      {'queue': {'count': 5000, 'fixture': True}}]


def test_cancelled_waiter_does_not_block_later_queue_readers(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = 0
    def snapshot():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(1)
        return {'count': calls}
    monkeypatch.setattr(api_queue_router, 'build_queue_payload', snapshot)
    async def scenario():
        first = asyncio.create_task(api_queue_router.api_queue_get())
        try:
            assert await asyncio.to_thread(entered.wait, .5)
            waiting = asyncio.create_task(api_queue_router.api_queue_get())
            await asyncio.sleep(.01)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        finally:
            release.set()
        await first
        return await asyncio.wait_for(api_queue_router.api_queue_get(), .5)
    assert asyncio.run(scenario()) == {'queue': {'count': 2}}


def test_failed_snapshot_releases_cpu_slot(monkeypatch):
    calls = 0
    def snapshot():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError('controlled snapshot failure')
        return {'count': 5000}
    monkeypatch.setattr(api_queue_router, 'build_queue_payload', snapshot)
    async def scenario():
        with pytest.raises(ValueError, match='controlled snapshot failure'):
            await api_queue_router.api_queue_get()
        return await asyncio.wait_for(api_queue_router.api_queue_get(), .5)
    assert asyncio.run(scenario()) == {'queue': {'count': 5000}}
