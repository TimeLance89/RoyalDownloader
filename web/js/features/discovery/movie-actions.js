export function createMovieActions({
  getMovieFilters,
  getCatalogRefresh,
  getCardArtwork,
  getCatalogMetadata,
  getPosterPreloader,
  getCatalogSeed,
  getMovieStatus,
  getSeriesStatus,
  getSeriesChecks,
  getCleanMediaCardInitials,
  getResultCards,
  getMovieBrowse,
  getMovieDownloads,
  getMovieDetailsLoader,
  getTrailers,
  getMediaLanguage,
  getMoviePresentation,
  getMovieDiscovery,
}) {
  function fpSmartFilters(...args) { return getMovieFilters().get(...args); }
  function fpSmartFilterMatches(...args) { return getMovieFilters().matches(...args); }
  function fpSmartFilteredResults(...args) { return getMovieFilters().results(...args); }
  function fpActiveFilterLabels(...args) { return getMovieFilters().labels(...args); }
  function applyFpSmartFilters(...args) { return getMovieFilters().apply(...args); }
  function resetFpSmartFilters(...args) { return getMovieFilters().reset(...args); }

  function scheduleFpCatalogRefresh(pending = false) { return getCatalogRefresh().schedule(pending); }

  function scheduleResultPoster(image, coverCandidates) {
    getCardArtwork().set(image, coverCandidates.map(url => ({ url })), { eager: true });
  }

  function discardObservedResultPosters(container) {
    container?.querySelectorAll(".result-card-poster").forEach(image => getCardArtwork().discard(image));
  }

  function mergeFpMetadata(...args) { return getCatalogMetadata().merge(...args); }
  function fpMetadataPreloadItems(...args) { return getCatalogMetadata().items(...args); }
  function preloadTmdbMetadata(...args) { return getCatalogMetadata().preload(...args); }

  function preloadSeriesPosterImages(results, maxWaitMs = 3500, signal) {
    return getPosterPreloader().preload(results, maxWaitMs, signal);
  }

  function syncFpCatalogFromHome(...args) { return getCatalogSeed().movies(...args); }
  function syncSeriesCatalogFromHome(...args) { return getCatalogSeed().series(...args); }

  function refreshFpCatalogInBackground(force = false) { return getCatalogRefresh().movies.refresh(force); }

  function refreshSeriesCatalogInBackground() { return getCatalogRefresh().series.refresh(); }

  // ── Filmkatalog und Filmdetails ──────────────────────────────────────────

  function refreshFpJellyfinStatus(...args) { return getMovieStatus().refresh(...args); }
  function updateSeriesStatus(...args) { return getSeriesStatus().update(...args); }
  function updateSeriesJellyfinBadge(...args) { return getSeriesStatus().badge(...args); }
  function refreshSeriesJellyfinStatus(...args) { return getSeriesChecks().refresh(...args); }
  function mediaCardInitials(title) { return getCleanMediaCardInitials()(title); }
  function syncResultCardPoster(...args) { return getResultCards().sync(...args); }
  function createResultCardVisual(...args) { return getResultCards().create(...args); }
  function activateResultCard(...args) { return getResultCards().activate(...args); }
  function clearFpSearchContext(...args) { return getMovieBrowse().clear(...args); }
  function rememberFpSearchContext(...args) { return getMovieBrowse().remember(...args); }
  function restoreFpSearchContext(...args) { return getMovieBrowse().restore(...args); }
  function fpSearch(...args) { return getMovieBrowse().search(...args); }
  function fpShowList(...args) { return getMovieBrowse().list(...args); }
  function ensureFpResults(...args) { return getMovieBrowse().ensure(...args); }
  function fpGenreChange(...args) { return getMovieBrowse().genre(...args); }
  function loadNextFpPage(...args) { return getMovieBrowse().next(...args); }
  function toggleFpPick(...args) { return getMovieDownloads().toggle(...args); }
  function selectFpRow(...args) { return getMovieDetailsLoader().open(...args); }
  function fpTrailerYoutubeKey(movie) { return getTrailers().key(movie); }
  function setFpDetailHeroTrailerMuted(...args) { return getTrailers().setMuted(...args); }
  function stopFpDetailHeroTrailer() { return getTrailers().film.stop(); }
  function scheduleFpDetailHeroTrailer(movie) { return getTrailers().film.schedule(movie); }
  function closeFpTrailerModal(...args) { return getTrailers().close(...args); }
  function openFpTrailerModal(...args) { return getTrailers().open(...args); }
  function configureFpTrailer(movie) { return getTrailers().film.configure(movie); }
  function trailerModalFocusableElements() { return getTrailers().focusable(); }
  function configureFpDetailAction(...args) { return getMovieDownloads().configure(...args); }
  function mediaContentLanguages(media) { return getMediaLanguage().languages(media); }
  function normalizeUiContentLanguage(value) { return getMediaLanguage().normalize(value); }
  function fpStatusMessage(...args) { return getMoviePresentation().fpStatusMessage(...args); }
  function setActiveGenreFilter(...args) { return getMoviePresentation().setActiveGenreFilter(...args); }
  function mergeCatalogItems(...args) { return getMoviePresentation().mergeCatalogItems(...args); }
  function mergeCatalogSources(...args) { return getMoviePresentation().mergeCatalogSources(...args); }
  function updateFpInfiniteState(...args) { return getMoviePresentation().updateFpInfiniteState(...args); }
  function fpResultYear(...args) { return getMoviePresentation().fpResultYear(...args); }
  function setFpJellyfinBadge(...args) { return getMoviePresentation().setFpJellyfinBadge(...args); }
  function setFpPosterJellyfinBadge(...args) { return getMoviePresentation().setFpPosterJellyfinBadge(...args); }
  function updateFpJellyfinBadges(...args) { return getMoviePresentation().updateFpJellyfinBadges(...args); }
  function fpResultMedia(...args) { return getMoviePresentation().fpResultMedia(...args); }
  function fpResultAvailability(...args) { return getMoviePresentation().fpResultAvailability(...args); }
  function findFpResultCard(...args) { return getMoviePresentation().findFpResultCard(...args); }
  function updateFpResultCard(...args) { return getMoviePresentation().updateFpResultCard(...args); }
  function syncFpDetailQueueAction(...args) { return getMoviePresentation().syncFpDetailQueueAction(...args); }
  function syncFpQueueIndicators(...args) { return getMoviePresentation().syncFpQueueIndicators(...args); }
  function updateFpResultSelection(...args) { return getMoviePresentation().updateFpResultSelection(...args); }
  function renderFpResults(...args) { return getMoviePresentation().renderFpResults(...args); }
  function applyFpResults(...args) { return getMoviePresentation().applyFpResults(...args); }
  function basicMovieMetadata(...args) { return getMoviePresentation().basicMovieMetadata(...args); }
  function metadataPreviewMovie(...args) { return getMoviePresentation().metadataPreviewMovie(...args); }
  function renderFpDetailItems(...args) { return getMoviePresentation().renderFpDetailItems(...args); }
  function setFpDetailAvailability(...args) { return getMoviePresentation().setFpDetailAvailability(...args); }
  function setFpDetailJellyfinStatus(...args) { return getMoviePresentation().setFpDetailJellyfinStatus(...args); }
  function fpDetailJellyfinValue(...args) { return getMoviePresentation().fpDetailJellyfinValue(...args); }
  function formatMovieDate(...args) { return getMoviePresentation().formatMovieDate(...args); }
  function formatMovieNumber(...args) { return getMoviePresentation().formatMovieNumber(...args); }
  function formatMovieMoney(...args) { return getMoviePresentation().formatMovieMoney(...args); }
  function movieCertificationLabel(...args) { return getMoviePresentation().movieCertificationLabel(...args); }
  function movieStatusLabel(...args) { return getMoviePresentation().movieStatusLabel(...args); }
  function setFpDetailText(...args) { return getMoviePresentation().setFpDetailText(...args); }
  function renderFpCast(...args) { return getMoviePresentation().renderFpCast(...args); }
  function configureFpSubscriptionAction(...args) { return getMoviePresentation().configureFpSubscriptionAction(...args); }
  function openSelectedMovieSubscription(...args) { return getMoviePresentation().openSelectedMovieSubscription(...args); }
  function presentMovieSubscriptions(...args) { return getMoviePresentation().presentMovieSubscriptions(...args); }
  function movieQualityRank(...args) { return getMoviePresentation().movieQualityRank(...args); }
  function renderFpDownloadSources(...args) { return getMoviePresentation().renderFpDownloadSources(...args); }
  function showFpDetail(...args) { return getMoviePresentation().showFpDetail(...args); }
  function renderFpAbout(...args) { return getMovieDiscovery().renderAbout(...args); }
  function renderFpSimilarTitles(...args) { return getMovieDiscovery().renderSimilarTitles(...args); }
  function renderFpExtras(...args) { return getMovieDiscovery().renderExtras(...args); }
  return { fpSmartFilters, fpSmartFilterMatches, fpSmartFilteredResults, fpActiveFilterLabels, applyFpSmartFilters, resetFpSmartFilters, scheduleFpCatalogRefresh, scheduleResultPoster, discardObservedResultPosters, mergeFpMetadata, fpMetadataPreloadItems, preloadTmdbMetadata, preloadSeriesPosterImages, syncFpCatalogFromHome, syncSeriesCatalogFromHome, refreshFpCatalogInBackground, refreshSeriesCatalogInBackground, refreshFpJellyfinStatus, updateSeriesStatus, updateSeriesJellyfinBadge, refreshSeriesJellyfinStatus, mediaCardInitials, syncResultCardPoster, createResultCardVisual, activateResultCard, clearFpSearchContext, rememberFpSearchContext, restoreFpSearchContext, fpSearch, fpShowList, ensureFpResults, fpGenreChange, loadNextFpPage, toggleFpPick, selectFpRow, fpTrailerYoutubeKey, setFpDetailHeroTrailerMuted, stopFpDetailHeroTrailer, scheduleFpDetailHeroTrailer, closeFpTrailerModal, openFpTrailerModal, configureFpTrailer, trailerModalFocusableElements, configureFpDetailAction, mediaContentLanguages, normalizeUiContentLanguage, fpStatusMessage, setActiveGenreFilter, mergeCatalogItems, mergeCatalogSources, updateFpInfiniteState, fpResultYear, setFpJellyfinBadge, setFpPosterJellyfinBadge, updateFpJellyfinBadges, fpResultMedia, fpResultAvailability, findFpResultCard, updateFpResultCard, syncFpDetailQueueAction, syncFpQueueIndicators, updateFpResultSelection, renderFpResults, applyFpResults, basicMovieMetadata, metadataPreviewMovie, renderFpDetailItems, setFpDetailAvailability, setFpDetailJellyfinStatus, fpDetailJellyfinValue, formatMovieDate, formatMovieNumber, formatMovieMoney, movieCertificationLabel, movieStatusLabel, setFpDetailText, renderFpCast, configureFpSubscriptionAction, openSelectedMovieSubscription, presentMovieSubscriptions, movieQualityRank, renderFpDownloadSources, showFpDetail, renderFpAbout, renderFpSimilarTitles, renderFpExtras };
}
