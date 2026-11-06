import { api } from "../../core/api.js";
import { createMoviePlayerControls, formatMovieTime } from "./movie-player-controls.js";
import { createMoviePlayerEpisodes } from "./movie-player-episodes.js";

const TICKS_PER_SECOND = 10_000_000;
const progressPath = "/api/media-center/movies/progress";

export function createMoviePlayback(root, { canPlay, stopTrailer, client = api }) {
  const button = root.querySelector("#fp-detail-play");
  const dialog = root.querySelector("#fp-movie-player") || root.ownerDocument.getElementById("fp-movie-player");
  const video = dialog.querySelector("video");
  const title = dialog.querySelector("h2");
  let currentMovie, slug, owned;
  let progress, readController, playing, controls, episodes;
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
      ? `▶ Weiterschauen ${formatMovieTime(progress.position_ticks / TICKS_PER_SECOND)}`
      : "▶ Film ansehen";
  }

  function getPosition() {
    const start = (playing?.startTicks || 0) / TICKS_PER_SECOND;
    const elapsed = start + (playing?.ready && Number.isFinite(video.currentTime) ? video.currentTime : 0);
    const nativeDuration = playing?.ready && Number.isFinite(video.duration) ? start + video.duration : 0;
    const duration = (playing?.entry?.duration_ticks || 0) / TICKS_PER_SECOND || nativeDuration;
    return { elapsed: duration ? Math.min(elapsed, duration) : elapsed, duration };
  }

  function saveProgress(ended = false) {
    if (!playing?.entry?.profile_id || !playing.started || playing.finished) return;
    const { entry } = playing;
    const position = Math.round(getPosition().elapsed * TICKS_PER_SECOND);
    const finished = ended && (!entry.duration_ticks || position >= entry.duration_ticks - 5 * TICKS_PER_SECOND);
    const positionTicks = finished ? 0 : position;
    if (positionTicks === entry.position_ticks && !finished) return;
    entry.position_ticks = positionTicks;
    const body = { profile_id: entry.profile_id, generation: entry.generation,
      position_ticks: positionTicks, ended: finished };
    writes = writes.then(() => client.post(`${progressPath}?${entry.params}`, body, {
      keepalive: true, timeoutMs: 8_000,
    })).catch(() => {
      if (playing?.entry === entry && dialog.open) controls.message("Wiedergabestand konnte nicht gespeichert werden.");
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
    controls.message();
  }

  function close() {
    const wasOpen = dialog.open;
    controls?.leavePresentationMode();
    if (wasOpen) dialog.close();
    stop();
    episodes?.reset();
    if (wasOpen) void writes.then(() => dialog.ownerDocument.dispatchEvent(new Event("royal:playback-closed")));
  }

  function startStream(entry, seconds, autoplay) {
    const params = new URLSearchParams(entry.params);
    const startTicks = Math.round(seconds * TICKS_PER_SECOND);
    if (startTicks) params.set("start_ticks", startTicks);
    playing = { entry, startTicks, started: false, ready: false, nextSave: 15 };
    controls.message(title.textContent, { loading: true });
    video.src = `/api/media-center/movies/stream?${params}`;
    if (autoplay) void video.play().catch(() => {});
  }

  function seek(seconds) {
    if (!playing || !Number.isFinite(seconds)) return;
    const { elapsed, duration } = getPosition();
    const target = Math.max(0, Math.min(seconds, duration ? Math.max(0, duration - 0.25) : elapsed));
    if (Math.abs(elapsed - target) < 0.05) return;
    const relative = target - playing.startTicks / TICKS_PER_SECOND;
    if (playing.ready && !playing.finished) {
      for (let i = 0; i < video.seekable.length; i++) {
        if (relative >= video.seekable.start(i) && relative < video.seekable.end(i)) {
          video.currentTime = relative;
          controls.render();
          return;
        }
      }
    }
    // Jellyfin's progressive MP4 can only seek within data it has already sent.
    // Outside that range, restart the stream at the requested film timestamp.
    const autoplay = !video.paused && !video.ended;
    saveProgress();
    startStream(playing.entry, target, autoplay);
  }

  function open() {
    if (button.hidden || button.disabled || !canPlay() || dialog.open) return;
    stopTrailer();
    title.textContent = currentMovie.title;
    episodes.reset();
    dialog.showModal();
    startStream(progress, (progress.position_ticks || 0) / TICKS_PER_SECOND, true);
  }

  function selectItem(item) {
    const entry = { ...item, params: new URLSearchParams({ item_id: item.id }).toString() };
    saveProgress(video.ended);
    title.textContent = item.kind === "episode"
      ? [item.title, item.season != null && `Staffel ${item.season}`,
        item.episode != null && `Episode ${item.episode}`].filter(Boolean).join(" · ")
      : item.title;
    startStream(entry, (item.position_ticks || 0) / TICKS_PER_SECOND, true);
    void episodes.show(item, writes);
  }

  function openItem(item, trigger) {
    if (!controls || !canPlay() || dialog.open || !item?.id || !item.profile_id) return;
    trigger?.focus({ preventScroll: true });
    stopTrailer();
    dialog.showModal();
    selectItem(item);
  }

  function resetProgress() {
    readController?.abort();
    readController = progress = null;
  }

  return {
    get active() { return dialog.open; },
    openItem,
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
      controls = createMoviePlayerControls(dialog, {
        getPosition, seek, replay: () => startStream(playing.entry, 0, true),
        retry: () => startStream(playing.entry, getPosition().elapsed, true),
      });
      episodes = createMoviePlayerEpisodes(dialog, {
        client, selectEpisode: item => { if (dialog.open && canPlay()) selectItem(item); },
      });
      scope.listen(button, "click", open);
      scope.listen(dialog.querySelector('[data-player-action="close"]'), "click", close);
      scope.listen(dialog, "cancel", event => { event.preventDefault(); close(); });
      scope.listen(dialog, "keydown", event => event.stopPropagation());
      scope.listen(video, "loadedmetadata", () => {
        if (!playing) return;
        playing.ready = true;
        if (video.paused) controls.message();
      });
      scope.listen(video, "playing", () => {
        if (!playing) return;
        playing.started = true;
        controls.message();
      });
      scope.listen(video, "waiting", () => {
        if (playing && !video.paused) controls.message(title.textContent, { loading: true });
      });
      scope.listen(video, "timeupdate", () => {
        if (!playing?.started || video.currentTime < playing.nextSave) return;
        playing.nextSave = video.currentTime + 15;
        saveProgress();
      });
      scope.listen(video, "pause", () => { if (!video.ended) saveProgress(); });
      scope.listen(video, "ended", () => {
        saveProgress(true);
        if (playing) playing.finished = true;
        controls.message();
      });
      scope.listen(video, "error", () => {
        if (dialog.open && video.hasAttribute("src")) {
          controls.message("Der Inhalt konnte nicht abgespielt werden.", { error: true });
        }
      });
      controls.mount(scope);
      episodes.mount(scope);
    },
  };
}
