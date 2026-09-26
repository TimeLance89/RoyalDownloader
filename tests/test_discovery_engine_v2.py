from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE = (ROOT / "web/js/features/home/discovery-policy.js").read_text(encoding="utf-8")


def test_discovery_v2_keeps_a_persistent_exposure_history():
    assert 'HOME_DISCOVERY_V2_EXPOSURE_KEY = "royal-home-exposure-v2"' in STORE
    assert "function recordDiscoveryExposureV2" in STORE
    assert "function discoveryV2ExposurePenalty" in STORE
    assert "if (age < 1 || age > 14) continue" in STORE


def test_personalized_lane_keeps_the_active_five_plus_two_policy():
    ranking = (ROOT / "web/js/features/home/taste-ranking.js").read_text(encoding="utf-8")
    assert "addDiverse(strong, 5)" in ranking
    assert "addDiverse(adjacent, Math.max(0, 7 - selected.length))" in ranking
    legacy = (ROOT / "web/store.js").read_text(encoding="utf-8")
    assert "window.homePersonalizedEntries =" not in legacy
    assert "window.homeTopEntries =" not in legacy


def test_top_ten_limits_yesterdays_repeats_when_alternatives_exist():
    assert "function discoveryV2TopEntries" in STORE
    assert 'discoveryV2PreviousLaneKeys("top", 1)' in STORE
    assert "repeatLimit: previousTop.size ? 4 : Infinity" in STORE


def test_home_reservoir_warms_deeper_catalog_pages_in_background():
    data = (ROOT / "web/js/features/home/data.js").read_text(encoding="utf-8")
    assert "async function performWarm" in data
    for fragment in (
        'catalog("movie", { mode: "new", page: 3 }, scope.signal)',
        'catalog("movie", { mode: "top", page: 4 }, scope.signal)',
        'catalog("series", { mode: "discover", page: 2 }, scope.signal)',
        'catalog("series", { mode: "trending", page: 3 }, scope.signal)',
        'catalog("series", { mode: "new", page: 3 }, scope.signal)',
    ):
        assert fragment in data
    assert "Promise.allSettled" in data
    assert "scheduleWarm(120)" in data
    assert "owner.timeout" in data


def test_discovery_v2_deduplicates_logical_media_and_preserves_language_metadata():
    assert "function discoveryV2LogicalKey" in STORE
    assert "function discoveryV2MergeItems" in STORE
    assert "existing.content_languages = [...languages]" in STORE
    assert "discoveryV2SelectDiverse" in STORE
