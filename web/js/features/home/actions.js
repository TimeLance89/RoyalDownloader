export function createHomeActions({
  renderSeriesResults,
  renderAnimeResults,
  getMovieHero,
  getHomeCatalog,
  getCatalogJellyfin,
  getJellyfinStatusText,
  getSetCatalogJellyfinBadge,
  getSeriesState,
  getAnime,
  getSearch,
  getTasteProfile,
  getMovieState,
  getTasteRanking,
  getHomeLanes,
  getDailyTop,
  getHomePresenter,
  getHeroSelection,
  getHero,
  getHomeCards,
  getRows,
  getHomeData,
  getSearchSupport,
  getArtwork,
  getCarousel,
  getHomeLayout,
  getRailRenderer,
  getCardArtwork,
  getSetMediaCardMeta,
}) {
  function refreshMovieFeatureCandidates() { getMovieHero().refresh(); }

  function homeMovieInstances(...args) { return getHomeCatalog().homeMovieInstances(...args); }

  function homeMovieBySlug(...args) { return getHomeCatalog().homeMovieBySlug(...args); }

  function applyMovieJellyfinStatus(slug, status, owned = null) { getCatalogJellyfin().applyMovie(slug, status, owned); }

  function homeSeriesBySlug(...args) { return getHomeCatalog().homeSeriesBySlug(...args); }

  function homeAnimeById(...args) { return getHomeCatalog().homeAnimeById(...args); }

  function mediaJellyfinStatus(...args) { return getHomeCatalog().mediaJellyfinStatus(...args); }

  function jellyfinStatusText(status) { return getJellyfinStatusText()(status); }
  function setCatalogJellyfinBadge(badge, status) { getSetCatalogJellyfinBadge()(badge, status); }

  function refreshCatalogJellyfinStatus(entries, render, options) { return getCatalogJellyfin().refresh(entries, render, options); }

  function refreshAllCatalogJellyfinStatuses() {
    const entries = [
      ...homeAllEntries(),
      ...getSeriesState().results.map(homeSeriesEntry),
      ...getAnime().get().results.map(homeAnimeEntry),
      ...getSearch().get().results,
    ];
    return refreshCatalogJellyfinStatus(entries, () => {
      renderHome();
      renderSeriesResults();
      renderAnimeResults();
      renderGlobalSearchResults();
    });
  }

  function uniqueHomeEntries(...args) { return getHomeCatalog().uniqueHomeEntries(...args); }

  function interleaveHomeEntries(...args) { return getHomeCatalog().interleaveHomeEntries(...args); }

  function homeMovieEntry(...args) { return getHomeCatalog().homeMovieEntry(...args); }

  function homeSeriesEntry(...args) { return getHomeCatalog().homeSeriesEntry(...args); }

  function homeAnimeEntry(...args) { return getHomeCatalog().homeAnimeEntry(...args); }

  function discoveryProfileStorageKey() { return getTasteProfile().key(); }

  function homeEntryKey(...args) { return getHomeCatalog().homeEntryKey(...args); }

  function homeEntryMedia(...args) { return getHomeCatalog().homeEntryMedia(...args); }

  function canonicalHomeText(...args) { return getHomeCatalog().canonicalHomeText(...args); }

  function homeContentKeys(...args) { return getHomeCatalog().homeContentKeys(...args); }

  function homeContentKey(...args) { return getHomeCatalog().homeContentKey(...args); }

  function uniqueHomeContentEntries(...args) { return getHomeCatalog().uniqueHomeContentEntries(...args); }

  function localDateKey(...args) { return getHomeCatalog().localDateKey(...args); }

  function stableDiscoveryHash(...args) { return getHomeCatalog().stableDiscoveryHash(...args); }

  function stableDailyOrder(...args) { return getHomeCatalog().stableDailyOrder(...args); }

  function currentTasteTarget(kind) {
    if (kind === "movie") {
      const slug = getMovieState().selectedSlug || "";
      const item = {
        ...(homeMovieBySlug(slug) || {}),
        ...(getMovieState().moviesCache[slug] || {}),
        ...(getMovieState().metadataCache[slug] || {}),
        slug,
      };
      return slug ? { key: `movie:${slug}`, item } : null;
    }
    const item = getSeriesState().current;
    return item?.base_slug ? { key: `series:${item.base_slug}`, item } : null;
  }

  function renderTasteProfileSummary(profile, offline) { getTasteRanking().summary(profile, offline); }
  function loadDiscoveryProfile(...args) { return getTasteProfile().load(...args); }
  function saveDiscoveryProfile(...args) { return getTasteProfile().save(...args); }
  function applyServerTasteProfile(...args) { return getTasteProfile().accept(...args); }
  function syncTasteProfile(...args) { return getTasteProfile().sync(...args); }
  function tasteMetadata(...args) { return getTasteProfile().metadata(...args); }
  function updateTasteFeedbackButtons(...args) { return getTasteProfile().updateButtons(...args); }
  function setTasteFeedback(...args) { return getTasteProfile().feedback(...args); }
  function trackDiscoveryPreference(...args) { return getTasteProfile().track(...args); }

  function allowedHomeEntries(entries, profile) { return getTasteRanking().allowed(entries, profile); }

  function homeAllEntries(...args) { return getHomeLanes().homeAllEntries(...args); }

  function homeTopEntries() { return getDailyTop().entries(); }

  function homeNewEntries(...args) { return getHomeLanes().homeNewEntries(...args); }

  function homePopularSeriesEntries(...args) { return getHomeLanes().homePopularSeriesEntries(...args); }

  function homePersonalizedEntries() { return getTasteRanking().entries(); }

  function favoriteDiscoveryGenre(...args) { return getHomeLanes().favoriteDiscoveryGenre(...args); }

  function homeGenreEntries(...args) { return getHomeLanes().homeGenreEntries(...args); }

  function homeExploreEntries(...args) { return getHomeLanes().homeExploreEntries(...args); }

  function homeGemEntries(...args) { return getHomeLanes().homeGemEntries(...args); }
  function takeDistinctHomeLane(...args) { return getHomeLanes().takeDistinctHomeLane(...args); }
  function homeDiscoveryLanes(...args) { return getHomeLanes().homeDiscoveryLanes(...args); }
  function shuffleHomeDiscovery(...args) { return getHomePresenter().shuffle(...args); }
  function homeHeroCandidates() { return getHeroSelection().candidates(); }
  function stopHomeHeroRotation() { getHero().stop(); }
  function scheduleHomeHeroRotation() { getHero().schedule(); }
  function renderHomeHero() { getHero().refresh(); }
  function showHomeHero(index, userInitiated = false) { getHero().show(index, userInitiated); }

  function openHomeEntry(...args) { return getHomeCards().open(...args); }
  function createHomeCard(...args) { return getHomeCards().create(...args); }

  function renderHomeRail(...args) { return getRows()(...args); }
  function renderHome(...args) { return getHomePresenter().render(...args); }
  function saveHomeCache() { return getHomeData().save(); }

  function rememberSearch(...args) { return getSearchSupport().remember(...args); }
  function closeSearchSuggestions(...args) { return getSearchSupport().closeSuggestions(...args); }
  function syncSearchClearButtons(...args) { return getSearchSupport().syncClearButtons(...args); }

  function renderGlobalSearchResults() { getSearch().refresh(); }
  function closeGlobalSearch(options) { getSearch().close(options); }

  async function hydrateHomeMovieArtwork(items, options) {
    return getArtwork().movies(items, options);
  }

  async function hydrateHomeSeriesArtwork(items, options) {
    return getArtwork().series(items, options);
  }

  // Shell actions for row renderers and layout editing.
  function setHomeRailCycleAccessibility(...args) { return getCarousel().setHomeRailCycleAccessibility(...args); }
  function homeRailLoopSize(...args) { return getCarousel().homeRailLoopSize(...args); }
  function normalizeHomeRailLoop(...args) { return getCarousel().normalizeHomeRailLoop(...args); }
  function prepareHomeRailLoop(...args) { return getCarousel().prepareHomeRailLoop(...args); }
  function updateHomeRailNavigation(...args) { return getCarousel().updateHomeRailNavigation(...args); }
  function homeRailStoredScroll(...args) { return getCarousel().homeRailStoredScroll(...args); }
  function rememberHomeRailScroll(...args) { return getCarousel().rememberHomeRailScroll(...args); }
  function rememberAllHomeRailScroll(...args) { return getCarousel().rememberAllHomeRailScroll(...args); }
  function restoreHomeRailScroll(...args) { return getCarousel().restoreHomeRailScroll(...args); }
  function moveHomeRail(...args) { return getCarousel().moveHomeRail(...args); }
  function scheduleHomeRailSettle(...args) { return getCarousel().scheduleHomeRailSettle(...args); }

  function currentHomeLayout() { return getHomeLayout().current(); }
  function applyHomeLayout() { return getHomeLayout().apply(); }

  function homeRatedEntries(...args) { return getHomeLanes().homeRatedEntries(...args); }

  function homeLibraryEntries(...args) { return getHomeLanes().homeLibraryEntries(...args); }

  function homeArtworkEntriesInLayout(...args) { return getHomeLanes().homeArtworkEntriesInLayout(...args); }

  function homeRailDefinition(id) { return getHomeLayout().definition(id); }

  function homeRailCardSignature(...args) { return getRailRenderer().signature(...args); }
  function syncHomeCardContent(...args) { return getRailRenderer().sync(...args); }
  function reconcileHomeRail(...args) { return getRailRenderer().reconcile(...args); }
  function setHomeCardArtworkCandidates(...args) { return getCardArtwork().set(...args); }
  function setHomeCardMeta(...args) { return getSetMediaCardMeta()(...args); }
  return { refreshMovieFeatureCandidates, homeMovieInstances, homeMovieBySlug, applyMovieJellyfinStatus, homeSeriesBySlug, homeAnimeById, mediaJellyfinStatus, jellyfinStatusText, setCatalogJellyfinBadge, refreshCatalogJellyfinStatus, refreshAllCatalogJellyfinStatuses, uniqueHomeEntries, interleaveHomeEntries, homeMovieEntry, homeSeriesEntry, homeAnimeEntry, discoveryProfileStorageKey, homeEntryKey, homeEntryMedia, canonicalHomeText, homeContentKeys, homeContentKey, uniqueHomeContentEntries, localDateKey, stableDiscoveryHash, stableDailyOrder, currentTasteTarget, renderTasteProfileSummary, loadDiscoveryProfile, saveDiscoveryProfile, applyServerTasteProfile, syncTasteProfile, tasteMetadata, updateTasteFeedbackButtons, setTasteFeedback, trackDiscoveryPreference, allowedHomeEntries, homeAllEntries, homeTopEntries, homeNewEntries, homePopularSeriesEntries, homePersonalizedEntries, favoriteDiscoveryGenre, homeGenreEntries, homeExploreEntries, homeGemEntries, takeDistinctHomeLane, homeDiscoveryLanes, shuffleHomeDiscovery, homeHeroCandidates, stopHomeHeroRotation, scheduleHomeHeroRotation, renderHomeHero, showHomeHero, openHomeEntry, createHomeCard, renderHomeRail, renderHome, saveHomeCache, rememberSearch, closeSearchSuggestions, syncSearchClearButtons, renderGlobalSearchResults, closeGlobalSearch, hydrateHomeMovieArtwork, hydrateHomeSeriesArtwork, setHomeRailCycleAccessibility, homeRailLoopSize, normalizeHomeRailLoop, prepareHomeRailLoop, updateHomeRailNavigation, homeRailStoredScroll, rememberHomeRailScroll, rememberAllHomeRailScroll, restoreHomeRailScroll, moveHomeRail, scheduleHomeRailSettle, currentHomeLayout, applyHomeLayout, homeRatedEntries, homeLibraryEntries, homeArtworkEntriesInLayout, homeRailDefinition, homeRailCardSignature, syncHomeCardContent, reconcileHomeRail, setHomeCardArtworkCandidates, setHomeCardMeta };
}
