import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { createStore } from "../../core/store.js";
import { isAbortError } from "../../core/errors.js";
import { calendarNormalizeSnapshotPayload } from "./model.js";

export const SERIES_CALENDAR_WATCHDOG_MS = 16_000;

/** One read-only server snapshot; no permanent polling or global timer. */
export function createCalendarState({ cache, client = api, document: doc = globalThis.document, deadlineMs = SERIES_CALENDAR_WATCHDOG_MS }) {
  const store = createStore({ days: [], total: 0, loaded: false, loading: false, phase: "idle", error: "", stale: false, cached: false, updatedAt: 0 });
  let pending;
  function refresh(force = false) {
    if (pending) return pending.promise;
    if (store.get().loaded && !force) return Promise.resolve(false);
    const scope = createScope();
    const startedAt = Date.now();
    const task = { scope };
    pending = task;
    const deadline = new Promise((resolve, reject) => {
      const expire = () => reject(new Error("Der Kalenderdienst hat das Zeitlimit überschritten."));
      scope.timeout(expire, deadlineMs);
      if (doc) scope.listen(doc, "visibilitychange", () => { if (!doc.hidden && Date.now() - startedAt >= deadlineMs) expire(); });
      scope.listen(scope.signal, "abort", () => reject(new DOMException("Abgebrochen", "AbortError")), { once: true });
    });
    task.promise = Promise.race([
      client.get(`/api/series-calendar${force ? "?refresh=true" : ""}`, {
        signal: scope.signal, timeoutMs: 15_000,
        timeoutMessage: "Der Kalenderdienst hat nach 15 Sekunden nicht geantwortet.",
      }), deadline,
    ]).then(response => {
      if (!scope.active) return false;
      if (!response?.ready && !response?.days?.length) throw new Error(response?.error || "Der Server hat noch keinen gültigen Sendeplan.");
      const payload = calendarNormalizeSnapshotPayload(response);
      store.set({ ...payload, loaded: true, loading: false, phase: "ready", error: "", cached: Boolean(response.stale), updatedAt: Number(response.updated_at || 0) * 1000 || Date.now() });
      cache.storeSnapshot(payload);
      return true;
    }).catch(error => {
      if (scope.active && !isAbortError(error)) {
        const loaded = store.get().loaded;
        store.set({ error: error.message || "Unbekannter Kalenderfehler", loading: false, phase: loaded ? "ready" : "error", stale: loaded, cached: loaded });
      }
      return false;
    }).finally(() => { scope.dispose(); if (pending === task) pending = null; });
    store.set({ loading: true, phase: "loading", error: "" });
    return task.promise;
  }
  return {
    get: store.get, subscribe: store.subscribe, refresh,
    restore() {
      const cached = cache.restoreSnapshot();
      if (!cached) return false;
      store.set({ ...cached.payload, loaded: true, phase: "ready", stale: true, cached: true, updatedAt: cached.savedAt });
      return true;
    },
    unmount() {
      pending?.scope.dispose(); pending = null;
      store.set({ loading: false, phase: store.get().loaded ? "ready" : "idle" });
    },
  };
}
