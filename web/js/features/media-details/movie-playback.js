import { api } from "../../core/api.js";

const TICKS_PER_SECOND = 10_000_000;
const progressPath = "/api/media-center/movies/progress";

function formatPosition(ticks) {
  const seconds = Math.floor(ticks / TICKS_PER_SECOND);
  const minutes = Math.floor(seconds / 60);
  const pad = value => String(value).padStart(2, "0");
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${pad(minutes % 60)}:${pad(seconds % 60)}`
    : `${pad(minutes)}:${pad(seconds % 60)}`;
}

export function createMoviePlayback(root, { canPlay, stopTrailer, client = api }) {
  const button = root.querySelector("#fp-detail-play");
  const dialog = root.querySelector("#fp-movie-player");
  const video = dialog.querySelector("video");
  const title = dialog.querySelector("h2");
  const status = dialog.querySelector("[role=status]");
  let currentMovie, slug, owned;
  let progress, readController, playing;
  let writes = Promise.resolve();

  function movieQuery() {
    const params = new URLSearchParams({ title: currentMovie.title, year: currentMovie.year || "" });
    if (Number(currentMovie.tmdb_id) > 0) params.set("tmdb_id", currentMovie.tmdb_id);
    return params;
  }

  function readProgress(key, params) {
    readController?.abort();
    const controller = new AbortController();
    readController = controller;
    const entry = { key, params, position_ticks: 0, loading: true };
    progress = entry;
    void writes.then(() => {
      if (!controller.signal.aborted) return client.get(`${progressPath}?${params}`, {
        signal: controller.signal, timeoutMs: 8_000,
      });
    }).then(result => {
      if (result && progress === entry) Object.assign(entry, result);
    }).catch(() => {
      // A library film remains playable if its personal data is unavailable.
    }).finally(() => {
      if (progress !== entry) return;
      entry.loading = false;
      refresh();
    });
  }

  function refresh() {
    button.hidden = !(currentMovie?.title && owned && canPlay());
    if (!button.hidden && !playing) {
      const params = movieQuery();
      const key = params.get("tmdb_id") || params.toString();
      if (progress?.key !== key) readProgress(key, params.toString());
    }
    button.disabled = !button.hidden && Boolean(progress?.loading);
    button.textContent = progress?.position_ticks
      ? `▶ Weiterschauen ${formatPosition(progress.position_ticks)}`
      : "▶ Film ansehen";
  }

  function saveProgress(ended = false) {
    if (!playing?.entry.profile_id || !playing.started || !Number.isFinite(video.currentTime)) return;
    const { entry, startTicks } = playing;
    const position = startTicks + Math.round(video.currentTime * TICKS_PER_SECOND);
    const finished = ended && (!entry.duration_ticks || position >= entry.duration_ticks - 5 * TICKS_PER_SECOND);
    const positionTicks = finished ? 0 : position;
    if (positionTicks === entry.position_ticks && !finished) return;
    entry.position_ticks = positionTicks;
    const body = { profile_id: entry.profile_id, generation: entry.generation,
      position_ticks: positionTicks, ended: finished };
    writes = writes.then(() => client.post(`${progressPath}?${entry.params}`, body, {
      keepalive: true, timeoutMs: 8_000,
    })).catch(() => {
      if (playing?.entry === entry && dialog.open) status.textContent = "Wiedergabestand konnte nicht gespeichert werden.";
    });
    refresh();
  }

  function stop() {
    if (!video.hasAttribute("src")) return;
    saveProgress(video.ended);
    playing = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    status.textContent = "";
  }

  function close() {
    if (dialog.open) dialog.close();
    stop();
  }

  function open() {
    if (button.hidden || button.disabled || !canPlay() || dialog.open) return;
    const params = movieQuery();
    const startTicks = progress?.position_ticks || 0;
    if (startTicks) params.set("start_ticks", startTicks);
    playing = { entry: progress, startTicks, started: false, nextSave: 15 };
    stopTrailer();
    title.textContent = currentMovie.title;
    status.textContent = "Film wird geladen …";
    dialog.showModal();
    video.src = `/api/media-center/movies/stream?${params}`;
    // The native controls remain usable when the browser blocks autoplay.
    void video.play().catch(() => {});
  }

  function resetProgress() {
    readController?.abort();
    readController = progress = null;
  }

  return {
    get active() { return dialog.open; },
    show(nextSlug, movie) {
      if (nextSlug !== slug) {
        close();
        owned = false;
        resetProgress();
      }
      slug = nextSlug;
      currentMovie = movie;
      refresh();
    },
    setOwned(value) { owned = value; refresh(); },
    reset() { close(); resetProgress(); slug = currentMovie = null; owned = false; refresh(); },
    mount(scope) {
      scope.listen(button, "click", open);
      scope.listen(dialog.querySelector("button"), "click", close);
      scope.listen(dialog, "cancel", event => { event.preventDefault(); close(); });
      scope.listen(dialog, "keydown", event => event.stopPropagation());
      scope.listen(video, "playing", () => { if (playing) playing.started = true; });
      scope.listen(video, "timeupdate", () => {
        if (!playing?.started || video.currentTime < playing.nextSave) return;
        playing.nextSave = video.currentTime + 15;
        saveProgress();
      });
      scope.listen(video, "pause", () => { if (!video.ended) saveProgress(); });
      scope.listen(video, "ended", () => {
        saveProgress(true);
        playing = null;
      });
      scope.listen(video, "loadeddata", () => { if (dialog.open) status.textContent = ""; });
      scope.listen(video, "error", () => {
        if (dialog.open && video.hasAttribute("src")) {
          status.textContent = "Der Film konnte nicht abgespielt werden. Prüfe die Wiedergabe in Jellyfin und versuche es erneut.";
        }
      });
    },
  };
}
