/** Home seeds are previews; provider refresh keeps catalog pagination authoritative. */
const CATALOG_SEED_PAGE_SIZE = 32;
export function createCatalogSeed({
  movieState, seriesState, getActiveTab, getHomeData, mergeFpMetadata, fpMetadataPreloadItems, preloadTmdbMetadata,
  renderFpResults, refreshMovieFeatureCandidates, updateFpInfiniteState, recheckFpInfinite,
  renderSeriesResults, renderSeriesCatalogHero, updateSeriesInfiniteState, recheckSeriesInfinite,
}) {
  function syncFpCatalogFromHome({ fresh = false } = {}) {
    if (movieState.searchActive || (movieState.category && movieState.category !== "new")) return false;
    const incoming = Array.isArray(getHomeData().newMovies) ? getHomeData().newMovies : [];
    if (
      !incoming.length || (!fresh && movieState.results.length)
      || (fresh && movieState.results.length && !movieState.previewFromHome)
    ) return false;
    movieState.results = incoming.slice();
    movieState.category = "new";
    movieState.page = 1;
    movieState.lastPageFull = true;
    movieState.loadingMore = false;
    movieState.loadError = "";
    movieState.previewFromHome = true;
    movieState.lastCatalogRefreshAt = 0;
    for (const result of incoming) {
      if (result?.tmdb_id) movieState.metadataCache[result.slug] = mergeFpMetadata(
        movieState.metadataCache[result.slug], result,
      );
    }
    const metadataItems = fpMetadataPreloadItems(incoming);
    if (metadataItems.length) {
      movieState.pendingPreload = movieState.pendingPreload || new Set();
      for (const item of metadataItems) movieState.pendingPreload.add(item.slug);
      void preloadTmdbMetadata(movieState.metadataRequestSeq, metadataItems);
    }
    if (getActiveTab() === "filme") {
      renderFpResults();
      refreshMovieFeatureCandidates();
      updateFpInfiniteState();
      recheckFpInfinite();
    }
    return true;
  }

  function syncSeriesCatalogFromHome({ fresh = false } = {}) {
    if (seriesState.browseMode && seriesState.browseMode !== "discover") return false;
    const reservoir = Array.isArray(getHomeData().discoverySeries) ? getHomeData().discoverySeries : [];
    // The Home discovery reservoir may contain up to 220 warmed titles. The
    // series catalog must start with exactly one normal page, just like movies;
    // further pages are appended only by the catalog infinite-scroll path.
    const incoming = reservoir.slice(0, CATALOG_SEED_PAGE_SIZE);
    if (
      !incoming.length || (!fresh && seriesState.results.length)
      || (fresh && seriesState.results.length && !seriesState.previewFromHome)
    ) return false;
    seriesState.results = incoming.slice();
    seriesState.browseMode = "discover";
    seriesState.page = 1;
    seriesState.lastPageFull = true;
    seriesState.loadingBrowse = false;
    seriesState.loadError = "";
    seriesState.previewFromHome = !fresh;
    if (fresh) seriesState.lastCatalogRefreshAt = Date.now();
    if (getActiveTab() === "serien") {
      renderSeriesResults();
      renderSeriesCatalogHero();
      updateSeriesInfiniteState();
      recheckSeriesInfinite();
    }
    return true;
  }

  return { movies: syncFpCatalogFromHome, series: syncSeriesCatalogFromHome };
}
