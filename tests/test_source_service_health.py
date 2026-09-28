"""Impact is about usable configured paths, never alarm counts or raw error text."""
from copy import deepcopy

from application_services.source_service_health import source_service_health
from application_services.provider_monitor import ProviderMonitor
from media.provider_health import ProviderHealth

NOW = 2_000_000


def provider(key, media=("movies", "series"), language="de", state="healthy"):
    return {"provider": key, "enabled": True, "contract": {"media_types": media}, "content_language": language,
            "runtime": {"state": "cooldown" if state == "broken" else "healthy"}, "routing": {"allowed": state != "broken"}, "diagnosis": state, "last_check_at": NOW - 60, "last_error_at": 0}


def hoster(key, providers, state="healthy"):
    return {"hoster": key, "providers": providers, "diagnosis": state, "last_check_at": NOW - 60,
            "metrics_24h": {"attempts": 0, "success_rate": None}}


def result(providers, hosters):
    return source_service_health(providers, hosters, NOW)


def test_five_degraded_video_services_with_working_alternatives_are_healthy():
    providers = [provider("one"), provider("two")]
    hosters = [hoster("working", ["one", "two"])] + [hoster(str(i), ["one", "two"], "degraded") for i in range(5)]
    summary = result(providers, hosters)
    assert summary["service_health"] == "healthy"
    assert summary["user_impact"] == "none"
    assert not summary["action_required"]
    assert summary["coverage"]["anime"] == "not_configured"


def test_inconclusive_http_probe_with_real_success_does_not_warn():
    video = hoster("voe", ["one"], "degraded")
    video.update(last_success_at=NOW - 20, metrics_24h={"attempts": 1, "success_rate": 1},
                 steps=[{"code": "browser_fallback_required"}])
    summary = result([provider("one")], [video])
    assert summary["service_health"] == "healthy"
    assert summary["sources"]["hosters"]["voe"]["availability"] == "available"


def test_single_blocked_hoster_with_alternative_needs_no_user_action():
    summary = result([provider("one")], [hoster("working", ["one"]), hoster("blocked", ["one"], "blocked")])
    assert not summary["action_required"]
    assert summary["sources"]["hosters"]["blocked"]["impact"] == "none"


def test_all_video_paths_failed_requires_action():
    summary = result([provider("one")], [hoster("failed", ["one"], "broken"), hoster("blocked", ["one"], "blocked")])
    assert summary["service_health"] == "action_required"
    assert summary["coverage"]["series"] == "action_required"


def test_complete_provider_type_unavailable_requires_action():
    sources = [provider("movies", ("movies",)), provider("series", ("series",), state="broken")]
    summary = result(sources, [hoster("video", ["movies", "series"])])
    assert summary["coverage"]["movies"] == "healthy"
    assert summary["coverage"]["series"] == "action_required"
    assert summary["sources"]["hosters"]["video"]["impact"] == "none"


def test_lost_redundancy_is_yellow_but_keeps_download_path():
    summary = result([provider("one"), provider("two", state="broken")], [hoster("working", ["one", "two"])])
    assert summary["service_health"] == "degraded"
    assert summary["user_impact"] == "reduced_redundancy"
    assert not summary["action_required"]


def test_repaired_working_provider_has_no_warning():
    source = provider("one")
    source["active_repair"] = "validated"
    assert result([source], [hoster("working", ["one"])])["user_impact"] == "none"


def test_unknown_and_stale_evidence_never_claims_green_or_outage():
    source, video = provider("one"), hoster("working", ["one"])
    for row in (source, video):
        row["last_check_at"] = NOW - 86401
    summary = result([source], [video])
    assert summary["user_impact"] == "unconfirmed"
    assert not summary["action_required"]
    assert summary["available_video_services"] == 0


def test_english_alternative_does_not_hide_missing_german_series():
    summary = result([provider("de", ("series",), state="broken"), provider("en", ("series",), "en")], [hoster("working", ["de", "en"])])
    assert summary["action_required"]
    assert {p["language"]: p["state"] for p in summary["paths"]} == {"de": "action_required", "en": "healthy"}


def test_unconfigured_disabled_media_is_not_a_false_outage():
    source = provider("one")
    source["enabled_media_types"] = ["movies"]
    summary = result([source], [hoster("working", ["one"])])
    assert summary["coverage"]["series"] == "not_configured"
    assert summary["service_health"] == "healthy"


def test_raw_errors_never_enter_safe_impact_contract_and_input_is_preserved():
    source = provider("one", state="needs_attention")
    source["last_error"] = "The origin web server returned an invalid or incomplete response to Cloudflare token=secret"
    original = deepcopy(source)
    summary = result([source], [hoster("working", ["one"])])
    assert "Cloudflare" not in repr(summary) and "secret" not in repr(summary)
    assert source == original


def test_no_sources_requires_configuration_not_false_green():
    assert result([], [hoster("unselected", ["disabled"])])["action_required"]
    assert result([], [hoster("unselected", ["disabled"])])["available_video_services"] == 0


def test_default_circuit_healthy_is_not_runtime_evidence():
    source = provider("one", state="unknown")
    source["last_check_at"] = 0
    assert result([source], [hoster("working", ["one"])])["user_impact"] == "unconfirmed"


def test_notifications_only_emit_real_impact_transitions(tmp_path, monkeypatch):
    events = []
    owner = ProviderMonitor(tmp_path / "sentinel.json", ProviderHealth(tmp_path / "health.json"), lambda: ["one"], notify=events.append)
    owner.store.configure({"notify_changes": True})
    providers, videos = [provider("one")], [hoster("working", ["one"]), hoster("blocked", ["one"], "blocked")]
    monkeypatch.setattr(owner, "diagnostics", lambda: {"service": result(providers, videos)})
    owner._notify("blocked", "blocked", "hoster")
    assert events == []
    videos[0]["diagnosis"] = "broken"
    owner._notify("working", "broken", "hoster")
    owner._notify("working", "needs_attention", "hoster")
    assert len(events) == 1 and events[0]["message_code"] == "source_unavailable"
    videos[0]["diagnosis"] = "healthy"
    owner._notify("working", "healthy", "hoster")
    assert events[-1]["message_code"] == "source_recovered"


def test_initial_inconclusive_to_healthy_is_not_an_alarm_or_recovery(tmp_path, monkeypatch):
    events = []
    owner = ProviderMonitor(tmp_path / "sentinel.json", ProviderHealth(tmp_path / "health.json"), lambda: ["one"], notify=events.append)
    owner.store.configure({"notify_changes": True})
    source = provider("one", state="unknown")
    monkeypatch.setattr(owner, "diagnostics", lambda: {"service": result([source], [hoster("working", ["one"])])})
    owner._notify("one", "needs_attention")
    source["diagnosis"] = "healthy"
    owner._notify("one", "healthy")
    assert events == []


def test_unconfirmed_alternative_is_not_a_confirmed_redundancy_loss():
    summary = result([provider("one"), provider("two", state="needs_attention")], [hoster("working", ["one", "two"])])
    assert summary["service_health"] == "healthy"
    assert not summary["action_required"]


def test_diagnostics_single_source_uses_global_impact_and_preserves_details(tmp_path):
    owner = ProviderMonitor(tmp_path / "sentinel.json", ProviderHealth(tmp_path / "health.json"), lambda: ["filmpalast", "huhu"],
                            priorities=lambda media: ["filmpalast", "huhu"] if media == "movies" else [], clock=lambda: NOW)
    for key in ("filmpalast", "huhu"):
        owner.store.update(key, diagnosis="healthy", last_check_at=NOW - 60,
                           steps=[{"name": "catalog", "ok": True}], history=[], repairs=[])
    owner.hosters.store.update("voe", diagnosis="healthy", last_check_at=NOW - 60, health_evidence_version=2, providers=["filmpalast", "huhu"])
    overview = owner.diagnostics()
    detail = owner.diagnostics("filmpalast")
    assert detail["service"] == overview["service"]
    assert detail["providers"][0]["steps"] == [{"name": "catalog", "ok": True}]
    assert detail["providers"][0]["user_impact"]["impact"] == "none"
    assert overview["service"]["coverage"]["series"] == "not_configured"
    assert overview["service"]["service_health"] == "healthy"


def test_manual_attention_only_requires_action_when_runtime_proves_failure():
    video = hoster("video", ["one"], "needs_attention")
    assert result([provider("one")], [video])["user_impact"] == "unconfirmed"
    video.update(last_failure_at=NOW - 10, metrics_24h={"attempts": 5, "success_rate": 0})
    assert result([provider("one")], [video])["action_required"]


def test_pending_repair_does_not_hide_a_confirmed_http_only_outage():
    video = hoster("video", ["one"], "repair_available")
    video["contract"] = {"probe_mode": "http_only"}
    video["steps"] = [{"name": "resolver", "ok": False, "code": "parser_error", "sample": str(i)} for i in range(5)]
    assert result([provider("one")], [video])["action_required"]
    video["contract"]["probe_mode"] = "browser_capable"
    assert result([provider("one")], [video])["user_impact"] == "unconfirmed"
