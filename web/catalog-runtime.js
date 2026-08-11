const CATALOG_REFRESH_INTERVAL_MS = 60 * 1000;
let fpCatalogRefreshPromise = null;
let seriesCatalogRefreshPromise = null;

const resultPosterObserver = typeof IntersectionObserver === "function"
  ? new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      resultPosterObserver.unobserve(entry.target);
      entry.target.__loadResultPoster?.();
    }
  }, { root: null, rootMargin: "4200px 1200px", threshold: 0.01 })
  : null;

function scheduleResultPoster(image, coverCandidates) {
  let coverIndex = 0;
  const load = () => {
    if (image.src || !coverCandidates[coverIndex]) return;
    image.loading = "eager";
    image.fetchPriority = "auto";
    image.src = coverCandidates[coverIndex];
  };
  image.__loadResultPoster = load;
  image.addEventListener("error", () => {
    coverIndex += 1;
    image.removeAttribute("src");
    if (coverIndex < coverCandidates.length) load();
    else image.remove();
  });
  if (resultPosterObserver) resultPosterObserver.observe(image);
  else load();
}

function discardObservedResultPosters(container) {
  if (!resultPosterObserver || !container) return;
  container.querySelectorAll(".result-card-poster").forEach((image) => {
    resultPosterObserver.unobserve(image);
  });
}

function mergeFpMetadata(existing = {}, incoming = {}) {
  const merged = existing.details_loaded && !incoming.details_loaded
    ? { ...incoming, ...existing }
    : { ...existing, ...incoming };
  merged.cover_url = incoming.cover_url || existing.cover_url || "";
  merged.backdrop_url = incoming.backdrop_url || existing.backdrop_url || "";
  return merged;
}

function fpMetadataPreloadItems(results) {
  return results
    .filter((result) => {
      const metadata = state.fp.metadataCache[result.slug];
      return !metadata?.cover_url
        || !metadata?.backdrop_url
        || metadata?.metadata_source !== "TMDB";
    })
    .map((result) => ({
      slug: result.slug,
      title: result.title,
      year: result.year || "",
      tmdb_id: result.tmdb_id || state.fp.metadataCache[result.slug]?.tmdb_id || null,
    }));
}

async function preloadTmdbMetadata(requestId, items, { attempts = 2 } = {}) {
  if (!items.length) {
    state.fp.pendingPreload = null;
    return;
  }
  const visibleSlugs = new Set(items.map((item) => item.slug));
  const batches = [];
  for (let index = 0; index < items.length; index += FP_METADATA_BATCH_SIZE) {
    batches.push(items.slice(index, index + FP_METADATA_BATCH_SIZE));
  }
  let nextBatch = 0;

  const loadNextBatch = async () => {
    while (nextBatch < batches.length) {
      const batch = batches[nextBatch++];
      const unresolved = new Map(batch.map((item) => [item.slug, item]));
      const maxAttempts = Math.max(1, Math.min(2, Number(attempts) || 1));
      for (let attempt = 0; attempt < maxAttempts && unresolved.size; attempt += 1) {
        let response;
        try {
          response = await api.tmdbMovies([...unresolved.values()]);
        } catch (e) {
          if (requestId !== state.fp.metadataRequestSeq) return;
          if (attempt + 1 < maxAttempts) {
            await new Promise((resolve) => setTimeout(resolve, 700));
            continue;
          }
          break;
        }
        if (requestId !== state.fp.metadataRequestSeq) return;
        for (const [slug, metadata] of Object.entries(response.movies || {})) {
          if (!visibleSlugs.has(slug)) continue;
          state.fp.metadataCache[slug] = mergeFpMetadata(
            state.fp.metadataCache[slug], metadata,
          );
          unresolved.delete(slug);
          state.fp.pendingPreload?.delete(slug);
          updateFpResultCard(slug);
        }
        if (unresolved.size && attempt + 1 < maxAttempts) {
          await new Promise((resolve) => setTimeout(resolve, 700));
        }
      }
      for (const item of batch) state.fp.pendingPreload?.delete(item.slug);
      refreshMovieFeatureCandidates();
      const selected = state.fp.selectedSlug;
      if (selected && batch.some((item) => item.slug === selected)
          && !state.fp.moviesCache[selected] && state.fp.metadataCache[selected]) {
        showFpDetail(selected, metadataPreviewMovie(state.fp.metadataCache[selected]), true);
      }
    }
  };

  try {
    const workerCount = Math.min(FP_METADATA_BATCH_CONCURRENCY, batches.length);
    await Promise.all(Array.from({ length: workerCount }, () => loadNextBatch()));
    if (requestId !== state.fp.metadataRequestSeq) return;
    refreshFpJellyfinStatus();
  } catch (e) { /* Anbieter-Metadaten bleiben als Fallback sichtbar. */ }
  finally {
    if (requestId !== state.fp.metadataRequestSeq) return;
    for (const slug of visibleSlugs) updateFpResultCard(slug);
    if (state.fp.pendingPreload && state.fp.pendingPreload.size === 0) {
      state.fp.pendingPreload = null;
    }
    refreshMovieFeatureCandidates();
  }
}

async function preloadFpPosterImages(results, maxWaitMs = 3500) {
  let next = 0;
  const warmOne = (result) => {
    const candidates = api.coverThumbnailCandidates(fpResultMedia(result)?.cover_url);
    if (!candidates.length) return Promise.resolve();
    return new Promise((resolve) => {
      const image = new Image();
      let index = 0;
      const finish = () => resolve();
      const load = () => {
        if (!candidates[index]) return finish();
        image.src = candidates[index];
      };
      image.onload = async () => {
        try { await image.decode(); } catch (e) { /* bereits im Browser-Cache */ }
        finish();
      };
      image.onerror = () => {
        index += 1;
        load();
      };
      load();
    });
  };
  const worker = async () => {
    while (next < results.length) {
      const result = results[next++];
      await warmOne(result);
    }
  };
  const workers = Array.from(
    { length: Math.min(6, results.length) }, () => worker(),
  );
  let timer;
  await Promise.race([
    Promise.allSettled(workers),
    new Promise((resolve) => { timer = setTimeout(resolve, maxWaitMs); }),
  ]).finally(() => clearTimeout(timer));
}

async function preloadSeriesPosterImages(results, maxWaitMs = 3500) {
  let next = 0;
  const warmOne = (result) => {
    const candidates = api.coverThumbnailCandidates(result?.cover_url);
    if (!candidates.length) return Promise.resolve();
    return new Promise((resolve) => {
      const image = new Image();
      let index = 0;
      const finish = () => resolve();
      const load = () => {
        if (!candidates[index]) return finish();
        image.src = candidates[index];
      };
      image.onload = async () => {
        try { await image.decode(); } catch (e) { /* bereits im Browser-Cache */ }
        finish();
      };
      image.onerror = () => {
        index += 1;
        load();
      };
      load();
    });
  };
  const worker = async () => {
    while (next < results.length) {
      const result = results[next++];
      await warmOne(result);
    }
  };
  const workers = Array.from(
    { length: Math.min(6, results.length) }, () => worker(),
  );
  let timer;
  await Promise.race([
    Promise.allSettled(workers),
    new Promise((resolve) => { timer = setTimeout(resolve, maxWaitMs); }),
  ]).finally(() => clearTimeout(timer));
}

function syncFpCatalogFromHome({ fresh = false } = {}) {
  if (state.fp.searchActive || (state.fp.category && state.fp.category !== "new")) return false;
  const incoming = Array.isArray(state.home.newMovies) ? state.home.newMovies : [];
  if (
    !incoming.length || (!fresh && state.fp.results.length)
    || (fresh && state.fp.results.length && !state.fp.previewFromHome)
  ) return false;
  state.fp.results = incoming.slice();
  state.fp.category = "new";
  state.fp.page = 1;
  state.fp.lastPageFull = true;
  state.fp.loadingMore = false;
  state.fp.loadError = "";
  state.fp.previewFromHome = !fresh;
  if (fresh) state.fp.lastCatalogRefreshAt = Date.now();
  for (const result of incoming) {
    if (result?.tmdb_id) state.fp.metadataCache[result.slug] = mergeFpMetadata(
      state.fp.metadataCache[result.slug], result,
    );
  }
  const metadataItems = fpMetadataPreloadItems(incoming);
  if (metadataItems.length) {
    state.fp.pendingPreload = state.fp.pendingPreload || new Set();
    for (const item of metadataItems) state.fp.pendingPreload.add(item.slug);
    void preloadTmdbMetadata(state.fp.metadataRequestSeq, metadataItems);
  }
  if (state.tab === "filme") {
    renderFpResults();
    refreshMovieFeatureCandidates();
    updateFpInfiniteState();
    recheckFpInfinite();
  }
  return true;
}

function refreshFpCatalogInBackground() {
  const stillFresh = Date.now() - state.fp.lastCatalogRefreshAt < CATALOG_REFRESH_INTERVAL_MS;
  if (stillFresh || fpCatalogRefreshPromise || state.fp.searchActive || state.fp.category !== "new") return;
  fpCatalogRefreshPromise = api.movies({ mode: "new", page: 1 })
    .then((data) => {
      if (state.fp.searchActive || state.fp.category !== "new" || state.fp.page > 1) return;
      state.fp.previewFromHome = false;
      state.fp.lastCatalogRefreshAt = Date.now();
      applyFpResults(data);
    })
    .catch((error) => console.warn("Filmkatalog konnte nicht im Hintergrund aktualisiert werden:", error))
    .finally(() => { fpCatalogRefreshPromise = null; });
}

function syncSeriesCatalogFromHome({ fresh = false } = {}) {
  if (state.series.browseMode && state.series.browseMode !== "discover") return false;
  const incoming = Array.isArray(state.home.discoverySeries) ? state.home.discoverySeries : [];
  if (
    !incoming.length || (!fresh && state.series.results.length)
    || (fresh && state.series.results.length && !state.series.previewFromHome)
  ) return false;
  state.series.results = incoming.slice();
  state.series.browseMode = "discover";
  state.series.page = 1;
  state.series.lastPageFull = true;
  state.series.loadingBrowse = false;
  state.series.loadError = "";
  state.series.previewFromHome = !fresh;
  if (fresh) state.series.lastCatalogRefreshAt = Date.now();
  if (state.tab === "serien") {
    renderSeriesResults();
    renderSeriesCatalogHero();
    updateSeriesInfiniteState();
    recheckSeriesInfinite();
  }
  return true;
}

function refreshSeriesCatalogInBackground() {
  const stillFresh = Date.now() - state.series.lastCatalogRefreshAt < CATALOG_REFRESH_INTERVAL_MS;
  if (
    stillFresh || seriesCatalogRefreshPromise || state.series.loadingBrowse
    || state.series.browseMode !== "discover"
  ) return;
  seriesCatalogRefreshPromise = api.series({ mode: "discover", page: 1 })
    .then((data) => {
      if (state.series.browseMode !== "discover" || state.series.page > 1) return;
      state.series.previewFromHome = false;
      state.series.lastCatalogRefreshAt = Date.now();
      applySeriesResults(data);
    })
    .catch((error) => console.warn("Serienkatalog konnte nicht im Hintergrund aktualisiert werden:", error))
    .finally(() => { seriesCatalogRefreshPromise = null; });
}
