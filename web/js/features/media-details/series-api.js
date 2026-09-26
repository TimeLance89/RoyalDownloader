export function loadSeriesDetails(client, sampleSlug, baseSlug = "", { refreshJellyfin = false, deferChecks = false, signal } = {}) {
  const special = /^monster-tmdb:(\d+)$/i.exec(baseSlug || sampleSlug || "");
  return client.post(special ? "/api/series/monster-tmdb-load" : "/api/series/load", {
    ...(special ? { tmdb_id: Number(special[1]) } : { sample_slug: sampleSlug, base_slug: baseSlug }),
    refresh_jellyfin: refreshJellyfin, defer_checks: deferChecks,
  }, { signal });
}
