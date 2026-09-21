from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_taste_onboarding_requires_five_and_uses_real_catalog_entries():
    script = (ROOT / "web/screens/taste-onboarding.js").read_text(encoding="utf-8")
    assert "const TASTE_ONBOARDING_MINIMUM = 5" in script
    assert "homeAllEntries()" in script
    assert "diverseTasteOnboardingCandidates" in script
    assert "tasteOnboardingSelection.size < TASTE_ONBOARDING_MINIMUM" in script
    assert "api.tasteOnboarding" in script


def test_browser_taste_cache_is_scoped_to_the_authenticated_user():
    home = (ROOT / "web/screens/home.js").read_text(encoding="utf-8")
    assert "function discoveryProfileStorageKey()" in home
    assert "authStatus?.user?.id" in home
    assert "`${HOME_DISCOVERY_PROFILE_KEY}:${userId}`" in home


def test_onboarding_screen_is_accessible_and_responsive():
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    css = (ROOT / "web/styles/taste-onboarding.css").read_text(encoding="utf-8")
    assert 'id="taste-onboarding"' in index
    assert 'aria-modal="true"' in index
    assert 'id="taste-onboarding-submit"' in index
    assert "@media (max-width: 520px)" in css
    assert "grid-auto-rows: max-content" in css


def test_onboarding_keeps_picks_across_batches_and_exposes_removal():
    script = (ROOT / "web/screens/taste-onboarding.js").read_text(encoding="utf-8")
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "let tasteOnboardingSeen = new Set()" in script
    assert "!tasteOnboardingSeen.has(item.key)" in script
    assert 'id="taste-onboarding-selected"' in index
    assert "tasteOnboardingSelection.delete(item.key)" in script
    assert "tasteOnboardingSelection.clear()" not in script


def test_header_profile_and_rail_posters_do_not_depend_on_hover():
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    profile = (ROOT / "web/screens/user-profile.js").read_text(encoding="utf-8")
    rail = (ROOT / "web/home_rail_runtime.js").read_text(encoding="utf-8")
    assert 'id="user-menu-trigger"' in index
    assert 'id="tab-profil"' in index
    assert "api.meProfileSummary" in profile
    assert "api.meHousehold" in profile
    assert "primeHomeRailPosters" in rail
    assert 'image.loading = "eager"' in rail
