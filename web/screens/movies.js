function fpSmartFilters(...args) { return sharedPresentation.movieFilters.get(...args); }
function fpSmartFilterMatches(...args) { return sharedPresentation.movieFilters.matches(...args); }
function fpSmartFilteredResults(...args) { return sharedPresentation.movieFilters.results(...args); }
function fpActiveFilterLabels(...args) { return sharedPresentation.movieFilters.labels(...args); }
function applyFpSmartFilters(...args) { return sharedPresentation.movieFilters.apply(...args); }
function resetFpSmartFilters(...args) { return sharedPresentation.movieFilters.reset(...args); }

function scheduleFpCatalogRefresh(pending = false) { return sharedPresentation.catalogRefresh.schedule(pending); }

function scheduleResultPoster(image, coverCandidates) {
  sharedPresentation.cardArtwork.set(image, coverCandidates.map(url => ({ url })), { eager: true });
}

function discardObservedResultPosters(container) {
  container?.querySelectorAll(".result-card-poster").forEach(image => sharedPresentation.cardArtwork.discard(image));
}

function mergeFpMetadata(...args) { return sharedPresentation.catalogMetadata.merge(...args); }
function fpMetadataPreloadItems(...args) { return sharedPresentation.catalogMetadata.items(...args); }
function preloadTmdbMetadata(...args) { return sharedPresentation.catalogMetadata.preload(...args); }

function preloadSeriesPosterImages(results, maxWaitMs = 3500, signal) {
  return sharedPresentation.posterPreloader.preload(results, maxWaitMs, signal);
}

function syncFpCatalogFromHome(...args) { return sharedPresentation.catalogSeed.movies(...args); }
function syncSeriesCatalogFromHome(...args) { return sharedPresentation.catalogSeed.series(...args); }

function refreshFpCatalogInBackground(force = false) { return sharedPresentation.catalogRefresh.movies.refresh(force); }

function refreshSeriesCatalogInBackground() { return sharedPresentation.catalogRefresh.series.refresh(); }

// ── Filmkatalog und Filmdetails ──────────────────────────────────────────

function refreshFpJellyfinStatus(...args) { return sharedPresentation.movieStatus.refresh(...args); }
function updateSeriesStatus(...args) { return sharedPresentation.seriesStatus.update(...args); }
function updateSeriesJellyfinBadge(...args) { return sharedPresentation.seriesStatus.badge(...args); }
function refreshSeriesJellyfinStatus(...args) { return sharedPresentation.seriesChecks.refresh(...args); }
function mediaCardInitials(title) { return sharedPresentation.cleanMediaCardInitials(title); }
function syncResultCardPoster(...args) { return sharedPresentation.resultCards.sync(...args); }
function createResultCardVisual(...args) { return sharedPresentation.resultCards.create(...args); }
function activateResultCard(...args) { return sharedPresentation.resultCards.activate(...args); }
function clearFpSearchContext(...args) { return sharedPresentation.movieBrowse.clear(...args); }
function rememberFpSearchContext(...args) { return sharedPresentation.movieBrowse.remember(...args); }
function restoreFpSearchContext(...args) { return sharedPresentation.movieBrowse.restore(...args); }
function fpSearch(...args) { return sharedPresentation.movieBrowse.search(...args); }
function fpShowList(...args) { return sharedPresentation.movieBrowse.list(...args); }
function ensureFpResults(...args) { return sharedPresentation.movieBrowse.ensure(...args); }
function fpGenreChange(...args) { return sharedPresentation.movieBrowse.genre(...args); }
function loadNextFpPage(...args) { return sharedPresentation.movieBrowse.next(...args); }
function toggleFpPick(...args) { return sharedPresentation.movieDownloads.toggle(...args); }
function selectFpRow(...args) { return sharedPresentation.movieDetailsLoader.open(...args); }
function fpTrailerYoutubeKey(movie) { return sharedPresentation.trailers.key(movie); }
function setFpDetailHeroTrailerMuted(...args) { return sharedPresentation.trailers.setMuted(...args); }
function stopFpDetailHeroTrailer() { return sharedPresentation.trailers.film.stop(); }
function scheduleFpDetailHeroTrailer(movie) { return sharedPresentation.trailers.film.schedule(movie); }
function closeFpTrailerModal(...args) { return sharedPresentation.trailers.close(...args); }
function openFpTrailerModal(...args) { return sharedPresentation.trailers.open(...args); }
function configureFpTrailer(movie) { return sharedPresentation.trailers.film.configure(movie); }
function trailerModalFocusableElements() { return sharedPresentation.trailers.focusable(); }
function configureFpDetailAction(...args) { return sharedPresentation.movieDownloads.configure(...args); }
function mediaContentLanguages(media) { return sharedPresentation.mediaLanguage.languages(media); }
function normalizeUiContentLanguage(value) { return sharedPresentation.mediaLanguage.normalize(value); }
function fpStatusMessage(...args) { return sharedPresentation.moviePresentation.fpStatusMessage(...args); }
function setActiveGenreFilter(...args) { return sharedPresentation.moviePresentation.setActiveGenreFilter(...args); }
function mergeCatalogItems(...args) { return sharedPresentation.moviePresentation.mergeCatalogItems(...args); }
function mergeCatalogSources(...args) { return sharedPresentation.moviePresentation.mergeCatalogSources(...args); }
function updateFpInfiniteState(...args) { return sharedPresentation.moviePresentation.updateFpInfiniteState(...args); }
function fpResultYear(...args) { return sharedPresentation.moviePresentation.fpResultYear(...args); }
function setFpJellyfinBadge(...args) { return sharedPresentation.moviePresentation.setFpJellyfinBadge(...args); }
function setFpPosterJellyfinBadge(...args) { return sharedPresentation.moviePresentation.setFpPosterJellyfinBadge(...args); }
function updateFpJellyfinBadges(...args) { return sharedPresentation.moviePresentation.updateFpJellyfinBadges(...args); }
function fpResultMedia(...args) { return sharedPresentation.moviePresentation.fpResultMedia(...args); }
function fpResultAvailability(...args) { return sharedPresentation.moviePresentation.fpResultAvailability(...args); }
function findFpResultCard(...args) { return sharedPresentation.moviePresentation.findFpResultCard(...args); }
function updateFpResultCard(...args) { return sharedPresentation.moviePresentation.updateFpResultCard(...args); }
function syncFpDetailQueueAction(...args) { return sharedPresentation.moviePresentation.syncFpDetailQueueAction(...args); }
function syncFpQueueIndicators(...args) { return sharedPresentation.moviePresentation.syncFpQueueIndicators(...args); }
function updateFpResultSelection(...args) { return sharedPresentation.moviePresentation.updateFpResultSelection(...args); }
function renderFpResults(...args) { return sharedPresentation.moviePresentation.renderFpResults(...args); }
function applyFpResults(...args) { return sharedPresentation.moviePresentation.applyFpResults(...args); }
function basicMovieMetadata(...args) { return sharedPresentation.moviePresentation.basicMovieMetadata(...args); }
function metadataPreviewMovie(...args) { return sharedPresentation.moviePresentation.metadataPreviewMovie(...args); }
function renderFpDetailItems(...args) { return sharedPresentation.moviePresentation.renderFpDetailItems(...args); }
function setFpDetailAvailability(...args) { return sharedPresentation.moviePresentation.setFpDetailAvailability(...args); }
function setFpDetailJellyfinStatus(...args) { return sharedPresentation.moviePresentation.setFpDetailJellyfinStatus(...args); }
function fpDetailJellyfinValue(...args) { return sharedPresentation.moviePresentation.fpDetailJellyfinValue(...args); }
function formatMovieDate(...args) { return sharedPresentation.moviePresentation.formatMovieDate(...args); }
function formatMovieNumber(...args) { return sharedPresentation.moviePresentation.formatMovieNumber(...args); }
function formatMovieMoney(...args) { return sharedPresentation.moviePresentation.formatMovieMoney(...args); }
function movieCertificationLabel(...args) { return sharedPresentation.moviePresentation.movieCertificationLabel(...args); }
function movieStatusLabel(...args) { return sharedPresentation.moviePresentation.movieStatusLabel(...args); }
function setFpDetailText(...args) { return sharedPresentation.moviePresentation.setFpDetailText(...args); }
function renderFpCast(...args) { return sharedPresentation.moviePresentation.renderFpCast(...args); }
function configureFpSubscriptionAction(...args) { return sharedPresentation.moviePresentation.configureFpSubscriptionAction(...args); }
function openSelectedMovieSubscription(...args) { return sharedPresentation.moviePresentation.openSelectedMovieSubscription(...args); }
function presentMovieSubscriptions(...args) { return sharedPresentation.moviePresentation.presentMovieSubscriptions(...args); }
function movieQualityRank(...args) { return sharedPresentation.moviePresentation.movieQualityRank(...args); }
function renderFpDownloadSources(...args) { return sharedPresentation.moviePresentation.renderFpDownloadSources(...args); }
function showFpDetail(...args) { return sharedPresentation.moviePresentation.showFpDetail(...args); }
function renderFpAbout(...args) { return sharedPresentation.movieDiscovery.renderAbout(...args); }
function renderFpSimilarTitles(...args) { return sharedPresentation.movieDiscovery.renderSimilarTitles(...args); }
function renderFpExtras(...args) { return sharedPresentation.movieDiscovery.renderExtras(...args); }
