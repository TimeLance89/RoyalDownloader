import { reportError } from "./errors.js";

/** Shared client state only. Features retain their own server snapshots and filters. */
export function createStore(initial) {
  let value = Object.freeze({ ...initial });
  const listeners = new Set();
  return {
    get: () => value,
    set(patch) {
      if (!Object.keys(patch).some(key => !Object.is(value[key], patch[key]))) return;
      const previous = value;
      value = Object.freeze({ ...value, ...patch });
      for (const listener of [...listeners]) {
        try { listener(value, previous); } catch (error) { reportError(error); }
      }
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export const appStore = createStore({ user: null, language: "de", navigation: "home", connection: "disconnected" });
