"""Regressions from the NAS source-monitor audit, without production services."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_provider_monitor_router import create_provider_monitor_router
from application_services.provider_monitor import ProviderMonitor
from application_services.hoster_monitor import MAX_HOSTERS
from media.hoster_contracts import CONTRACTS, runtime_contract
from media.provider_health import ProviderHealth
from media.provider_monitor_store import ProviderMonitorStore


def monitor(tmp_path, clock=time.time):
    return ProviderMonitor(tmp_path / "monitor.json", ProviderHealth(tmp_path / "health.json", clock=clock),
                           lambda: ["filmpalast"], clock=clock)


def test_resolve_telemetry_coalesces_without_synchronous_io(tmp_path, monkeypatch):
    owner = monitor(tmp_path)
    writes = []
    original = owner.store._write_data
    monkeypatch.setattr(owner.store, "_write_data", lambda data: (writes.append(1), original(data)))
    try:
        for index in range(20):
            owner.hosters.begin("voe", f"https://voe.example/{index}", "filmpalast")
            owner.hosters.observe("voe", f"https://voe.example/{index}", True, 20, "filmpalast")
        assert writes == []
        assert owner.store.persistence_status()["pending"]
        assert next(row for row in owner.hosters.diagnostics() if row["hoster"] == "voe")["metrics_24h"]["attempts"] == 20
        assert owner.store.flush()
        assert len(writes) == 1
        reloaded = ProviderMonitorStore(owner.store.path)
        assert len(reloaded.entry("voe", namespace="hosters")["samples"]) == 20
    finally:
        owner.stop()


def test_blocked_flush_does_not_block_telemetry_or_lose_durable_configuration(tmp_path, monkeypatch):
    store = ProviderMonitorStore(tmp_path / "state.json")
    store.update("filmpalast", deferred=True, diagnosis="healthy")
    entered, release = threading.Event(), threading.Event()
    original = store._write_data

    def slow(data):
        entered.set()
        assert release.wait(5)
        original(data)

    monkeypatch.setattr(store, "_write_data", slow)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        pending = store.flush_background()
        assert entered.wait(2)
        assert store.flush_background() is pending  # No replacement writer/queue.
        change = pool.submit(store.update, "filmpalast", deferred=True, diagnosis="degraded")
        change.result(timeout=1)
        assert store.entry("filmpalast")["diagnosis"] == "degraded"
        saved = pool.submit(store.configure, {"enabled": False})
        release.set()
        pending.result(timeout=3)
        saved.result(timeout=3)
        persisted = json.loads(store.path.read_text())
        assert persisted["config"]["enabled"] is False
        assert persisted["providers"]["filmpalast"]["diagnosis"] == "degraded"
    finally:
        release.set()
        pool.shutdown(wait=True)
        store.close()


def test_failed_background_write_retries_and_failed_configuration_rolls_back(tmp_path, monkeypatch):
    store = ProviderMonitorStore(tmp_path / "state.json")
    store.update("filmpalast", deferred=True, diagnosis="healthy")
    original = store._write_data

    def fail(_data):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store, "_write_data", fail)
    assert not store.flush()
    assert store.persistence_status() == {"pending": True, "write_failed": True}
    try:
        store.configure({"enabled": False})
        raise AssertionError("durable configuration cannot claim success")
    except OSError:
        pass
    assert store.config()["enabled"] is True
    monkeypatch.setattr(store, "_write_data", original)
    assert store.flush()
    assert not store.persistence_status()["pending"]
    assert not store.persistence_status()["write_failed"]
    assert json.loads(store.path.read_text())["config"]["enabled"] is True
    store.close()


def test_scheduler_survives_disk_error_and_continues_other_sources(tmp_path, monkeypatch):
    owner = monitor(tmp_path)
    owner.enabled = lambda: ["filmpalast", "moflix"]
    now = time.time()
    for key in owner.enabled():
        owner.store.update(key, next_check_at=now - 10, requested_intensity="light")
    original = owner.store.update
    attempts = []

    def update(key, **values):
        if key == "filmpalast":
            raise OSError("simulated disk error")
        return original(key, **values)

    monkeypatch.setattr(owner.store, "update", update)
    monkeypatch.setattr(owner, "request", lambda key, *a, **kw: attempts.append(key) or True)
    # Run real loop rounds without sleeping or issuing network requests.
    rounds = []
    def wait(_timeout):
        rounds.append(1)
        if len(rounds) == 2:
            owner.stop_event.set()
        return True
    monkeypatch.setattr(owner.wake, "wait", wait)
    try:
        owner._loop()
        assert len(rounds) == 2
        assert attempts.count("moflix") == 2
        assert owner.scheduler_errors == 2
        assert owner.scheduler_retrying
        monkeypatch.setattr(owner.store, "update", original)
        owner.stop_event.clear()
        rounds.clear()
        owner._loop()
        assert not owner.scheduler_retrying
    finally:
        owner.stop()


def fill_inventory(owner, now):
    for index in range(MAX_HOSTERS - len(CONTRACTS)):
        key = f"dynamic{index}"
        owner.hosters.inventory[key] = runtime_contract(key)
        owner.store.update(key, namespace="hosters", deferred=True, last_seen_at=now - 9 * 86400)


def test_full_inventory_reclaims_idle_dynamic_hosters_but_protects_repairs_and_work(tmp_path):
    now = time.time()
    owner = monitor(tmp_path, clock=lambda: now)
    fill_inventory(owner, now)
    owner.hosters.store.update("dynamic0", active_repair="keep", deferred=True)
    owner.active.add("hoster:dynamic1")
    try:
        owner.hosters.observe("newdynamic", "https://new.example/embed", True, provider="filmpalast")
        assert len(owner.hosters.inventory) == MAX_HOSTERS
        assert "newdynamic" in owner.hosters.inventory
        assert "dynamic0" in owner.hosters.inventory
        assert "dynamic1" in owner.hosters.inventory
        assert set(CONTRACTS) <= set(owner.hosters.inventory)
        assert len(owner.hosters.store.entry("newdynamic")["samples"]) == 1
        assert len(owner.store.data["hosters"]) == MAX_HOSTERS - len(CONTRACTS)
    finally:
        owner.stop()


def test_fresh_full_inventory_exposes_rejection_and_recovers_when_old(tmp_path):
    now = [time.time()]
    owner = monitor(tmp_path, clock=lambda: now[0])
    fill_inventory(owner, now[0] + 9 * 86400)
    try:
        owner.hosters.observe("newdynamic", "https://new.example/embed", True)
        assert "newdynamic" not in owner.hosters.inventory
        assert owner.diagnostics(details=False)["hoster_inventory"]["rejected"] == 1
        now[0] += 8 * 86400
        owner.hosters.observe("newdynamic", "https://new.example/embed", True)
        assert "newdynamic" in owner.hosters.inventory
        assert owner.hosters.rejected_admissions == 0
    finally:
        owner.stop()


def test_compact_http_poll_preserves_health_and_omits_large_histories(tmp_path):
    owner = monitor(tmp_path)
    event = {"timestamp": time.time(), "event": "probe", "diagnosis": "healthy", "duration_ms": 20,
             "hoster_names": ["voe"], "steps": [{"name": "detail", "code": "ok", "padding": "x" * 400} for _ in range(35)]}
    owner.store.update("filmpalast", history=[event] * 120, repairs=[{"id": "test", "profile": {"domain": "example.com"}}],
                       diagnosis="healthy", last_check_at=time.time())
    app = FastAPI()
    app.include_router(create_provider_monitor_router(owner, lambda *_: {"role": "admin"}))
    try:
        client = TestClient(app)
        full = client.get("/api/providers/diagnostics").json()
        response = client.get("/api/providers/diagnostics?summary=true")
        small = response.json()
        assert small["service"] == full["service"]
        assert small["summary"] == full["summary"]
        assert small["compact"] is True
        row = next(row for row in small["providers"] if row["provider"] == "filmpalast")
        assert row["history"] == row["repairs"] == []
        assert row["history_count"] == 120 and row["repairs_count"] == 1
        assert row["error_rate_24h"] == 0
        assert len(response.content) < len(json.dumps(full)) / 10
        assert len(client.get("/api/providers/filmpalast/history").json()["history"]) == 120
        assert client.get("/api/providers/filmpalast/repairs").json()["repairs"][0]["id"] == "test"
    finally:
        owner.stop()


def test_manual_probe_all_is_one_durable_commit_and_still_staggered(tmp_path, monkeypatch):
    owner = monitor(tmp_path)
    owner.enabled = lambda: ["filmpalast", "moflix"]
    owner.hosters.seed("voe", "https://voe.example/sample", "filmpalast")
    writes = []
    original = owner.store._write_data
    monkeypatch.setattr(owner.store, "_write_data", lambda data: (writes.append(1), original(data)))
    try:
        owner.schedule_checks("light")
        assert len(writes) == 1
        data = json.loads(owner.store.path.read_text())
        first, second = (data["providers"][key] for key in owner.enabled())
        assert second["next_check_at"] - first["next_check_at"] == 30
        assert first["requested_intensity"] == data["hosters"]["voe"]["requested_intensity"] == "light"
        assert owner.wake.is_set()
    finally:
        owner.stop()
