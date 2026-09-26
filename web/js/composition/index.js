import { composeSubscriptions } from "./subscriptions.js";
import { composeHome } from "./home.js";
import { composeCore } from "./core.js";
import { composeDiscovery } from "./discovery.js";
import { composeDownloads } from "./downloads.js";
import { composeIntegrations } from "./integrations.js";
import { composeSearch } from "./search.js";
import { composeProfile } from "./profile.js";
import { composeSettings } from "./settings.js";

import { createStartupCurtain } from "../shared/components/startup-curtain.js";
import { handleLiveMessage, renderQueue, renderSerienstreamHealth, resyncAfterWsOpen, setDownloadState, sharedPresentation, showPersistenceWarning, state, switchTab, syncMovieSubscriptions, syncQueueSnapshot, updateQueueJobProgress } from "../shell/presentation.js";
import { closeFpTrailerModal, mediaCardInitials, mediaContentLanguages, normalizeUiContentLanguage, presentMovieSubscriptions, selectFpRow, stopFpDetailHeroTrailer, syncFpCatalogFromHome, syncFpQueueIndicators, syncSeriesCatalogFromHome, toggleFpPick, trailerModalFocusableElements } from "../shell/actions/movies.js";
import { loadSeries, markSeriesSlugDownloaded, stopSeriesDetailHeroTrailer, syncSeriesQueueFlags } from "../shell/actions/series.js";
import { allowedHomeEntries, applyServerTasteProfile, createHomeCard, homeAllEntries, homeEntryKey, homeEntryMedia, homeHeroCandidates, homeMovieEntry, homeRailCardSignature, homeSeriesEntry, hydrateHomeMovieArtwork, hydrateHomeSeriesArtwork, interleaveHomeEntries, loadDiscoveryProfile, localDateKey, mediaJellyfinStatus, normalizeHomeRailLoop, openHomeEntry, reconcileHomeRail, refreshCatalogJellyfinStatus, rememberSearch, renderHome, renderHomeHero, scheduleHomeHeroRotation, shuffleHomeDiscovery, stableDiscoveryHash, stopHomeHeroRotation, syncHomeCardContent, syncTasteProfile, tasteMetadata, uniqueHomeContentEntries, uniqueHomeEntries, updateHomeRailNavigation } from "../shell/actions/home.js";
import { createProfileActions } from "../features/profile/actions.js";
import { markAnimeSlugDownloaded, syncAnimeQueueFlags } from "../shell/actions/anime.js";
import { presentWatchlist, refreshWatchlist } from "../shell/actions/library.js";

import { markAniworldSlugDownloaded, syncAniworldQueueFlags } from "../shell/actions/aniworld.js";
import { applyFpDownloadJobResult } from "../shell/actions/movie_download_feedback.js";
import { createArtworkUrls } from "../shared/utils/artwork-url.js";

import { createLocalization } from "../core/localization.js";









import { createMovieState } from "../features/discovery/movie-state.js";
import { createSeriesState } from "../features/discovery/series-state.js";





















import { createDiscoveryPolicy } from "../features/home/discovery-policy.js";
import { createMood } from "../features/mood/index.js";
import { createCardDock } from "../features/home/card-dock.js";

import { createRailRenderer } from "../features/home/rail-renderer.js";
import { createHomeLayout } from "../features/home/layout.js";






import { createHomeSearch } from "../features/search/home.js";
import { createTasteOnboarding } from "../features/profile/taste-onboarding.js";
import { createStartup } from "../core/startup.js";

import { createAuthentication } from "../features/auth/index.js";

import { createSetup } from "../features/setup/index.js";






import { createSettingsNavigation } from "../features/settings/navigation.js";




import { logout } from "../core/session.js";
import { createRecommendations } from "../features/home/recommendations.js";
import { createIntelligenceSettings } from "../features/settings/intelligence.js";




import { createMovieSubscriptionRules } from "../features/subscriptions/movie-rules.js";




import { createSubscriptions } from "../features/subscriptions/state.js";





import { appStore } from "../core/store.js";
import { userInitials, userRoleLabel } from "../features/profile/identity.js";
import { createUserMenu } from "../features/profile/menu.js";
import { createHousehold } from "../features/profile/household.js";


import { createModalController } from "../shared/components/modal.js";
import { createServerBuildMonitor } from "../features/system/server-build.js";
import { createDownloadEvents } from "../features/downloads/events.js";
import { createHero } from "../features/home/hero.js";
import { createHomeRows } from "../features/home/rows.js";



import { createQueueView } from "../features/downloads/view.js";
import { createApplication } from "../app.js";
import { createHomeLifecycle } from "../features/home/index.js";

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
  const profileActions = createProfileActions({
    getUser: () => sharedPresentation.auth.get().user,
    invalidateRecommendations: () => sharedPresentation.recommendations.invalidate(),
    invalidateHome: () => sharedPresentation.homePresenter.invalidate(),
    setUser: user => appStore.set({ user }), household, userMenu,
  });
  const { personalStorageKey } = profileActions;
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
...composeSubscriptions({ movieSubscriptions, movieSubscriptionRules, subscriptions, seriesState, artworkUrls }),
...composeHome({ discoveryPolicy, movieState, artworkUrls, recommendations }),
...composeCore({ i18n, modal }),
...composeDiscovery({ movieState, seriesState, artworkUrls, i18n }),
...composeDownloads({ movieState }),
...composeIntegrations({ movieState }),
...composeSearch({ personalStorageKey }),
...composeProfile({ household, userMenu }),
...composeSettings({ i18n, movieState, seriesState, console, intelligence, subscriptions })
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

  return { initUserProfile: profileActions.initUserProfile };
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
