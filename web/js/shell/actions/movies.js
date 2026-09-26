import { sharedPresentation } from "../presentation.js";
export function fpSmartFilters(...args) { return sharedPresentation.movieFilters.get(...args); }
export function fpSmartFilterMatches(...args) { return sharedPresentation.movieFilters.matches(...args); }
export function fpSmartFilteredResults(...args) { return sharedPresentation.movieFilters.results(...args); }
export function fpActiveFilterLabels(...args) { return sharedPresentation.movieFilters.labels(...args); }
export function applyFpSmartFilters(...args) { return sharedPresentation.movieFilters.apply(...args); }
export function resetFpSmartFilters(...args) { return sharedPresentation.movieFilters.reset(...args); }

export function scheduleFpCatalogRefresh(pending = false) { return sharedPresentation.catalogRefresh.schedule(pending); }

export function scheduleResultPoster(image, coverCandidates) {
  sharedPresentation.cardArtwork.set(image, coverCandidates.map(url => ({ url })), { eager: true });
}

export function discardObservedResultPosters(container) {
  container?.querySelectorAll(".result-card-poster").forEach(image => sharedPresentation.cardArtwork.discard(image));
}

export function mergeFpMetadata(...args) { return sharedPresentation.catalogMetadata.merge(...args); }
export function fpMetadataPreloadItems(...args) { return sharedPresentation.catalogMetadata.items(...args); }
export function preloadTmdbMetadata(...args) { return sharedPresentation.catalogMetadata.preload(...args); }

export function preloadSeriesPosterImages(results, maxWaitMs = 3500, signal) {
  return sharedPresentation.posterPreloader.preload(results, maxWaitMs, signal);
}

export function syncFpCatalogFromHome(...args) { return sharedPresentation.catalogSeed.movies(...args); }
export function syncSeriesCatalogFromHome(...args) { return sharedPresentation.catalogSeed.series(...args); }

export function refreshFpCatalogInBackground(force = false) { return sharedPresentation.catalogRefresh.movies.refresh(force); }

export function refreshSeriesCatalogInBackground() { return sharedPresentation.catalogRefresh.series.refresh(); }

// ── Filmkatalog und Filmdetails ──────────────────────────────────────────

export function refreshFpJellyfinStatus(...args) { return sharedPresentation.movieStatus.refresh(...args); }
export function updateSeriesStatus(...args) { return sharedPresentation.seriesStatus.update(...args); }
export function updateSeriesJellyfinBadge(...args) { return sharedPresentation.seriesStatus.badge(...args); }
export function refreshSeriesJellyfinStatus(...args) { return sharedPresentation.seriesChecks.refresh(...args); }
export function mediaCardInitials(title) { return sharedPresentation.cleanMediaCardInitials(title); }
export function syncResultCardPoster(...args) { return sharedPresentation.resultCards.sync(...args); }
export function createResultCardVisual(...args) { return sharedPresentation.resultCards.create(...args); }
export function activateResultCard(...args) { return sharedPresentation.resultCards.activate(...args); }
export function clearFpSearchContext(...args) { return sharedPresentation.movieBrowse.clear(...args); }
export function rememberFpSearchContext(...args) { return sharedPresentation.movieBrowse.remember(...args); }
export function restoreFpSearchContext(...args) { return sharedPresentation.movieBrowse.restore(...args); }
export function fpSearch(...args) { return sharedPresentation.movieBrowse.search(...args); }
export function fpShowList(...args) { return sharedPresentation.movieBrowse.list(...args); }
export function ensureFpResults(...args) { return sharedPresentation.movieBrowse.ensure(...args); }
export function fpGenreChange(...args) { return sharedPresentation.movieBrowse.genre(...args); }
export function loadNextFpPage(...args) { return sharedPresentation.movieBrowse.next(...args); }
export function toggleFpPick(...args) { return sharedPresentation.movieDownloads.toggle(...args); }
export function selectFpRow(...args) { return sharedPresentation.movieDetailsLoader.open(...args); }
export function fpTrailerYoutubeKey(movie) { return sharedPresentation.trailers.key(movie); }
export function setFpDetailHeroTrailerMuted(...args) { return sharedPresentation.trailers.setMuted(...args); }
export function stopFpDetailHeroTrailer() { return sharedPresentation.trailers.film.stop(); }
export function scheduleFpDetailHeroTrailer(movie) { return sharedPresentation.trailers.film.schedule(movie); }
export function closeFpTrailerModal(...args) { return sharedPresentation.trailers.close(...args); }
export function openFpTrailerModal(...args) { return sharedPresentation.trailers.open(...args); }
export function configureFpTrailer(movie) { return sharedPresentation.trailers.film.configure(movie); }
export function trailerModalFocusableElements() { return sharedPresentation.trailers.focusable(); }
export function configureFpDetailAction(...args) { return sharedPresentation.movieDownloads.configure(...args); }
export function mediaContentLanguages(media) { return sharedPresentation.mediaLanguage.languages(media); }
export function normalizeUiContentLanguage(value) { return sharedPresentation.mediaLanguage.normalize(value); }
export function fpStatusMessage(...args) { return sharedPresentation.moviePresentation.fpStatusMessage(...args); }
export function setActiveGenreFilter(...args) { return sharedPresentation.moviePresentation.setActiveGenreFilter(...args); }
export function mergeCatalogItems(...args) { return sharedPresentation.moviePresentation.mergeCatalogItems(...args); }
export function mergeCatalogSources(...args) { return sharedPresentation.moviePresentation.mergeCatalogSources(...args); }
export function updateFpInfiniteState(...args) { return sharedPresentation.moviePresentation.updateFpInfiniteState(...args); }
export function fpResultYear(...args) { return sharedPresentation.moviePresentation.fpResultYear(...args); }
export function setFpJellyfinBadge(...args) { return sharedPresentation.moviePresentation.setFpJellyfinBadge(...args); }
export function setFpPosterJellyfinBadge(...args) { return sharedPresentation.moviePresentation.setFpPosterJellyfinBadge(...args); }
export function updateFpJellyfinBadges(...args) { return sharedPresentation.moviePresentation.updateFpJellyfinBadges(...args); }
export function fpResultMedia(...args) { return sharedPresentation.moviePresentation.fpResultMedia(...args); }
export function fpResultAvailability(...args) { return sharedPresentation.moviePresentation.fpResultAvailability(...args); }
export function findFpResultCard(...args) { return sharedPresentation.moviePresentation.findFpResultCard(...args); }
export function updateFpResultCard(...args) { return sharedPresentation.moviePresentation.updateFpResultCard(...args); }
export function syncFpDetailQueueAction(...args) { return sharedPresentation.moviePresentation.syncFpDetailQueueAction(...args); }
export function syncFpQueueIndicators(...args) { return sharedPresentation.moviePresentation.syncFpQueueIndicators(...args); }
export function updateFpResultSelection(...args) { return sharedPresentation.moviePresentation.updateFpResultSelection(...args); }
export function renderFpResults(...args) { return sharedPresentation.moviePresentation.renderFpResults(...args); }
export function applyFpResults(...args) { return sharedPresentation.moviePresentation.applyFpResults(...args); }
export function basicMovieMetadata(...args) { return sharedPresentation.moviePresentation.basicMovieMetadata(...args); }
export function metadataPreviewMovie(...args) { return sharedPresentation.moviePresentation.metadataPreviewMovie(...args); }
export function renderFpDetailItems(...args) { return sharedPresentation.moviePresentation.renderFpDetailItems(...args); }
export function setFpDetailAvailability(...args) { return sharedPresentation.moviePresentation.setFpDetailAvailability(...args); }
export function setFpDetailJellyfinStatus(...args) { return sharedPresentation.moviePresentation.setFpDetailJellyfinStatus(...args); }
export function fpDetailJellyfinValue(...args) { return sharedPresentation.moviePresentation.fpDetailJellyfinValue(...args); }
export function formatMovieDate(...args) { return sharedPresentation.moviePresentation.formatMovieDate(...args); }
export function formatMovieNumber(...args) { return sharedPresentation.moviePresentation.formatMovieNumber(...args); }
export function formatMovieMoney(...args) { return sharedPresentation.moviePresentation.formatMovieMoney(...args); }
export function movieCertificationLabel(...args) { return sharedPresentation.moviePresentation.movieCertificationLabel(...args); }
export function movieStatusLabel(...args) { return sharedPresentation.moviePresentation.movieStatusLabel(...args); }
export function setFpDetailText(...args) { return sharedPresentation.moviePresentation.setFpDetailText(...args); }
export function renderFpCast(...args) { return sharedPresentation.moviePresentation.renderFpCast(...args); }
export function configureFpSubscriptionAction(...args) { return sharedPresentation.moviePresentation.configureFpSubscriptionAction(...args); }
export function openSelectedMovieSubscription(...args) { return sharedPresentation.moviePresentation.openSelectedMovieSubscription(...args); }
export function presentMovieSubscriptions(...args) { return sharedPresentation.moviePresentation.presentMovieSubscriptions(...args); }
export function movieQualityRank(...args) { return sharedPresentation.moviePresentation.movieQualityRank(...args); }
export function renderFpDownloadSources(...args) { return sharedPresentation.moviePresentation.renderFpDownloadSources(...args); }
export function showFpDetail(...args) { return sharedPresentation.moviePresentation.showFpDetail(...args); }
export function renderFpAbout(...args) { return sharedPresentation.movieDiscovery.renderAbout(...args); }
export function renderFpSimilarTitles(...args) { return sharedPresentation.movieDiscovery.renderSimilarTitles(...args); }
export function renderFpExtras(...args) { return sharedPresentation.movieDiscovery.renderExtras(...args); }
