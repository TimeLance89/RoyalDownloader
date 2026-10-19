/** Record actual, sustained Home visibility instead of recording every render.
 * No external telemetry is emitted: the injected record function only updates
 * the existing per-profile, browser-local exposure history.
 */
export function createHomeExposureVisibility(root, {
  record, logicalKey, getOwner, getDay,
  Observer = root.ownerDocument.defaultView?.IntersectionObserver,
  schedule = (callback, delay) => setTimeout(callback, delay),
  cancel = handle => clearTimeout(handle),
  dwellMs = 1500,
}) {
  const doc = root.ownerDocument;
  const tracked = new Map();
  const rails = new Map();
  const committed = new Set();
  let observer = null;
  let active = false;
  let lastHero = null;

  function validPage() {
    return active && doc.visibilityState !== "hidden"
      && root.isConnected !== false && !root.hidden
      && root.getAttribute?.("aria-hidden") !== "true";
  }
  function clearPending(state) {
    if (state.timer != null) cancel(state.timer);
    state.timer = null;
    state.visible = false;
  }
  function stopTracking(element) {
    const previous = tracked.get(element);
    if (!previous) return;
    clearPending(previous);
    observer?.unobserve(element);
    tracked.delete(element);
  }
  function observe(element, lane, entry) {
    if (!observer || !element || !logicalKey(entry)) return;
    const owner = String(getOwner() || "");
    if (!owner) return;
    const key = logicalKey(entry);
    const previous = tracked.get(element);
    if (previous && previous.lane === lane && previous.key === key && previous.owner === owner) return;
    stopTracking(element);
    tracked.set(element, { lane, entry, key, owner, timer: null, visible: false });
    observer.observe(element);
  }
  function observeRail(trackId, lane, entries) {
    const track = root.querySelector("#" + trackId);
    if (!track) return;
    const expected = new Map();
    for (const entry of entries) {
      const item = entry?.item || {};
      const key = entry?.kind === "movie" ? item.slug
        : entry?.kind === "anime" ? (item.provider === "aniworld" ? "aniworld:" : "") + item.id
          : item.base_slug;
      if (key != null) expected.set(entry.kind + ":" + key, entry);
    }
    const present = new Set();
    for (const element of track.children) {
      if (!element.classList?.contains("home-card")) continue;
      const entry = expected.get(element.dataset.kind + ":" + element.dataset.key);
      if (!entry) continue;
      present.add(element);
      observe(element, lane, entry);
    }
    for (const [element, state] of tracked) {
      if (state.trackId === trackId && !present.has(element)) stopTracking(element);
      if (present.has(element)) state.trackId = trackId;
    }
  }
  function syncRail(trackId, lane, entries) {
    rails.set(trackId, { lane, entries: [...entries] });
    if (active) observeRail(trackId, lane, entries);
  }
  function syncHero(candidate) {
    lastHero = candidate;
    const element = root.querySelector("#home-hero");
    if (!element) return;
    if (!candidate?.kind || !candidate?.media) {
      stopTracking(element);
      return;
    }
    const entry = { kind: candidate.kind, item: candidate.media };
    if (active) observe(element, "hero", entry);
  }
  function onIntersections(entries) {
    for (const change of entries) {
      const state = tracked.get(change.target);
      if (!state) continue;
      if (!validPage() || !change.isIntersecting || change.intersectionRatio < 0.6) {
        clearPending(state);
        continue;
      }
      // Crossing 75% while still above 60% is continuous visibility.
      if (state.visible) continue;
      state.visible = true;
      const day = String(getDay());
      const dedupe = [state.owner, day, state.lane, state.key].join("\u0000");
      if (committed.has(dedupe)) continue;
      state.timer = schedule(() => {
        state.timer = null;
        if (committed.has(dedupe) || !state.visible || !validPage() || !change.target.isConnected
            || String(getOwner() || "") !== state.owner || String(getDay()) !== day) return;
        committed.add(dedupe);
        if (committed.size > 600) committed.delete(committed.values().next().value);
        record(state.lane, [state.entry]);
      }, dwellMs);
    }
  }
  function onVisibilityChange() {
    for (const [element, state] of tracked) {
      clearPending(state);
      observer?.unobserve(element);
      if (validPage()) observer?.observe(element);
    }
  }
  return {
    hasSeen(key) {
      const prefix = [String(getOwner() || ""), String(getDay()), ""].join("\u0000");
      return [...committed].some(value => value.startsWith(prefix) && value.endsWith("\u0000" + key));
    },
    syncRail,
    syncHero,
    mount() {
      if (active) return;
      active = true;
      if (!Observer) return; // no false exposure from unsupported browsers
      observer = new Observer(onIntersections, { threshold: [0, 0.6, 0.75] });
      doc.addEventListener("visibilitychange", onVisibilityChange);
      for (const [trackId, { lane, entries }] of rails) observeRail(trackId, lane, entries);
      if (lastHero) syncHero(lastHero);
    },
    unmount() {
      if (!active) return;
      active = false;
      doc.removeEventListener("visibilitychange", onVisibilityChange);
      for (const element of [...tracked.keys()]) stopTracking(element);
      observer?.disconnect();
      observer = null;
    },
  };
}
