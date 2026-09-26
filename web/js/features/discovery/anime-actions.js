export function createAnimeActions({
  getAnime,
  getSubscriptions,
  getSubscriptionRules,
}) {
  function animeBrowse(...args) { return getAnime().browse(...args); }
  function restoreAnimeSearchContext(...args) { return getAnime().restore(...args); }
  function openAnimeDetail(...args) { return getAnime().open(...args); }
  function loadAnimeDetail(...args) { return getAnime().loadDetail(...args); }
  function renderAnimeResults(...args) { return getAnime().renderResults(...args); }
  function renderAnimeDetail(...args) { return getAnime().renderDetail(...args); }
  function renderAnimeEpisodes(...args) { return getAnime().renderEpisodes(...args); }
  function syncAnimeQueueFlags(...args) { return getAnime().syncQueue(...args); }
  function markAnimeSlugDownloaded(...args) { return getAnime().markDownloaded(...args); }
  function animeAddSelected(...args) { return getAnime().addSelected(...args); }

  function normalizeSeriesIdentityTitle(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase()
      .replace(/[^a-z0-9]+/g, "");
  }

  function watchlistEntryForSeries(series, items = getSubscriptions().get().items) {
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

  function openWatchModeModal(entry = null) { getSubscriptionRules().open(entry); }
  return { animeBrowse, restoreAnimeSearchContext, openAnimeDetail, loadAnimeDetail, renderAnimeResults, renderAnimeDetail, renderAnimeEpisodes, syncAnimeQueueFlags, markAnimeSlugDownloaded, animeAddSelected, normalizeSeriesIdentityTitle, watchlistEntryForSeries, openWatchModeModal };
}
