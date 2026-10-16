/** Release offscreen card contents; lightweight slots preserve grid and scroll position. */
export function createCatalogWindow(document, { release }) {
  const records = new WeakMap(), live = new Set();
  const win = document.defaultView;
  let observer = null, removals = null, root = null;
  let version = 0;

  function suspend(row) {
    if (!live.has(row) || row.contains(document.activeElement)) return;
    const copy = row.querySelector(".result-card-copy");
    const height = copy?.getBoundingClientRect().height || 88;
    row.style.setProperty("--catalog-copy-height", `${height}px`);
    release(row);
    row.replaceChildren();
    row.classList.add("is-catalog-placeholder");
    live.delete(row);
  }

  function restore(row) {
    const build = records.get(row);
    if (!build || live.has(row)) return;
    const fresh = build();
    row.className = fresh.className;
    for (const name of ["aria-current", "aria-busy", "aria-label"]) {
      const value = fresh.getAttribute(name);
      if (value === null) row.removeAttribute(name);
      else row.setAttribute(name, value);
    }
    row.replaceChildren(...fresh.childNodes);
    live.add(row);
  }

  function onFocus(event) {
    const row = event.target.closest?.(".result-card");
    if (row && root?.contains(row)) restore(row);
  }

  return {
    track(row, build) {
      if (!win?.IntersectionObserver) return;
      records.set(row, build);
      live.add(row);
      observer?.observe(row);
    },
    mount(shelf) {
      if (root || !win?.IntersectionObserver) return;
      root = shelf;
      const mounted = ++version;
      observer = new win.IntersectionObserver(entries => {
        if (mounted !== version) return;
        for (const entry of entries) {
          if (!entry.target.isConnected) { observer.unobserve(entry.target); live.delete(entry.target); continue; }
          if (entry.isIntersecting) restore(entry.target);
          else suspend(entry.target);
        }
      }, { root: null, rootMargin: "800px 0px", threshold: 0 });
      if (win.MutationObserver) {
        removals = new win.MutationObserver(changes => {
          if (mounted !== version) return;
          for (const change of changes) for (const row of change.removedNodes) {
            if (!records.has(row) || root.contains(row)) continue;
            observer.unobserve(row);
            if (live.delete(row)) release(row);
          }
        });
        removals.observe(root, { childList: true });
      }
      root.addEventListener("focusin", onFocus);
      for (const row of root.querySelectorAll(".result-card")) {
        if (records.has(row)) observer.observe(row);
      }
    },
    unmount() {
      if (!root) return;
      version++;
      observer?.disconnect(); removals?.disconnect();
      root?.removeEventListener("focusin", onFocus);
      for (const row of [...live]) suspend(row);
      observer = null; removals = null; root = null;
    },
  };
}
