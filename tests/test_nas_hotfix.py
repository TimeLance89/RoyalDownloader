"""Bound resource use during stalled inference and NAS I/O; no external services."""
import asyncio
import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import anyio
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import storage_work
from application_services.series_detail_work import SeriesDetailWork
from integrations import royal_intelligence as intelligence
from storage import storage_inventory as inventory


def candidate(index=1):
    return [{"key": f"movie:{index}", "title": f"Film {index}", "kind": "movie", "rating": 8, "genres": []}]


def wait_for(predicate):
    until = time.monotonic() + 2
    while not predicate() and time.monotonic() < until:
        time.sleep(.005)
    assert predicate()


def test_inference_limit_survives_multiple_users_and_reconfiguration(monkeypatch):
    release = threading.Event()
    entered = []
    class Provider:
        def score_candidates(self, profile, candidates):
            entered.append(candidates[0]["key"])
            assert release.wait(3)
            return [{"key": candidates[0]["key"], "score": 90, "angle": "taste", "confidence": 1, "noul": .8}]
    monkeypatch.setattr(intelligence.RoyalIntelligenceService, "_provider", lambda *args: Provider())
    services = [intelligence.RoyalIntelligenceService({"enabled": True, "model": "one"}) for _ in range(2)]
    try:
        for i, service in enumerate(services):
            assert service.recommendations_now(candidate(i), {}, str(i))["refinement_status"] == "queued"
        wait_for(lambda: len(entered) == 2)
        services[0].configure({"enabled": True, "model": "two"})
        for i in range(100):
            result = services[0].recommendations_now(candidate(i + 10), {}, "other")
            assert result["source"] == "baseline" and result["refinement_status"] == "busy"
        assert len(entered) == 2
        assert len(services[0]._jobs) == 0, "rejected requests must not accumulate queued jobs"
    finally:
        release.set()
        wait_for(lambda: not any(thread.name == "royal-reflex" and thread.is_alive() for thread in threading.enumerate()))
    assert not services[0]._cache, "old configuration cannot publish a late result"
    assert services[1]._cache


def test_failed_inference_has_backoff_and_bounded_history(monkeypatch):
    calls = []
    class Provider:
        def score_candidates(self, *args):
            calls.append(True)
            raise intelligence.ReflexError("offline")
    monkeypatch.setattr(intelligence.RoyalIntelligenceService, "_provider", lambda *args: Provider())
    service = intelligence.RoyalIntelligenceService({"enabled": True})
    service.recommendations_now(candidate(), {})
    wait_for(lambda: any(status == "error" for status, _ in service._jobs.values()))
    for _ in range(20):
        assert service.recommendations_now(candidate(), {})["refinement_status"] == "error"
    assert len(calls) == 1
    now = time.monotonic()
    service._cache = OrderedDict((str(i), (now, [])) for i in range(200))
    service._jobs = OrderedDict((str(i), ("ready", now)) for i in range(300))
    service._prune(now)
    assert len(service._cache) <= intelligence.CACHE_LIMIT
    assert len(service._jobs) <= intelligence.JOB_LIMIT
    service._prune(now + intelligence.CACHE_SECONDS + 1)
    assert not service._cache and not service._jobs


def test_storage_noop_avoids_disk_write_but_changed_state_stays_durable(tmp_path, monkeypatch):
    path = tmp_path / "storage.json"
    monkeypatch.setattr(inventory, "state_path", lambda: path)
    inventory.transact(lambda document: document.update(last_scan_at=1))
    original = path.read_bytes()
    calls = []
    real_sync = inventory.os.fsync
    monkeypatch.setattr(inventory.os, "fsync", lambda fd: (calls.append(fd), real_sync(fd))[1])
    inventory.transact(lambda document: document.update(last_scan_at=1))
    assert calls == [] and path.read_bytes() == original
    inventory.transact(lambda document: document.update(last_scan_at=2))
    assert calls and json.loads(path.read_text())["last_scan_at"] == 2


@pytest.fixture
def telemetry(monkeypatch):
    pool = SeriesDetailWork(workers=1, capacity=2, retain_seconds=1, thread_name="test-storage")
    monkeypatch.setattr(storage_work, "_TELEMETRY_WORK", pool)
    monkeypatch.setattr(storage_work, "TELEMETRY_WAIT_SECONDS", .05)
    yield pool
    pool.close()


def test_mount_timeout_reuses_stalled_work_and_does_not_starve_auth(telemetry):
    release, entered = threading.Event(), threading.Event()
    calls = []
    def blocked():
        calls.append(True); entered.set()
        assert release.wait(3)
        return {"available": False}
    app = FastAPI()
    @app.get("/storage")
    async def storage():
        anyio.to_thread.current_default_thread_limiter().total_tokens = 1
        return await storage_work.read_storage_telemetry("status", blocked)
    @app.get("/auth")
    def auth():
        return {"responsive": True}
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as workers:
            pending = workers.submit(client.get, "/storage")
            assert entered.wait(1)
            assert workers.submit(client.get, "/auth").result(timeout=.5).json() == {"responsive": True}
            assert pending.result(timeout=1).status_code == 503
            for _ in range(5):
                assert client.get("/storage").json()["detail"]["code"] == "storage_timeout"
            assert len(calls) == 1, "HTTP timeout cannot free admission for a replacement disk probe"
    finally:
        release.set()


def test_telemetry_coalesces_copies_and_invalidates_after_mutation(telemetry):
    calls = []
    def read():
        calls.append(True)
        return {"roots": [{"available": False}]}
    async def scenario():
        results = await asyncio.gather(*(storage_work.read_storage_telemetry("status", read) for _ in range(20)))
        assert len(calls) == 1
        results[0]["roots"][0]["available"] = True
        assert not results[1]["roots"][0]["available"]
        storage_work.invalidate_storage_telemetry()
        await storage_work.read_storage_telemetry("status", read)
        assert len(calls) == 2
    asyncio.run(scenario())
