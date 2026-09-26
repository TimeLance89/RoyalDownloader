import { createScope } from "../../core/lifecycle.js";

/** App-wide idle detector; periodic pulses only detect suspended browser clocks. */
export function createJellyfinResume({ refreshAllCatalogJellyfinStatuses, refreshFpJellyfinStatus,
  refreshSeriesJellyfinStatus, document = globalThis.document, window = globalThis.window, now = Date.now }) {
  let scope;
const JELLYFIN_RESUME_IDLE_MS = 60_000;
const JELLYFIN_RESUME_COOLDOWN_MS = 10_000;
let jellyfinResumeInactiveAt = 0;
let jellyfinResumeLastPulseAt = now();
let jellyfinResumeLastRefreshAt = 0;

function runJellyfinResumeRefresh() {
  if (!scope?.active || document.hidden) return false;
  const timestamp = now();
  if (timestamp - jellyfinResumeLastRefreshAt < JELLYFIN_RESUME_COOLDOWN_MS) {
    return false;
  }
  jellyfinResumeLastRefreshAt = timestamp;
  const refreshes = [
    ["Katalog", () => refreshAllCatalogJellyfinStatuses()],
    ["Filme", () => refreshFpJellyfinStatus()],
    ["Serie", () => refreshSeriesJellyfinStatus(true)],
  ];
  const current = scope;
  for (const [label, refresh] of refreshes) {
    Promise.resolve()
      .then(() => { if (current.active) return refresh(); })
      .catch((error) => { if (current.active) console.warn(`${label}-Jellyfin-Abgleich nach Standby fehlgeschlagen:`, error); });
  }
  return true;
}

function markJellyfinResumeInactive() {
  if (!jellyfinResumeInactiveAt) jellyfinResumeInactiveAt = now();
}

function resumeJellyfinAfterIdle(force = false) {
  const timestamp = now();
  const idleFor = jellyfinResumeInactiveAt ? timestamp - jellyfinResumeInactiveAt : 0;
  const pulseGap = timestamp - jellyfinResumeLastPulseAt;
  jellyfinResumeInactiveAt = 0;
  jellyfinResumeLastPulseAt = timestamp;
  if (force || idleFor >= JELLYFIN_RESUME_IDLE_MS || pulseGap >= JELLYFIN_RESUME_IDLE_MS) {
    return runJellyfinResumeRefresh();
  }
  return false;
}


  return {
    refresh: runJellyfinResumeRefresh,
    mount({ resumed = false } = {}) {
      if (scope) return; scope = createScope();
      scope.listen(document, "visibilitychange", () => {
        if (document.hidden) markJellyfinResumeInactive(); else resumeJellyfinAfterIdle();
      });
      scope.listen(window, "blur", markJellyfinResumeInactive);
      scope.listen(window, "focus", () => resumeJellyfinAfterIdle());
      scope.listen(window, "online", runJellyfinResumeRefresh);
      // No server request on normal ticks. A gap detects OS/browser suspension.
      scope.interval(() => {
        const timestamp = now(), pulseGap = timestamp - jellyfinResumeLastPulseAt;
        jellyfinResumeLastPulseAt = timestamp;
        if (!document.hidden && pulseGap >= JELLYFIN_RESUME_IDLE_MS) runJellyfinResumeRefresh();
      }, 15_000);
      if (resumed) resumeJellyfinAfterIdle(true);
    },
    unmount() { scope?.dispose(); scope = null; },
  };
}
