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
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", installMediaPresentationPolicy, { once: true });
} else {
  installMediaPresentationPolicy();
}
