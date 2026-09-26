import { sharedPresentation } from "../presentation.js";
export function animeBrowse(...args) { return sharedPresentation.anime.browse(...args); }
export function restoreAnimeSearchContext(...args) { return sharedPresentation.anime.restore(...args); }
export function openAnimeDetail(...args) { return sharedPresentation.anime.open(...args); }
export function loadAnimeDetail(...args) { return sharedPresentation.anime.loadDetail(...args); }
export function renderAnimeResults(...args) { return sharedPresentation.anime.renderResults(...args); }
export function renderAnimeDetail(...args) { return sharedPresentation.anime.renderDetail(...args); }
export function renderAnimeEpisodes(...args) { return sharedPresentation.anime.renderEpisodes(...args); }
export function syncAnimeQueueFlags(...args) { return sharedPresentation.anime.syncQueue(...args); }
export function markAnimeSlugDownloaded(...args) { return sharedPresentation.anime.markDownloaded(...args); }
export function animeAddSelected(...args) { return sharedPresentation.anime.addSelected(...args); }

export function normalizeSeriesIdentityTitle(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

export function watchlistEntryForSeries(series, items = sharedPresentation.subscriptions.get().items) {
  if (!series) return null;
  const exact = items.find((item) => item.base_slug === series.base_slug);
  if (exact) return exact;
  const tmdbId = String(series.tmdb_id || "").trim();
  if (tmdbId) {
    const stable = items.filter((item) => String(item.tmdb_id || "").trim() === tmdbId);
    if (stable.length === 1) return stable[0];
  }
  const wantedTitles = new Set([
    series.title, series.original_title, ...(series.aliases || []),
  ].map(normalizeSeriesIdentityTitle).filter(Boolean));
  const matches = items.filter((item) => {
    const storedTmdb = String(item.tmdb_id || "").trim();
    if (tmdbId && storedTmdb && storedTmdb !== tmdbId) return false;
    return [item.title, ...(item.aliases || [])]
      .map(normalizeSeriesIdentityTitle)
      .some((title) => wantedTitles.has(title));
  });
  return matches.length === 1 ? matches[0] : null;
}

export function openWatchModeModal(entry = null) { sharedPresentation.subscriptionRules.open(entry); }
