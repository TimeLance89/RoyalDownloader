/** Best-effort seven-day catalog cache; UI state and credentials are never persisted. */
export function createHomeCache(data, getMovieMetadata, storage) {
  if (storage === undefined) {
    try { storage = globalThis.localStorage; } catch { storage = null; }
  }
  const HOME_CACHE_KEY = "royal-home-cache-v5";
  const HOME_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

  function restore() {
    try {
      const cached = JSON.parse(storage.getItem(HOME_CACHE_KEY) || "null");
      if (
        !cached
        || !Number.isFinite(Number(cached.savedAt))
        || Date.now() - Number(cached.savedAt || 0) > HOME_CACHE_MAX_AGE_MS
        || Number(cached.savedAt) > Date.now()
        || !cached.home
      ) return false;
      const keys = [
        "newMovies", "topMovies", "trendingSeries", "newSeries",
        "discoveryMovies", "discoverySeries",
      ];
      if (!keys.some((key) => Array.isArray(cached.home[key]) && cached.home[key].length)) return false;
      keys.forEach((key) => {
        data[key] = Array.isArray(cached.home[key]) ? cached.home[key] : [];
      });
      const cinemaAge = Date.now() - Number(cached.home.cinemaUpdatedAt || 0);
      data.cinemaMovies = cinemaAge >= 0 && cinemaAge < 24 * 60 * 60 * 1000
        && Array.isArray(cached.home.cinemaMovies) ? cached.home.cinemaMovies : [];
      data.cinemaUpdatedAt = data.cinemaMovies.length ? Number(cached.home.cinemaUpdatedAt) : 0;
      Object.assign(getMovieMetadata(), cached.movieMetadata || {});
      data.loading = false;

      return true;
    } catch {
      return false;
    }
  }

  function save() {
    try {
      const movieSlugs = new Set([
        ...data.newMovies,
        ...data.topMovies,
        ...data.discoveryMovies,
      ].map((item) => item?.slug).filter(Boolean));
      const movieMetadata = Object.fromEntries(
        [...movieSlugs]
          .filter((slug) => getMovieMetadata()[slug])
          .map((slug) => [slug, getMovieMetadata()[slug]]),
      );
      storage.setItem(HOME_CACHE_KEY, JSON.stringify({
        savedAt: Date.now(),
        home: {
          newMovies: data.newMovies,
          topMovies: data.topMovies,
          cinemaMovies: data.cinemaMovies,
          cinemaUpdatedAt: data.cinemaUpdatedAt,
          trendingSeries: data.trendingSeries,
          newSeries: data.newSeries,
          discoveryMovies: data.discoveryMovies,
          discoverySeries: data.discoverySeries,
        },
        movieMetadata,
      }));
    } catch {
      // Ein voller oder gesperrter Browser-Speicher darf die Startseite nicht blockieren.
    }
  }

  return { restore, save };
}
