import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { createHomeCache } from "./cache.js";

/** Session-owned server catalog. View filters and rail positions stay with the view. */
export function createHomeData({
  client = api, storage, getMovieMetadata, isRendered,
  homeAllEntries, homeArtworkEntriesInLayout, renderHome,
  syncFpCatalogFromHome, syncSeriesCatalogFromHome,
  hydrateHomeMovieArtwork, hydrateHomeSeriesArtwork,
  refreshCatalogJellyfinStatus, discoveryV2MergeItems, homeMovieEntry, homeSeriesEntry,
  onLoaded = () => {},
}) {
  const data = { newMovies: [], topMovies: [], cinemaMovies: [], cinemaUpdatedAt: 0,
    trendingSeries: [], newSeries: [],
    discoveryMovies: [], discoverySeries: [], loading: true, refreshing: false };
  const cache = createHomeCache(data, getMovieMetadata, storage);
  let owner = createScope();
  let pendingLoad = null;
  let pendingWarm = null;
  let cancelWarm = () => {};
  let resumeLoad = false;
  let resumeWarm = false;
  let warmFinished = false;
  const saveHomeCache = () => { if (owner.active) cache.save(); };
  function catalog(kind, params, signal) {
    return client.get(`/api/${kind === "movie" ? "movies" : "series"}?${new URLSearchParams(params)}`, {
      signal, ...(kind === "movie" ? { timeoutMs: 15_000,
        timeoutMessage: "Der Filmkatalog antwortet zu langsam. Die Anbieter laden im Hintergrund weiter." } : {}),
    });
  }
  async function refreshCinemaStatus(scope) {
    try {
      const response = await client.get("/api/tmdb/now-playing", { signal: scope.signal });
      if (!scope.active || response?.available !== true || !Array.isArray(response.ids)) return;
      const ids = new Set(response.ids.map(String));
      const metadata = getMovieMetadata();
      let changed = false;
      const titleIdentity = (movie) => {
        const title = String(movie.title || "").replace(/\s*\[[^\]]{1,40}\]\s*$/, "")
          .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
          .toLowerCase().replace(/[^a-z0-9]+/g, "").trim();
        const year = String(movie.year || movie.release_date || "").slice(0, 4);
        return title && /^\d{4}$/.test(year) ? `${title}:${year}` : "";
      };
      const currentMovies = Array.isArray(response.movies) ? response.movies : [];
      const byId = new Map(currentMovies.map(movie => [String(movie.tmdb_id), movie]));
      const byTitle = new Map(currentMovies.map(movie => [titleIdentity(movie), movie]).filter(([key]) => key));
      for (const item of [...data.newMovies, ...data.topMovies, ...data.discoveryMovies]) {
        const details = metadata[item.slug] || {};
        const media = { ...item, ...details };
        const cinema = byId.get(String(media.tmdb_id)) || byTitle.get(titleIdentity(media));
        if (!media.tmdb_id && !cinema) continue;
        const updated = { ...details, in_cinema: Boolean(cinema) || ids.has(String(media.tmdb_id)) };
        // Enrich the existing provider title rather than discarding its cinema
        // record and leaving it without the artwork/momentum needed by the hero.
        for (const field of ["tmdb_id", "release_date", "rating", "vote_count", "popularity", "backdrop_url"]) {
          if (cinema?.[field] != null) updated[field] = cinema[field];
        }
        if (JSON.stringify(updated) !== JSON.stringify(details)) {
          metadata[item.slug] = updated;
          changed = true;
        }
      }
      const knownIds = new Set([...data.newMovies, ...data.topMovies, ...data.discoveryMovies]
        .map((item) => metadata[item.slug]?.tmdb_id || item.tmdb_id)
        .filter(Boolean).map(String));
      const knownTitles = new Set([...data.newMovies, ...data.topMovies, ...data.discoveryMovies]
        .map((item) => titleIdentity({ ...item, ...metadata[item.slug] })).filter(Boolean));
      const cinemaMovies = (Array.isArray(response.movies) ? response.movies : [])
        .filter((movie) => movie?.slug && movie.backdrop_url
          && !knownIds.has(String(movie.tmdb_id))
          && !knownTitles.has(titleIdentity(movie)))
        .slice(0, 30);
      if (JSON.stringify(cinemaMovies) !== JSON.stringify(data.cinemaMovies)) changed = true;
      data.cinemaMovies = cinemaMovies;
      data.cinemaUpdatedAt = Date.now();
      saveHomeCache();
      if (changed) renderHome({ force: true });
    } catch {
      // The current catalog and release dates still provide a usable selection.
    }
  }
  function scheduleWarm(delay) {
    cancelWarm();
    cancelWarm = owner.timeout(() => { void warm(); }, delay);
  }
  function load() {
    if (!owner.active) return Promise.resolve();
    if (pendingLoad) return pendingLoad;
    const scope = owner;
    const result = performLoad(scope).finally(() => { if (pendingLoad === result) pendingLoad = null; });
    pendingLoad = result;
    return result;
  }
  function warm() {
    if (!owner.active) return Promise.resolve();
    if (pendingWarm) return pendingWarm;
    const scope = owner;
    pendingWarm = performWarm(scope).then(result => {
      if (scope.active) warmFinished = true;
      return result;
    }).catch(error => {
      if (scope.active) console.warn("Discovery-Reservoir konnte nicht vollständig erweitert werden:", error);
      return null;
    });
    return pendingWarm;
  }
  async function performLoad(scope) {
    const hadCachedPresentation = isRendered() && homeAllEntries().length > 0;
    let catalogUpdated = false;
    data.refreshing = true;
    data.loading = !hadCachedPresentation;
    if (!hadCachedPresentation) renderHome({ force: true });
    let seriesEntries = [];
    try {
      // Alle Katalogdaten werden zuerst vollständig gesammelt. Währenddessen
      // bleibt entweder der gespeicherte Stand oder genau ein Skeleton sichtbar.
      const primary = await Promise.allSettled([
        catalog("movie", { mode: "new", page: 1 }, scope.signal),
        catalog("series", { mode: "trending", page: 1 }, scope.signal),
      ]);
      if (!scope.active) return;
      if (primary[0].status === "fulfilled" && primary[0].value.results?.length) {
        data.newMovies = primary[0].value.results;
        catalogUpdated = true;
      }
      if (primary[1].status === "fulfilled" && primary[1].value.results?.length) {
        data.trendingSeries = primary[1].value.results;
        catalogUpdated = true;
      }
      if (!data.topMovies.length) data.topMovies = data.newMovies.slice();
      if (!data.newSeries.length) data.newSeries = data.trendingSeries.slice();
      syncFpCatalogFromHome({ fresh: true });
      syncSeriesCatalogFromHome({ fresh: true });

      const secondary = await Promise.allSettled([
        catalog("movie", { mode: "top", page: 1 }, scope.signal),
        catalog("series", { mode: "new", page: 1 }, scope.signal),
        catalog("series", { mode: "discover", page: 1 }, scope.signal),
        catalog("movie", { mode: "new", page: 2 }, scope.signal),
        catalog("movie", { mode: "top", page: 2 }, scope.signal),
      ]);
      if (!scope.active) return;
      if (secondary[0].status === "fulfilled" && secondary[0].value.results?.length) {
        data.topMovies = secondary[0].value.results;
        catalogUpdated = true;
      }
      if (secondary[1].status === "fulfilled" && secondary[1].value.results?.length) {
        data.newSeries = secondary[1].value.results;
        catalogUpdated = true;
      }
      if (secondary[2].status === "fulfilled" && secondary[2].value.results?.length) {
        data.discoverySeries = discoveryV2MergeItems(
          secondary[2].value.results, data.discoverySeries, "series",
        ).slice(0, 220);
        catalogUpdated = true;
      }
      const discoveredMovies = secondary.slice(3)
        .filter((result) => result.status === "fulfilled")
        .flatMap((result) => result.value.results || []);
      if (discoveredMovies.length) {
        data.discoveryMovies = discoveryV2MergeItems(
          discoveredMovies, data.discoveryMovies, "movie",
        ).slice(0, 220);
        catalogUpdated = true;
      }
      if (!data.topMovies.length) data.topMovies = data.newMovies.slice();
      if (!data.newSeries.length) data.newSeries = data.trendingSeries.slice();

      // Nur die tatsächlich sichtbaren Reihen erhalten vor dem ersten Aufbau
      // ihre 16:9-Wallpaper. Es gibt keinen zwischenzeitlichen Poster-Render.
      const artworkEntries = homeArtworkEntriesInLayout();
      await Promise.allSettled([
        hydrateHomeMovieArtwork(
          artworkEntries.filter((entry) => entry.kind === "movie").map((entry) => entry.item),
          { render: false, signal: scope.signal },
        ),
        hydrateHomeSeriesArtwork(
          artworkEntries.filter((entry) => entry.kind === "series").map((entry) => entry.item),
          { render: false, signal: scope.signal },
        ),
      ]);

      if (!scope.active) return;
      const currentEntries = homeAllEntries();
      const movieEntries = currentEntries.filter((entry) => entry.kind === "movie");
      seriesEntries = currentEntries.filter((entry) => entry.kind === "series");
      await refreshCatalogJellyfinStatus(movieEntries, null, { signal: scope.signal });
      if (scope.active) saveHomeCache();
    } finally {
      if (scope.active) {
        data.loading = false;
        data.refreshing = false;
        if (!hadCachedPresentation || catalogUpdated) renderHome({ force: true });
      }
    }
    if (scope.active && seriesEntries.length) {
      void refreshCatalogJellyfinStatus(seriesEntries, null, { signal: scope.signal })
        .then(() => { if (scope.active) saveHomeCache(); })
        .catch((error) => { if (scope.active) console.warn("Serien-Jellyfin-Status konnte nicht aktualisiert werden:", error); });
    }
    if (scope.active) {
      scheduleWarm(120);
      void refreshCinemaStatus(scope);
      onLoaded();
    }
  }

  async function hydrateInBatches(items, kind, scope) {
    const unique = items.filter(Boolean);
    for (let index = 0; index < unique.length; index += 80) {
      if (!scope.active) return;
      const batch = unique.slice(index, index + 80);
      if (kind === "movie") await hydrateHomeMovieArtwork(batch, { render: false, signal: scope.signal });
      else await hydrateHomeSeriesArtwork(batch, { render: false, signal: scope.signal });
    }
  }

  async function performWarm(scope) {
    if (pendingLoad) await pendingLoad;
    if (!scope.active) return;
    const movies = [];
    const series = [];
    const dailyPageOffset = Math.floor(Date.now() / 86400000) % 5;
    const waves = [
      [
        ["movie", () => catalog("movie", { mode: "new", page: 3 }, scope.signal)],
        ["movie", () => catalog("movie", { mode: "top", page: 3 }, scope.signal)],
        ["series", () => catalog("series", { mode: "discover", page: 2 }, scope.signal)],
        ["series", () => catalog("series", { mode: "trending", page: 2 }, scope.signal)],
        ["series", () => catalog("series", { mode: "new", page: 2 }, scope.signal)],
      ],
      [
        ["movie", () => catalog("movie", { mode: "new", page: 4 }, scope.signal)],
        ["movie", () => catalog("movie", { mode: "top", page: 4 + dailyPageOffset }, scope.signal)],
        ["series", () => catalog("series", { mode: "discover", page: 3 + dailyPageOffset }, scope.signal)],
        ["series", () => catalog("series", { mode: "trending", page: 3 }, scope.signal)],
        ["series", () => catalog("series", { mode: "new", page: 3 }, scope.signal)],
      ],
    ];

    for (const wave of waves) {
      const settled = await Promise.allSettled(wave.map(([, request]) => request()));
      if (!scope.active) return;
      settled.forEach((result, index) => {
        if (result.status !== "fulfilled") return;
        const kind = wave[index][0];
        const values = result.value?.results || [];
        if (kind === "movie") movies.push(...values);
        else series.push(...values);
      });
    }

    const previousMovieKeys = new Set(data.discoveryMovies.map((item) => item.slug));
    const previousSeriesKeys = new Set(data.discoverySeries.map((item) => item.base_slug));
    data.discoveryMovies = discoveryV2MergeItems(movies, data.discoveryMovies, "movie").slice(0, 220);
    data.discoverySeries = discoveryV2MergeItems(series, data.discoverySeries, "series").slice(0, 220);
    const newMovies = data.discoveryMovies.filter((item) => !previousMovieKeys.has(item.slug));
    const newSeries = data.discoverySeries.filter((item) => !previousSeriesKeys.has(item.base_slug));

    await Promise.allSettled([
      hydrateInBatches(newMovies, "movie", scope),
      hydrateInBatches(newSeries, "series", scope),
    ]);
    if (!scope.active) return;
    await refreshCatalogJellyfinStatus([
      ...newMovies.map(homeMovieEntry),
      ...newSeries.map(homeSeriesEntry),
    ], null, { signal: scope.signal });
    if (!scope.active) return;
    saveHomeCache();
    // Publish the hydrated reservoir now, including on a first visit.
    if (newMovies.length || newSeries.length) renderHome({ force: true });
    return { movies: data.discoveryMovies.length, series: data.discoverySeries.length };
  }

  return {
    get: () => Object.freeze({ ...data }), load, warm, save: saveHomeCache,
    restore() {
      if (!owner.active) return false;
      const restored = cache.restore();
      if (restored) { renderHome({ force: true }); scheduleWarm(350); }
      return restored;
    },
    unmount() {
      if (!owner.active) return;
      resumeLoad = Boolean(pendingLoad);
      resumeWarm = Boolean(pendingWarm) && !warmFinished;
      owner.dispose(); pendingLoad = null; pendingWarm = null;
      warmFinished = false;
      data.loading = false; data.refreshing = false;
    },
    mount() {
      if (owner.active) return;
      owner = createScope();
      if (resumeLoad) void load().catch(error => console.warn("Startseite konnte nicht geladen werden:", error));
      if (resumeWarm) void warm();
      resumeLoad = false; resumeWarm = false;
    },
  };
}
