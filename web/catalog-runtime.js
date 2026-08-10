const CATALOG_REFRESH_INTERVAL_MS = 60 * 1000;
let fpCatalogRefreshPromise = null;
let seriesCatalogRefreshPromise = null;

const resultPosterObserver = typeof IntersectionObserver === "function"
  ? new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      resultPosterObserver.unobserve(entry.target);
      entry.target.__loadResultPoster?.();
    }
  }, { root: null, rootMargin: "4200px 1200px", threshold: 0.01 })
  : null;

function scheduleResultPoster(image, coverCandidates) {
  let coverIndex = 0;
  const load = () => {
    if (image.src || !coverCandidates[coverIndex]) return;
    image.loading = "eager";
    image.fetchPriority = "auto";
    image.src = coverCandidates[coverIndex];
  };
  image.__loadResultPoster = load;
  image.addEventListener("error", () => {
    coverIndex += 1;
    image.removeAttribute("src");
    if (coverIndex < coverCandidates.length) load();
    else image.remove();
  });
  if (resultPosterObserver) resultPosterObserver.observe(image);
  else load();
}

function discardObservedResultPosters(container) {
  if (!resultPosterObserver || !container) return;
  container.querySelectorAll(".result-card-poster").forEach((image) => {
    resultPosterObserver.unobserve(image);
  });
}

function syncFpCatalogFromHome({ fresh = false } = {}) {
  if (state.fp.searchActive || (state.fp.category && state.fp.category !== "new")) return false;
  const incoming = Array.isArray(state.home.newMovies) ? state.home.newMovies : [];
  if (
    !incoming.length || (!fresh && state.fp.results.length)
    || (fresh && state.fp.results.length && !state.fp.previewFromHome)
  ) return false;
  state.fp.results = incoming.slice();
  state.fp.category = "new";
  state.fp.page = 1;
  state.fp.lastPageFull = true;
  state.fp.loadingMore = false;
  state.fp.loadError = "";
  state.fp.previewFromHome = !fresh;
  if (fresh) state.fp.lastCatalogRefreshAt = Date.now();
  for (const result of incoming) {
    if (result?.tmdb_id) state.fp.metadataCache[result.slug] = {
      ...(state.fp.metadataCache[result.slug] || {}), ...result,
    };
  }
  if (state.tab === "filme") {
    renderFpResults();
    refreshMovieFeatureCandidates();
    updateFpInfiniteState();
    recheckFpInfinite();
  }
  return true;
}

function refreshFpCatalogInBackground() {
  const stillFresh = Date.now() - state.fp.lastCatalogRefreshAt < CATALOG_REFRESH_INTERVAL_MS;
  if (stillFresh || fpCatalogRefreshPromise || state.fp.searchActive || state.fp.category !== "new") return;
  fpCatalogRefreshPromise = api.movies({ mode: "new", page: 1 })
    .then((data) => {
      if (state.fp.searchActive || state.fp.category !== "new" || state.fp.page > 1) return;
      state.fp.previewFromHome = false;
      state.fp.lastCatalogRefreshAt = Date.now();
      applyFpResults(data);
    })
    .catch((error) => console.warn("Filmkatalog konnte nicht im Hintergrund aktualisiert werden:", error))
    .finally(() => { fpCatalogRefreshPromise = null; });
}

function syncSeriesCatalogFromHome({ fresh = false } = {}) {
  if (state.series.browseMode && state.series.browseMode !== "discover") return false;
  const incoming = Array.isArray(state.home.discoverySeries) ? state.home.discoverySeries : [];
  if (
    !incoming.length || (!fresh && state.series.results.length)
    || (fresh && state.series.results.length && !state.series.previewFromHome)
  ) return false;
  state.series.results = incoming.slice();
  state.series.browseMode = "discover";
  state.series.page = 1;
  state.series.lastPageFull = true;
  state.series.loadingBrowse = false;
  state.series.loadError = "";
  state.series.previewFromHome = !fresh;
  if (fresh) state.series.lastCatalogRefreshAt = Date.now();
  if (state.tab === "serien") {
    renderSeriesResults();
    renderSeriesCatalogHero();
    updateSeriesInfiniteState();
    recheckSeriesInfinite();
  }
  return true;
}

function refreshSeriesCatalogInBackground() {
  const stillFresh = Date.now() - state.series.lastCatalogRefreshAt < CATALOG_REFRESH_INTERVAL_MS;
  if (
    stillFresh || seriesCatalogRefreshPromise || state.series.loadingBrowse
    || state.series.browseMode !== "discover"
  ) return;
  seriesCatalogRefreshPromise = api.series({ mode: "discover", page: 1 })
    .then((data) => {
      if (state.series.browseMode !== "discover" || state.series.page > 1) return;
      state.series.previewFromHome = false;
      state.series.lastCatalogRefreshAt = Date.now();
      applySeriesResults(data);
    })
    .catch((error) => console.warn("Serienkatalog konnte nicht im Hintergrund aktualisiert werden:", error))
    .finally(() => { seriesCatalogRefreshPromise = null; });
}
