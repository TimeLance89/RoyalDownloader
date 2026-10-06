import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { loadSeriesDetails } from "./series-api.js";

export function createSeriesChecks(status, {
  seriesState, isVisible, firstEpisodeSlug, pruneSeriesEpisodeSelection, refreshSeriesTileStates,
  updateSeriesStatus, syncSeriesQueueFlags, seriesStructureFingerprint, mergeSeriesDetailPayload,
  updateSeriesOverview, updateWatchBtn, renderSeriesTiles, client = api,
}) {
  let refreshScope = null, refreshSequence = 0;
  const refreshByBase = new Map(), languageJobs = new Set(), languagePendingSlugs = new Map();
  const languageQueue = [];
  let activeLanguageJob = null;

  function providerNeedsExactEpisodeLanguage(series) {
    if (!series) return false;
    if (["huhu", "serienstream"].includes(series.provider)) return true;
    const capabilities = Array.isArray(series.provider_content_languages)
      ? series.provider_content_languages.filter(Boolean)
      : [];
    return capabilities.length > 1;
  }

  function publishedMissingLanguageEpisodes(series) {
    if (!providerNeedsExactEpisodeLanguage(series)) return [];
    return [...(series.seasons || [])]
      .sort((left, right) => Number(right.season || 0) - Number(left.season || 0))
      .flatMap((season) => [...(season.episodes || [])]
        .sort((left, right) => Number(left.episode || 0) - Number(right.episode || 0)))
      .filter((episode) => (
        !episode.unreleased
        && !episode.downloaded
        && !episode.in_jellyfin
        && episode.language_checked !== true
        && episode.huhu_language_checked !== true
      ));
  }
  async function refreshSeriesJellyfinStatus(force = false) {
    if (!isVisible()) return false;
    const current = seriesState.current;
    if (!current) return false;
    refreshScope?.dispose();
    const owner = createScope();
    refreshScope = owner;
    const baseSlug = current.base_slug;
    const sampleSlug = seriesState.currentSampleSlug || firstEpisodeSlug(current) || current.url;
    const viewGeneration = seriesState.viewGeneration;
    const refreshGeneration = ++refreshSequence;
    refreshByBase.set(baseSlug, refreshGeneration);
    const quickStatusPromise = client.post("/api/series/jellyfin-status", {
      title: current.title, tmdb_id: current.tmdb_id || null, aliases: current.aliases || [],
      episodes: (current.seasons || []).flatMap(season => (season.episodes || []).map(episode => ({
        slug: episode.slug, season: episode.season, episode: episode.episode,
      }))), force,
    }, { signal: owner.signal, timeoutMs: 15_000, timeoutMessage: "Die Jellyfin-Serienprüfung hat nicht rechtzeitig geantwortet." }).then((status) => {
      const isLatestForSeries = refreshByBase.get(baseSlug) === refreshGeneration;
      const isSameView = seriesState.viewGeneration === viewGeneration;
      if (!owner.active || !isLatestForSeries || !isSameView || seriesState.current?.base_slug !== baseSlug) return;
      const live = seriesState.current;
      for (const season of live.seasons || []) {
        for (const episode of season.episodes || []) {
          if (Object.hasOwn(status.episodes || {}, episode.slug)) {
            episode.in_jellyfin = Boolean(status.episodes[episode.slug]);
          }
        }
      }
      live.jellyfin_configured = Boolean(status.configured);
      live.jellyfin_pending = false;
      live.jellyfin_available = Boolean(status.available);
      live.jellyfin_stale = Boolean(status.stale);
      live.jellyfin_checked_at = Number(status.checked_at || 0);
      seriesState.cache[baseSlug] = live;
      pruneSeriesEpisodeSelection();
      refreshSeriesTileStates();
      updateSeriesStatus(live);
    }).catch((error) => {
      if (!owner.active) return false;
      console.warn("Schneller Jellyfin-Abgleich fehlgeschlagen:", error);
    });
    try {
      // Der gezielte Status oben übernimmt ein erzwungenes Live-Refresh. Das
      // vollständige Enrichment nutzt danach denselben Cache und lädt nicht
      // parallel erneut die komplette Jellyfin-Struktur.
      const refreshed = await loadSeriesDetails(client, sampleSlug, baseSlug, { signal: owner.signal });
      const isLatestForSeries = refreshByBase.get(baseSlug) === refreshGeneration;
      const isSameView = seriesState.viewGeneration === viewGeneration;
      if (!owner.active || !isLatestForSeries || !isSameView || seriesState.current?.base_slug !== baseSlug) return false;
      syncSeriesQueueFlags(refreshed);
      const previousStructure = seriesStructureFingerprint(seriesState.current);
      const enriched = mergeSeriesDetailPayload(seriesState.current || current, refreshed);
      seriesState.current = enriched;
      seriesState.cache[baseSlug] = enriched;
      pruneSeriesEpisodeSelection();
      updateSeriesOverview(enriched);
      updateWatchBtn();
      if (seriesStructureFingerprint(enriched) !== previousStructure) renderSeriesTiles();
      else refreshSeriesTileStates();
      updateSeriesStatus(enriched);

      // The first detail payload can be a lightweight/cache snapshot without
      // provider capability metadata. Re-run the latest published season after
      // hydration so exact language truth never depends on a user click.
      const languageEpisodes = publishedMissingLanguageEpisodes(enriched);
      if (languageEpisodes.length) {
        try {
          await verifyHuhuEpisodeLanguages(languageEpisodes, enriched, { background: true });
        } catch (error) {
          if (error.name !== "AbortError") {
            console.warn("Automatische Episoden-Sprachprüfung fehlgeschlagen:", error);
          }
        }
      }
      return true;
    } catch (error) {
      if (!owner.active) return false;
      console.warn("Serienstatus konnte nicht live aktualisiert werden:", error);
      const isLatestForSeries = refreshByBase.get(baseSlug) === refreshGeneration;
      const isSameView = seriesState.viewGeneration === viewGeneration;
      if (
        isLatestForSeries
        && isSameView
        && seriesState.current?.base_slug === baseSlug
        && seriesState.current.availability_pending
      ) {
        seriesState.current.availability_error = true;
        seriesState.cache[baseSlug] = seriesState.current;
        refreshSeriesTileStates();
        updateSeriesStatus(seriesState.current);
      }
      return false;
    } finally {
      await quickStatusPromise;
      owner.dispose();
      if (refreshScope === owner) refreshScope = null;
      if (refreshByBase.get(baseSlug) === refreshGeneration) {
        refreshByBase.delete(baseSlug);
      }
    }
  }

  function runNextLanguageJob() {
    if (activeLanguageJob || !languageQueue.length) return;
    const job = languageQueue.shift();
    activeLanguageJob = job;
    job.run().then(job.resolve, job.reject).finally(() => {
      for (const key of job.keys) {
        if (languagePendingSlugs.get(key) === job) languagePendingSlugs.delete(key);
      }
      job.owner.dispose();
      languageJobs.delete(job.owner);
      if (activeLanguageJob === job) activeLanguageJob = null;
      runNextLanguageJob();
    });
  }

  async function verifyHuhuEpisodeLanguages(episodes, series = seriesState.current, { background = false } = {}) {
    if (!series || !providerNeedsExactEpisodeLanguage(series)) return;
    if (!isVisible()) throw new DOMException("Abgebrochen", "AbortError");
    const generation = seriesState.viewGeneration;
    const baseSlug = series.base_slug;
    const keyFor = episode => `${generation}:${series.provider}:${episode.slug}`;
    const requested = episodes.filter(episode => (
      !episode.downloaded && !episode.in_jellyfin && !episode.unreleased
      && episode.language_checked !== true && episode.huhu_language_checked !== true
    ));
    // A new detail view must not sit behind a cancelled provider request.
    if (activeLanguageJob && activeLanguageJob.generation !== generation) {
      activeLanguageJob.owner.dispose();
      activeLanguageJob = null;
    }
    for (let i = languageQueue.length - 1; i >= 0; i--) {
      const job = languageQueue[i];
      if (job.generation !== generation) {
        languageQueue.splice(i, 1);
        job.reject(new DOMException("Abgebrochen", "AbortError"));
        job.owner.dispose();
        languageJobs.delete(job.owner);
        for (const key of job.keys) languagePendingSlugs.delete(key);
      }
    }
    const waiting = new Set(requested.map(episode => languagePendingSlugs.get(keyFor(episode))).filter(Boolean));
    const pending = requested.filter(episode => !languagePendingSlugs.has(keyFor(episode)));
    // Small serial probes publish results promptly without flooding the provider.
    for (let index = 0; index < pending.length; index += 4) {
      const chunk = pending.slice(index, index + 4);
      const owner = createScope();
      languageJobs.add(owner);
      const job = { owner, generation, keys: chunk.map(keyFor) };
      job.promise = new Promise((resolve, reject) => { job.resolve = resolve; job.reject = reject; });
      job.run = async () => {
        if (!owner.active) throw new DOMException("Abgebrochen", "AbortError");
        const result = await client.post("/api/series/episode-languages", {
          provider: series.provider, slugs: chunk.map(episode => episode.slug),
        }, { signal: owner.signal, timeoutMs: 15_000,
          timeoutMessage: "Die Sprachprüfung antwortet nicht. Bitte erneut auswählen." });
        const live = seriesState.current;
        if (!owner.active || generation !== seriesState.viewGeneration
            || live?.base_slug !== baseSlug || live?.provider !== series.provider) {
          throw new DOMException("Abgebrochen", "AbortError");
        }
        const liveEpisodes = new Map((live.seasons || []).flatMap(season => season.episodes || []).map(episode => [episode.slug, episode]));
        for (const episode of chunk) {
          for (const target of new Set([episode, liveEpisodes.get(episode.slug)])) {
            if (!target) continue;
            target.language_checked = true;
            target.language_available = result.available?.[episode.slug] === true;
            target.huhu_language_checked = true;
            target.huhu_language_available = target.language_available;
            target.content_languages = result.languages?.[episode.slug] || [];
          }
        }
        pruneSeriesEpisodeSelection?.();
        if (refreshSeriesTileStates) refreshSeriesTileStates();
        else renderSeriesTiles();
      };
      for (const key of job.keys) languagePendingSlugs.set(key, job);
      languageQueue.push(job);
      waiting.add(job);
    }
    // A click waits only for its own batches, and moves queued work ahead of
    // unrelated automatic checks. The active request remains shared.
    if (!background) languageQueue.sort((a, b) => Number(waiting.has(b)) - Number(waiting.has(a)));
    if (requested.length) status.textContent = `Prüfe Stream-Sprache für ${requested.length} Folge(n) …`;
    runNextLanguageJob();
    await Promise.all([...waiting].map(job => job.promise));
  }

  return {
    refresh: refreshSeriesJellyfinStatus, verifyLanguages: verifyHuhuEpisodeLanguages,
    unmount() {
      refreshScope?.dispose(); refreshScope = null; refreshByBase.clear();
      for (const job of languageJobs) job.dispose();
      languageJobs.clear();
      languagePendingSlugs.clear();
      for (const job of languageQueue.splice(0)) job.reject(new DOMException("Abgebrochen", "AbortError"));
      activeLanguageJob = null;
    },
  };
}
