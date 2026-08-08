from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_MANIFEST = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
HOVER = (ROOT / "web" / "styles" / "home-card-hover.css").read_text(encoding="utf-8")
EXPERIENCE = (ROOT / "web" / "home_experience_v2.js").read_text(encoding="utf-8")


def test_hover_polish_is_loaded_last_with_fresh_cache_key():
    imports = [line for line in STYLE_MANIFEST.splitlines() if line.startswith("@import")]
    assert imports[-1] == "@import url('/styles/home-card-hover.css?v=royal-20260808-2');"


def test_hover_keeps_card_geometry_calm_and_artwork_visible():
    assert "translateY(-4px) scale(1.035)" in HOVER
    assert "scale(1.018)" in HOVER
    assert "brightness(.9)" in HOVER
    assert "transparent 27%" in HOVER


def test_hover_restores_real_context_without_fake_action_circles():
    assert "display: grid !important" in HOVER
    assert ".home-card-hover-meta" in HOVER
    assert ".home-card-preview-description" in HOVER
    assert ".home-card-preview-match" in HOVER
    assert ".home-card-preview-open" in HOVER
    assert 'preview.querySelector(".home-card-preview-actions")?.remove()' in EXPERIENCE
    assert 'openHint.textContent = "Details öffnen  →"' in EXPERIENCE
    assert "Passt zu dir:" in EXPERIENCE


def test_hover_keeps_title_stable_and_uses_richer_metadata():
    assert "Keep title anchored in the exact resting position" in HOVER
    assert "#tab-home .home-card:hover .home-card-overlay > span" in HOVER
    assert "#tab-home .home-card .taste-v2-dismiss" in HOVER
    assert "top: 42px" in HOVER
    assert "width: 24px" in HOVER


def test_touch_and_reduced_motion_remain_supported():
    assert "@media (hover: none), (pointer: coarse)" in HOVER
    assert "@media (prefers-reduced-motion: reduce)" in HOVER
    assert "transition: none !important" in HOVER
    assert "#tab-home .home-card-preview" in HOVER
