from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_MANIFEST = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
HOVER = (ROOT / "web" / "styles" / "home-card-hover.css").read_text(encoding="utf-8")
PREMIUM = (ROOT / "web" / "styles" / "home-card-premium.css").read_text(encoding="utf-8")
HOME = (ROOT / "web/js/features/home/cards.js").read_text(encoding="utf-8")
DOCK = (ROOT / "web/js/features/home/card-dock.js").read_text(encoding="utf-8")
TASTE = (ROOT / "web/js/features/home/taste-ranking.js").read_text(encoding="utf-8")


def test_cinema_dock_and_premium_card_finish_precede_mobile_override():
    imports = [line for line in STYLE_MANIFEST.splitlines() if line.startswith("@import")]
    ordered_layers = [
        "@import url('/styles/home-card-hover.css?v=royal-20260811-5');",
        "@import url('/styles/home-card-premium.css?v=royal-20260830-2');",
        "@import url('/styles/home-rails-mockup.css?v=royal-20260915-2');",
        '@import url("/styles/taste-feedback.css?v=royal-20260926-1");',
        '@import url("/styles/daily-top.css?v=royal-20260926-1");',
        '@import url("/styles/language-studio.css?v=royal-language-studio-1");',
        '@import url("/styles/mobile.css?v=royal-mobile-20261006-3");',
    ]
    positions = [imports.index(layer) for layer in ordered_layers]
    assert positions == sorted(positions)
    assert imports[-1] == ordered_layers[-1]
    assert '<script src="/home_card_dock.js' not in (
        ROOT / "web" / "index.html"
    ).read_text(encoding="utf-8")


def test_premium_cards_use_the_royal_material_and_focus_rail():
    for token in (
        "--card-ink: #0b0d10",
        "--card-surface: #161a20",
        "--card-gold: #d8b766",
        "--card-paper: #f3efe4",
        "--card-signal: #e32636",
    ):
        assert token in PREMIUM
    assert "#tab-home .home-card-art::before" in PREMIUM
    assert "transform: scaleX(1)" in PREMIUM
    assert "#tab-home .home-card.is-spotlight-lead" in PREMIUM
    ranked_hover = PREMIUM.split("#tab-home .home-card.is-ranked:hover {", 1)[1].split("}", 1)[0]
    assert "transform: none" in ranked_hover
    assert "@media (prefers-reduced-motion: reduce)" in PREMIUM


def test_premium_rails_do_not_inherit_the_legacy_hover_overlap():
    track_rule = PREMIUM.split("#tab-home .home-track,", 1)[1].split("}", 1)[0]
    assert "margin-block: 0" in track_rule
    assert "padding: 8px var(--home-gutter) 25px 1px" in track_rule


def test_ranked_cards_keep_an_editorial_but_compact_footprint():
    ranked_rule = PREMIUM.split("#tab-home .home-card.is-ranked {", 1)[1].split("}", 1)[0]
    assert "15.5vw" in ranked_rule
    assert "300px" in ranked_rule
    assert "26vw" not in ranked_rule


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
    assert "scope.timeout(reveal, HOME_CARD_DOCK_FADE_MS)" in DOCK
    assert ".home-card-dock.is-visible" in HOVER
    assert ".home-card-dock.is-leaving" in HOVER
    assert "opacity .17s ease" in HOVER


def test_hover_exposes_real_royal_actions_instead_of_fake_marks():
    assert 'homeCardDockButton("is-primary"' in DOCK
    assert "openHomeEntry(entry.kind" in DOCK
    assert "await toggleFpPick(entry.item.slug)" in DOCK
    assert 'await client.post("/api/tmdb/movie"' in DOCK
    assert "openFpTrailerModal(trailerMedia" in DOCK
    assert "dismissSource.click()" in DOCK
    assert "home-card-preview-actions" not in HOME + DOCK
    assert 'card.dataset.tasteReason = positives.join(" · ")' in TASTE


def test_hover_actions_are_keyboard_accessible_and_announce_async_feedback():
    assert 'homeCardDock.setAttribute("role", "group")' in DOCK
    assert 'if (event.key !== "ArrowDown") return' in DOCK
    assert 'if (event.key !== "Escape") return' in DOCK
    assert 'status.setAttribute("aria-live", "polite")' in DOCK
    assert ".home-card-dock-action:focus-visible" in HOVER


def test_touch_and_reduced_motion_remain_supported():
    assert "@media (hover: none), (pointer: coarse)" in HOVER
    assert "@media (prefers-reduced-motion: reduce)" in HOVER
    assert "transition: none !important" in HOVER
    assert ".home-card-dock { display: none !important; }" in HOVER


def test_ranked_top_ten_cards_have_no_pointer_hover_behavior():
    assert "if (!rank) decorate?.(card, primaryAction);" in (ROOT / "web/js/shared/components/media-card.js").read_text(encoding="utf-8")
    assert "registerDock(card, entry)" in HOME
    assert 'scope.listen(root, "pointerover"' in DOCK
    assert "#tab-home .home-card.is-ranked:hover" in HOVER
    assert "#tab-home .home-card.is-ranked:hover .home-card-art img" in HOVER
    assert "filter: none" in HOVER


def test_wheel_over_the_dock_is_forwarded_to_the_real_scroll_container():
    assert 'scope.listen(homeCardDock, "wheel", relayHomeCardDockWheel, { passive: false })' in DOCK
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
    assert "registerDock(card, entry)" in HOME
    assert "const homeCardDockEntries = new WeakMap()" in DOCK
    assert 'scope.listen(document, "pointermove", handleHomeCardDockPointerMove' in DOCK
    assert "homeCardDockPointerInsideActiveZone()" in DOCK
    assert "homeCardDockPointInside(card, 8)" in DOCK
    assert 'homeCardDock?.matches(":hover")' not in DOCK
    assert 'homeCardDockOwner?.matches(":hover")' not in DOCK


def test_internal_scroll_events_cannot_cancel_the_latched_hover():
    assert 'window.addEventListener("scroll"' not in DOCK
    assert "homeCardDockScrollBlockedUntil" not in DOCK
    assert "homeCardDockShowTimer = scope.timeout(show, delay)" in DOCK


def test_open_dock_is_hard_latched_until_pointer_leaves_card_and_dock_zone():
    assert "Math.min(cardRect.left, dockRect.left) - padding" in DOCK
    assert "Math.max(cardRect.right, dockRect.right) + padding" in DOCK
    assert 'card.addEventListener("pointerleave"' not in DOCK
    assert 'scope.listen(homeCardDock, "pointerleave"' not in DOCK
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


def test_clicking_non_action_dock_content_opens_details():
    assert 'scope.listen(homeCardDock, "click", (event) =>' in DOCK
    assert 'target?.closest("button, a, input, select, textarea")' in DOCK
    assert 'homeCardDock.querySelector(".home-card-dock-action.is-primary")?.click()' in DOCK
    assert "cursor: pointer" in HOVER


def test_entering_a_carousel_arrow_closes_card_hover_but_keeps_arrow_hover():
    assert 'target?.closest("#tab-home .home-rail-controls button")' in DOCK
    arrow_branch = DOCK.split("const railArrow", 1)[1].split("const card", 1)[0]
    assert "hideHomeCardDock();" in arrow_branch
    assert ".home-rail-controls button:hover" not in HOVER


def test_hover_autoplays_an_available_trailer_after_one_second():
    assert "const HOME_CARD_DOCK_PREVIEW_MS = 1000" in DOCK
    assert "void playHomeCardDockPreview(card, entry, request)" in DOCK
    assert 'await client.post("/api/tmdb/movie"' in DOCK
    assert "request !== homeCardDockPreviewRequest" in DOCK
    assert "homeCardDockOwner !== card" in DOCK
    assert "youtube-nocookie.com/embed/" in DOCK
    assert "?autoplay=1&mute=1&controls=0" in DOCK
    assert 'frame.referrerPolicy = "strict-origin-when-cross-origin"' in DOCK
    assert ".home-card-dock-preview" in HOVER
    assert "pointer-events: none" in HOVER


def test_hover_trailer_reuses_and_persists_the_global_sound_choice():
    trailers = (ROOT / "web/js/features/trailers/index.js").read_text(encoding="utf-8")
    assert '["home-card-dock-preview", "home-card-dock-mute"]' in trailers
    assert "setFpDetailHeroTrailerMuted(!muted, { persist: true })" in DOCK
    assert "setFpDetailHeroTrailerMuted(" in DOCK
    assert "cancelHomeCardDockPreview();" in DOCK
