from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIENCE = (ROOT / "web" / "home_experience_v2.js").read_text(encoding="utf-8")
API = (ROOT / "web" / "api.js").read_text(encoding="utf-8")


def test_home_experience_loads_after_taste_profile_v2():
    assert 'script.src = "/taste_v2.js?v=royal-20260811-1"' in API
    assert 'script.src = "/home_experience_v2.js?v=royal-20260811-1"' in API
    assert "window.setTimeout(loadRoyalHomeExperienceV2, 0)" in API


def test_hero_uses_five_personal_plus_trend_plus_adjacent_discovery():
    assert "const HERO_STRONG_TARGET = 5" in EXPERIENCE
    assert "five strongest personal matches" in EXPERIENCE
    assert "one taste-compatible current" in EXPERIENCE
    assert "addBalanced(selected, selectedKeys, strong, HERO_STRONG_TARGET)" in EXPERIENCE
    assert "addBalanced(selected, selectedKeys, trend" in EXPERIENCE
    assert "addBalanced(selected, selectedKeys, discovery" in EXPERIENCE


def test_hero_is_not_driven_by_daily_hash_or_manual_shuffle_seed():
    hero_section = EXPERIENCE.split("function tasteRankedHeroEntries()", 1)[1].split(
        "function homeExperienceHeroCandidates()", 1
    )[0]
    assert "stableDailyOrder" not in hero_section
    assert "discoveryShuffle" not in hero_section
    assert "discoveryV2Noise" not in hero_section


def test_hero_requires_quality_and_reuses_exposure_history():
    assert "const HERO_MIN_RATING = 5.5" in EXPERIENCE
    assert "media.backdrop_url" in EXPERIENCE
    assert 'discoveryV2ExposurePenalty(entry, "hero")' in EXPERIENCE
    assert "HERO_MAX_SAME_KIND = 4" in EXPERIENCE
    assert "HERO_MAX_OWNED = 4" in EXPERIENCE


def test_trained_hero_requires_positive_taste_affinity():
    assert "record.score >= minAffinity" in EXPERIENCE
    assert "record.coverage >= minCoverage" in EXPERIENCE
    assert "record.positive > Math.abs(record.negative)" in EXPERIENCE
    assert "record.score >= Math.max(adjacentFloor, 0.35)" in EXPERIENCE
