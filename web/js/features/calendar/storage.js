import { calendarNormalizeSnapshotPayload } from "./model.js";

const SNAPSHOT_KEY = "royal.series-calendar.v2";
const FILTERS_KEY = "royal.series-calendar.filters.v1";
export const SERIES_CALENDAR_CACHE_MAX_AGE = 30 * 24 * 60 * 60 * 1_000;

export function createCalendarStorage(storage) {
  if (storage === undefined) {
    try { storage = globalThis.localStorage; } catch { storage = null; }
  }
  const filterKey = userId => userId ? `${FILTERS_KEY}:${userId}` : FILTERS_KEY;
  return {
    restoreSnapshot() {
      try {
        const cached = JSON.parse(storage.getItem(SNAPSHOT_KEY) || "null");
        const savedAt = Number(cached?.saved_at || 0);
        if (!savedAt || Date.now() - savedAt > SERIES_CALENDAR_CACHE_MAX_AGE) return null;
        return { payload: calendarNormalizeSnapshotPayload(cached.payload), savedAt };
      } catch {
        try { storage.removeItem(SNAPSHOT_KEY); } catch { /* Private mode. */ }
        return null;
      }
    },
    storeSnapshot(payload) {
      try { storage.setItem(SNAPSHOT_KEY, JSON.stringify({ saved_at: Date.now(), payload: { ...payload, stale: false } })); } catch { /* Storage limit/private mode. */ }
    },
    restoreFilters(userId) {
      const result = {};
      try {
        const saved = JSON.parse(storage.getItem(filterKey(userId)) || "null");
        if (!saved || typeof saved !== "object") return result;
        if (["all", "1", "2", "3"].includes(saved.language)) result.language = saved.language;
        if (["all", "released", "upcoming"].includes(saved.status)) result.status = saved.status;
        if (["day", "week"].includes(saved.view)) result.view = saved.view;
        result.subscribedOnly = Boolean(saved.subscribedOnly);
        result.query = String(saved.query || "").slice(0, 120);
      } catch { /* Invalid old preferences. */ }
      return result;
    },
    storeFilters(userId, { language, status, view, subscribedOnly, query }) {
      try { storage.setItem(filterKey(userId), JSON.stringify({ language, status, view, subscribedOnly, query })); } catch { /* Storage limit/private mode. */ }
    },
  };
}
