/** Existing deterministic diversity ranking; no browser or server state. */
export function createTasteCandidates({ homeEntryMedia, homeEntryKey, tasteMetadata }) {
function tasteOnboardingGenreName(genre) {
  return String(typeof genre === "object" ? genre?.name || genre?.label || "" : genre || "").trim();
}

function tasteOnboardingRuntime(value) {
  const minutes = Number(String(value || "").match(/\d+/)?.[0] || 0);
  if (!minutes) return "";
  if (minutes < 60) return `${minutes} Min.`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} Std.${rest ? ` ${rest} Min.` : ""}`;
}

function tasteOnboardingEntryData(entry) {
  const media = homeEntryMedia(entry);
  const year = String(media.year || media.release_date || media.first_air_date || "").match(/\b(19|20)\d{2}\b/)?.[0] || "";
  const genres = [...new Set((media.genres || []).map(tasteOnboardingGenreName).filter(Boolean))];
  const rating = Number(media.rating || media.vote_average || media.score || 0);
  return {
    entry,
    key: homeEntryKey(entry),
    title: String(media.title || media.name || "").trim(),
    kind: entry.kind,
    kindLabel: entry.kind === "movie" ? "Film" : entry.kind === "anime" ? "Anime" : "Serie",
    year,
    decade: year ? `${year.slice(0, 3)}0` : "unknown",
    genres,
    artwork: media.cover_url || media.poster_url || media.backdrop_url || "",
    description: String(media.description || media.overview || media.synopsis || "").trim(),
    rating: Number.isFinite(rating) && rating > 0 ? Math.min(10, rating) : 0,
    runtime: tasteOnboardingRuntime(media.runtime || media.duration),
    metadata: tasteMetadata(entry.kind, media),
  };
}

function tasteOnboardingHash(value) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function diverseTasteOnboardingCandidates(entries, page = 0) {
  const unique = new Map();
  entries.map(tasteOnboardingEntryData).forEach((item) => {
    if (item.key && item.title && item.artwork && !unique.has(item.key)) unique.set(item.key, item);
  });
  const pool = [...unique.values()].sort((a, b) =>
    tasteOnboardingHash(`${page}|${a.key}`) - tasteOnboardingHash(`${page}|${b.key}`));
  const selected = [];
  const genreCounts = new Map();
  const kindCounts = new Map();
  const decadeCounts = new Map();
  while (pool.length) {
    let bestIndex = 0;
    let bestScore = -Infinity;
    pool.forEach((item, index) => {
      const unseenGenres = item.genres.filter((genre) => !genreCounts.has(genre)).length;
      const genrePressure = item.genres.reduce((sum, genre) => sum + (genreCounts.get(genre) || 0), 0);
      const score = unseenGenres * 8
        - genrePressure * 2.4
        - (kindCounts.get(item.kind) || 0) * 1.4
        - (decadeCounts.get(item.decade) || 0) * .55
        + ((tasteOnboardingHash(`${page}:${item.key}:tie`) % 1000) / 1000);
      if (score > bestScore) { bestScore = score; bestIndex = index; }
    });
    const [picked] = pool.splice(bestIndex, 1);
    selected.push(picked);
    picked.genres.forEach((genre) => genreCounts.set(genre, (genreCounts.get(genre) || 0) + 1));
    kindCounts.set(picked.kind, (kindCounts.get(picked.kind) || 0) + 1);
    decadeCounts.set(picked.decade, (decadeCounts.get(picked.decade) || 0) + 1);
  }
  return selected;
}


return { diverse: diverseTasteOnboardingCandidates, hash: tasteOnboardingHash };
}
