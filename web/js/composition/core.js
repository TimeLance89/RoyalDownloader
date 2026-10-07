import { createStartup } from "../core/startup.js";
import { createModalController } from "../shared/components/modal.js";
import { createServerBuildMonitor } from "../features/system/server-build.js";
import { createLocalization } from "../core/localization.js";
import { createArtworkUrls } from "../shared/utils/artwork-url.js";
import { createStartupCurtain } from "../shared/components/startup-curtain.js";
import { createInitialState } from "../shell/state.js";
import { createShellActions } from "../shell/actions.js";
import { cleanMediaCardInitials } from "../features/discovery/catalog-identity.js";
import { createShell } from "../core/shell.js";

import { setMediaCardMeta } from "../shared/components/media-card.js";
import { createCardArtwork } from "../shared/components/card-artwork.js";
import { renderMediaCard } from "../shared/components/media-card.js";
import { jellyfinStatusText as statusText } from "../shared/components/status-badge.js";
import { setCatalogJellyfinBadge as statusBadge } from "../shared/components/status-badge.js";

export function composeCore({ i18n, modal, state, getSettings, getHome, getDiscovery, getSearch, getDownloads, getSubscriptions }) {
  const services = {
  cleanMediaCardInitials,
  localization: i18n,
  shell: createShell(document, {
        switchTab: (...args) => services.actions.switchTab(...args), openMobileQueue: (...args) => services.actions.openMobileQueue(...args), closeMobileQueue: (...args) => services.actions.closeMobileQueue(...args), toggleDesktopQueue: (...args) => services.actions.toggleDesktopQueue(...args), closeMediaModal: (...args) => services.actions.closeMediaModal(...args),
        openWatchModeModal: (...args) => getDiscovery().animeActions.openWatchModeModal(...args), handleMediaModalKeydown: (...args) => services.actions.handleMediaModalKeydown(...args), setQueueDockExpanded: (...args) => services.actions.setQueueDockExpanded(...args), refreshQueueUiAfterChange: (...args) => services.actions.refreshQueueUiAfterChange(...args),
        renderSerienstreamHealth: (...args) => services.actions.renderSerienstreamHealth(...args), setDownloadState: (...args) => services.actions.setDownloadState(...args), getDownloadPercent: () => state.download.percent,
        closeNotifications: () => getSubscriptions().notifications.close(),
        openDirectory: (...args) => getSettings().directory.open(...args),
      }),
  setMediaCardMeta,
  cardArtwork: createCardArtwork(document.body),
  modal,
  renderMediaCard,
  jellyfinStatusText: statusText,
  setCatalogJellyfinBadge: statusBadge
  };
  services.actions = createShellActions({
    providerLanguage: (...args) => getSettings().actions.providerLanguage(...args),
    closeGlobalSearch: (...args) => getHome().actions.closeGlobalSearch(...args),
    refreshAllCatalogJellyfinStatuses: (...args) => getHome().actions.refreshAllCatalogJellyfinStatuses(...args),
    renderHome: (...args) => getHome().actions.renderHome(...args),
    stopHomeHeroRotation: (...args) => getHome().actions.stopHomeHeroRotation(...args),
    ensureFpResults: (...args) => getDiscovery().movieActions.ensureFpResults(...args),
    fpResultAvailability: (...args) => getDiscovery().movieActions.fpResultAvailability(...args),
    fpStatusMessage: (...args) => getDiscovery().movieActions.fpStatusMessage(...args),
    refreshFpJellyfinStatus: (...args) => getDiscovery().movieActions.refreshFpJellyfinStatus(...args),
    refreshSeriesJellyfinStatus: (...args) => getDiscovery().movieActions.refreshSeriesJellyfinStatus(...args),
    ensureSeriesResults: (...args) => getDiscovery().seriesActions.ensureSeriesResults(...args),
    animeBrowse: (...args) => getDiscovery().animeActions.animeBrowse(...args),
    aniworldBrowse: (...args) => getDiscovery().aniworldActions.aniworldBrowse(...args),
    getInfinite: () => getDiscovery().infinite,
    getProviders: () => getSettings().providers,
    getShell: () => services.shell,
    getSearch: () => getSearch().search,
    getAnime: () => getDiscovery().anime,
    getAniworld: () => getDiscovery().aniworld,
    getLocalization: () => services.localization,
    getQueueSync: () => getDownloads().queueSync,
    getSubscriptions: () => getSubscriptions().subscriptions,
    getMovieSubscriptions: () => getSubscriptions().movieSubscriptions,
    getQueueView: () => getDownloads().queueView,
    getModal: () => services.modal,
    getMovieState: () => getDiscovery().movieState,
    getMovieDownloads: () => getDownloads().movieDownloads,
    state,
  });
  return services;
}

export function prepareCore({ getDiscovery, getDownloads, getIntegrations, getHome }) {
  const state = createInitialState();
  const startupCurtain = createStartupCurtain(document);
  const artworkUrls = createArtworkUrls(document.defaultView.location.origin);
  const i18n = createLocalization(document);
  i18n.primeStoredInterface();
  const monitor = createServerBuildMonitor();
  monitor.mount();
  window.addEventListener("pagehide", () => monitor.unmount());
  window.addEventListener("pageshow", event => { if (event.persisted) monitor.mount(); });
  const modal = createModalController(document.body, {
      closeCollectionDetails: () => getDiscovery().movieCollections.close(),
      closeAniworldDetails: () => getDiscovery().aniworld.closeDetail(),
      closeAnimeDetails: () => getDiscovery().anime.closeDetail(),
      closeSeriesDetails() { getDiscovery().seriesDetailsLoader.unmount(); getDiscovery().seriesChecks.unmount(); getDiscovery().seriesPresentation.closeSavedMedia(); },
      closeMovieDetails: () => { getDiscovery().movieDetailsLoader.unmount(); getDownloads().movieDownloads.closeDetail(); getIntegrations().movieStatus.cancel(); getDiscovery().moviePresentation.closeSavedMedia(); },
      closeLanguageChoice: () => getDiscovery().mediaLanguage.close(),
      closeFpTrailerModal: (...args) => getDiscovery().movieActions.closeFpTrailerModal(...args),
      stopFpDetailHeroTrailer: () => getDiscovery().movieActions.stopFpDetailHeroTrailer(),
      stopSeriesDetailHeroTrailer: () => getDiscovery().seriesActions.stopSeriesDetailHeroTrailer(),
      trailerModalFocusableElements: () => getDiscovery().movieActions.trailerModalFocusableElements(),
      resumeMoodMatchAfterDetail: () => getHome().mood.resumeAfterDetail(),
    });
  window.addEventListener("pagehide", () => modal.unmount());
  document.addEventListener("royal:session-expired", () => modal.unmount());
  return { state, startupCurtain, artworkUrls, i18n, monitor, modal };
}

export function initializeCore({ getCore, startupCurtain, getHome, getDiscovery, getSubscriptions, state }) {
  getCore().startupCurtain = startupCurtain;
  getCore().startup = createStartup({
      homeData: getHome().homeData, genres: getDiscovery().genres,
      onInitial() {
        getDiscovery().movieActions.syncFpCatalogFromHome(); getDiscovery().movieActions.syncSeriesCatalogFromHome(); getHome().actions.syncTasteProfile();
        void getCore().actions.syncQueueSnapshot("Initiale Queue-Synchronisierung");
        void getSubscriptions().actions.refreshWatchlist(); void getCore().actions.syncMovieSubscriptions();
      },
      onLoaded() { getDiscovery().movieActions.syncFpCatalogFromHome({ fresh: true }); getDiscovery().movieActions.syncSeriesCatalogFromHome({ fresh: true }); },
      onError(error) { document.getElementById("fp-status").textContent = `Fehler: ${error.message}`; getHome().actions.renderHome(); },
    });
  document.querySelectorAll('.tab-btn[data-tab="kalender"]').forEach(button => {
      const release = document.createElement("button");
      release.className = "tab-btn";
      release.dataset.tab = "releases";
      release.innerHTML = '<span class="tab-icon" aria-hidden="true">◷</span><span>Releases</span>';
      button.after(release);
    });
  getCore().state = state;
}
