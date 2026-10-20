"""Bounded series work is shared across retries and survives HTTP cancellation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
import server  # noqa: F401
from starlette.concurrency import run_in_threadpool
import anyio

from api import api_discovery_router as discovery
from application_services import series_catalog as catalog
from application_services.series_detail_work import SeriesDetailWork, SeriesDetailsBusy


def test_work_is_shared_bounded_and_completed_results_expire():
    clock = [0]
    service = SeriesDetailWork(workers=1, capacity=2, clock=lambda: clock[0])
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(3)
        return {"result": 1}

    try:
        first = service.submit("first", work)
        assert entered.wait(1)
        assert service.submit("first", lambda: pytest.fail("duplicated work")) is first
        second = service.submit("second", lambda: 2)
        with pytest.raises(SeriesDetailsBusy):
            service.submit("third", lambda: None)
        release.set()
        assert first.result(2) == {"result": 1}
        assert second.result(2) == 2
        assert service.submit("first", lambda: None) is first
        # The completion callback also runs on the worker; wait for its tail.
        service.pool.submit(lambda: None).result(2)
        clock[0] = 6
        assert service.submit("first", lambda: "fresh").result(2) == "fresh"
    finally:
        release.set()
        service.close()


def test_failed_work_can_be_retried():
    service = SeriesDetailWork(workers=1)
    try:
        failed = service.submit("key", lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            failed.result(2)
        service.pool.submit(lambda: None).result(2)
        assert service.submit("key", lambda: "recovered").result(2) == "recovered"
    finally:
        service.close()


def test_provider_timeout_is_not_misreported_as_pending(monkeypatch):
    service = SeriesDetailWork()
    monkeypatch.setattr(discovery, "_SERIES_DETAIL_WORK", service)
    monkeypatch.setattr(discovery, "get_tmdb_client", lambda: service)

    def failed():
        raise TimeoutError("provider timeout")

    try:
        with pytest.raises(TimeoutError, match="provider timeout"):
            asyncio.run(discovery._bounded_series_detail_work("timeout", failed, progressive=True))
    finally:
        service.close()


@pytest.mark.parametrize("kind", ["series", "matches"])
def test_slow_library_reads_leave_auth_and_static_file_workers_available(monkeypatch, kind):
    entered, release = threading.Event(), threading.Event()
    service = SeriesDetailWork(workers=2, capacity=2, retain_seconds=0)
    calls = []

    def blocked(*_args, **_kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return {"available": True} if kind == "series" else SimpleNamespace(configured=False)

    monkeypatch.setattr(discovery, "_LIBRARY_WORK", service)
    monkeypatch.setattr(discovery, "_series_jellyfin_status", blocked)
    monkeypatch.setattr(discovery, "get_jellyfin_client", blocked)
    route, body = ((discovery.api_series_jellyfin_status, discovery.SeriesJellyfinStatusBody(title="Fixture", episodes=[]))
                   if kind == "series" else (discovery.api_jellyfin_matches, discovery.MovieMetadataBody(items=[])))

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1
        requests = [asyncio.create_task(route(body)) for _ in range(2)]
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert await asyncio.wait_for(run_in_threadpool(lambda: "auth/static available"), 0.25) == "auth/static available"
            assert len(calls) == 1
        finally:
            release.set()
            limiter.total_tokens = previous
            await asyncio.gather(*requests)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        service.close()


def test_native_callers_keep_completed_response_contract(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    service = SeriesDetailWork()
    monkeypatch.setattr(discovery, "_SERIES_DETAIL_WORK", service)
    monkeypatch.setattr(discovery, "SERIES_DETAIL_WAIT_SECONDS", 0)
    monkeypatch.setattr(discovery, "get_tmdb_client", lambda: service)

    def work():
        entered.set()
        assert release.wait(3)
        return "complete"

    async def scenario():
        pending = asyncio.create_task(discovery._bounded_series_detail_work("native", work))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            await asyncio.sleep(0)
            assert not pending.done()
        finally:
            release.set()
        assert await pending == "complete"

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        service.close()


@pytest.mark.parametrize("defer_checks", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
def test_detail_wait_is_short_and_retry_reuses_same_enrichment(monkeypatch, cancel, defer_checks):
    entered, release = threading.Event(), threading.Event()
    service = SeriesDetailWork()
    series = SimpleNamespace(base_slug="fixture", title="Fixture", url="fixture")
    state = SimpleNamespace(series_cache={"fixture": series}, series_path="fixture", jellyfin_config_generation=0)
    calls = []

    def payload(*_args, **_kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return {"title": "Fixture", "seasons": []}

    monkeypatch.setattr(discovery, "state", state)
    monkeypatch.setattr(discovery, "_SERIES_DETAIL_WORK", service)
    monkeypatch.setattr(discovery, "SERIES_DETAIL_WAIT_SECONDS", 0.02)
    monkeypatch.setattr(discovery, "get_tmdb_client", lambda: state)
    monkeypatch.setattr(discovery, "series_to_dict", payload)
    monkeypatch.setattr(discovery, "series_payload_missing_seasons", lambda _: set())
    body = discovery.SeriesLoadBody(sample_slug="fixture", base_slug="fixture", progressive=True,
                                    defer_checks=defer_checks)

    async def scenario():
        first = asyncio.create_task(discovery.api_series_load(body))
        assert await asyncio.to_thread(entered.wait, 1)
        if cancel:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            with pytest.raises(HTTPException) as error:
                await first
            assert error.value.status_code == 503
            assert error.value.detail["code"] == "series_details_pending"
        assert not next(iter(service.jobs.values()))[0].cancelled()
        release.set()
        await asyncio.to_thread(next(iter(service.jobs.values()))[0].result, 2)
        assert await discovery.api_series_load(body) == {"title": "Fixture", "seasons": []}
        assert len(calls) == 1

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        service.close()


def test_inventory_scans_share_global_capacity(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    full = threading.Event()
    active = peak = calls = 0
    lock = threading.Lock()
    series = []
    for index in range(2):
        folder = tmp_path / f"Fixture{index}"
        folder.mkdir()
        for episode in range(1, 5):
            (folder / f"Fixture S01E{episode:02d}.mkv").write_bytes(b"fixture")
        series.append(SimpleNamespace(title=f"Fixture{index}", all_episodes=[
            SimpleNamespace(slug=f"episode-{number}", season=1, episode=number) for number in range(1, 5)
        ]))
    state = SimpleNamespace(series_path=str(tmp_path), media_validation_cache={}, media_validation_lock=threading.RLock())

    def validate(_path):
        nonlocal active, peak, calls
        with lock:
            active += 1
            calls += 1
            peak = max(peak, active)
            if active == 4:
                full.set()
        entered.set()
        try:
            assert release.wait(3)
            return True, "verified"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(catalog, "state", state)
    monkeypatch.setattr(catalog, "_existing_series_dir", lambda root, title: root / title)
    monkeypatch.setattr(catalog, "validate_media_file", validate)
    with ThreadPoolExecutor(max_workers=2) as readers:
        futures = [readers.submit(catalog.compute_downloaded_episodes, item) for item in series]
        try:
            assert entered.wait(1)
            assert full.wait(1)
            threading.Event().wait(0.05)
            assert peak <= 4
        finally:
            release.set()
        assert all(len(future.result(2)) == 4 for future in futures)
    assert calls == 8
    assert peak <= 4
    # A changed file signature must invalidate the old verification.
    path = tmp_path / "Fixture0" / "Fixture S01E01.mkv"
    path.write_bytes(b"changed fixture")
    assert catalog._valid_media_cached(Path(path))[0]
    assert calls == 9


def test_two_cold_readers_of_same_file_run_only_one_probe(monkeypatch, tmp_path):
    entered, both_read, release = threading.Event(), threading.Event(), threading.Event()
    readers_seen, calls = set(), []

    class Cache(dict):
        def get(self, key):
            readers_seen.add(threading.get_ident())
            if len(readers_seen) == 2:
                both_read.set()
            return super().get(key)

    state = SimpleNamespace(media_validation_cache=Cache(), media_validation_lock=threading.RLock())
    path = tmp_path / "fixture.mkv"
    path.write_bytes(b"fixture")

    def validate(_path):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return True, "verified"

    monkeypatch.setattr(catalog, "state", state)
    monkeypatch.setattr(catalog, "validate_media_file", validate)
    with ThreadPoolExecutor(max_workers=2) as readers:
        futures = [readers.submit(catalog._valid_media_cached, path) for _ in range(2)]
        try:
            assert entered.wait(1)
            assert both_read.wait(1)
        finally:
            release.set()
        assert all(future.result(2) == (True, "verified") for future in futures)
    assert len(calls) == 1
