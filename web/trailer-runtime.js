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
  if (activeTrailerLoadTimer) clearTimeout(activeTrailerLoadTimer);
  activeTrailerLoadTimer = null;
  const frame = document.getElementById("fp-trailer-frame");
  if (frame) frame.onload = null;
  activeTrailerPlayback = null;
  setTrailerPlayerState("idle");
}

function startTrailerPlayback() {
  if (!activeTrailerPlayback) return;
  const { key, startAt } = activeTrailerPlayback;
  const frame = document.getElementById("fp-trailer-frame");
  if (!frame) return;
  if (activeTrailerLoadTimer) clearTimeout(activeTrailerLoadTimer);
  setTrailerPlayerState("loading");
  frame.onload = () => {
    if (activeTrailerLoadTimer) clearTimeout(activeTrailerLoadTimer);
    activeTrailerLoadTimer = null;
    setTrailerPlayerState("ready");
    listenForHeroTrailerTime(frame);
  };
  frame.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
    + `?autoplay=1&rel=0&playsinline=1&enablejsapi=1`
    + `${startAt >= 1 ? `&start=${Math.floor(startAt)}` : ""}`
    + `&origin=${encodeURIComponent(window.location.origin)}`;
  activeTrailerLoadTimer = window.setTimeout(() => {
    setTrailerPlayerState("error", "YouTube antwortet nicht. Erneut versuchen oder extern öffnen.");
  }, 10000);
}

function openTrailerPlayer(movie, key, startAt, trigger) {
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
  requestAnimationFrame(() => document.getElementById("fp-trailer-close")?.focus());
}

function handleTrailerPlayerMessage(event, payload) {
  const frame = document.getElementById("fp-trailer-frame");
  if (!frame || event.source !== frame.contentWindow) return false;
  if (payload?.event === "onError") {
    if (activeTrailerLoadTimer) clearTimeout(activeTrailerLoadTimer);
    activeTrailerLoadTimer = null;
    setTrailerPlayerState("error", "Dieser Trailer ist bei YouTube nicht verfügbar.");
  } else if (payload?.event === "onReady") {
    if (activeTrailerLoadTimer) clearTimeout(activeTrailerLoadTimer);
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

function initializeTrailerExperience() {
  document.getElementById("fp-trailer-retry")?.addEventListener("click", startTrailerPlayback);
  document.getElementById("fp-trailer-autoplay")?.addEventListener("change", (event) => {
    setHeroTrailerAutoplay(event.currentTarget.checked);
  });
  document.getElementById("fp-trailer-focus-end")?.addEventListener("focus", () => {
    document.getElementById("fp-trailer-close")?.focus();
  });
}
