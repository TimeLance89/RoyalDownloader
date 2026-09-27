import { createMovieSubscriptionRules } from "../features/subscriptions/movie-rules.js";
import { createSubscriptions } from "../features/subscriptions/state.js";
import { createSubscriptionActions } from "../features/subscriptions/actions.js";
import { WATCH_MODE_EXPLANATIONS } from "../shared/constants/watch-policy.js";
import { WATCH_CLEANUP_DEFAULT } from "../shared/constants/watch-policy.js";
import { WATCH_CLEANUP_LABELS } from "../shared/constants/watch-policy.js";
import { WATCH_MODE_DEFAULT } from "../shared/constants/watch-policy.js";
import { WATCH_MODE_LABELS } from "../shared/constants/watch-policy.js";
import { createSubscriptionSummary } from "../features/subscriptions/summary.js";

import { movieSubscriptionFor } from "../features/subscriptions/movie-model.js";
import { createMovieSubscriptionsView } from "../features/subscriptions/movies.js";
import { subscriptionMonogram } from "../features/subscriptions/summary.js";
import { createSubscriptionRules } from "../features/subscriptions/rules.js";

import { createLibrary } from "../features/subscriptions/index.js";

import { watchlistStatusText } from "../features/subscriptions/summary.js";
import { downloadedEpisodeLabel } from "../features/notifications/model.js";

import { createNotifications } from "../features/notifications/index.js";

import { libraryCheckedLabel } from "../features/subscriptions/model.js";

export function composeSubscriptions({ movieSubscriptions, movieSubscriptionRules, subscriptions, seriesState, artworkUrls, getCore, getDiscovery, getHome, getIntegrations }) {
  const services = {
  subscriptionSummary: createSubscriptionSummary(document.getElementById("series-subscriptions-list"), document.getElementById("series-subscriptions-count"), {
        getItems: () => services.subscriptions.get().items, open: ((...args) => services.actions.openWatchlistEntry(...args)),
        WATCH_MODE_LABELS, WATCH_MODE_DEFAULT, WATCH_CLEANUP_LABELS, WATCH_CLEANUP_DEFAULT,
      }),
  movieSubscriptions,
  movieSubscriptionRules,
  movieSubscriptionFor: (slug, movie) => movieSubscriptionFor(movieSubscriptions.get().items, slug, movie),
  movieSubscriptionView: createMovieSubscriptionsView(document.querySelector(".movie-subscriptions"), {
        model: movieSubscriptions, subscriptionMonogram, open: movieSubscriptionRules.open,
      }),
  subscriptions,
  subscriptionRules: createSubscriptionRules(document.getElementById("watch-mode-modal"), {
        subscriptions, getSeries: () => seriesState.current,
        findEntry: series => getDiscovery().animeActions.watchlistEntryForSeries(series), getCleanupDefault: () => getIntegrations().jellyfin.get().cleanupDefault,
        isJellyfinConfigured: () => getIntegrations().jellyfin.get().userConfigured,
        refreshQueue: () => getCore().actions.syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung"),
        WATCH_MODE_DEFAULT, WATCH_MODE_EXPLANATIONS, WATCH_CLEANUP_DEFAULT, WATCH_CLEANUP_LABELS,
      }),
  library: createLibrary(document.getElementById("tab-bibliothek"), {
        subscriptions, checkResultText: data => services.actions.watchlistCheckResultText(data),
        refreshQueue: () => getCore().actions.syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung"),
        coverUrl: url => artworkUrls.coverUrl(url), watchlistStatusText, subscriptionMonogram, downloadedEpisodeLabel,
        openWatchModeModal: entry => getDiscovery().animeActions.openWatchModeModal(entry), openWatchlistEntry: slug => services.actions.openWatchlistEntry(slug),
        WATCH_MODE_LABELS, WATCH_MODE_DEFAULT, WATCH_CLEANUP_LABELS, WATCH_CLEANUP_DEFAULT,
      }),
  notifications: createNotifications(document.querySelector(".bell-wrap"), {
        getSnapshot: subscriptions.get,
        getSnapshotVersion: () => subscriptions.revision,
        check: subscriptions.check, onSnapshot: subscriptions.accept,
        openEntry: slug => services.actions.openWatchlistEntry(slug), openLibrary: () => getCore().actions.switchTab("bibliothek"),
        coverUrl: url => artworkUrls.coverUrl(url), subscriptionMonogram, libraryCheckedLabel,
      })
  };
  services.actions = createSubscriptionActions({
    syncWatchlistSnapshot: (...args) => getCore().actions.syncWatchlistSnapshot(...args),
    watchlistEntryForSeries: (...args) => getDiscovery().animeActions.watchlistEntryForSeries(...args),
    renderSeriesCatalogHero: (...args) => getDiscovery().seriesActions.renderSeriesCatalogHero(...args),
    renderSeriesResults: (...args) => getDiscovery().seriesActions.renderSeriesResults(...args),
    updateSeriesInfiniteState: (...args) => getDiscovery().seriesActions.updateSeriesInfiniteState(...args),
    updateWatchBtn: (...args) => getDiscovery().seriesActions.updateWatchBtn(...args),
    fpStatusMessage: (...args) => getDiscovery().movieActions.fpStatusMessage(...args),
    renderFpResults: (...args) => getDiscovery().movieActions.renderFpResults(...args),
    updateFpInfiniteState: (...args) => getDiscovery().movieActions.updateFpInfiniteState(...args),
    refreshMovieFeatureCandidates: (...args) => getHome().actions.refreshMovieFeatureCandidates(...args),
    getNotifications: () => services.notifications,
    getSeriesState: () => getDiscovery().seriesState,
    getSubscriptionSummary: () => services.subscriptionSummary,
    getCatalogIdentity: () => getDiscovery().catalogIdentity,
    getMovieState: () => getDiscovery().movieState,
    getSeriesDetailsLoader: () => getDiscovery().seriesDetailsLoader,
  });
  return services;
}

export function prepareSubscriptions({ getCore, getIntegrations }) {
  const subscriptions = createSubscriptions({ onPersistence: data => getCore().actions.showPersistenceWarning("Serien-Abos", data) });
  const movieSubscriptions = createSubscriptions({ kind: "movies", onPersistence: data => getCore().actions.showPersistenceWarning("Film-Abos", data) });
  const movieSubscriptionRules = createMovieSubscriptionRules(document.getElementById("movie-subscription-modal"), {
      model: movieSubscriptions, isJellyfinConfigured: () => getIntegrations().jellyfin.get().userConfigured,
    });
  return { subscriptions, movieSubscriptions, movieSubscriptionRules };
}
