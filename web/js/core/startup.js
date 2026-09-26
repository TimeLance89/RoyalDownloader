import { createScope } from "./lifecycle.js";

/** Session bootstrap. Data owners cancel their own transport on session end. */
export function createStartup({ homeData, genres, onInitial, onLoaded, onError }) {
  let started = false, scope = createScope();
  function start() {
    if (started || !scope.active) return;
    started = true;
    const current = scope;
    homeData.restore(); onInitial();
    void genres.refresh().catch(error => { if (current.active) console.warn("Genres konnten nicht geladen werden:", error); });
    void homeData.load().then(() => { if (current.active) onLoaded(); })
      .catch(error => { if (current.active) onError(error); });
  }
  return { start, mount() { if (!scope.active) scope = createScope(); }, unmount() { scope.dispose(); } };
}
