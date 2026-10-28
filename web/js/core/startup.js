import { createScope } from "./lifecycle.js";
import { api } from "./api.js";

/** Session bootstrap. Data owners cancel their own transport on session end. */
export function createStartup({ homeData, genres, onInitial, onLoaded, onError, onMediaCenter = () => {} }) {
  let started = false, scope = createScope();
  function start() {
    if (started || !scope.active) return;
    started = true;
    const current = scope;
    void api.get("/api/media-center/status", { signal: current.signal }).then(value => {
      if (current.active) onMediaCenter(value.provider);
    }).catch(error => { if (current.active) console.warn("Mediencenter-Status konnte nicht geladen werden:", error); });
    homeData.restore(); onInitial();
    void genres.refresh().catch(error => { if (current.active) console.warn("Genres konnten nicht geladen werden:", error); });
    void homeData.load().then(() => { if (current.active) onLoaded(); })
      .catch(error => { if (current.active) onError(error); });
  }
  return { start, mount() { if (!scope.active) scope = createScope(); }, unmount() { scope.dispose(); } };
}
