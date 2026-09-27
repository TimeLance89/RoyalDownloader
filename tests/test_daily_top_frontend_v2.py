from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAILY = (ROOT / "web/js/features/home/daily-top.js").read_text(encoding="utf-8")
API = ((ROOT / "web" / "js/core/api.js").read_text(encoding="utf-8") + "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "web/js/composition").glob("*.js")))
RUNTIME = (ROOT / "application_services" / "runtime.py").read_text(encoding="utf-8")
HOME = (ROOT / "web/js/features/home/cards.js").read_text(encoding="utf-8")
STORE = (ROOT / "web" / "js/shell/state.js").read_text(encoding="utf-8")


def test_daily_top_service_is_part_of_runtime_graph():
    assert '"application_services.daily_top"' in RUNTIME


def test_daily_top_frontend_loads_after_home_experience_v2():
    assert "daily_top_v2.js" not in API
    assert "export function createDailyTop" in DAILY
    assert "fallbackEntries" in DAILY


def test_daily_top_is_real_rank_not_daily_hash_or_taste_shuffle():
    assert 'client.get("/api/daily-top?"' in DAILY
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


def test_daily_top_does_not_repaint_the_initial_home_screen():
    assert "void refreshDailyTop(false)" in DAILY


def test_daily_top_jellyfin_status_survives_snapshot_rerenders():
    matching = (ROOT / "web/js/features/integrations/catalog-jellyfin.js").read_text(encoding="utf-8")
    assert "statuses = new Map()" in matching
    assert "statuses.set(key, status)" in matching
    assert "getJellyfinStatus(homeEntryKey(entry))" in HOME
    assert 'response.configured ? "unavailable" : "unconfigured"' in matching
    assert 'statusByKey.get(key) || "unavailable"' in matching
