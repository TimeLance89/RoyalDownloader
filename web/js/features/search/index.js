import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createSearch(page, shell, {
  client = api, createHomeCard, mediaJellyfinStatus, rememberSearch, uniqueHomeContentEntries,
  uniqueHomeEntries, homeCollectionEntry, homeMovieEntry, homeSeriesEntry, homeAnimeEntry,
  hydrateHomeMovieArtwork, hydrateHomeSeriesArtwork, refreshCatalogJellyfinStatus, mediaDetailModalOpen,
}) {
  const data = { query: "", results: [], active: false, loading: false, requestSeq: 0,
    scope: "all", jellyfinOnly: false, submitted: false, failures: [], pendingCatalogs: [] };
  const byId = id => page.querySelector(`#${id}`) || shell.querySelector(`#${id}`);
  const input = byId("global-search-input");
  const toggle = byId("global-search-toggle");
  let scope;
  let cancelQuery = () => {};
  const CATALOGS = [
    { key: "collection", label: "Filmreihen", load: (query, signal) => client.get(`/api/movie-collections?${new URLSearchParams({ query })}`, { signal }).then(data => (data.results || []).map(homeCollectionEntry)) },
    { key: "movie", label: "Filme", load: (query, signal) => client.get(`/api/movies?${new URLSearchParams({ mode: "search", query })}`, { signal, timeoutMs: 0 }).then(data => (data.results || []).map(homeMovieEntry)) },
    { key: "series", label: "Serien", load: (query, signal) => client.get(`/api/series?${new URLSearchParams({ mode: "search", query })}`, { signal }).then(data => (data.results || []).map(homeSeriesEntry)) },
    { key: "anime", label: "Anime", load: (query, signal) => client.get(`/api/anime?${new URLSearchParams({ mode: "search", query, page: 1 })}`, { signal }).then(data => (data.results || []).map(homeAnimeEntry)) },
  ];
  function uniqueCatalogContentEntries(entries) {
    // Provider-Slugs/Base-Slugs sind technische Quellen-IDs und keine
    // Inhaltsidentität. Innerhalb eines Katalogs deshalb TMDB bzw.
    // normalisierten Titel + Jahr verwenden. Die Gruppen bleiben absichtlich
    // getrennt, damit z. B. ein Anime nicht versehentlich mit einer gleich
    // benannten normalen Serie zusammenfällt.
    if (typeof uniqueHomeContentEntries === "function") {
      return uniqueHomeContentEntries(entries);
    }
    return uniqueHomeEntries(entries);
  }

  function mergeCatalogGroups(groups) {
    const ordered = CATALOGS
      .map((catalog) => uniqueCatalogContentEntries(groups.get(catalog.key) || []))
      .filter((group) => group.length);
    const mixed = [];
    const max = Math.max(0, ...ordered.map((group) => group.length));
    for (let index = 0; index < max; index += 1) {
      ordered.forEach((group) => {
        if (group[index]) mixed.push(group[index]);
      });
    }
    return uniqueHomeEntries(mixed);
  }

  async function performGlobalSearch(query, requestId, current) {
    rememberSearch(query, "all");
    const groups = new Map();
    data.failures = [];
    data.pendingCatalogs = CATALOGS.map((catalog) => catalog.label);
    renderGlobalSearchResults();

    const settleCatalog = async (catalog) => {
      try {
        groups.set(catalog.key, await catalog.load(query, current.signal));
      } catch (error) {
        if (!current.active || requestId !== data.requestSeq) return;
        data.failures.push({
          key: catalog.key,
          label: catalog.label,
          message: error?.message || "nicht erreichbar",
        });
        console.warn(`${catalog.label}-Suche fehlgeschlagen:`, error);
      } finally {
        if (!current.active || requestId !== data.requestSeq) return;
        data.pendingCatalogs = data.pendingCatalogs
          .filter((label) => label !== catalog.label);
        data.results = mergeCatalogGroups(groups);
        // Ein leer beantworteter schneller Katalog ist noch kein endgültiges
        // "nichts gefunden". Solange weitere Kataloge laufen und noch kein
        // Treffer vorliegt, bleibt der echte Loading-/Skeleton-Zustand aktiv.
        // Sobald irgendein Treffer da ist, zeigen wir ihn dagegen sofort und
        // ergänzen die langsameren Kataloge progressiv im Hintergrund.
        data.loading = data.results.length === 0
          && data.pendingCatalogs.length > 0;
        renderGlobalSearchResults();
      }
    };

    await Promise.all(CATALOGS.map(settleCatalog));
    if (!current.active || requestId !== data.requestSeq) return;

    data.results = mergeCatalogGroups(groups);
    data.loading = false;
    renderGlobalSearchResults();

    await Promise.allSettled([
      hydrateHomeMovieArtwork(
        data.results
          .filter((entry) => entry.kind === "movie")
          .map((entry) => entry.item),
        { render: false, signal: current.signal },
      ),
      hydrateHomeSeriesArtwork(
        data.results
          .filter((entry) => entry.kind === "series")
          .map((entry) => entry.item),
        { render: false, signal: current.signal },
      ),
    ]);
    if (!current.active || requestId !== data.requestSeq) return;

    // Durch die Artwork-/TMDB-Anreicherung kann eine zuvor noch nicht
    // erkennbare Provider-Dublette jetzt eine eindeutige Inhalts-ID besitzen.
    // Deshalb nach der Metadatenphase noch einmal über dieselben Rohgruppen
    // deduplizieren, bevor Jellyfin abgefragt und final gerendert wird.
    data.results = mergeCatalogGroups(groups);
    await refreshCatalogJellyfinStatus(
      data.results.filter((entry) => entry.kind !== "collection"),
      null, { signal: current.signal },
    );
    if (!current.active || requestId !== data.requestSeq) return;
    renderGlobalSearchResults();
  }

  function renderGlobalSearchResults() {
    const grid = byId("global-search-grid");
    const status = byId("global-search-status");
    const clear = byId("global-search-clear");
    if (!page || !grid || !status || !shell || !input || !clear || !toggle) return;

    page.hidden = !data.active;
    page.ownerDocument.body.classList.toggle("global-search-open", data.active);
    shell.classList.toggle("has-value", Boolean(input.value));
    clear.hidden = !input.value;
    toggle.setAttribute("aria-expanded", String(data.active || page.ownerDocument.activeElement === input));
    if (!data.active) return;

    grid.replaceChildren();
    const visibleResults = data.results.filter((entry) => {
      const scopeMatches = data.scope === "all" || entry.kind === data.scope;
      const libraryMatches = !data.jellyfinOnly || mediaJellyfinStatus(entry.item) === "owned";
      return scopeMatches && libraryMatches;
    });
    page.querySelectorAll("[data-global-search-scope]").forEach((button) => {
      const active = button.dataset.globalSearchScope === data.scope;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const libraryFilter = byId("global-search-jellyfin");
    if (libraryFilter) {
      libraryFilter.classList.toggle("is-active", data.jellyfinOnly);
      libraryFilter.setAttribute("aria-pressed", String(data.jellyfinOnly));
    }
    const jellyfinCount = data.results.filter(
      (entry) => mediaJellyfinStatus(entry.item) === "owned",
    ).length;
    status.textContent = !data.submitted
      ? "Enter drücken, um alle Kataloge zu durchsuchen."
      : data.loading
      ? `Suche nach «${data.query}» …`
      : `${visibleResults.length} Treffer · ${jellyfinCount} davon in Jellyfin`;
    const suffix = [];
    if (data.pendingCatalogs.length) suffix.push(`${data.pendingCatalogs.join(", ")} werden noch durchsucht`);
    if (data.failures.length) suffix.push(`${data.failures.map(item => item.label).join(", ")} nicht erreichbar`);
    if (suffix.length) status.textContent += ` · ${suffix.join(" · ")}`;
    page.classList.toggle("is-loading", data.loading);
    if (data.loading) {
      for (let index = 0; index < 12; index += 1) {
        const skeleton = page.ownerDocument.createElement("span");
        skeleton.className = "home-card-skeleton";
        skeleton.setAttribute("aria-hidden", "true");
        grid.appendChild(skeleton);
      }
      return;
    }
    if (!visibleResults.length) {
      const empty = page.ownerDocument.createElement("div");
      empty.className = "global-search-empty";
      empty.innerHTML = data.failures.length && !data.results.length && !data.pendingCatalogs.length
        ? "<strong>Suche fehlgeschlagen</strong><span>Kataloge nicht erreichbar. Erneut Enter drücken.</span>"
        : data.submitted
        ? "<strong>Nichts in diesem Filter</strong><span>Filter ändern oder einen anderen Titel suchen.</span>"
        : "<strong>Bereit zum Suchen</strong><span>Suchbegriff prüfen und Enter drücken.</span>";
      grid.appendChild(empty);
      return;
    }
    visibleResults.forEach((entry, index) => {
      grid.appendChild(createHomeCard(entry, 0, index < 8));
    });
  }

  function syncGlobalSearchDraft() {
    const query = input?.value.trim() || "";
    cancelQuery();
    ++data.requestSeq;
    data.query = query;
    data.active = Boolean(query);
    data.loading = false;
    data.submitted = false;
    data.results = [];
    renderGlobalSearchResults();
  }

  function openGlobalSearch() {
    if (!scope?.active) return;
    data.active = true;
    renderGlobalSearchResults();
    input?.focus();
  }

  function runGlobalSearch() {
    if (!scope?.active) return;
    const query = input.value.trim();
    cancelQuery();
    const requestId = ++data.requestSeq;
    data.query = query;
    if (!query) {
      data.active = false;
      data.loading = false;
      data.submitted = false;
      data.results = [];
      renderGlobalSearchResults();
      return;
    }
    data.active = true;
    data.loading = true;
    data.submitted = true;
    data.results = [];
    renderGlobalSearchResults();
    const current = createScope();
    const release = scope.add(() => current.dispose());
    cancelQuery = () => { release(); data.failures = []; data.pendingCatalogs = []; };
    void performGlobalSearch(query, requestId, current).catch(error => {
      if (current.active) { data.loading = false; data.failures.push({ label: "Suche", message: error.message }); renderGlobalSearchResults(); }
    }).finally(release);
  }

  function closeGlobalSearch({ restoreFocus = false, force = false } = {}) {
    if (!force && data.active && mediaDetailModalOpen()) return;
    if (!input) return;
    cancelQuery();
    ++data.requestSeq;
    data.query = "";
    data.results = [];
    data.active = false;
    data.loading = false;
    data.submitted = false;
    input.value = "";
    renderGlobalSearchResults();
    if (restoreFocus) toggle?.focus();
  }


  return {
    get: () => Object.freeze({ ...data }), refresh: renderGlobalSearchResults,
    close: closeGlobalSearch, open: openGlobalSearch, search: runGlobalSearch,
    mount() {
      if (scope) return;
      scope = createScope();
      scope.listen(toggle, "click", openGlobalSearch);
      scope.listen(input, "focus", () => {
        shell.classList.add("is-expanded");
        toggle.setAttribute("aria-expanded", "true");
      });
      scope.listen(input, "blur", () => {
        scope.timeout(() => {
          if (input.value || shell.contains(page.ownerDocument.activeElement)) return;
          shell.classList.remove("is-expanded");
          toggle.setAttribute("aria-expanded", "false");
        }, 0);
      });
      scope.listen(input, "input", syncGlobalSearchDraft);
      scope.listen(input, "keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          runGlobalSearch();
        } else if (event.key === "Escape") {
          event.preventDefault();
          closeGlobalSearch({ restoreFocus: true });
          shell.classList.remove("is-expanded");
        }
      });
      scope.listen(byId("global-search-clear"), "click", () => {
        closeGlobalSearch({ restoreFocus: true });
        shell.classList.remove("is-expanded");
      });
      page.querySelectorAll("[data-global-search-scope]").forEach((button) => {
        scope.listen(button, "click", () => {
          data.scope = button.dataset.globalSearchScope;
          renderGlobalSearchResults();
        });
      });
      scope.listen(byId("global-search-jellyfin"), "click", () => {
        data.jellyfinOnly = !data.jellyfinOnly;
        renderGlobalSearchResults();
      });
      scope.listen(page, "click", (event) => {
        if (event.target.closest(".global-search-head, .home-card")) return;
        closeGlobalSearch();
      });
      scope.listen(page.ownerDocument, "pointerdown", (event) => {
        if (!data.active) return;
        if (shell.contains(event.target)) return;
        if (page.contains(event.target)) return;
        closeGlobalSearch();
      });
    },
    unmount() {
      closeGlobalSearch({ force: true }); scope?.dispose(); scope = null;
      shell.classList.remove("is-expanded");
    },
  };
}
