import { loadSeriesDetails } from "./series-api.js";
import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createSeriesDetailsLoader(root, status, {
  seriesState, trackDiscoveryPreference, updateSeriesResultSelection, showSeriesLoading,
  openMediaModal, findSeriesResultCard, showSeriesDetail, updateSeriesStatus,
  refreshSeriesJellyfinStatus, switchTab, firstEpisodeSlug, seriesEpisodes, isEpisodeSelectable,
  renderSeriesTiles, syncWatchlistSnapshot, client = api,
}) {
  const byId = id => root.querySelector(`#${id}`);
  let scope = null;
  function begin() { scope?.dispose(); scope = createScope(); return scope; }
  function mergeSeriesDetailPayload(previous, fresh) {
    if (!previous) return fresh;
    if (!fresh) return previous;
    const seasons = new Map();
    for (const snapshot of [previous, fresh]) {
      for (const season of snapshot.seasons || []) {
        const seasonNumber = Number(season.season || 0);
        if (seasonNumber <= 0) continue;
        const episodes = seasons.get(seasonNumber) || new Map();
        for (const episode of season.episodes || []) {
          const key = episode.slug || `${seasonNumber}:${episode.episode}`;
          episodes.set(key, { ...(episodes.get(key) || {}), ...episode });
        }
        seasons.set(seasonNumber, episodes);
      }
    }
    const mergedSeasons = [...seasons.entries()]
      .sort(([left], [right]) => left - right)
      .map(([season, episodes]) => ({
        season,
        episodes: [...episodes.values()].sort((left, right) => left.episode - right.episode),
      }));
    return {
      ...previous,
      ...fresh,
      seasons: mergedSeasons,
      episode_count: mergedSeasons.reduce((total, season) => total + season.episodes.length, 0),
      backdrop_url: fresh.backdrop_url || previous.backdrop_url || "",
    };
  }

  async function loadSeries(result) {
    const cacheKey = result.base_slug || result.sample_slug;
    if (seriesState.pendingBaseSlug === cacheKey) return;
    trackDiscoveryPreference("series", result, 0.8, "open");
    const owner = begin();
    const requestId = ++seriesState.requestSeq;
    seriesState.pendingBaseSlug = cacheKey;
    updateSeriesResultSelection();
    showSeriesLoading(result);
    openMediaModal("series-detail-modal", findSeriesResultCard(result.base_slug));

    const cached = seriesState.cache[cacheKey];
    if (cached) {
      const enriched = mergeSeriesDetailPayload(result, cached);
      showSeriesDetail(enriched, result.sample_slug);
      updateSeriesStatus(enriched);
      refreshSeriesJellyfinStatus();
      return;
    }

    status.textContent = `Öffne Staffeln für «${result.title}» …`;
    try {
      const loaded = await loadSeriesDetails(client, result.sample_slug, result.base_slug || "", {
      deferChecks: true, signal: owner.signal,
    });
    if (!owner.active || requestId !== seriesState.requestSeq) return;
      const series = mergeSeriesDetailPayload(result, loaded);
      showSeriesDetail(series, result.sample_slug);
      updateSeriesStatus(series);
      refreshSeriesJellyfinStatus();
    } catch (e) {
      if (!owner.active || requestId !== seriesState.requestSeq) return;
      seriesState.pendingBaseSlug = "";
      updateSeriesResultSelection();
      status.textContent = `Fehler: ${e.message}`;
      byId("series-detail-title").textContent = `${result.title} · Laden fehlgeschlagen`;
      byId("series-desc").textContent = e.message;
      const loading = root.querySelector("#series-tiles .series-loading");
      if (loading) loading.textContent = "Serie konnte nicht geladen werden";
    }
  }

  async function openWatchlistEntry(baseSlug) {
    switchTab("serien", { autoLoad: false });
    seriesState.browseRequestSeq += 1;
    seriesState.loadingBrowse = false;
    const owner = begin();
    const openGeneration = ++seriesState.viewGeneration;
    status.textContent = "Lade abonnierte Serie …";
    try {
      const series = await client.post("/api/watchlist/open", { base_slug: baseSlug }, { signal: owner.signal });
      if (!owner.active || seriesState.viewGeneration !== openGeneration) return;
      const preselect = series.preselect_slugs || [];
      delete series.preselect_slugs;
      showSeriesDetail(series, firstEpisodeSlug(series));
      const selectable = new Set(
        seriesEpisodes(series).filter(isEpisodeSelectable).map((episode) => episode.slug),
      );
      seriesState.epPicked = new Set(preselect.filter((slug) => selectable.has(slug)));
      renderSeriesTiles();
      await syncWatchlistSnapshot("Abo-Aktualisierung nach Öffnen");
    } catch (error) {
      if (!owner.active || seriesState.viewGeneration !== openGeneration) return;
      status.textContent =
        `Serie konnte nicht geöffnet werden: ${error.message}`;
    }
  }
  return {
    open: loadSeries, openSubscription: openWatchlistEntry, merge: mergeSeriesDetailPayload,
    unmount() {
      scope?.dispose(); scope = null;
      seriesState.pendingBaseSlug = "";
      seriesState.requestSeq += 1;
      seriesState.viewGeneration += 1;
    },
  };
}
