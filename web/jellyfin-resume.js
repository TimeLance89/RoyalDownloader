// Browser-Standby und lange Hintergrundphasen dürfen keine alten
// Jellyfin-Prüfungen dauerhaft in der Oberfläche stehen lassen.
const JELLYFIN_RESUME_IDLE_MS = 60_000;
const JELLYFIN_RESUME_COOLDOWN_MS = 10_000;
let jellyfinResumeInactiveAt = 0;
let jellyfinResumeLastPulseAt = Date.now();
let jellyfinResumeLastRefreshAt = 0;

function runJellyfinResumeRefresh() {
  if (document.hidden) return false;
  const now = Date.now();
  if (now - jellyfinResumeLastRefreshAt < JELLYFIN_RESUME_COOLDOWN_MS) {
    return false;
  }
  jellyfinResumeLastRefreshAt = now;
  const refreshes = [
    ["Katalog", () => refreshAllCatalogJellyfinStatuses()],
    ["Filme", () => refreshFpJellyfinStatus()],
    ["Serie", () => refreshSeriesJellyfinStatus(true)],
  ];
  for (const [label, refresh] of refreshes) {
    Promise.resolve()
      .then(refresh)
      .catch((error) => console.warn(`${label}-Jellyfin-Abgleich nach Standby fehlgeschlagen:`, error));
  }
  return true;
}

function markJellyfinResumeInactive() {
  if (!jellyfinResumeInactiveAt) jellyfinResumeInactiveAt = Date.now();
}

function resumeJellyfinAfterIdle(force = false) {
  const now = Date.now();
  const idleFor = jellyfinResumeInactiveAt ? now - jellyfinResumeInactiveAt : 0;
  const pulseGap = now - jellyfinResumeLastPulseAt;
  jellyfinResumeInactiveAt = 0;
  jellyfinResumeLastPulseAt = now;
  if (force || idleFor >= JELLYFIN_RESUME_IDLE_MS || pulseGap >= JELLYFIN_RESUME_IDLE_MS) {
    return runJellyfinResumeRefresh();
  }
  return false;
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) markJellyfinResumeInactive();
  else resumeJellyfinAfterIdle();
});
window.addEventListener("blur", markJellyfinResumeInactive);
window.addEventListener("focus", () => resumeJellyfinAfterIdle());
window.addEventListener("pageshow", (event) => resumeJellyfinAfterIdle(Boolean(event.persisted)));
window.addEventListener("online", () => runJellyfinResumeRefresh());

setInterval(() => {
  const now = Date.now();
  const pulseGap = now - jellyfinResumeLastPulseAt;
  jellyfinResumeLastPulseAt = now;
  if (!document.hidden && pulseGap >= JELLYFIN_RESUME_IDLE_MS) {
    runJellyfinResumeRefresh();
  }
}, 15_000);
