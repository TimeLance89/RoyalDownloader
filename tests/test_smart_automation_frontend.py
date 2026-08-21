from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_JS = ROOT / "web" / "automation-policy.js"
POLICY_CSS = ROOT / "web" / "styles" / "automation-policy.css"
GLOBAL_RUNTIME = ROOT / "web" / "global-search-runtime.js"
DOMAIN_ROUTER = ROOT / "api_domain_routers.py"
RUNTIME = ROOT / "application_services" / "runtime.py"


def test_smart_automation_frontend_exposes_all_requested_controls():
    js = POLICY_JS.read_text(encoding="utf-8")
    for identifier in (
        "weekday-custom-start",
        "weekday-custom-end",
        "weekend-custom-start",
        "weekend-custom-end",
        "max-parallel-downloads",
        "max-bandwidth-mbps",
        "min-free-space-gb",
        "jellyfin-throttle-enabled",
        "jellyfin-streaming-bandwidth-mbps",
        "movie-upgrades-night-only",
        "movie-upgrade-window-start",
        "movie-upgrade-window-end",
    ):
        assert f'id="{identifier}"' in js
    assert '"/api/automation/policy"' in js
    assert "Gesamtbudget" in js
    assert "Manuelle Downloads bleiben verfügbar" in js


def test_schedule_uses_friendly_modes_and_clock_inputs_instead_of_raw_hours():
    js = POLICY_JS.read_text(encoding="utf-8")
    assert 'name="weekday-mode"' in js
    assert 'name="weekend-mode"' in js
    assert "Jederzeit" in js
    assert "Nur nachts" in js
    assert "Eigene Zeiten" in js
    assert "Wie Mo–Fr" in js
    assert 'id="weekday-custom-start" type="time"' in js
    assert 'id="weekend-custom-start" type="time"' in js
    assert 'id="movie-upgrade-window-start" type="time"' in js
    assert 'id="weekend-window-start" type="number"' not in js
    assert "smart-automation-legacy-window" in js


def test_smart_automation_frontend_is_loaded_and_styled():
    runtime = GLOBAL_RUNTIME.read_text(encoding="utf-8")
    css = POLICY_CSS.read_text(encoding="utf-8")
    assert "/automation-policy.js?v=royal-20260821-1" in runtime
    assert "data-royal-smart-automation" in runtime
    assert ".smart-automation-policy" in css
    assert ".smart-schedule-choice" in css
    assert ".smart-time-window" in css
    assert "@media(max-width:470px)" in css
    assert "focus-visible" in css
    assert "prefers-reduced-motion" in css


def test_smart_automation_routes_and_service_layer_are_wired():
    domain = DOMAIN_ROUTER.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "api_automation_policy_router" in domain
    assert "automation_policy_router" in domain
    assert '"application_services.smart_automation"' in runtime
