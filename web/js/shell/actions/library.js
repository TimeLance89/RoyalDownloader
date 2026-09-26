import { WATCH_CLEANUP_DEFAULT, WATCH_MODE_DEFAULT, sharedPresentation, syncWatchlistSnapshot } from "../presentation.js";
import { watchlistEntryForSeries } from "./anime.js";
import { renderSeriesCatalogHero, renderSeriesResults, updateSeriesInfiniteState, updateWatchBtn } from "./series.js";
import { fpStatusMessage, renderFpResults, updateFpInfiniteState } from "./movies.js";
import { refreshMovieFeatureCandidates } from "./home.js";
// ── Bibliothek-Tab ─────────────────────────────────────────────────────────
export function presentWatchlist(snapshot, previous) {
  sharedPresentation.notifications.refresh();
  const items = snapshot.items;
  if (items === previous?.items) return;
  for (const series of Object.values(sharedPresentation.seriesState.cache)) {
    const entry = watchlistEntryForSeries(series, items);
    series.watchlisted = Boolean(entry);
    series.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
    series.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
  }
  if (sharedPresentation.seriesState.current) {
    const entry = watchlistEntryForSeries(sharedPresentation.seriesState.current, items);
    sharedPresentation.seriesState.current.watchlisted = Boolean(entry);
    sharedPresentation.seriesState.current.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
    sharedPresentation.seriesState.current.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
    updateWatchBtn();
  }
  renderSeriesSubscriptions();
}

export function renderSeriesSubscriptions() { sharedPresentation.subscriptionSummary.refresh(); }

export async function refreshWatchlist() {
  return syncWatchlistSnapshot("Abo-Aktualisierung");
}

export function watchlistCheckResultText(data) {
  return String(data?.health?.error || "")
    || `${Number(data?.checked || 0)}/${Number(data?.total || 0)} geprüft`;
}

export function dedupeCatalogMedia(items) { return sharedPresentation.catalogIdentity.dedupe(items); }
export function catalogLogicalMediaMatch(left, right) { return sharedPresentation.catalogIdentity.match(left, right); }

export function reconcileMovieCatalogDuplicates() {
  const current = Array.isArray(sharedPresentation.movieState.results) ? sharedPresentation.movieState.results : [];
  const selected = current.find((item) => item.slug === sharedPresentation.movieState.selectedSlug) || null;
  const reconciled = dedupeCatalogMedia(current);
  if (reconciled.length === current.length) return false;

  sharedPresentation.movieState.results = reconciled;
  if (selected && !reconciled.some((item) => item.slug === sharedPresentation.movieState.selectedSlug)) {
    sharedPresentation.movieState.selectedSlug = reconciled.find((item) => catalogLogicalMediaMatch(item, selected))?.slug || null;
  }
  renderFpResults(0);
  refreshMovieFeatureCandidates();
  updateFpInfiniteState();
  const status = document.getElementById("fp-status");
  if (status) status.textContent = fpStatusMessage();
  return true;
}

export function reconcileSeriesCatalogDuplicates() {
  const current = Array.isArray(sharedPresentation.seriesState.results) ? sharedPresentation.seriesState.results : [];
  const reconciled = dedupeCatalogMedia(current);
  if (reconciled.length === current.length) return false;

  sharedPresentation.seriesState.results = reconciled;
  renderSeriesResults(0);
  renderSeriesCatalogHero();
  updateSeriesInfiniteState();
  const sourceCount = sharedPresentation.seriesState.sources.length;
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

export function openWatchlistEntry(...args) { return sharedPresentation.seriesDetailsLoader.openSubscription(...args); }
