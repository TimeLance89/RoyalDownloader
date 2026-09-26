import { WATCH_CLEANUP_DEFAULT } from "../../shared/constants/watch-policy.js";
import { WATCH_MODE_DEFAULT } from "../../shared/constants/watch-policy.js";

export function createSubscriptionActions({
  syncWatchlistSnapshot,
  watchlistEntryForSeries,
  renderSeriesCatalogHero,
  renderSeriesResults,
  updateSeriesInfiniteState,
  updateWatchBtn,
  fpStatusMessage,
  renderFpResults,
  updateFpInfiniteState,
  refreshMovieFeatureCandidates,
  getNotifications,
  getSeriesState,
  getSubscriptionSummary,
  getCatalogIdentity,
  getMovieState,
  getSeriesDetailsLoader,
}) {
  // ── Bibliothek-Tab ─────────────────────────────────────────────────────────
  function presentWatchlist(snapshot, previous) {
    getNotifications().refresh();
    const items = snapshot.items;
    if (items === previous?.items) return;
    for (const series of Object.values(getSeriesState().cache)) {
      const entry = watchlistEntryForSeries(series, items);
      series.watchlisted = Boolean(entry);
      series.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
      series.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
    }
    if (getSeriesState().current) {
      const entry = watchlistEntryForSeries(getSeriesState().current, items);
      getSeriesState().current.watchlisted = Boolean(entry);
      getSeriesState().current.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
      getSeriesState().current.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
      updateWatchBtn();
    }
    renderSeriesSubscriptions();
  }

  function renderSeriesSubscriptions() { getSubscriptionSummary().refresh(); }

  async function refreshWatchlist() {
    return syncWatchlistSnapshot("Abo-Aktualisierung");
  }

  function watchlistCheckResultText(data) {
    return String(data?.health?.error || "")
      || `${Number(data?.checked || 0)}/${Number(data?.total || 0)} geprüft`;
  }

  function dedupeCatalogMedia(items) { return getCatalogIdentity().dedupe(items); }
  function catalogLogicalMediaMatch(left, right) { return getCatalogIdentity().match(left, right); }

  function reconcileMovieCatalogDuplicates() {
    const current = Array.isArray(getMovieState().results) ? getMovieState().results : [];
    const selected = current.find((item) => item.slug === getMovieState().selectedSlug) || null;
    const reconciled = dedupeCatalogMedia(current);
    if (reconciled.length === current.length) return false;

    getMovieState().results = reconciled;
    if (selected && !reconciled.some((item) => item.slug === getMovieState().selectedSlug)) {
      getMovieState().selectedSlug = reconciled.find((item) => catalogLogicalMediaMatch(item, selected))?.slug || null;
    }
    renderFpResults(0);
    refreshMovieFeatureCandidates();
    updateFpInfiniteState();
    const status = document.getElementById("fp-status");
    if (status) status.textContent = fpStatusMessage();
    return true;
  }

  function reconcileSeriesCatalogDuplicates() {
    const current = Array.isArray(getSeriesState().results) ? getSeriesState().results : [];
    const reconciled = dedupeCatalogMedia(current);
    if (reconciled.length === current.length) return false;

    getSeriesState().results = reconciled;
    renderSeriesResults(0);
    renderSeriesCatalogHero();
    updateSeriesInfiniteState();
    const sourceCount = getSeriesState().sources.length;
    const status = document.getElementById("series-status");
    if (status) {
      status.textContent = reconciled.length
        ? (sourceCount
          ? `${reconciled.length} Serie(n) · ${sourceCount} ${sourceCount === 1 ? "Quelle" : "Quellen"}`
          : `${reconciled.length} Serie(n) gefunden`)
        : "Keine Serie gefunden.";
    }
    return true;
  }

  function openWatchlistEntry(...args) { return getSeriesDetailsLoader().openSubscription(...args); }
  return { presentWatchlist, renderSeriesSubscriptions, refreshWatchlist, watchlistCheckResultText, dedupeCatalogMedia, catalogLogicalMediaMatch, reconcileMovieCatalogDuplicates, reconcileSeriesCatalogDuplicates, openWatchlistEntry };
}
