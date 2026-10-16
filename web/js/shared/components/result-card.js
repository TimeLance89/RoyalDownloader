import { createScope } from "../../core/lifecycle.js";
import { createCatalogWindow } from "./catalog-window.js";

/** Shared catalog card artwork and keyboard activation, owned by the visible catalog. */
export function createResultCards(document, {
  coverCandidates, mediaCardInitials, scheduleResultPoster, discardPoster, setFpPosterJellyfinBadge, markLanguage,
}) {
  const scopes = new Map(), actions = new WeakMap(), jobs = new WeakMap(), mediaByVisual = new WeakMap();
  const windows = new Map();
  function windowFor(kind) {
    if (!windows.has(kind)) windows.set(kind, createCatalogWindow(document, {
      release(row) {
        for (const image of row.querySelectorAll(".result-card-poster")) {
          jobs.get(image)?.dispose();
          discardPoster(image);
          image.removeAttribute("src");
          image.removeAttribute("srcset");
        }
      },
    }));
    return windows.get(kind);
  }
  function syncResultCardPoster(visual, media) {
    mediaByVisual.set(visual, media);
    const current = visual.querySelector(".result-card-poster:not(.is-pending-poster)");
    // Das Anbieterposter startet sofort. Sobald TMDB ein besseres Poster liefert,
    // wird es parallel geladen und erst nach erfolgreichem Decode ausgetauscht.
    const candidates = coverCandidates(media?.cover_url);
    if (!candidates.length) return;

    const posterKey = candidates.join("\n");
    if (current?.dataset.posterKey === posterKey) return;
    const pending = visual.querySelector(".result-card-poster.is-pending-poster");
    if (pending?.dataset.posterKey === posterKey) return;
    if (pending) { jobs.get(pending)?.dispose(); pending.remove(); }
    const owner = scopes.get(visual.dataset.kind);
    if (!owner?.active) return;

    const image = document.createElement("img");
    image.className = "result-card-poster";
    image.dataset.posterKey = posterKey;
    image.alt = "";
    image.loading = "lazy";
    image.fetchPriority = "auto";
    image.decoding = "async";
    // Auch das allererste Poster bleibt bis zum vollständigen Decode unsichtbar.
    // Der ruhige Platzhalter darunter verhindert progressive Bildaufbauten und
    // helle Zwischenframes beim schnellen Scrollen.
    image.classList.add("is-pending-poster");
    const job = createScope();
    jobs.set(image, job);
    const release = owner.add(() => job.dispose());
    job.add(() => {
      jobs.delete(image); release();
      if (image.classList.contains("is-pending-poster")) { discardPoster(image); image.remove(); }
      else current?.remove();
    });
    job.listen(image, "load", async () => {
      try { await image.decode(); } catch (e) { /* already decoded */ }
      if (!job.active || !image.isConnected) return;
      job.frame(() => {
        if (!image.isConnected) { job.dispose(); return; }
        image.classList.remove("is-pending-poster");
        if (!current?.isConnected) { job.dispose(); return; }
        const removePreviousPoster = () => job.dispose();
        job.listen(image, "transitionend", removePreviousPoster, { once: true });
        job.timeout(removePreviousPoster, 360);
      });
    }, { once: true });
    scheduleResultPoster(image, candidates);
    visual.appendChild(image);
  }

  function createResultCardVisual(media, title, kind, jellyfinStatus = "checking") {
    const visual = document.createElement("span");
    visual.className = "result-card-visual";
    visual.dataset.kind = kind;

    const fallback = document.createElement("span");
    fallback.className = "result-card-fallback";
    fallback.textContent = mediaCardInitials(title);
    visual.appendChild(fallback);

    syncResultCardPoster(visual, media);

    const kindMark = document.createElement("span");
    kindMark.className = "result-card-kind";
    kindMark.textContent = kind === "series" ? "S" : "F";
    const openMark = document.createElement("span");
    openMark.className = "result-card-open";
    openMark.textContent = "↗";
    openMark.setAttribute("aria-hidden", "true");
    visual.append(kindMark, openMark);
    const libraryBadge = document.createElement("span");
    setFpPosterJellyfinBadge(libraryBadge, jellyfinStatus);
    visual.appendChild(libraryBadge);
    markLanguage(kindMark, media);
    return visual;
  }

  function activateResultCard(row, callback, restore) {
    row.tabIndex = 0; row.setAttribute("role", "button"); row.setAttribute("aria-haspopup", "dialog");
    actions.set(row, callback);
    if (restore) windowFor(row.querySelector(".result-card-visual").dataset.kind).track(row, restore);
  }
  function mount(kind, root) {
    if (scopes.get(kind)?.active) return;
    const scope = createScope(); scopes.set(kind, scope);
    function activate(event) {
      for (let row = event.target; row && row !== root; row = row.parentElement) {
        const callback = actions.get(row);
        if (!callback) continue;
        const control = event.target.closest?.("button, a, input, select, textarea");
        if (control && control !== row && row.contains(control)) return;
        if (event.type === "keydown") {
          if (event.target !== row || (event.key !== "Enter" && event.key !== " ")) return;
          event.preventDefault();
        }
        callback(event); return;
      }
    }
    scope.listen(root, "click", activate); scope.listen(root, "keydown", activate);
    windowFor(kind).mount(root.querySelector(kind === "movie" ? "#fp-results" : "#series-results") || root);
    root.querySelectorAll(".result-card-visual").forEach(visual => {
      const media = mediaByVisual.get(visual);
      if (media) syncResultCardPoster(visual, media);
    });
  }
  function unmount(kind) { windows.get(kind)?.unmount(); scopes.get(kind)?.dispose(); scopes.delete(kind); }
  function dispose() { for (const kind of [...scopes.keys()]) unmount(kind); }
  return { mount, unmount, dispose, sync: syncResultCardPoster, create: createResultCardVisual, activate: activateResultCard };
}
