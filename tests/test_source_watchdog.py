"""Deterministic monitoring/repair/escalation cycles, without live downloads."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_provider_monitor_router import create_provider_monitor_router
from application_services.provider_monitor import ProviderMonitor
from media.hoster_contracts import canary_identity, media_identity
from media.provider_health import ProviderHealth

NOW = 1_800_000_000


def monitor(tmp_path, **kwargs):
    return ProviderMonitor(tmp_path / "monitor.json", ProviderHealth(tmp_path / "health.json"),
                           lambda: ["filmpalast"], clock=lambda: NOW, **kwargs)


def test_persistent_deduplicated_escalation_recovery_and_new_incident(tmp_path):
    owner = monitor(tmp_path)
    try:
        owner.watchdog.result("filmpalast", failed=True)
        assert owner.watchdog.incidents("a") == []
        assert owner.watchdog.retry_delay("filmpalast") == 300
        owner.watchdog.result("filmpalast", failed=True)
        incident = owner.watchdog.incidents("a")[0]
        owner.watchdog.acknowledge(incident["id"], "a")
        owner.watchdog.result("filmpalast", failed=True)
        assert owner.watchdog.incidents("a")[0]["read"]
        assert not owner.watchdog.incidents("b")[0]["read"]
        assert owner.watchdog.incidents("a")[0]["id"] == incident["id"]
        owner.store.flush()
        restarted = monitor(tmp_path)
        try:
            assert restarted.watchdog.incidents("a") == owner.watchdog.incidents("a")
            restarted.watchdog.result("filmpalast", recovered=True)
            assert restarted.watchdog.incidents("a") == []
            assert restarted.watchdog.retry_delay("filmpalast") is None
            restarted.watchdog.result("filmpalast", rollback=True)
            assert restarted.watchdog.incidents("a")[0]["id"] != incident["id"]
        finally:
            restarted.stop()
    finally:
        owner.stop()


def test_individual_hoster_escalates_with_healthy_alternatives_and_push_opt_out(tmp_path):
    events = []
    owner = monitor(tmp_path, notify=events.append)
    try:
        owner.hosters.seed("voe", "https://voe.example/embed", "filmpalast")
        owner.hosters.seed("streamtape", "https://streamtape.example/embed", "filmpalast")
        for _ in range(3):
            owner.watchdog.result("voe", kind="hoster", failed=True)
        assert owner.watchdog.incidents("a")[0]["key"] == "voe"
        assert events == []  # Persistent inbox is independent of optional push.
        owner.store.configure({"notify_changes": True})
        owner.watchdog.result("streamtape", kind="hoster", rollback=True)
        owner.watchdog.result("streamtape", kind="hoster", failed=True)
        assert len(events) == 1 and events[0]["message_code"] == "source_attention"
        owner.enabled = lambda: []
        assert owner.watchdog.incidents("a") == []
    finally:
        owner.stop()


def test_canary_proof_restored_from_same_recent_hash_without_persisting_tokens(tmp_path):
    owner = monitor(tmp_path)
    url = "https://voe.example/embed?token=private"
    media = "https://cdn.example/movie.mp4?token=private"
    try:
        owner.hosters.observe("voe", url, True, 10, "filmpalast", media_url=media)
        owner.store.flush()
        assert "private" not in owner.store.path.read_text()
        restarted = monitor(tmp_path)
        try:
            assert not restarted.hosters.candidates("voe")
            restarted.hosters.seed("voe", url, "filmpalast")
            proof = restarted.hosters.candidates("voe")[0]
            assert proof["proven"] and proof["media_signature"] == media_identity(media)
            assert proof["identity"] == canary_identity(url)
            restarted.hosters.seed("voe", "https://voe.example/different", "filmpalast")
            assert not next(row for row in restarted.hosters.candidates("voe") if "different" in row["url"])["proven"]
        finally:
            restarted.stop()
    finally:
        owner.stop()


def test_start_staggers_reference_refresh_and_respects_disabled_monitor(tmp_path, monkeypatch):
    owner = monitor(tmp_path)
    monkeypatch.setattr(owner, "_loop", lambda: None)
    try:
        owner.store.update("filmpalast", last_check_at=NOW - 100, next_check_at=NOW + 40000)
        owner.start()
        owner.thread.join()
        assert NOW + 30 <= owner.store.entry("filmpalast")["next_check_at"] < NOW + 60
        owner.store.configure({"enabled": False})
        owner.store.update("filmpalast", next_check_at=NOW + 40000)
        owner.start()
        owner.thread.join()
        assert owner.store.entry("filmpalast")["next_check_at"] == NOW + 40000
    finally:
        owner.stop()


def test_admin_api_profile_guard_read_isolation_and_no_reader_leak(tmp_path):
    owner = monitor(tmp_path)
    owner.watchdog.result("filmpalast", rollback=True)
    app = FastAPI()
    app.include_router(create_provider_monitor_router(owner, lambda headers, cookies: {
        "id": headers.get("user", "a"), "role": headers.get("role", "admin"),
    }))
    try:
        with TestClient(app) as client:
            assert client.get("/api/providers/incidents", headers={"role": "member"}).status_code == 403
            assert client.get("/api/providers/incidents", headers={"X-Royal-Profile": "other"}).status_code == 409
            incident = client.get("/api/providers/incidents").json()["items"][0]
            url = f'/api/providers/incidents/{incident["id"]}/read'
            assert client.post(url, headers={"role": "member"}).status_code == 403
            assert client.post(url, headers={"X-Royal-Profile": "other"}).status_code == 409
            assert client.post(url).status_code == 200
            assert client.get("/api/providers/incidents").json()["items"][0]["read"]
            assert not client.get("/api/providers/incidents", headers={"user": "b"}).json()["items"][0]["read"]
            assert "read_by" not in client.get("/api/providers/incidents").text
            assert client.post("/api/providers/incidents/missing/read").status_code == 404
    finally:
        owner.stop()


def test_full_failed_cycle_retries_escalates_then_clears_on_confirmed_success(tmp_path):
    success = False
    def run(*args):
        return {"steps": [{"name": "connectivity", "ok": success, "code": "ok" if success else "domain_offline", "duration_ms": 1}],
                "details": [{"ok": True, "source": f"https://filmpalast.to/stream/{i}", "title": str(i), "media_type": "movies"} for i in range(3)] if success else [],
                "responses": [], "hoster_candidates": []}
    owner = monitor(tmp_path, probe=SimpleNamespace(run=run))
    owner.repairs.propose = lambda *a: []
    try:
        owner.check("filmpalast", "full")
        assert owner.watchdog.incidents("a") == []
        owner.check("filmpalast", "full")
        assert len(owner.watchdog.incidents("a")) == 1
        assert owner.store.entry("filmpalast")["next_check_at"] < NOW + 1900
        success = True
        owner.check("filmpalast", "full")
        assert not owner.watchdog.incidents("a")
    finally:
        owner.stop()


def test_incomplete_hoster_probes_do_not_escalate_stale_attention(tmp_path, monkeypatch):
    owner = monitor(tmp_path)
    try:
        owner.hosters.seed("voe", "https://voe.example/embed", "filmpalast")
        monkeypatch.setattr("application_services.hoster_monitor.source_health", lambda *args: "needs_attention")
        monkeypatch.setattr(owner.hosters.repairs, "propose", lambda *args: [])
        monkeypatch.setattr(owner.hosters, "schedule", lambda *args: None)
        result = {"steps": [], "details": [{"ok": False, "identity": "canary", "code": "browser_fallback_required", "probe_complete": False}]}
        monkeypatch.setattr(owner.hosters.probe, "run", lambda *args: result)
        for _ in range(3):
            owner.hosters.check("voe")
        assert owner.watchdog.incidents("owner") == []
        result["details"][0].update(code="network_error", probe_complete=False)
        for _ in range(3):
            owner.hosters.check("voe")
        assert owner.watchdog.incidents("owner") == []
        result["details"][0]["probe_complete"] = True
        owner.hosters.check("voe")
        owner.hosters.check("voe")
        assert owner.watchdog.incidents("owner")[0]["key"] == "voe"
    finally:
        owner.stop()
