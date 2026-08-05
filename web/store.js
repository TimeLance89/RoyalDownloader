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
    wl: { items: [], selected: new Set(), loaded: false },
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
