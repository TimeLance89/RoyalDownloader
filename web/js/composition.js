import { createSubscriptionSummary, subscriptionMonogram, watchlistStatusText } from "./features/subscriptions/summary.js";
import { createStartupCurtain } from "./shared/components/startup-curtain.js";
import {
  WATCH_CLEANUP_DEFAULT,
  WATCH_CLEANUP_LABELS,
  WATCH_MODE_DEFAULT,
  WATCH_MODE_EXPLANATIONS,
  WATCH_MODE_LABELS,
  closeMediaModal,
  closeMobileQueue,
  handleLiveMessage,
  handleMediaModalKeydown,
  openMediaModal,
  openMobileQueue,
  recheckAniworldInfinite,
  recheckFpInfinite,
  recheckSeriesInfinite,
  refreshFpQueuePresentation,
  refreshQueueUiAfterChange,
  renderQueue,
  renderSerienstreamHealth,
  resyncAfterWsOpen,
  setDownloadState,
  setQueueDockExpanded,
  sharedPresentation,
  showPersistenceWarning,
  state,
  switchTab,
  syncAnimeNavigationVisibility,
  syncAniworldNavigationVisibility,
  syncMovieSubscriptions,
  syncQueueSnapshot,
  syncWatchlistSnapshot,
  toggleDesktopQueue,
  updateQueueJobProgress,
} from "./shell/presentation.js";
import {
  activateResultCard,
  applyFpResults,
  applyFpSmartFilters,
  basicMovieMetadata,
  closeFpTrailerModal,
  configureFpDetailAction,
  configureFpTrailer,
  createResultCardVisual,
  discardObservedResultPosters,
  findFpResultCard,
  fpDetailJellyfinValue,
  fpGenreChange,
  fpMetadataPreloadItems,
  fpResultMedia,
  fpResultYear,
  fpShowList,
  fpSmartFilteredResults,
  fpSmartFilters,
  fpStatusMessage,
  fpTrailerYoutubeKey,
  loadNextFpPage,
  mediaCardInitials,
  mediaContentLanguages,
  mergeCatalogItems,
  mergeCatalogSources,
  mergeFpMetadata,
  metadataPreviewMovie,
  normalizeUiContentLanguage,
  openFpTrailerModal,
  preloadSeriesPosterImages,
  preloadTmdbMetadata,
  presentMovieSubscriptions,
  refreshFpCatalogInBackground,
  refreshFpJellyfinStatus,
  refreshSeriesCatalogInBackground,
  refreshSeriesJellyfinStatus,
  renderFpAbout,
  renderFpExtras,
  renderFpResults,
  renderFpSimilarTitles,
  resetFpSmartFilters,
  scheduleFpCatalogRefresh,
  scheduleResultPoster,
  selectFpRow,
  setActiveGenreFilter,
  setFpDetailAvailability,
  setFpDetailJellyfinStatus,
  setFpJellyfinBadge,
  setFpPosterJellyfinBadge,
  showFpDetail,
  stopFpDetailHeroTrailer,
  syncFpCatalogFromHome,
  syncFpQueueIndicators,
  syncResultCardPoster,
  syncSeriesCatalogFromHome,
  toggleFpPick,
  trailerModalFocusableElements,
  updateFpInfiniteState,
  updateFpJellyfinBadges,
  updateFpResultCard,
  updateFpResultSelection,
  updateSeriesJellyfinBadge,
  updateSeriesStatus,
} from "./shell/actions/movies.js";
import {
  applySeriesResults,
  configureSeriesTrailer,
  findSeriesResultCard,
  firstEpisodeSlug,
  isEpisodeEligible,
  isEpisodeSelectable,
  loadNextSeriesPage,
  loadSeries,
  markSeriesSlugDownloaded,
  mergeSeriesDetailPayload,
  pruneSeriesEpisodeSelection,
  refreshSeriesTileStates,
  renderSeriesCatalogHero,
  renderSeriesDetailDiscovery,
  renderSeriesResults,
  renderSeriesTiles,
  seriesBrowse,
  seriesEpisodes,
  seriesStructureFingerprint,
  showSeriesDetail,
  showSeriesLoading,
  stopSeriesDetailHeroTrailer,
  syncSeriesQueueFlags,
  updateSeriesInfiniteState,
  updateSeriesOverview,
  updateSeriesResultSelection,
  updateWatchBtn,
  verifyHuhuEpisodeLanguages,
} from "./shell/actions/series.js";
import {
  allowedHomeEntries,
  applyHomeLayout,
  applyMovieJellyfinStatus,
  applyServerTasteProfile,
  closeGlobalSearch,
  closeSearchSuggestions,
  createHomeCard,
  currentHomeLayout,
  currentTasteTarget,
  favoriteDiscoveryGenre,
  homeAllEntries,
  homeAnimeById,
  homeAnimeEntry,
  homeArtworkEntriesInLayout,
  homeDiscoveryLanes,
  homeEntryKey,
  homeEntryMedia,
  homeHeroCandidates,
  homeMovieBySlug,
  homeMovieEntry,
  homeMovieInstances,
  homePersonalizedEntries,
  homeRailCardSignature,
  homeRailDefinition,
  homeSeriesBySlug,
  homeSeriesEntry,
  homeTopEntries,
  hydrateHomeMovieArtwork,
  hydrateHomeSeriesArtwork,
  interleaveHomeEntries,
  jellyfinStatusText,
  loadDiscoveryProfile,
  localDateKey,
  mediaJellyfinStatus,
  normalizeHomeRailLoop,
  openHomeEntry,
  reconcileHomeRail,
  refreshAllCatalogJellyfinStatuses,
  refreshCatalogJellyfinStatus,
  refreshMovieFeatureCandidates,
  rememberAllHomeRailScroll,
  rememberSearch,
  renderHome,
  renderHomeHero,
  renderHomeRail,
  renderTasteProfileSummary,
  saveHomeCache,
  scheduleHomeHeroRotation,
  setCatalogJellyfinBadge,
  setHomeCardArtworkCandidates,
  setHomeCardMeta,
  shuffleHomeDiscovery,
  stableDailyOrder,
  stableDiscoveryHash,
  stopHomeHeroRotation,
  syncHomeCardContent,
  syncSearchClearButtons,
  syncTasteProfile,
  tasteMetadata,
  trackDiscoveryPreference,
  uniqueHomeContentEntries,
  uniqueHomeEntries,
  updateHomeRailNavigation,
  updateTasteFeedbackButtons,
} from "./shell/actions/home.js";
import { personalStorageKey } from "./shell/actions/user-profile.js";
import {
  markAnimeSlugDownloaded,
  openAnimeDetail,
  openWatchModeModal,
  syncAnimeQueueFlags,
  watchlistEntryForSeries,
} from "./shell/actions/anime.js";
import {
  dedupeCatalogMedia,
  openWatchlistEntry,
  presentWatchlist,
  reconcileMovieCatalogDuplicates,
  reconcileSeriesCatalogDuplicates,
  refreshWatchlist,
  watchlistCheckResultText,
} from "./shell/actions/library.js";
import { createMovieCollectionSearchCard, homeCollectionEntry, openMovieCollection } from "./shell/actions/movie-collections.js";
import { loadNextAniworldPage, markAniworldSlugDownloaded, syncAniworldQueueFlags } from "./shell/actions/aniworld.js";
import { applyFpDownloadJobResult } from "./shell/actions/movie_download_feedback.js";
import { createArtworkUrls } from "./shared/utils/artwork-url.js";
import { createQueueSync } from "./features/downloads/sync.js";
import { createLocalization } from "./core/localization.js";
import { createShell } from "./core/shell.js";
import { createDetailDiscovery } from "./features/media-details/discovery.js";
import { createMoviePresentation } from "./features/discovery/movie-presentation.js";
import { createMovieStatus } from "./features/integrations/movie-status.js";
import { createSeriesStatus } from "./features/media-details/series-status.js";
import { createResultCards } from "./shared/components/result-card.js";
import { createSeriesPresentation } from "./features/discovery/series-presentation.js";
import { createSeriesEpisodes } from "./features/media-details/series-episodes.js";
import { createMovieDownloads } from "./features/downloads/movies.js";
import { createMovieState } from "./features/discovery/movie-state.js";
import { createSeriesState } from "./features/discovery/series-state.js";
import { createSearchSupport } from "./features/search/support.js";
import { createMovieCollections } from "./features/collections/index.js";
import { createHomeCards } from "./features/home/cards.js";
import { createHomePresenter } from "./features/home/presenter.js";
import { createHomeLanes } from "./features/home/lanes.js";
import { createHomeCatalog } from "./features/home/catalog.js";
import { createTasteProfile } from "./features/profile/taste.js";
import { createAniworld } from "./features/discovery/aniworld.js";
import { createAnime } from "./features/discovery/anime.js";
import { createSeriesChecks } from "./features/media-details/series-checks.js";
import { createSeriesDetailsLoader } from "./features/media-details/series-loader.js";
import { createMovieDetailsLoader } from "./features/media-details/movie-loader.js";
import { createMovieFilters } from "./features/discovery/movie-filters.js";
import { createSeriesBrowse } from "./features/discovery/series-browse.js";
import { createMovieBrowse } from "./features/discovery/movie-browse.js";
import { createCatalogIdentity, cleanMediaCardInitials } from "./features/discovery/catalog-identity.js";
import { createCatalogSeed } from "./features/discovery/catalog-seed.js";
import { createCatalogMetadata } from "./features/discovery/catalog-metadata.js";
import { createPosterPreloader } from "./features/discovery/poster-preload.js";
import { createCatalogRefresh } from "./features/discovery/catalog-refresh.js";
import { createMediaLanguage } from "./features/media-details/language.js";
import { createDiscoveryPolicy } from "./features/home/discovery-policy.js";
import { createMood } from "./features/mood/index.js";
import { createCardDock } from "./features/home/card-dock.js";
import { createCardArtwork } from "./shared/components/card-artwork.js";
import { createRailRenderer } from "./features/home/rail-renderer.js";
import { createHomeLayout } from "./features/home/layout.js";
import { createTrailers } from "./features/trailers/index.js";
import { createJellyfinResume } from "./features/integrations/resume.js";
import { createTasteRanking } from "./features/home/taste-ranking.js";
import { createHeroSelection } from "./features/home/hero-selection.js";
import { createDailyTop } from "./features/home/daily-top.js";
import { createCatalogJellyfin } from "./features/integrations/catalog-jellyfin.js";
import { createHomeSearch } from "./features/search/home.js";
import { createTasteOnboarding } from "./features/profile/taste-onboarding.js";
import { createStartup } from "./core/startup.js";
import { createGenres } from "./features/discovery/genres.js";
import { createAuthentication } from "./features/auth/index.js";
import { createInfiniteScroll } from "./shared/components/infinite-scroll.js";
import { createSetup } from "./features/setup/index.js";
import { createSettings } from "./features/settings/index.js";
import {
  updateDeploymentModeHints as deploymentHints,
  selectedDeploymentMode as deploymentMode,
} from "./features/settings/deployment.js";
import { createJellyfinSettings } from "./features/integrations/jellyfin.js";
import { createJellyfinUserPicker } from "./features/integrations/jellyfin-users.js";
import { createProviderSettings } from "./features/settings/providers.js";
import { createIntegrationSettings } from "./features/integrations/settings.js";
import { createSettingsNavigation } from "./features/settings/navigation.js";
import { createDirectoryPicker } from "./features/settings/directory.js";
import { createUpdater } from "./features/settings/updater.js";
import { createSearch } from "./features/search/index.js";
import { createAccountSettings } from "./features/settings/account.js";
import { logout } from "./core/session.js";
import { createRecommendations } from "./features/home/recommendations.js";
import { createIntelligenceSettings } from "./features/settings/intelligence.js";
import { createHomeData } from "./features/home/data.js";
import { createCatalogArtwork } from "./features/discovery/artwork.js";
import { createCalendar } from "./features/calendar/index.js";
import { createMovieSubscriptionsView } from "./features/subscriptions/movies.js";
import { createMovieSubscriptionRules } from "./features/subscriptions/movie-rules.js";
import { movieSubscriptionFor } from "./features/subscriptions/movie-model.js";
import { createSubscriptionRules } from "./features/subscriptions/rules.js";
import { createLibrary } from "./features/subscriptions/index.js";
import { libraryCheckedLabel } from "./features/subscriptions/model.js";
import { createSubscriptions } from "./features/subscriptions/state.js";
import { createNotifications } from "./features/notifications/index.js";
import { downloadedEpisodeLabel } from "./features/notifications/model.js";
import { createAutomation } from "./features/automation/index.js";
import { createStorage } from "./features/storage/index.js";
import { createMovieHero } from "./features/discovery/movie-hero.js";
import { appStore } from "./core/store.js";
import { userInitials, userRoleLabel } from "./features/profile/identity.js";
import { createUserMenu } from "./features/profile/menu.js";
import { createHousehold } from "./features/profile/household.js";
import { createProfile } from "./features/profile/index.js";
import { createModuleSettings } from "./features/settings/modules.js";
import { createModalController } from "./shared/components/modal.js";
import { createServerBuildMonitor } from "./features/system/server-build.js";
import { createDownloadEvents } from "./features/downloads/events.js";
import { createHero } from "./features/home/hero.js";
import { createHomeRows } from "./features/home/rows.js";
import { createCarousel } from "./shared/components/carousel.js";
import { renderMediaCard, setMediaCardMeta } from "./shared/components/media-card.js";
import { jellyfinStatusText as statusText, setCatalogJellyfinBadge as statusBadge } from "./shared/components/status-badge.js";
import { createQueueView } from "./features/downloads/view.js";
import { createApplication } from "./app.js";
import { createHomeLifecycle } from "./features/home/index.js";

export function preparePresentation() {
  sharedPresentation.startupCurtain = createStartupCurtain(document);
  const artworkUrls = createArtworkUrls(document.defaultView.location.origin);
  const i18n = createLocalization(document);
  i18n.primeStoredInterface();
  const movieState = createMovieState(), seriesState = createSeriesState();
  const monitor = createServerBuildMonitor();
  monitor.mount();
  window.addEventListener("pagehide", () => monitor.unmount());
  window.addEventListener("pageshow", event => { if (event.persisted) monitor.mount(); });
  const household = createHousehold(document.getElementById("household-panel"), { userInitials, userRoleLabel });
  const userMenu = createUserMenu(document.getElementById("user-menu"), {
    logout, navigate: name => switchTab(name),
    openHousehold: () => household.open(),
    openSecurity() { switchTab("einstellungen"); document.getElementById("settings-account")?.scrollIntoView({ behavior: "smooth" }); },
  });
  window.addEventListener("pagehide", () => { household.unmount(); userMenu.unmount(); });
  window.addEventListener("pageshow", event => { if (event.persisted && appStore.get().user) { household.mount(); userMenu.mount(); } });
  document.addEventListener("royal:session-expired", () => { household.unmount(); userMenu.unmount(); });
  const modal = createModalController(document.body, {
    closeCollectionDetails: () => sharedPresentation.movieCollections.close(),
    closeAniworldDetails: () => sharedPresentation.aniworld.closeDetail(),
    closeAnimeDetails: () => sharedPresentation.anime.closeDetail(),
    closeSeriesDetails() { sharedPresentation.seriesDetailsLoader.unmount(); sharedPresentation.seriesChecks.unmount(); },
    closeMovieDetails: () => { sharedPresentation.movieDetailsLoader.unmount(); sharedPresentation.movieDownloads.closeDetail(); sharedPresentation.movieStatus.cancel(); },
    closeLanguageChoice: () => sharedPresentation.mediaLanguage.close(),
    closeFpTrailerModal: (...args) => closeFpTrailerModal(...args),
    stopFpDetailHeroTrailer: () => stopFpDetailHeroTrailer(),
    stopSeriesDetailHeroTrailer: () => stopSeriesDetailHeroTrailer(),
    trailerModalFocusableElements: () => trailerModalFocusableElements(),
    resumeMoodMatchAfterDetail: () => sharedPresentation.mood.resumeAfterDetail(),
  });
  window.addEventListener("pagehide", () => modal.unmount());
  document.addEventListener("royal:session-expired", () => modal.unmount());
  const subscriptions = createSubscriptions({ onPersistence: data => showPersistenceWarning("Serien-Abos", data) });
  const movieSubscriptions = createSubscriptions({ kind: "movies", onPersistence: data => showPersistenceWarning("Film-Abos", data) });
  const movieSubscriptionRules = createMovieSubscriptionRules(document.getElementById("movie-subscription-modal"), {
    model: movieSubscriptions, isJellyfinConfigured: () => sharedPresentation.jellyfin.get().userConfigured,
  });
  const intelligence = createIntelligenceSettings(document.querySelector(".ai-settings-card"), {
    onConfig: () => recommendations.configure(),
  });
  const recommendations = createRecommendations(document.getElementById("home-ai-rail"), {
    getConfig: intelligence.get, homeAllEntries: () => homeAllEntries(),
    homeEntryKey: entry => homeEntryKey(entry), homeEntryMedia: entry => homeEntryMedia(entry),
    mediaJellyfinStatus: entry => mediaJellyfinStatus(entry), createHomeCard: (...args) => createHomeCard(...args),
    syncHomeCardContent: (...args) => syncHomeCardContent(...args),
    reconcileHomeRail: (...args) => reconcileHomeRail(...args), updateHomeRailNavigation: (...args) => updateHomeRailNavigation(...args),
  });
  const discoveryPolicy = createDiscoveryPolicy({
    personalStorageKey, homeEntryMedia, homeEntryKey, localDateKey,
    getShuffle: () => sharedPresentation.homePresenter.get().discoveryShuffle, stableDiscoveryHash, mediaContentLanguages,
    getHomeData: () => sharedPresentation.homeData.get(), homeMovieEntry, homeSeriesEntry,
    allowedHomeEntries: entries => allowedHomeEntries(entries), uniqueHomeEntries, normalizeUiContentLanguage,
  });
  Object.assign(sharedPresentation, {
    subscriptionSummary: createSubscriptionSummary(document.getElementById("series-subscriptions-list"), document.getElementById("series-subscriptions-count"), {
      getItems: () => sharedPresentation.subscriptions.get().items, open: openWatchlistEntry,
      WATCH_MODE_LABELS, WATCH_MODE_DEFAULT, WATCH_CLEANUP_LABELS, WATCH_CLEANUP_DEFAULT,
    }),
    discoveryPolicy, cleanMediaCardInitials, movieState, seriesState, localization: i18n,
    queueSync: createQueueSync({ getView: () => sharedPresentation.queueView, downloadState: state.download,
      setDownloadState, refreshFpQueuePresentation, renderSeriesTiles }),
    shell: createShell(document, {
      switchTab, openMobileQueue, closeMobileQueue, toggleDesktopQueue, closeMediaModal,
      openWatchModeModal, handleMediaModalKeydown, setQueueDockExpanded, refreshQueueUiAfterChange,
      renderSerienstreamHealth, setDownloadState, getDownloadPercent: () => state.download.percent,
      closeNotifications: () => sharedPresentation.notifications.close(),
      openDirectory: (...args) => sharedPresentation.directory.open(...args),
    }),
    movieDiscovery: createDetailDiscovery(document.getElementById("fp-detail-modal"), {
      kind: "movie", coverUrl: url => artworkUrls.coverUrl(url), selectFpRow, loadSeries, fpTrailerYoutubeKey, openFpTrailerModal,
    }),
    seriesDiscovery: createDetailDiscovery(document.getElementById("series-detail-modal"), {
      kind: "series", coverUrl: url => artworkUrls.coverUrl(url), selectFpRow, loadSeries, fpTrailerYoutubeKey, openFpTrailerModal,
    }),
    moviePresentation: createMoviePresentation(document.getElementById("tab-filme"), document.getElementById("fp-detail-modal"), {
      locale: () => i18n.locale(), movieState, getQueuedSlugs: () => state.queuedSlugs, coverUrl: url => artworkUrls.coverUrl(url),
      subscriptionFor: (...args) => sharedPresentation.movieSubscriptionFor(...args),
      openSubscription: (...args) => sharedPresentation.movieSubscriptionRules.open(...args),
      activateResultCard, applyFpSmartFilters, configureFpDetailAction, configureFpTrailer, createResultCardVisual, dedupeCatalogMedia, discardObservedResultPosters, fpMetadataPreloadItems, fpSmartFilteredResults, fpSmartFilters, homeMovieBySlug, mediaJellyfinStatus, mergeFpMetadata, preloadTmdbMetadata, refreshFpJellyfinStatus, refreshMovieFeatureCandidates, renderFpAbout, renderFpExtras, renderFpSimilarTitles, scheduleFpCatalogRefresh, selectFpRow, setCatalogJellyfinBadge, syncResultCardPoster, toggleFpPick, updateTasteFeedbackButtons,
    }),
    seriesStatus: createSeriesStatus(document.getElementById("series-status"), document.getElementById("series-jellyfin-status")),
    movieStatus: createMovieStatus({ movieState, refreshCatalogJellyfinStatus, homeMovieEntry,
      homeMovieBySlug, updateFpJellyfinBadges, setFpDetailJellyfinStatus }),
    resultCards: createResultCards(document, {
      coverCandidates: url => artworkUrls.coverThumbnailCandidates(url), mediaCardInitials, scheduleResultPoster,
      discardPoster: image => sharedPresentation.cardArtwork.discard(image), setFpPosterJellyfinBadge,
      markLanguage: (node, media) => sharedPresentation.mediaLanguage.mark(node, media),
    }),
    seriesPresentation: createSeriesPresentation(document.getElementById("tab-serien"), document.getElementById("series-detail-modal"), {
      watchModeLabel: mode => WATCH_MODE_LABELS[mode] || WATCH_MODE_LABELS[WATCH_MODE_DEFAULT],
      seriesState, getHomeData: () => sharedPresentation.homeData.get(), coverUrl: url => artworkUrls.coverUrl(url),
      activateResultCard, configureSeriesTrailer, createResultCardVisual, dedupeCatalogMedia, discardObservedResultPosters, homeSeriesEntry, hydrateHomeSeriesArtwork, isEpisodeEligible, loadSeries, mediaJellyfinStatus, mergeCatalogItems, mergeCatalogSources, openMediaModal, recheckSeriesInfinite, refreshCatalogJellyfinStatus, renderSeriesDetailDiscovery, renderSeriesTiles, setFpJellyfinBadge, setFpPosterJellyfinBadge, syncResultCardPoster, syncSeriesQueueFlags, updateSeriesJellyfinBadge, updateSeriesStatus, updateTasteFeedbackButtons, verifyHuhuEpisodeLanguages,
    }),
    seriesEpisodes: createSeriesEpisodes(document.getElementById("series-detail-modal"), {
      isQueueLoaded: () => state.queue.loaded, status: document.getElementById("series-status"), seriesState, getQueuedSlugs: () => state.queuedSlugs,
      getEnabledLanguages: () => sharedPresentation.providers.get()?.contentLanguages,
      verifyHuhuEpisodeLanguages, trackDiscoveryPreference, refreshQueueUiAfterChange,
    }),
    movieDownloads: createMovieDownloads(document.getElementById("fp-detail-modal"), {
      movieState, getQueuedSlugs: () => state.queuedSlugs, homeMovieBySlug, updateFpResultCard, showFpDetail,
      setDownloadState, refreshQueueUiAfterChange, refreshFpQueuePresentation, trackDiscoveryPreference,
      metadataPreviewMovie, basicMovieMetadata, fpDetailJellyfinValue,
      needsLanguageChoice: movie => sharedPresentation.mediaLanguage.needsChoice(movie),
      chooseLanguage: (movie, button) => sharedPresentation.mediaLanguage.choose(movie, button),
    }),
    searchSupport: createSearchSupport(document, {
      personalStorageKey, getGenres: () => sharedPresentation.genres.get(),
      recordTasteEvent: event => sharedPresentation.tasteProfile.event(event),
    }),
    movieCollections: createMovieCollections(document.getElementById("movie-collection-modal"), {
      getMovieCache: () => movieState.moviesCache, getMetadataCache: () => movieState.metadataCache,
      getQueuedSlugs: () => state.queuedSlugs, coverCandidates: url => artworkUrls.coverCandidates(url), coverUrl: url => artworkUrls.coverUrl(url),
      mediaCardInitials, openMediaModal, selectFpRow, applyMovieJellyfinStatus, refreshQueueUiAfterChange,
    }),
    homeCards: createHomeCards({
      getMovieMetadata: () => movieState.metadataCache,
      getJellyfinStatus: key => sharedPresentation.catalogJellyfin.getStatus(key),
      renderMediaCard, coverCandidates: url => artworkUrls.coverCandidates(url),
      mediaCardInitials, setHomeCardArtworkCandidates, setHomeCardMeta, mediaJellyfinStatus, homeEntryKey,
      openDailyTop: entry => sharedPresentation.dailyTop.open(entry),
      registerDock: (card, entry) => sharedPresentation.cardDock.register(card, entry),
      markLanguage: (node, media) => sharedPresentation.mediaLanguage.mark(node, media),
      enhanceTaste: (card, entry) => sharedPresentation.tasteRanking.enhance(card, entry),
      enhanceHero: (card, entry) => sharedPresentation.heroSelection.enhance(card, entry),
      enhanceDailyTop: (card, entry, rank) => sharedPresentation.dailyTop.enhance(card, entry, rank),
      createCollectionCard: createMovieCollectionSearchCard, openMovieCollection, homeMovieBySlug, selectFpRow,
      homeAnimeById, openAnimeDetail, homeSeriesBySlug, loadSeries,
    }),
    homeLanes: createHomeLanes(document.getElementById("tab-home"), {
      allowedHomeEntries, uniqueHomeEntries, homeMovieEntry, homeSeriesEntry, interleaveHomeEntries,
      loadDiscoveryProfile, stableDailyOrder, homeEntryMedia, homeEntryKey, homeTopEntries,
      stableDiscoveryHash, localDateKey, homeHeroCandidates, homePersonalizedEntries, currentHomeLayout,
      mediaJellyfinStatus, getJellyfinStatus: key => sharedPresentation.catalogJellyfin.getStatus(key),
      getData: () => sharedPresentation.homeData.get(),
    }),
    homePresenter: createHomePresenter(document.getElementById("tab-home"), {
      getData: () => sharedPresentation.homeData.get(), rememberAllHomeRailScroll, localDateKey,
      loadDiscoveryProfile, favoriteDiscoveryGenre, applyHomeLayout, currentHomeLayout, renderHomeHero,
      homeDiscoveryLanes, homeRailDefinition, renderHomeRail, scheduleHomeHeroRotation, homeAllEntries,
      beforeShuffle: () => sharedPresentation.tasteRanking.beforeShuffle(),
      animateShuffle: () => sharedPresentation.tasteRanking.animateShuffle(), resetHero: () => sharedPresentation.hero.reset(),
    }),
    homeCatalog: createHomeCatalog({
      getData: () => sharedPresentation.homeData.get(),
      getHomeSearchResults: () => sharedPresentation.homeSearch.get().results,
      getSearchResults: () => sharedPresentation.search.get().results,
      getAnimeResults: () => sharedPresentation.anime.get().results,
      getMovieMetadata: () => movieState.metadataCache, getShuffle: () => sharedPresentation.homePresenter.get().discoveryShuffle,
    }),
    tasteProfile: createTasteProfile(document, {
      getUser: () => sharedPresentation.auth.get().user, currentTasteTarget, renderTasteProfileSummary,
      shouldRenderHome: () => state.tab === "home" && !sharedPresentation.homeData.get().refreshing && !sharedPresentation.homePresenter.get().rendered,
      renderHome, homeMovieEntry, homeSeriesEntry, homeEntryMedia, homeEntryKey,
      onReset(user) { sharedPresentation.auth.acceptUser(user); sharedPresentation.tasteOnboarding.show(user); },
    }),
    aniworld: createAniworld(document.getElementById("tab-aniworld"), document.getElementById("aniworld-detail-modal"), {
      getQueuedSlugs: () => state.queuedSlugs, coverUrl: value => artworkUrls.coverUrl(value),
      mediaCardInitials, openMediaModal, recheckAniworldInfinite, refreshQueueUiAfterChange,
    }),
    anime: createAnime(document.getElementById("tab-anime"), document.getElementById("anime-detail-modal"), {
      getQueuedSlugs: () => state.queuedSlugs, coverUrl: value => artworkUrls.coverUrl(value),
      mediaCardInitials, mediaJellyfinStatus, jellyfinStatusText,
      refreshCatalogJellyfinStatus: (...args) => refreshCatalogJellyfinStatus(...args), homeAnimeEntry,
      openMediaModal, trackDiscoveryPreference, refreshQueueUiAfterChange,
    }),
    seriesChecks: createSeriesChecks(document.getElementById("series-status"), {
      seriesState, isVisible: () => !document.getElementById("series-detail-modal").hidden,
      firstEpisodeSlug, pruneSeriesEpisodeSelection, refreshSeriesTileStates,
      updateSeriesStatus, syncSeriesQueueFlags, seriesStructureFingerprint, mergeSeriesDetailPayload,
      updateSeriesOverview, updateWatchBtn, renderSeriesTiles,
    }),
    seriesDetailsLoader: createSeriesDetailsLoader(document.getElementById("series-detail-modal"), document.getElementById("series-status"), {
      seriesState, trackDiscoveryPreference, updateSeriesResultSelection, showSeriesLoading,
      openMediaModal, findSeriesResultCard, showSeriesDetail, updateSeriesStatus,
      refreshSeriesJellyfinStatus, switchTab, firstEpisodeSlug, seriesEpisodes, isEpisodeSelectable,
      renderSeriesTiles, syncWatchlistSnapshot,
    }),
    movieDetailsLoader: createMovieDetailsLoader({
      movieState, updateFpResultSelection, homeMovieBySlug, trackDiscoveryPreference, showFpDetail,
      metadataPreviewMovie, basicMovieMetadata, setFpDetailAvailability, openMediaModal,
      findFpResultCard, updateFpResultCard, refreshMovieFeatureCandidates, refreshFpJellyfinStatus,
    }),
    movieFilters: createMovieFilters(document.getElementById("tab-filme"), {
      movieState, getQueuedSlugs: () => state.queuedSlugs, fpResultMedia, fpResultYear, mediaJellyfinStatus, mediaContentLanguages,
      fpStatusMessage, fpGenreChange,
    }),
    seriesBrowse: createSeriesBrowse(document.getElementById("tab-serien"), {
      seriesState, getActiveTab: () => state.tab, syncSearchClearButtons, closeSearchSuggestions, rememberSearch,
      applySeriesResults: (...args) => applySeriesResults(...args), renderSeriesTiles,
      updateSeriesInfiniteState, showSeriesDetail, firstEpisodeSlug, updateSeriesStatus,
      refreshSeriesJellyfinStatus, recheckSeriesInfinite, preloadSeriesPosterImages,
      syncSeriesCatalogFromHome, renderSeriesResults, refreshSeriesCatalogInBackground,
    }),
    movieBrowse: createMovieBrowse(document.getElementById("tab-filme"), {
      movieState, getActiveTab: () => state.tab, syncSearchClearButtons, closeSearchSuggestions, rememberSearch,
      applyFpResults: (...args) => applyFpResults(...args), setActiveGenreFilter,
      renderFpResults, updateFpInfiniteState, refreshMovieFeatureCandidates,
      syncFpCatalogFromHome, refreshFpCatalogInBackground,
      getGenres: () => sharedPresentation.genres.get(), applyFpSmartFilters, resetFpSmartFilters,
      setFilter: (key, value) => sharedPresentation.movieFilters.set(key, value),
      cancelMetadata: () => sharedPresentation.catalogMetadata.unmount(),
    }),
    catalogIdentity: createCatalogIdentity({ getMetadata: slug => movieState.metadataCache[slug] }),
    catalogSeed: createCatalogSeed({
      movieState, seriesState, getActiveTab: () => state.tab, getHomeData: () => sharedPresentation.homeData.get(),
      mergeFpMetadata, fpMetadataPreloadItems, preloadTmdbMetadata,
      renderFpResults: (...args) => renderFpResults(...args), refreshMovieFeatureCandidates,
      updateFpInfiniteState, recheckFpInfinite,
      renderSeriesResults: (...args) => renderSeriesResults(...args), renderSeriesCatalogHero,
      updateSeriesInfiniteState, recheckSeriesInfinite,
    }),
    catalogMetadata: createCatalogMetadata({
      movieState, updateFpResultCard: slug => updateFpResultCard(slug),
      refreshFpJellyfinStatus: items => refreshFpJellyfinStatus(items),
      refreshMovieFeatureCandidates: () => refreshMovieFeatureCandidates(),
      showFpDetail: (...args) => showFpDetail(...args), metadataPreviewMovie,
      reconcileMovieCatalogDuplicates: () => reconcileMovieCatalogDuplicates(),
    }),
    posterPreloader: createPosterPreloader({ candidates: value => artworkUrls.coverThumbnailCandidates(value) }),
    catalogRefresh: createCatalogRefresh({
      movieState, seriesState, applyFpResults: (...args) => applyFpResults(...args),
      applySeriesResults: (...args) => applySeriesResults(...args),
      mergeCatalogItems: (...args) => mergeCatalogItems(...args),
      preloadSeriesPosterImages: (...args) => preloadSeriesPosterImages(...args),
    }),
    mediaLanguage: createMediaLanguage(document, { getProviders: () => sharedPresentation.providers.get() }),
    setMediaCardMeta, cardArtwork: createCardArtwork(document.body),
    trailers: createTrailers(document),
    search: createSearch(document.getElementById("global-search-page"), document.getElementById("global-search-shell"), {
      createHomeCard: (...args) => createHomeCard(...args), mediaJellyfinStatus,
      rememberSearch: (...args) => rememberSearch(...args),
      uniqueHomeContentEntries: entries => uniqueHomeContentEntries(entries), uniqueHomeEntries,
      homeCollectionEntry, homeMovieEntry, homeSeriesEntry, homeAnimeEntry,
      hydrateHomeMovieArtwork: (...args) => sharedPresentation.artwork.movies(...args),
      hydrateHomeSeriesArtwork: (...args) => sharedPresentation.artwork.series(...args),
      refreshCatalogJellyfinStatus: (...args) => refreshCatalogJellyfinStatus(...args),
      mediaDetailModalOpen: () => [...document.querySelectorAll(".media-modal")].some(modal =>
        !modal.hidden && !modal.classList.contains("hidden") && modal.getAttribute("aria-hidden") !== "true"),
    }),
    providers: createProviderSettings(document.getElementById("settings-sources"), document.getElementById("setup-wizard"), {
      onChange() { syncAnimeNavigationVisibility(); syncAniworldNavigationVisibility(); },
      onApply() { sharedPresentation.anime.invalidate(); },
      onSetupStatus: (message, error) => sharedPresentation.setup.status(message, error),
    }),
    tasteRanking: createTasteRanking(document.getElementById("tab-home"), document.getElementById("taste-profile-summary"), {
      homeEntryMedia: entry => homeEntryMedia(entry), homeEntryKey, tasteMetadata,
      loadDiscoveryProfile: () => loadDiscoveryProfile(), homeAllEntries: () => homeAllEntries(),
      discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry),
      discoveryV2ExposurePenalty: (...args) => discoveryPolicy.discoveryV2ExposurePenalty(...args),
      discoveryV2SelectDiverse: (...args) => discoveryPolicy.discoveryV2SelectDiverse(...args),
      getShuffle: () => sharedPresentation.homePresenter.get().discoveryShuffle,
      applyServerTasteProfile: profile => applyServerTasteProfile(profile), renderHome: () => renderHome(),
    }),
    heroSelection: createHeroSelection({
      discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry), homeEntryKey, homeEntryMedia: entry => homeEntryMedia(entry), tasteMetadata,
      discoveryV2ExposurePenalty: (...args) => discoveryPolicy.discoveryV2ExposurePenalty(...args), getHomeData: () => sharedPresentation.homeData.get(),
      homeMovieEntry, homeSeriesEntry, mediaJellyfinStatus, loadDiscoveryProfile: () => loadDiscoveryProfile(), homeAllEntries: () => homeAllEntries(),
    }),
    dailyTop: createDailyTop(document.getElementById("tab-home"), {
      fallbackEntries: discoveryPolicy.discoveryV2TopEntries, localDateKey, homeEntryKey,
      discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry), loadDiscoveryProfile: () => loadDiscoveryProfile(),
      selectFpRow: (...args) => selectFpRow(...args), closeGlobalSearch: () => closeGlobalSearch(),
      loadSeries: item => loadSeries(item), renderHome: () => renderHome(),
    }),
    jellyfinResume: createJellyfinResume({
      refreshAllCatalogJellyfinStatuses: () => refreshAllCatalogJellyfinStatuses(),
      refreshFpJellyfinStatus: () => refreshFpJellyfinStatus(),
      refreshSeriesJellyfinStatus: force => refreshSeriesJellyfinStatus(force),
    }),
    catalogJellyfin: createCatalogJellyfin({
      uniqueHomeEntries, homeEntryKey, getMovieMetadata: () => movieState.metadataCache,
      getMovieInstances: slug => [
        ...movieState.results.filter(item => item.slug === slug), ...homeMovieInstances(slug),
        movieState.metadataCache[slug], movieState.moviesCache[slug],
      ],
    }),
    genres: createGenres(document.getElementById("tab-filme"), {
      getActive: () => movieState.activeGenre,
      select(value) { movieState.activeGenre = value; setActiveGenreFilter(value); },
      onChange: () => applyFpSmartFilters(),
    }),
    infinite: {
      movies: createInfiniteScroll(document.getElementById("tab-filme"), {
        sentinel: document.getElementById("fp-infinite"), retryButton: document.getElementById("fp-infinite-retry"),
        loadNext: () => loadNextFpPage(), retry() {
          if (movieState.loadingMore || !movieState.category) return;
          if (movieState.lastPageFull) loadNextFpPage();
          else if (movieState.category === "genre") fpGenreChange(movieState.activeGenre);
          else fpShowList(movieState.category);
        },
      }),
      series: createInfiniteScroll(document.getElementById("tab-serien"), {
        sentinel: document.getElementById("series-infinite"), retryButton: document.getElementById("series-infinite-retry"),
        loadNext: () => loadNextSeriesPage(), retry() {
          const mode = seriesState.browseMode;
          if (seriesState.loadingBrowse || !mode || mode === "search") return;
          if (seriesState.lastPageFull) loadNextSeriesPage(); else seriesBrowse(mode, 1);
        },
      }),
      aniworld: createInfiniteScroll(document.getElementById("tab-aniworld"), {
        sentinel: document.getElementById("aniworld-infinite"), loadNext: () => loadNextAniworldPage(),
      }),
    },
    deploymentHints: (context, mode) => deploymentHints(document.getElementById(context === "setup" ? "setup-wizard" : "tab-einstellungen"), context, mode),
    deploymentMode: name => deploymentMode(document.getElementById(name === "setup-deployment-mode" ? "setup-wizard" : "tab-einstellungen"), name),
    settings: createSettings(document.getElementById("tab-einstellungen"), {
      getFeatures: () => sharedPresentation, language: () => i18n.language, locale: () => i18n.locale(),
      changeLanguage: language => i18n.changeLanguage(language, { userInitiated: true, persist: true }),
      async onSaved({ signal }) {
    movieState.results = [];
    movieState.moviesCache = {};
    movieState.metadataCache = {};
    movieState.sources = [];
    seriesState.results = [];
    seriesState.sources = [];
    seriesState.browseMode = null;
    seriesState.page = 1;
    seriesState.cache = {};
    await sharedPresentation.genres.refresh().catch((error) => {
      console.error("Genres konnten nach dem Quellenwechsel nicht geladen werden:", error);
    });
    if (signal.aborted) return;
    fpShowList("new").catch((error) => {
      document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
    });
        if (sharedPresentation.subscriptions.get().loaded) void refreshWatchlist();
      },
    }),
    jellyfin: createJellyfinSettings(document.getElementById("jellyfin-url").closest(".settings-group")),
    setupJellyfin: createJellyfinUserPicker(document.getElementById("setup-wizard"), {
      urlId: "setup-jellyfin-url", keyId: "setup-jellyfin-key", selectId: "setup-jellyfin-user",
      buttonId: "setup-jellyfin-users-load", onError: message => sharedPresentation.setup.status(message, true),
    }),
    integrations: createIntegrationSettings(document.getElementById("settings-media")),
    directory: createDirectoryPicker(document.getElementById("dir-modal")),
    updater: createUpdater(document.getElementById("updater-card")),
    intelligence, recommendations,
    account: createAccountSettings(document.getElementById("settings-account"), {
      getUser: () => sharedPresentation.auth.get().user, logout,
      onSaved(result, username) {
        const previous = sharedPresentation.auth.get();
        sharedPresentation.auth.accept({ ...previous, user: result.user || previous.user, configured: true, authenticated: true, username: result.user?.username || username });
      },
    }),
    homeData: createHomeData({
      getMovieMetadata: () => movieState.metadataCache, isRendered: () => sharedPresentation.homePresenter.get().rendered,
      homeAllEntries: () => homeAllEntries(), homeArtworkEntriesInLayout: () => homeArtworkEntriesInLayout(),
      renderHome: options => renderHome(options),
      syncFpCatalogFromHome: options => syncFpCatalogFromHome(options),
      syncSeriesCatalogFromHome: options => syncSeriesCatalogFromHome(options),
      hydrateHomeMovieArtwork: (...args) => sharedPresentation.artwork.movies(...args),
      hydrateHomeSeriesArtwork: (...args) => sharedPresentation.artwork.series(...args),
      refreshCatalogJellyfinStatus: (...args) => refreshCatalogJellyfinStatus(...args),
      discoveryV2MergeItems: (...args) => discoveryPolicy.discoveryV2MergeItems(...args),
      homeMovieEntry: item => homeMovieEntry(item), homeSeriesEntry: item => homeSeriesEntry(item),
      onLoaded: () => { void recommendations.refresh(); },
    }),
    artwork: createCatalogArtwork({
      getMovieMetadata: () => movieState.metadataCache,
      renderHome: () => renderHome(), saveHomeCache: () => saveHomeCache(),
      onSeriesHydrated: () => reconcileSeriesCatalogDuplicates(),
    }),
    movieSubscriptions, movieSubscriptionRules,
    calendar: createCalendar(document.getElementById("tab-kalender"), {
      subscriptions, getUserId: () => String(sharedPresentation.auth.get().user?.id || ""), locale: () => i18n.locale(),
      loadSeries: entry => loadSeries(entry),
    }),
    movieSubscriptionFor: (slug, movie) => movieSubscriptionFor(movieSubscriptions.get().items, slug, movie),
    movieSubscriptionView: createMovieSubscriptionsView(document.querySelector(".movie-subscriptions"), {
      model: movieSubscriptions, subscriptionMonogram, open: movieSubscriptionRules.open,
    }),
    subscriptions,
    subscriptionRules: createSubscriptionRules(document.getElementById("watch-mode-modal"), {
      subscriptions, getSeries: () => seriesState.current,
      findEntry: series => watchlistEntryForSeries(series), getCleanupDefault: () => sharedPresentation.jellyfin.get().cleanupDefault,
      isJellyfinConfigured: () => sharedPresentation.jellyfin.get().userConfigured,
      refreshQueue: () => syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung"),
      WATCH_MODE_DEFAULT, WATCH_MODE_EXPLANATIONS, WATCH_CLEANUP_DEFAULT, WATCH_CLEANUP_LABELS,
    }),
    library: createLibrary(document.getElementById("tab-bibliothek"), {
      subscriptions, checkResultText: data => watchlistCheckResultText(data),
      refreshQueue: () => syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung"),
      coverUrl: url => artworkUrls.coverUrl(url), watchlistStatusText, subscriptionMonogram, downloadedEpisodeLabel,
      openWatchModeModal: entry => openWatchModeModal(entry), openWatchlistEntry: slug => openWatchlistEntry(slug),
      WATCH_MODE_LABELS, WATCH_MODE_DEFAULT, WATCH_CLEANUP_LABELS, WATCH_CLEANUP_DEFAULT,
    }),
    modal, household, userMenu,
    notifications: createNotifications(document.querySelector(".bell-wrap"), {
      getSnapshot: subscriptions.get,
      getSnapshotVersion: () => subscriptions.revision,
      check: subscriptions.check, onSnapshot: subscriptions.accept,
      openEntry: slug => openWatchlistEntry(slug), openLibrary: () => switchTab("bibliothek"),
      coverUrl: url => artworkUrls.coverUrl(url), subscriptionMonogram, libraryCheckedLabel,
    }),
    movieHero: createMovieHero(document.getElementById("movie-feature"), {
      getCatalog: () => movieState, getProviderLabels: () => sharedPresentation.providers.get().labels,
      coverUrl: url => artworkUrls.coverUrl(url), locale: () => i18n.locale(),
      openMovie: slug => selectFpRow(slug), onUpdateHome: () => renderHomeHero(),
    }),
    setUser: user => appStore.set({ user }),
    profile: createProfile(document.getElementById("tab-profil"), {
      switchTab: name => switchTab(name), userRoleLabel,
      applyUser(user) { sharedPresentation.auth.acceptUser(user); },
      showHousehold: () => household.open(), closeHousehold: () => household.close(),
      reopenTasteOnboarding(user) { sharedPresentation.auth.acceptUser(user); sharedPresentation.tasteOnboarding.show(user); },
      openSecurity() { switchTab("einstellungen"); document.getElementById("settings-account")?.scrollIntoView({ behavior: "smooth", block: "start" }); },
    }),
    automation: createAutomation(document.getElementById("tab-einstellungen")),
    storage: createStorage(document.getElementById("tab-einstellungen")),
    modules: createModuleSettings(document.getElementById("tab-einstellungen")),
    renderMediaCard, jellyfinStatusText: statusText, setCatalogJellyfinBadge: statusBadge,
    carousel: createCarousel(document.getElementById("tab-home")),
  });

  sharedPresentation.homeSearch = createHomeSearch(document.getElementById("tab-home"), {
    rememberSearch: (...args) => rememberSearch(...args), homeMovieEntry, homeSeriesEntry,
    interleaveHomeEntries, uniqueHomeEntries, createHomeCard: (...args) => createHomeCard(...args),
    artwork: sharedPresentation.artwork, refreshJellyfin: (...args) => refreshCatalogJellyfinStatus(...args),
  });
  sharedPresentation.startup = createStartup({
    homeData: sharedPresentation.homeData, genres: sharedPresentation.genres,
    onInitial() {
      syncFpCatalogFromHome(); syncSeriesCatalogFromHome(); syncTasteProfile();
      void syncQueueSnapshot("Initiale Queue-Synchronisierung");
      void refreshWatchlist(); void syncMovieSubscriptions();
    },
    onLoaded() { syncFpCatalogFromHome({ fresh: true }); syncSeriesCatalogFromHome({ fresh: true }); },
    onError(error) { document.getElementById("fp-status").textContent = `Fehler: ${error.message}`; renderHome(); },
  });
  sharedPresentation.auth = createAuthentication(document.getElementById("login-screen"), {
    isSetupRequired: () => Boolean(sharedPresentation.setup?.required),
    onChange: status => appStore.set({ user: status.user || null }),
    onVisibility: visible => document.body.classList.toggle("login-open", visible),
    onExpired: () => document.dispatchEvent(new Event("royal:session-expired")),
    finishLoading: () => sharedPresentation.startupCurtain.finish(),
  });
  window.addEventListener("pagehide", () => sharedPresentation.auth.unmount());
  window.addEventListener("pageshow", event => { if (event.persisted) sharedPresentation.auth.mount(); });
  sharedPresentation.tasteOnboarding = createTasteOnboarding(document.getElementById("taste-onboarding"), {
    getUser: () => sharedPresentation.auth.get().user, acceptUser: user => sharedPresentation.auth.acceptUser(user),
    homeData: sharedPresentation.homeData, homeAllEntries: () => homeAllEntries(),
    homeEntryMedia: entry => homeEntryMedia(entry), homeEntryKey: entry => homeEntryKey(entry),
    tasteMetadata: (...args) => tasteMetadata(...args),
    onVisibility: visible => document.body.classList.toggle("taste-onboarding-open", visible),
    onSaved(profile) {
      applyServerTasteProfile(profile); sharedPresentation.recommendations.invalidate();
      renderHome({ force: true }); void sharedPresentation.recommendations.refresh(true);
    },
  });
  sharedPresentation.setup = createSetup(document.getElementById("setup-wizard"), {
    providers: sharedPresentation.providers, jellyfin: sharedPresentation.setupJellyfin,
    directory: sharedPresentation.directory, i18n,
    onVisibility: visible => document.body.classList.toggle("setup-open", visible),
    async onComplete() { await sharedPresentation.settings.initialize(); sharedPresentation.startup.start(); },
    onError: error => console.error("Ersteinrichtung konnte nicht geprüft werden:", error),
  });

  sharedPresentation.hero = createHero(document.getElementById("tab-home"), {
    homeHeroCandidates: () => homeHeroCandidates(), coverUrl: url => artworkUrls.coverUrl(url),
    onRendered: entry => discoveryPolicy.recordDiscoveryExposureV2("hero", [entry]),
    onRender: () => renderHomeHero(), openEntry: (kind, key) => openHomeEntry(kind, key),
    openLibrary: () => switchTab("bibliothek"),
  });
  sharedPresentation.mood = createMood(document.getElementById("mood-modal"), {
    model: { homeEntryMedia, homeEntryKey, mediaJellyfinStatus, loadDiscoveryProfile, stableDiscoveryHash, localDateKey,
      allowedHomeEntries: entries => allowedHomeEntries(entries), homeAllEntries, uniqueHomeContentEntries, uniqueHomeEntries },
    homeEntryMedia, homeEntryKey, homeAllEntries, coverCandidates: url => artworkUrls.coverCandidates(url),
    hydrateHomeMovieArtwork, hydrateHomeSeriesArtwork, openHomeEntry, stopHomeHeroRotation, scheduleHomeHeroRotation,
    isHome: () => state.tab === "home",
  });
  sharedPresentation.cardDock = createCardDock(document.getElementById("tab-home"), {
    trailers: sharedPresentation.trailers, homeEntryMedia, mediaJellyfinStatus, mediaCardInitials,
    openHomeEntry, toggleFpPick, getMovie: slug => movieState.moviesCache[slug],
    acceptMetadata(slug, movie) { movieState.metadataCache[slug] = { ...movieState.metadataCache[slug], ...movie }; },
    isQueued: slug => state.queuedSlugs.has(slug), normalizeHomeRailLoop,
  });
  sharedPresentation.railRenderer = createRailRenderer(document.getElementById("tab-home"), {
    artwork: sharedPresentation.cardArtwork, carousel: sharedPresentation.carousel,
    homeEntryMedia, homeEntryKey, mediaJellyfinStatus, getJellyfinStatus: key => sharedPresentation.catalogJellyfin.getStatus(key),
  });
  sharedPresentation.homeLayout = createHomeLayout(document.getElementById("tab-home"), document.getElementById("home-layout-modal"), {
    carousel: sharedPresentation.carousel, render: () => renderHome(), stopRotation: () => stopHomeHeroRotation(),
  });
  sharedPresentation.rows = createHomeRows(document.getElementById("tab-home"), {
    isLoading: () => sharedPresentation.homeData.get().loading,
    onRendered(trackId, entries, options) {
      const lane = { "home-movies-track": "personal", "home-explore-track": "explore", "home-series-track": "series",
        "home-top-track": "top", "home-genre-track": "genre", "home-gems-track": "gems" }[trackId];
      if (lane) discoveryPolicy.recordDiscoveryExposureV2(lane, entries.slice(0, options.layout === "spotlight" ? 7 : options.ranked ? 10 : 16));
    },
    reconcileHomeRail, homeRailCardSignature,
    createHomeCard: (...args) => createHomeCard(...args), syncHomeCardContent,
  });

  // Shell-owned navigation entries exist before the shell menu listeners bind.
  document.querySelectorAll('.tab-btn[data-tab="kalender"]').forEach(button => {
    const release = document.createElement("button");
    release.className = "tab-btn";
    release.dataset.tab = "releases";
    release.innerHTML = '<span class="tab-icon" aria-hidden="true">◷</span><span>Releases</span>';
    button.after(release);
  });

}

export function mountApplication() {
  const queueView = createQueueView(document.getElementById("queue-dock"), {
    state, invalidate: () => sharedPresentation.queueSync.invalidate(),
    showPersistenceWarning, renderSerienstreamHealth,
    syncSeriesQueueFlags, syncAnimeQueueFlags, syncAniworldQueueFlags,
    syncFpQueueIndicators, setDownloadState,
    refresh: () => syncQueueSnapshot(),
    setMobileCount: count => { document.getElementById("mobile-queue-count").textContent = String(count); },
  });
  sharedPresentation.queueView = queueView;
  queueView.mount();
  const application = createApplication({
    user: sharedPresentation.auth.get().user || null,
    queueView,
    search: sharedPresentation.search,
    settingsNavigation: createSettingsNavigation(document.getElementById("tab-einstellungen")),
    localization: sharedPresentation.localization,
    shell: sharedPresentation.shell,
    movieDiscovery: sharedPresentation.movieDiscovery, seriesDiscovery: sharedPresentation.seriesDiscovery,
    moviePresentation: sharedPresentation.moviePresentation,
    movieStatus: sharedPresentation.movieStatus,
    resultCards: sharedPresentation.resultCards,
    seriesPresentation: sharedPresentation.seriesPresentation,
    subscriptionSummary: sharedPresentation.subscriptionSummary,
    seriesEpisodes: sharedPresentation.seriesEpisodes,
    movieDownloads: sharedPresentation.movieDownloads,
    movieCollections: sharedPresentation.movieCollections,
    tasteProfile: sharedPresentation.tasteProfile,
    aniworld: sharedPresentation.aniworld,
    anime: sharedPresentation.anime,
    seriesChecks: sharedPresentation.seriesChecks,
    seriesDetailsLoader: sharedPresentation.seriesDetailsLoader,
    movieDetailsLoader: sharedPresentation.movieDetailsLoader,
    seriesBrowse: sharedPresentation.seriesBrowse,
    movieBrowse: sharedPresentation.movieBrowse,
    catalogMetadata: sharedPresentation.catalogMetadata,
    posterPreloader: sharedPresentation.posterPreloader,
    catalogRefresh: sharedPresentation.catalogRefresh,
    mediaLanguage: sharedPresentation.mediaLanguage,
    mood: sharedPresentation.mood,
    cardArtwork: sharedPresentation.cardArtwork,
    trailers: sharedPresentation.trailers,
    jellyfinResume: sharedPresentation.jellyfinResume,
    catalogJellyfin: sharedPresentation.catalogJellyfin,
    tasteOnboarding: sharedPresentation.tasteOnboarding,
    startup: sharedPresentation.startup,
    genres: sharedPresentation.genres,
    infinite: sharedPresentation.infinite,
    setup: sharedPresentation.setup,
    settings: sharedPresentation.settings,
    jellyfin: sharedPresentation.jellyfin,
    setupJellyfin: sharedPresentation.setupJellyfin,
    providers: sharedPresentation.providers,
    integrations: sharedPresentation.integrations,
    directory: sharedPresentation.directory,
    updater: sharedPresentation.updater,
    account: sharedPresentation.account,
    intelligence: sharedPresentation.intelligence,
    homeData: sharedPresentation.homeData,
    artwork: sharedPresentation.artwork,
    calendar: sharedPresentation.calendar,
    modules: sharedPresentation.modules,
    storage: sharedPresentation.storage,
    automation: sharedPresentation.automation,
    notifications: sharedPresentation.notifications,
    subscriptions: sharedPresentation.subscriptions,
    library: sharedPresentation.library,
    subscriptionRules: sharedPresentation.subscriptionRules,
    movieSubscriptions: sharedPresentation.movieSubscriptions,
    movieSubscriptionView: sharedPresentation.movieSubscriptionView,
    movieSubscriptionRules: sharedPresentation.movieSubscriptionRules,
    onMovieSubscriptions: (snapshot, previous) => { if (snapshot.items !== previous?.items) presentMovieSubscriptions(); },
    onSubscriptions: (snapshot, previous) => presentWatchlist(snapshot, previous),
    profile: sharedPresentation.profile,
    movieHero: sharedPresentation.movieHero,
    live: {
      onMessage: handleLiveMessage, onOpen: resyncAfterWsOpen, onUnauthorized: sharedPresentation.auth.unauthorized,
      onDownload: createDownloadEvents({
        state, setDownloadState, updateQueueJobProgress, applyFpDownloadJobResult, syncQueueSnapshot,
        markSeriesSlugDownloaded, markAnimeSlugDownloaded, markAniworldSlugDownloaded,
        renderQueue, renderSerienstreamHealth,
        disableCancel: () => { document.getElementById("cancel-btn").disabled = true; },
      }),
    },
    releases: {
      openSettings() {
        switchTab("einstellungen");
        document.querySelector('[data-settings-target="settings-media"]')?.click();
        document.getElementById("release-settings")?.scrollIntoView({ block: "center" });
      },
      openMedia(type, match) {
        if (type === "series") { switchTab("serien"); loadSeries(match); }
        else selectFpRow(match.slug, match);
      },
    },
    home: createHomeLifecycle({
      root: document.getElementById("tab-home"), shuffle: shuffleHomeDiscovery, updateRailNavigation: updateHomeRailNavigation,
      railRenderer: sharedPresentation.railRenderer,
      layout: sharedPresentation.homeLayout,
      tasteRanking: sharedPresentation.tasteRanking,
      dailyTop: sharedPresentation.dailyTop,
      search: sharedPresentation.homeSearch,
      recommendations: sharedPresentation.recommendations,
      carousel: sharedPresentation.carousel,
      hero: sharedPresentation.hero,
      refresh() { sharedPresentation.hero.reset(); renderHome(); },
      dayChanged: () => sharedPresentation.homePresenter.get().discoveryDay !== localDateKey(),
      stopRotation: stopHomeHeroRotation,
      dock: sharedPresentation.cardDock,
    }),
  });
  application.downloads.mount();
  return application;
}
