import { api } from "../../core/api.js";
import { createScope, delay } from "../../core/lifecycle.js";

const FP_METADATA_BATCH_SIZE = 12;
const FP_METADATA_BATCH_CONCURRENCY = 3;

export function mergeFpMetadata(existing = {}, incoming = {}) {
  const merged = existing.details_loaded && !incoming.details_loaded
    ? { ...incoming, ...existing }
    : { ...existing, ...incoming };
  merged.cover_url = incoming.cover_url || existing.cover_url || "";
  merged.backdrop_url = incoming.backdrop_url || existing.backdrop_url || "";
  return merged;
}

export function createCatalogMetadata({
  movieState, updateFpResultCard, refreshFpJellyfinStatus, refreshMovieFeatureCandidates,
  showFpDetail, metadataPreviewMovie, reconcileMovieCatalogDuplicates, client = api,
}) {
  const pending = new Set();
  function fpMetadataPreloadItems(results) {
    return results
      .filter((result) => {
        const metadata = movieState.metadataCache[result.slug];
        return !metadata?.cover_url
          || !metadata?.backdrop_url
          || metadata?.metadata_source !== "TMDB";
      })
      .map((result) => ({
        slug: result.slug,
        title: result.title,
        year: result.year || "",
        tmdb_id: result.tmdb_id || movieState.metadataCache[result.slug]?.tmdb_id || null,
      }));
  }

  async function preloadTmdbMetadata(requestId, items, { attempts = 2 } = {}) {
    if (requestId !== movieState.metadataRequestSeq) return;
    for (const job of pending) if (job.requestId !== requestId) job.scope.dispose();
    if (!items.length) {
      movieState.pendingPreload = null;
      return;
    }
    const scope = createScope();
    const job = { requestId, scope };
    pending.add(job);
    const current = () => scope.active && requestId === movieState.metadataRequestSeq;
    const visibleSlugs = new Set(items.map((item) => item.slug));
    const batches = [];
    for (let index = 0; index < items.length; index += FP_METADATA_BATCH_SIZE) {
      batches.push(items.slice(index, index + FP_METADATA_BATCH_SIZE));
    }
    let nextBatch = 0;

    const loadNextBatch = async () => {
      while (current() && nextBatch < batches.length) {
        const batch = batches[nextBatch++];
        const unresolved = new Map(batch.map((item) => [item.slug, item]));
        const maxAttempts = Math.max(1, Math.min(2, Number(attempts) || 1));
        for (let attempt = 0; attempt < maxAttempts && unresolved.size; attempt += 1) {
          let response;
          try {
            response = await client.post("/api/tmdb/movies", { items: [...unresolved.values()], background: false }, { signal: scope.signal });
          } catch (e) {
            if (!current()) return;
            if (attempt + 1 < maxAttempts) {
              await delay(700, scope.signal);
              continue;
            }
            break;
          }
          if (!current()) return;
          for (const [slug, metadata] of Object.entries(response.movies || {})) {
            if (!visibleSlugs.has(slug)) continue;
            movieState.metadataCache[slug] = mergeFpMetadata(
              movieState.metadataCache[slug], metadata,
            );
            unresolved.delete(slug);
            movieState.pendingPreload?.delete(slug);
            updateFpResultCard(slug);
          }
          if (unresolved.size && attempt + 1 < maxAttempts) {
            await delay(700, scope.signal);
          }
        }
        if (!current()) return;
        for (const item of batch) movieState.pendingPreload?.delete(item.slug);
        const refreshedSlugs = new Set(batch.map((item) => item.slug));
        void refreshFpJellyfinStatus(
          movieState.results.filter((item) => refreshedSlugs.has(item.slug)),
        );
        refreshMovieFeatureCandidates();
        const selected = movieState.selectedSlug;
        if (selected && batch.some((item) => item.slug === selected)
            && movieState.detail?.slug !== selected
            && !movieState.moviesCache[selected] && movieState.metadataCache[selected]) {
          showFpDetail(selected, metadataPreviewMovie(movieState.metadataCache[selected]), true);
        }
      }
    };

    try {
      const workerCount = Math.min(FP_METADATA_BATCH_CONCURRENCY, batches.length);
      await Promise.all(Array.from({ length: workerCount }, () => loadNextBatch()));
      if (!current()) return;
    } catch (e) { /* Anbieter-Metadaten bleiben als Fallback sichtbar. */ }
    finally {
      pending.delete(job);
      const accept = current();
      scope.dispose();
      if (!accept) return;
      for (const slug of visibleSlugs) updateFpResultCard(slug);
      if (movieState.pendingPreload && movieState.pendingPreload.size === 0) {
        movieState.pendingPreload = null;
      }
      refreshMovieFeatureCandidates();
      reconcileMovieCatalogDuplicates();
    }
  }

  return {
    merge: mergeFpMetadata, items: fpMetadataPreloadItems, preload: preloadTmdbMetadata,
    resume() {
      const items = fpMetadataPreloadItems(movieState.results);
      if (!items.length) return;
      movieState.pendingPreload = new Set(items.map(item => item.slug));
      void preloadTmdbMetadata(movieState.metadataRequestSeq, items);
    },
    unmount() {
      for (const job of pending) job.scope.dispose();
      pending.clear();
      movieState.pendingPreload = null;
    },
  };
}
