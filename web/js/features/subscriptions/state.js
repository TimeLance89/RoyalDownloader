import { api } from "../../core/api.js";
import { createStore } from "../../core/store.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { websocket } from "../../core/websocket.js";

/** Both subscription contracts share request ownership; each instance owns its snapshot. */
export function createSubscriptions({ client = api, socket = websocket, onPersistence = () => {}, kind = "series" } = {}) {
  const movies = kind === "movies";
  const path = movies ? "/api/movie-subscriptions" : "/api/watchlist";
  const collection = movies ? "movie_subscriptions" : "watchlist";
  const store = createStore({ items: [], health: { error: "", checking_count: 0 }, loaded: false, checkRunning: false, status: "idle", error: "" });
  let scope;
  let revision = 0;
  let readTask;
  let checkTask;

  function accept(payload) {
    if (!scope?.active) return false;
    revision++;
    onPersistence(payload.persistence);
    store.set({ items: payload[collection] || [], health: payload.health || store.get().health, loaded: true, status: "ready", error: "" });
    return true;
  }
  function operation(signal) {
    const child = createScope();
    const release = scope.add(() => child.dispose());
    if (signal?.aborted) child.dispose();
    else if (signal) child.listen(signal, "abort", () => child.dispose(), { once: true });
    return { child, release };
  }
  function refresh({ signal, shouldApply, force = false } = {}) {
    if (!scope?.active) return Promise.resolve(false);
    if (readTask?.child.active && !force) return readTask.promise;
    readTask?.child.dispose();
    const task = operation(signal);
    const version = revision;
    readTask = task;
    task.promise = client.get(path, { signal: task.child.signal }).then(payload => {
      if (!task.child.active || revision !== version || (shouldApply && !shouldApply())) return false;
      return accept(payload);
    }).catch(error => {
      if (task.child.active && !isAbortError(error) && revision === version) store.set({ status: "error", error: error.message || String(error) });
      return false;
    }).finally(() => {
      task.release();
      if (readTask === task) readTask = null;
    });
    store.set({ status: "loading", error: "" });
    return task.promise;
  }
  function check(slugs = null, { signal } = {}) {
    if (!scope?.active || signal?.aborted) return Promise.reject(new DOMException("Abgebrochen", "AbortError"));
    if (checkTask?.child.active) return checkTask.promise;
    const task = operation(signal);
    const version = revision;
    checkTask = task;
    task.promise = client.post(`${path}/check`, { [movies ? "keys" : "base_slugs"]: slugs || null }, { signal: task.child.signal }).then(payload => {
      if (!task.child.active) throw new DOMException("Abgebrochen", "AbortError");
      if (revision === version) accept(payload);
      return payload;
    }).finally(() => {
      task.release();
      if (checkTask === task) { checkTask = null; store.set({ checkRunning: false }); }
    });
    store.set({ checkRunning: true });
    return task.promise;
  }
  return {
    get: store.get, subscribe: store.subscribe, accept, refresh, check,
    get revision() { return revision; },
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.add(socket.subscribe(movies ? "movie_subscriptions_update" : "watchlist_update", accept));
      if (!movies) scope.add(socket.subscribe("jellyfin_update", data => { if (data.watchlist) accept(data); }));
      scope.add(socket.subscribe("connection.open", () => { void refresh({ force: true }); }));
    },
    unmount() {
      scope?.dispose(); scope = null;
      readTask = null; checkTask = null;
      store.set({ checkRunning: false });
    },
  };
}
