import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

const CATALOG_REFRESH_INTERVAL_MS = 60_000;

/** Only the visible catalog owns refresh requests and retry timers. */
export function createCatalogRefresh({
  movieState, seriesState, applyFpResults, applySeriesResults, mergeCatalogItems, preloadSeriesPosterImages,
  client = api, documentRef = document, scopeFactory = createScope,
}) {
  let movieScope = null;
  let seriesScope = null;
  let fpCatalogRefreshPromise = null;
  let seriesCatalogRefreshPromise = null;
  let cancelMovieTimer = null;

  function scheduleFpCatalogRefresh(pending = false) {
    cancelMovieTimer?.();
    cancelMovieTimer = null;
    if (!movieScope?.active) return;
    cancelMovieTimer = movieScope.timeout(() => {
      cancelMovieTimer = null;
      if (!documentRef.hidden) void refreshFpCatalogInBackground(true);
      else scheduleFpCatalogRefresh();
    }, pending ? 5000 : CATALOG_REFRESH_INTERVAL_MS);
  }

  function refreshFpCatalogInBackground(force = false) {
    if (!movieScope?.active) return;
    const owner = movieScope;
    const stillFresh = Date.now() - movieState.lastCatalogRefreshAt < CATALOG_REFRESH_INTERVAL_MS;
    if ((!force && stillFresh && !movieState.previewFromHome) || fpCatalogRefreshPromise
      || movieState.loadingMore || movieState.searchActive || movieState.category !== "new") {
      scheduleFpCatalogRefresh();
      return;
    }
    const requestSeq = movieState.requestSeq;
    fpCatalogRefreshPromise = client.get("/api/movies?mode=new&page=1", { signal: owner.signal, timeoutMs: 15_000 })
      .then((data) => {
        if (!owner.active || movieState.searchActive || movieState.category !== "new" || requestSeq !== movieState.requestSeq) return;
        movieState.previewFromHome = false;
        movieState.lastCatalogRefreshAt = Date.now();
        if (movieState.page > 1) {
          data.results = mergeCatalogItems(data.results, movieState.results, (item) => item.slug);
          data.page = movieState.page;
          data.has_more = movieState.lastPageFull;
          data.sources = movieState.sources;
        }
        applyFpResults(data, { backgroundRefresh: true });
      })
      .catch((error) => {
        if (!owner.active) return;
        console.warn("Filmkatalog konnte nicht im Hintergrund aktualisiert werden:", error);
        scheduleFpCatalogRefresh();
      })
      .finally(() => { if (movieScope === owner) fpCatalogRefreshPromise = null; });
    return fpCatalogRefreshPromise;
  }

  function refreshSeriesCatalogInBackground() {
    if (!seriesScope?.active) return;
    const owner = seriesScope;
    const requestSeq = seriesState.browseRequestSeq;
    const current = () => owner.active && requestSeq === seriesState.browseRequestSeq
      && seriesState.browseMode === "discover" && seriesState.page <= 1;
    const stillFresh = Date.now() - seriesState.lastCatalogRefreshAt < CATALOG_REFRESH_INTERVAL_MS;
    if (
      stillFresh || seriesCatalogRefreshPromise || seriesState.loadingBrowse
      || seriesState.browseMode !== "discover"
    ) return;
    seriesCatalogRefreshPromise = client.get("/api/series?mode=discover&page=1", { signal: owner.signal })
      .then(async (data) => {
        if (!current()) return;
        // Wie im Filmkatalog bleibt die sichtbare Seite stehen, bis die Poster
        // der neuen Katalogseite im Browsercache liegen. Der Abruf bleibt dabei
        // vollständig im Hintergrund.
        await preloadSeriesPosterImages(data.results || [], 6000, owner.signal);
        if (!current()) return;
        seriesState.previewFromHome = false;
        seriesState.lastCatalogRefreshAt = Date.now();
        applySeriesResults(data, { backgroundRefresh: true });
      })
      .catch((error) => { if (owner.active) console.warn("Serienkatalog konnte nicht im Hintergrund aktualisiert werden:", error); })
      .finally(() => { if (seriesScope === owner) seriesCatalogRefreshPromise = null; });
    return seriesCatalogRefreshPromise;
  }

  return {
    schedule: scheduleFpCatalogRefresh,
    movies: {
      mount() { if (!movieScope?.active) movieScope = scopeFactory(); scheduleFpCatalogRefresh(); },
      refresh: refreshFpCatalogInBackground,
      unmount() { movieScope?.dispose(); movieScope = null; fpCatalogRefreshPromise = null; cancelMovieTimer = null; },
    },
    series: {
      mount() { if (!seriesScope?.active) seriesScope = scopeFactory(); },
      refresh: refreshSeriesCatalogInBackground,
      unmount() { seriesScope?.dispose(); seriesScope = null; seriesCatalogRefreshPromise = null; },
    },
  };
}
