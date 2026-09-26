import { createScope } from "../../core/lifecycle.js";

/** Shared lazy card imagery; no request or listener survives the application session. */
export function createCardArtwork(root, { window = root.ownerDocument.defaultView } = {}) {
  const states = new WeakMap();
  let scope = null, observer = null;
  function start(image, priority = "auto") {
    const artwork = states.get(image);
    if (!scope?.active || !artwork || artwork.started || !artwork.candidates.length) return;
    artwork.started = true;
    image.loading = "eager";
    image.fetchPriority = priority;
    const candidate = artwork.candidates[artwork.index];
    image.classList.toggle("is-poster-fallback", candidate.posterFallback);
    image.src = candidate.url;
    observer?.unobserve(image);
  }
  function observe(image) {
    const artwork = states.get(image);
    if (!scope?.active || !artwork || artwork.started) return;
    if (observer) observer.observe(image);
    else start(image);
  }
  function failed(image) {
    const artwork = states.get(image);
    if (!artwork || !artwork.started) return;
    artwork.index++;
    if (artwork.index >= artwork.candidates.length) {
      states.delete(image); observer?.unobserve(image); image.remove(); return;
    }
    artwork.started = false;
    start(image, image.fetchPriority);
  }
  function mount() {
    if (scope?.active) return;
    scope = createScope();
    const mounted = scope;
    if (window.IntersectionObserver) {
      observer = new window.IntersectionObserver(entries => {
        if (!mounted.active) return;
        for (const entry of entries) {
          if (!entry.target.isConnected) { observer.unobserve(entry.target); continue; }
          if (entry.isIntersecting) start(entry.target, entry.intersectionRatio > 0 ? "high" : "auto");
        }
      }, { root: null, rootMargin: "480px 520px", threshold: 0.01 });
      scope.observe(observer);
    }
    scope.listen(root, "error", event => failed(event.target), true);
    const images = node => node.matches?.("img") ? [node] : [...(node.querySelectorAll?.("img") || [])];
    if (window.MutationObserver) {
      const removals = new window.MutationObserver(records => {
        if (!mounted.active) return;
        for (const record of records) for (const node of record.removedNodes) {
          for (const image of images(node)) if (!root.contains(image)) observer?.unobserve(image);
        }
      });
      removals.observe(root, { subtree: true, childList: true }); scope.observe(removals);
    }
    for (const image of root.querySelectorAll(".home-card-art img, .result-card-poster")) {
      if (states.get(image)?.started && image.complete && !image.naturalWidth) failed(image);
      else observe(image);
    }
  }
  return {
    mount, start,
    set(image, candidates, { eager = false } = {}) {
      states.set(image, { candidates: [...candidates], index: 0, started: false });
      if (eager) start(image); else observe(image);
    },
    discard(image) { observer?.unobserve(image); states.delete(image); },
    unmount() { scope?.dispose(); scope = null; observer = null; },
  };
}
