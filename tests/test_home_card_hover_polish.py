from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_MANIFEST = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
HOVER = (ROOT / "web" / "styles" / "home-card-hover.css").read_text(encoding="utf-8")


def test_hover_polish_is_loaded_last():
    imports = [line for line in STYLE_MANIFEST.splitlines() if line.startswith("@import")]
    assert imports[-1] == "@import url('/styles/home-card-hover.css?v=royal-20260808-1');"


def test_hover_keeps_card_geometry_calm_and_artwork_visible():
    assert "translateY(-4px) scale(1.035)" in HOVER
    assert "brightness(.96)" in HOVER
    assert "scale(1.018)" in HOVER
    assert "#tab-home .home-card-preview" in HOVER
    assert "display: none !important" in HOVER


def test_hover_keeps_stable_overlay_and_secondary_taste_action():
    assert "#tab-home .home-card:hover .home-card-overlay" in HOVER
    assert "opacity: 1" in HOVER
    assert "#tab-home .home-card .taste-v2-dismiss" in HOVER
    assert "top: 42px" in HOVER
    assert "width: 24px" in HOVER
    assert "opacity: .7" in HOVER


def test_touch_and_reduced_motion_remain_supported():
    assert "@media (hover: none), (pointer: coarse)" in HOVER
    assert "@media (prefers-reduced-motion: reduce)" in HOVER
    assert "transition: none !important" in HOVER
