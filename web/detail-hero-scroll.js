// Hero trailers follow the visible detail header instead of playing off-screen.
const DETAIL_HERO_SCROLL_TARGETS = [
  {
    panel: "#fp-detail-panel",
    shell: "fp-detail-hero-trailer",
    frame: "fp-detail-hero-frame",
  },
  {
    panel: "#series-detail-modal .series-detail-panel",
    shell: "series-detail-hero-trailer",
    frame: "series-detail-hero-frame",
  },
];

function detailHeroScrollTarget(panel) {
  return DETAIL_HERO_SCROLL_TARGETS.find(
    (target) => document.querySelector(target.panel) === panel,
  ) || null;
}

function detailHeroScrolledPast(panel, shell) {
  const threshold = Math.min(180, Math.max(96, Number(shell?.clientHeight || 0) * .28));
  return Number(panel?.scrollTop || 0) > threshold;
}

function commandDetailHeroTrailer(frame, command) {
  if (!frame?.contentWindow) return;
  frame.contentWindow.postMessage(JSON.stringify({
    event: "command",
    func: command,
    args: [],
  }), "*");
}

function syncDetailHeroScrollPlayback(panel, { force = false } = {}) {
  const target = detailHeroScrollTarget(panel);
  if (!target) return;
  const shell = document.getElementById(target.shell);
  const frame = document.getElementById(target.frame);
  const active = Boolean(frame?.getAttribute("src") && !shell?.hidden);
  if (!active) {
    shell?.classList.remove("is-scroll-paused");
    if (shell) delete shell.dataset.scrollPlayback;
    return;
  }
  const shouldPause = detailHeroScrolledPast(panel, shell);
  const paused = shell.dataset.scrollPlayback === "paused";
  if (shouldPause && (!paused || force)) {
    commandDetailHeroTrailer(frame, "pauseVideo");
    shell.dataset.scrollPlayback = "paused";
    shell.classList.add("is-scroll-paused");
  } else if (!shouldPause && (paused || force)) {
    commandDetailHeroTrailer(frame, "playVideo");
    delete shell.dataset.scrollPlayback;
    shell.classList.remove("is-scroll-paused");
  }
}

function initDetailHeroScrollPlayback() {
  for (const target of DETAIL_HERO_SCROLL_TARGETS) {
    const panel = document.querySelector(target.panel);
    if (!panel || panel.dataset.heroScrollPlaybackBound === "true") continue;
    panel.dataset.heroScrollPlaybackBound = "true";
    let scheduled = false;
    panel.addEventListener("scroll", () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        syncDetailHeroScrollPlayback(panel);
      });
    }, { passive: true });
  }
}

document.addEventListener("DOMContentLoaded", initDetailHeroScrollPlayback);
