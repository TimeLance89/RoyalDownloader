"""Offline Sentinel tests: real HTML parsing, shadow repairs and bounded routing."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from application_services.provider_monitor import ProviderMonitor
from application_services.provider_probe import ProviderProbe, diagnose, identity
from application_services.provider_repair import ProviderRepair, validate_profile
from media.provider_health import ProviderHealth
from media.provider_monitor_store import MAX_HISTORY, ProviderMonitorStore
from providers.catalog import PROVIDER_CATALOG
from providers.filmpalast import FilmpalastScraper
from providers.probe_contracts import ADAPTER_CLASSES, ProbeContract, create_adapter
from providers.sentinel_runtime import AdapterSession, ProbeFailure, probe_context

FIXTURES = Path(__file__).parent / "fixtures" / "provider-sentinel"


class FixtureSession:
    def __init__(self, *, changed=False, domain=None, blocked=False, missing_hosters=False):
        self.changed, self.domain, self.blocked, self.missing_hosters = changed, domain, blocked, missing_hosters
        self.calls = []
        self._curl = self  # Model SessionManager's HTTP-only transport surface.

    def get(self, url, **options):
        self.calls.append((url, options))
        if self.blocked:
            text = (FIXTURES / "blocked.html").read_text()
        elif "/stream/" in url:
            text = (FIXTURES / "detail.html").read_text().replace("%INDEX%", url.rsplit("-", 1)[1])
            if self.changed:
                text = text.replace('h2 class="bgDark"', 'h1 class="media-heading"').replace("</h2>", "</h1>")
            if self.missing_hosters:
                text = text.replace('class="currentStreamLinks"', 'class="missing"')
        else:
            text = (FIXTURES / "catalog.html").read_text()
            if self.changed:
                text = text.replace('class="liste"', 'class="media-card"')
        final_url = url.replace("filmpalast.to", self.domain) if self.domain else url
        return SimpleNamespace(text=text, status_code=200, url=final_url)

    def close(self):
        pass


def real_probe(monkeypatch, transport):
    # Focus the real Filmpalast movie parser. Whole-provider mixed-media
    # capability coverage is independently enforced below.
    monkeypatch.setattr("application_services.provider_probe.contract", lambda p: ProbeContract(p, ("movies",), True, ()))
    def factory(_provider):
        adapter = FilmpalastScraper.__new__(FilmpalastScraper)
        adapter._log = lambda _message: None
        adapter.session = AdapterSession("filmpalast", transport)
        return adapter
    return ProviderProbe(factory)


def test_real_parser_shadow_repair_and_rollback(monkeypatch, tmp_path):
    transport = FixtureSession()
    probe = real_probe(monkeypatch, transport)
    baseline = probe.run("filmpalast", "full")
    assert diagnose(baseline) == "healthy"
    store = ProviderMonitorStore(tmp_path / "monitor.json")
    repair = ProviderRepair(store, probe)
    transport.changed = True
    broken = probe.run("filmpalast", "full", canaries=baseline["canaries"])
    assert diagnose(broken, baseline["responses"]) == "broken"
    # Two uniquely identified fields can be validated together; neither alone
    # passes the whole shadow contract.
    candidates = repair.propose("filmpalast", broken, baseline["canaries"])
    assert candidates[0]["confidence"] == "high"
    profile, evidence = repair.validate("filmpalast", {"catalog_selector": "article.media-card", "title_selector": "h1.media-heading"}, broken, baseline["canaries"])
    assert evidence["shadow_passed"] and evidence["validated_detail_pages"] == 5
    candidate = {"id": "fixture-repair", "profile": profile, "previous_profile": {}, "state": "available", "confidence": "high", "validation": evidence}
    store.add_repair("filmpalast", candidate)
    repair.activate("filmpalast", candidate["id"])
    assert repair.profile("filmpalast") == profile
    repair.rollback("filmpalast", candidate["id"])
    assert repair.profile("filmpalast") == {}
    raw = (tmp_path / "monitor.json").read_text()
    assert "<html" not in raw and "voe.example" not in raw
    assert all(options["verify"] is True and options["timeout"] <= 8 for _, options in transport.calls)


@pytest.mark.parametrize("kind", ["title", "catalog"])
def test_simple_selector_change_automatically_validates(monkeypatch, tmp_path, kind):
    transport = FixtureSession()
    probe = real_probe(monkeypatch, transport)
    baseline = probe.run("filmpalast", "full")
    original = transport.get
    def changed(url, **options):
        result = original(url, **options)
        if kind == "title":
            result.text = result.text.replace('h2 class="bgDark"', 'h1 class="media-heading"').replace('</h2><img class="cover2"', '</h1><img class="cover2"')
        else:
            result.text = result.text.replace('class="liste"', 'class="media-card"')
        return result
    transport.get = changed
    current = probe.run("filmpalast", "full", canaries=baseline["canaries"])
    repair = ProviderRepair(ProviderMonitorStore(tmp_path / "state.json"), probe)
    proposed = repair.propose("filmpalast", current, baseline["canaries"])
    assert any(item["confidence"] == "high" and item["validation"]["validated_detail_pages"] == 5 for item in proposed)


def test_blocked_pages_never_generate_repairs_or_browser_recovery(monkeypatch, tmp_path):
    transport = FixtureSession(blocked=True)
    probe = real_probe(monkeypatch, transport)
    result = probe.run("filmpalast", "full")
    assert diagnose(result) == "blocked"
    assert len(transport.calls) == 1
    assert ProviderRepair(ProviderMonitorStore(tmp_path / "state.json"), probe).propose("filmpalast", result, []) == []


def test_domain_candidate_needs_three_known_pages_and_hosters(monkeypatch, tmp_path):
    transport = FixtureSession()
    probe = real_probe(monkeypatch, transport)
    baseline = probe.run("filmpalast", "full")
    transport.domain = "filmpalast-new.example"
    current = probe.run("filmpalast", "full", canaries=baseline["canaries"])
    repair = ProviderRepair(ProviderMonitorStore(tmp_path / "state.json"), probe)
    candidates = repair.propose("filmpalast", current, baseline["canaries"])
    assert candidates[0]["confidence"] == "high"
    assert candidates[0]["profile"] == {"domain": "filmpalast-new.example"}
    _, evidence = repair.validate("filmpalast", candidates[0]["profile"], current, baseline["canaries"][:1])
    assert not evidence["shadow_passed"]
    transport.missing_hosters = True
    _, evidence = repair.validate("filmpalast", candidates[0]["profile"], current, baseline["canaries"])
    assert not evidence["shadow_passed"]


def test_http_budget_stops_adapter_calls():
    session = AdapterSession("filmpalast", FixtureSession())
    with probe_context("filmpalast", maximum_requests=1):
        session.get("https://filmpalast.to/")
        with pytest.raises(ProbeFailure, match="budget_exhausted"):
            session.get("https://filmpalast.to/")


@pytest.mark.parametrize("provider", sorted(PROVIDER_CATALOG))
def test_every_provider_uses_existing_adapter_and_declares_actual_media(provider):
    from providers.probe_contracts import contract
    assert provider in ADAPTER_CLASSES
    adapter = create_adapter(provider)
    assert isinstance(adapter.session, AdapterSession)
    assert contract(provider).media_types == PROVIDER_CATALOG[provider].media_types
    for media in contract(provider).media_types:
        assert callable(getattr(adapter, "browse" if media == "anime" else "list_movies" if media == "movies" else "list_series"))
    close = getattr(adapter.session, "close", None)
    if close:
        close()


@pytest.mark.parametrize("bad", [{"python": "exec()"}, {"title_selector": "script"}, {"title_selector": "h1:has(a)"}, {"domain": "127.0.0.1"}, {"domain": "huhu.to"}, {"domain": "https://example.test/?token=secret"}])
def test_repair_profiles_reject_unbounded_or_unsafe_parameters(bad):
    with pytest.raises(ValueError):
        validate_profile("filmpalast", bad)


def test_store_history_is_bounded_atomic_and_survives_restart(tmp_path):
    store = ProviderMonitorStore(tmp_path / "state.json")
    for _ in range(MAX_HISTORY + 10):
        store.record("huhu", {"event": "probe"})
    assert len(ProviderMonitorStore(store.path).entry("huhu")["history"]) == MAX_HISTORY
    assert not list(tmp_path.glob("*.tmp"))


def test_independent_failures_isolate_and_full_success_recovers(tmp_path):
    healthy = {"steps": [{"name": "metadata", "sample": str(i), "ok": True, "code": "ok", "duration_ms": 1} for i in range(3)], "details": [{"identity": str(i), "source": str(i), "title": str(i), "media_type": "movies", "ok": True} for i in range(3)], "responses": [], "canaries": []}
    broken = copy.deepcopy(healthy)
    for step in broken["steps"]:
        step.update(ok=False, code="identity_mismatch")
    for detail in broken["details"]:
        detail["ok"] = False
    result = [broken]
    health = ProviderHealth(tmp_path / "health.json")
    probe = SimpleNamespace(run=lambda *_args: result[0])
    monitor = ProviderMonitor(tmp_path / "state.json", health, lambda: ["huhu"], probe=probe)
    monitor.check("huhu")
    assert health.request_allowed("huhu")
    monitor.check("huhu")
    assert not health.request_allowed("huhu")
    result[0] = healthy
    monitor.check("huhu")
    assert health.request_allowed("huhu")
    assert identity("https://filmpalast.to/stream/title") == identity("title")
    monitor.stop()


@pytest.mark.parametrize("provider", sorted(PROVIDER_CATALOG))
def test_every_adapter_empty_fixture_is_bounded_and_classified(provider):
    class EmptyResponse:
        text, content, status_code, headers = "{}", b"{}", 200, {}
        def __init__(self, url):
            self.url = url
        def json(self):
            return {}
        def raise_for_status(self):
            pass
    class Transport:
        headers = {}
        def __init__(self):
            self.calls = 0
        def get(self, url, **_options):
            self.calls += 1
            return EmptyResponse(url)
        post = get
        def close(self):
            pass
    transport = Transport()
    if provider in {"filmpalast", "serienstream"}:
        transport._curl = transport
    def factory(key):
        adapter = create_adapter(key)
        adapter.session = AdapterSession(key, transport)
        return adapter
    result = ProviderProbe(factory).run(provider, "light")
    assert result["steps"][0]["name"] == "connectivity"
    assert any(step["name"] == "catalog" and step["ok"] is False for step in result["steps"])
    assert diagnose(result) != "healthy"
    assert transport.calls <= 32


def test_three_independent_real_failures_rollback_once(tmp_path):
    store_path = tmp_path / "state.json"
    monitor = ProviderMonitor(store_path, ProviderHealth(tmp_path / "health.json"), lambda: ["filmpalast"])
    candidate = {"id": "test", "profile": {"title_selector": "h1.media-heading"}, "previous_profile": {}, "state": "available", "confidence": "high", "validation": {"shadow_passed": True}}
    monitor.store.add_repair("filmpalast", candidate)
    monitor.repairs.activate("filmpalast", "test")
    for _ in range(5):
        monitor.observe("filmpalast", False, .1, "same-title")
    assert monitor.store.entry("filmpalast")["active_repair"] == "test"
    for source in ("other-title", "third-title"):
        monitor.observe("filmpalast", False, .1, source)
    assert monitor.profile("filmpalast") == {}
    assert monitor.store.entry("filmpalast")["active_repair"] is None
    assert len([event for event in monitor.store.entry("filmpalast")["history"] if event["event"] == "repair_rolled_back"]) == 1
    monitor.stop()


def test_scheduler_budget_deduplication_and_config_validation(tmp_path):
    import threading
    started, release = threading.Event(), threading.Event()
    def run(*_args):
        started.set()
        release.wait(2)
        return {"steps": [], "details": [], "responses": [], "canaries": []}
    monitor = ProviderMonitor(tmp_path / "state.json", ProviderHealth(tmp_path / "health.json"), lambda: ["huhu"], probe=SimpleNamespace(run=run))
    try:
        assert monitor.request("huhu")
        assert started.wait(1)
        assert not monitor.request("huhu")
        assert monitor.request("megakino")
        assert not monitor.request("kinoger")
        monitor._schedule("huhu")
        monitor._schedule("megakino")
        assert monitor.store.entry("huhu")["next_check_at"] != monitor.store.entry("megakino")["next_check_at"]
        with pytest.raises(ValueError):
            monitor.configure({"interval_hours": 0})
    finally:
        monitor.stop()
        release.set()
        monitor.pool.shutdown(wait=True)
    assert not monitor.store.entry("huhu").get("last_check_at")


def test_legacy_recovery_owner_can_probe_without_releasing_quarantine(monkeypatch):
    from providers import sentinel_runtime
    runtime = sentinel_runtime._runtime
    monkeypatch.setattr(sentinel_runtime, "_runtime", SimpleNamespace(allowed=lambda _p: False, profile=lambda _p: {}))
    class Transport:
        def get(self, url, **_options):
            return url
    session = AdapterSession("serienstream", Transport())
    with pytest.raises(ProbeFailure, match="provider_cooldown"):
        session.get("https://serienstream.to/")
    with sentinel_runtime.runtime_recovery("serienstream"):
        assert session.get("https://serienstream.to/")
    with pytest.raises(ProbeFailure):
        session.get("https://serienstream.to/")
    monkeypatch.setattr(sentinel_runtime, "_runtime", runtime)


def test_api_requires_admin_and_explicit_rollback_confirmation(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.api_provider_monitor_router import create_provider_monitor_router
    role = ["member"]
    monitor = ProviderMonitor(tmp_path / "state.json", ProviderHealth(tmp_path / "health.json"), lambda: ["huhu"])
    app = FastAPI()
    app.include_router(create_provider_monitor_router(monitor, lambda *_args: {"role": role[0]}))
    client = TestClient(app)
    for prefix in ("/api/providers", "/api/v1/providers"):
        assert client.get(f"{prefix}/diagnostics").status_code == 403
        assert client.post(f"{prefix}/huhu/probe", json={}).status_code == 403
    role[0] = "admin"
    assert client.get("/api/providers/diagnostics").status_code == 200
    assert client.get("/api/providers/unknown/diagnostics").status_code == 404
    assert client.post("/api/providers/huhu/repairs/test/rollback", json={"confirmed": False}).status_code == 400
    assert client.put("/api/providers/monitor/config", json={"interval_hours": 0}).status_code == 422
    monitor.stop()


def test_megakino_real_parser_recovers_moved_catalog_json_path(monkeypatch, tmp_path):
    from providers.megakino import MegaKinoScraper
    monkeypatch.setattr("application_services.provider_probe.contract", lambda p: ProbeContract(p, ("movies",), False, ()))
    rows = [{"_id": f"{i:024x}", "title": f"Canary {i}", "type": "movies", "year": "2026", "streams": [{"stream": f"https://voe.example/e/{i}"}]} for i in range(5)]
    class Response:
        status_code = 200
        def __init__(self, url, data):
            self.url, self.data, self.text = url, data, json.dumps(data)
        def json(self):
            return self.data
        def raise_for_status(self):
            pass
    class Transport:
        changed = False
        def get(self, url, params=None, **_options):
            if "/data/browse/" in url:
                data = {"payload": {"items": rows}} if self.changed else {"movies": rows}
            elif "/data/search/" in url:
                data = rows
            elif "/data/watch/" in url:
                data = next(item for item in rows if item["_id"] == params["_id"])
            else:
                data = {}
            return Response(url, data)
        def close(self):
            pass
    transport = Transport()
    def factory(_provider):
        adapter = MegaKinoScraper.__new__(MegaKinoScraper)
        adapter._log = lambda _message: None
        adapter.session = AdapterSession("megakino", transport)
        return adapter
    probe = ProviderProbe(factory)
    baseline = probe.run("megakino", "full")
    assert diagnose(baseline) == "healthy"
    transport.changed = True
    broken = probe.run("megakino", "full", canaries=baseline["canaries"])
    repair = ProviderRepair(ProviderMonitorStore(tmp_path / "state.json"), probe)
    candidates = repair.propose("megakino", broken, baseline["canaries"])
    assert candidates[0]["profile"] == {"catalog_json_path": ["payload", "items"]}
    assert candidates[0]["confidence"] == "high"


@pytest.mark.parametrize("mutation", ["wrapper", "order", "optional", "poster-attribute", "absolute-url"])
def test_real_adapter_harmless_layout_mutations(monkeypatch, mutation):
    transport = FixtureSession()
    original = transport.get
    def mutated(url, **options):
        result = original(url, **options)
        if mutation == "wrapper":
            result.text = result.text.replace("<body>", "<body><main>").replace("</body>", "</main></body>")
        elif mutation == "order":
            result.text = result.text.replace('<span id="release_text">', '<div><span id="release_text">').replace('GERMAN.HD</span>', 'GERMAN.HD</span></div>')
        elif mutation == "optional":
            result.text = result.text.replace('<span id="release_text">', '<span>')
        elif mutation == "poster-attribute":
            result.text = result.text.replace('src="/files/movies/', 'data-src="/files/movies/')
        elif mutation == "absolute-url":
            result.text = result.text.replace('href="/stream/', 'href="https://filmpalast.to/stream/')
        return result
    transport.get = mutated
    result = real_probe(monkeypatch, transport).run("filmpalast", "full")
    assert diagnose(result) == "healthy"
    assert len(result["details"]) == 5


def test_observation_failure_never_changes_real_adapter_result_or_error(monkeypatch):
    from providers import sentinel_runtime
    def broken_observer(*_args):
        raise OSError("secret must not be exposed")
    monkeypatch.setattr(sentinel_runtime, "_runtime", SimpleNamespace(observe=broken_observer))
    @sentinel_runtime.monitor_adapter("filmpalast")
    class Adapter:
        def __init__(self):
            self.session = FixtureSession()
        def get_movie(self, source):
            if source == "failure":
                raise ValueError("original parser failure")
            return {"title": "original"}
    adapter = Adapter()
    assert adapter.get_movie("success") == {"title": "original"}
    with pytest.raises(ValueError, match="original parser failure"):
        adapter.get_movie("failure")


def test_failed_atomic_write_cannot_activate_runtime_profile(monkeypatch, tmp_path):
    store = ProviderMonitorStore(tmp_path / "state.json")
    repair = ProviderRepair(store, None)
    candidate = {"id": "test", "profile": {"title_selector": "h1.heading"}, "previous_profile": {}, "state": "available", "confidence": "high", "validation": {"shadow_passed": True}}
    store.add_repair("filmpalast", candidate)
    def unavailable():
        raise OSError("disk unavailable")
    monkeypatch.setattr(store, "_write", unavailable)
    with pytest.raises(OSError):
        repair.activate("filmpalast", "test")
    assert repair.profile("filmpalast") == {}
    assert not store.entry("filmpalast").get("active_repair")
    assert store.entry("filmpalast")["repairs"][0]["state"] == "available"


def test_caught_catalog_rate_limit_remains_rate_limit(monkeypatch):
    transport = FixtureSession()
    original = transport.get
    def throttled(url, **options):
        response = original(url, **options)
        if "/search/" in url or "/movies/" in url or url.endswith("/page/1/"):
            response.status_code = 429
        return response
    transport.get = throttled
    # The production adapter deliberately catches catalog exceptions.
    probe = real_probe(monkeypatch, transport)
    with probe_context("filmpalast") as context:
        session = AdapterSession("filmpalast", transport)
        with pytest.raises(ProbeFailure):
            session.get("https://filmpalast.to/movies/")
        assert context.failures == [("rate_limit", 429)]
    result = probe.run("filmpalast", "full")
    assert any(step["code"] == "rate_limit" for step in result["steps"])
    assert diagnose(result) == "degraded"


@pytest.mark.parametrize("mutation", ["missing-hosters", "wrong-cover", "ambiguous-title"])
def test_shadow_rejects_regression_or_ambiguous_recovery(monkeypatch, tmp_path, mutation):
    transport = FixtureSession()
    probe = real_probe(monkeypatch, transport)
    baseline = probe.run("filmpalast", "full")
    original = transport.get
    def changed(url, **options):
        response = original(url, **options)
        if "/stream/" in url:
            response.text = response.text.replace('h2 class="bgDark"', 'h1 class="heading"').replace('</h2><img', '</h1><img')
            if mutation == "missing-hosters":
                response.text = response.text.replace('class="currentStreamLinks"', 'class="missing"')
            elif mutation == "wrong-cover":
                response.text = response.text.replace('/files/movies/', '/different/')
            else:
                response.text = response.text.replace('</h1>', '</h1><h2 class="duplicate">Canary ' + url.rsplit('-', 1)[1] + '</h2>')
        return response
    transport.get = changed
    current = probe.run("filmpalast", "full", canaries=baseline["details"])
    repair = ProviderRepair(ProviderMonitorStore(tmp_path / "state.json"), probe)
    assert not any(candidate["confidence"] == "high" for candidate in repair.propose("filmpalast", current, baseline["details"]))


def test_domain_repair_requires_catalogued_https_origin():
    from application_services.provider_repair import discover_candidates
    from providers.sentinel_runtime import safe_url
    assert safe_url("https://user:secret@example.com/") == ""
    assert safe_url("https://example.com:8443/") == ""
    result = {"steps": [], "responses": [{"origin": "https://unrelated.example/", "final_origin": "https://new.example/", "status": 200, "url": "https://unrelated.example/", "text": ""}]}
    assert discover_candidates("filmpalast", result, []) == []


def test_full_anime_checks_use_existing_track_episode_contracts():
    from application_services.provider_probe import episode_source
    from providers.aniworld import AniWorldAnime, AniWorldEpisode
    from providers.mkissa import MkissaAnime
    from providers.models import parse_episode_slug
    ani = AniWorldAnime(id="canary-anime", title="Canary", episodes=[AniWorldEpisode(season=2, number=3, tracks=("dub",))])
    mk = MkissaAnime(id="canary123", title="Canary", translations={"sub": 12})
    assert parse_episode_slug(episode_source("aniworld", ani)) == ("aniworld:canary-anime|dub", 2, 3)
    assert parse_episode_slug(episode_source("mkissa", mk)) == ("mkissa:canary123|sub", 1, 1)


def test_poster_attribute_repair_preserves_known_artwork(monkeypatch, tmp_path):
    transport = FixtureSession()
    probe = real_probe(monkeypatch, transport)
    baseline = probe.run("filmpalast", "full")
    original = transport.get
    def changed(url, **options):
        response = original(url, **options)
        if "/stream/" in url:
            response.text = response.text.replace('class="cover2" src=', 'class="new-poster" data-original=')
        return response
    transport.get = changed
    current = probe.run("filmpalast", "full", canaries=baseline["details"])
    repair = ProviderRepair(ProviderMonitorStore(tmp_path / "state.json"), probe)
    candidates = repair.propose("filmpalast", current, baseline["details"])
    assert candidates[0]["profile"] == {"poster_selector": "img.new-poster"}
    assert candidates[0]["confidence"] == "high"


def test_runtime_domain_override_retains_public_network_boundary(monkeypatch):
    from providers import sentinel_runtime
    monkeypatch.setattr(sentinel_runtime, "_runtime", SimpleNamespace(allowed=lambda _p: True, profile=lambda _p: {"domain": "new.example"}))
    seen = []
    class Transport:
        def get(self, url, **options):
            seen.append((url, options))
            return "result"
    session = AdapterSession("huhu", Transport())
    assert session.get("https://huhu.to/path?query=value") == "result"
    assert seen[0][0] == "https://new.example/path?query=value"
    assert seen[0][1]["verify"] is True
    assert seen[0][1]["proxies"]["https"].startswith("http://127.0.0.1:")


def test_http_200_login_wall_is_verification_not_parser_repair(monkeypatch):
    transport = FixtureSession()
    closed = []
    transport.close = lambda: closed.append(True)
    transport.get = lambda url, **_options: SimpleNamespace(text='<html><title>Login required</title><form><input type="password"></form></html>', status_code=200, url=url)
    result = real_probe(monkeypatch, transport).run("filmpalast", "full")
    assert diagnose(result) == "blocked"
    assert len(result["steps"]) == 1
    assert closed == [True]


@pytest.mark.parametrize("url", ["http:", "https://user:secret@host.example/", "https://host.example:8443/", "http://127.0.0.1/", "http://[::1]/", "https://nas.local/", "https://[invalid/", "javascript:alert(1)"])
def test_invalid_or_private_hoster_links_never_pass_probe_structure(url):
    from application_services.provider_probe import valid_source_link
    assert not valid_source_link(url)
    assert valid_source_link("https://voe.example/e/canary")


def test_manual_revalidation_replaces_stale_high_confidence_evidence(tmp_path):
    result = {"steps": [], "responses": [], "canaries": [], "details": [{"identity": str(i), "source": str(i), "title": str(i), "media_type": "movies", "ok": True} for i in range(3)]}
    monitor = ProviderMonitor(tmp_path / "state.json", ProviderHealth(tmp_path / "health.json"), lambda: ["filmpalast"], probe=SimpleNamespace(run=lambda *_args: result))
    repair = {"id": "stale", "profile": {"title_selector": "h1.heading"}, "previous_profile": {}, "confidence": "high", "state": "available", "validation": {"shadow_passed": True}}
    monitor.store.add_repair("filmpalast", repair)
    monitor.store.update("filmpalast", requested_repair="stale", canaries=result["details"])
    monitor.check("filmpalast", "full")
    entry = monitor.store.entry("filmpalast")
    assert not entry.get("active_repair")
    assert entry["diagnosis"] == "needs_attention"
    assert entry["repairs"][0]["confidence"] == "low"
    assert not entry["repairs"][0]["validation"]["shadow_passed"]
    monitor.stop()
