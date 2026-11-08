import { api } from "../../core/api.js";
import { createMoviePlayerControls, formatMovieTime } from "./movie-player-controls.js";
import { createMoviePlayerEpisodes } from "./movie-player-episodes.js";
import { createMovieStream } from "./movie-stream.js";

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
  const stream = createMovieStream(video, {
    document: root.ownerDocument, client,
    starting: position => {
      if (playing) { playing.target = position; playing.ready = false; playing.started = false; }
    },
    positionReady: () => { if (playing) { playing.ready = true; playing.started = true; } },
    failed: () => { if (dialog.open) controls.message("Der Inhalt konnte nicht abgespielt werden.", { error: true }); },
    prepared: result => { if (playing && result.duration_ticks) playing.entry.duration_ticks = result.duration_ticks; },
  });

  function movieQuery() {
    if (currentMovie.jellyfin_item_id) return new URLSearchParams({ item_id: currentMovie.jellyfin_item_id });
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
    const elapsed = stream.pendingPosition ?? (playing?.ready && Number.isFinite(video.currentTime) ? video.currentTime : playing?.target || 0);
    const nativeDuration = playing?.ready && Number.isFinite(video.duration) ? video.duration : 0;
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
    saveProgress(video.ended);
    playing = null;
    stream.close();
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
    playing = null;
    stream.close();
    playing = { entry, target: seconds, started: false, ready: false, nextSave: seconds + 15 };
    controls.message(title.textContent, { loading: true });
    void stream.open(entry.params, seconds, autoplay);
  }

  function seek(seconds) {
    if (!playing || !Number.isFinite(seconds)) return;
    const { elapsed, duration } = getPosition();
    const target = Math.max(0, Math.min(seconds, duration ? Math.max(0, duration - 0.25) : elapsed));
    if (Math.abs(elapsed - target) < 0.05) return;
    saveProgress();
    playing.target = target;
    playing.finished = false;
    playing.nextSave = target + 15;
    stream.seek(target);
    controls.render();
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
        if (dialog.open && video.hasAttribute("src") && !stream.managesErrors) {
          controls.message("Der Inhalt konnte nicht abgespielt werden.", { error: true });
        }
      });
      scope.interval(() => { if (dialog.open) stream.heartbeat(); }, 30_000);
      scope.listen(root.ownerDocument.defaultView, "pagehide", () => { saveProgress(); stream.close(); });
      scope.add(() => { playing = null; stream.close(); });
      controls.mount(scope);
      episodes.mount(scope);
    },
  };
}
