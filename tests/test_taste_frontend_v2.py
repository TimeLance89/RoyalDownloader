from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASTE = (ROOT / "web" / "taste_v2.js").read_text(encoding="utf-8")
API = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
RUNTIME = (ROOT / "application_services" / "runtime.py").read_text(encoding="utf-8")


def test_taste_v2_is_loaded_after_legacy_discovery_installers():
    assert 'script.src = "/taste_v2.js?v=royal-20260808-1"' in API
    assert "window.setTimeout(loadRoyalTasteProfileV2, 0)" in API


def test_personal_lane_is_strict_five_plus_two_without_forced_surprise():
    assert "five strong matches plus at most two adjacent discoveries" in TASTE
    assert "addDiverse(strong, 5)" in TASTE
    assert "addDiverse(adjacent, Math.max(0, 7 - selected.length))" in TASTE
    assert "personal-surprise" not in TASTE


def test_manual_shuffle_penalizes_current_session_exposure():
    assert "const sessionExposure = new Set()" in TASTE
    assert "sessionExposure.add(tasteV2LogicalKey(entry))" in TASTE
    assert "const sessionPenalty = sessionExposure.has(key) ? 18 : 0" in TASTE


def test_home_cards_offer_direct_not_for_me_feedback_and_reason():
    assert 'control.setAttribute("aria-label", "Nicht für mich")' in TASTE
    assert 'action: "dismiss"' in TASTE
    assert "Passt: ${positives.join" in TASTE


def test_blocking_uses_logical_media_identity_as_well_as_provider_slug():
    assert "!blocked.has(tasteV2LogicalKey(entry))" in TASTE
    assert "!blocked.has(homeEntryKey(entry))" in TASTE


def test_unified_jellyfin_recommender_is_installed_as_post_service():
    assert '"application_services.taste_recommender_runtime"' in RUNTIME
