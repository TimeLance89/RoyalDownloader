export function formatMovieTime(seconds) {
  const whole = Math.floor(Math.max(0, seconds));
  const minutes = Math.floor(whole / 60);
  const pad = value => String(value).padStart(2, "0");
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${pad(minutes % 60)}:${pad(whole % 60)}`
    : `${pad(minutes)}:${pad(whole % 60)}`;
}

export function createMoviePlayerControls(dialog, { getPosition, seek, replay, retry }) {
  const document = dialog.ownerDocument;
  const video = dialog.querySelector("video");
  const player = dialog.querySelector(".rd-player");
  const deck = dialog.querySelector(".rd-player-deck");
  const timeline = deck.querySelector(".rd-player-timeline");
  const volume = deck.querySelector(".rd-player-volume");
  const rate = deck.querySelector("select");
  const elapsed = deck.querySelector("[data-player-elapsed]");
  const duration = deck.querySelector("[data-player-duration]");
  const status = dialog.querySelector("[role=status]");
  const center = dialog.querySelector(".rd-player-center");
  const actionButton = name => dialog.querySelector(`[data-player-action="${name}"]`);
  const fullscreen = actionButton("fullscreen");
  const pip = actionButton("pip");
  const mute = actionButton("mute");
  const retryButton = actionButton("retry");
  const back = actionButton("back");
  const forward = actionButton("forward");
  const playbackButtons = dialog.querySelectorAll('[data-player-action="play"]');
  let busy = false, failed = false, scrubbing = false;

  function render() {
    if (!dialog.open) return;
    const position = getPosition();
    const current = scrubbing ? Number(timeline.value) : position.elapsed;
    const max = position.duration;
    timeline.disabled = !max;
    timeline.max = max || 1;
    if (!scrubbing) timeline.value = current;
    timeline.style.setProperty("--rd-played", `${max ? Math.min(100, 100 * current / max) : 0}%`);
    timeline.setAttribute("aria-valuetext", max
      ? `${formatMovieTime(current)} von ${formatMovieTime(max)}` : formatMovieTime(current));
    elapsed.textContent = formatMovieTime(current);
    duration.textContent = max ? `/ ${formatMovieTime(max)}` : "";

    const paused = video.paused || video.ended;
    const playLabel = video.ended ? "Erneut abspielen" : paused ? "Abspielen" : "Pausieren";
    player.classList.toggle("is-playing", !paused);
    const silent = video.muted || video.volume === 0;
    player.classList.toggle("is-muted", silent);
    for (const button of playbackButtons) {
      button.setAttribute("aria-label", playLabel);
      button.title = playLabel;
    }
    center.hidden = !paused || busy || failed;
    retryButton.hidden = !failed;
    mute.setAttribute("aria-label", silent ? "Ton einschalten" : "Stummschalten");
    mute.title = silent ? "Ton einschalten (M)" : "Stummschalten (M)";
    volume.value = video.muted ? 0 : video.volume;
    rate.value = video.playbackRate;
    forward.disabled = !max;
    back.disabled = position.elapsed <= 0;
    fullscreen.setAttribute("aria-label", document.fullscreenElement ? "Vollbild verlassen" : "Vollbild");
  }

  function message(text = "", { loading = false, error = false } = {}) {
    busy = loading;
    failed = error;
    status.textContent = text;
    player.classList.toggle("is-buffering", busy);
    render();
  }

  function togglePlayback() {
    if (failed) return retry();
    if (video.ended) return replay();
    if (!video.paused) return video.pause();
    void video.play().catch(() => {});
  }

  function attempt(action) {
    try { Promise.resolve(action()).catch(() => {}); } catch { /* Browser refused the request. */ }
  }

  function toggleFullscreen() {
    if (document.fullscreenElement === player) attempt(() => document.exitFullscreen());
    else if (document.fullscreenEnabled && player.requestFullscreen) attempt(() => player.requestFullscreen());
    else if (video.webkitEnterFullscreen) attempt(() => video.webkitEnterFullscreen());
  }

  function leavePresentationMode() {
    scrubbing = false;
    if (document.fullscreenElement === player) attempt(() => document.exitFullscreen());
    if (document.pictureInPictureElement === video) attempt(() => document.exitPictureInPicture());
    if (video.webkitDisplayingFullscreen) attempt(() => video.webkitExitFullscreen());
  }

  const actions = {
    play: togglePlayback,
    back: () => seek(getPosition().elapsed - 10),
    forward: () => seek(getPosition().elapsed + 10),
    mute: () => {
      if (video.volume === 0) {
        video.volume = 0.8;
        video.muted = false;
      } else video.muted = !video.muted;
    },
    fullscreen: toggleFullscreen,
    pip: () => attempt(() => document.pictureInPictureElement === video
      ? document.exitPictureInPicture() : video.requestPictureInPicture()),
    retry,
  };

  function mount(scope) {
    video.controls = false;
    fullscreen.hidden = !(document.fullscreenEnabled || video.webkitEnterFullscreen);
    pip.hidden = !(document.pictureInPictureEnabled && video.requestPictureInPicture);
    scope.listen(dialog, "click", event => {
      const action = event.target.closest("[data-player-action]")?.dataset.playerAction;
      actions[action]?.();
    });
    scope.listen(video, "click", togglePlayback);
    scope.listen(timeline, "input", () => { scrubbing = true; render(); });
    scope.listen(timeline, "change", () => {
      scrubbing = false;
      seek(Number(timeline.value));
      render();
    });
    scope.listen(volume, "input", () => { video.volume = Number(volume.value); video.muted = false; });
    scope.listen(rate, "change", () => { video.defaultPlaybackRate = video.playbackRate = Number(rate.value); });
    scope.listen(document, "fullscreenchange", render);
    scope.listen(video, "webkitbeginfullscreen", () => { video.controls = true; });
    scope.listen(video, "webkitendfullscreen", () => { video.controls = false; });
    for (const event of ["loadedmetadata", "durationchange", "play", "pause", "ended", "timeupdate", "volumechange", "ratechange"]) {
      scope.listen(video, event, render);
    }
    scope.listen(dialog, "keydown", event => {
      if (event.ctrlKey || event.altKey || event.metaKey || event.target.closest("input, select, textarea, [contenteditable]")) return;
      const shortcut = {
        k: "play", ArrowLeft: "back", ArrowRight: "forward", m: "mute", f: "fullscreen",
      }[event.key];
      const action = shortcut || (event.key === " " && !event.target.closest("button") ? "play" : "");
      if (!action) return;
      event.preventDefault();
      if (!event.repeat || action === "back" || action === "forward") actions[action]();
    });
  }

  return { render, message, leavePresentationMode, mount };
}
