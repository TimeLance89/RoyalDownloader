from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAILY = (ROOT / "web/js/features/home/daily-top.js").read_text(encoding="utf-8")
RUNTIME = (ROOT / "application_services/runtime.py").read_text(encoding="utf-8")
HOME = (ROOT / "web/js/features/home/cards.js").read_text(encoding="utf-8")
HTML = (ROOT / "web/index.html").read_text(encoding="utf-8")


def test_daily_top_service_is_part_of_runtime_graph():
    assert '"application_services.daily_top"' in RUNTIME


def test_charts_use_server_snapshots_with_profile_visibility_and_owned_status():
    assert 'client.get("/api/v3/royal-charts?"' in DAILY
    assert "localStorage" not in DAILY
    assert "fallbackEntries" not in DAILY
    assert "blocked_items" in DAILY
    assert "discoveryV2LogicalKey" in DAILY
    assert "getJellyfinStatus(homeEntryKey(entry))" in HOME
    assert "refreshStatuses" in DAILY


def test_chart_modes_and_dialogs_are_present_in_home_layout():
    for mode in ("today", "week", "month", "breakouts", "new"):
        assert f'data-chart-mode="{mode}"' in HTML
    assert '<dialog id="royal-charts"' in HTML
    assert '<dialog id="royal-chart-detail"' in HTML
    assert 'id="home-top-track" class="home-track home-top-track"' in HTML
