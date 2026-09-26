import { createScope } from "../../core/lifecycle.js";
import { createDetailHeroScroll } from "./scroll.js";

/** Session preferences with independent film, series and full-player lifetimes. */
export function createTrailers(document, { window = document.defaultView, storage = window.localStorage } = {}) {
  const localStorage = storage;
  const HTMLElement = window.HTMLElement;
  let owner = null;
  let filmScope = null;
  let seriesScope = null;
  let playerScope = null;
  const scroll = createDetailHeroScroll(document);
  const syncDetailHeroScrollPlayback = scroll.sync;
  const TRAILER_HERO_AUTOPLAY_KEY = "royal-trailer-hero-autoplay-v1";
  let activeTrailerPlayback = null;
  let activeTrailerLoadTimer = null;

  function heroTrailerAutoplayEnabled() {
    try {
      const saved = localStorage.getItem(TRAILER_HERO_AUTOPLAY_KEY);
      return saved === null ? true : saved === "true";
    } catch { return true; }
  }

  function setHeroTrailerAutoplay(enabled) {
    try { localStorage.setItem(TRAILER_HERO_AUTOPLAY_KEY, String(Boolean(enabled))); }
    catch { /* Gesperrter Speicher darf den Player nicht blockieren. */ }
    const toggle = document.getElementById("fp-trailer-autoplay");
    if (toggle) toggle.checked = Boolean(enabled);
    if (!enabled) {
      stopFpDetailHeroTrailer();
      stopSeriesDetailHeroTrailer();
    }
  }

  function setTrailerPlayerState(status, message = "") {
    const modal = document.getElementById("fp-trailer-modal");
    const stateLayer = document.getElementById("fp-trailer-state");
    const title = document.getElementById("fp-trailer-state-title");
    const copy = document.getElementById("fp-trailer-state-copy");
    const frame = document.getElementById("fp-trailer-frame");
    if (!modal || !stateLayer || !title || !copy || !frame) return;
    modal.dataset.playerState = status;
    stateLayer.hidden = status === "ready";
    frame.tabIndex = status === "ready" ? 0 : -1;
    title.textContent = status === "error" ? "Trailer nicht verfügbar" : "Trailer wird geladen";
    copy.textContent = message || (status === "error"
      ? "Der Trailer konnte nicht geladen werden."
      : "Vorführung wird vorbereitet …");
  }

  function resetTrailerPlayerState() {
    playerScope?.dispose(); playerScope = null;
    activeTrailerLoadTimer?.();
    activeTrailerLoadTimer = null;
    const frame = document.getElementById("fp-trailer-frame");
    if (frame) frame.onload = null;
    activeTrailerPlayback = null;
    setTrailerPlayerState("idle");
  }

  function startTrailerPlayback() {
    if (!owner?.active || !activeTrailerPlayback) return;
    playerScope?.dispose();
    playerScope = createScope();
    const playback = playerScope;
    const { key, startAt } = activeTrailerPlayback;
    const frame = document.getElementById("fp-trailer-frame");
    if (!frame) return;
    activeTrailerLoadTimer?.();
    setTrailerPlayerState("loading");
    frame.onload = () => {
      if (!playback.active) return;
      activeTrailerLoadTimer?.();
      activeTrailerLoadTimer = null;
      setTrailerPlayerState("ready");
      listenForHeroTrailerTime(frame);
    };
    frame.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
      + `?autoplay=1&rel=0&playsinline=1&enablejsapi=1`
      + `${startAt >= 1 ? `&start=${Math.floor(startAt)}` : ""}`
      + `&origin=${encodeURIComponent(window.location.origin)}`;
    activeTrailerLoadTimer = playback.timeout(() => {
      setTrailerPlayerState("error", "YouTube antwortet nicht. Erneut versuchen oder extern öffnen.");
    }, 10000);
  }

  function openTrailerPlayer(movie, key, startAt, trigger) {
    if (!owner?.active) return;
    const modal = document.getElementById("fp-trailer-modal");
    modal._returnFocus = trigger instanceof HTMLElement ? trigger : document.activeElement;
    activeTrailerPlayback = { key, startAt };
    document.getElementById("fp-trailer-title").textContent = `${movie.title || "Titel"} · Trailer`;
    document.getElementById("fp-trailer-caption").textContent = movie.trailer?.name || "Offizieller Trailer";
    document.getElementById("fp-trailer-external").href = `https://www.youtube.com/watch?v=${encodeURIComponent(key)}`;
    document.getElementById("fp-trailer-autoplay").checked = heroTrailerAutoplayEnabled();
    modal.hidden = false;
    modal.classList.add("is-open");
    document.body.classList.add("trailer-modal-open");
    startTrailerPlayback();
    playerScope.frame(() => document.getElementById("fp-trailer-close")?.focus());
  }

  function handleTrailerPlayerMessage(event, payload) {
    const frame = document.getElementById("fp-trailer-frame");
    if (!playerScope?.active || !frame?.getAttribute("src") || event.source !== frame.contentWindow) return false;
    if (payload?.event === "onError") {
      activeTrailerLoadTimer?.();
      activeTrailerLoadTimer = null;
      setTrailerPlayerState("error", "Dieser Trailer ist bei YouTube nicht verfügbar.");
    } else if (payload?.event === "onReady") {
      activeTrailerLoadTimer?.();
      activeTrailerLoadTimer = null;
      setTrailerPlayerState("ready");
    }
    return true;
  }

  function trailerModalFocusableElements() {
    const modal = document.getElementById("fp-trailer-modal");
    if (!modal) return [];
    return [...modal.querySelectorAll('button:not([hidden]), a:not([hidden]), input:not([hidden]), iframe')]
      .filter((element) => !element.disabled
        && element.tabIndex >= 0
        && element.id !== "fp-trailer-focus-end"
        && Boolean(element.offsetWidth || element.offsetHeight));
  }


  let fpDetailHeroTrailerTimer = null;
  let fpDetailHeroTrailerToken = 0;
  let fpDetailHeroTrailerCurrentTime = 0;
  let fpDetailHeroTrailerKey = "";
  const completedFilmHeroTrailers = new Set();
  const completedSeriesHeroTrailers = new Set();
  const FP_TRAILER_MUTED_KEY = "royal-trailer-muted-v1";


  function loadFpDetailHeroTrailerMuted() {
    try {
      const saved = localStorage.getItem(FP_TRAILER_MUTED_KEY);
      return saved === null ? true : saved !== "false";
    } catch {
      return true;
    }
  }

  let fpDetailHeroTrailerMuted = loadFpDetailHeroTrailerMuted();

  function fpTrailerYoutubeKey(movie) {
    const trailer = movie?.trailer;
    const key = String(trailer?.key || "").trim();
    return trailer?.site === "YouTube" && /^[A-Za-z0-9_-]{6,20}$/.test(key) ? key : "";
  }

  function setFpDetailHeroTrailerMuted(muted, { persist = false } = {}) {
    fpDetailHeroTrailerMuted = Boolean(muted);
    if (persist) {
      try {
        localStorage.setItem(FP_TRAILER_MUTED_KEY, String(fpDetailHeroTrailerMuted));
      } catch {
        // Gesperrter Browser-Speicher darf die Trailersteuerung nicht blockieren.
      }
    }
    const enabled = !fpDetailHeroTrailerMuted;
    for (const [frameId, buttonId] of [
      ["fp-detail-hero-frame", "fp-detail-hero-mute"],
      ["series-detail-hero-frame", "series-detail-hero-mute"],
      ["home-card-dock-preview", "home-card-dock-mute"],
    ]) {
      const frame = document.getElementById(frameId);
      const button = document.getElementById(buttonId);
      frame?.contentWindow?.postMessage(JSON.stringify({
        event: "command",
        func: fpDetailHeroTrailerMuted ? "mute" : "unMute",
        args: [],
      }), "*");
      if (!button) continue;
      button.setAttribute("aria-pressed", String(enabled));
      button.setAttribute("aria-label", enabled ? "Trailerton ausschalten" : "Trailerton einschalten");
      button.title = enabled ? "Trailerton ausschalten" : "Trailerton einschalten";
      button.querySelector("span").textContent = enabled ? "🔊" : "🔇";
    }
  }

  function onMessage(event) {
    if (!["https://www.youtube-nocookie.com", "https://www.youtube.com"].includes(event.origin)) return;
    let payload = event.data;
    if (typeof payload === "string") {
      try { payload = JSON.parse(payload); } catch { return; }
    }
    if (handleTrailerPlayerMessage(event, payload)) return;
    const playerState = payload?.event === "onStateChange"
      ? Number(payload.info)
      : Number(payload?.info?.playerState);
    if (Number.isFinite(playerState)) {
      for (const [frameId, kind] of [
        ["fp-detail-hero-frame", "film"],
        ["series-detail-hero-frame", "series"],
      ]) {
        const frame = document.getElementById(frameId);
        if (!frame?.getAttribute("src") || event.source !== frame.contentWindow) continue;
        if (playerState === 1) {
          syncDetailHeroScrollPlayback(frame.closest(".media-modal-panel"), { force: true });
          // Erst nach echtem Videostart einblenden: So bleibt YouTubes großes
          // Start-/Pause-Piktogramm hinter dem bereits sichtbaren Wallpaper.
          const playback = kind === "film" ? filmScope : seriesScope;
          playback?.timeout(() => {
            if (!frame.getAttribute("src")) return;
            frame.parentElement?.classList.add("is-playing");
            frame.closest(".media-modal-panel")?.classList.add("is-trailer-playing");
          }, 350);
        } else if (playerState === 0) {
          if (kind === "film") {
            completedFilmHeroTrailers.add(fpDetailHeroTrailerKey);
            stopFpDetailHeroTrailer();
          } else {
            completedSeriesHeroTrailers.add(seriesDetailHeroTrailerKey);
            stopSeriesDetailHeroTrailer();
          }
        }
        break;
      }
    }
    const currentTime = Number(payload?.info?.currentTime);
    if (!Number.isFinite(currentTime) || currentTime < 0) return;
    for (const [frameId, kind] of [
      ["fp-detail-hero-frame", "film"],
      ["series-detail-hero-frame", "series"],
    ]) {
      const frame = document.getElementById(frameId);
      if (!frame?.getAttribute("src") || event.source !== frame.contentWindow) continue;
      if (kind === "film") fpDetailHeroTrailerCurrentTime = currentTime;
      else seriesDetailHeroTrailerCurrentTime = currentTime;
      break;
    }
  }

  function listenForHeroTrailerTime(frame) {
    if (!frame?.contentWindow) return;
    const subscribe = () => frame.contentWindow?.postMessage(JSON.stringify({
      event: "listening",
      id: frame.id,
      channel: frame.id,
    }), "*");
    subscribe();
    const playback = frame.id === "fp-trailer-frame" ? playerScope
      : frame.id === "fp-detail-hero-frame" ? filmScope : seriesScope;
    playback?.timeout(subscribe, 250);
    playback?.timeout(subscribe, 750);
  }

  function stopFpDetailHeroTrailer() {
    filmScope?.dispose(); filmScope = null;
    fpDetailHeroTrailerToken += 1;
    if (fpDetailHeroTrailerTimer) fpDetailHeroTrailerTimer();
    fpDetailHeroTrailerTimer = null;
    const panel = document.getElementById("fp-detail-panel");
    const shell = document.getElementById("fp-detail-hero-trailer");
    const frame = document.getElementById("fp-detail-hero-frame");
    const muteButton = document.getElementById("fp-detail-hero-mute");
    shell.classList.remove("is-playing");
    panel.classList.remove("is-trailer-playing");
    muteButton.hidden = true;
    frame.onload = null;
    frame.removeAttribute("src");
    shell.hidden = true;
    setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
    fpDetailHeroTrailerKey = "";
  }

  function scheduleFpDetailHeroTrailer(movie) {
    if (!owner?.active) return;
    const key = fpTrailerYoutubeKey(movie);
    const shell = document.getElementById("fp-detail-hero-trailer");
    if (key && fpDetailHeroTrailerKey === key && (!shell.hidden || fpDetailHeroTrailerTimer)) return;
    stopFpDetailHeroTrailer();
    if (
      !key
      || !heroTrailerAutoplayEnabled()
      || completedFilmHeroTrailers.has(key)
      || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) return;
    fpDetailHeroTrailerKey = key;
    fpDetailHeroTrailerCurrentTime = 0;
    const token = fpDetailHeroTrailerToken;
    filmScope = createScope();
    fpDetailHeroTrailerTimer = filmScope.timeout(() => {
      fpDetailHeroTrailerTimer = null;
      if (
        token !== fpDetailHeroTrailerToken
        || document.getElementById("fp-detail-modal").hidden
      ) return;
      const shell = document.getElementById("fp-detail-hero-trailer");
      const frame = document.getElementById("fp-detail-hero-frame");
      const muteButton = document.getElementById("fp-detail-hero-mute");
      setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
      shell.hidden = false;
      frame.onload = () => {
        if (token !== fpDetailHeroTrailerToken) return;
        listenForHeroTrailerTime(frame);
        muteButton.hidden = false;
        setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
        syncDetailHeroScrollPlayback(document.getElementById("fp-detail-panel"), { force: true });
      };
      frame.src =
        `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
        + `?autoplay=1&mute=1&controls=0&playsinline=1&rel=0&modestbranding=1`
        + `&disablekb=1&fs=0&iv_load_policy=3&enablejsapi=1`
        + `&origin=${encodeURIComponent(window.location.origin)}`;
    }, 2000);
  }

  function closeFpTrailerModal(restoreFocus = true) {
    const modal = document.getElementById("fp-trailer-modal");
    if (!modal || modal.hidden) return;
    const returnFocus = modal._returnFocus;
    modal.classList.remove("is-open");
    modal.hidden = true;
    document.body.classList.remove("trailer-modal-open");
    document.getElementById("fp-trailer-frame")?.removeAttribute("src");
    resetTrailerPlayerState();
    if (restoreFocus && returnFocus instanceof HTMLElement && returnFocus.isConnected) {
      returnFocus.focus();
    }
  }

  function openFpTrailerModal(movie, trigger, heroKind = "film") {
    const trailer = movie?.trailer;
    const key = String(trailer?.key || "").trim();
    if (trailer?.site !== "YouTube" || !/^[A-Za-z0-9_-]{6,20}$/.test(key)) return;
    const isSeriesHero = heroKind === "series" && seriesDetailHeroTrailerKey === key;
    const isFilmHero = heroKind === "film" && fpDetailHeroTrailerKey === key;
    const startAt = isSeriesHero
      ? seriesDetailHeroTrailerCurrentTime
      : isFilmHero ? fpDetailHeroTrailerCurrentTime : 0;
    stopFpDetailHeroTrailer();
    stopSeriesDetailHeroTrailer();
    openTrailerPlayer(movie, key, startAt, trigger);
  }

  function configureFpTrailer(movie) {
    if (!owner?.active) return;
    const button = document.getElementById("fp-detail-trailer");
    const trailerKey = fpTrailerYoutubeKey(movie);
    const available = Boolean(trailerKey);
    const trailer = movie?.trailer;
    button.hidden = !available;
    const trailerMovie = available
      ? { ...movie, trailer: { ...trailer, key: trailerKey } }
      : null;
    button.onclick = trailerMovie ? () => openFpTrailerModal(trailerMovie, button, "film") : null;
    if (!available) {
      closeFpTrailerModal(false);
      stopFpDetailHeroTrailer();
    } else {
      scheduleFpDetailHeroTrailer(trailerMovie);
    }
  }


  let seriesDetailHeroTrailerTimer = null;
  let seriesDetailHeroTrailerToken = 0;
  let seriesDetailHeroTrailerCurrentTime = 0;
  let seriesDetailHeroTrailerKey = "";

  function stopSeriesDetailHeroTrailer() {
    seriesScope?.dispose(); seriesScope = null;
    seriesDetailHeroTrailerToken += 1;
    if (seriesDetailHeroTrailerTimer) seriesDetailHeroTrailerTimer();
    seriesDetailHeroTrailerTimer = null;
    const panel = document.querySelector("#series-detail-modal .series-detail-panel");
    const shell = document.getElementById("series-detail-hero-trailer");
    const frame = document.getElementById("series-detail-hero-frame");
    const muteButton = document.getElementById("series-detail-hero-mute");
    if (!panel || !shell || !frame || !muteButton) return;
    shell.classList.remove("is-playing");
    panel.classList.remove("is-trailer-playing");
    muteButton.hidden = true;
    frame.onload = null;
    frame.removeAttribute("src");
    shell.hidden = true;
    seriesDetailHeroTrailerKey = "";
    setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
  }

  function scheduleSeriesDetailHeroTrailer(series) {
    if (!owner?.active) return;
    const key = fpTrailerYoutubeKey(series);
    if (
      !key
      || !heroTrailerAutoplayEnabled()
      || completedSeriesHeroTrailers.has(key)
      || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      stopSeriesDetailHeroTrailer();
      return;
    }
    const shell = document.getElementById("series-detail-hero-trailer");
    if (seriesDetailHeroTrailerKey === key && (!shell.hidden || seriesDetailHeroTrailerTimer)) return;
    stopSeriesDetailHeroTrailer();
    seriesDetailHeroTrailerKey = key;
    seriesDetailHeroTrailerCurrentTime = 0;
    const token = seriesDetailHeroTrailerToken;
    seriesScope = createScope();
    seriesDetailHeroTrailerTimer = seriesScope.timeout(() => {
      seriesDetailHeroTrailerTimer = null;
      if (
        token !== seriesDetailHeroTrailerToken
        || document.getElementById("series-detail-modal").hidden
      ) return;
      const frame = document.getElementById("series-detail-hero-frame");
      const muteButton = document.getElementById("series-detail-hero-mute");
      shell.hidden = false;
      frame.onload = () => {
        if (token !== seriesDetailHeroTrailerToken) return;
        listenForHeroTrailerTime(frame);
        muteButton.hidden = false;
        setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
        syncDetailHeroScrollPlayback(
          document.querySelector("#series-detail-modal .series-detail-panel"),
          { force: true },
        );
      };
      frame.src =
        `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
        + `?autoplay=1&mute=1&controls=0&playsinline=1&rel=0&modestbranding=1`
        + `&disablekb=1&fs=0&iv_load_policy=3&enablejsapi=1`
        + `&origin=${encodeURIComponent(window.location.origin)}`;
    }, 2000);
  }

  function configureSeriesTrailer(series) {
    if (!owner?.active) return;
    const button = document.getElementById("series-detail-trailer");
    const trailerKey = fpTrailerYoutubeKey(series);
    const available = Boolean(trailerKey);
    const trailerSeries = available
      ? { ...series, trailer: { ...series.trailer, key: trailerKey } }
      : null;
    button.hidden = !available;
    button.onclick = trailerSeries
      ? () => openFpTrailerModal(trailerSeries, button, "series")
      : null;
    if (available) scheduleSeriesDetailHeroTrailer(trailerSeries);
    else stopSeriesDetailHeroTrailer();
  }


function mount() {
  if (owner?.active) return;
  owner = createScope();
  scroll.mount();
  owner.listen(window, "message", onMessage);
  for (const id of ["fp-trailer-close", "fp-trailer-backdrop"]) {
    owner.listen(document.getElementById(id), "click", () => closeFpTrailerModal());
  }
  owner.listen(document.getElementById("fp-trailer-retry"), "click", startTrailerPlayback);
  owner.listen(document.getElementById("fp-trailer-autoplay"), "change", event => setHeroTrailerAutoplay(event.currentTarget.checked));
  owner.listen(document.getElementById("fp-trailer-focus-end"), "focus", () => document.getElementById("fp-trailer-close")?.focus());
  for (const id of ["fp-detail-hero-mute", "series-detail-hero-mute"]) {
    owner.listen(document.getElementById(id), "click", () => setFpDetailHeroTrailerMuted(!fpDetailHeroTrailerMuted, { persist: true }));
  }
}
function unmount() {
  owner?.dispose(); owner = null;
  closeFpTrailerModal(false);
  resetTrailerPlayerState();
  stopFpDetailHeroTrailer(); stopSeriesDetailHeroTrailer();
  scroll.unmount();
  document.getElementById("fp-detail-trailer").onclick = null;
  document.getElementById("series-detail-trailer").onclick = null;
}
return {
  mount, unmount, key: fpTrailerYoutubeKey,
  get muted() { return fpDetailHeroTrailerMuted; },
  setMuted: setFpDetailHeroTrailerMuted,
  open: openFpTrailerModal, close: closeFpTrailerModal, focusable: trailerModalFocusableElements,
  film: { configure: configureFpTrailer, schedule: scheduleFpDetailHeroTrailer, stop: stopFpDetailHeroTrailer },
  series: { configure: configureSeriesTrailer, schedule: scheduleSeriesDetailHeroTrailer, stop: stopSeriesDetailHeroTrailer },
};
}
