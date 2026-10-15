import { createScope } from "../../core/lifecycle.js";

/** One viewport look-ahead; observes only the currently mounted catalog. */
export function createInfiniteScroll(root, { sentinel, loadNext, retry, retryButton, preload = 1200, trackScrollIntent = false }) {
  let scope, scheduled = false;
  let reveal = false, lastWindowTop = 0, lastRootTop = 0;
  let touchY = null;
  const win = root.ownerDocument.defaultView;
  function run() {
    scheduled = false;
    const options = { reveal };
    reveal = false;
    if (!scope?.active || sentinel.classList.contains("hidden")) return;
    const overflow = win.getComputedStyle(root).overflowY;
    const internal = /(auto|scroll|overlay)/.test(overflow) && root.scrollHeight > root.clientHeight + 1;
    if (internal) {
      if (root.scrollHeight - root.scrollTop - root.clientHeight <= preload) loadNext(options);
    } else if (sentinel.getBoundingClientRect().top <= (win.innerHeight || root.ownerDocument.documentElement.clientHeight) + preload) loadNext(options);
  }
  function onScroll() {
    const windowTop = win.scrollY || 0, rootTop = root.scrollTop || 0;
    reveal ||= windowTop > lastWindowTop || rootTop > lastRootTop;
    lastWindowTop = windowTop;
    lastRootTop = rootTop;
    refresh();
  }
  function onDownwardIntent() {
    reveal = true;
    refresh();
  }
  function refresh() {
    if (!scope?.active || scheduled) return;
    scheduled = true; scope.frame(run);
  }
  return {
    refresh,
    mount() {
      if (scope) return;
      scope = createScope();
      lastWindowTop = win.scrollY || 0;
      lastRootTop = root.scrollTop || 0;
      scope.listen(root, "scroll", onScroll, { passive: true });
      scope.listen(win, "scroll", onScroll, { passive: true });
      if (trackScrollIntent) {
        // At the bottom, wheel/touch input no longer changes scrollTop.
        scope.listen(win, "wheel", event => {
          if (event.deltaY > 0) onDownwardIntent();
        }, { passive: true });
        scope.listen(win, "touchstart", event => {
          touchY = event.touches.length === 1 ? event.touches[0].clientY : null;
        }, { passive: true });
        scope.listen(win, "touchmove", event => {
          const nextY = event.touches.length === 1 ? event.touches[0].clientY : null;
          if (touchY !== null && nextY !== null && nextY < touchY) onDownwardIntent();
          touchY = nextY;
        }, { passive: true });
        scope.listen(win, "keydown", event => {
          if (event.defaultPrevented || event.target?.closest?.("input,textarea,select,[contenteditable]")) return;
          if (["ArrowDown", "PageDown", "End"].includes(event.key)
              || (event.key === " " && !event.shiftKey)) onDownwardIntent();
        });
      }
      scope.listen(win, "resize", refresh, { passive: true });
      if (retryButton) scope.listen(retryButton, "click", retry);
      refresh();
    },
    unmount() { scope?.dispose(); scope = null; scheduled = false; reveal = false; touchY = null; },
  };
}
