import { api } from "../../core/api.js";

export const releaseRequest = (path, { method = "GET", body, signal } = {}) =>
  api.request(method, path, body, { signal, timeoutMs: 15_000 });
