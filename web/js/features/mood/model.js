import {
  MOOD_MATCH_STEPS, MOOD_MATCH_PROFILES, MOOD_MATCH_RULES, MOOD_DEFAULT_ANSWERS,
  MOOD_REFINEMENT_GROUPS, MOOD_GENRE_ALIASES
} from "./config.js";

/** Pure selection rules with explicit catalog, taste and clock inputs. */
export function createMoodModel({ homeEntryMedia, homeEntryKey, mediaJellyfinStatus,
  loadDiscoveryProfile, stableDiscoveryHash, localDateKey, allowedHomeEntries,
  homeAllEntries, uniqueHomeContentEntries, uniqueHomeEntries,
}) {
function createMoodRefinements() {
  return {
    duration: "any", tempo: "any", discovery: "balanced", era: "any",
    library: "any", minRating: "any", avoid: [],
  };
}

function createMoodState() {
  return {
    step: 0, answers: {}, inferred: [], refinements: createMoodRefinements(),
    draftRefinements: null, results: [], analysis: [], dismissed: [], open: true,
    view: "question", returnAfterDetail: false, requestId: 0, genreOpen: false,
  };
}

function canonicalMoodGenre(value) {
  const clean = String(value || "").trim();
  return MOOD_GENRE_ALIASES[clean.toLocaleLowerCase("de-DE")] || clean;
}

function normalizedMoodGenres(media) {
  const rawGenres = [media?.genres, media?.genre, media?.categories]
    .flatMap((value) => Array.isArray(value) ? value : (value ? String(value).split(/[,;/|]/) : []));
  return new Set(rawGenres
    .map((genre) => typeof genre === "object" ? (genre.name || genre.title || "") : genre)
    .flatMap((genre) => {
      const clean = String(genre || "").trim().toLocaleLowerCase("de-DE");
      if (clean === "action & adventure") return ["Action", "Abenteuer"];
      if (clean === "sci-fi & fantasy") return ["Science-Fiction", "Fantasy"];
      if (clean === "war & politics") return ["Krieg", "Geschichte"];
      return [canonicalMoodGenre(genre)];
    }).filter(Boolean));
}

function moodHasGenre(genres, name) {
  return genres.has(canonicalMoodGenre(name));
}

function moodHasAnyGenre(genres, names = []) {
  return names.some((name) => moodHasGenre(genres, name));
}

function moodRuntimeMinutes(media) {
  const raw = Array.isArray(media?.runtime) ? media.runtime[0] : media?.runtime;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  const value = String(raw || "").toLocaleLowerCase("de-DE");
  const hours = Number(value.match(/(\d+(?:[.,]\d+)?)\s*(?:h|std)/)?.[1]?.replace(",", ".") || 0);
  const minutes = Number(value.match(/(\d+)\s*(?:min|minute)/)?.[1] || 0);
  if (hours || minutes) return Math.round(hours * 60 + minutes);
  const standalone = Number(value.match(/^\s*(\d{2,3})\s*$/)?.[1] || 0);
  return standalone >= 20 && standalone <= 400 ? standalone : 0;
}

function moodMediaYear(media) {
  return Number(String(media?.year || media?.release_date || media?.first_air_date || "")
    .match(/\b(19|20)\d{2}\b/)?.[0] || 0);
}

function moodLibraryStatus(entry) {
  if (typeof mediaJellyfinStatus === "function") return mediaJellyfinStatus(homeEntryMedia(entry));
  const media = homeEntryMedia(entry);
  if (media.jellyfin_status) return media.jellyfin_status;
  if (media.in_jellyfin === true) return "owned";
  if (media.in_jellyfin === false) return "missing";
  return "unknown";
}

function moodEffectiveAnswers(answers = {}) {
  return {
    ...MOOD_DEFAULT_ANSWERS,
    ...answers,
    genres: Array.isArray(answers.genres) ? answers.genres.map(canonicalMoodGenre).filter(Boolean).slice(0, 2) : [],
  };
}

function moodFocusedGenres(answers = {}) {
  return moodEffectiveAnswers(answers).genres;
}

function moodMatchesGenreFocus(entry, answers = {}) {
  const focused = moodFocusedGenres(answers);
  if (!focused.length) return true;
  const genres = normalizedMoodGenres(homeEntryMedia(entry));
  return focused.every((genre) => moodHasGenre(genres, genre));
}

function moodFamilyPool(entries) {
  return entries.filter((entry) => {
    const media = homeEntryMedia(entry);
    const genres = normalizedMoodGenres(media);
    if (!genres.size || media.adult === true) return false;
    if (moodHasAnyGenre(genres, ["Horror", "Thriller", "Krimi", "Krieg", "Erotik"])) return false;
    return moodHasAnyGenre(genres, ["Familie", "Kinder", "Animation", "Abenteuer", "Fantasy", "Komödie"]);
  });
}

function moodIntentTier(entry, answers) {
  const effective = moodEffectiveAnswers(answers);
  if (effective.mood === "open") return 0;
  const genres = normalizedMoodGenres(homeEntryMedia(entry));
  const rules = MOOD_MATCH_RULES[effective.mood];
  const focused = new Set(effective.genres);
  const hardExclusions = (rules?.excluded || []).filter((genre) => !focused.has(canonicalMoodGenre(genre)));
  if (!rules || !genres.size || moodHasAnyGenre(genres, hardExclusions)) return 3;
  if (moodHasAnyGenre(genres, rules.direct)) return 0;
  if (moodHasAnyGenre(genres, rules.related)) return 1;
  if (focused.size) return 1;
  return 2;
}

function moodMatchesIntent(entry, answers) {
  return moodIntentTier(entry, answers) < 2;
}

function moodMatchesRefinements(entry, refinements = createMoodRefinements()) {
  const media = homeEntryMedia(entry);
  const genres = normalizedMoodGenres(media);
  if ((refinements.avoid || []).some((genre) => moodHasGenre(genres, genre))) return false;
  if (refinements.duration !== "any") {
    const runtime = moodRuntimeMinutes(media);
    if (!runtime || runtime > Number(refinements.duration)) return false;
  }
  const year = moodMediaYear(media);
  if (refinements.era === "new" && (!year || year < 2018)) return false;
  if (refinements.era === "modern" && (!year || year < 2000 || year > 2017)) return false;
  if (refinements.era === "classic" && (!year || year >= 2000)) return false;
  if (refinements.library !== "any" && moodLibraryStatus(entry) !== refinements.library) return false;
  if (refinements.minRating !== "any" && Number(media.rating || 0) < Number(refinements.minRating)) return false;
  return true;
}

function moodCompanyScore(genres, company) {
  const weights = {
    alone: { Mystery: 3, Thriller: 2, Drama: 2, "Science-Fiction": 1 },
    couple: { Drama: 4, Romanze: 4, Komödie: 3, Mystery: 2, Thriller: 1 },
    friends: { Action: 5, Komödie: 5, Horror: 4, Abenteuer: 3, Thriller: 2 },
    family: { Familie: 12, Animation: 11, Abenteuer: 7, Fantasy: 5, Komödie: 4 },
  }[company] || {};
  return Object.entries(weights).reduce(
    (score, [genre, weight]) => score + (moodHasGenre(genres, genre) ? weight : 0), 0,
  );
}

function moodTempoScore(genres, tempo) {
  if (tempo === "drive") {
    return ["Action", "Thriller", "Horror", "Krimi", "Abenteuer"]
      .reduce((score, genre) => score + (moodHasGenre(genres, genre) ? 4 : 0), 0);
  }
  if (tempo === "quiet") {
    let score = ["Drama", "Romanze", "Dokumentation", "Geschichte"]
      .reduce((total, genre) => total + (moodHasGenre(genres, genre) ? 4 : 0), 0);
    if (moodHasAnyGenre(genres, ["Action", "Horror"])) score -= 5;
    return score;
  }
  if (tempo === "balanced") {
    return moodHasAnyGenre(genres, ["Abenteuer", "Komödie", "Mystery", "Drama"]) ? 3 : 0;
  }
  return 0;
}

function moodDiscoveryScore(media, discovery, key) {
  const rating = Number(media.rating || 0);
  const votes = Math.max(0, Number(media.vote_count || 0));
  const confidence = Math.log10(votes + 1);
  if (discovery === "safe") return rating * 1.1 + confidence * 3.2;
  if (discovery === "hidden") return rating * 1.3 - confidence * 1.6;
  if (discovery === "surprise") return stableDiscoveryHash(`mood-surprise|${key}`) / 4294967295 * 12;
  return rating * .75 + confidence * 1.15;
}

function moodMatchScore(entry, answers, profile = loadDiscoveryProfile(), refinements = createMoodRefinements()) {
  const effective = moodEffectiveAnswers(answers);
  const media = homeEntryMedia(entry);
  const genres = normalizedMoodGenres(media);
  const mood = MOOD_MATCH_PROFILES[effective.mood];
  let score = 0;
  if (mood) {
    Object.entries(mood.weights).forEach(([genre, weight]) => {
      if (moodHasGenre(genres, genre)) score += weight;
    });
  }
  effective.genres.forEach((genre) => {
    if (moodHasGenre(genres, genre)) score += 18;
  });
  score += moodCompanyScore(genres, effective.company);
  score += moodTempoScore(genres, refinements.tempo);
  score += moodDiscoveryScore(media, refinements.discovery, homeEntryKey(entry));
  Object.entries(profile?.genres || {}).forEach(([genre, weight]) => {
    if (moodHasGenre(genres, genre)) score += Math.max(-3, Math.min(3, Number(weight || 0) * .08));
  });
  if ((profile?.recent || []).slice(0, 30).some((event) => event.key === homeEntryKey(entry))) score -= 7;
  if (effective.format === "any") score += Math.max(-1.5, Math.min(1.5, Number(profile?.kinds?.[entry.kind] || 0) * .04));
  score += stableDiscoveryHash(`${localDateKey()}|abendregie|${JSON.stringify(effective)}|${homeEntryKey(entry)}`) / 4294967295;
  return score;
}

function moodPrimaryGenre(entry, answers) {
  const genres = normalizedMoodGenres(homeEntryMedia(entry));
  const profile = MOOD_MATCH_PROFILES[moodEffectiveAnswers(answers).mood];
  return [...(profile?.direct || []), ...(profile?.related || []), ...genres]
    .map(canonicalMoodGenre).find((genre) => genres.has(genre)) || "";
}

function moodBasePool(answers, refinements = createMoodRefinements()) {
  const effective = moodEffectiveAnswers(answers);
  let entries = allowedHomeEntries(homeAllEntries());
  const unique = typeof uniqueHomeContentEntries === "function" ? uniqueHomeContentEntries : uniqueHomeEntries;
  entries = unique(entries);
  if (effective.format === "movie") entries = entries.filter((entry) => entry.kind === "movie");
  if (effective.format === "series") entries = entries.filter((entry) => entry.kind === "series");
  if (effective.company === "family") entries = moodFamilyPool(entries);
  if (effective.genres.length) entries = entries.filter((entry) => moodMatchesGenreFocus(entry, effective));
  entries = entries.filter((entry) => moodMatchesRefinements(entry, refinements));
  if (effective.mood !== "open") entries = entries.filter((entry) => moodMatchesIntent(entry, effective));
  return entries;
}

function moodMatchAnalyses(answers, refinements = createMoodRefinements()) {
  const profile = loadDiscoveryProfile();
  const ranked = moodBasePool(answers, refinements).map((entry) => ({
    entry, tier: moodIntentTier(entry, answers),
    score: moodMatchScore(entry, answers, profile, refinements),
  })).sort((left, right) => left.tier - right.tier || right.score - left.score);
  const selected = [];
  const genreCounts = new Map();
  const kindCounts = new Map();
  const remaining = ranked.slice();
  while (remaining.length && selected.length < 12) {
    remaining.sort((left, right) => {
      const leftGenre = moodPrimaryGenre(left.entry, answers);
      const rightGenre = moodPrimaryGenre(right.entry, answers);
      const leftAdjusted = left.score - (genreCounts.get(leftGenre) || 0) * 3.2 - (kindCounts.get(left.entry.kind) || 0) * .8;
      const rightAdjusted = right.score - (genreCounts.get(rightGenre) || 0) * 3.2 - (kindCounts.get(right.entry.kind) || 0) * .8;
      return left.tier - right.tier || rightAdjusted - leftAdjusted;
    });
    const next = remaining.shift();
    selected.push(next);
    const genre = moodPrimaryGenre(next.entry, answers);
    genreCounts.set(genre, (genreCounts.get(genre) || 0) + 1);
    kindCounts.set(next.entry.kind, (kindCounts.get(next.entry.kind) || 0) + 1);
  }
  return selected;
}

function moodMatchResults(answers, refinements = createMoodRefinements()) {
  return moodMatchAnalyses(answers, refinements).map(({ entry }) => entry);
}

function moodAnswerLabel(stepKey, value) {
  if (stepKey === "mood" && value === "open") return "Wirkung offen";
  return MOOD_MATCH_STEPS.find((step) => step.key === stepKey)
    ?.options.find((option) => option.value === value)?.title || value;
}

function moodRefinementLabel(key, value) {
  return MOOD_REFINEMENT_GROUPS.find((group) => group.key === key)
    ?.options.find((option) => option.value === value)?.label || value;
}

function moodMatchGrade(analysis, answers) {
  if (moodEffectiveAnswers(answers).mood === "open") return "BESTE PASSUNG";
  return analysis.tier === 0 ? "SEHR NAHER TREFFER" : "STARKER VERWANDTER TREFFER";
}

function moodReasons(analysis, answers, refinements) {
  const effective = moodEffectiveAnswers(answers);
  const media = homeEntryMedia(analysis.entry);
  const genres = normalizedMoodGenres(media);
  const reasons = [];
  if (effective.genres.length) reasons.push(`Genre-Fokus · ${effective.genres.join(" + ")}`);
  if (effective.mood !== "open") {
    const profile = MOOD_MATCH_PROFILES[effective.mood];
    const matched = [...profile.direct, ...profile.related].find((genre) => moodHasGenre(genres, genre));
    if (matched) reasons.push(`${moodAnswerLabel("mood", effective.mood)} · ${matched}`);
  } else {
    reasons.push("Wirkung bewusst offen");
  }
  reasons.push(moodAnswerLabel("company", effective.company));
  if (refinements.tempo !== "any") reasons.push(`Tempo · ${moodRefinementLabel("tempo", refinements.tempo)}`);
  if (refinements.duration !== "any") reasons.push(`${moodRuntimeMinutes(media)} Min. im Zeitfenster`);
  if (Number(media.rating || 0) >= 7.5) reasons.push(`Stark bewertet · ${Number(media.rating).toFixed(1)}`);
  if (refinements.library === "owned") reasons.push("Sofort in Jellyfin");
  if (refinements.library === "missing") reasons.push("Noch nicht in Jellyfin");
  return reasons.slice(0, 4);
}

function moodMediaMeta(entry) {
  const media = homeEntryMedia(entry);
  const status = moodLibraryStatus(entry);
  const statusLabel = {
    owned: "IN JELLYFIN", missing: "NOCH NICHT IN JELLYFIN", checking: "JELLYFIN WIRD GEPRÜFT",
    unconfigured: "JELLYFIN NICHT VERBUNDEN", unavailable: "JELLYFIN NICHT ERREICHBAR",
  }[status] || "JELLYFIN-STATUS OFFEN";
  return [
    entry.kind === "movie" ? "FILM" : "SERIE",
    media.year || String(media.release_date || media.first_air_date || "").slice(0, 4),
    media.runtime || "", media.rating ? `★ ${media.rating}` : "", statusLabel,
  ].filter(Boolean).join(" · ");
}

function moodRelaxationSuggestion(answers, refinements) {
  const candidates = [
    ["duration", "any", "Zeitfenster öffnen"],
    ["library", "any", "Jellyfin-Filter öffnen"],
    ["minRating", "any", "Bewertung öffnen"],
    ["era", "any", "Alle Jahre zulassen"],
  ];
  for (const [key, value, label] of candidates) {
    if (refinements[key] === value) continue;
    const relaxed = { ...refinements, avoid: [...(refinements.avoid || [])], [key]: value };
    const count = moodBasePool(answers, relaxed).length;
    if (count) return { key, value, label: `${label} · ${count} Treffer` };
  }
  if ((refinements.avoid || []).length) {
    const relaxed = { ...refinements, avoid: [] };
    const count = moodBasePool(answers, relaxed).length;
    if (count) return { key: "avoid", value: [], label: `No-Gos öffnen · ${count} Treffer` };
  }
  const focused = moodFocusedGenres(answers);
  if (focused.length) {
    const reduced = focused.length > 1 ? focused.slice(0, 1) : [];
    const relaxedAnswers = { ...answers, genres: reduced };
    const count = moodBasePool(relaxedAnswers, refinements).length;
    if (count) {
      return {
        target: "answer", key: "genres", value: reduced,
        label: reduced.length ? `Nur ${reduced[0]} fokussieren · ${count} Treffer` : `Genre-Fokus lösen · ${count} Treffer`,
      };
    }
  }
  if (answers.mood !== "open") {
    const relaxedAnswers = { ...answers, mood: "open" };
    const count = moodBasePool(relaxedAnswers, refinements).length;
    if (count) {
      return {
        target: "answer", key: "mood", value: "open",
        label: `Wirkung offen lassen · ${count} Treffer`,
      };
    }
  }
  return null;
}

return { createMoodRefinements, createMoodState, canonicalMoodGenre, normalizedMoodGenres, moodHasGenre, moodHasAnyGenre, moodRuntimeMinutes, moodMediaYear, moodLibraryStatus, moodEffectiveAnswers, moodFocusedGenres, moodMatchesGenreFocus, moodFamilyPool, moodIntentTier, moodMatchesIntent, moodMatchesRefinements, moodCompanyScore, moodTempoScore, moodDiscoveryScore, moodMatchScore, moodPrimaryGenre, moodBasePool, moodMatchAnalyses, moodMatchResults, moodAnswerLabel, moodRefinementLabel, moodMatchGrade, moodReasons, moodMediaMeta, moodRelaxationSuggestion };
}
