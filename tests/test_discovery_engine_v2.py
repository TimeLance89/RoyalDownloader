from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE = (ROOT / "web" / "store.js").read_text(encoding="utf-8")


def test_discovery_v2_keeps_a_persistent_exposure_history():
    assert 'HOME_DISCOVERY_V2_EXPOSURE_KEY = "royal-home-exposure-v2"' in STORE
    assert "function recordDiscoveryExposureV2" in STORE
    assert "function discoveryV2ExposurePenalty" in STORE
    assert "if (age < 1 || age > 14) continue" in STORE


def test_personalized_lane_has_core_adjacent_and_surprise_mix():
    assert "function discoveryV2PersonalizedEntries" in STORE
    assert "four strong taste matches, two adjacent discoveries and one surprise" in STORE
    assert "discoveryV2SelectDiverse(scored.slice" in STORE
    assert '"personal-adjacent"' in STORE
    assert '"personal-surprise"' in STORE


def test_top_ten_limits_yesterdays_repeats_when_alternatives_exist():
    assert "function discoveryV2TopEntries" in STORE
    assert 'discoveryV2PreviousLaneKeys("top", 1)' in STORE
    assert "repeatLimit: previousTop.size ? 4 : Infinity" in STORE


def test_home_reservoir_warms_deeper_catalog_pages_in_background():
    assert "async function warmDiscoveryReservoirV2" in STORE
    for fragment in (
        'api.movies({ mode: "new", page: 3 })',
        'api.movies({ mode: "top", page: 4 })',
        'api.series({ mode: "discover", page: 2 })',
        'api.series({ mode: "trending", page: 3 })',
        'api.series({ mode: "new", page: 3 })',
    ):
        assert fragment in STORE
    assert "Promise.allSettled" in STORE
    assert "window.setTimeout(() => { void warmDiscoveryReservoirV2(); }, 120)" in STORE


def test_discovery_v2_deduplicates_logical_media_and_preserves_language_metadata():
    assert "function discoveryV2LogicalKey" in STORE
    assert "function discoveryV2MergeItems" in STORE
    assert "existing.content_languages = [...languages]" in STORE
    assert "discoveryV2SelectDiverse" in STORE
