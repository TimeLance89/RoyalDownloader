import { createQueueView } from "../features/downloads/view.js";
import { createApplication } from "../app.js";
import { createSettingsNavigation } from "../features/settings/navigation.js";
import { createDownloadEvents } from "../features/downloads/events.js";
import { createHomeLifecycle } from "../features/home/index.js";

export function mountApplication({ state, downloadsDomain, coreDomain, discoveryDomain, profileDomain, searchDomain, integrationsDomain, subscriptionsDomain, homeDomain, settingsDomain }) {

  const queueView = createQueueView(document.getElementById("queue-dock"), {
    state, invalidate: () => downloadsDomain.queueSync.invalidate(),
    showPersistenceWarning: (...args) => coreDomain.actions.showPersistenceWarning(...args), renderSerienstreamHealth: (...args) => coreDomain.actions.renderSerienstreamHealth(...args),
    syncSeriesQueueFlags: (...args) => discoveryDomain.seriesActions.syncSeriesQueueFlags(...args), syncAnimeQueueFlags: (...args) => discoveryDomain.animeActions.syncAnimeQueueFlags(...args), syncAniworldQueueFlags: (...args) => discoveryDomain.aniworldActions.syncAniworldQueueFlags(...args),
    syncFpQueueIndicators: (...args) => discoveryDomain.movieActions.syncFpQueueIndicators(...args), setDownloadState: (...args) => coreDomain.actions.setDownloadState(...args),
    refresh: () => coreDomain.actions.syncQueueSnapshot(),
    setMobileCount: count => { document.getElementById("mobile-queue-count").textContent = String(count); },
  });
  downloadsDomain.queueView = queueView;
  queueView.mount();
  const application = createApplication({
    core: {
      user: profileDomain.auth.get().user || null,
      localization: coreDomain.localization,
      shell: coreDomain.shell,
      cardArtwork: coreDomain.cardArtwork,
      startup: coreDomain.startup
    },
    home: {
      mood: homeDomain.mood,
      homeData: homeDomain.homeData,
      home: createHomeLifecycle({
      root: document.getElementById("tab-home"), shuffle: ((...args) => homeDomain.actions.shuffleHomeDiscovery(...args)), updateRailNavigation: ((...args) => homeDomain.actions.updateHomeRailNavigation(...args)),
      railRenderer: homeDomain.railRenderer,
      layout: homeDomain.homeLayout,
      tasteRanking: homeDomain.tasteRanking,
      dailyTop: homeDomain.dailyTop,
      search: searchDomain.homeSearch,
      recommendations: homeDomain.recommendations,
      carousel: homeDomain.carousel,
      hero: homeDomain.hero,
      refresh() { homeDomain.hero.reset(); homeDomain.actions.renderHome(); },
      dayChanged: () => homeDomain.homePresenter.get().discoveryDay !== homeDomain.actions.localDateKey(),
      stopRotation: ((...args) => homeDomain.actions.stopHomeHeroRotation(...args)),
      dock: homeDomain.cardDock,
    })
    },
    discovery: {
      movieDiscovery: discoveryDomain.movieDiscovery,
      seriesDiscovery: discoveryDomain.seriesDiscovery,
      moviePresentation: discoveryDomain.moviePresentation,
      resultCards: discoveryDomain.resultCards,
      seriesPresentation: discoveryDomain.seriesPresentation,
      seriesEpisodes: discoveryDomain.seriesEpisodes,
      movieCollections: discoveryDomain.movieCollections,
      aniworld: discoveryDomain.aniworld,
      anime: discoveryDomain.anime,
      seriesChecks: discoveryDomain.seriesChecks,
      seriesDetailsLoader: discoveryDomain.seriesDetailsLoader,
      movieDetailsLoader: discoveryDomain.movieDetailsLoader,
      seriesBrowse: discoveryDomain.seriesBrowse,
      movieBrowse: discoveryDomain.movieBrowse,
      catalogMetadata: discoveryDomain.catalogMetadata,
      posterPreloader: discoveryDomain.posterPreloader,
      catalogRefresh: discoveryDomain.catalogRefresh,
      mediaLanguage: discoveryDomain.mediaLanguage,
      trailers: discoveryDomain.trailers,
      genres: discoveryDomain.genres,
      infinite: discoveryDomain.infinite,
      artwork: discoveryDomain.artwork,
      movieHero: discoveryDomain.movieHero
    },
    downloads: {
      queueView,
      movieDownloads: downloadsDomain.movieDownloads,
      live: {
      onMessage: ((...args) => coreDomain.actions.handleLiveMessage(...args)), onOpen: ((...args) => coreDomain.actions.resyncAfterWsOpen(...args)), onUnauthorized: profileDomain.auth.unauthorized,
      onDownload: createDownloadEvents({
        state, setDownloadState: (...args) => coreDomain.actions.setDownloadState(...args), updateQueueJobProgress: (...args) => coreDomain.actions.updateQueueJobProgress(...args), applyFpDownloadJobResult: (...args) => downloadsDomain.actions.applyFpDownloadJobResult(...args), syncQueueSnapshot: (...args) => coreDomain.actions.syncQueueSnapshot(...args),
        markSeriesSlugDownloaded: (...args) => discoveryDomain.seriesActions.markSeriesSlugDownloaded(...args), markAnimeSlugDownloaded: (...args) => discoveryDomain.animeActions.markAnimeSlugDownloaded(...args), markAniworldSlugDownloaded: (...args) => discoveryDomain.aniworldActions.markAniworldSlugDownloaded(...args),
        renderQueue: (...args) => coreDomain.actions.renderQueue(...args), renderSerienstreamHealth: (...args) => coreDomain.actions.renderSerienstreamHealth(...args),
        disableCancel: () => { document.getElementById("cancel-btn").disabled = true; },
      }),
    }
    },
    profile: {
      tasteProfile: profileDomain.tasteProfile,
      tasteOnboarding: profileDomain.tasteOnboarding,
      profile: profileDomain.profile
    },
    subscriptions: {
      subscriptionSummary: subscriptionsDomain.subscriptionSummary,
      notifications: subscriptionsDomain.notifications,
      subscriptions: subscriptionsDomain.subscriptions,
      library: subscriptionsDomain.library,
      subscriptionRules: subscriptionsDomain.subscriptionRules,
      movieSubscriptions: subscriptionsDomain.movieSubscriptions,
      movieSubscriptionView: subscriptionsDomain.movieSubscriptionView,
      movieSubscriptionRules: subscriptionsDomain.movieSubscriptionRules,
      onMovieSubscriptions: (snapshot, previous) => { if (snapshot.items !== previous?.items) discoveryDomain.movieActions.presentMovieSubscriptions(); },
      onSubscriptions: (snapshot, previous) => subscriptionsDomain.actions.presentWatchlist(snapshot, previous)
    },
    settings: {
      settingsNavigation: createSettingsNavigation(document.getElementById("tab-einstellungen")),
      setup: settingsDomain.setup,
      settings: settingsDomain.settings,
      providers: settingsDomain.providers,
      directory: settingsDomain.directory,
      updater: settingsDomain.updater,
      account: settingsDomain.account,
      intelligence: settingsDomain.intelligence,
      calendar: settingsDomain.calendar,
      modules: settingsDomain.modules,
      storage: settingsDomain.storage,
      automation: settingsDomain.automation,
      releases: {
      openSettings() {
        coreDomain.actions.switchTab("einstellungen");
        document.querySelector('[data-settings-target="settings-media"]')?.click();
        document.getElementById("release-settings")?.scrollIntoView({ block: "center" });
      },
      openMedia(type, match) {
        if (type === "series") { coreDomain.actions.switchTab("serien"); discoveryDomain.seriesActions.loadSeries(match); }
        else discoveryDomain.movieActions.selectFpRow(match.slug, match);
      },
    }
    },
    integrations: {
      movieStatus: integrationsDomain.movieStatus,
      jellyfinResume: integrationsDomain.jellyfinResume,
      catalogJellyfin: integrationsDomain.catalogJellyfin,
      jellyfin: integrationsDomain.jellyfin,
      setupJellyfin: integrationsDomain.setupJellyfin,
      integrations: integrationsDomain.integrations
    },
    search: {
      search: searchDomain.search
    }
  });
  application.downloads.mount();
  return application;

}
