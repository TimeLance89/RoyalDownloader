/** Shared discovery identities and catalog projections, independent of the DOM. */
export function createHomeCatalog({
  getData, getHomeSearchResults, getSearchResults, getAnimeResults, getMovieMetadata,
  getShuffle = () => 0,
}) {
  function homeMovieInstances(slug) {
    return [
      ...getData().newMovies,
      ...getData().topMovies,
      ...(getData().cinemaMovies || []),
      ...getData().discoveryMovies,
      ...getHomeSearchResults().filter((entry) => entry.kind === "movie").map((entry) => entry.item),
      ...getSearchResults().filter((entry) => entry.kind === "movie").map((entry) => entry.item),
    ]
      .filter((item) => item.slug === slug);
  }

  function homeMovieBySlug(slug) {
    return homeMovieInstances(slug)[0] || null;
  }

  function homeSeriesBySlug(baseSlug) {
    return [
      ...getData().trendingSeries,
      ...getData().newSeries,
      ...getData().discoverySeries,
      ...getHomeSearchResults().filter((entry) => entry.kind === "series").map((entry) => entry.item),
      ...getSearchResults().filter((entry) => entry.kind === "series").map((entry) => entry.item),
    ]
      .find((item) => item.base_slug === baseSlug) || null;
  }

  function homeAnimeById(id) {
    const aniworld = String(id).startsWith("aniworld:");
    const wantedId = aniworld ? String(id).slice("aniworld:".length) : String(id);
    return [
      ...getAnimeResults(),
      ...getSearchResults().filter((entry) => entry.kind === "anime").map((entry) => entry.item),
    ].find((item) => String(item.id) === wantedId && (item.provider === "aniworld") === aniworld) || null;
  }

  function mediaJellyfinStatus(media) {
    if (media?.jellyfin_status) return media.jellyfin_status;
    if (typeof media?.in_jellyfin === "boolean") return media.in_jellyfin ? "owned" : "missing";
    return "checking";
  }

  function uniqueHomeEntries(entries) {
    const seen = new Set();
    return entries.filter((entry) => {
      if (!entry?.item) return false;
      const key = homeEntryKey(entry);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function interleaveHomeEntries(primary, secondary, limit = 20) {
    const mixed = [];
    const max = Math.max(primary.length, secondary.length);
    for (let index = 0; index < max && mixed.length < limit; index += 1) {
      if (primary[index]) mixed.push(primary[index]);
      if (secondary[index] && mixed.length < limit) mixed.push(secondary[index]);
    }
    return uniqueHomeEntries(mixed).slice(0, limit);
  }

  function homeMovieEntry(item) {
    return { kind: "movie", item };
  }

  function homeSeriesEntry(item) {
    return { kind: "series", item };
  }

  function homeAnimeEntry(item) {
    return { kind: "anime", item };
  }

  function homeEntryKey(entry) {
    if (!entry?.item) return "";
    if (entry.kind === "collection") return `collection:${entry.item.collection_id}`;
    const key = entry.kind === "movie"
      ? entry.item.slug
      : entry.kind === "anime" ? `${entry.item.provider === "aniworld" ? "aniworld:" : ""}${entry.item.id}` : entry.item.base_slug;
    return `${entry.kind}:${key}`;
  }

  function homeEntryMedia(entry) {
    if (!entry?.item) return {};
    const metadata = entry.kind === "movie"
      ? (getMovieMetadata()[entry.item.slug] || {})
      : {};
    return { ...entry.item, ...metadata };
  }

  function canonicalHomeText(value) {
    return String(value || "")
      .replace(/\s*\[[^\]]{1,40}\]\s*$/g, "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase("de-DE")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function homeContentKeys(entry) {
    if (entry?.kind === "collection") return [`collection:tmdb:${entry.item.collection_id}`];
    const media = homeEntryMedia(entry);
    const kind = entry?.kind === "movie" ? "movie" : "series";
    const tmdbId = String(media.tmdb_id || media.tmdbId || "").trim();
    const title = canonicalHomeText(media.title || media.name);
    const year = String(
      media.year
      || media.release_year
      || media.release_date
      || media.first_air_date
      || "",
    ).match(/\b(19|20)\d{2}\b/)?.[0] || "";
    const keys = [];
    if (tmdbId) keys.push(`${kind}:tmdb:${tmdbId}`);
    if (title) keys.push(`${kind}:title:${title}:${year}`);
    return keys.length ? keys : [homeEntryKey(entry)];
  }

  function homeContentKey(entry) {
    return homeContentKeys(entry)[0];
  }

  function uniqueHomeContentEntries(entries) {
    const seen = new Set();
    return entries.filter((entry) => {
      if (!entry?.item) return false;
      const keys = homeContentKeys(entry);
      if (keys.some((key) => seen.has(key))) return false;
      keys.forEach((key) => seen.add(key));
      return true;
    });
  }

  function localDateKey(date = new Date()) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function stableDiscoveryHash(value) {
    let hash = 2166136261;
    for (const char of String(value)) {
      hash ^= char.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function stableDailyOrder(entries, lane) {
    const seed = `${localDateKey()}|${Number(getShuffle() || 0)}|${lane}`;
    return entries.slice().sort((a, b) =>
      stableDiscoveryHash(`${seed}|${homeEntryKey(a)}`)
      - stableDiscoveryHash(`${seed}|${homeEntryKey(b)}`));
  }

  return { homeMovieInstances, homeMovieBySlug, homeSeriesBySlug, homeAnimeById, mediaJellyfinStatus, uniqueHomeEntries, interleaveHomeEntries, homeMovieEntry, homeSeriesEntry, homeAnimeEntry, homeEntryKey, homeEntryMedia, canonicalHomeText, homeContentKeys, homeContentKey, uniqueHomeContentEntries, localDateKey, stableDiscoveryHash, stableDailyOrder };
}
