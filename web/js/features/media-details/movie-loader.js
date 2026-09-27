import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { mergeDetailMetadata } from "./metadata.js";

/** A dialog owns independent metadata, library and provider requests. */
export function createMovieDetailsLoader({
  movieState, updateFpResultSelection, homeMovieBySlug, trackDiscoveryPreference, showFpDetail,
  basicMovieMetadata, setFpDetailAvailability, openMediaModal,
  findFpResultCard, updateFpResultCard, refreshMovieFeatureCandidates, refreshFpJellyfinStatus,
  client = api,
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
    let provider = movieState.moviesCache[slug];
    const detail = { slug, metadataState: metadata.details_loaded ? "ready" : "loading",
      availabilityState: provider ? (provider.hosters?.length ? "available" : "unavailable") : "checking" };
    movieState.detail = detail;
    const render = () => {
      if (!current()) return;
      // Provider fields own availability; nonempty TMDB fields own presentation.
      const movie = { ...(metadata.details_loaded
        ? mergeDetailMetadata(provider || {}, metadata) : mergeDetailMetadata(metadata, provider)),
        hosters: provider?.hosters || [], hoster_route: provider?.hoster_route || "Derzeit nicht verfügbar" };
      if (provider) movieState.moviesCache[slug] = movie;
      showFpDetail(slug, movie, detail.availabilityState === "checking");
      if (detail.availabilityState === "failed") setFpDetailAvailability("Anbieter derzeit nicht erreichbar", "error");
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
      if (provider) return;
      try {
        const query = Number(metadata.tmdb_id) > 0 ? `?${new URLSearchParams({ tmdb_id: String(metadata.tmdb_id) })}` : "";
        const resolved = await client.get(`/api/movie/${encodeURIComponent(slug)}${query}`, {
          signal: owner.signal, timeoutMs: 20_000,
        });
        if (!current()) return;
        provider = resolved;
        movieState.moviesCache[slug] = resolved;
        detail.availabilityState = resolved.hosters?.length ? "available" : "unavailable";
        updateFpResultCard(slug);
      } catch (error) {
        if (!current()) return;
        detail.availabilityState = error.code === "movie_hoster_unavailable" ? "unavailable" : "failed";
        console.warn("Anbietersuche fehlgeschlagen:", error);
      }
      render();
    }
    // The catalog service owns library state and its 15-second timeout.
    const library = refreshFpJellyfinStatus([metadata], { signal: owner.signal });
    await Promise.all([loadMetadata(), loadProvider(), library]);
  }
  return { open: selectFpRow, unmount() { scope?.dispose(); scope = null; movieState.detail = null; } };
}
