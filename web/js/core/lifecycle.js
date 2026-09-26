import { reportError } from "./errors.js";

export function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    let timer;
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Abgebrochen", "AbortError"));
    };
    if (signal?.aborted) return abort();
    signal?.addEventListener("abort", abort, { once: true });
    timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, ms);
  });
}

/** One scope per mounted view. Dispose is idempotent, including after partial mount. */
export function createScope() {
  const controller = new AbortController();
  const cleanups = new Set();
  const add = cleanup => {
    if (controller.signal.aborted) cleanup();
    else cleanups.add(cleanup);
    return () => { if (cleanups.delete(cleanup)) cleanup(); };
  };
  return {
    signal: controller.signal,
    get active() { return !controller.signal.aborted; },
    add,
    listen(target, event, callback, options) {
      if (controller.signal.aborted) return () => {};
      const listenerOptions = typeof options === "boolean" ? { capture: options } : options;
      target.addEventListener(event, callback, listenerOptions);
      return add(() => target.removeEventListener(event, callback, listenerOptions));
    },
    timeout(callback, delay) {
      if (controller.signal.aborted) return () => {};
      const cleanup = () => clearTimeout(timer);
      const timer = setTimeout(() => {
        cleanups.delete(cleanup);
        if (!controller.signal.aborted) callback();
      }, delay);
      return add(cleanup);
    },
    interval(callback, delay) {
      if (controller.signal.aborted) return () => {};
      const timer = setInterval(callback, delay);
      return add(() => clearInterval(timer));
    },
    frame(callback) {
      if (controller.signal.aborted) return () => {};
      const cleanup = () => cancelAnimationFrame(frame);
      const frame = requestAnimationFrame(() => {
        cleanups.delete(cleanup);
        if (!controller.signal.aborted) callback();
      });
      return add(cleanup);
    },
    observe(observer) { return add(() => observer.disconnect()); },
    dispose() {
      if (controller.signal.aborted) return;
      controller.abort();
      for (const cleanup of [...cleanups].reverse()) {
        cleanups.delete(cleanup);
        try { cleanup(); } catch (error) { reportError(error); }
      }
    },
  };
}
