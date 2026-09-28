"""Offline hoster contracts, mutations, attribution, repair and runtime safety."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from application_services.provider_monitor import ProviderMonitor
from application_services.hoster_monitor import health, metrics, canary_identity, media_identity, MAX_CANARIES
from application_services.hoster_probe import HosterProbe, HosterProbeError
from media.provider_health import ProviderHealth
from media.provider_monitor_store import ProviderMonitorStore, HosterStore
from media.hoster_contracts import CONTRACTS, hoster_key
from media.hoster_profiles import discover_profiles, extract_profile, validate_profile
from media.hoster_intel import HosterIntel


def monitor(tmp_path):
    return ProviderMonitor(tmp_path / "sentinel.json", ProviderHealth(tmp_path / "health.json"), lambda: ["filmpalast"], clock=lambda: 1_000_000)


def player(index, mutation="json"):
    url = f"https://media.example/video-{index}.m3u8?expires=secret"
    if mutation == "attribute":
        return f'<video id="player" data-stream="{url}"></video>'
    if mutation == "relative":
        url = f"/video-{index}.m3u8"
    return '<script id="config" type="application/json">' + json.dumps({"player": {"config": {"sources": [{"url": url}]}}}) + '</script>'


class FixtureProbe:
    def __init__(self, mutation="json"):
        self.mutation = mutation

    def run(self, hoster, intensity="standard", profile=None, canaries=()):
        details, responses = [], []
        for row in canaries:
            index = row["url"].rsplit("/", 1)[1].split("?")[0]
            text = player(index, self.mutation)
            result = extract_profile(text, row["url"], profile) if profile else None
            details.append({"identity": row["identity"], "ok": bool(result), "code": "ok" if result else "parser_error", "duration_ms": 10, "media_signature": media_identity(result[0]) if result else ""})
            responses.append({"identity": row["identity"], "url": row["url"], "text": text})
        return {"details": details, "responses": responses, "steps": []}


def seed(owner, count=5, proven=True):
    for index in range(count):
        owner.hosters.seed("voe", f"https://voe.example/{index}", "filmpalast", proven=proven, media_signature=media_identity(f"https://media.example/video-{index}.m3u8"))


def test_store_namespace_and_restart(tmp_path):
    store = ProviderMonitorStore(tmp_path / "state.json")
    hosters = HosterStore(store)
    store.update("voe", diagnosis="provider")
    hosters.update("voe", diagnosis="healthy")
    assert store.entry("voe")["diagnosis"] == "provider"
    restored = ProviderMonitorStore(store.path)
    assert HosterStore(restored).entry("voe")["diagnosis"] == "healthy"
    assert restored.config() == store.config()


def test_passive_metrics_health_ranking_and_privacy(tmp_path):
    owner = monitor(tmp_path)
    intel = HosterIntel(tmp_path / "intel.json")
    intel.health_penalty = owner.hosters.penalty
    for index in range(6):
        owner.hosters.observe("VOE", f"https://voe.example/{index}?token=SUPERSECRET", False, 100 + index, "filmpalast", "parser error with SUPERSECRET")
    entry = owner.hosters.store.entry("voe")
    assert entry["diagnosis"] == "broken"
    assert owner.health.request_allowed("filmpalast")
    metric = owner.hosters.diagnostics()
    voe = next(row for row in metric if row["hoster"] == "voe")
    assert voe["metrics_24h"]["attempts"] == 6
    assert voe["metrics_24h"]["median_resolve_ms"] == 102.5
    assert "SUPERSECRET" not in owner.store.path.read_text()
    assert "/0" not in owner.store.path.read_text()
    candidates = [SimpleNamespace(name="VOE", url="https://voe.example/embed"), SimpleNamespace(name="Vidoza", url="https://vidoza.example/embed")]
    assert intel.rank(candidates)[0].name == "Vidoza"
    intel.health_penalty = lambda *_: 1 / 0
    assert intel.rank(candidates)  # Fail-open monitoring.


def test_independent_evidence_and_expiry(tmp_path):
    owner = monitor(tmp_path)
    for index in range(8):
        owner.hosters.observe("voe", f"https://voe.example/same?token={index}", False, message="parser error")
    assert owner.hosters.store.entry("voe")["diagnosis"] == "degraded"
    seed(owner, 12)
    assert len(owner.hosters.candidates("voe")) == MAX_CANARIES
    assert canary_identity("https://voe.example/a?t=1") == canary_identity("https://voe.example/a?t=2")
    owner.hosters.clock = lambda: 2_000_000
    assert owner.hosters.candidates("voe") == []
    assert monitor(tmp_path).hosters.candidates("voe") == []


@pytest.mark.parametrize("mutation", ["json", "attribute", "relative"])
def test_player_mutations(mutation):
    text = player(1, mutation)
    profiles = discover_profiles(text, "https://media.example/embed")
    assert len(profiles) == 1
    assert extract_profile(text, "https://media.example/embed", profiles[0])[1] == "hls"


@pytest.mark.parametrize("profile", [{"code": "eval()"}, {"player_selector": "script:has(*)"}, {"player_json_path": ["__x", -1]}, {"player_attribute": "onclick"}, {"media_kind": "drm"}])
def test_no_executable_profiles(profile):
    with pytest.raises(ValueError):
        validate_profile("voe", profile)


def test_shadow_auto_activation_and_runtime_rollback(tmp_path):
    owner = monitor(tmp_path)
    owner.hosters.probe = owner.hosters.repairs.probe = FixtureProbe()
    seed(owner)
    owner.hosters.check("voe", "full")
    entry = owner.hosters.store.entry("voe")
    assert entry["active_repair"]
    repair = entry["repairs"][0]
    assert repair["confidence"] == "high"
    assert repair["validation"]["identity_preserved"]
    assert repair["validation"]["validated_detail_pages"] == 5
    assert owner.store.entry("filmpalast").get("profile") is None
    for index in range(5):
        owner.hosters.observe("voe", f"https://voe.example/{index}", False, 100, "filmpalast", "parser error")
    entry = owner.hosters.store.entry("voe")
    assert entry["active_repair"] is None
    assert entry["profile"] == {}
    assert entry["diagnosis"] == "needs_attention"
    assert entry["history"][-1]["event"] == "repair_rolled_back"


@pytest.mark.parametrize("count,proven", [(1, True), (3, True), (5, False)])
def test_insufficient_or_unknown_canaries_never_auto_activate(tmp_path, count, proven):
    owner = monitor(tmp_path)
    owner.hosters.probe = owner.hosters.repairs.probe = FixtureProbe()
    seed(owner, count, proven)
    owner.hosters.check("voe", "full")
    assert not owner.hosters.store.entry("voe").get("active_repair")


def test_media_identity_change_rejected(tmp_path):
    owner = monitor(tmp_path)
    seed(owner)
    probe = FixtureProbe()
    owner.hosters.repairs.probe = probe
    refs = owner.hosters.candidates("voe")
    for row in refs:
        row["media_signature"] = media_identity("https://foreign.example/ad.m3u8")
    current = probe.run("voe", "full", {}, refs)
    proposals = owner.hosters.repairs.propose("voe", current, refs)
    assert proposals and proposals[0]["confidence"] == "low"


def test_ambiguous_profiles_and_protection_do_not_activate(tmp_path):
    owner = monitor(tmp_path)
    seed(owner)
    refs = owner.hosters.candidates("voe")
    current = FixtureProbe().run("voe", "full", {}, refs)
    for row in current["details"]:
        row["code"] = "blocked"
    assert owner.hosters.repairs.propose("voe", current, refs) == []
    assert extract_profile(player(1) + "<div>cf-turnstile</div>", "https://voe.example/1", discover_profiles(player(1), "https://voe.example/1")[0]) is None


def test_shared_scheduler_budget_and_shutdown(tmp_path):
    owner = monitor(tmp_path)
    owner.active.update({"filmpalast", "megakino"})
    assert not owner.request("hoster:voe")
    owner.stop()
    assert not owner.request("hoster:voe")
    assert owner.hosters.store.entry("voe") == {}


def test_contract_inventory_and_aliases():
    assert {"voe", "vidara", "streamtape", "filemoon", "firestream", "filmfrei24"} <= CONTRACTS.keys()
    assert hoster_key("FSST", "https://incvideo.example/e/a") == "kinoger"
    assert hoster_key("VOE", "https://mirror.example/a") == "voe"
    assert CONTRACTS["vidara"].resolver == "extract_vidara_url"
    assert "embed" not in CONTRACTS["filmfrei24"].capabilities


def test_attempt_event_does_not_invent_completed_success(tmp_path):
    owner = monitor(tmp_path)
    owner.hosters.begin("VOE", "https://voe.example/known?token=secret", "filmpalast")
    entry = owner.hosters.store.entry("voe")
    assert entry["history"][-1]["event"] == "resolve_attempt"
    assert entry.get("samples", []) == []
    assert not owner.hosters.candidates("voe")[0]["proven"]
    assert "token=secret" not in owner.store.path.read_text()


@pytest.mark.parametrize("code,state", [("parser_error", "broken"), ("network_error", "offline"), ("blocked", "blocked"), ("resolve_success", "healthy"), ("removed", "unknown")])
def test_health_contract(code, state):
    rows = [{"identity": str(index), "code": code} for index in range(6)]
    assert health(rows) == state


def test_no_future_or_old_samples():
    assert metrics([{ "timestamp": 1, "code": "resolve_success", "duration_ms": 4}], 200000)["attempts"] == 0


class FixtureSession:
    def __init__(self, filename, code=None, redirect=None):
        self.filename, self.code, self.redirect = filename, code, redirect
        self.responses, self.errors, self.calls = [], [], []

    def get(self, url, **_options):
        self.calls.append(url)
        if self.code:
            self.errors.append(self.code)
            raise HosterProbeError(self.code)
        text = (Path(__file__).parent / "fixtures" / "hoster-sentinel" / self.filename).read_text()
        response = SimpleNamespace(text=text, url=self.redirect or url, status_code=200, headers={})
        self.responses.append(response)
        return response

    def close(self):
        pass


def test_production_resolver_changed_json_shadow(tmp_path, monkeypatch):
    import media.extractor as extractor
    import application_services.hoster_probe as probe_module
    monkeypatch.setattr(extractor, "ensure_public_http_url", lambda _: None)
    monkeypatch.setattr(extractor, "request_proxy_kwargs", lambda _: {})
    monkeypatch.setattr(probe_module, "ensure_public_http_url", lambda _: None)
    canary = {"url": "https://voe.example/0", "identity": "known", "proven": True, "media_signature": media_identity("https://media.example/video-0.m3u8")}
    normal = HosterProbe(lambda: FixtureSession("normal.html"))
    assert normal.run("voe", "full", {}, [canary])["details"][0]["ok"]
    changed = HosterProbe(lambda: FixtureSession("changed-player.html"))
    current = changed.run("voe", "full", {}, [canary])
    assert not current["details"][0]["ok"]
    candidate = discover_profiles(current["responses"][0]["text"], canary["url"])[0]
    repaired = changed.run("voe", "full", candidate, [canary])
    assert repaired["details"][0]["ok"]
    assert repaired["details"][0]["media_signature"] == canary["media_signature"]


@pytest.mark.parametrize("filename,code", [("missing-media.html", None), ("invalid-media.html", None), ("blocked.html", "blocked"), ("normal.html", "rate_limit"), ("normal.html", "timeout")])
def test_real_probe_failures_stay_technical(filename, code, monkeypatch):
    import media.extractor as extractor
    import application_services.hoster_probe as probe_module
    monkeypatch.setattr(extractor, "ensure_public_http_url", lambda _: None)
    monkeypatch.setattr(extractor, "request_proxy_kwargs", lambda _: {})
    monkeypatch.setattr(probe_module, "ensure_public_http_url", lambda _: None)
    session = FixtureSession(filename, code)
    probe = HosterProbe(lambda: session)
    result = probe.run("voe", "full", {}, [{"url": "https://voe.example/0", "identity": "known"}])
    assert not result["details"][0]["ok"]
    if code:
        assert result["details"][0]["code"] == code
    assert all("url" not in step and "text" not in step for step in result["steps"])


def test_domain_redirect_identity_and_shadow(tmp_path):
    owner = monitor(tmp_path)
    seed(owner)
    refs = owner.hosters.candidates("voe")
    class RedirectProbe(FixtureProbe):
        def run(self, hoster, intensity="standard", profile=None, canaries=()):
            result = super().run(hoster, intensity, profile, canaries)
            for row in result["responses"]:
                row["original_url"] = row["url"]
                row["url"] = row["url"].replace("voe.example", "new-embed.example")
            return result
    probe = RedirectProbe()
    owner.hosters.repairs.probe = probe
    current = probe.run("voe", "full", {}, refs)
    proposals = owner.hosters.repairs.propose("voe", current, refs)
    assert proposals[0]["profile"]["embed_domain"] == "new-embed.example"
    assert proposals[0]["confidence"] == "high"
    for row in refs:
        row["media_signature"] = "not-the-same-media"
    proposals = owner.hosters.repairs.propose("voe", current, refs)
    assert proposals[0]["confidence"] == "low"


def test_admin_hoster_routes_share_auth_and_confirmation(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.api_provider_monitor_router import create_provider_monitor_router
    owner = monitor(tmp_path)
    role = ["viewer"]
    app = FastAPI()
    app.include_router(create_provider_monitor_router(owner, lambda *_: {"role": role[0]}))
    with TestClient(app) as client:
        assert client.get("/api/hosters/diagnostics").status_code == 403
        assert client.post("/api/hosters/voe/probe", json={}).status_code == 403
        role[0] = "admin"
        assert client.get("/api/v1/hosters/diagnostics").status_code == 200
        assert client.get("/api/hosters/nonexistent/diagnostics").status_code == 404
        assert client.post("/api/hosters/voe/repairs/missing/rollback", json={}).status_code == 400
        assert client.post("/api/hosters/voe/repairs/missing/activate", json={"confirmed": True}).status_code == 409
        owner.active.update({"filmpalast", "megakino"})
        assert client.post("/api/v1/hosters/voe/probe", json={"intensity": "full"}).status_code == 429


def test_transport_budget_binary_and_redirect_boundaries(monkeypatch):
    import application_services.hoster_probe as module
    from core.source_urls import valid_source_link
    def guard(url):
        if not valid_source_link(url):
            raise HosterProbeError("media_invalid")
    monkeypatch.setattr(module, "ensure_public_http_url", guard)
    monkeypatch.setattr(module, "request_proxy_kwargs", lambda _: {})
    session = module.ProbeSession()
    calls, closed = [], []
    response = SimpleNamespace(status_code=200, headers={"Content-Type": "video/mp4"}, iter_content=lambda _: pytest.fail("Binary media must not be consumed"), close=lambda: closed.append(True))
    def request(method, url, **options):
        calls.append((method, url, options))
        return response
    session.transport.request = request
    session.get("https://public.example/video.mp4", verify=False)
    assert calls[-1][2]["verify"] is True
    assert closed == [True]
    for _ in range(11):
        session.get("https://public.example/a")
    with pytest.raises(HosterProbeError, match="budget_exhausted"):
        session.get("https://public.example/a")
    assert len(calls) == 12
    session.close()
    session = module.ProbeSession()
    response.status_code = 307
    response.headers = {"Location": "https://foreign.example/api"}
    session.transport.request = request
    with pytest.raises(HosterProbeError, match="redirect_invalid"):
        session.post("https://public.example/api", data="secret-token")
    assert len(calls) == 13  # No credential-bearing POST to the new domain.
    response.headers = {"Location": "http://127.0.0.1/private"}
    with pytest.raises(HosterProbeError):
        session.get("https://public.example/a")
    assert len(calls) == 14
    session.close()


def test_embed_route_mutation_and_secret_preservation():
    from media.hoster_profiles import profile_url
    profile = {"embed_domain": "new.example", "embed_path_prefix": "/embed/"}
    assert profile_url("https://old.example/e/known?token=ephemeral", profile) == "https://new.example/embed/known?token=ephemeral"
    with pytest.raises(ValueError):
        validate_profile("voe", {"embed_path_prefix": "/../../admin/"})


def test_stopped_generation_never_activates_shadow(tmp_path):
    owner = monitor(tmp_path)
    seed(owner)
    class StopDuringShadow(FixtureProbe):
        def run(self, hoster, intensity="standard", profile=None, canaries=()):
            result = super().run(hoster, intensity, profile, canaries)
            if profile:
                owner.stop()
            return result
    owner.hosters.probe = owner.hosters.repairs.probe = StopDuringShadow()
    owner.hosters.check("voe", "full", generation=owner.generation)
    assert not owner.hosters.store.entry("voe").get("active_repair")
