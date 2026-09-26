import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { createLibraryView } from "./view.js";
import { libraryVisibleItems } from "./model.js";

/** View-local filters and selection; persistent subscriptions belong to the service. */
export function createLibrary(root, { subscriptions, checkResultText, refreshQueue, client = api, ...presentation }) {
  const ui = { selected: new Set(), filter: "all", query: "", draftQuery: "", sort: "attention", view: "grid", heroBaseSlug: "", feedback: "", removing: false };
  const view = createLibraryView(root, { subscriptions, ui, ...presentation });
  const byId = id => root.querySelector(`#${id}`);
  let scope;
  function refresh() { if (scope?.active) view.render(); }
  async function check(slugs, message) {
    const current = scope;
    if (!current?.active || subscriptions.get().checkRunning) return;
    ui.feedback = message;
    refresh();
    try {
      const data = await subscriptions.check(slugs, { signal: current.signal });
      if (current.active) ui.feedback = checkResultText(data);
    } catch (error) {
      if (current.active && !isAbortError(error)) ui.feedback = `Prüfung fehlgeschlagen: ${error.message}`;
    } finally { if (current.active) refresh(); }
  }
  async function remove() {
    const current = scope;
    if (!current?.active || ui.removing || !ui.selected.size) return;
    const count = ui.selected.size;
    if (!window.confirm(`${count} ${count === 1 ? "Abo" : "Abos"} wirklich entfernen?`)) return;
    ui.removing = true;
    refresh();
    const version = subscriptions.revision;
    try {
      const data = await client.post("/api/watchlist/remove", { base_slugs: [...ui.selected] }, { signal: current.signal });
      if (!current.active) return;
      ui.selected.clear();
      if (version === subscriptions.revision) subscriptions.accept(data);
      else await subscriptions.refresh({ signal: current.signal, force: true });
      if (current.active) await refreshQueue();
    } catch (error) {
      if (current.active && !isAbortError(error)) ui.feedback = `Entfernen fehlgeschlagen: ${error.message}`;
    } finally { if (current.active) { ui.removing = false; refresh(); } }
  }
  return {
    refresh,
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.add(subscriptions.subscribe(refresh));
      const listen = (id, event, handler) => scope.listen(byId(id), event, handler);
      listen("wl-hero-open", "click", () => { if (ui.heroBaseSlug) presentation.openWatchlistEntry(ui.heroBaseSlug); });
      listen("wl-hero-check", "click", () => { if (ui.heroBaseSlug) void check([ui.heroBaseSlug], "Archivstück wird geprüft …"); });
      for (const button of root.querySelectorAll("[data-library-filter]")) scope.listen(button, "click", () => {
        ui.filter = button.dataset.libraryFilter || "all"; ui.selected.clear(); refresh();
      });
      for (const button of root.querySelectorAll("[data-library-view]")) scope.listen(button, "click", () => {
        ui.view = button.dataset.libraryView || "grid"; refresh();
      });
      listen("wl-search", "input", event => {
        ui.draftQuery = event.currentTarget.value; ui.query = ui.draftQuery.trim(); ui.selected.clear();
        byId("wl-search-clear").hidden = !ui.query; refresh();
      });
      listen("wl-search-form", "submit", event => { event.preventDefault(); ui.query = ui.draftQuery.trim(); refresh(); });
      listen("wl-search-clear", "click", () => {
        ui.query = ""; ui.draftQuery = ""; ui.selected.clear();
        byId("wl-search").value = ""; byId("wl-search-clear").hidden = true; refresh(); byId("wl-search").focus();
      });
      listen("wl-sort", "change", event => { ui.sort = event.currentTarget.value || "attention"; refresh(); });
      listen("wl-select-visible", "click", () => {
        const slugs = libraryVisibleItems(subscriptions.get().items, ui).map(entry => entry.base_slug);
        const selected = slugs.length > 0 && slugs.every(slug => ui.selected.has(slug));
        slugs.forEach(slug => selected ? ui.selected.delete(slug) : ui.selected.add(slug)); refresh();
      });
      listen("wl-check-all", "click", () => { void check(null, `Prüfe ${subscriptions.get().items.length} Serie(n) …`); });
      listen("wl-check-selected", "click", () => {
        if (ui.selected.size) void check([...ui.selected], `Prüfe ${ui.selected.size} Serie(n) …`);
      });
      listen("wl-open", "click", () => { const first = [...ui.selected][0]; if (first) presentation.openWatchlistEntry(first); });
      listen("wl-remove", "click", () => { void remove(); });
      refresh();
      if (!subscriptions.get().loaded) void subscriptions.refresh({ signal: scope.signal });
    },
    unmount() { scope?.dispose(); scope = null; view.dispose(); ui.removing = false; },
  };
}
