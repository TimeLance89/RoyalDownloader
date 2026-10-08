import { delay } from "../../core/lifecycle.js";

export function freshMovieAvailability(movie) {
  return !!movie?.hosters?.length && Number(movie.availability?.expires_at) * 1000 > Date.now();
}

/** Closing one view only stops its polling; the server retains shared probes. */
export async function fetchMovieAvailability({ client, slug, tmdbId, signal,
  onUpdate = () => {}, budgetMs = 60_000, pause = delay, firstAvailable = false }) {
  const deadline = Date.now() + budgetMs;
  let latest, failures = 0;
  while (!signal?.aborted && Date.now() < deadline) {
    const id = Number(typeof tmdbId === "function" ? tmdbId() : tmdbId) || 0;
    const query = new URLSearchParams({ progressive: "true" });
    if (id > 0) query.set("tmdb_id", String(id));
    try {
      latest = await client.get(`/api/movie/${encodeURIComponent(slug)}?${query}`, {
        signal, timeoutMs: Math.min(5000, Math.max(1, deadline - Date.now())),
      });
      if (signal?.aborted) break;
      failures = 0;
      onUpdate(latest);
      if ((firstAvailable && latest.hosters?.length) || !latest.availability || latest.availability.complete !== false) return latest;
    } catch (error) {
      if (signal?.aborted) throw error;
      const transient = ["request_timeout", "network_error", "invalid_json", "movie_provider_unavailable", "movie_probe_pending"].includes(error.code);
      if (!transient || (++failures > 2 && error.code !== "movie_probe_pending")) throw error;
    }
    const interval = Math.min(5000, Math.max(600, failures * 2500, Number(latest?.availability?.retry_after_ms) || 1200));
    await pause(Math.min(interval, Math.max(1, deadline - Date.now())), signal);
  }
  if (signal?.aborted) throw new DOMException("Abgebrochen", "AbortError");
  if (latest?.hosters?.length) return latest;
  throw Object.assign(new Error("Quellenprüfung noch offen. Bitte erneut prüfen."), { code: "movie_probe_pending" });
}
