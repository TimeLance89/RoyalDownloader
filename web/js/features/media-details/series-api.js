import { delay } from "../../core/lifecycle.js";

export async function loadSeriesDetails(client, sampleSlug, baseSlug = "", { refreshJellyfin = false, deferChecks = false, signal, waitForRetry = delay, now = () => Date.now() } = {}) {
  const deadline = now() + 35_000;
  let pendingError = Object.assign(new Error("Das Einlesen der Staffeln hat zu lange gedauert."), {
    status: 503, code: "series_details_pending",
  });
  for (;;) {
    if (signal?.aborted) throw new DOMException("Abgebrochen", "AbortError");
    if (now() >= deadline) throw pendingError;
    try { return await request(); }
    catch (error) {
      if (Number(error.status) !== 503 || !["series_details_pending", "series_details_busy"].includes(error.code)
          || now() >= deadline) throw error;
      // A short HTTP wait releases server resources. The same bounded server
      // job supplies later retries; closing the detail cancels further polling.
      pendingError = error;
      await waitForRetry(Math.min(1000, deadline - now()), signal);
    }
  }

  function request() {
    const timeoutMs = Math.max(1, Math.min(20_000, deadline - now()));
    const personSeries = /^(?:people-tmdb:|tmdb:)(\d+)$/i.exec(baseSlug || sampleSlug || "");
    if (personSeries) return client.get(`/api/people/series/${personSeries[1]}?${new URLSearchParams({
      refresh_jellyfin: String(refreshJellyfin), defer_checks: String(deferChecks), progressive: "true",
    })}`, { signal, timeoutMs });
    const special = /^monster-tmdb:(\d+)$/i.exec(baseSlug || sampleSlug || "");
    return client.post(special ? "/api/series/monster-tmdb-load" : "/api/series/load", {
      ...(special ? { tmdb_id: Number(special[1]) } : { sample_slug: sampleSlug, base_slug: baseSlug }),
      refresh_jellyfin: refreshJellyfin, defer_checks: deferChecks, progressive: true,
    }, { signal, timeoutMs });
  }
}
