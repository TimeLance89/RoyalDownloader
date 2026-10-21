"""Regressions for NAS stalls, worker exhaustion and late background work."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import threading
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
import server  # noqa: F401 - service composition

from api import api_administration_router as admin
from api import api_discovery_router as discovery
from api import api_queue_router as queue
from api import api_storage_router as storage
from api import api_library_router as library
from api import interactive_work
from api.api_system_router import legacy_health, create_system_router
from application_services.series_detail_work import SeriesDetailWork
from application_services import movie_catalog, series_catalog_cache
from application_services import runtime_maintenance
from core.runtime_diagnostics import RuntimeDiagnostics


def assert_health_during_work(handler, monkeypatch, owner, attribute, value):
    entered, release = threading.Event(), threading.Event()

    def slow(*_args, **_kwargs):
        entered.set()
        assert release.wait(3), "slow operation was not released"
        return value

    monkeypatch.setattr(owner, attribute, slow)
    app = FastAPI()
    app.add_api_route("/probe", handler)
    app.add_api_route("/health", legacy_health)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(client.get, "/probe")
        try:
            assert entered.wait(1)
            assert workers.submit(client.get, "/health").result(timeout=0.5).status_code == 200
            assert not pending.done()
        finally:
            release.set()
        assert pending.result(timeout=2).status_code == 200


@pytest.mark.parametrize("handler,owner,attribute,value", [
    (admin.api_ui_config_get, admin, "_ui_language_payload", {}),
    (admin.api_updater_config_get, admin, "_updater_config_payload", {}),
    (admin.api_seerr_config_get, admin, "_seerr_config_payload", {}),
    (admin.api_provider_priority_get, admin, "_provider_priority_payload", {}),
    (admin.api_config_get, admin.appconfig, "load_deployment_mode", "nas"),
    (discovery.api_home_layout_get, server.state.home_layout, "public_layout", {}),
])
def test_slow_configuration_reads_keep_health_responsive(monkeypatch, handler, owner, attribute, value):
    assert_health_during_work(handler, monkeypatch, owner, attribute, value)


def test_storage_prepares_arguments_outside_event_loop(monkeypatch):
    from api.storage_work import invalidate_storage_telemetry
    invalidate_storage_telemetry()  # exercise a cold mount read, not a recent snapshot
    monkeypatch.setattr(storage, "combined_storage_status", lambda *_: {})
    monkeypatch.setattr(storage, "load_storage_locations", lambda: [])
    assert_health_during_work(storage.api_storage_status, monkeypatch, storage, "_media_paths", {})


def test_queue_cancel_snapshot_keeps_health_responsive(monkeypatch):
    monkeypatch.setattr(queue, "_job_or_404", lambda *_: {"slug": "fixture"})
    monkeypatch.setattr(queue, "_request_queue_cancel", lambda *_: ({}, [], []))
    monkeypatch.setattr(queue, "broadcast", lambda *_: None)

    async def handler():
        return await queue.api_queue_job_cancel("fixture")

    assert_health_during_work(handler, monkeypatch, queue, "build_queue_payload", [])


def test_resume_persistence_keeps_health_responsive(monkeypatch):
    monkeypatch.setattr(queue, "state", SimpleNamespace(
        queue_claim_lock=threading.RLock(), provider_waiting_jobs={},
        provider_retry_wake_event=threading.Event(),
    ))
    monkeypatch.setattr(queue, "_job_or_404", lambda *_: {"slug": "fixture", "status": "waiting_provider"})
    monkeypatch.setattr(queue, "_update_queue_job", lambda *_args, **_kwargs: {})

    async def handler():
        return await queue.api_queue_job_resume("fixture")

    assert_health_during_work(handler, monkeypatch, queue, "_persist_queue_state", None)


def test_worker_reconciliation_keeps_health_responsive(monkeypatch):
    monkeypatch.setattr(admin.appconfig, "save_telegram", lambda *_: True)
    monkeypatch.setattr(admin.appconfig, "load_telegram", lambda: {"enabled": False})
    monkeypatch.setattr(admin, "state", SimpleNamespace(
        telegram_cfg={}, module_manager=SimpleNamespace(reconcile=lambda *_: None),
    ))

    async def handler():
        return await admin.api_telegram_config_set(admin.TelegramConfigBody())

    assert_health_during_work(handler, monkeypatch, admin.state.module_manager, "reconcile", None)


def test_release_check_store_lock_keeps_health_responsive(monkeypatch):
    monkeypatch.setattr(discovery.appconfig, "load_releases", lambda: {"api_key": "fixture"})
    service = SimpleNamespace(check=lambda *_: {})
    monkeypatch.setattr(discovery, "release_service", lambda: service)

    async def handler():
        return await discovery.api_release_check(discovery.ReleaseCheckBody(id="fixture"))

    assert_health_during_work(handler, monkeypatch, service, "check", {})


def test_browse_work_remains_bounded_after_client_cancellation(monkeypatch):
    pool = SeriesDetailWork(workers=1, capacity=1, retain_seconds=0)
    monkeypatch.setattr(interactive_work, "_BROWSE_WORK", pool)
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        assert release.wait(3)

    async def scenario():
        pending = asyncio.create_task(interactive_work.run_browse_work(blocked))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            with pytest.raises(HTTPException) as caught:
                await interactive_work.run_browse_work(lambda: None)
            assert caught.value.status_code == 503
            assert await asyncio.wait_for(legacy_health(), 0.1) == {"status": "ok"}
            running = next(iter(pool.jobs.values()))[0]
            release.set()
            await asyncio.wrap_future(running)
            assert await interactive_work.run_browse_work(lambda: 42) == 42
        finally:
            release.set()

    try:
        asyncio.run(scenario())
    finally:
        pool.close()


def test_browse_workers_preserve_request_context(monkeypatch):
    pool = SeriesDetailWork(workers=1, capacity=1, retain_seconds=0)
    monkeypatch.setattr(interactive_work, "_BROWSE_WORK", pool)
    owner = ContextVar("test_request_owner")

    async def scenario():
        owner.set("fixture-owner")
        return await interactive_work.run_browse_work(owner.get)

    try:
        assert asyncio.run(scenario()) == "fixture-owner"
    finally:
        pool.close()


def test_duplicate_cover_requests_share_work_and_survive_cancellation(monkeypatch):
    pool = SeriesDetailWork(workers=1, capacity=1, retain_seconds=0)
    monkeypatch.setattr(library, "_COVER_FETCH_POOL", pool)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def fetch(url):
        calls.append(url)
        entered.set()
        assert release.wait(3)
        return b"fixture", "image/png"

    monkeypatch.setattr(library, "_fetch_cover_data", fetch)

    async def scenario():
        first = asyncio.create_task(library.api_cover("fixture"))
        second = None
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            second = asyncio.create_task(library.api_cover("fixture"))
            await asyncio.sleep(0)
            with pytest.raises(HTTPException) as caught:
                await library.api_cover("another")
            assert caught.value.status_code == 503
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            release.set()
            assert (await second).body == b"fixture"
            assert calls == ["fixture"]
        finally:
            release.set()
            await asyncio.gather(first, *([second] if second else []), return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        pool.close()


def test_watchdog_retains_bounded_stall_evidence(caplog):
    now = [10.0]
    diagnostics = RuntimeDiagnostics(clock=lambda: now[0])
    diagnostics.tick()
    now[0] += 5
    diagnostics.check()
    diagnostics.check()
    snapshot = diagnostics.snapshot()
    assert snapshot["stall_count"] == 1
    assert snapshot["max_event_loop_lag_seconds"] == 4
    assert len(snapshot["last_stall"]["stack"]) <= 12
    assert "event loop stalled" in caplog.text
    diagnostics.tick()
    now[0] += 5
    diagnostics.check()
    assert diagnostics.snapshot()["stall_count"] == 2


def test_runtime_diagnostics_do_not_change_public_health_payload():
    app = FastAPI()
    app.include_router(create_system_router(lambda: [], runtime_diagnostics=lambda: {"pid": 123}))
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/diagnostics/runtime").json() == {"pid": 123}


@pytest.mark.parametrize("kind", ["movies", "series"])
def test_catalog_overload_remains_incomplete_instead_of_queuing_more(monkeypatch, kind):
    incomplete = [False]
    if kind == "movies":
        monkeypatch.setattr(movie_catalog, "MOVIE_PROVIDER_PENDING_LIMIT", 0)
        monkeypatch.setattr(movie_catalog, "_movie_provider_page_cache_state", lambda *_: (None, "missing"))
        result = movie_catalog._load_movie_provider_pages("new", "", [("filmpalast", 987)], timed_out=incomplete)
    else:
        monkeypatch.setattr(series_catalog_cache, "SERIES_PROVIDER_PENDING_LIMIT", 0)
        monkeypatch.setattr(series_catalog_cache, "cache_state", lambda *_: (None, "missing"))
        result = series_catalog_cache.load_pages(
            "new", "", [("filmpalast", 987)], lambda *_: pytest.fail("overload must not submit work"),
            timed_out=incomplete,
        )
    assert result == {}
    assert incomplete == [True]


def test_metadata_overload_keeps_series_pending(monkeypatch):
    monkeypatch.setattr(discovery, "get_tmdb_client", lambda: SimpleNamespace(configured=True))
    monkeypatch.setattr(discovery, "TMDB_METADATA_PENDING_LIMIT", 0)
    result = asyncio.run(discovery.api_tmdb_series(discovery.SeriesMetadataBody(items=[
        {"base_slug": "fixture", "title": "Fixture"},
    ])))
    assert result == {"series": {}, "pending": ["fixture"]}


def test_watchdog_thread_exits_with_lifespan():
    diagnostics = RuntimeDiagnostics()

    async def scenario():
        pending = asyncio.create_task(diagnostics.heartbeat())
        await asyncio.sleep(0)
        assert diagnostics.thread.is_alive()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not diagnostics.thread.is_alive()

    asyncio.run(scenario())


def test_maintenance_failure_does_not_disable_reconciliation_or_next_cycle(monkeypatch):
    calls = []
    cycles = []
    loop_thread = threading.get_ident()

    async def next_cycle(_seconds):
        cycles.append(1)
        if len(cycles) > 2:
            raise asyncio.CancelledError

    def cache():
        assert threading.get_ident() != loop_thread
        calls.append("cache")
        if len(calls) == 1:
            raise OSError("fixture storage failure")

    monkeypatch.setattr(runtime_maintenance, "asyncio", SimpleNamespace(
        sleep=next_cycle, to_thread=asyncio.to_thread,
    ))
    state = SimpleNamespace(maintain_runtime_caches=cache,
                            module_manager=SimpleNamespace(reconcile_all=lambda: calls.append("modules")))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime_maintenance.maintain_runtime(state))
    assert calls == ["cache", "modules", "cache", "modules"]
