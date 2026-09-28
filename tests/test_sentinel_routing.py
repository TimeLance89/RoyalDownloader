"""Diagnostics may warn; only production evidence may close a route."""
import asyncio
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from application_services.provider_monitor import ProviderMonitor
from application_services.source_service_health import source_service_health
from media.provider_health import ProviderHealth
from providers import sentinel_runtime

NOW = 2_000_000


def owner(tmp_path, result=None):
    health = ProviderHealth(tmp_path / "health.json", clock=lambda: NOW)
    monitor = ProviderMonitor(tmp_path / "monitor.json", health, lambda: ["aniworld"],
                              probe=SimpleNamespace(run=lambda *_args: result), clock=lambda: NOW)
    return monitor


def partial():
    return {"steps": [{"name": "metadata", "sample": str(i), "ok": False,
                       "code": "parser_error", "duration_ms": 1} for i in range(5)],
            "details": [], "responses": [], "canaries": []}


@pytest.mark.parametrize("diagnosis", ["degraded", "needs_attention", "broken", "blocked", "unknown"])
def test_diagnostic_warning_is_not_routing_evidence(tmp_path, diagnosis, monkeypatch):
    monitor = owner(tmp_path, partial())
    try:
        monitor.store.update("aniworld", diagnosis=diagnosis)
        monkeypatch.setattr(sentinel_runtime, "_runtime", monitor)
        for _ in range(4):
            monitor.check("aniworld", "full")
        assert monitor.health.request_allowed("aniworld")
        assert monitor.diagnostics("aniworld")["providers"][0]["routing"]["allowed"]
    finally:
        monitor.pool.shutdown(wait=True)


def test_recent_runtime_success_outweighs_partial_probe(tmp_path):
    monitor = owner(tmp_path, partial())
    try:
        monitor.observe("aniworld", True, .1, "title", {"title": "Title"}, "get_anime")
        for _ in range(5):
            monitor.check("aniworld", "full")
        assert monitor.health.status("aniworld")["last_runtime_success_at"] == NOW
        assert monitor.health.request_allowed("aniworld")
    finally:
        monitor.pool.shutdown(wait=True)


def test_independent_real_failures_close_circuit_not_removed_titles(tmp_path):
    monitor = owner(tmp_path)
    try:
        for title in ("one", "two", "three"):
            monitor.observe("aniworld", False, .1, title, operation="get_anime")
        assert monitor.health.request_allowed("aniworld")
        for _ in range(4):
            monitor.observe("aniworld", False, .1, "same", operation="get_anime", runtime_failure=True)
        assert monitor.health.request_allowed("aniworld")
        for title in ("other", "third"):
            monitor.observe("aniworld", False, .1, title, operation="get_anime", runtime_failure=True)
        assert not monitor.health.routing_allowed("aniworld")
        assert monitor.health.status("aniworld")["reason"] == "runtime_independent_failures"
        assert "third" not in (tmp_path / "health.json").read_text()
    finally:
        monitor.pool.shutdown(wait=True)


def test_repeated_confirmed_domain_offline_can_quarantine(tmp_path):
    result = {"steps": [{"name": "connectivity", "sample": "", "ok": False,
                         "code": "domain_offline", "duration_ms": 1}], "details": [], "responses": []}
    monitor = owner(tmp_path, result)
    try:
        monitor.check("aniworld")
        monitor.check("aniworld")
        assert monitor.health.routing_allowed("aniworld")
        monitor.check("aniworld")
        assert not monitor.health.routing_allowed("aniworld")
    finally:
        monitor.pool.shutdown(wait=True)


def test_only_explicit_nxdomain_is_hard_offline():
    assert sentinel_runtime.confirmed_dns_failure(socket.gaierror(socket.EAI_NONAME, "not found"))
    assert not sentinel_runtime.confirmed_dns_failure(socket.gaierror(socket.EAI_AGAIN, "temporary"))
    assert not sentinel_runtime.confirmed_dns_failure(TimeoutError())


def test_old_sentinel_quarantine_reconciled_runtime_breaker_preserved(tmp_path):
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"providers": {
        "aniworld": {"state": "cooldown", "blocked_reason": "sentinel_confirmed_failure", "next_probe_at": NOW + 900},
        "mkissa": {"state": "cooldown", "blocked_reason": "runtime_independent_failures", "next_probe_at": NOW + 900},
        "serienstream": {"state": "cooldown", "blocked_reason": "captcha_gate", "next_probe_at": NOW + 900},
    }}))
    health = ProviderHealth(path, clock=lambda: NOW)
    assert health.routing_allowed("aniworld")
    assert health.status("aniworld")["last_runtime_success_at"] == 0
    assert not health.routing_allowed("mkissa")
    assert not health.routing_allowed("serienstream")
    restored = ProviderHealth(path, clock=lambda: NOW)
    assert restored.routing_allowed("aniworld")
    assert not restored.routing_allowed("mkissa")


def test_real_adapter_recovery_without_restart(tmp_path, monkeypatch):
    now = [NOW]
    monitor = owner(tmp_path)
    monitor.health.clock = lambda: now[0]
    monkeypatch.setattr(sentinel_runtime, "_runtime", monitor)

    @sentinel_runtime.monitor_adapter("aniworld")
    class Adapter:
        def __init__(self):
            self.session = SimpleNamespace()

        def browse(self):
            assert sentinel_runtime._recovery.get() == "aniworld"
            return {"results": [{"title": "Recovered"}]}

    try:
        blocked = monitor.health.mark_blocked("aniworld", "runtime_independent_failures")
        with pytest.raises(sentinel_runtime.ProbeFailure, match="provider_cooldown"):
            Adapter().browse()
        now[0] = blocked["next_probe_at"]
        assert monitor.health.routing_allowed("aniworld")
        assert Adapter().browse()["results"]
        assert monitor.health.request_allowed("aniworld")
    finally:
        monitor.pool.shutdown(wait=True)


@pytest.mark.parametrize("language", ["de", "en"])
def test_aniworld_last_route_api_attempted_despite_diagnosis(tmp_path, monkeypatch, language):
    import server
    from api import api_discovery_router as discovery
    from application_services.movie_catalog import provider_priority
    monitor = owner(tmp_path)
    monitor.store.update("aniworld", diagnosis="needs_attention")
    monkeypatch.setattr(sentinel_runtime, "_runtime", monitor)
    monkeypatch.setattr(server.state, "provider_health", monitor.health)
    monkeypatch.setattr(server.state, "content_languages", {language})
    monkeypatch.setattr(server.state, "provider_enabled", {"anime": ["aniworld", "mkissa"]})
    monkeypatch.setattr(server.state, "provider_priorities", {"anime": ["aniworld", "mkissa"]})
    calls = []
    monkeypatch.setattr(discovery, "get_aniworld_scraper", lambda: SimpleNamespace(browse=lambda **kw: calls.append(kw) or {"results": [{"id": "fixture"}]}))
    try:
        assert "aniworld" in provider_priority("anime")
        result = asyncio.run(discovery.api_aniworld())
        assert calls and result["disabled"] is False
        assert result["results"][0]["id"] == "fixture"
        assert server.state.provider_enabled["anime"] == ["aniworld", "mkissa"]
    finally:
        monitor.pool.shutdown(wait=True)


@pytest.mark.parametrize("enabled,languages,blocked,phrase", [
    ([], {"de"}, False, "deaktiviert"), (["aniworld"], {"ja"}, False, "Inhaltssprachen"),
    (["aniworld"], {"de"}, True, "automatisch erneut"),
])
def test_api_unavailable_reasons_are_distinct(tmp_path, monkeypatch, enabled, languages, blocked, phrase):
    from api import api_discovery_router as discovery
    health = ProviderHealth(tmp_path / "health.json", clock=lambda: NOW)
    if blocked:
        health.mark_blocked("aniworld", "runtime_independent_failures")
    monkeypatch.setattr(discovery, "state", SimpleNamespace(provider_enabled={"anime": enabled}, content_languages=languages,
                                                           provider_health=health, aniworld_lock=threading.RLock()))
    assert phrase in discovery.aniworld_unavailable_reason()


@pytest.mark.parametrize("diagnosis,allowed,success,expected", [
    ("degraded", True, False, "unconfirmed"), ("needs_attention", True, True, "healthy"),
    ("broken", True, True, "healthy"), ("broken", True, False, "unconfirmed"),
    ("offline", False, False, "action_required"),
])
def test_service_health_uses_routing_and_actual_language_evidence(diagnosis, allowed, success, expected):
    provider = {"provider": "aniworld", "enabled": True, "contract": {"media_types": ["anime"]},
                "content_languages": ["de", "en"], "diagnosis": diagnosis, "last_check_at": NOW - 10,
                "routing": {"allowed": allowed}, "runtime": {"state": "healthy" if allowed else "cooldown",
                    "last_runtime_success_at": NOW - 60 if success else 0},
                "language_evidence": {"anime": {"de": NOW - 60}} if success else {}}
    hoster = {"hoster": "working", "providers": ["aniworld"], "diagnosis": "healthy", "last_check_at": NOW - 30}
    summary = source_service_health([provider], [hoster], NOW, {"de"})
    assert summary["coverage"]["anime"] == expected
    assert summary["action_required"] == (not allowed)


def test_failed_hoster_does_not_remove_provider_route(tmp_path):
    monitor = owner(tmp_path)
    try:
        monitor.hosters.store.update("voe", diagnosis="broken")
        assert monitor.health.routing_allowed("aniworld")
    finally:
        monitor.pool.shutdown(wait=True)


def test_actual_german_circuit_failure_excludes_route_and_recovers_live(tmp_path, monkeypatch):
    import server
    from application_services.movie_catalog import provider_priority
    monitor = owner(tmp_path)
    monkeypatch.setattr(server.state, "provider_health", monitor.health)
    monkeypatch.setattr(server.state, "content_languages", {"de"})
    monkeypatch.setattr(server.state, "provider_enabled", {"anime": ["aniworld", "mkissa"]})
    monkeypatch.setattr(server.state, "provider_priorities", {"anime": ["aniworld", "mkissa"]})
    try:
        for title in ("one", "two", "three"):
            monitor.observe("aniworld", False, .1, title, operation="get_anime", runtime_failure=True)
        assert provider_priority("anime") == []
        assert monitor.diagnostics()["service"]["coverage"]["anime"] == "action_required"
        monitor.health.record_runtime("aniworld", True)
        assert provider_priority("anime") == ["aniworld"]
        assert not monitor.diagnostics()["service"]["action_required"]
        monkeypatch.setattr(server.state, "provider_enabled", {"anime": ["mkissa"]})
        assert provider_priority("anime") == []
    finally:
        monitor.pool.shutdown(wait=True)


def test_diagnostics_reorder_not_remove_matching_routes(tmp_path, monkeypatch):
    import server
    from application_services.movie_catalog import provider_priority
    monitor = owner(tmp_path)
    monitor.store.update("aniworld", diagnosis="needs_attention")
    monkeypatch.setattr(sentinel_runtime, "_runtime", monitor)
    monkeypatch.setattr(server.state, "provider_health", monitor.health)
    monkeypatch.setattr(server.state, "content_languages", {"en"})
    monkeypatch.setattr(server.state, "provider_enabled", {"anime": ["aniworld", "mkissa"]})
    monkeypatch.setattr(server.state, "provider_priorities", {"anime": ["aniworld", "mkissa"]})
    try:
        assert provider_priority("anime") == ["mkissa", "aniworld"]
        monitor.store.update("aniworld", diagnosis="healthy")
        assert provider_priority("anime") == ["aniworld", "mkissa"]
    finally:
        monitor.pool.shutdown(wait=True)
