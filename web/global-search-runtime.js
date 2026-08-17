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

  function mergeCatalogGroups(groups) {
    const ordered = CATALOGS
      .map((catalog) => groups.get(catalog.key) || [])
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
        // Sobald mindestens ein Katalog geantwortet hat, zeigen wir dessen
        // Treffer sofort. Langsamere Kataloge ergänzen dieselbe Ansicht später.
        state.globalSearch.loading = groups.size === 0
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
    await refreshCatalogJellyfinStatus(state.globalSearch.results, null);
    if (requestId !== state.globalSearch.requestSeq) return;
    renderGlobalSearchResults();
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
    state.globalSearch.failures = [];
    state.globalSearch.pendingCatalogs = [];
    return baseCloseGlobalSearch(options);
  };
})();
