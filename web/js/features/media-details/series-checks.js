import { api } from "../../core/api.js";
import { createEpisodeProbeProgress } from "./series-probe-progress.js";
import { delay } from "../../core/lifecycle.js";
import { createScope } from "../../core/lifecycle.js";
import { loadSeriesDetails } from "./series-api.js";

export function createSeriesChecks(status, {
  seriesState, isVisible, firstEpisodeSlug, pruneSeriesEpisodeSelection, refreshSeriesTileStates,
  updateSeriesStatus, syncSeriesQueueFlags, seriesStructureFingerprint, mergeSeriesDetailPayload,
  updateSeriesOverview, updateWatchBtn, renderSeriesTiles, client = api, retryDelays = [1000, 5000], languageConcurrency = 2,
}) {
  let refreshScope = null, refreshSequence = 0;
  const refreshByBase = new Map(), languageJobs = new Set(), languagePendingSlugs = new Map();
  const languageQueue = [];
  const activeLanguageJobs = new Set();
  const progress = createEpisodeProbeProgress(status);
  let progressGeneration = -1;

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
    while (activeLanguageJobs.size < languageConcurrency && languageQueue.length) {
      const job = languageQueue.shift();
      activeLanguageJobs.add(job);
      job.run().then(job.resolve, job.reject).finally(() => {
        for (const key of job.keys) {
          if (languagePendingSlugs.get(key) === job) languagePendingSlugs.delete(key);
        }
        job.owner.dispose(); languageJobs.delete(job.owner);
        activeLanguageJobs.delete(job);
        runNextLanguageJob();
      });
    }
  }

  async function verifyHuhuEpisodeLanguages(episodes, series = seriesState.current, { background = false } = {}) {
    if (!series || !providerNeedsExactEpisodeLanguage(series)) return;
    if (!isVisible()) throw new DOMException("Abgebrochen", "AbortError");
    const generation = seriesState.viewGeneration;
    if (progressGeneration !== generation) { progress.reset(); progressGeneration = generation; }
    const baseSlug = series.base_slug;
    const keyFor = episode => `${generation}:${series.provider}:${episode.slug}`;
    const requested = episodes.filter(episode => (
      !episode.downloaded && !episode.in_jellyfin && !episode.unreleased
      && episode.language_checked !== true && episode.huhu_language_checked !== true
    ));
    // A new detail view must not sit behind a cancelled provider request.
    for (const job of activeLanguageJobs) {
      if (job.generation !== generation) { job.owner.dispose(); activeLanguageJobs.delete(job); }
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
        let remaining = [...chunk];
        let lastError = null;
        const negativeEvidence = new Map();
        for (let attempt = 0; attempt < 3 && remaining.length; attempt++) {
          const current = () => owner.active && generation === seriesState.viewGeneration
            && seriesState.current?.base_slug === baseSlug && seriesState.current?.provider === series.provider && isVisible();
          if (!current()) throw new DOMException("Abgebrochen", "AbortError");
          const probeId = globalThis.crypto?.randomUUID?.() || `probe-${Date.now()}-${Math.random().toString(36).slice(2)}`;
          const initial = [{provider: series.provider, label: series.provider_label || series.provider, status: "checking"}];
          const renderProgress = (providers = initial, state = "checking") => {
            if (current()) progress.render({episodes: chunk, attempt, providers,
              batchKey: `${generation}:${chunk[0].slug}`, queued: languageQueue.reduce((total, next) => total + next.keys.length, 0),
              state, remaining: remaining.length});
          };
          renderProgress();
          let polling = false, pollActive = true;
          const stopPolling = typeof client.get === "function" ? owner.interval(async () => {
            if (polling || !current()) return;
            polling = true;
            try {
              const snapshot = await client.get(`/api/series/episode-probe/${probeId}`, {signal: owner.signal, timeoutMs: 2000});
              if (pollActive && snapshot.providers?.length) renderProgress(snapshot.providers);
            } catch { /* The primary request remains authoritative if progress is unavailable. */ }
            finally { polling = false; }
          }, 750) : () => {};
          let providers = initial;
          try {
            const result = await client.post("/api/series/episode-languages", {
              provider: series.provider, slugs: remaining.map(episode => episode.slug), probe_id: probeId, attempt,
              title: series.title || "", aliases: [...new Set([...(series.aliases || []), series.original_title].filter(Boolean))].slice(0, 12), tmdb_id: series.tmdb_id || null,
            }, {signal: owner.signal, timeoutMs: 15_000,
              timeoutMessage: "Die Sprachprüfung antwortet gerade nicht."});
            if (!current()) throw new DOMException("Abgebrochen", "AbortError");
            providers = result.progress?.length ? result.progress : initial.map(row => ({...row, status: "checked"}));
            const liveEpisodes = new Map((seriesState.current.seasons || []).flatMap(season => season.episodes || []).map(episode => [episode.slug, episode]));
            remaining = remaining.filter(episode => {
              const languages = result.languages?.[episode.slug];
              const known = Array.isArray(languages) && languages.length > 0
                && typeof result.available?.[episode.slug] === "boolean" && !result.pending?.includes(episode.slug);
              // Positive evidence is immediate. A negative needs a fresh second
              // request; incomplete responses never become a permanent lock.
              const fingerprint = known ? [...languages].sort().join(",") : "";
              const checked = known && (result.available[episode.slug]
                || negativeEvidence.get(episode.slug) === fingerprint);
              if (known && !result.available[episode.slug]) negativeEvidence.set(episode.slug, fingerprint);
              for (const target of new Set([episode, liveEpisodes.get(episode.slug)])) {
                if (!target) continue;
                target.language_check_error = !checked;
                if (!checked) continue;
                target.language_checked = true;
                target.language_available = result.available[episode.slug];
                target.huhu_language_checked = true;
                target.huhu_language_available = target.language_available;
                target.content_languages = languages;
                target.source_providers = result.source_providers?.[episode.slug] || [series.provider];
              }
              return !checked;
            });
            lastError = null;
            pruneSeriesEpisodeSelection?.();
            if (refreshSeriesTileStates) refreshSeriesTileStates(); else renderSeriesTiles();
          } catch (error) {
            if (!current()) throw new DOMException("Abgebrochen", "AbortError");
            lastError = error;
          } finally { pollActive = false; stopPolling(); }
          renderProgress(providers, remaining.length ? attempt < 2 ? "retry" : "incomplete" : "complete");
          if (remaining.length && attempt < 2) await delay(retryDelays[attempt], owner.signal);
        }
        if (remaining.length) {
          const liveEpisodes = new Map((seriesState.current.seasons || []).flatMap(season => season.episodes || []).map(episode => [episode.slug, episode]));
          for (const episode of remaining) {
            episode.language_check_error = true;
            if (liveEpisodes.has(episode.slug)) liveEpisodes.get(episode.slug).language_check_error = true;
          }
          if (refreshSeriesTileStates) refreshSeriesTileStates(); else renderSeriesTiles();
          if (lastError) throw lastError;
        }
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
    if (!background && requested.length) progress.reveal();
    const results = await Promise.allSettled([...waiting].map(job => job.promise));
    const failed = results.find(result => result.status === "rejected");
    if (failed && generation === seriesState.viewGeneration) {
      progress.render({episodes: requested, attempt: 2, state: "incomplete", remaining: requested.filter(ep => !ep.language_checked && !ep.huhu_language_checked).length});
    }
    if (failed) throw failed.reason;
    if (requested.some(episode => episode.language_check_error)) {
      progress.render({episodes: requested.filter(ep => ep.language_check_error), attempt: 2, state: "incomplete", remaining: requested.filter(ep => ep.language_check_error).length});
      throw new Error("Einige Episodensprachen konnten nicht geladen werden. Bitte erneut auswählen.");
    }
  }

  return {
    refresh: refreshSeriesJellyfinStatus, verifyLanguages: verifyHuhuEpisodeLanguages,
    unmount() {
      progress.reset();
      refreshScope?.dispose(); refreshScope = null; refreshByBase.clear();
      for (const job of languageJobs) job.dispose();
      languageJobs.clear();
      languagePendingSlugs.clear();
      for (const job of languageQueue.splice(0)) job.reject(new DOMException("Abgebrochen", "AbortError"));
      activeLanguageJobs.clear();
    },
  };
}
