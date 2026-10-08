import { loadSeriesDetails } from "./series-api.js";
import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { mergeDetailMetadata } from "./metadata.js";

export function createSeriesDetailsLoader(root, status, {
  seriesState, trackDiscoveryPreference, updateSeriesResultSelection, showSeriesLoading,
  openMediaModal, findSeriesResultCard, showSeriesDetail, updateSeriesStatus,
  refreshSeriesJellyfinStatus, switchTab, firstEpisodeSlug, seriesEpisodes, isEpisodeSelectable,
  renderSeriesTiles, syncWatchlistSnapshot, updateSeriesOverview, updateSeriesJellyfinBadge,
  verifyHuhuEpisodeLanguages, client = api,
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
          const previousEpisode = episodes.get(key);
          const merged = { ...(previousEpisode || {}), ...episode };
          if ((previousEpisode?.language_checked || previousEpisode?.huhu_language_checked)
              && !episode.language_checked && !episode.huhu_language_checked) {
            // Listing metadata must not replace concrete episode-track evidence.
            merged.content_languages = previousEpisode.content_languages;
            for (const field of ["language_checked", "language_available", "huhu_language_checked",
              "huhu_language_available", "source_providers", "source_release_verified", "language_profile"]) {
              if (previousEpisode[field] !== undefined) merged[field] = previousEpisode[field];
            }
          }
          if (merged.source_release_verified && merged.provider_unreleased === false) {
            merged.unreleased = false;
          }
          episodes.set(key, merged);
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
      ...mergeDetailMetadata(previous, fresh),
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
    const metadataWork = (async () => {
      if (!result.tmdb_id || result.metadata_source !== "TMDB") return;
      try {
        for (let attempt = 0; attempt < 3; attempt++) {
          const response = await client.post("/api/tmdb/series", { items: [{
            base_slug: cacheKey, title: result.title, year: result.year || "", tmdb_id: result.tmdb_id,
          }] }, { signal: owner.signal, timeoutMs: 4_000 });
          if (!owner.active || requestId !== seriesState.requestSeq) return;
          const metadata = response.series?.[cacheKey];
          if (metadata) {
            result = mergeDetailMetadata(result, metadata);
            if (seriesState.current) {
              const enriched = mergeSeriesDetailPayload(seriesState.current, result);
              seriesState.current = enriched;
              seriesState.cache[enriched.base_slug] = enriched;
              updateSeriesOverview(enriched);
            } else updateSeriesOverview({ ...result, seasons: [], episode_count: 0 });
            return;
          }
          if (!response.pending?.includes(cacheKey)) return;
        }
      } catch (error) { if (owner.active) console.warn("Serienmetadaten nicht erreichbar:", error); }
    })();
    // Preview identity is sufficient for a library check, even without a provider.
    if (result.tmdb_id) void client.post("/api/series/jellyfin-status", {
      title: result.title, tmdb_id: result.tmdb_id, episodes: [],
    }, { signal: owner.signal, timeoutMs: 15_000 }).then(response => {
      if (!owner.active || requestId !== seriesState.requestSeq || seriesState.current) return;
      updateSeriesJellyfinBadge({ jellyfin_configured: response.configured, jellyfin_available: response.available, seasons: [] });
    }).catch(error => {
      if (!owner.active || requestId !== seriesState.requestSeq || seriesState.current) return;
      console.warn("Serienbibliothek nicht erreichbar:", error);
      updateSeriesJellyfinBadge({ jellyfin_configured: true, jellyfin_available: false });
    });
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
      console.warn("Serienanbieter nicht erreichbar:", e);
      status.textContent = "Anbieter derzeit nicht erreichbar";
      byId("series-detail-title").textContent = result.title;
      byId("series-desc").textContent = result.description || "Metadaten derzeit nicht verfügbar";
      const loading = root.querySelector("#series-tiles .series-loading");
      if (loading) loading.textContent = "Staffeln derzeit nicht verfügbar";
      byId("series-pick-count").textContent = "Keine Episoden verfügbar";
    }
    await metadataWork;
  }

  async function openWatchlistEntry(baseSlug) {
    switchTab("serien", { autoLoad: false });
    seriesState.browseRequestSeq += 1;
    seriesState.loadingBrowse = false;
    const owner = begin();
    const openGeneration = ++seriesState.viewGeneration;
    let detailGeneration = openGeneration;
    status.textContent = "Lade abonnierte Serie …";
    try {
      const series = await client.post("/api/watchlist/open", { base_slug: baseSlug }, { signal: owner.signal });
      if (!owner.active || seriesState.viewGeneration !== openGeneration) return;
      const preselect = series.preselect_slugs || [];
      delete series.preselect_slugs;
      showSeriesDetail(series, firstEpisodeSlug(series));
      detailGeneration = seriesState.viewGeneration;
      await verifyHuhuEpisodeLanguages(
        seriesEpisodes(series).filter(episode => preselect.includes(episode.slug)), series,
      );
      if (!owner.active || seriesState.viewGeneration !== detailGeneration) return;
      const liveSeries = seriesState.current;
      if (liveSeries?.base_slug !== baseSlug) return;
      const selectable = new Set(
        seriesEpisodes(liveSeries).filter(isEpisodeSelectable).map((episode) => episode.slug),
      );
      seriesState.epPicked = new Set(preselect.filter((slug) => selectable.has(slug)));
      renderSeriesTiles();
      await syncWatchlistSnapshot("Abo-Aktualisierung nach Öffnen");
    } catch (error) {
      if (!owner.active || seriesState.viewGeneration !== detailGeneration) return;
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
