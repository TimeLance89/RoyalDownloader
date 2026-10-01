from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIENCE = (ROOT / "web/js/features/home/hero-selection.js").read_text(encoding="utf-8")
API = ((ROOT / "web" / "js/core/api.js").read_text(encoding="utf-8") + "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "web/js/composition").glob("*.js")))


def test_home_experience_loads_after_taste_profile_v2():
    assert "createTasteRanking" in API
    assert "createHeroSelection" in API
    assert "window.homeHeroCandidates =" not in EXPERIENCE


def test_hero_prioritizes_cinema_then_personal_and_adjacent_discovery():
    assert "const HERO_STRONG_TARGET = 5" in EXPERIENCE
    assert "addBalanced(selected, selectedKeys, cinema, 4)" in EXPERIENCE
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
    assert "HERO_MAX_SAME_KIND = 5" in EXPERIENCE
    assert "HERO_MAX_OWNED = 4" in EXPERIENCE
    assert 'const artwork = media.backdrop_url || media.cover_url || ""' in EXPERIENCE


def test_trained_hero_requires_positive_taste_affinity():
    assert "record.score >= minAffinity" in EXPERIENCE
    assert "record.coverage >= minCoverage" in EXPERIENCE
    assert "record.positive > Math.abs(record.negative)" in EXPERIENCE
    assert "record.score >= Math.max(adjacentFloor, 0.35)" in EXPERIENCE
