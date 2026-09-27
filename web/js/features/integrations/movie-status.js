import { createScope } from "../../core/lifecycle.js";

/** Deduplicates movie availability batches; view/dialog exit cancels queued work. */
export function createMovieStatus({ movieState, refreshCatalogJellyfinStatus, homeMovieEntry,
  homeMovieBySlug, updateFpJellyfinBadges, setFpDetailJellyfinStatus }) {
  const fpJellyfinPending = new Map();
  let fpJellyfinWorker = null, owner = null, active = true;
  async function drainFpJellyfinQueue(owner) {
    while (owner.active && fpJellyfinPending.size) {
      const targets = [...fpJellyfinPending.values()].slice(0, 100);
      targets.forEach((item) => fpJellyfinPending.delete(item.slug));
      try {
        await refreshCatalogJellyfinStatus(targets.map(homeMovieEntry), null, { signal: owner.signal });
        if (!owner.active) return;
        updateFpJellyfinBadges();
      } catch (e) {
        if (owner.active && targets.some((item) => item.slug === movieState.selectedSlug)) {
          setFpDetailJellyfinStatus("unavailable");
        }
      }
    }
  }

  function refreshFpJellyfinStatus(items = null, { signal } = {}) {
    if (!active) return Promise.resolve();
    // Detail navigation must not queue behind an unrelated catalog batch.
    if (signal) return refreshCatalogJellyfinStatus(items.map(homeMovieEntry), null, { signal })
      .then(() => { if (active && !signal.aborted) updateFpJellyfinBadges(); });
    const targets = Array.isArray(items) ? [...items] : [...movieState.results];
    if (!items) {
      const selectedHomeMovie = homeMovieBySlug(movieState.selectedSlug);
      if (selectedHomeMovie && !targets.some((item) => item.slug === selectedHomeMovie.slug)) {
        targets.push(selectedHomeMovie);
      }
    }
    for (const item of targets) {
      if (item?.slug) fpJellyfinPending.set(item.slug, item);
    }
    if (!fpJellyfinPending.size || fpJellyfinWorker) return fpJellyfinWorker;
    owner = createScope();
    const current = owner;
    const work = drainFpJellyfinQueue(current).finally(() => {
      current.dispose();
      if (owner === current) { owner = null; fpJellyfinWorker = null; }
    });
    fpJellyfinWorker = work;
    return fpJellyfinWorker;
  }

  function cancel() { owner?.dispose(); owner = null; fpJellyfinWorker = null; fpJellyfinPending.clear(); }
  return { refresh: refreshFpJellyfinStatus, cancel, mount() { active = true; }, unmount() { active = false; cancel(); } };
}
