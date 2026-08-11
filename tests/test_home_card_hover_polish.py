from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_MANIFEST = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
HOVER = (ROOT / "web" / "styles" / "home-card-hover.css").read_text(encoding="utf-8")
HOME = (ROOT / "web" / "screens" / "home.js").read_text(encoding="utf-8")
DOCK = (ROOT / "web" / "home_card_dock.js").read_text(encoding="utf-8")
TASTE = (ROOT / "web" / "taste_v2.js").read_text(encoding="utf-8")


def test_cinema_dock_is_loaded_last_with_fresh_cache_key():
    imports = [line for line in STYLE_MANIFEST.splitlines() if line.startswith("@import")]
    assert imports[-1] == "@import url('/styles/home-card-hover.css?v=royal-20260811-3');"
    assert '<script src="/home_card_dock.js?v=royal-20260811-6"></script>' in (
        ROOT / "web" / "index.html"
    ).read_text(encoding="utf-8")


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


def test_ranked_top_ten_cards_have_no_pointer_hover_behavior():
    assert "if (!rank) {" in HOME
    assert "registerHomeCardDock(card, entry)" in HOME
    assert "card.addEventListener(\"pointerenter\"" in DOCK
    assert "#tab-home .home-card.is-ranked:hover" in HOVER
    assert "#tab-home .home-card.is-ranked:hover .home-card-art img" in HOVER
    assert "filter: none" in HOVER


def test_wheel_over_the_dock_is_forwarded_to_the_real_scroll_container():
    assert 'homeCardDock.addEventListener("wheel", relayHomeCardDockWheel, { passive: false })' in DOCK
    assert 'owner?.closest(".tab-content")' in DOCK
    assert "homeScroller.scrollTop += event.deltaY * lineFactor" in DOCK
    assert "track.scrollLeft += (event.deltaX || event.deltaY) * lineFactor" in DOCK


def test_hover_lifecycle_has_a_minimum_visible_window_and_safe_handoff():
    assert "HOME_CARD_DOCK_HANDOFF_MS = 110" in DOCK
    assert "HOME_CARD_DOCK_MIN_VISIBLE_MS = 360" in DOCK
    assert "homeCardDockCandidate !== card" in DOCK
    assert "event?.relatedTarget" in DOCK
    assert "homeCardDockOwner !== card" in DOCK


def test_pointer_geometry_keeps_micro_movements_from_collapsing_the_dock():
    assert "registerHomeCardDock(card, entry)" in HOME
    assert "const homeCardDockEntries = new WeakMap()" in DOCK
    assert 'document.addEventListener("pointermove", handleHomeCardDockPointerMove' in DOCK
    assert "homeCardDockPointerInsideActiveZone()" in DOCK
    assert "homeCardDockPointInside(card, 8)" in DOCK
    assert 'homeCardDock?.matches(":hover")' not in DOCK
    assert 'homeCardDockOwner?.matches(":hover")' not in DOCK


def test_internal_scroll_events_cannot_cancel_the_latched_hover():
    assert 'window.addEventListener("scroll"' not in DOCK
    assert "homeCardDockScrollBlockedUntil" not in DOCK
    assert "homeCardDockShowTimer = window.setTimeout(show, delay)" in DOCK


def test_open_dock_is_hard_latched_until_pointer_leaves_card_and_dock_zone():
    assert "Math.min(cardRect.left, dockRect.left) - padding" in DOCK
    assert "Math.max(cardRect.right, dockRect.right) + padding" in DOCK
    assert 'card.addEventListener("pointerleave"' not in DOCK
    assert 'homeCardDock.addEventListener("pointerleave"' not in DOCK
    assert "if (homeCardDockPointerInsideActiveZone())" in DOCK
    assert "hideHomeCardDock();" in DOCK


def test_dock_avoids_visible_rail_navigation_buttons_at_both_edges():
    assert 'document.querySelectorAll(`[data-home-scroll="${track.id}"]:not([hidden])`)' in DOCK
    assert "buttonRect.right + reserve" in DOCK
    assert "buttonRect.left - width - reserve" in DOCK
    assert "#tab-home .home-rail-controls button" in HOVER
    assert "z-index: 260" in HOVER


def test_smooth_rail_scroll_cannot_discard_a_pending_card_hover():
    assert "function handleHomeCardDockScroll" not in DOCK
    assert "function restoreHomeCardDockAfterRailScroll" not in DOCK
    assert "cancelHomeCardDockTimers();" in DOCK
