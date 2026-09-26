import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Shared catalog enrichment. Requests belong to the session and optionally a view. */
export function createCatalogArtwork({
  client = api, getMovieMetadata = () => ({}), renderHome = () => {},
  saveHomeCache = () => {}, onSeriesHydrated = () => {},
} = {}) {
  let owner = createScope();
  function begin(signal) {
    const scope = createScope();
    const release = owner.add(() => scope.dispose());
    if (signal?.aborted) scope.dispose();
    else if (signal) scope.listen(signal, "abort", () => scope.dispose(), { once: true });
    return { scope, finish: release };
  }
  async function movies(items, { render = true, signal } = {}) {
    const request = begin(signal);
    if (!request.scope.active) { request.finish(); return; }
    try {
      const targets = [
        ...new Map(
          items
            .filter((item) => {
              if (!item?.slug) return false;
              const known = { ...item, ...(getMovieMetadata()[item.slug] || {}) };
              return known.catalog_identity_version !== 2
                || !known.cover_url || !known.backdrop_url
                || !Array.isArray(known.genres) || !known.genres.length;
            })
            .map((item) => [item.slug, item]),
        ).values(),
      ];
      if (!targets.length) return;
      try {
        const response = await client.post("/api/tmdb/movies", { items: targets.map((item) => ({
          slug: item.slug,
          title: item.title,
          year: item.year || "",
        })), background: true }, { signal: request.scope.signal });
        if (!request.scope.active) return;
        for (const [slug, metadata] of Object.entries(response.movies || {})) {
          if (metadata) {
            getMovieMetadata()[slug] = { ...(getMovieMetadata()[slug] || {}), ...metadata };
          }
        }
        if (render) renderHome();
      } catch (error) {
        if (request.scope.active) console.warn("Startseitenbilder konnten nicht ergänzt werden:", error);
      }
    } finally { request.finish(); }
  }

  const HOME_SERIES_ARTWORK_BATCH_SIZE = 8;
  const HOME_SERIES_ARTWORK_MAX_PASSES = 3;

  async function series(items, { render = true, signal } = {}) {
    const request = begin(signal);
    if (!request.scope.active) { request.finish(); return []; }
    try {
      const groups = new Map();
      items.filter((item) => item?.base_slug).forEach((item) => {
        if (!groups.has(item.base_slug)) groups.set(item.base_slug, []);
        groups.get(item.base_slug).push(item);
      });
      const targets = [];
      groups.forEach((variants, baseSlug) => {
        const sharedCover = variants.find((item) => item.cover_url)?.cover_url || "";
        const sharedBackdrop = variants.find((item) => item.backdrop_url)?.backdrop_url || "";
        const sharedGenres = variants.find((item) => Array.isArray(item.genres) && item.genres.length)?.genres || [];
        variants.forEach((item) => {
          if (!item.cover_url && sharedCover) item.cover_url = sharedCover;
          if (!item.backdrop_url && sharedBackdrop) item.backdrop_url = sharedBackdrop;
          if (item.metadata_policy !== "provider_authoritative" && (!Array.isArray(item.genres) || !item.genres.length) && sharedGenres.length) {
            item.genres = sharedGenres.slice();
          }
        });
        if (variants.some((item) => (
          !item.cover_url
          || !item.backdrop_url
          || !Array.isArray(item.genres)
          || !item.genres.length
        ))) {
          const representative = variants[0];
          targets.push({
            base_slug: baseSlug,
            title: representative.title,
            year: representative.year || "",
            variants,
          });
        }
      });
      if (!targets.length) return [];
      const hydratedBaseSlugs = new Set();
      for (let index = 0; index < targets.length; index += HOME_SERIES_ARTWORK_BATCH_SIZE) {
        const batch = targets.slice(index, index + HOME_SERIES_ARTWORK_BATCH_SIZE);
        let pendingTargets = batch;
        for (let pass = 0; pendingTargets.length && pass < HOME_SERIES_ARTWORK_MAX_PASSES; pass += 1) {
          if (!request.scope.active) return [];
          let response;
          try {
            response = await client.post("/api/tmdb/series", { items: pendingTargets.map((target) => ({
              base_slug: target.base_slug,
              title: target.title,
              year: target.year,
            })) }, { signal: request.scope.signal });
            if (!request.scope.active) return [];
          } catch (error) {
            if (request.scope.active) console.warn("Serien-Wallpaper konnten nicht ergänzt werden:", error);
            break;
          }
          let repainted = false;
          for (const target of pendingTargets) {
            const metadata = response.series?.[target.base_slug];
            if (!metadata) continue;
            let hydrated = false;
            target.variants.forEach((item) => {
              const hadCover = Boolean(item.cover_url);
              const hadBackdrop = Boolean(item.backdrop_url);
              Object.assign(item, item.metadata_policy === "provider_authoritative" ? {} : metadata, {
                cover_url: metadata.cover_url || item.cover_url || "",
                backdrop_url: metadata.backdrop_url || item.backdrop_url || "",
              });
              if ((!hadCover && item.cover_url) || (!hadBackdrop && item.backdrop_url)) {
                hydrated = true;
              }
            });
            if (hydrated) {
              hydratedBaseSlugs.add(target.base_slug);
              repainted = true;
            }
          }
          if (repainted) {
            saveHomeCache();
            if (render) renderHome();
          }
          const pending = new Set(Array.isArray(response.pending) ? response.pending : []);
          pendingTargets = pendingTargets.filter((target) => pending.has(target.base_slug));
        }
      }
      return [...hydratedBaseSlugs];
    } finally {
      try { if (request.scope.active) onSeriesHydrated(); }
      finally { request.finish(); }
    }
  }

  return { movies, series, unmount() { owner.dispose(); }, mount() { if (!owner.active) owner = createScope(); } };
}
