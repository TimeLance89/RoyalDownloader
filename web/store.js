function createInitialState() {
  return {
    tab: "home",
    globalSearch: {
      query: "", results: [], active: false, loading: false,
      requestSeq: 0, scope: "all", jellyfinOnly: false, submitted: false,
    },
    home: {
      newMovies: [], topMovies: [], trendingSeries: [], newSeries: [],
      discoveryMovies: [], discoverySeries: [],
      heroIndex: 0, heroTimer: null, loading: true, discoveryDay: "", discoveryShuffle: 0,
      jellyfinStatusByKey: new Map(),
      mood: { step: 0, answers: {}, results: [], open: false },
      search: { scope: "all", query: "", results: [], active: false, loading: false, requestSeq: 0 },
    },
    fp: {
      results: [], moviesCache: {}, category: null, page: 1, lastPageFull: false,
      activeGenre: "Alle Genres", selectedSlug: null, pendingPreload: null,
      availableGenres: [],
      filters: { period: "all", rating: "all", availability: "all", language: "all", sort: "default" },
      metadataCache: {}, requestSeq: 0, metadataRequestSeq: 0, sources: [], loadingMore: false,
      loadError: "", searchActive: false, searchReturn: null,
      previewFromHome: false, lastCatalogRefreshAt: 0,
      featureCandidates: [], featureIndex: 0, featureTimer: null,
      featurePaused: false, downloadSelections: new Map(),
    },
    series: {
      results: [], browseMode: null, page: 1, lastPageFull: false,
      sources: [], browseRequestSeq: 0, loadingBrowse: false, loadError: "",
      current: null, currentSampleSlug: "", epPicked: new Set(), cache: {},
      pendingBaseSlug: "", requestSeq: 0, viewGeneration: 0,
      jellyfinRefreshSeq: 0, jellyfinRefreshByBase: new Map(), searchReturn: null,
      previewFromHome: false, lastCatalogRefreshAt: 0,
    },
    anime: {
      results: [], mode: null, query: "", page: 1, hasMore: false,
      loaded: false, loading: false, requestSeq: 0, detailSeq: 0,
      currentId: "", current: null, translation: "", episodePage: 1,
      picked: new Set(), searchReturn: null,
    },
    aniworld: {
      results: [], mode: null, query: "", page: 1, hasMore: false,
      total: 0, facets: { letters: {}, genres: {} }, letter: "ALL", genre: "",
      loaded: false, loading: false, requestSeq: 0, detailSeq: 0,
      currentId: "", current: null, translation: "", episodePage: 1,
      selectedSeason: null, picked: new Set(), searchReturn: null,
      disabledReason: "", loadError: "", posterCache: new Map(),
      posterLoading: new Set(),
    },
    wl: {
      items: [], selected: new Set(), loaded: false,
      filter: "all", query: "", draftQuery: "", sort: "attention", heroBaseSlug: "",
    },
    movieSubscriptions: { items: [], loaded: false },
    queue: { count: 0, groups: [], loaded: false },
    download: { active: false, percent: 0, completed: 0, total: 0, failed: 0 },
    providers: {
      movies: [], series: [], anime: [], labels: {}, catalog: {}, languages: {},
      contentLanguages: new Set(), enabledMovies: new Set(),
      enabledSeries: new Set(), enabledAnime: new Set(),
    },
    queuedSlugs: new Set(), jellyfinUserConfigured: false,
    watchlistCleanupDefault: "keep",
  };
}

// ── Cross-screen media presentation policy ────────────────────────────────
// These decorators are installed after all classic screen scripts have been
// parsed. They keep presentation-only language badges in one place and, for
// movie details, prevent a harmless UI refresh from recreating a running
// YouTube iframe.
function normalizeUiContentLanguage(value) {
  const code = String(value || "").trim().replace("_", "-").toLowerCase().split("-", 1)[0];
  return code === "de" || code === "en" ? code : "";
}

function mediaContentLanguages(media = {}) {
  const languages = new Set();
  const add = (value) => {
    const normalized = normalizeUiContentLanguage(value);
    if (normalized) languages.add(normalized);
  };
  const providerLanguage = (provider) => {
    const key = String(provider || "").trim().toLowerCase();
    return state.providers.catalog?.[key]?.content_language || "";
  };

  add(media.content_language);
  for (const value of media.content_languages || []) add(value);
  if (media.provider) add(providerLanguage(media.provider));
  for (const source of [
    ...(Array.isArray(media.sources) ? media.sources : []),
    ...(Array.isArray(media.source_providers) ? media.source_providers : []),
  ]) {
    add(source?.content_language);
    if (source?.key) add(providerLanguage(source.key));
    else if (source?.provider) add(providerLanguage(source.provider));
  }
  return languages;
}

function mixedGermanEnglishContentEnabled() {
  return state.providers.contentLanguages.has("de")
    && state.providers.contentLanguages.has("en");
}

function mediaLanguageMarker(media) {
  if (!mixedGermanEnglishContentEnabled()) return null;
  const languages = mediaContentLanguages(media);
  const flags = [];
  const labels = [];
  if (languages.has("de")) {
    flags.push("🇩🇪");
    labels.push("Deutsch");
  }
  if (languages.has("en")) {
    flags.push("🇬🇧");
    labels.push("Englisch");
  }
  if (!flags.length) return null;
  return { text: flags.join(" "), label: labels.join(" und ") };
}

function appendMediaLanguageMarker(element, media) {
  const marker = mediaLanguageMarker(media);
  if (!element || !marker || element.dataset.languageMarked === "true") return;
  element.dataset.languageMarked = "true";
  element.textContent = `${element.textContent} · ${marker.text}`;
  const previousTitle = element.getAttribute("title") || "";
  element.setAttribute("title", [previousTitle, `Inhaltssprache: ${marker.label}`].filter(Boolean).join(" · "));
}

function movieDownloadLanguageOptions(movie = {}) {
  const grouped = new Map();
  const sources = Array.isArray(movie.source_providers) ? movie.source_providers : [];
  for (const source of sources) {
    const language = normalizeUiContentLanguage(source?.content_language);
    const hosterCount = Number(source?.hoster_count ?? source?.hosters?.length ?? 0);
    if (!language || hosterCount <= 0) continue;
    if (!grouped.has(language)) grouped.set(language, { language, providers: [], hosterCount: 0 });
    const option = grouped.get(language);
    option.hosterCount += hosterCount;
    if (source?.label && !option.providers.includes(source.label)) option.providers.push(source.label);
  }
  return grouped;
}

function ensureMovieLanguageDialog() {
  let modal = document.getElementById("movie-language-choice");
  if (modal) return modal;

  const style = document.createElement("style");
  style.textContent = `
    .movie-language-choice{position:fixed;inset:0;z-index:10040;display:grid;place-items:center;padding:24px;background:rgba(4,6,12,.72);backdrop-filter:blur(12px)}
    .movie-language-choice[hidden]{display:none}
    .movie-language-panel{width:min(520px,100%);border:1px solid rgba(255,255,255,.12);border-radius:24px;padding:24px;background:linear-gradient(145deg,rgba(24,27,38,.98),rgba(10,12,19,.98));box-shadow:0 28px 90px rgba(0,0,0,.5);color:#fff}
    .movie-language-kicker{display:block;margin-bottom:8px;font-size:11px;font-weight:800;letter-spacing:.16em;color:#9ca6bd}
    .movie-language-panel h3{margin:0 0 8px;font-size:24px}
    .movie-language-panel p{margin:0 0 18px;color:#b7bfd1;line-height:1.5}
    .movie-language-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    .movie-language-option{display:flex;align-items:center;gap:12px;text-align:left;border:1px solid rgba(255,255,255,.12);border-radius:18px;padding:16px;background:rgba(255,255,255,.045);color:#fff;cursor:pointer}
    .movie-language-option:hover,.movie-language-option:focus-visible{border-color:rgba(111,145,255,.7);background:rgba(111,145,255,.12);outline:none}
    .movie-language-option b{font-size:26px}.movie-language-option span{display:grid;gap:3px}.movie-language-option strong{font-size:15px}.movie-language-option small{color:#9ca6bd}
    .movie-language-cancel{margin-top:16px;width:100%;border:0;background:transparent;color:#aeb6c8;padding:10px;cursor:pointer}
    @media(max-width:560px){.movie-language-options{grid-template-columns:1fr}.movie-language-panel{padding:20px;border-radius:20px}}
  `;
  document.head.appendChild(style);

  modal = document.createElement("div");
  modal.id = "movie-language-choice";
  modal.className = "movie-language-choice";
  modal.hidden = true;
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "movie-language-title");
  modal.innerHTML = `
    <section class="movie-language-panel">
      <span class="movie-language-kicker">DOWNLOADSPRACHE</span>
      <h3 id="movie-language-title">Welche Sprache möchtest du?</h3>
      <p>Royal nutzt danach automatisch alle verfügbaren Anbieter-Fallbacks innerhalb dieser Sprache.</p>
      <div class="movie-language-options">
        <button class="movie-language-option" type="button" data-language="de"><b>🇩🇪</b><span><strong>Deutsch</strong><small></small></span></button>
        <button class="movie-language-option" type="button" data-language="en"><b>🇬🇧</b><span><strong>English</strong><small></small></span></button>
      </div>
      <button class="movie-language-cancel" type="button">Abbrechen</button>
    </section>
  `;
  document.body.appendChild(modal);
  return modal;
}

function chooseMovieDownloadLanguage(movie) {
  const options = movieDownloadLanguageOptions(movie);
  if (!mixedGermanEnglishContentEnabled() || !options.has("de") || !options.has("en")) {
    return Promise.resolve(null);
  }
  const modal = ensureMovieLanguageDialog();
  const previousFocus = document.activeElement;
  for (const language of ["de", "en"]) {
    const data = options.get(language);
    const button = modal.querySelector(`[data-language="${language}"]`);
    const providerText = data.providers.slice(0, 3).join(" · ");
    const extraProviders = Math.max(0, data.providers.length - 3);
    button.querySelector("small").textContent = [
      `${data.hosterCount} Hoster`,
      providerText,
      extraProviders ? `+${extraProviders} weitere` : "",
    ].filter(Boolean).join(" · ");
  }
  modal.hidden = false;
  modal.querySelector('[data-language="en"]')?.focus();

  return new Promise((resolve) => {
    let finished = false;
    const finish = (value) => {
      if (finished) return;
      finished = true;
      modal.hidden = true;
      modal.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKeydown);
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
      resolve(value);
    };
    const onClick = (event) => {
      const languageButton = event.target.closest("[data-language]");
      if (languageButton) {
        finish(languageButton.dataset.language || "");
        return;
      }
      if (event.target === modal || event.target.closest(".movie-language-cancel")) finish("");
    };
    const onKeydown = (event) => {
      if (event.key === "Escape") finish("");
    };
    modal.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeydown);
  });
}

// ── Discovery Engine v2 ───────────────────────────────────────────────────
// The provider catalog has grown far beyond the small page-1/page-2 window the
// original home screen was designed for. Discovery v2 keeps the fast first
// paint, then expands the candidate reservoir in the background and uses a
// persistent exposure history so good recommendations rotate instead of being
// mathematically re-elected every day.
const HOME_DISCOVERY_V2_EXPOSURE_KEY = "royal-home-exposure-v2";
const HOME_DISCOVERY_V2_HISTORY_DAYS = 21;
let discoveryV2ReservoirPromise = null;

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
    history = JSON.parse(localStorage.getItem(HOME_DISCOVERY_V2_EXPOSURE_KEY) || "null");
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
    localStorage.setItem(HOME_DISCOVERY_V2_EXPOSURE_KEY, JSON.stringify(history));
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
  const seed = `${localDateKey()}|${Number(state.home.discoveryShuffle || 0)}|v2|${lane}|${discoveryV2LogicalKey(entry)}`;
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

function discoveryV2TasteAffinity(entry, profile) {
  const media = homeEntryMedia(entry);
  const metadata = tasteMetadata(entry.kind, media);
  let score = 0;
  for (const [dimension, values] of Object.entries(metadata)) {
    if (!["genres", "tags", "studios", "directors", "actors", "languages"].includes(dimension)) continue;
    const list = Array.isArray(values) ? values : [values];
    score += list.reduce(
      (sum, value) => sum + Number(profile.dimensions?.[dimension]?.[String(value)] || 0),
      0,
    );
  }
  const year = Number(String(metadata.year || "").slice(0, 4));
  if (year) score += Number(profile.dimensions?.decades?.[`${Math.floor(year / 10) * 10}er`] || 0);
  score += Number(profile.kinds?.[entry.kind] || 0);
  score += Number(media.rating || 0) * 0.12;
  return score;
}

function discoveryV2PersonalizedEntries() {
  const profile = loadDiscoveryProfile();
  const recent = new Set(profile.recent.slice(0, 24).map((event) => event.key));
  const pool = homeAllEntries().filter((entry) => !recent.has(homeEntryKey(entry)));
  const scored = pool.map((entry) => ({
    entry,
    affinity: discoveryV2TasteAffinity(entry, profile),
    score: discoveryV2TasteAffinity(entry, profile)
      - discoveryV2ExposurePenalty(entry, "personal")
      + discoveryV2Noise(entry, "personal", profile.interactions >= 2 ? 3.2 : 8),
  })).sort((a, b) => b.score - a.score);

  if (profile.interactions < 2 || !Object.keys(profile.genres || {}).length) {
    return discoveryV2SelectDiverse(scored, 24);
  }

  const selected = [];
  const selectedKeys = new Set();
  const add = (entries) => {
    for (const entry of entries) {
      const key = discoveryV2LogicalKey(entry);
      if (!key || selectedKeys.has(key)) continue;
      selectedKeys.add(key);
      selected.push(entry);
    }
  };

  // First seven visible cards deliberately follow a 4/2/1 mix:
  // four strong taste matches, two adjacent discoveries and one surprise.
  add(discoveryV2SelectDiverse(scored.slice(0, Math.max(40, Math.ceil(scored.length * 0.45))), 4));

  const adjacent = scored
    .filter(({ entry, affinity }) => !selectedKeys.has(discoveryV2LogicalKey(entry)) && affinity > 0)
    .map((candidate) => ({
      ...candidate,
      score: candidate.score * 0.72 + discoveryV2Noise(candidate.entry, "personal-adjacent", 7),
    }))
    .sort((a, b) => b.score - a.score);
  add(discoveryV2SelectDiverse(adjacent, 2));

  const favoriteGenres = new Set(Object.entries(profile.genres || {})
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 2)
    .map(([genre]) => discoveryV2Normalize(genre)));
  const surprise = scored
    .filter(({ entry }) => {
      if (selectedKeys.has(discoveryV2LogicalKey(entry))) return false;
      const genres = discoveryV2EntryTokens(entry).genres;
      return ![...genres].some((genre) => favoriteGenres.has(genre));
    })
    .map((candidate) => ({
      ...candidate,
      score: Number(homeEntryMedia(candidate.entry).rating || 0) * 0.35
        - discoveryV2ExposurePenalty(candidate.entry, "personal")
        + discoveryV2Noise(candidate.entry, "personal-surprise", 10),
    }))
    .sort((a, b) => b.score - a.score);
  add(discoveryV2SelectDiverse(surprise, 1));

  const remainder = scored.filter(({ entry }) => !selectedKeys.has(discoveryV2LogicalKey(entry)));
  add(discoveryV2SelectDiverse(remainder, Math.max(0, 24 - selected.length)));
  return selected.slice(0, 24);
}

function discoveryV2TopEntries() {
  const movieRanks = new Map();
  const seriesRanks = new Map();
  state.home.topMovies.forEach((item, index) => {
    movieRanks.set(discoveryV2LogicalKey(homeMovieEntry(item)), index);
  });
  state.home.trendingSeries.forEach((item, index) => {
    seriesRanks.set(discoveryV2LogicalKey(homeSeriesEntry(item)), index);
  });

  const pool = allowedHomeEntries(uniqueHomeEntries([
    ...state.home.topMovies.map(homeMovieEntry),
    ...state.home.trendingSeries.map(homeSeriesEntry),
    ...state.home.discoveryMovies.map(homeMovieEntry),
    ...state.home.discoverySeries.map(homeSeriesEntry),
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

async function discoveryV2HydrateInBatches(items, kind) {
  const unique = items.filter(Boolean);
  for (let index = 0; index < unique.length; index += 80) {
    const batch = unique.slice(index, index + 80);
    if (kind === "movie") await hydrateHomeMovieArtwork(batch, { render: false });
    else await hydrateHomeSeriesArtwork(batch, { render: false });
  }
}

async function warmDiscoveryReservoirV2() {
  if (discoveryV2ReservoirPromise) return discoveryV2ReservoirPromise;
  discoveryV2ReservoirPromise = (async () => {
    const movies = [];
    const series = [];
    const waves = [
      [
        ["movie", () => api.movies({ mode: "new", page: 3 })],
        ["movie", () => api.movies({ mode: "top", page: 3 })],
        ["series", () => api.series({ mode: "discover", page: 2 })],
        ["series", () => api.series({ mode: "trending", page: 2 })],
        ["series", () => api.series({ mode: "new", page: 2 })],
      ],
      [
        ["movie", () => api.movies({ mode: "new", page: 4 })],
        ["movie", () => api.movies({ mode: "top", page: 4 })],
        ["series", () => api.series({ mode: "discover", page: 3 })],
        ["series", () => api.series({ mode: "trending", page: 3 })],
        ["series", () => api.series({ mode: "new", page: 3 })],
      ],
    ];

    for (const wave of waves) {
      const settled = await Promise.allSettled(wave.map(([, request]) => request()));
      settled.forEach((result, index) => {
        if (result.status !== "fulfilled") return;
        const kind = wave[index][0];
        const values = result.value?.results || [];
        if (kind === "movie") movies.push(...values);
        else series.push(...values);
      });
    }

    const previousMovieKeys = new Set(state.home.discoveryMovies.map((item) => item.slug));
    const previousSeriesKeys = new Set(state.home.discoverySeries.map((item) => item.base_slug));
    state.home.discoveryMovies = discoveryV2MergeItems(state.home.discoveryMovies, movies, "movie").slice(0, 220);
    state.home.discoverySeries = discoveryV2MergeItems(state.home.discoverySeries, series, "series").slice(0, 220);
    const newMovies = state.home.discoveryMovies.filter((item) => !previousMovieKeys.has(item.slug));
    const newSeries = state.home.discoverySeries.filter((item) => !previousSeriesKeys.has(item.base_slug));

    await Promise.allSettled([
      discoveryV2HydrateInBatches(newMovies, "movie"),
      discoveryV2HydrateInBatches(newSeries, "series"),
    ]);
    await refreshCatalogJellyfinStatus([
      ...newMovies.map(homeMovieEntry),
      ...newSeries.map(homeSeriesEntry),
    ], null);
    saveHomeCache();
    if (state.tab === "home") {
      state.home.heroIndex = 0;
      renderHome();
    }
    return { movies: state.home.discoveryMovies.length, series: state.home.discoverySeries.length };
  })().catch((error) => {
    console.warn("Discovery-Reservoir konnte nicht vollständig erweitert werden:", error);
    return null;
  });
  return discoveryV2ReservoirPromise;
}

function installDiscoveryEngineV2() {
  if (window.__royalDiscoveryEngineV2Installed) return;
  if (
    typeof homePersonalizedEntries !== "function"
    || typeof homeTopEntries !== "function"
    || typeof loadHomeData !== "function"
  ) return;
  window.__royalDiscoveryEngineV2Installed = true;

  window.homePersonalizedEntries = discoveryV2PersonalizedEntries;
  window.homeTopEntries = discoveryV2TopEntries;

  const originalLoadHomeData = loadHomeData;
  window.loadHomeData = async function discoveryV2LoadHomeData(...args) {
    const result = await originalLoadHomeData(...args);
    window.setTimeout(() => { void warmDiscoveryReservoirV2(); }, 120);
    return result;
  };

  if (typeof restoreHomeCache === "function") {
    const originalRestoreHomeCache = restoreHomeCache;
    window.restoreHomeCache = function discoveryV2RestoreHomeCache(...args) {
      const restored = originalRestoreHomeCache(...args);
      if (restored) window.setTimeout(() => { void warmDiscoveryReservoirV2(); }, 350);
      return restored;
    };
  }

  if (typeof renderHomeRail === "function") {
    const originalRenderHomeRail = renderHomeRail;
    const lanesByTrack = {
      "home-movies-track": "personal",
      "home-explore-track": "explore",
      "home-series-track": "series",
      "home-top-track": "top",
      "home-genre-track": "genre",
      "home-gems-track": "gems",
    };
    window.renderHomeRail = function discoveryV2RenderHomeRail(trackId, entries, options = {}) {
      const result = originalRenderHomeRail(trackId, entries, options);
      const lane = lanesByTrack[trackId];
      if (lane) {
        const visibleCount = options.layout === "spotlight" ? 7 : (options.ranked ? 10 : 16);
        recordDiscoveryExposureV2(lane, (entries || []).slice(0, visibleCount));
      }
      return result;
    };
  }

  if (typeof renderHomeHero === "function") {
    const originalRenderHomeHero = renderHomeHero;
    window.renderHomeHero = function discoveryV2RenderHomeHero(...args) {
      const result = originalRenderHomeHero(...args);
      const candidates = typeof homeHeroCandidates === "function" ? homeHeroCandidates() : [];
      const candidate = candidates[state.home.heroIndex];
      if (candidate) recordDiscoveryExposureV2("hero", [candidate]);
      return result;
    };
  }
}

function installMediaPresentationPolicy() {
  if (window.__royalMediaPresentationPolicyInstalled) return;
  window.__royalMediaPresentationPolicyInstalled = true;

  if (typeof createResultCardVisual === "function") {
    const originalCreateResultCardVisual = createResultCardVisual;
    window.createResultCardVisual = function mediaAwareResultCardVisual(media, ...args) {
      const visual = originalCreateResultCardVisual(media, ...args);
      appendMediaLanguageMarker(visual?.querySelector(".result-card-kind"), media);
      return visual;
    };
  }

  if (typeof createHomeCard === "function") {
    const originalCreateHomeCard = createHomeCard;
    window.createHomeCard = function mediaAwareHomeCard(entry, ...args) {
      const card = originalCreateHomeCard(entry, ...args);
      const media = entry?.kind === "movie"
        ? { ...(entry?.item || {}), ...(state.fp.metadataCache[entry?.item?.slug] || {}) }
        : (entry?.item || {});
      appendMediaLanguageMarker(card?.querySelector(".home-card-type"), media);
      return card;
    };
  }

  if (typeof scheduleFpDetailHeroTrailer === "function") {
    const originalScheduleFpDetailHeroTrailer = scheduleFpDetailHeroTrailer;
    window.scheduleFpDetailHeroTrailer = function stableMovieHeroTrailer(movie) {
      const key = typeof fpTrailerYoutubeKey === "function" ? fpTrailerYoutubeKey(movie) : "";
      const shell = document.getElementById("fp-detail-hero-trailer");
      const sameKey = key
        && typeof fpDetailHeroTrailerKey !== "undefined"
        && fpDetailHeroTrailerKey === key;
      const alreadyActive = sameKey && (
        (shell && !shell.hidden)
        || (typeof fpDetailHeroTrailerTimer !== "undefined" && fpDetailHeroTrailerTimer)
      );
      if (alreadyActive) return;
      return originalScheduleFpDetailHeroTrailer(movie);
    };
  }

  if (typeof configureFpDetailAction === "function") {
    const originalConfigureFpDetailAction = configureFpDetailAction;
    window.configureFpDetailAction = function languageAwareMovieDownload(slug, movie, metadataOnly = false) {
      originalConfigureFpDetailAction(slug, movie, metadataOnly);
      const button = document.getElementById("fp-detail-add");
      if (
        !button
        || metadataOnly
        || state.queuedSlugs.has(slug)
        || !mixedGermanEnglishContentEnabled()
      ) return;
      const languages = movieDownloadLanguageOptions(movie);
      if (!languages.has("de") || !languages.has("en")) return;
      const originalClick = button.onclick;
      button.onclick = async () => {
        const language = await chooseMovieDownloadLanguage(movie);
        if (!language) return;
        const previous = state.fp.downloadSelections.get(slug) || {};
        state.fp.downloadSelections.set(slug, {
          provider: `language:${language}`,
          quality: previous.quality || "",
        });
        await originalClick?.();
      };
    };
  }

  installDiscoveryEngineV2();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", installMediaPresentationPolicy, { once: true });
} else {
  installMediaPresentationPolicy();
}
