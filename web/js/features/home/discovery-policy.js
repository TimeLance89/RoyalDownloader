/** Persisted exposure, logical identity and diversity used by native Home sections. */
export function createDiscoveryPolicy({
  storage = globalThis.localStorage, personalStorageKey, homeEntryMedia, homeEntryKey,
  localDateKey, getShuffle, stableDiscoveryHash, mediaContentLanguages, getHomeData,
  homeMovieEntry, homeSeriesEntry, allowedHomeEntries, uniqueHomeEntries, normalizeUiContentLanguage,
}) {
  const localStorage = storage;
const HOME_DISCOVERY_V2_EXPOSURE_KEY = "royal-home-exposure-v2";
const HOME_DISCOVERY_V2_HISTORY_DAYS = 21;

function discoveryV2Normalize(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/gi, "")
    .toLowerCase();
}

function discoveryV2LogicalKey(entry) {
  if (!entry?.item) return "";
  const media = typeof homeEntryMedia === "function" ? homeEntryMedia(entry) : entry.item;
  if (media.tmdb_id) return `${entry.kind}:tmdb:${media.tmdb_id}`;
  const year = String(media.year || media.first_air_date || "").slice(0, 4);
  return `${entry.kind}:${discoveryV2Normalize(media.title)}:${year}`;
}

function discoveryV2DayDistance(day) {
  const then = new Date(`${day}T12:00:00`);
  const now = new Date(`${localDateKey()}T12:00:00`);
  if (Number.isNaN(then.getTime()) || Number.isNaN(now.getTime())) return 999;
  return Math.max(0, Math.round((now.getTime() - then.getTime()) / 86400000));
}

function loadDiscoveryExposureV2() {
  let history = null;
  try {
    history = JSON.parse(localStorage.getItem(personalStorageKey(HOME_DISCOVERY_V2_EXPOSURE_KEY)) || "null");
  } catch {
    history = null;
  }
  if (!history || typeof history !== "object") history = { version: 2, days: {} };
  history.days = history.days && typeof history.days === "object" ? history.days : {};
  for (const day of Object.keys(history.days)) {
    if (discoveryV2DayDistance(day) > HOME_DISCOVERY_V2_HISTORY_DAYS) delete history.days[day];
  }
  return history;
}

function saveDiscoveryExposureV2(history) {
  try {
    localStorage.setItem(personalStorageKey(HOME_DISCOVERY_V2_EXPOSURE_KEY), JSON.stringify(history));
  } catch {
    // Discovery remains deterministic even when browser storage is unavailable.
  }
}

function recordDiscoveryExposureV2(lane, entries) {
  if (!lane || !Array.isArray(entries) || !entries.length) return;
  const keys = [...new Set(entries.map(discoveryV2LogicalKey).filter(Boolean))];
  if (!keys.length) return;
  const history = loadDiscoveryExposureV2();
  const day = localDateKey();
  const record = history.days[day] || { lanes: {} };
  record.lanes = record.lanes && typeof record.lanes === "object" ? record.lanes : {};
  const current = new Set(Array.isArray(record.lanes[lane]) ? record.lanes[lane] : []);
  keys.forEach((key) => current.add(key));
  record.lanes[lane] = [...current].slice(-80);
  history.days[day] = record;
  saveDiscoveryExposureV2(history);
}

function discoveryV2PreviousLaneKeys(lane, daysAgo = 1) {
  const history = loadDiscoveryExposureV2();
  const result = new Set();
  for (const [day, record] of Object.entries(history.days)) {
    if (discoveryV2DayDistance(day) !== daysAgo) continue;
    const lanes = record?.lanes || {};
    for (const [storedLane, keys] of Object.entries(lanes)) {
      if (storedLane === lane || storedLane.startsWith(`${lane}:`)) {
        for (const key of Array.isArray(keys) ? keys : []) result.add(key);
      }
    }
  }
  return result;
}

function discoveryV2ExposurePenalty(entry, lane) {
  const key = discoveryV2LogicalKey(entry);
  if (!key) return 0;
  const history = loadDiscoveryExposureV2();
  let penalty = 0;
  for (const [day, record] of Object.entries(history.days)) {
    const age = discoveryV2DayDistance(day);
    if (age < 1 || age > 14) continue; // Today's ranking must stay stable.
    const sameLaneWeight = age === 1 ? 16 : age === 2 ? 10 : age <= 4 ? 6 : age <= 7 ? 3 : 1;
    for (const [storedLane, keys] of Object.entries(record?.lanes || {})) {
      if (!Array.isArray(keys) || !keys.includes(key)) continue;
      penalty += (storedLane === lane || storedLane.startsWith(`${lane}:`))
        ? sameLaneWeight
        : sameLaneWeight * 0.35;
    }
  }
  return Math.min(32, penalty);
}

function discoveryV2Noise(entry, lane, scale = 1) {
  const seed = `${localDateKey()}|${Number(getShuffle() || 0)}|v2|${lane}|${discoveryV2LogicalKey(entry)}`;
  return (stableDiscoveryHash(seed) / 4294967295) * scale;
}

function discoveryV2EntryTokens(entry) {
  const media = homeEntryMedia(entry);
  const genres = new Set((media.genres || []).map((value) => discoveryV2Normalize(value)).filter(Boolean));
  const providers = new Set();
  if (media.provider) providers.add(String(media.provider).toLowerCase());
  for (const source of [...(media.sources || []), ...(media.source_providers || [])]) {
    const provider = source?.key || source?.provider;
    if (provider) providers.add(String(provider).toLowerCase());
  }
  return {
    genres,
    providers,
    languages: mediaContentLanguages(media),
    kind: entry.kind,
  };
}

function discoveryV2DiversityPenalty(entry, selected) {
  if (!selected.length) return 0;
  const tokens = discoveryV2EntryTokens(entry);
  let penalty = 0;
  for (const chosen of selected) {
    const other = discoveryV2EntryTokens(chosen);
    if (tokens.kind === other.kind) penalty += 0.28;
    const sharedGenres = [...tokens.genres].filter((genre) => other.genres.has(genre)).length;
    penalty += Math.min(1.8, sharedGenres * 0.72);
    const sharedProviders = [...tokens.providers].filter((provider) => other.providers.has(provider)).length;
    penalty += Math.min(0.8, sharedProviders * 0.32);
    if (tokens.languages.size === 1 && other.languages.size === 1) {
      const language = [...tokens.languages][0];
      if (other.languages.has(language)) penalty += 0.16;
    }
  }
  return penalty;
}

function discoveryV2SelectDiverse(scored, limit, { repeatKeys = null, repeatLimit = Infinity } = {}) {
  const remaining = scored.slice();
  const selected = [];
  const selectedKeys = new Set();
  let repeatCount = 0;
  while (remaining.length && selected.length < limit) {
    let bestIndex = -1;
    let bestScore = -Infinity;
    for (let index = 0; index < remaining.length; index += 1) {
      const candidate = remaining[index];
      const logicalKey = discoveryV2LogicalKey(candidate.entry);
      if (!logicalKey || selectedKeys.has(logicalKey)) continue;
      const repeats = repeatKeys?.has(logicalKey);
      if (repeats && repeatCount >= repeatLimit) {
        const hasFreshAlternative = remaining.some((other) => {
          const otherKey = discoveryV2LogicalKey(other.entry);
          return otherKey && !selectedKeys.has(otherKey) && !repeatKeys.has(otherKey);
        });
        if (hasFreshAlternative) continue;
      }
      const adjusted = Number(candidate.score || 0)
        - discoveryV2DiversityPenalty(candidate.entry, selected);
      if (adjusted > bestScore) {
        bestScore = adjusted;
        bestIndex = index;
      }
    }
    if (bestIndex < 0) break;
    const [winner] = remaining.splice(bestIndex, 1);
    const winnerKey = discoveryV2LogicalKey(winner.entry);
    selected.push(winner.entry);
    selectedKeys.add(winnerKey);
    if (repeatKeys?.has(winnerKey)) repeatCount += 1;
  }
  return selected;
}

function discoveryV2TopEntries() {
  const movieRanks = new Map();
  const seriesRanks = new Map();
  getHomeData().topMovies.forEach((item, index) => {
    movieRanks.set(discoveryV2LogicalKey(homeMovieEntry(item)), index);
  });
  getHomeData().trendingSeries.forEach((item, index) => {
    seriesRanks.set(discoveryV2LogicalKey(homeSeriesEntry(item)), index);
  });

  const pool = allowedHomeEntries(uniqueHomeEntries([
    ...getHomeData().topMovies.map(homeMovieEntry),
    ...getHomeData().trendingSeries.map(homeSeriesEntry),
    ...getHomeData().discoveryMovies.map(homeMovieEntry),
    ...getHomeData().discoverySeries.map(homeSeriesEntry),
  ]));
  const previousTop = discoveryV2PreviousLaneKeys("top", 1);
  const now = new Date().getFullYear();
  const scored = pool.map((entry) => {
    const media = homeEntryMedia(entry);
    const logicalKey = discoveryV2LogicalKey(entry);
    const primaryRank = entry.kind === "movie" ? movieRanks.get(logicalKey) : seriesRanks.get(logicalKey);
    const sourceScore = Number.isInteger(primaryRank) ? 58 - Math.min(30, primaryRank * 1.35) : 18;
    const rating = Number(media.rating || 0);
    const votes = Number(media.vote_count || 0);
    const year = Number(String(media.year || media.first_air_date || "").slice(0, 4));
    const recency = year ? Math.max(0, 7 - Math.min(7, Math.abs(now - year) * 1.4)) : 0;
    const availability = Math.min(5, Number(media.provider_count || media.sources?.length || 1));
    const languageBonus = mediaContentLanguages(media).size > 1 ? 1.5 : 0;
    return {
      entry,
      score: sourceScore
        + rating * 1.45
        + Math.min(8, Math.log10(votes + 1) * 1.7)
        + recency
        + availability
        + languageBonus
        - discoveryV2ExposurePenalty(entry, "top") * 0.7
        + discoveryV2Noise(entry, "top", 6.5),
    };
  }).sort((a, b) => b.score - a.score);

  // Keep continuity without allowing yesterday's chart to freeze the rail.
  // With enough alternatives, at most four of ten may survive into the next day.
  return discoveryV2SelectDiverse(scored, 10, {
    repeatKeys: previousTop,
    repeatLimit: previousTop.size ? 4 : Infinity,
  });
}

function discoveryV2MergeItems(current, incoming, kind) {
  const result = [];
  const byIdentity = new Map();
  const mergeOne = (item) => {
    if (!item) return;
    const entry = kind === "movie" ? homeMovieEntry(item) : homeSeriesEntry(item);
    const identity = discoveryV2LogicalKey(entry) || `${kind}:${item.slug || item.base_slug || item.title}`;
    const existing = byIdentity.get(identity);
    if (!existing) {
      const copy = { ...item };
      byIdentity.set(identity, copy);
      result.push(copy);
      return;
    }
    const languages = new Set([
      ...(existing.content_languages || []),
      ...(item.content_languages || []),
      existing.content_language,
      item.content_language,
    ].map(normalizeUiContentLanguage).filter(Boolean));
    if (languages.size) existing.content_languages = [...languages];
    for (const field of ["cover_url", "backdrop_url", "description", "genres", "rating", "vote_count", "tmdb_id"]) {
      if ((!existing[field] || (Array.isArray(existing[field]) && !existing[field].length)) && item[field]) {
        existing[field] = item[field];
      }
    }
    const sources = [...(existing.sources || []), ...(item.sources || [])];
    if (sources.length) {
      const unique = new Map();
      for (const source of sources) {
        const key = `${source?.key || source?.provider || ""}|${source?.content_language || ""}`;
        if (!unique.has(key)) unique.set(key, source);
      }
      existing.sources = [...unique.values()];
    }
  };
  current.forEach(mergeOne);
  incoming.forEach(mergeOne);
  return result;
}

return { discoveryV2Normalize, discoveryV2LogicalKey, discoveryV2DayDistance, loadDiscoveryExposureV2, saveDiscoveryExposureV2, recordDiscoveryExposureV2, discoveryV2PreviousLaneKeys, discoveryV2ExposurePenalty, discoveryV2Noise, discoveryV2EntryTokens, discoveryV2DiversityPenalty, discoveryV2SelectDiverse, discoveryV2TopEntries, discoveryV2MergeItems };
}
