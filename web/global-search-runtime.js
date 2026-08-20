(() => {
  if (window.__royalGlobalSearchRuntimeInstalled) return;
  window.__royalGlobalSearchRuntimeInstalled = true;

  const CATALOGS = [
    {
      key: "movie",
      label: "Filme",
      load: (query) => api.movies({ mode: "search", query })
        .then((data) => (data.results || []).map(homeMovieEntry)),
    },
    {
      key: "series",
      label: "Serien",
      load: (query) => api.series({ mode: "search", query })
        .then((data) => (data.results || []).map(homeSeriesEntry)),
    },
    {
      key: "anime",
      label: "Anime",
      load: (query) => api.anime({ mode: "search", query, page: 1 })
        .then((data) => (data.results || []).map(homeAnimeEntry)),
    },
  ];

  state.globalSearch.failures = [];
  state.globalSearch.pendingCatalogs = [];

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

  function mediaDetailModalOpen() {
    return [...document.querySelectorAll(".media-modal")].some((modal) =>
      !modal.hidden
      && !modal.classList.contains("hidden")
      && modal.getAttribute("aria-hidden") !== "true");
  }

  const baseRenderGlobalSearchResults = window.renderGlobalSearchResults;
  window.renderGlobalSearchResults = function renderGlobalSearchResultsWithCatalogState() {
    baseRenderGlobalSearchResults();
    if (!state.globalSearch.active || !state.globalSearch.submitted) return;
    const status = document.getElementById("global-search-status");
    if (!status) return;
    const pending = Array.isArray(state.globalSearch.pendingCatalogs)
      ? state.globalSearch.pendingCatalogs
      : [];
    const failures = Array.isArray(state.globalSearch.failures)
      ? state.globalSearch.failures
      : [];
    const suffix = [];
    if (pending.length) suffix.push(`${pending.join(", ")} werden noch durchsucht`);
    if (failures.length) suffix.push(
      `${failures.map((failure) => failure.label).join(", ")} nicht erreichbar`,
    );
    if (suffix.length) status.textContent = `${status.textContent} · ${suffix.join(" · ")}`;
  };

  window.performGlobalSearch = async function performGlobalSearchProgressively(query, requestId) {
    rememberSearch(query, "all");
    const groups = new Map();
    state.globalSearch.failures = [];
    state.globalSearch.pendingCatalogs = CATALOGS.map((catalog) => catalog.label);
    renderGlobalSearchResults();

    const settleCatalog = async (catalog) => {
      try {
        groups.set(catalog.key, await catalog.load(query));
      } catch (error) {
        state.globalSearch.failures.push({
          key: catalog.key,
          label: catalog.label,
          message: error?.message || "nicht erreichbar",
        });
        console.warn(`${catalog.label}-Suche fehlgeschlagen:`, error);
      } finally {
        if (requestId !== state.globalSearch.requestSeq) return;
        state.globalSearch.pendingCatalogs = state.globalSearch.pendingCatalogs
          .filter((label) => label !== catalog.label);
        state.globalSearch.results = mergeCatalogGroups(groups);
        // Ein leer beantworteter schneller Katalog ist noch kein endgültiges
        // "nichts gefunden". Solange weitere Kataloge laufen und noch kein
        // Treffer vorliegt, bleibt der echte Loading-/Skeleton-Zustand aktiv.
        // Sobald irgendein Treffer da ist, zeigen wir ihn dagegen sofort und
        // ergänzen die langsameren Kataloge progressiv im Hintergrund.
        state.globalSearch.loading = state.globalSearch.results.length === 0
          && state.globalSearch.pendingCatalogs.length > 0;
        renderGlobalSearchResults();
      }
    };

    await Promise.all(CATALOGS.map(settleCatalog));
    if (requestId !== state.globalSearch.requestSeq) return;

    state.globalSearch.results = mergeCatalogGroups(groups);
    state.globalSearch.loading = false;
    renderGlobalSearchResults();

    await Promise.allSettled([
      hydrateHomeMovieArtwork(
        state.globalSearch.results
          .filter((entry) => entry.kind === "movie")
          .map((entry) => entry.item),
        { render: false },
      ),
      hydrateHomeSeriesArtwork(
        state.globalSearch.results
          .filter((entry) => entry.kind === "series")
          .map((entry) => entry.item),
        { render: false },
      ),
    ]);
    if (requestId !== state.globalSearch.requestSeq) return;

    // Durch die Artwork-/TMDB-Anreicherung kann eine zuvor noch nicht
    // erkennbare Provider-Dublette jetzt eine eindeutige Inhalts-ID besitzen.
    // Deshalb nach der Metadatenphase noch einmal über dieselben Rohgruppen
    // deduplizieren, bevor Jellyfin abgefragt und final gerendert wird.
    state.globalSearch.results = mergeCatalogGroups(groups);
    await refreshCatalogJellyfinStatus(state.globalSearch.results, null);
    if (requestId !== state.globalSearch.requestSeq) return;
    renderGlobalSearchResults();
  };

  // Suchkarten öffnen ihre normale Detailansicht als Modal über der Suche.
  // Die Suchseite wird dabei NICHT geschlossen; Query, Filter, Treffer und
  // Scrollposition bleiben dadurch unverändert hinter dem Modal erhalten.
  window.openHomeEntry = function openHomeEntryKeepingGlobalSearch(kind, key) {
    if (kind === "movie") {
      const movie = homeMovieBySlug(key);
      if (movie) selectFpRow(movie.slug, movie);
      return;
    }
    if (kind === "anime") {
      const anime = homeAnimeById(key);
      if (anime) openAnimeDetail(anime);
      return;
    }
    const series = homeSeriesBySlug(key);
    if (series) loadSeries(series);
  };

  const baseRunGlobalSearch = window.runGlobalSearch;
  window.runGlobalSearch = function runGlobalSearchWithFreshCatalogState() {
    state.globalSearch.failures = [];
    state.globalSearch.pendingCatalogs = [];
    return baseRunGlobalSearch();
  };

  const baseSyncGlobalSearchDraft = window.syncGlobalSearchDraft;
  window.syncGlobalSearchDraft = function syncGlobalSearchDraftWithFreshCatalogState() {
    state.globalSearch.failures = [];
    state.globalSearch.pendingCatalogs = [];
    return baseSyncGlobalSearchDraft();
  };

  const baseCloseGlobalSearch = window.closeGlobalSearch;
  window.closeGlobalSearch = function closeGlobalSearchWithFreshCatalogState(options) {
    // Der globale Outside-Click-Handler betrachtet Modals als "außerhalb" der
    // Suchseite. Solange ein aus der Suche geöffnetes Mediendetail sichtbar
    // ist, darf dieser Handler die darunterliegende Suche nicht zerstören.
    if (state.globalSearch.active && mediaDetailModalOpen()) return;
    state.globalSearch.failures = [];
    state.globalSearch.pendingCatalogs = [];
    return baseCloseGlobalSearch(options);
  };
})();

function loadRoyalSmartAutomationPolicy() {
  if (document.querySelector('script[data-royal-smart-automation]')) return;
  const script = document.createElement("script");
  script.src = "/automation-policy.js?v=royal-20260820-1";
  script.async = false;
  script.setAttribute("data-royal-smart-automation", "true");
  script.addEventListener("error", () => {
    console.warn("Royal Smart Automation konnte nicht geladen werden.");
  }, { once: true });
  document.body.appendChild(script);
}

window.setTimeout(loadRoyalSmartAutomationPolicy, 0);
