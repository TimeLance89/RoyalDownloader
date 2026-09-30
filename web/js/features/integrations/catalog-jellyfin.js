import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Shared media-availability snapshot. Integration health has a separate contract. */
export function createCatalogJellyfin({ uniqueHomeEntries, homeEntryKey, getMovieMetadata, getMovieInstances, client = api }) {
  let owner = createScope();
  let catalogJellyfinRequestSequence = 0;
  const catalogJellyfinRequestByKey = new Map(), statuses = new Map();
  function beginCatalogJellyfinRequest(keys) {
    const sequence = ++catalogJellyfinRequestSequence;
    keys.forEach(key => catalogJellyfinRequestByKey.set(key, sequence)); return sequence;
  }
  function isCurrentCatalogJellyfinRequest(key, sequence) { return catalogJellyfinRequestByKey.get(key) === sequence; }
  function applyMovieJellyfinStatus(slug, status, owned = null) {
    const resolvedOwned = typeof owned === "boolean" ? owned : status === "owned" ? true : status === "missing" ? false : null;
    for (const movie of new Set(getMovieInstances(slug).filter(Boolean))) {
      movie.jellyfin_status = status;
      if (typeof resolvedOwned === "boolean") movie.in_jellyfin = resolvedOwned;
    }
    statuses.set(`movie:${slug}`, status);
  }
async function refreshCatalogJellyfinStatus(entries, render, { signal } = {}) {
  if (!owner.active || signal?.aborted) return;
  const targets = entries.filter(entry => entry.kind !== "collection");
  const unique = uniqueHomeEntries(targets);
  if (!unique.length) return;
  const current = createScope();
  const release = owner.add(() => current.dispose());
  const abort = () => current.dispose();
  signal?.addEventListener("abort", abort, { once: true });
  try {
  const requests = unique.map(({ kind, item }) => {
    const metadata = kind === "movie" ? (getMovieMetadata()[item.slug] || {}) : {};
    return {
      slug: homeEntryKey({ kind, item }),
      title: metadata.title || item.title,
      year: metadata.year || item.year || "",
      tmdb_id: metadata.tmdb_id || item.tmdb_id || null,
      media_type: kind === "movie" ? "movie" : "series",
    };
  });
  const requestSequence = beginCatalogJellyfinRequest(requests.map((item) => item.slug));
  const statusByKey = new Map();
  const batches = [];
  for (let index = 0; index < requests.length; index += 100) {
    batches.push(requests.slice(index, index + 100));
  }
  const responses = await Promise.allSettled(
    batches.map((batch) => client.post("/api/jellyfin/matches", { items: batch }, { signal: current.signal, timeoutMs: 15_000, timeoutMessage: "Die Jellyfin-Statusprüfung hat nicht rechtzeitig geantwortet." })),
  );
  if (!current.active) return;
  responses.forEach((result, batchIndex) => {
    const batch = batches[batchIndex];
    if (result.status !== "fulfilled") {
      const status = [401, 403].includes(Number(result.reason?.status))
        ? "blocked" : "unavailable";
      batch.forEach((request) => statusByKey.set(request.slug, status));
      return;
    }
    const response = result.value;
    batch.forEach((request) => {
      const status = response.statuses?.[request.slug]
        || (Object.hasOwn(response.matches || {}, request.slug)
          ? (response.matches[request.slug] ? "owned" : "missing")
          : (response.configured ? "unavailable" : "unconfigured"));
      statusByKey.set(request.slug, status);
    });
  });
  const appliedMovieKeys = new Set();
  for (const entry of targets) {
    const key = homeEntryKey(entry);
    if (!isCurrentCatalogJellyfinRequest(key, requestSequence)) continue;
    const status = statusByKey.get(key) || "unavailable";
    if (entry.kind === "movie") {
      if (appliedMovieKeys.has(key)) continue;
      appliedMovieKeys.add(key);
      applyMovieJellyfinStatus(entry.item.slug, status);
      continue;
    }
    // A series can exist as distinct object instances in Home, discovery and
    // global search. The request is deduplicated by identity, but the resolved
    // status must be propagated to every visible instance of that identity.
    statuses.set(key, status);
    entry.item.jellyfin_status = status;
    if (status === "owned" || status === "missing") {
      entry.item.in_jellyfin = status === "owned";
    } else {
      delete entry.item.in_jellyfin;
    }
  }
  if (render) render();
  } finally { signal?.removeEventListener("abort", abort); release(); }
}

  return {
    getStatus: key => statuses.get(key), applyMovie: applyMovieJellyfinStatus, refresh: refreshCatalogJellyfinStatus,
    mount() { if (!owner.active) owner = createScope(); },
    unmount() { owner.dispose(); catalogJellyfinRequestByKey.clear(); },
  };
}
