import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { halloweenArt } from "./halloween-art.js";

/** Browser-local calendar, inclusive dates; no UTC conversion or fixed year. */
export function seasonalEventAt(date = new Date()) {
  if (date.getMonth() !== 9 || date.getDate() < 28 || date.getDate() > 31) return null;
  return { id: "halloween", stage: date.getDate() - 27 };
}

export function createSeasonalEvents(root, { client = api, now = () => new Date() } = {}) {
  const document = root.ownerDocument, win = document.defaultView;
  let scope = null, enabled = null, cancelMidnight = null, revision = 0;
  function clear() {
    root.querySelector(".home-event-ornaments")?.remove();
    delete root.dataset.seasonalEvent;
    delete root.dataset.eventStage;
  }
  function render() {
    const event = enabled && scope?.active ? seasonalEventAt(now()) : null;
    if (!event) { clear(); return; }
    root.dataset.seasonalEvent = event.id;
    root.dataset.eventStage = String(event.stage);
    const hero = root.querySelector("#home-hero");
    if (!hero) return;
    let panel = hero.querySelector(".home-event-ornaments");
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "home-event-ornaments";
      panel.setAttribute("aria-hidden", "true");
      panel.innerHTML = halloweenArt;
      hero.append(panel);
    }
    panel.querySelectorAll("[data-event-min-stage]").forEach(node => {
      node.hidden = Number(node.dataset.eventMinStage) > event.stage;
    });
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
      refresh();
      void load({ signal: owner.signal }).catch(() => { /* Keep the saved state; decoration never blocks Home. */ });
      owner.listen(document, "visibilitychange", refresh);
      owner.listen(win, "pageshow", refresh);
    },
    unmount() { scope?.dispose(); scope = null; cancelMidnight = null; clear(); },
  };
}
