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
      mood: { step: 0, answers: {}, results: [], open: false },
      search: { scope: "all", query: "", results: [], active: false, loading: false, requestSeq: 0 },
    },
    fp: {
      results: [], moviesCache: {}, category: null, page: 1, lastPageFull: false,
      activeGenre: "Alle Genres", selectedSlug: null, pendingPreload: null,
      metadataCache: {}, requestSeq: 0, sources: [], loadingMore: false,
      loadError: "", searchActive: false, searchReturn: null,
      featureCandidates: [], featureIndex: 0, featureTimer: null,
      featurePaused: false, downloadSelections: new Map(),
    },
    series: {
      results: [], browseMode: null, page: 1, lastPageFull: false,
      sources: [], browseRequestSeq: 0, loadingBrowse: false, loadError: "",
      current: null, currentSampleSlug: "", epPicked: new Set(), cache: {},
      pendingBaseSlug: "", requestSeq: 0, viewGeneration: 0,
      jellyfinRefreshSeq: 0, jellyfinRefreshByBase: new Map(), searchReturn: null,
    },
    anime: {
      results: [], mode: null, query: "", page: 1, hasMore: false,
      loaded: false, loading: false, requestSeq: 0, detailSeq: 0,
      currentId: "", current: null, translation: "", episodePage: 1,
      picked: new Set(), searchReturn: null,
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
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", installMediaPresentationPolicy, { once: true });
} else {
  installMediaPresentationPolicy();
}
