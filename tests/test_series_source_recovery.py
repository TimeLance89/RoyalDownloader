import threading
from types import SimpleNamespace

import pytest
import server  # noqa: F401
from application_services import series_catalog as catalog
from media.provider_health import ProviderHealth


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    now = [1000.0]
    health = ProviderHealth(tmp_path / "health.json", initial_cooldown=60, clock=lambda: now[0])
    health.mark_blocked("serienstream", "probe_failed")
    calls = []
    def record(value, result):
        from providers import sentinel_runtime
        if health.status("serienstream")["state"] == "probing":
            assert sentinel_runtime._recovery.get() == "serienstream"
        calls.append(value)
        return result
    scraper = SimpleNamespace(
        _catalog_cache=["old"], _browse_catalog_cache=["old"], _beliebte_cache=["old"],
        get_series=lambda value: record(value, "series"),
        search_series=lambda value: record(value, ["match"]),
        list_series_catalog=lambda page: record(page, ["catalog"]),
    )
    monkeypatch.setattr(catalog, "state", SimpleNamespace(provider_health=health, sto_lock=threading.Lock()))
    monkeypatch.setattr(catalog, "get_sto_scraper", lambda: scraper)
    return health, now, calls, scraper


@pytest.mark.parametrize("operation", [
    lambda: catalog._sto_get_series("show"),
    lambda: catalog._sto_search_series("Show"),
    lambda: catalog._fetch_series_provider_page("serienstream", "discover", "", 1),
])
def test_due_cooldown_recovers_detail_search_and_catalog(recovery, operation):
    health, now, calls, scraper = recovery
    with pytest.raises(RuntimeError, match="Cooldown"):
        operation()
    assert calls == []
    now[0] += 61
    assert operation()
    assert health.request_allowed("serienstream")
    assert len(calls) == 1
    assert scraper._catalog_cache is None
    assert scraper._browse_catalog_cache is None


def test_only_one_reader_can_own_recovery(recovery):
    health, now, calls, _ = recovery
    now[0] += 61
    assert health.begin_probe("serienstream")
    with pytest.raises(RuntimeError, match="Cooldown"):
        catalog._sto_get_series("show")
    assert calls == []


def test_manual_probe_reaches_transport_with_recovery_ownership(recovery, monkeypatch):
    from application_services import download_lifecycle as lifecycle
    from providers import sentinel_runtime
    health, now, _, _ = recovery
    now[0] += 61
    assert health.begin_probe("serienstream")
    calls = []
    def get(url, **kwargs):
        assert sentinel_runtime._recovery.get() == "serienstream"
        calls.append(url)
        return "<html>source is available</html>"
    scraper = SimpleNamespace(reset_gate=lambda: None, session=SimpleNamespace(get=get))
    monkeypatch.setattr(lifecycle, "state", SimpleNamespace(
        sto_lock=threading.Lock(), queue_prepare_lock=threading.Lock(), provider_health=health))
    monkeypatch.setattr(lifecycle, "get_sto_scraper", lambda: scraper)
    monkeypatch.setattr(lifecycle, "log", lambda *args: None)
    monkeypatch.setattr(lifecycle, "broadcast", lambda *args: None)
    monkeypatch.setattr(lifecycle, "serienstream_provider_status", lambda: {})
    monkeypatch.setattr(lifecycle, "_resume_waiting_provider_jobs", lambda *args: None)
    lifecycle._execute_provider_probe(None)
    assert len(calls) == 1
    assert health.request_allowed("serienstream")
    assert sentinel_runtime._recovery.get() is None


@pytest.mark.parametrize("fail", [False, True])
def test_empty_or_failed_recovery_restarts_cooldown(recovery, fail):
    health, now, calls, scraper = recovery
    now[0] += 61
    def read(_):
        if fail:
            raise OSError("source unavailable")
        return None
    scraper.get_series = read
    if fail:
        with pytest.raises(OSError):
            catalog._sto_get_series("show")
    else:
        assert catalog._sto_get_series("show") is None
    assert health.status("serienstream")["state"] == "cooldown"
    assert health.next_probe_at("serienstream") > now[0]
    with pytest.raises(RuntimeError, match="Cooldown"):
        catalog._sto_get_series("show")


def test_a_real_block_during_recovery_is_not_cleared(recovery, monkeypatch):
    from media.session_manager import ProviderBlockedError
    health, now, _, scraper = recovery
    now[0] += 61
    def blocked(_):
        raise ProviderBlockedError("captcha_gate", 403)
    scraper.get_series = blocked
    monkeypatch.setattr(catalog, "_mark_serienstream_blocked",
                        lambda reason, message: health.mark_blocked("serienstream", reason, message))
    with pytest.raises(ProviderBlockedError):
        catalog._sto_get_series("show")
    assert health.status("serienstream")["state"] == "cooldown"
    assert health.status("serienstream")["reason"] == "captcha_gate"
