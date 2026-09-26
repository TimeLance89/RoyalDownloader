function refreshMovieFeatureCandidates() { sharedPresentation.movieHero.refresh(); }

function homeMovieInstances(...args) { return sharedPresentation.homeCatalog.homeMovieInstances(...args); }

function homeMovieBySlug(...args) { return sharedPresentation.homeCatalog.homeMovieBySlug(...args); }

function applyMovieJellyfinStatus(slug, status, owned = null) { sharedPresentation.catalogJellyfin.applyMovie(slug, status, owned); }

function homeSeriesBySlug(...args) { return sharedPresentation.homeCatalog.homeSeriesBySlug(...args); }

function homeAnimeById(...args) { return sharedPresentation.homeCatalog.homeAnimeById(...args); }

function mediaJellyfinStatus(...args) { return sharedPresentation.homeCatalog.mediaJellyfinStatus(...args); }

function jellyfinStatusText(status) { return sharedPresentation.jellyfinStatusText(status); }
function setCatalogJellyfinBadge(badge, status) { sharedPresentation.setCatalogJellyfinBadge(badge, status); }

function refreshCatalogJellyfinStatus(entries, render, options) { return sharedPresentation.catalogJellyfin.refresh(entries, render, options); }

function refreshAllCatalogJellyfinStatuses() {
  const entries = [
    ...homeAllEntries(),
    ...sharedPresentation.seriesState.results.map(homeSeriesEntry),
    ...sharedPresentation.anime.get().results.map(homeAnimeEntry),
    ...sharedPresentation.search.get().results,
  ];
  return refreshCatalogJellyfinStatus(entries, () => {
    renderHome();
    renderSeriesResults();
    renderAnimeResults();
    renderGlobalSearchResults();
  });
}

function uniqueHomeEntries(...args) { return sharedPresentation.homeCatalog.uniqueHomeEntries(...args); }

function interleaveHomeEntries(...args) { return sharedPresentation.homeCatalog.interleaveHomeEntries(...args); }

function homeMovieEntry(...args) { return sharedPresentation.homeCatalog.homeMovieEntry(...args); }

function homeSeriesEntry(...args) { return sharedPresentation.homeCatalog.homeSeriesEntry(...args); }

function homeAnimeEntry(...args) { return sharedPresentation.homeCatalog.homeAnimeEntry(...args); }

function discoveryProfileStorageKey() { return sharedPresentation.tasteProfile.key(); }

function homeEntryKey(...args) { return sharedPresentation.homeCatalog.homeEntryKey(...args); }

function homeEntryMedia(...args) { return sharedPresentation.homeCatalog.homeEntryMedia(...args); }

function canonicalHomeText(...args) { return sharedPresentation.homeCatalog.canonicalHomeText(...args); }

function homeContentKeys(...args) { return sharedPresentation.homeCatalog.homeContentKeys(...args); }

function homeContentKey(...args) { return sharedPresentation.homeCatalog.homeContentKey(...args); }

function uniqueHomeContentEntries(...args) { return sharedPresentation.homeCatalog.uniqueHomeContentEntries(...args); }

function localDateKey(...args) { return sharedPresentation.homeCatalog.localDateKey(...args); }

function stableDiscoveryHash(...args) { return sharedPresentation.homeCatalog.stableDiscoveryHash(...args); }

function stableDailyOrder(...args) { return sharedPresentation.homeCatalog.stableDailyOrder(...args); }

function currentTasteTarget(kind) {
  if (kind === "movie") {
    const slug = sharedPresentation.movieState.selectedSlug || "";
    const item = {
      ...(homeMovieBySlug(slug) || {}),
      ...(sharedPresentation.movieState.moviesCache[slug] || {}),
      ...(sharedPresentation.movieState.metadataCache[slug] || {}),
      slug,
    };
    return slug ? { key: `movie:${slug}`, item } : null;
  }
  const item = sharedPresentation.seriesState.current;
  return item?.base_slug ? { key: `series:${item.base_slug}`, item } : null;
}

function renderTasteProfileSummary(profile, offline) { sharedPresentation.tasteRanking.summary(profile, offline); }
function loadDiscoveryProfile(...args) { return sharedPresentation.tasteProfile.load(...args); }
function saveDiscoveryProfile(...args) { return sharedPresentation.tasteProfile.save(...args); }
function applyServerTasteProfile(...args) { return sharedPresentation.tasteProfile.accept(...args); }
function syncTasteProfile(...args) { return sharedPresentation.tasteProfile.sync(...args); }
function tasteMetadata(...args) { return sharedPresentation.tasteProfile.metadata(...args); }
function updateTasteFeedbackButtons(...args) { return sharedPresentation.tasteProfile.updateButtons(...args); }
function setTasteFeedback(...args) { return sharedPresentation.tasteProfile.feedback(...args); }
function trackDiscoveryPreference(...args) { return sharedPresentation.tasteProfile.track(...args); }

function allowedHomeEntries(entries, profile) { return sharedPresentation.tasteRanking.allowed(entries, profile); }

function homeAllEntries(...args) { return sharedPresentation.homeLanes.homeAllEntries(...args); }

function homeTopEntries() { return sharedPresentation.dailyTop.entries(); }

function homeNewEntries(...args) { return sharedPresentation.homeLanes.homeNewEntries(...args); }

function homePopularSeriesEntries(...args) { return sharedPresentation.homeLanes.homePopularSeriesEntries(...args); }

function homePersonalizedEntries() { return sharedPresentation.tasteRanking.entries(); }

function favoriteDiscoveryGenre(...args) { return sharedPresentation.homeLanes.favoriteDiscoveryGenre(...args); }

function homeGenreEntries(...args) { return sharedPresentation.homeLanes.homeGenreEntries(...args); }

function homeExploreEntries(...args) { return sharedPresentation.homeLanes.homeExploreEntries(...args); }

function homeGemEntries(...args) { return sharedPresentation.homeLanes.homeGemEntries(...args); }
function takeDistinctHomeLane(...args) { return sharedPresentation.homeLanes.takeDistinctHomeLane(...args); }
function homeDiscoveryLanes(...args) { return sharedPresentation.homeLanes.homeDiscoveryLanes(...args); }
function shuffleHomeDiscovery(...args) { return sharedPresentation.homePresenter.shuffle(...args); }
function homeHeroCandidates() { return sharedPresentation.heroSelection.candidates(); }
function stopHomeHeroRotation() { sharedPresentation.hero.stop(); }
function scheduleHomeHeroRotation() { sharedPresentation.hero.schedule(); }
function renderHomeHero() { sharedPresentation.hero.refresh(); }
function showHomeHero(index, userInitiated = false) { sharedPresentation.hero.show(index, userInitiated); }

function openHomeEntry(...args) { return sharedPresentation.homeCards.open(...args); }
function createHomeCard(...args) { return sharedPresentation.homeCards.create(...args); }

function renderHomeRail(...args) { return sharedPresentation.rows(...args); }
function renderHome(...args) { return sharedPresentation.homePresenter.render(...args); }
function restoreHomeCache() { return sharedPresentation.homeData.restore(); }
function saveHomeCache() { return sharedPresentation.homeData.save(); }

function rememberSearch(...args) { return sharedPresentation.searchSupport.remember(...args); }
function closeSearchSuggestions(...args) { return sharedPresentation.searchSupport.closeSuggestions(...args); }
function syncSearchClearButtons(...args) { return sharedPresentation.searchSupport.syncClearButtons(...args); }

function renderGlobalSearchResults() { sharedPresentation.search.refresh(); }
function closeGlobalSearch(options) { sharedPresentation.search.close(options); }

async function loadHomeData() { return sharedPresentation.homeData.load(); }

async function hydrateHomeMovieArtwork(items, options) {
  return sharedPresentation.artwork.movies(items, options);
}

async function hydrateHomeSeriesArtwork(items, options) {
  return sharedPresentation.artwork.series(items, options);
}

// Compatibility calls for legacy row renderers and layout editing.
function setHomeRailCycleAccessibility(...args) { return sharedPresentation.carousel.setHomeRailCycleAccessibility(...args); }
function homeRailLoopSize(...args) { return sharedPresentation.carousel.homeRailLoopSize(...args); }
function normalizeHomeRailLoop(...args) { return sharedPresentation.carousel.normalizeHomeRailLoop(...args); }
function prepareHomeRailLoop(...args) { return sharedPresentation.carousel.prepareHomeRailLoop(...args); }
function updateHomeRailNavigation(...args) { return sharedPresentation.carousel.updateHomeRailNavigation(...args); }
function homeRailStoredScroll(...args) { return sharedPresentation.carousel.homeRailStoredScroll(...args); }
function rememberHomeRailScroll(...args) { return sharedPresentation.carousel.rememberHomeRailScroll(...args); }
function rememberAllHomeRailScroll(...args) { return sharedPresentation.carousel.rememberAllHomeRailScroll(...args); }
function restoreHomeRailScroll(...args) { return sharedPresentation.carousel.restoreHomeRailScroll(...args); }
function moveHomeRail(...args) { return sharedPresentation.carousel.moveHomeRail(...args); }
function scheduleHomeRailSettle(...args) { return sharedPresentation.carousel.scheduleHomeRailSettle(...args); }

function currentHomeLayout() { return sharedPresentation.homeLayout.current(); }
function applyHomeLayout() { return sharedPresentation.homeLayout.apply(); }

function homeRatedEntries(...args) { return sharedPresentation.homeLanes.homeRatedEntries(...args); }

function homeLibraryEntries(...args) { return sharedPresentation.homeLanes.homeLibraryEntries(...args); }

function homeArtworkEntriesInLayout(...args) { return sharedPresentation.homeLanes.homeArtworkEntriesInLayout(...args); }

function homeRailDefinition(id) { return sharedPresentation.homeLayout.definition(id); }

function homeRailCardSignature(...args) { return sharedPresentation.railRenderer.signature(...args); }
function syncHomeCardContent(...args) { return sharedPresentation.railRenderer.sync(...args); }
function reconcileHomeRail(...args) { return sharedPresentation.railRenderer.reconcile(...args); }
function setHomeCardArtworkCandidates(...args) { return sharedPresentation.cardArtwork.set(...args); }
function setHomeCardMeta(...args) { return sharedPresentation.setMediaCardMeta(...args); }
