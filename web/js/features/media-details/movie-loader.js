import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { mergeDetailMetadata } from "./metadata.js";
import { fetchMovieAvailability, freshMovieAvailability } from "./movie-availability.js";

/** A dialog owns independent metadata, library and provider requests. */
export function createMovieDetailsLoader({
  movieState, updateFpResultSelection, homeMovieBySlug, trackDiscoveryPreference, showFpDetail,
  basicMovieMetadata, setFpDetailAvailability, openMediaModal,
  findFpResultCard, updateFpResultCard, refreshMovieFeatureCandidates, refreshFpJellyfinStatus,
  client = api, resolveAvailability = fetchMovieAvailability,
}) {
  let scope = null;
  async function selectFpRow(slug, initialItem = null) {
    scope?.dispose();
    const owner = createScope();
    scope = owner;
    const current = () => scope === owner && owner.active && movieState.selectedSlug === slug;
    const item = initialItem || movieState.results.find(r => r.slug === slug) || homeMovieBySlug(slug);
    if (!item) { owner.dispose(); return; }
    movieState.selectedSlug = slug;
    updateFpResultSelection();
    let metadata = mergeDetailMetadata(basicMovieMetadata({ ...item, slug }), movieState.metadataCache[slug]);
    const cached = movieState.moviesCache[slug];
    let provider = freshMovieAvailability(cached) ? cached : null;
    if (cached && !provider) {
      delete movieState.moviesCache[slug];
      updateFpResultCard(slug);
    }
    const detail = { slug, metadataState: metadata.details_loaded ? "ready" : "loading",
      availabilityState: provider ? (provider.hosters?.length ? "available" : "unavailable") : "checking" };
    movieState.detail = detail;
    const render = () => {
      if (!current()) return;
      // Provider fields own availability; nonempty TMDB fields own presentation.
      const movie = { ...(metadata.details_loaded
        ? mergeDetailMetadata(provider || {}, metadata) : mergeDetailMetadata(metadata, provider)),
        hosters: provider?.hosters || [], hoster_route: provider?.hoster_route || "Derzeit nicht verfügbar",
        availability: detail.availabilityState === "pending" ? { state: "pending", complete: false } : provider?.availability };
      if (provider || detail.availabilityState === "pending") movieState.moviesCache[slug] = movie;
      showFpDetail(slug, movie, detail.availabilityState === "checking");
      if (detail.availabilityState === "failed") setFpDetailAvailability("Anbieter derzeit nicht erreichbar", "error");
      else if (detail.availabilityState === "pending") setFpDetailAvailability("Quellenprüfung noch offen · Erneut prüfen möglich", "error");
      else if (detail.availabilityState === "unavailable") setFpDetailAvailability("Derzeit nicht verfügbar", "ready");
    };
    movieState.metadataCache[slug] = metadata;
    trackDiscoveryPreference("movie", metadata, 0.8, "open");
    render();
    openMediaModal("fp-detail-modal", findFpResultCard(slug));
    async function loadMetadata() {
      if (metadata.details_loaded) return;
      try {
        const response = await client.post("/api/tmdb/movie", {
          slug, title: item.title, year: item.year || "", tmdb_id: metadata.tmdb_id || null,
        }, { signal: owner.signal, timeoutMs: 12_000 });
        if (!current()) return;
        metadata = mergeDetailMetadata(metadata, response.movie);
        detail.metadataState = response.movie ? "ready" : "failed";
        movieState.metadataCache[slug] = metadata;
        updateFpResultCard(slug);
        refreshMovieFeatureCandidates();
      } catch (error) {
        if (!current()) return;
        detail.metadataState = "failed";
        console.warn("Filmmetadaten nicht erreichbar:", error);
      }
      render();
    }
    async function loadProvider() {
      if (provider && provider.availability?.complete !== false) return;
      const initialId = Number(metadata.tmdb_id) || 0;
      const deadline = Date.now() + 60_000;
      const apply = resolved => {
        if (!current()) return;
        if (resolved.hosters?.length || resolved.availability?.complete !== false) {
          provider = resolved;
          movieState.moviesCache[slug] = resolved;
          detail.availabilityState = resolved.hosters?.length ? "available" : "unavailable";
          updateFpResultCard(slug);
          render();
        } else if (!provider?.hosters?.length && resolved.availability?.state === "retrying") {
          setFpDetailAvailability("Quellen vorübergehend nicht erreichbar · Prüfe erneut …", "loading");
        }
      };
      const requestProvider = tmdbId => resolveAvailability({ client, slug,
        tmdbId: () => Number(metadata.tmdb_id) || tmdbId, signal: owner.signal,
        budgetMs: Math.max(1, deadline - Date.now()), onUpdate: apply });
      try {
        let resolved;
        try { resolved = await requestProvider(initialId); }
        catch (error) {
          // A provider-only catalog hit may learn its TMDB identity later.
          // Preserve cross-provider fallback without serializing Similar clicks.
          if (initialId || !current()) throw error;
          await metadataWork;
          if (!current() || !Number(metadata.tmdb_id) || Date.now() >= deadline) throw error;
          resolved = await requestProvider(Number(metadata.tmdb_id));
        }
        if (!current()) return;
        apply(resolved);
      } catch (error) {
        if (!current()) return;
        if (!provider?.hosters?.length) detail.availabilityState = error.code === "movie_hoster_unavailable" ? "unavailable"
          : ["movie_probe_pending", "movie_provider_unavailable", "request_timeout", "network_error", "invalid_json"].includes(error.code) ? "pending" : "failed";
        console.warn("Anbietersuche fehlgeschlagen:", error);
      }
      render();
    }
    // The catalog service owns library state and its 15-second timeout.
    const library = refreshFpJellyfinStatus([metadata], { signal: owner.signal });
    const metadataWork = loadMetadata();
    await Promise.all([metadataWork, loadProvider(), library]);
  }
  return { open: selectFpRow, unmount() { scope?.dispose(); scope = null; movieState.detail = null; } };
}
