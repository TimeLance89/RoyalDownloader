import { api } from "../../core/api.js";
import { createDialog } from "../../shared/components/dialog.js";
import { renderSelectableMediaCard } from "../../shared/components/media-card.js";
import { createTasteCandidates } from "./taste-candidates.js";

const TASTE_ONBOARDING_MINIMUM = 5;
const TASTE_ONBOARDING_BATCH_SIZE = 20;

export function createTasteOnboarding(root, {
  getUser, acceptUser, homeData, homeAllEntries, homeEntryMedia, homeEntryKey, tasteMetadata,
  onVisibility, onSaved, client = api,
}) {
  const document = root.ownerDocument, byId = id => root.querySelector(`#${id}`);
  const ranking = createTasteCandidates({ homeEntryMedia, homeEntryKey, tasteMetadata });
  let scope, open = false, loading = false, saving = false, exhausted = false, framePending = false;
  let selection = new Map(), seen = new Set(), pool = [];
  const dialog = createDialog(root, { dismissible: false, initialFocus: () => byId("taste-onboarding-more"),
    onClose() { scope = null; framePending = false; loading = false; saving = false; onVisibility(false); },
  });
  function refreshPool() {
    const user = getUser();
    const seed = ranking.hash(String(user?.id || user?.username || "royal"));
    pool = ranking.diverse(homeAllEntries(), seed);
    exhausted = pool.length > 0 && pool.every(item => seen.has(item.key));
  }
  function progress() {
    const count = selection.size;
    byId("taste-onboarding-count").textContent = String(count);
    byId("taste-onboarding-submit").disabled = saving || count < TASTE_ONBOARDING_MINIMUM;
    const meter = root.querySelector(".taste-onboarding-progress");
    meter?.style.setProperty("--taste-progress", `${Math.min(100, count / TASTE_ONBOARDING_MINIMUM * 100)}%`);
    meter?.classList.toggle("is-ready", count >= TASTE_ONBOARDING_MINIMUM);
    byId("taste-onboarding-selected").replaceChildren(...[...selection.values()].map(item => {
      const chip = document.createElement("button"); chip.type = "button"; chip.className = "taste-onboarding-selection";
      chip.textContent = `${item.title} ×`; chip.dataset.key = item.key;
      chip.setAttribute("aria-label", `${item.title} aus Auswahl entfernen`); return chip;
    }));
  }
  function loadState() {
    const more = byId("taste-onboarding-more");
    more.disabled = saving || loading || (exhausted && pool.length > 0);
    more.textContent = loading ? "Titel werden geladen …" : exhausted ? pool.length ? "Alle Titel angezeigt" : "Erneut laden" : "Weitere Titel laden";
  }
  function setStatus(message, state) {
    const status = byId("taste-onboarding-status");
    status.textContent = message; status.hidden = !message; root.dataset.state = state;
  }
  function append({ reveal = false } = {}) {
    if (!scope?.active || loading || exhausted) return;
    if (!pool.length) refreshPool();
    const candidates = pool.filter(item => !seen.has(item.key)).slice(0, TASTE_ONBOARDING_BATCH_SIZE);
    if (!candidates.length) {
      exhausted = true;
      setStatus(pool.length ? "" : "Der Katalog ist gerade nicht verfügbar. Bitte versuche es gleich erneut.", pool.length ? "ready" : "empty");
      loadState(); return;
    }
    const fragment = document.createDocumentFragment(); let first;
    for (const item of candidates) {
      seen.add(item.key);
      const card = renderSelectableMediaCard(document, item, { selected: selection.has(item.key) });
      first ||= card; fragment.append(card);
    }
    byId("taste-onboarding-grid").append(fragment);
    exhausted = pool.every(item => seen.has(item.key));
    setStatus("", "ready"); loadState();
    if (reveal) first?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function onScroll() {
    if (!scope?.active || framePending) return;
    framePending = true;
    scope.frame(() => {
      framePending = false;
      const grid = byId("taste-onboarding-grid");
      if (!loading && !exhausted && grid.scrollHeight - grid.scrollTop - grid.clientHeight < Math.max(520, grid.clientHeight * .7)) append();
    });
  }
  async function loadCatalog() {
    if (!scope?.active || loading) return;
    const current = scope; loading = true; setStatus("Dein Katalog wird geladen …", "loading"); loadState();
    try {
      // The shared data owner deduplicates an already running bootstrap request.
      await homeData.load();
      if (!current.active) return;
      loading = false; refreshPool(); exhausted = false; append();
    } catch (error) {
      if (!current.active) return;
      loading = false; exhausted = true;
      setStatus(`Katalog konnte nicht geladen werden: ${error.message}`, "error"); loadState();
    }
  }
  async function complete() {
    if (!scope?.active || saving || selection.size < TASTE_ONBOARDING_MINIMUM) return;
    const current = scope; saving = true; progress(); loadState();
    setStatus("Dein Royal-Profil wird vorbereitet …", "loading");
    try {
      const result = await client.post("/api/taste/onboarding", { items: [...selection.values()].map(item => ({
        item_key: item.key, title: item.title, media_type: item.kind, metadata: item.metadata,
      })) }, { signal: current.signal });
      if (!current.active) return;
      acceptUser(result.user); close(); onSaved(result.profile);
    } catch (error) {
      if (!current.active) return;
      saving = false; setStatus(error.message, "error"); progress(); loadState();
    }
  }
  function select(item, remove = false) {
    if (!item || saving) return;
    if (remove || selection.has(item.key)) selection.delete(item.key); else selection.set(item.key, item);
    const card = byId("taste-onboarding-grid").querySelector(`[data-key="${CSS.escape(item.key)}"]`);
    const selected = selection.has(item.key);
    card?.classList.toggle("is-selected", selected); card?.setAttribute("aria-pressed", String(selected));
    card?.setAttribute("aria-label", `${item.title} ${selected ? "ausgewählt" : "auswählen"}`); progress();
  }
  function mount() {
    if (!open || scope?.active) return;
    scope = dialog.open(); const current = scope; onVisibility(true);
    progress(); loadState();
    const grid = byId("taste-onboarding-grid");
    scope.listen(grid, "scroll", onScroll, { passive: true });
    scope.listen(grid, "click", event => { const key = event.target.closest(".taste-onboarding-card")?.dataset.key; select(pool.find(item => item.key === key)); });
    scope.listen(grid, "error", event => { if (event.target.tagName === "IMG") event.target.remove(); }, true);
    scope.listen(byId("taste-onboarding-selected"), "click", event => select(selection.get(event.target.closest("[data-key]")?.dataset.key), true));
    scope.listen(byId("taste-onboarding-more"), "click", () => { if (exhausted && !pool.length) void loadCatalog(); else append({ reveal: true }); });
    scope.listen(byId("taste-onboarding-submit"), "click", complete);
    if (homeAllEntries().length) { refreshPool(); append(); } else void loadCatalog();
    void homeData.warm().then(() => {
      if (!current.active) return;
      refreshPool(); loadState(); onScroll();
    });
  }
  function close() { open = false; dialog.close(); }
  return {
    show(user = getUser()) {
      if (!user?.taste_onboarding_required) return false;
      dialog.unmount(); open = true; selection = new Map(); seen = new Set(); pool = []; exhausted = false;
      byId("taste-onboarding-welcome").textContent = `Willkommen, ${user.display_name || user.username}.`;
      byId("taste-onboarding-grid").replaceChildren(); mount(); return true;
    },
    mount, close, unmount: dialog.unmount, refresh() { if (scope?.active) { refreshPool(); append(); } },
  };
}
