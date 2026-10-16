import { delay } from "../../core/lifecycle.js";

export async function loadSeriesDetails(client, sampleSlug, baseSlug = "", { refreshJellyfin = false, deferChecks = false, signal, waitForRetry = delay } = {}) {
  const deadline = Date.now() + 60_000;
  for (;;) {
    if (signal?.aborted) throw new DOMException("Abgebrochen", "AbortError");
    try { return await request(); }
    catch (error) {
      if (Number(error.status) !== 503 || !["series_details_pending", "series_details_busy"].includes(error.code)
          || (!signal && Date.now() >= deadline)) throw error;
      // A short HTTP wait releases server resources. The same bounded server
      // job supplies later retries; closing the detail cancels further polling.
      await waitForRetry(1000, signal);
    }
  }

  function request() {
    const personSeries = /^people-tmdb:(\d+)$/i.exec(baseSlug || sampleSlug || "");
    if (personSeries) return client.get(`/api/people/series/${personSeries[1]}?${new URLSearchParams({
      refresh_jellyfin: String(refreshJellyfin), defer_checks: String(deferChecks), progressive: "true",
    })}`, { signal, timeoutMs: 20_000 });
    const special = /^monster-tmdb:(\d+)$/i.exec(baseSlug || sampleSlug || "");
    return client.post(special ? "/api/series/monster-tmdb-load" : "/api/series/load", {
      ...(special ? { tmdb_id: Number(special[1]) } : { sample_slug: sampleSlug, base_slug: baseSlug }),
      refresh_jellyfin: refreshJellyfin, defer_checks: deferChecks, progressive: true,
    }, { signal, timeoutMs: 20_000 });
  }
}
