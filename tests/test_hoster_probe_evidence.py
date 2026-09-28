"""Real HTTP-only probes cannot disprove untested production browser fallbacks."""
from types import SimpleNamespace

import pytest

from application_services.provider_monitor import ProviderMonitor
from application_services.hoster_probe import HosterProbe
from media.hoster_contracts import runtime_contract, BROWSER_EMBED_PROVIDERS
from media.provider_health import ProviderHealth
from providers.catalog import PROVIDER_CATALOG


class BrowserPlayerSession:
    """The HTML is valid; its media is produced only by player JavaScript."""
    def __init__(self):
        self.responses, self.errors = [], []

    def get(self, url, **_options):
        response = SimpleNamespace(text='<html><div id="player"></div><script src="/runtime.js"></script></html>', url=url, status_code=200)
        self.responses.append(response)
        return response

    def post(self, url, **_options):
        response = SimpleNamespace(text="{}", url=url, status_code=200, json=lambda: {})
        self.responses.append(response)
        return response

    def close(self):
        pass


@pytest.fixture
def source(tmp_path, monkeypatch):
    import media.extractor as extractor
    import media.downloader as downloader
    monkeypatch.setattr(extractor, "request_proxy_kwargs", lambda _: {})
    monkeypatch.setattr(downloader, "probe_stream_url", lambda *_args, **_kwargs: (False, "parser error"))
    monkeypatch.setattr(extractor, "VOEBrowserPool", lambda *_args, **_kwargs: pytest.fail("Sentinel must never start a browser"))
    owner = ProviderMonitor(tmp_path / "sentinel.json", ProviderHealth(tmp_path / "health.json"), lambda: list(PROVIDER_CATALOG), clock=lambda: 2_000_000)
    owner.hosters.probe = owner.hosters.repairs.probe = HosterProbe(BrowserPlayerSession)
    return owner


def seed(owner, name, provider="filmpalast"):
    for index in range(5):
        owner.hosters.seed(name, f"https://{name}.example/embed-{index}", provider)


@pytest.mark.parametrize("name", ["voe", "veev", "moflix", "kinoger"])
def test_browser_contract_http_failure_is_inconclusive(source, name):
    seed(source, name)
    source.hosters.check(name, "full")
    entry = source.hosters.store.entry(name)
    assert entry["diagnosis"] == "degraded"
    assert source.hosters.penalty(name) == -20
    assert not entry.get("active_repair")
    assert all(row["code"] == "browser_fallback_required" and not row["probe_complete"] for row in entry["probe_evidence"])
    assert all(step["ok"] is None for step in entry["steps"] if step["name"] in {"player", "resolver", "media_result"})


@pytest.mark.parametrize("name", ["voe", "veev"])
def test_production_success_then_five_http_failures_never_broken(source, name):
    # Production observation: VOE succeeded once (100%) shortly before full check.
    providers = ["filmo", "filmpalast", "huhu", "kinox", "megakino", "serienstream", "xcine"]
    url = f"https://{'voe.sx' if name == 'voe' else 'veev.example'}/known"
    source.hosters.observe(name, url, True, 1300, "filmpalast", media_url="https://cdn.example/known.m3u8")
    for index, provider in enumerate(providers):
        source.hosters.seed(name, f"https://{name}.example/embed-{index}", provider)
    before = next(row for row in source.hosters.diagnostics() if row["hoster"] == name)
    assert before["metrics_24h"]["attempts"] == 1
    assert before["metrics_24h"]["success_rate"] == 1
    source.hosters.check(name, "full")
    after = next(row for row in source.hosters.diagnostics() if row["hoster"] == name)
    assert after["diagnosis"] == "degraded"
    assert after["metrics_24h"]["success_rate"] == 1
    assert source.hosters.penalty(name) > -100
    assert source.health.request_allowed("filmpalast")


def test_complete_http_only_parser_failures_can_still_be_broken(source):
    seed(source, "vidara")
    source.hosters.check("vidara", "full")
    entry = source.hosters.store.entry("vidara")
    assert not runtime_contract("vidara").browser_fallback
    assert all(row["probe_complete"] for row in entry["probe_evidence"])
    assert entry["diagnosis"] == "broken"
    assert source.hosters.penalty("vidara") == -100


def test_independent_real_runtime_failures_remain_authoritative(source):
    seed(source, "voe")
    for index in range(5):
        source.hosters.observe("voe", f"https://voe.example/failed-{index}", False, 1300, "filmpalast", "parser error after production browser")
    source.hosters.check("voe", "full")
    assert source.hosters.store.entry("voe")["diagnosis"] == "broken"
    assert source.hosters.penalty("voe") == -100


@pytest.mark.parametrize("provider", sorted(BROWSER_EMBED_PROVIDERS))
def test_generic_embed_provider_context(source, provider):
    seed(source, "sirius", provider)
    assert runtime_contract("sirius", provider=provider).browser_fallback
    assert not runtime_contract("sirius", provider="filmpalast").browser_fallback
    # Dedicated HTTP extractors precede the generic provider fallback in production.
    assert not runtime_contract("vidara", provider=provider).browser_fallback
    source.hosters.check("sirius", "full")
    assert source.hosters.store.entry("sirius")["diagnosis"] == "degraded"
    assert source.hosters.penalty("sirius") > -100


def test_generic_unknown_provider_cannot_claim_complete_production_probe(source):
    seed(source, "sirius", "")
    source.hosters.check("sirius", "full")
    assert source.hosters.store.entry("sirius")["diagnosis"] == "degraded"
    assert source.hosters.store.entry("sirius")["probe_evidence"][0]["code"] == "runtime_validation_required"


def test_generic_known_http_only_route_can_be_broken(source):
    seed(source, "sirius", "filmpalast")
    source.hosters.check("sirius", "full")
    assert source.hosters.store.entry("sirius")["diagnosis"] == "broken"


def test_mixed_provider_paths_cannot_claim_global_browser_failure(source):
    seed(source, "sirius", "filmpalast")
    source.hosters.seed("sirius", "https://sirius.example/other-provider", "sflix")
    source.hosters.check("sirius", "full")
    assert source.hosters.store.entry("sirius")["diagnosis"] == "degraded"
    assert source.hosters.penalty("sirius") == -20


def test_new_browser_provider_invalidates_cached_http_only_penalty(source):
    seed(source, "sirius", "filmpalast")
    source.hosters.check("sirius", "full")
    assert source.hosters.penalty("sirius") == -100
    source.hosters.seed("sirius", "https://sirius.example/new-context", "sflix")
    assert source.hosters.penalty("sirius") == -20


def test_legacy_cached_false_positive_is_fixed_before_next_probe(source):
    source.hosters.store.update("voe", diagnosis="broken", last_check_at=2_000_000, providers=["filmpalast"],
        samples=[{"timestamp": 2_000_000, "identity": "real", "code": "resolve_success", "duration_ms": 1300}],
        probe_evidence=[{"timestamp": 2_000_000, "identity": str(index), "code": "parser_error", "ok": False} for index in range(5)],
        steps=[{"name": "resolver", "code": "parser_error", "ok": False, "duration_ms": 0}])
    assert source.hosters.penalty("voe") == -20
    diagnostic = next(row for row in source.hosters.diagnostics() if row["hoster"] == "voe")
    assert diagnostic["diagnosis"] == "degraded"
    assert diagnostic["steps"][0]["code"] == "browser_fallback_required"
    assert source.hosters.store.entry("voe").get("profile") is None


def test_only_measured_step_duration_is_published(source):
    seed(source, "voe")
    source.hosters.check("voe", "full")
    steps = source.hosters.store.entry("voe")["steps"]
    assert all(step["duration_ms"] is None for step in steps if step["name"] in {"embed", "redirect", "player", "media_result"})
    assert all(step["duration_ms"] >= 0 for step in steps if step["name"] == "reachability")
