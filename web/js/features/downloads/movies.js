import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { queueAddFailureReason } from "./outcome.js";

/** User-started mutations survive detail navigation, but never the authenticated session. */
export function createMovieDownloads(root, {
  movieState, getQueuedSlugs, homeMovieBySlug, updateFpResultCard, showFpDetail,
  setDownloadState, refreshQueueUiAfterChange, refreshFpQueuePresentation, trackDiscoveryPreference,
  metadataPreviewMovie, basicMovieMetadata, fpDetailJellyfinValue, needsLanguageChoice, chooseLanguage,
  client = api,
}) {
  const byId = id => root.querySelector(`#${id}`);
  const fpDownloadFeedback = new Map(), pending = new Set();
  let scope = createScope(), bound = false, action = null;
  const visible = slug => !root.hidden && movieState.selectedSlug === slug;
  function renderFpDownloadFeedback(slug) {
    const status = byId("fp-detail-download-status");
    if (!status) return;
    const feedback = fpDownloadFeedback.get(slug);
    status.hidden = !feedback;
    status.className = `detail-download-status is-${feedback?.kind || "idle"}`;
    status.textContent = feedback?.message || "";
  }

  function setFpDownloadFeedback(slug, message = "", kind = "error") {
    if (!slug) return;
    if (message) fpDownloadFeedback.set(slug, { message, kind });
    else fpDownloadFeedback.delete(slug);
    if (movieState.selectedSlug === slug) renderFpDownloadFeedback(slug);
  }

  function setFpJellyfinDownloadPending(slug) {
    setFpDownloadFeedback(
      slug, "Jellyfin wird live geprüft. Der Download startet danach automatisch.", "active",
    );
  }

  function applyFpQueueAddResponse(slug, response) {
    const reason = queueAddFailureReason(response, [slug]);
    if (reason) {
      const message = `Download nicht gestartet: ${reason}`;
      setFpDownloadFeedback(slug, message, "error");
      setDownloadState("error", "Download nicht gestartet", reason, 0);
      return false;
    }
    setFpDownloadFeedback(slug, "Download eingeplant. Die Quelle wird vorbereitet.", "active");
    return true;
  }

  async function prepareFpMovieDownload(slug, owner) {
    const cached = movieState.moviesCache[slug];
    if (Array.isArray(cached?.hosters) && cached.hosters.length) return cached;
    const tmdbId = movieState.metadataCache[slug]?.tmdb_id
      || movieState.results.find((item) => item.slug === slug)?.tmdb_id
      || homeMovieBySlug(slug)?.tmdb_id
      || null;
    const query = Number(tmdbId) > 0 ? `?${new URLSearchParams({ tmdb_id: String(tmdbId) })}` : "";
    const movie = await client.get(`/api/movie/${encodeURIComponent(slug)}${query}`, { signal: owner.signal });
    if (!owner.active) return null;
    movieState.moviesCache[slug] = movie;
    updateFpResultCard(slug);
    if (visible(slug)) showFpDetail(slug, movie);
    if (Array.isArray(movie?.hosters) && movie.hosters.length) return movie;
    const reason = "kein Hoster verfügbar";
    setFpDownloadFeedback(slug, `Download nicht gestartet: ${reason}`, "error");
    setDownloadState("error", "Download nicht gestartet", reason, 0);
    return null;
  }

  function applyFpDownloadJobResult(result) {
    const slug = String(result?.slug || "");
    if (!slug) return;
    if (result.ok) {
      setFpDownloadFeedback(slug, "Download erfolgreich abgeschlossen.", "success");
      return;
    }
    const reason = String(result.msg || "Alle Anbieter oder Hoster sind ausgefallen.");
    setFpDownloadFeedback(slug, `Download fehlgeschlagen: ${reason}`, "error");
  }

  async function toggleFpPick(slug, { movie: provided, preferences = {} } = {}) {
    if (!scope.active || pending.has(slug)) return;
    const owner = scope;
    pending.add(slug); refreshFpQueuePresentation();
    try {
      if (getQueuedSlugs().has(slug)) {
        const resp = await client.post("/api/queue/remove", { slug }, { signal: owner.signal });
        if (!owner.active) return;
        setFpDownloadFeedback(slug); refreshQueueUiAfterChange(resp); return;
      }
      setFpDownloadFeedback(slug);
      const movie = provided || await prepareFpMovieDownload(slug, owner);
      if (!movie || !owner.active) return;
      setFpJellyfinDownloadPending(slug);
      const resp = await client.post("/api/queue/add", { slugs: [slug], preferences, source: "web" }, { signal: owner.signal });
      if (!owner.active) return;
      refreshQueueUiAfterChange(resp);
      if (applyFpQueueAddResponse(slug, resp)) trackDiscoveryPreference("movie", { ...movie, slug }, 5, "download");
    } catch (error) {
      if (!owner.active) return;
      const reason = error?.message || "Unbekannter Fehler";
      setFpDownloadFeedback(slug, `Download nicht gestartet: ${reason}`, "error");
      setDownloadState("error", "Download nicht gestartet", reason, 0);
      console.warn("Film konnte nicht zur Queue hinzugefügt werden:", error);
    } finally {
      if (owner.active) {
        pending.delete(slug); refreshFpQueuePresentation();
        const movie = movieState.moviesCache[slug]
          || metadataPreviewMovie(movieState.metadataCache[slug] || basicMovieMetadata(
            movieState.results.find(item => item.slug === slug) || homeMovieBySlug(slug) || {},
          ));
        if (visible(slug)) configureFpDetailAction(slug, movie, !movieState.moviesCache[slug]);
      }
    }
  }
  function configureFpDetailAction(slug, movie, metadataOnly = false) {
    action = { slug, movie, metadataOnly };
    const addBtn = byId("fp-detail-add");
    const queued = getQueuedSlugs().has(slug), owned = fpDetailJellyfinValue(slug, movie) === true;
    const hasHosters = Array.isArray(movie.hosters) && movie.hosters.length > 0;
    const mutationPending = pending.has(slug);
    renderFpDownloadFeedback(slug);
    addBtn.hidden = owned && !queued;
    addBtn.disabled = mutationPending || (owned && !queued) || (!queued && (metadataOnly || !hasHosters));
    addBtn.textContent = mutationPending ? (queued ? "Entferne …" : "Füge hinzu …")
      : queued ? "✕ Aus Queue entfernen" : metadataOnly ? "Prüfe Verfügbarkeit …"
        : hasHosters ? "↓ Herunterladen" : "Derzeit nicht verfügbar";
  }
  async function detailAction() {
    const selected = action, owner = scope;
    if (!selected || !owner.active || !visible(selected.slug)) return;
    const { slug, movie, metadataOnly } = selected;
    if (pending.has(slug)) return;
    const shouldRemove = getQueuedSlugs().has(slug);
    if (!shouldRemove && fpDetailJellyfinValue(slug, movie) === true) return;
    if (!shouldRemove && !metadataOnly && needsLanguageChoice(movie)) {
      const language = await chooseLanguage(movie, byId("fp-detail-add"));
      if (!owner.active || !language || action !== selected || !visible(slug) || getQueuedSlugs().has(slug)) return;
      const previous = movieState.downloadSelections.get(slug) || {};
      movieState.downloadSelections.set(slug, { provider: `language:${language}`, quality: previous.quality || "" });
    }
    const selection = movieState.downloadSelections.get(slug);
    const operation = toggleFpPick(slug, { movie: metadataOnly ? null : movie, preferences: selection ? { [slug]: selection } : {} });
    configureFpDetailAction(slug, movie, metadataOnly);
    await operation;
  }
  function mount() {
    if (bound) return;
    if (!scope.active) scope = createScope();
    bound = true; scope.listen(byId("fp-detail-add"), "click", detailAction);
  }
  function unmount() { scope.dispose(); pending.clear(); action = null; bound = false; fpDownloadFeedback.clear(); }
  return { mount, unmount, closeDetail() { action = null; }, pending: slug => pending.has(slug), toggle: toggleFpPick,
    configure: configureFpDetailAction, renderFeedback: renderFpDownloadFeedback, feedback: setFpDownloadFeedback,
    pendingFeedback: setFpJellyfinDownloadPending, accept: applyFpQueueAddResponse, job: applyFpDownloadJobResult };
}
