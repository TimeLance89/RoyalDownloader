import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Existing compact Home search; its 36-card limit is distinct from global search. */
export function createHomeSearch(root, {
  rememberSearch, homeMovieEntry, homeSeriesEntry, interleaveHomeEntries, uniqueHomeEntries,
  createHomeCard, artwork, refreshJellyfin, client = api,
}) {
  const byId = id => root.querySelector(`#${id}`);
  const data = { scope: "all", query: "", results: [], active: false, loading: false, errors: [] };
  let scope, cancelRequest = () => {}, resume = false;
  function closeSuggestions() {
    byId("home-search-suggestions").hidden = true; byId("home-search").setAttribute("aria-expanded", "false");
  }
  function render() {
    const section = byId("home-search-results"), track = byId("home-search-track"), status = byId("home-search-status");
    section.hidden = !data.active; if (!data.active) return;
    track.replaceChildren(); section.classList.toggle("is-loading", data.loading);
    section.dataset.state = data.loading ? "loading" : data.errors.length && !data.results.length ? "error" : data.results.length ? "ready" : "empty";
    status.textContent = data.loading ? `Suche nach «${data.query}» …`
      : data.errors.length ? `${data.results.length} Treffer · ${data.errors.join(" · ")}` : `${data.results.length} Treffer für «${data.query}»`;
    if (data.loading) {
      for (let index = 0; index < 6; index++) {
        const skeleton = root.ownerDocument.createElement("span"); skeleton.className = "home-card-skeleton"; track.appendChild(skeleton);
      }
    } else if (!data.results.length) {
      const empty = root.ownerDocument.createElement("div"); empty.className = "home-search-empty";
      const title = root.ownerDocument.createElement("strong"), detail = root.ownerDocument.createElement("span");
      title.textContent = data.errors.length ? "Suche nicht verfügbar" : "Nichts gefunden";
      detail.textContent = data.errors.length ? "Bitte versuche es erneut." : "Versuche einen kürzeren Titel, ein Genre oder einen Schauspieler.";
      empty.append(title, detail); track.appendChild(empty);
    } else data.results.forEach((entry, index) => track.appendChild(createHomeCard(entry, 0, index < 4)));
  }
  async function search() {
    if (!scope?.active) return;
    const query = byId("home-search").value.trim();
    closeSuggestions(); if (!query) return;
    cancelRequest(); const current = createScope(); cancelRequest = scope.add(() => current.dispose());
    const release = cancelRequest;
    rememberSearch(query, data.scope); data.query = query; data.active = true; data.loading = true; data.errors = []; render();
    const requests = [];
    if (data.scope !== "series") requests.push(client.get(`/api/movies?${new URLSearchParams({ mode: "search", query })}`, { signal: current.signal, timeoutMs: 0 }).then(value => (value.results || []).map(homeMovieEntry)));
    if (data.scope !== "movie") requests.push(client.get(`/api/series?${new URLSearchParams({ mode: "search", query })}`, { signal: current.signal }).then(value => (value.results || []).map(homeSeriesEntry)));
    try {
      const settled = await Promise.allSettled(requests);
      if (!current.active) return;
      const groups = settled.filter(result => result.status === "fulfilled").map(result => result.value);
      data.errors = settled.filter(result => result.status === "rejected").map(result => result.reason?.message || "Katalog nicht abrufbar");
      data.results = groups.length > 1 ? interleaveHomeEntries(groups[0], groups[1], 36) : uniqueHomeEntries(groups[0] || []).slice(0, 36);
      data.loading = false; render();
      await Promise.allSettled([
        artwork.movies(data.results.filter(entry => entry.kind === "movie").map(entry => entry.item), { render: false, signal: current.signal }),
        artwork.series(data.results.filter(entry => entry.kind === "series").map(entry => entry.item), { render: false, signal: current.signal }),
      ]);
      if (!current.active) return;
      await refreshJellyfin(data.results, null, { signal: current.signal });
      if (current.active) render();
    } finally { release(); }
  }
  function close() {
    cancelRequest(); data.active = false; data.loading = false; data.results = []; resume = false;
    byId("home-search").value = ""; byId("home-search-clear").hidden = true; closeSuggestions(); render();
  }
  return {
    get: () => Object.freeze({ ...data }), search, close, refresh: render,
    mount() {
      if (scope) return; const mounted = scope = createScope();
      const run = () => { void search().catch(error => { if (mounted.active) { data.loading = false; data.errors = [error.message]; render(); } }); };
      scope.listen(byId("home-search-btn"), "click", run);
      scope.listen(byId("home-search-close"), "click", close); scope.listen(byId("home-search-clear"), "click", close);
      scope.listen(byId("home-search"), "input", () => { byId("home-search-clear").hidden = !byId("home-search").value; closeSuggestions(); });
      scope.listen(byId("home-search"), "keydown", event => {
        if (event.key === "Enter") { event.preventDefault(); run(); }
        else if (event.key === "Escape") { event.stopPropagation(); closeSuggestions(); }
      });
      scope.listen(root, "click", event => {
        const button = event.target.closest("[data-home-search-scope]"); if (!button || !root.contains(button)) return;
        data.scope = button.dataset.homeSearchScope;
        root.querySelectorAll("[data-home-search-scope]").forEach(candidate => {
          const active = candidate === button; candidate.classList.toggle("is-active", active); candidate.setAttribute("aria-pressed", String(active));
        });
      });
      render(); if (resume) { resume = false; run(); }
    },
    unmount() { resume = data.loading; cancelRequest(); scope?.dispose(); scope = null; data.loading = false; },
  };
}
