import { ApiError } from "./errors.js";

/** Cookie-authenticated JSON transport. No persistent cache for user data. */
export function createApi({ fetchImpl = (...args) => fetch(...args), timeoutMs = 30_000 } = {}) {
  const pending = new Map();
  const signalIds = new WeakMap();
  let nextSignalId = 0;
  let unauthorized = null;

  async function request(method, url, body, options = {}) {
    const controller = new AbortController();
    const signal = options.signal;
    let timedOut = false;
    const abort = () => controller.abort(signal.reason);
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    const timeout = options.timeoutMs ?? timeoutMs;
    const timer = timeout > 0 ? setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeout) : null;
    try {
      const headers = new Headers(options.headers);
      headers.set("Accept", "application/json");
      if (body !== undefined) headers.set("Content-Type", "application/json");
      const response = await fetchImpl(url, {
        method, headers, credentials: "same-origin", signal: controller.signal,
        ...(options.cache ? { cache: options.cache } : {}),
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      const raw = await response.text();
      let data = null;
      if (raw.trim()) {
        try { data = JSON.parse(raw); }
        catch (cause) {
          if (response.ok) throw new ApiError("Ungültige JSON-Antwort", {
            status: response.status, code: "invalid_json", cause,
          });
        }
      }
      if (!response.ok) {
        if (response.status === 401 && !String(url).startsWith("/api/auth/")) unauthorized?.();
        const detail = data?.detail || data?.error;
        throw new ApiError(typeof detail === "string" ? detail
          : detail?.message || detail?.code || `HTTP ${response.status}`, {
          status: response.status, code: detail?.code || "", resource: detail?.resource || "",
        });
      }
      return data;
    } catch (cause) {
      if (timedOut) throw new ApiError(options.timeoutMessage || "Die Anfrage hat zu lange gedauert.", {
        code: "request_timeout", cause,
      });
      if (controller.signal.aborted) throw new DOMException("Anfrage abgebrochen", "AbortError");
      if (cause instanceof ApiError) throw cause;
      throw new ApiError(cause.message || "Verbindung fehlgeschlagen", { code: "network_error", cause });
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }

  return {
    set onUnauthorized(callback) { unauthorized = callback; },
    get onUnauthorized() { return unauthorized; },
    request,
    get(url, options = {}) {
      // Requests owned by a view never share cancellation with another consumer.
      if (options.signal && !signalIds.has(options.signal)) signalIds.set(options.signal, ++nextSignalId);
      const key = JSON.stringify([url, options.timeoutMs, options.timeoutMessage, options.cache,
        [...new Headers(options.headers).entries()], options.signal ? signalIds.get(options.signal) : 0]);
      if (pending.has(key)) return pending.get(key);
      const result = request("GET", url, undefined, options).finally(() => {
        if (pending.get(key) === result) pending.delete(key);
      });
      pending.set(key, result);
      return result;
    },
    post: (url, body = {}, options) => request("POST", url, body, options),
    put: (url, body, options) => request("PUT", url, body, options),
    patch: (url, body, options) => request("PATCH", url, body, options),
    delete: (url, options) => request("DELETE", url, undefined, options),
  };
}

export const api = createApi();
