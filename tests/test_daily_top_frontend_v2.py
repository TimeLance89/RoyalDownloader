from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAILY = (ROOT / "web" / "daily_top_v2.js").read_text(encoding="utf-8")
API = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
RUNTIME = (ROOT / "application_services" / "runtime.py").read_text(encoding="utf-8")
HOME = (ROOT / "web" / "screens" / "home.js").read_text(encoding="utf-8")
STORE = (ROOT / "web" / "store.js").read_text(encoding="utf-8")


def test_daily_top_service_is_part_of_runtime_graph():
    assert '"application_services.daily_top"' in RUNTIME


def test_daily_top_frontend_loads_after_home_experience_v2():
    assert 'script.src = "/daily_top_v2.js?v=royal-20260809-2"' in API
    assert "loadRoyalDailyTopV2" in API
    assert "window.setTimeout(loadRoyalDailyTopV2, 0)" in API


def test_daily_top_is_real_rank_not_daily_hash_or_taste_shuffle():
    assert 'api.get("/api/daily-top?"' in DAILY
    assert "stableDailyOrder" not in DAILY
    assert "discoveryShuffle" not in DAILY
    assert "global_rank" in DAILY
    assert "dailyTopScore" in DAILY


def test_daily_top_snapshot_is_stable_and_tracks_day_to_day_movement():
    assert 'const DAILY_TOP_STORAGE_KEY = "royal-home-daily-top-v3"' in DAILY
    assert "function isPresentable(candidate)" in DAILY
    assert "function cleanTitle(value)" in DAILY
    assert 'label: "NEW"' in DAILY
    assert "`↑${delta}`" in DAILY
    assert "`↓${Math.abs(delta)}`" in DAILY
    assert 'label: "—"' in DAILY
    assert "Same-day ranks are immutable" in DAILY


def test_daily_top_respects_blocked_media_and_keeps_visible_ranks_contiguous():
    assert "blocked_items" in DAILY
    assert "discoveryV2LogicalKey" in DAILY
    assert "visibleRank = Number(requestedRank || dailyTop.global_rank || 0)" in DAILY
    assert "rank.textContent = String(visibleRank)" in DAILY
    assert "`Platz ${visibleRank}:`" in DAILY
    assert "card.dataset.dailyTopGlobalRank = String(globalRank)" in DAILY
    assert "card.dataset.dailyTopDisplayRank = String(visibleRank)" in DAILY


def test_daily_top_cards_open_from_their_own_provider_payload():
    assert "function openDailyTopEntry(entry)" in DAILY
    assert "selectFpRow(item.slug, item)" in DAILY
    assert "loadSeries(item)" in DAILY
    assert "event.stopImmediatePropagation()" in DAILY
    assert "entry?.item?.daily_top" in DAILY
    assert "[role='button']" in DAILY


def test_daily_top_heading_describes_cross_source_popularity():
    assert 'eyebrow.textContent = "Heute über deine Quellen hinweg angesagt"' in DAILY


def test_daily_top_jellyfin_status_survives_snapshot_rerenders():
    assert "jellyfinStatusByKey: new Map()" in STORE
    assert "state.home.jellyfinStatusByKey.set(key, status)" in HOME
    assert "state.home.jellyfinStatusByKey.get(homeEntryKey(entry))" in HOME
    assert 'response.configured ? "unavailable" : "unconfigured"' in HOME
    assert 'statusByKey.get(key) || "unavailable"' in HOME
