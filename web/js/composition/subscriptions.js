import { createSubscriptionSummary } from "../features/subscriptions/summary.js";
import { sharedPresentation } from "../shell/presentation.js";
import { openWatchlistEntry } from "../shell/actions/library.js";
import { WATCH_MODE_LABELS } from "../shell/presentation.js";
import { WATCH_MODE_DEFAULT } from "../shell/presentation.js";
import { WATCH_CLEANUP_LABELS } from "../shell/presentation.js";
import { WATCH_CLEANUP_DEFAULT } from "../shell/presentation.js";
import { movieSubscriptionFor } from "../features/subscriptions/movie-model.js";
import { createMovieSubscriptionsView } from "../features/subscriptions/movies.js";
import { subscriptionMonogram } from "../features/subscriptions/summary.js";
import { createSubscriptionRules } from "../features/subscriptions/rules.js";
import { watchlistEntryForSeries } from "../shell/actions/anime.js";
import { syncQueueSnapshot } from "../shell/presentation.js";
import { WATCH_MODE_EXPLANATIONS } from "../shell/presentation.js";
import { createLibrary } from "../features/subscriptions/index.js";
import { watchlistCheckResultText } from "../shell/actions/library.js";
import { watchlistStatusText } from "../features/subscriptions/summary.js";
import { downloadedEpisodeLabel } from "../features/notifications/model.js";
import { openWatchModeModal } from "../shell/actions/anime.js";
import { createNotifications } from "../features/notifications/index.js";
import { switchTab } from "../shell/presentation.js";
import { libraryCheckedLabel } from "../features/subscriptions/model.js";

export function composeSubscriptions({ movieSubscriptions, movieSubscriptionRules, subscriptions, seriesState, artworkUrls }) {
return {
subscriptionSummary: createSubscriptionSummary(document.getElementById("series-subscriptions-list"), document.getElementById("series-subscriptions-count"), {
      getItems: () => sharedPresentation.subscriptions.get().items, open: openWatchlistEntry,
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
notifications: createNotifications(document.querySelector(".bell-wrap"), {
      getSnapshot: subscriptions.get,
      getSnapshotVersion: () => subscriptions.revision,
      check: subscriptions.check, onSnapshot: subscriptions.accept,
      openEntry: slug => openWatchlistEntry(slug), openLibrary: () => switchTab("bibliothek"),
      coverUrl: url => artworkUrls.coverUrl(url), subscriptionMonogram, libraryCheckedLabel,
    })
};
}
