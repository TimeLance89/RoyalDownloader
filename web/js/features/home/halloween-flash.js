import { createScope } from "../../core/lifecycle.js";

/** One isolated lightning strike, then a long random quiet period. Never a frame loop. */
export function createHalloweenFlash(root, {
  getState, random = Math.random, scopeFactory = createScope,
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
    const stage = getState().stage;
    const quiet = stage === 1 ? 35000 : stage === 2 ? 28000 : stage === 3 ? 22000 : 18000;
    const delay = first ? (stage === 1 ? 6500 : 1600) + random() * 1800 : quiet + random() * 16000;
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
