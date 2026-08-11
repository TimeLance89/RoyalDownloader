from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_MANIFEST = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
HOVER = (ROOT / "web" / "styles" / "home-card-hover.css").read_text(encoding="utf-8")
HOME = (ROOT / "web" / "screens" / "home.js").read_text(encoding="utf-8")
DOCK = (ROOT / "web" / "home_card_dock.js").read_text(encoding="utf-8")
TASTE = (ROOT / "web" / "taste_v2.js").read_text(encoding="utf-8")


def test_cinema_dock_is_loaded_last_with_fresh_cache_key():
    imports = [line for line in STYLE_MANIFEST.splitlines() if line.startswith("@import")]
    assert imports[-1] == "@import url('/styles/home-card-hover.css?v=royal-20260811-1');"


def test_cinema_dock_escapes_rail_clipping_and_stays_inside_the_viewport():
    assert ".home-card-dock {" in HOVER
    assert "position: fixed" in HOVER
    assert "document.body.appendChild(homeCardDock)" in DOCK
    assert "window.innerWidth - width - gutter" in DOCK
    assert "window.innerHeight - estimatedHeight - gutter" in DOCK
    assert "homeCardDock.style.left" in DOCK
    assert "homeCardDock.style.top" in DOCK


def test_hover_has_intent_fade_in_fade_out_and_soft_card_handoff():
    assert "const HOME_CARD_DOCK_INTENT_MS = 260" in DOCK
    assert "const HOME_CARD_DOCK_FADE_MS = 170" in DOCK
    assert 'dock.classList.add("is-leaving")' in DOCK
    assert "window.setTimeout(reveal, HOME_CARD_DOCK_FADE_MS)" in DOCK
    assert ".home-card-dock.is-visible" in HOVER
    assert ".home-card-dock.is-leaving" in HOVER
    assert "opacity .17s ease" in HOVER


def test_hover_exposes_real_royal_actions_instead_of_fake_marks():
    assert 'homeCardDockButton("is-primary"' in DOCK
    assert "openHomeEntry(entry.kind" in DOCK
    assert "await toggleFpPick(entry.item.slug)" in DOCK
    assert "await api.tmdbMovie" in DOCK
    assert "openFpTrailerModal(trailerMedia" in DOCK
    assert "dismissSource.click()" in DOCK
    assert "home-card-preview-actions" not in HOME + DOCK
    assert 'card.dataset.tasteReason = positives.join(" · ")' in TASTE


def test_hover_actions_are_keyboard_accessible_and_announce_async_feedback():
    assert 'homeCardDock.setAttribute("role", "group")' in DOCK
    assert 'if (event.key !== "ArrowDown") return' in HOME
    assert 'if (event.key !== "Escape") return' in DOCK
    assert 'status.setAttribute("aria-live", "polite")' in DOCK
    assert ".home-card-dock-action:focus-visible" in HOVER


def test_touch_and_reduced_motion_remain_supported():
    assert "@media (hover: none), (pointer: coarse)" in HOVER
    assert "@media (prefers-reduced-motion: reduce)" in HOVER
    assert "transition: none !important" in HOVER
    assert ".home-card-dock { display: none !important; }" in HOVER
