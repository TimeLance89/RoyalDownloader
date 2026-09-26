import { createScope } from "../../core/lifecycle.js";

/** Reusable looped carousel; state holds only scroll offsets/targets. */
export function createCarousel(root, localState = { railScrollPositions: {}, railScrollTargets: {} }) {
  const state = { home: localState };
  let scope;
const HOME_RAIL_SCROLL_STEP_RATIO = 0.68;
const HOME_RAIL_WHEEL_FACTOR = 0.78;
const homeRailSettleTimers = new Map();

function setHomeRailCycleAccessibility(element, cycle) {
  const interactive = element.querySelectorAll?.("a, button, input, select, textarea, [tabindex]") || [];
  const duplicate = cycle !== 1;
  if (duplicate) element.setAttribute?.("aria-hidden", "true");
  else element.removeAttribute?.("aria-hidden");
  interactive.forEach((control) => {
    if (duplicate) {
      if (!control.hasAttribute("data-home-loop-tabindex")) {
        control.setAttribute("data-home-loop-tabindex", control.getAttribute("tabindex") ?? "");
      }
      control.setAttribute("tabindex", "-1");
    } else if (control.hasAttribute("data-home-loop-tabindex")) {
      const previous = control.getAttribute("data-home-loop-tabindex");
      if (previous) control.setAttribute("tabindex", previous);
      else control.removeAttribute("tabindex");
      control.removeAttribute("data-home-loop-tabindex");
    }
  });
}

function homeRailLoopSize(track) {
  const count = Number(track?.dataset?.homeLoopCount || 0);
  if (!track || count < 2) return 0;
  const first = track.children[0];
  const repeated = track.children[count];
  const measured = Number(repeated?.offsetLeft) - Number(first?.offsetLeft);
  return measured > 0 ? measured : track.scrollWidth / 3;
}

function normalizeHomeRailLoop(track, { forceMiddle = false } = {}) {
  const size = homeRailLoopSize(track);
  if (!size) return 0;
  let next = track.scrollLeft;
  if (forceMiddle && next < size * 0.5) next += size;
  while (next < size * 0.2) next += size;
  while (next > size * 1.8) next -= size;
  if (Math.abs(next - track.scrollLeft) > 1) track.scrollLeft = next;
  return size;
}

function prepareHomeRailLoop(track, logicalCount) {
  if (!track) return;
  track.dataset ||= {};
  const wasLooping = Number(track.dataset.homeLoopCount || 0) > 1;
  track.dataset.homeLoopCount = logicalCount > 1 ? String(logicalCount) : "0";
  if (logicalCount < 2) {
    if (wasLooping) {
      track.scrollLeft = 0;
      delete state.home.railScrollPositions?.[track.id];
      delete state.home.railScrollTargets?.[track.id];
    }
    delete track.dataset.homeLoopReady;
    return;
  }
  const position = () => {
    if (track.dataset.homeLoopReady !== "true") {
      normalizeHomeRailLoop(track, { forceMiddle: true });
      track.dataset.homeLoopReady = "true";
    } else {
      normalizeHomeRailLoop(track);
    }
  };
  position();
  if (scope) scope.frame(position);
}

function updateHomeRailNavigation(track) {
  if (!track?.id) return;
  const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
  const canScroll = maxScroll > 2;
  const looping = Number(track.dataset.homeLoopCount || 0) > 1;
  const atStart = track.scrollLeft <= 2;
  const atEnd = track.scrollLeft >= maxScroll - 2;
  root.querySelectorAll(`[data-home-scroll="${CSS.escape(track.id)}"]`).forEach((button) => {
    const direction = Number(button.dataset.direction) || 1;
    button.hidden = !canScroll || (!looping && (direction < 0 ? atStart : atEnd));
  });
}

function homeRailStoredScroll(track, fallback = 0) {
  const target = Number(state.home.railScrollTargets?.[track.id]);
  if (Number.isFinite(target)) return target;
  const stored = Number(state.home.railScrollPositions?.[track.id]);
  return Number.isFinite(stored) ? stored : fallback;
}

function rememberHomeRailScroll(track, { force = false } = {}) {
  if (!track?.id) return;
  state.home.railScrollPositions ||= {};
  state.home.railScrollTargets ||= {};
  const target = Number(state.home.railScrollTargets[track.id]);
  if (!force && Number.isFinite(target)) {
    if (Math.abs(track.scrollLeft - target) <= 3) {
      state.home.railScrollPositions[track.id] = track.scrollLeft;
      delete state.home.railScrollTargets[track.id];
    }
    return;
  }
  state.home.railScrollPositions[track.id] = track.scrollLeft;
}

function rememberAllHomeRailScroll() {
  root.querySelectorAll(".home-track").forEach((track) => rememberHomeRailScroll(track));
}

function restoreHomeRailScroll(track, scrollLeft = 0) {
  const desired = homeRailStoredScroll(track, scrollLeft);
  const restore = () => {
    const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
    track.scrollLeft = Math.max(0, Math.min(desired, maximum));
    updateHomeRailNavigation(track);
  };
  restore();
  if (scope) scope.frame(restore);
}

function moveHomeRail(button) {
  const track = root.querySelector(`#${CSS.escape(button.dataset.homeScroll)}`);
  if (!track) return;
  normalizeHomeRailLoop(track, { forceMiddle: true });
  const direction = Number(button.dataset.direction) || 1;
  const distance = Math.max(260, track.clientWidth * HOME_RAIL_SCROLL_STEP_RATIO);
  const requested = track.scrollLeft + direction * distance;
  const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
  const target = homeRailLoopSize(track)
    ? requested
    : Math.max(0, Math.min(requested, maximum));
  state.home.railScrollTargets ||= {};
  state.home.railScrollPositions ||= {};
  // Das Ziel muss vor dem asynchronen Smooth-Scroll feststehen. Andernfalls
  // kann ein Poster-Update im selben Frame noch den alten Wert 0 konservieren.
  state.home.railScrollTargets[track.id] = target;
  state.home.railScrollPositions[track.id] = target;
  track.dataset.homeLoopAnimating = "true";
  const reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  track.scrollTo({ left: target, behavior: reducedMotion ? "auto" : "smooth" });
  scheduleHomeRailSettle(track, 700);
}

function scheduleHomeRailSettle(track, delay = 140) {
  const previous = homeRailSettleTimers.get(track);
  if (previous) previous();
  const timer = scope?.timeout(() => {
    homeRailSettleTimers.delete(track);
    delete track.dataset.homeLoopAnimating;
    normalizeHomeRailLoop(track);
    delete state.home.railScrollTargets?.[track.id];
    rememberHomeRailScroll(track, { force: true });
  }, delay);
  homeRailSettleTimers.set(track, timer);
}

function initHomeRailScrolling() {
  if (scope) return;
  scope = createScope();
  const home = root;
  scope.listen(home, "click", (event) => {
    const button = event.target.closest("[data-home-scroll]");
    if (button) moveHomeRail(button);
  });
  scope.listen(home, "scroll", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track) return;
    if (track.dataset.homeLoopAnimating === "true") scheduleHomeRailSettle(track);
    else normalizeHomeRailLoop(track);
    rememberHomeRailScroll(track);
    updateHomeRailNavigation(track);
  }, true);
  scope.listen(home, "wheel", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track?.id) return;
    delete state.home.railScrollTargets?.[track.id];
    const horizontalDelta = Math.abs(event.deltaX) > Math.abs(event.deltaY)
      ? event.deltaX
      : event.shiftKey ? event.deltaY : 0;
    if (!horizontalDelta) return;
    event.preventDefault();
    track.scrollLeft += horizontalDelta * HOME_RAIL_WHEEL_FACTOR;
    normalizeHomeRailLoop(track);
  }, { passive: false, capture: true });
  scope.listen(home, "pointerdown", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track?.id || event.target.closest?.("[data-home-scroll]")) return;
    delete state.home.railScrollTargets?.[track.id];
    normalizeHomeRailLoop(track, { forceMiddle: true });
  }, true);
}

  return {
    mount: initHomeRailScrolling,
    unmount() {
      rememberAllHomeRailScroll();
      scope?.dispose(); scope = null;
      homeRailSettleTimers.clear();
      root.querySelectorAll(".home-track").forEach(track => { delete track.dataset.homeLoopAnimating; });
    },
    setHomeRailCycleAccessibility,
    homeRailLoopSize,
    normalizeHomeRailLoop,
    prepareHomeRailLoop,
    updateHomeRailNavigation,
    homeRailStoredScroll,
    rememberHomeRailScroll,
    rememberAllHomeRailScroll,
    restoreHomeRailScroll,
    moveHomeRail,
    scheduleHomeRailSettle,
  };
}
