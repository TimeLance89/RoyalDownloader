/** Feature-owned catalog snapshot, cache and selection; never part of the application store. */
export function createSeriesState() {
  return {
    results: [], browseMode: null, page: 1, lastPageFull: false,
    sources: [], browseRequestSeq: 0, loadingBrowse: false, loadError: "",
    current: null, currentSampleSlug: "", epPicked: new Set(), cache: {},
    pendingBaseSlug: "", requestSeq: 0, viewGeneration: 0,
    searchReturn: null,
    previewFromHome: false, lastCatalogRefreshAt: 0,
  };
}
