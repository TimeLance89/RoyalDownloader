import { createScope } from "../../core/lifecycle.js";

/** One short background flash every ten seconds. Never a frame loop. */
export function createHalloweenFlash(root, {
  getState, scopeFactory = createScope,
  motion = root.ownerDocument.defaultView.matchMedia("(prefers-reduced-motion: reduce)"),
}) {
  const scope = scopeFactory();
  let cancelNext = null, cancelEnd = null, first = true;
  const active = () => scope.active && getState().active && !motion.matches;
  function stop() {
    cancelNext?.(); cancelEnd?.();
    cancelNext = null; cancelEnd = null;
    delete root.dataset.eventLightning;
  }
  function queue() {
    if (!active() || cancelNext || cancelEnd) return;
    const delay = first ? 1800 : 9640; // Including the 360 ms cleanup: ten seconds between starts.
    cancelNext = scope.timeout(() => {
      cancelNext = null;
      if (!active()) return;
      first = false;
      root.dataset.eventLightning = "true";
      cancelEnd = scope.timeout(() => {
        cancelEnd = null;
        delete root.dataset.eventLightning;
        queue();
      }, 360);
    }, delay);
  }
  function sync() { if (!active()) stop(); else queue(); }
  scope.listen(motion, "change", sync);
  return {
    sync,
    dispose() { stop(); scope.dispose(); },
  };
}
