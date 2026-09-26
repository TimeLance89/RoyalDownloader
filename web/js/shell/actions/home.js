import { sharedPresentation } from "../presentation.js";
import { renderSeriesResults } from "./series.js";
import { renderAnimeResults } from "./anime.js";
export function refreshMovieFeatureCandidates() { sharedPresentation.movieHero.refresh(); }

export function homeMovieInstances(...args) { return sharedPresentation.homeCatalog.homeMovieInstances(...args); }

export function homeMovieBySlug(...args) { return sharedPresentation.homeCatalog.homeMovieBySlug(...args); }

export function applyMovieJellyfinStatus(slug, status, owned = null) { sharedPresentation.catalogJellyfin.applyMovie(slug, status, owned); }

export function homeSeriesBySlug(...args) { return sharedPresentation.homeCatalog.homeSeriesBySlug(...args); }

export function homeAnimeById(...args) { return sharedPresentation.homeCatalog.homeAnimeById(...args); }

export function mediaJellyfinStatus(...args) { return sharedPresentation.homeCatalog.mediaJellyfinStatus(...args); }

export function jellyfinStatusText(status) { return sharedPresentation.jellyfinStatusText(status); }
export function setCatalogJellyfinBadge(badge, status) { sharedPresentation.setCatalogJellyfinBadge(badge, status); }

export function refreshCatalogJellyfinStatus(entries, render, options) { return sharedPresentation.catalogJellyfin.refresh(entries, render, options); }

export function refreshAllCatalogJellyfinStatuses() {
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

export function uniqueHomeEntries(...args) { return sharedPresentation.homeCatalog.uniqueHomeEntries(...args); }

export function interleaveHomeEntries(...args) { return sharedPresentation.homeCatalog.interleaveHomeEntries(...args); }

export function homeMovieEntry(...args) { return sharedPresentation.homeCatalog.homeMovieEntry(...args); }

export function homeSeriesEntry(...args) { return sharedPresentation.homeCatalog.homeSeriesEntry(...args); }

export function homeAnimeEntry(...args) { return sharedPresentation.homeCatalog.homeAnimeEntry(...args); }

export function discoveryProfileStorageKey() { return sharedPresentation.tasteProfile.key(); }

export function homeEntryKey(...args) { return sharedPresentation.homeCatalog.homeEntryKey(...args); }

export function homeEntryMedia(...args) { return sharedPresentation.homeCatalog.homeEntryMedia(...args); }

export function canonicalHomeText(...args) { return sharedPresentation.homeCatalog.canonicalHomeText(...args); }

export function homeContentKeys(...args) { return sharedPresentation.homeCatalog.homeContentKeys(...args); }

export function homeContentKey(...args) { return sharedPresentation.homeCatalog.homeContentKey(...args); }

export function uniqueHomeContentEntries(...args) { return sharedPresentation.homeCatalog.uniqueHomeContentEntries(...args); }

export function localDateKey(...args) { return sharedPresentation.homeCatalog.localDateKey(...args); }

export function stableDiscoveryHash(...args) { return sharedPresentation.homeCatalog.stableDiscoveryHash(...args); }

export function stableDailyOrder(...args) { return sharedPresentation.homeCatalog.stableDailyOrder(...args); }

export function currentTasteTarget(kind) {
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

export function renderTasteProfileSummary(profile, offline) { sharedPresentation.tasteRanking.summary(profile, offline); }
export function loadDiscoveryProfile(...args) { return sharedPresentation.tasteProfile.load(...args); }
export function saveDiscoveryProfile(...args) { return sharedPresentation.tasteProfile.save(...args); }
export function applyServerTasteProfile(...args) { return sharedPresentation.tasteProfile.accept(...args); }
export function syncTasteProfile(...args) { return sharedPresentation.tasteProfile.sync(...args); }
export function tasteMetadata(...args) { return sharedPresentation.tasteProfile.metadata(...args); }
export function updateTasteFeedbackButtons(...args) { return sharedPresentation.tasteProfile.updateButtons(...args); }
export function setTasteFeedback(...args) { return sharedPresentation.tasteProfile.feedback(...args); }
export function trackDiscoveryPreference(...args) { return sharedPresentation.tasteProfile.track(...args); }

export function allowedHomeEntries(entries, profile) { return sharedPresentation.tasteRanking.allowed(entries, profile); }

export function homeAllEntries(...args) { return sharedPresentation.homeLanes.homeAllEntries(...args); }

export function homeTopEntries() { return sharedPresentation.dailyTop.entries(); }

export function homeNewEntries(...args) { return sharedPresentation.homeLanes.homeNewEntries(...args); }

export function homePopularSeriesEntries(...args) { return sharedPresentation.homeLanes.homePopularSeriesEntries(...args); }

export function homePersonalizedEntries() { return sharedPresentation.tasteRanking.entries(); }

export function favoriteDiscoveryGenre(...args) { return sharedPresentation.homeLanes.favoriteDiscoveryGenre(...args); }

export function homeGenreEntries(...args) { return sharedPresentation.homeLanes.homeGenreEntries(...args); }

export function homeExploreEntries(...args) { return sharedPresentation.homeLanes.homeExploreEntries(...args); }

export function homeGemEntries(...args) { return sharedPresentation.homeLanes.homeGemEntries(...args); }
export function takeDistinctHomeLane(...args) { return sharedPresentation.homeLanes.takeDistinctHomeLane(...args); }
export function homeDiscoveryLanes(...args) { return sharedPresentation.homeLanes.homeDiscoveryLanes(...args); }
export function shuffleHomeDiscovery(...args) { return sharedPresentation.homePresenter.shuffle(...args); }
export function homeHeroCandidates() { return sharedPresentation.heroSelection.candidates(); }
export function stopHomeHeroRotation() { sharedPresentation.hero.stop(); }
export function scheduleHomeHeroRotation() { sharedPresentation.hero.schedule(); }
export function renderHomeHero() { sharedPresentation.hero.refresh(); }
export function showHomeHero(index, userInitiated = false) { sharedPresentation.hero.show(index, userInitiated); }

export function openHomeEntry(...args) { return sharedPresentation.homeCards.open(...args); }
export function createHomeCard(...args) { return sharedPresentation.homeCards.create(...args); }

export function renderHomeRail(...args) { return sharedPresentation.rows(...args); }
export function renderHome(...args) { return sharedPresentation.homePresenter.render(...args); }
export function saveHomeCache() { return sharedPresentation.homeData.save(); }

export function rememberSearch(...args) { return sharedPresentation.searchSupport.remember(...args); }
export function closeSearchSuggestions(...args) { return sharedPresentation.searchSupport.closeSuggestions(...args); }
export function syncSearchClearButtons(...args) { return sharedPresentation.searchSupport.syncClearButtons(...args); }

export function renderGlobalSearchResults() { sharedPresentation.search.refresh(); }
export function closeGlobalSearch(options) { sharedPresentation.search.close(options); }


export async function hydrateHomeMovieArtwork(items, options) {
  return sharedPresentation.artwork.movies(items, options);
}

export async function hydrateHomeSeriesArtwork(items, options) {
  return sharedPresentation.artwork.series(items, options);
}

// Shell actions for row renderers and layout editing.
export function setHomeRailCycleAccessibility(...args) { return sharedPresentation.carousel.setHomeRailCycleAccessibility(...args); }
export function homeRailLoopSize(...args) { return sharedPresentation.carousel.homeRailLoopSize(...args); }
export function normalizeHomeRailLoop(...args) { return sharedPresentation.carousel.normalizeHomeRailLoop(...args); }
export function prepareHomeRailLoop(...args) { return sharedPresentation.carousel.prepareHomeRailLoop(...args); }
export function updateHomeRailNavigation(...args) { return sharedPresentation.carousel.updateHomeRailNavigation(...args); }
export function homeRailStoredScroll(...args) { return sharedPresentation.carousel.homeRailStoredScroll(...args); }
export function rememberHomeRailScroll(...args) { return sharedPresentation.carousel.rememberHomeRailScroll(...args); }
export function rememberAllHomeRailScroll(...args) { return sharedPresentation.carousel.rememberAllHomeRailScroll(...args); }
export function restoreHomeRailScroll(...args) { return sharedPresentation.carousel.restoreHomeRailScroll(...args); }
export function moveHomeRail(...args) { return sharedPresentation.carousel.moveHomeRail(...args); }
export function scheduleHomeRailSettle(...args) { return sharedPresentation.carousel.scheduleHomeRailSettle(...args); }

export function currentHomeLayout() { return sharedPresentation.homeLayout.current(); }
export function applyHomeLayout() { return sharedPresentation.homeLayout.apply(); }

export function homeRatedEntries(...args) { return sharedPresentation.homeLanes.homeRatedEntries(...args); }

export function homeLibraryEntries(...args) { return sharedPresentation.homeLanes.homeLibraryEntries(...args); }

export function homeArtworkEntriesInLayout(...args) { return sharedPresentation.homeLanes.homeArtworkEntriesInLayout(...args); }

export function homeRailDefinition(id) { return sharedPresentation.homeLayout.definition(id); }

export function homeRailCardSignature(...args) { return sharedPresentation.railRenderer.signature(...args); }
export function syncHomeCardContent(...args) { return sharedPresentation.railRenderer.sync(...args); }
export function reconcileHomeRail(...args) { return sharedPresentation.railRenderer.reconcile(...args); }
export function setHomeCardArtworkCandidates(...args) { return sharedPresentation.cardArtwork.set(...args); }
export function setHomeCardMeta(...args) { return sharedPresentation.setMediaCardMeta(...args); }
