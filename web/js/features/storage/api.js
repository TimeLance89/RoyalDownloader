import { api } from "../../core/api.js";

/** Capture one view lifetime, including continuations of file mutations. */
export function createStorageApi(scope) {
  async function request(method, url, body) {
    if (!scope.active) throw new DOMException("Abgebrochen", "AbortError");
    const result = await api.request(method, url, body, { signal: scope.signal });
    if (!scope.active) throw new DOMException("Abgebrochen", "AbortError");
    return result;
  }
  return {
    get: url => request("GET", url),
    post: (url, body) => request("POST", url, body),
  };
}
