/** Feature-owned catalog snapshot, cache and selection; never part of the application store. */
export function createMovieState() {
  return {
    results: [], moviesCache: {}, category: null, page: 1, lastPageFull: false,
    activeGenre: "Alle Genres", selectedSlug: null, pendingPreload: null,
    metadataCache: {}, requestSeq: 0, metadataRequestSeq: 0, sources: [], loadingMore: false,
    loadError: "", searchActive: false, searchReturn: null,
    previewFromHome: false, lastCatalogRefreshAt: 0,
    downloadSelections: new Map(),
  };
}
