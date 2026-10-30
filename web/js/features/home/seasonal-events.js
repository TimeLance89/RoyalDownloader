import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { createHalloweenFlash } from "./halloween-flash.js";

/** Browser-local calendar, inclusive dates; no UTC conversion or fixed year. */
export function seasonalEventAt(date = new Date()) {
  if (date.getMonth() !== 9 || date.getDate() < 28 || date.getDate() > 31) return null;
  return { id: "halloween", stage: date.getDate() - 27 };
}

export function createSeasonalEvents(root, { client = api, now = () => new Date() } = {}) {
  const document = root.ownerDocument, win = document.defaultView;
  let scope = null, enabled = null, cancelMidnight = null, revision = 0;
  let flash = null;
  function clear() {
    root.querySelector(".home-event-backdrop")?.remove();
    root.querySelector(".home-event-flash")?.remove();
    delete root.dataset.seasonalEvent;
    delete root.dataset.eventStage;
    flash?.sync();
  }
  function render() {
    const event = enabled && scope?.active ? seasonalEventAt(now()) : null;
    if (!event) { clear(); return; }
    root.dataset.seasonalEvent = event.id;
    root.dataset.eventStage = String(event.stage);
    if (!root.querySelector(".home-event-backdrop")) {
      const backdrop = document.createElement("div");
      backdrop.className = "home-event-backdrop";
      backdrop.setAttribute("aria-hidden", "true");
      const image = document.createElement("img");
      image.src = "/assets/events/storm-clouds.jpg";
      image.alt = "";
      image.decoding = "async";
      backdrop.append(image);
      root.append(backdrop);
    }
    if (!root.querySelector(".home-event-flash")) {
      const weather = document.createElement("div");
      weather.className = "home-event-flash";
      weather.setAttribute("aria-hidden", "true");
      const light = document.createElement("span");
      light.className = "event-lightning-flash";
      weather.append(light);
      root.append(weather);
    }
    flash?.sync();
  }
  function refresh() {
    cancelMidnight?.(); cancelMidnight = null;
    render();
    if (!scope?.active || document.hidden || !enabled) return;
    const date = now();
    const midnight = new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1);
    cancelMidnight = scope.timeout(refresh, Math.max(1000, midnight - date + 50));
  }
  async function load({ signal } = {}) {
    const version = revision;
    const value = await client.get("/api/ui/events", { signal });
    if (typeof value.enabled !== "boolean") throw new Error("Events konnten nicht geladen werden. / Could not load events.");
    if (!signal?.aborted && version === revision) {
      enabled = value.enabled;
      refresh();
    }
    return enabled;
  }
  async function save(value, { signal } = {}) {
    ++revision; // A pending initial read cannot undo a saved preference.
    const result = await client.post("/api/ui/events", { enabled: value }, { signal });
    if (!signal?.aborted) { enabled = result.enabled; refresh(); }
    return enabled;
  }
  return {
    load, save, refresh,
    get enabled() { return enabled; },
    mount() {
      if (scope?.active) return;
      scope = createScope();
      const owner = scope;
      flash = createHalloweenFlash(root, { getState: () => ({
        active: Boolean(owner.active && enabled && !document.hidden && seasonalEventAt(now()) && root.querySelector(".home-event-flash")),
      }) });
      owner.add(() => { flash?.dispose(); flash = null; });
      refresh();
      void load({ signal: owner.signal }).catch(() => { /* Keep the saved state; decoration never blocks Home. */ });
      owner.listen(document, "visibilitychange", refresh);
      owner.listen(win, "pageshow", refresh);
    },
    unmount() { scope?.dispose(); scope = null; cancelMidnight = null; clear(); },
  };
}
