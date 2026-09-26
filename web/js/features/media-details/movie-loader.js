import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** A selected movie owns both metadata and provider lookup until its dialog closes. */
export function createMovieDetailsLoader({
  movieState, updateFpResultSelection, homeMovieBySlug, trackDiscoveryPreference, showFpDetail,
  metadataPreviewMovie, basicMovieMetadata, setFpDetailAvailability, openMediaModal,
  findFpResultCard, updateFpResultCard, refreshMovieFeatureCandidates, refreshFpJellyfinStatus,
  client = api,
}) {
  let scope = null;
  const current = (owner, slug) => scope === owner && owner.active && movieState.selectedSlug === slug;
  async function loadFpMetadata(item, owner, requestId = movieState.requestSeq) {
    let metadata = movieState.metadataCache[item.slug];
    if (metadata && movieState.selectedSlug === item.slug) {
      showFpDetail(item.slug, metadataPreviewMovie(metadata), true);
    }
    try {
      if (!metadata?.details_loaded) {
        const detailResponse = await client.post("/api/tmdb/movie", {
          slug: item.slug,
          title: item.title,
          year: item.year || "",
          tmdb_id: metadata?.tmdb_id || item.tmdb_id || null,
        }, { signal: owner.signal });
        if (!current(owner, item.slug) || requestId !== movieState.requestSeq) return metadata || null;
        if (detailResponse.movie) {
          metadata = detailResponse.movie;
          movieState.metadataCache[item.slug] = metadata;
          updateFpResultCard(item.slug);
          refreshMovieFeatureCandidates();
          if (movieState.selectedSlug === item.slug) showFpDetail(item.slug, metadataPreviewMovie(metadata), true);
        } else if (movieState.selectedSlug === item.slug) {
          showFpDetail(item.slug, metadataPreviewMovie(basicMovieMetadata({ ...item, ...metadata })), true);
          setFpDetailAvailability("Metadaten nicht verfügbar", "error");
        }
      }
      if (metadata?.tmdb_id) void refreshFpJellyfinStatus([item]);
      return metadata || null;
    } catch (e) {
      if (current(owner, item.slug) && requestId === movieState.requestSeq && movieState.selectedSlug === item.slug) {
        showFpDetail(
          item.slug,
          metadataPreviewMovie(basicMovieMetadata({ ...item, ...metadata })),
          true,
        );
        setFpDetailAvailability("Metadaten konnten nicht geladen werden", "error");
      }
      return metadata || null;
    }
  }

  async function selectFpRow(slug, initialItem = null) {
    scope?.dispose();
    const owner = createScope();
    scope = owner;
    movieState.selectedSlug = slug;
    updateFpResultSelection();
    const movie = movieState.moviesCache[slug];
    const item = movieState.results.find((r) => r.slug === slug)
      || homeMovieBySlug(slug)
      || initialItem;
    if (!item) return;
    const metadata = movieState.metadataCache[slug];
    trackDiscoveryPreference("movie", { ...item, ...metadata, slug }, 0.8, "open");
    if (movie) showFpDetail(slug, movie);
    else if (metadata) showFpDetail(slug, metadataPreviewMovie(metadata), true);
    else {
      showFpDetail(slug, basicMovieMetadata(item), true);
      setFpDetailAvailability("Metadaten werden geladen", "loading");
    }
    openMediaModal("fp-detail-modal", findFpResultCard(slug));
    if (movie) return;
    await loadFpMetadata(item, owner);
    if (!current(owner, slug)) return;
    setFpDetailAvailability("Alle Anbieter werden durchsucht", "loading");
    try {
      const identity = movieState.metadataCache[slug] || item;
      const query = Number(identity.tmdb_id) > 0 ? `?${new URLSearchParams({ tmdb_id: String(identity.tmdb_id) })}` : "";
      const resolved = await client.get(`/api/movie/${encodeURIComponent(slug)}${query}`, { signal: owner.signal });
      if (!current(owner, slug)) return;
      movieState.moviesCache[slug] = resolved;
      updateFpResultCard(slug);
      if (movieState.selectedSlug === slug) showFpDetail(slug, resolved);
    } catch (error) {
      if (!current(owner, slug)) return;
      console.warn("Anbietersuche fehlgeschlagen:", error);
      if (movieState.selectedSlug === slug) {
        const preview = movieState.metadataCache[slug] || basicMovieMetadata(item);
        const unavailable = {
          ...metadataPreviewMovie(preview),
          hosters: [],
          hoster_route: "Kein Hoster verfügbar",
          hoster_fallback_count: 0,
        };
        showFpDetail(slug, unavailable, false);
        setFpDetailAvailability(
          error.code === "movie_hoster_unavailable"
            ? "Aktuell kein Hoster verfügbar"
            : `Anbieterprüfung fehlgeschlagen: ${error.message}`,
          "error",
        );
      }
    }
  }

  return { open: selectFpRow, unmount() { scope?.dispose(); scope = null; } };
}
