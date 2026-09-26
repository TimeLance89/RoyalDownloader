import { createScope } from "../../core/lifecycle.js";

/** One viewport look-ahead; observes only the currently mounted catalog. */
export function createInfiniteScroll(root, { sentinel, loadNext, retry, retryButton, preload = 1200 }) {
  let scope, scheduled = false;
  const win = root.ownerDocument.defaultView;
  function run() {
    scheduled = false;
    if (!scope?.active || sentinel.classList.contains("hidden")) return;
    const overflow = win.getComputedStyle(root).overflowY;
    const internal = /(auto|scroll|overlay)/.test(overflow) && root.scrollHeight > root.clientHeight + 1;
    if (internal) {
      if (root.scrollHeight - root.scrollTop - root.clientHeight <= preload) loadNext();
    } else if (sentinel.getBoundingClientRect().top <= (win.innerHeight || root.ownerDocument.documentElement.clientHeight) + preload) loadNext();
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
      scope.listen(root, "scroll", refresh, { passive: true });
      scope.listen(win, "scroll", refresh, { passive: true });
      scope.listen(win, "resize", refresh, { passive: true });
      if (retryButton) scope.listen(retryButton, "click", retry);
      refresh();
    },
    unmount() { scope?.dispose(); scope = null; scheduled = false; },
  };
}
