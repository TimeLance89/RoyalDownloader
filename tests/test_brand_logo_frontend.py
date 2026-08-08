from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_royal_cinema_logo_asset_and_styles_are_wired():
    manifest = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    styles = (ROOT / "web" / "styles" / "brand-logo.css").read_text(encoding="utf-8")
    logo = (ROOT / "web" / "assets" / "royal-cinema-logo.svg").read_text(encoding="utf-8")

    assert "/styles/brand-logo.css?v=royal-20260808-1" in manifest
    assert "/assets/royal-cinema-logo.svg?v=royal-20260808-1" in styles
    assert ".topbar .brand::before" in styles
    assert "ROYAL" in logo
    assert "CINEMA" in logo
    assert 'fill="#ffffff"' in logo


def test_logo_keeps_existing_brand_text_accessible():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "web" / "styles" / "brand-logo.css").read_text(encoding="utf-8")

    assert '<span class="brand-title">ROYAL</span>' in index
    assert '<span class="brand-sub">Cinema</span>' in index
    assert ".topbar .brand > .brand-title" in styles
    assert ".topbar .brand > .brand-sub" in styles
