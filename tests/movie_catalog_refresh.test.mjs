import assert from "node:assert/strict";
import test from "node:test";
import { createCatalogRefresh } from "../web/js/features/discovery/catalog-refresh.js";
import { createScope } from "../web/js/core/lifecycle.js";
import { createPosterPreloader } from "../web/js/features/discovery/poster-preload.js";

function runtime(fetch) {
  const timers = [];
  const applied = [];
  const context = ({
    console, Date, Map, Set,
    document: { hidden: false },
    state: { tab: "filme", fp: {
      category: "new", page: 1, requestSeq: 1, lastCatalogRefreshAt: 0,
      results: [], lastPageFull: true,
    } },
    client: { get: fetch },
    setTimeout: (callback, delay) => { timers.push({ callback, delay }); return timers.length; },
    clearTimeout: () => {},
    applyFpResults: (data) => applied.push(data),
    mergeCatalogItems: (incoming, current) => [
      ...incoming, ...current.filter((item) => !incoming.some((other) => other.slug === item.slug)),
    ],
  });
  const refresh = createCatalogRefresh({
    ...context, movieState: context.state.fp, seriesState: context.state.series, documentRef: context.document,
    scopeFactory() {
      const scope = createScope();
      return { ...scope, get active() { return scope.active; }, timeout(callback, delay) {
        const timer = { callback: () => { if (scope.active) callback(); }, delay };
        timers.push(timer);
        return scope.add(() => { timer.callback = () => {}; });
      } };
    },
  });
  refresh.movies.mount();
  let result;
  context.refreshFpCatalogInBackground = (...args) => { result = refresh.movies.refresh(...args); return result; };
  context.scheduleFpCatalogRefresh = refresh.schedule;
  return { context, timers, applied, refresh, settle: () => result };

}

test("home preview is refreshed even inside the refresh interval", async () => {
  let calls = 0;
  const r = runtime(async () => { calls++; return { results: [], page: 1 }; });
  r.context.state.fp.lastCatalogRefreshAt = Date.now();
  r.context.state.fp.previewFromHome = true;
  r.context.refreshFpCatalogInBackground();
  await r.settle();
  assert.equal(calls, 1);
  assert.equal(r.applied.length, 1);
});

test("new arrivals precede already loaded pages without dropping their contents", async () => {
  const r = runtime(async () => ({ results: [{ slug: "new" }, { slug: "old" }], page: 1 }));
  Object.assign(r.context.state.fp, { page: 3, results: [{ slug: "old" }, { slug: "tail" }] });
  r.context.refreshFpCatalogInBackground();
  await r.settle();
  assert.deepEqual(r.applied[0].results.map((item) => item.slug), ["new", "old", "tail"]);
  assert.equal(r.applied[0].page, 3);
});

test("an outdated refresh cannot replace a newer user request", async () => {
  let resolve;
  const r = runtime(() => new Promise((done) => { resolve = done; }));
  r.context.refreshFpCatalogInBackground();
  r.context.state.fp.requestSeq++;
  resolve({ results: [{ slug: "obsolete" }], page: 1 });
  await r.settle();
  assert.equal(r.applied.length, 0);
});

test("pending providers retry quickly and hidden tabs do not fetch", () => {
  let calls = 0;
  const r = runtime(async () => { calls++; return {}; });
  r.context.scheduleFpCatalogRefresh(true);
  assert.equal(r.timers.at(-1).delay, 5000);
  r.context.document.hidden = true;
  r.timers.at(-1).callback();
  assert.equal(calls, 0);
  assert.equal(r.timers.at(-1).delay, 60000);
});

test("leaving a catalog aborts refresh and ignores its late response", async () => {
  let resolve, signal;
  const r = runtime((_url, options) => { signal = options.signal; return new Promise(done => { resolve = done; }); });
  const request = r.context.refreshFpCatalogInBackground();
  r.refresh.movies.unmount();
  assert.equal(signal.aborted, true);
  resolve({ results: [{ slug: "late" }] });
  await request;
  assert.equal(r.applied.length, 0);
  const count = r.timers.length;
  r.timers.at(-1).callback();
  assert.equal(r.timers.length, count);
});

test("poster preloading cancels stalled images and does not start another batch", async () => {
  const images = [];
  const preloader = createPosterPreloader({ candidates: cover => [cover], createImage() {
    const image = { removeAttribute() { this.src = ""; } };
    images.push(image); return image;
  } });
  const controller = new AbortController();
  const request = preloader.preload(Array.from({ length: 20 }, (_, i) => ({ cover_url: `/${i}` })), 6000, controller.signal);
  assert.equal(images.length, 6);
  controller.abort();
  await request;
  assert.equal(images.length, 6);
  assert.ok(images.every(image => image.onload === null && image.onerror === null && image.src === ""));
});

test("cancelled metadata cannot modify cards, cache, or reconciliation after a late response", async () => {
  const { createCatalogMetadata } = await import("../web/js/features/discovery/catalog-metadata.js");
  const state = { fp: { metadataRequestSeq: 1, metadataCache: {}, results: [], pendingPreload: new Set(["a"]) } };
  let resolve, signal, updates = 0;
  const changed = () => { updates++; };
  const metadata = createCatalogMetadata({ movieState: state.fp, seriesState: state.series, getActiveTab: () => state.tab, getQueuedSlugs: () => state.queuedSlugs, updateFpResultCard: changed,
    refreshFpJellyfinStatus: changed, refreshMovieFeatureCandidates: changed,
    showFpDetail: changed, metadataPreviewMovie: changed, reconcileMovieCatalogDuplicates: changed,
    client: { post(_url, _body, options) { signal = options.signal; return new Promise(done => { resolve = done; }); } },
  });
  const request = metadata.preload(1, [{ slug: "a" }]);
  metadata.unmount();
  assert.equal(signal.aborted, true);
  resolve({ movies: { a: { cover_url: "/late" } } });
  await request;
  assert.deepEqual(state.fp.metadataCache, {});
  assert.equal(state.fp.pendingPreload, null);
  assert.equal(updates, 0);
});

test("logical catalog identity preserves provider priority, languages, ownership and remakes", async () => {
  const { createCatalogIdentity, cleanMediaCardInitials } = await import("../web/js/features/discovery/catalog-identity.js");
  const identity = createCatalogIdentity({ getMetadata: slug => slug === "translated" ? { tmdb_id: 42 } : null });
  const records = identity.dedupe([
    { slug: "priority", title: "Original", tmdb_id: 42, sources: [{ key: "a", content_language: "de" }] },
    { slug: "translated", title: "Übersetzung", content_language: "en", in_jellyfin: true, sources: [{ key: "b" }] },
    { slug: "remake", title: "Original", tmdb_id: 43 },
  ]);
  assert.equal(records.length, 2);
  assert.equal(records[0].slug, "priority");
  assert.deepEqual(records[0].content_languages, ["en", "de"]);
  assert.deepEqual(records[0].sources.map(source => source.key), ["a", "b"]);
  assert.equal(records[0].jellyfin_status, "owned");
  assert.equal(records[1].slug, "remake");
  assert.equal(cleanMediaCardInitials("- The Odyssey"), "TO");
  assert.equal(cleanMediaCardInitials("..."), "RD");
});

test("movie browsing replaces requests, searches on submit and removes listeners on unmount", async () => {
  const { createMovieBrowse } = await import("../web/js/features/discovery/movie-browse.js");
  const nodes = new Map();
  const root = { querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, Object.assign(new EventTarget(), { value: "", childElementCount: 0 }));
    return nodes.get(id);
  } };
  const state = { tab: "filme", fp: { results: [], sources: [], requestSeq: 0, filters: {} } };
  const requests = [], applied = [];
  const noop = () => {};
  const browse = createMovieBrowse(root, { movieState: state.fp, seriesState: state.series, getActiveTab: () => state.tab, getQueuedSlugs: () => state.queuedSlugs, syncSearchClearButtons: noop, closeSearchSuggestions: noop,
    rememberSearch: noop, applyFpResults: data => applied.push(data), setActiveGenreFilter: noop,
    renderFpResults: noop, updateFpInfiniteState: noop, refreshMovieFeatureCandidates: noop,
    syncFpCatalogFromHome: noop, refreshFpCatalogInBackground: noop, getGenres: () => [],
    applyFpSmartFilters: noop, resetFpSmartFilters: noop, cancelMetadata: noop,
    client: { get(url, options) { return new Promise(resolve => { requests.push({ url, options, resolve }); }); } },
  });
  browse.mount(); browse.mount();
  root.querySelector("#fp-search").value = "Query";
  root.querySelector("#fp-search").dispatchEvent(new Event("input"));
  assert.equal(requests.length, 0);
  const search = browse.search();
  assert.equal(requests[0].options.timeoutMs, 0);
  const list = browse.list("top");
  assert.equal(requests[0].options.signal.aborted, true);
  requests[0].resolve({ results: ["obsolete"] });
  requests[1].resolve({ results: ["top"] });
  await Promise.all([search, list]);
  assert.deepEqual(applied, [{ results: ["top"] }]);
  const pending = browse.list("new");
  browse.unmount();
  assert.equal(requests[2].options.signal.aborted, true);
  requests[2].resolve({ results: ["late"] });
  await pending;
  assert.equal(applied.length, 1);
  root.querySelector("#fp-top-btn").dispatchEvent(new Event("click"));
  assert.equal(requests.length, 3);
  browse.mount();
  root.querySelector("#fp-top-btn").dispatchEvent(new Event("click"));
  assert.equal(requests.length, 4);
  browse.unmount(); requests[3].resolve({ results: [] });
});

test("series browsing retains search return state and cancels pagination on navigation", async () => {
  const { createSeriesBrowse } = await import("../web/js/features/discovery/series-browse.js");
  const nodes = new Map();
  const makeNode = () => Object.assign(new EventTarget(), {
    value: "", childElementCount: 0, children: [],
    replaceChildren() { this.children = []; }, appendChild(node) { this.children.push(node); },
  });
  const root = { ownerDocument: { createElement: makeNode }, querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, makeNode());
    return nodes.get(id);
  } };
  const state = { tab: "serien", series: { results: [{ base_slug: "existing" }], sources: [],
    browseRequestSeq: 0, browseMode: "discover", page: 2, lastPageFull: true, epPicked: new Set() } };
  const requests = [], applied = [];
  const noop = () => {};
  const browse = createSeriesBrowse(root, { movieState: state.fp, seriesState: state.series, getActiveTab: () => state.tab, getQueuedSlugs: () => state.queuedSlugs, syncSearchClearButtons: noop, closeSearchSuggestions: noop,
    rememberSearch: noop, applySeriesResults: data => applied.push(data), renderSeriesTiles: noop,
    updateSeriesInfiniteState: noop, showSeriesDetail: noop, firstEpisodeSlug: noop, updateSeriesStatus: noop,
    refreshSeriesJellyfinStatus: noop, recheckSeriesInfinite: noop, preloadSeriesPosterImages: noop,
    syncSeriesCatalogFromHome: noop, renderSeriesResults: noop, refreshSeriesCatalogInBackground: noop,
    client: { get(url, options) { return new Promise(resolve => { requests.push({ url, options, resolve }); }); } },
  });
  browse.mount(); browse.mount();
  assert.equal(root.querySelector("#series-alpha-bar").children.length, 27);
  root.querySelector("#series-search").value = "Query";
  const search = browse.search();
  await browse.restore();
  assert.equal(requests[0].options.signal.aborted, true);
  assert.equal(state.series.browseMode, "discover");
  assert.deepEqual(applied[0].results, [{ base_slug: "existing" }]);
  requests[0].resolve({ results: ["obsolete"] }); await search;
  assert.equal(applied.length, 1);
  const page = browse.next();
  assert.ok(requests[1].url.includes("page=3"));
  browse.unmount(); requests[1].resolve({ results: ["late"] }); await page;
  assert.equal(requests[1].options.signal.aborted, true);
  assert.equal(applied.length, 1);
  browse.mount();
  assert.equal(root.querySelector("#series-alpha-bar").children.length, 27);
  browse.unmount();
});

test("closing movie details cancels metadata and provider lookup without late cache writes", async () => {
  const { createMovieDetailsLoader } = await import("../web/js/features/media-details/movie-loader.js");
  for (const cachedMetadata of [false, true]) {
    const state = { fp: { selectedSlug: null, requestSeq: 0, results: [{ slug: "movie", title: "Movie" }],
      moviesCache: {}, metadataCache: cachedMetadata ? { movie: { details_loaded: true } } : {} } };
    const requests = []; let changes = 0;
    const changed = () => { changes++; };
    const fetch = (url, options) => new Promise(resolve => { requests.push({ url, options, resolve }); });
    const details = createMovieDetailsLoader({ movieState: state.fp, seriesState: state.series, getActiveTab: () => state.tab, getQueuedSlugs: () => state.queuedSlugs, updateFpResultSelection: changed,
      homeMovieBySlug: () => null, trackDiscoveryPreference: changed, showFpDetail: changed,
      metadataPreviewMovie: value => value, basicMovieMetadata: value => value,
      setFpDetailAvailability: changed, openMediaModal: changed, findFpResultCard: () => null,
      updateFpResultCard: changed, refreshMovieFeatureCandidates: changed, refreshFpJellyfinStatus: changed,
      client: { post: (url, _body, options) => fetch(url, options), get: fetch },
    });
    const request = details.open("movie");
    await Promise.resolve();
    // Uncached metadata and provider lookup now start independently.
    assert.equal(requests.length, cachedMetadata ? 1 : 2);
    const metadataBeforeClose = structuredClone(state.fp.metadataCache);
    details.unmount();
    const before = changes;
    for (const pending of requests) {
      assert.equal(pending.options.signal.aborted, true);
      pending.resolve(pending.url === "/api/tmdb/movie" ? { movie: { title: "late metadata" } } : { title: "late provider" });
    }
    await request;
    assert.equal(requests.length, cachedMetadata ? 1 : 2);
    assert.equal(changes, before);
    assert.deepEqual(state.fp.moviesCache, {});
    assert.deepEqual(state.fp.metadataCache, metadataBeforeClose);
  }
});

test("closing series details discards late provider and subscription responses", async () => {
  const { createSeriesDetailsLoader } = await import("../web/js/features/media-details/series-loader.js");
  for (const subscription of [false, true]) {
    const state = { series: { pendingBaseSlug: "", requestSeq: 0, viewGeneration: 0, cache: {} } };
    let resolve, signal, endpoint, changes = 0;
    const changed = () => { changes++; };
    const loader = createSeriesDetailsLoader({ querySelector: () => ({}) }, {}, {
      movieState: state.fp, seriesState: state.series, getActiveTab: () => state.tab, getQueuedSlugs: () => state.queuedSlugs, trackDiscoveryPreference: changed, updateSeriesResultSelection: changed, showSeriesLoading: changed,
      openMediaModal: changed, findSeriesResultCard: () => null, showSeriesDetail: changed,
      updateSeriesStatus: changed, refreshSeriesJellyfinStatus: changed, switchTab: changed,
      firstEpisodeSlug: changed, seriesEpisodes: () => [], isEpisodeSelectable: () => true,
      renderSeriesTiles: changed, syncWatchlistSnapshot: changed,
      client: { post(url, _body, options) { endpoint = url; signal = options.signal;
        return new Promise(done => { resolve = done; }); } },
    });
    const request = subscription ? loader.openSubscription("series")
      : loader.open({ base_slug: "monster-tmdb:123", sample_slug: "episode", title: "Series" });
    assert.equal(endpoint, subscription ? "/api/watchlist/open" : "/api/series/monster-tmdb-load");
    loader.unmount();
    const before = changes;
    assert.equal(signal.aborted, true);
    resolve({ title: "late", seasons: [] }); await request;
    assert.equal(changes, before);
    assert.equal(state.series.pendingBaseSlug, "");
  }
});

test("SerienStream language truth auto-checks after hydration without an episode click", async () => {
  const { createSeriesChecks } = await import("../web/js/features/media-details/series-checks.js");
  const initial = {
    base_slug: "serienstream:american-horror-story",
    provider: "serienstream",
    title: "American Horror Story",
    seasons: [{
      season: 13,
      episodes: [
        { slug: "serienstream:american-horror-story-s13e01", season: 13, episode: 1, in_jellyfin: true },
        { slug: "serienstream:american-horror-story-s13e03", season: 13, episode: 3 },
        { slug: "serienstream:american-horror-story-s13e04", season: 13, episode: 4 },
        { slug: "serienstream:american-horror-story-s13e07", season: 13, episode: 7, unreleased: true },
      ],
    }],
  };
  const state = {
    series: {
      current: initial,
      currentSampleSlug: initial.seasons[0].episodes[1].slug,
      cache: {},
      viewGeneration: 1,
    },
  };
  const status = { textContent: "" };
  const requests = [];
  const noop = () => {};
  const checks = createSeriesChecks(status, {
    seriesState: state.series,
    isVisible: () => true,
    firstEpisodeSlug: () => initial.seasons[0].episodes[0].slug,
    pruneSeriesEpisodeSelection: noop,
    refreshSeriesTileStates: noop,
    updateSeriesStatus: noop,
    syncSeriesQueueFlags: noop,
    seriesStructureFingerprint: series => JSON.stringify(series?.seasons || []),
    mergeSeriesDetailPayload: (_current, refreshed) => refreshed,
    updateSeriesOverview: noop,
    updateWatchBtn: noop,
    renderSeriesTiles: noop,
    client: {
      post(url, body, options) {
        return new Promise(resolve => requests.push({ url, body, options, resolve }));
      },
    },
  });

  const refresh = checks.refresh(false);
  assert.equal(requests.length, 2);
  const jellyfin = requests.find(request => request.url === "/api/series/jellyfin-status");
  const detail = requests.find(request => request.url === "/api/series/load");
  assert.ok(jellyfin);
  assert.ok(detail);

  jellyfin.resolve({
    episodes: {},
    configured: true,
    available: true,
    stale: false,
    checked_at: 1,
  });
  detail.resolve({
    ...initial,
    provider_content_languages: ["de", "en"],
    seasons: [{
      season: 13,
      episodes: initial.seasons[0].episodes.map(episode => ({ ...episode })),
    }],
  });

  await new Promise(resolve => setImmediate(resolve));
  const language = requests.find(request => request.url === "/api/series/episode-languages");
  assert.ok(language, "detail hydration must trigger language verification automatically");
  assert.deepEqual(language.body.slugs, [
    "serienstream:american-horror-story-s13e03",
    "serienstream:american-horror-story-s13e04",
  ]);

  language.resolve({
    available: {
      "serienstream:american-horror-story-s13e03": false,
      "serienstream:american-horror-story-s13e04": true,
    },
    languages: {
      "serienstream:american-horror-story-s13e03": ["en"],
      "serienstream:american-horror-story-s13e04": ["de", "en"],
    },
  });
  assert.equal(await refresh, true);

  const [e01, e03, e04, e07] = state.series.current.seasons[0].episodes;
  assert.equal(e01.language_checked, undefined, "local/Jellyfin episodes need no remote language probe");
  assert.equal(e03.language_checked, true);
  assert.equal(e03.language_available, false);
  assert.deepEqual(e03.content_languages, ["en"]);
  assert.equal(e04.language_checked, true);
  assert.equal(e04.language_available, true);
  assert.deepEqual(e04.content_languages, ["de", "en"]);
  assert.equal(e07.language_checked, undefined, "unreleased episodes must not be probed");
  checks.unmount();
});


test("series detail checks abort both status requests and language batches on close", async () => {
  const { createSeriesChecks } = await import("../web/js/features/media-details/series-checks.js");
  const series = { base_slug: "series", provider: "huhu", seasons: [] };
  const state = { series: { current: series, cache: {}, viewGeneration: 1 } };
  const requests = []; let changes = 0;
  const changed = () => { changes++; };
  const checks = createSeriesChecks({}, { movieState: state.fp, seriesState: state.series, getActiveTab: () => state.tab, getQueuedSlugs: () => state.queuedSlugs, isVisible: () => true, firstEpisodeSlug: () => "episode",
    pruneSeriesEpisodeSelection: changed, refreshSeriesTileStates: changed, updateSeriesStatus: changed,
    syncSeriesQueueFlags: changed, seriesStructureFingerprint: changed, mergeSeriesDetailPayload: changed,
    updateSeriesOverview: changed, updateWatchBtn: changed, renderSeriesTiles: changed,
    client: { post(url, _body, options) { return new Promise(resolve => { requests.push({ url, options, resolve }); }); } },
  });
  const refresh = checks.refresh(true);
  assert.equal(requests.length, 2);
  checks.unmount();
  assert.ok(requests.every(request => request.options.signal.aborted));
  requests.forEach(request => request.resolve({ episodes: {}, seasons: [] }));
  assert.equal(await refresh, false);
  assert.equal(changes, 0);
  assert.deepEqual(state.series.cache, {});
  const episode = { slug: "episode" };
  const language = checks.verifyLanguages([episode], series);
  checks.unmount();
  requests[2].resolve({ available: { episode: true } });
  await assert.rejects(language, { name: "AbortError" });
  assert.equal(episode.huhu_language_checked, undefined);
  assert.equal(changes, 0);
});

test("anime owns local state and discards catalog and detail responses after unmount", async () => {
  const { createAnime } = await import("../web/js/features/discovery/anime.js");
  const makeNode = () => Object.assign(new EventTarget(), {
    value: "", textContent: "", innerHTML: "", style: {}, classList: { toggle() {} },
    setAttribute() {}, appendChild() {}, replaceChildren() {}, removeAttribute() {},
  });
  const nodes = new Map();
  const root = Object.assign(makeNode(), { ownerDocument: { createElement: makeNode }, querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, makeNode());
    return nodes.get(id);
  } });
  const modal = Object.assign(makeNode(), { id: "anime-detail-modal", hidden: true, querySelector: root.querySelector });
  const requests = [];
  const noop = () => {};
  const anime = createAnime(root, modal, { getQueuedSlugs: () => new Set(), coverUrl: value => value,
    mediaCardInitials: () => "AF", mediaJellyfinStatus: () => "checking", jellyfinStatusText: () => "checking",
    refreshCatalogJellyfinStatus: noop, homeAnimeEntry: value => value,
    openMediaModal: () => { modal.hidden = false; }, trackDiscoveryPreference: noop, refreshQueueUiAfterChange: noop,
    client: { get(url, options) { return new Promise(resolve => { requests.push({ url, options, resolve }); }); } },
  });
  anime.mount();
  const browse = anime.browse("latest");
  anime.unmount();
  assert.equal(requests[0].options.signal.aborted, true);
  requests[0].resolve({ results: [{ id: "late" }] }); await browse;
  assert.deepEqual(anime.get().results, []);
  assert.equal(anime.get().loading, false);
  const details = anime.open({ id: "fixture", title: "Anime", translations: { dub: 2 } });
  assert.equal(requests.length, 2, "details may open from Home without the catalog mounted");
  anime.closeDetail();
  requests[1].resolve({ episodes: [{ slug: "late" }], translation: "dub", page: 1 }); await details;
  assert.equal(requests[1].options.signal.aborted, true);
  assert.deepEqual(anime.get().current.episodes, []);
  anime.dispose();
});

test("AniWorld cancels poster and detail work while retaining its last catalog", async () => {
  const { createAniworld } = await import("../web/js/features/discovery/aniworld.js");
  const makeNode = () => Object.assign(new EventTarget(), {
    value: "", textContent: "", innerHTML: "", style: {}, dataset: {}, classList: { toggle() {} },
    setAttribute() {}, appendChild() {}, replaceChildren() {}, removeAttribute() {},
  });
  const nodes = new Map();
  const root = Object.assign(makeNode(), { ownerDocument: { createElement: makeNode }, querySelectorAll: () => [], querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, makeNode());
    return nodes.get(id);
  } });
  const modal = Object.assign(makeNode(), { id: "aniworld-detail-modal", hidden: true, querySelector: root.querySelector });
  const requests = [];
  const fetch = (url, options) => new Promise(resolve => { requests.push({ url, options, resolve }); });
  const aniworld = createAniworld(root, modal, { getQueuedSlugs: () => new Set(), coverUrl: value => value,
    mediaCardInitials: () => "AW", openMediaModal: () => { modal.hidden = false; },
    recheckAniworldInfinite() {}, refreshQueueUiAfterChange() {},
    client: { get: fetch, post: (url, _body, options) => fetch(url, options) },
  });
  aniworld.mount();
  const browse = aniworld.browse("catalog");
  requests[0].resolve({ results: [{ id: "fixture", title: "Fixture" }], page: 1 }); await browse;
  assert.equal(requests[1].url, "/api/aniworld/posters");
  aniworld.unmount();
  assert.equal(requests[1].options.signal.aborted, true);
  requests[1].resolve({ posters: { fixture: "/late" } });
  await Promise.resolve();
  assert.equal(aniworld.get().posterCache.size, 0);
  assert.equal(aniworld.get().results.length, 1);
  const detail = aniworld.open({ id: "fixture", title: "Fixture" });
  aniworld.closeDetail();
  requests[2].resolve({ episodes: [{ slug: "late" }] }); await detail;
  assert.equal(requests[2].options.signal.aborted, true);
  assert.deepEqual(aniworld.get().current.episodes, []);
  aniworld.dispose();
});

test("taste profile responses cannot leak across users or survive session end", async () => {
  const { createTasteProfile } = await import("../web/js/features/profile/taste.js");
  let user = { id: "first" }, changes = 0;
  const saved = new Map(), requests = [];
  const profile = createTasteProfile({ defaultView: {} }, {
    getUser: () => user, currentTasteTarget: () => null, renderTasteProfileSummary: () => { changes++; },
    shouldRenderHome: () => false, renderHome() {}, homeMovieEntry: item => ({ item }), homeSeriesEntry: item => ({ item }),
    homeEntryMedia: entry => entry.item, homeEntryKey: entry => entry.item.slug, onReset() {},
    storage: { getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value) },
    client: { get(url, options) { return new Promise(resolve => { requests.push({ url, options, resolve }); }); } },
  });
  const first = profile.sync();
  user = { id: "second" };
  requests[0].resolve({ interactions: 99 }); await first;
  assert.equal(saved.size, 0);
  assert.equal(changes, 0);
  const second = profile.sync();
  profile.unmount();
  assert.equal(requests[1].options.signal.aborted, true);
  requests[1].resolve({ interactions: 100 }); await second;
  assert.equal(saved.size, 0);
});

test("collections abort closed reads and isolate late queue results from the next detail", async () => {
  const { createMovieCollections } = await import("../web/js/features/collections/index.js");
  const makeNode = () => Object.assign(new EventTarget(), {
    value: "", textContent: "", dataset: {}, style: { setProperty() {} },
    classList: { toggle() {} }, setAttribute() {}, append() {}, appendChild() {}, replaceChildren() {},
  });
  const document = Object.assign(new EventTarget(), { createElement: makeNode });
  const nodes = new Map();
  const root = { ownerDocument: document, querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, makeNode());
    return nodes.get(id);
  } };
  const requests = [], movieCache = {}, metadata = {}, queued = new Set();
  let queueUpdates = 0;
  const request = (url, body, options) => new Promise(resolve => requests.push({ url, body, options, resolve }));
  const model = createMovieCollections(root, {
    client: { get: (url, options) => request(url, null, options), post: request },
    getMovieCache: () => movieCache, getMetadataCache: () => metadata, getQueuedSlugs: () => queued,
    coverCandidates: () => [], coverUrl: () => "", mediaCardInitials: () => "F", openMediaModal() {},
    selectFpRow() {}, applyMovieJellyfinStatus() {}, refreshQueueUiAfterChange() { queueUpdates++; },
  });
  model.mount(); model.mount();
  const first = model.open(1);
  model.close();
  assert.equal(requests[0].options.signal.aborted, true);
  requests[0].resolve({ collection: { title: "Late", parts: [] } }); await first;
  assert.equal(model.get().collection, null);
  const second = model.open(2);
  const part = { slug: "tmdb:2", tmdb_id: 2, title: "Film", release_date: "2000-01-01" };
  requests[1].resolve({ collection: { title: "Second", parts: [part] } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests[2].url, "/api/jellyfin/matches");
  requests[2].resolve({ matches: { "tmdb:2": false } }); await second;
  assert.match(requests[3].url, /\/api\/movie\//);
  requests[3].resolve({ title: "Film", source_count: 1 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(model.get().availability.get(part.slug).selected, true);
  nodes.get("#movie-collection-download-all").dispatchEvent(new Event("click"));
  nodes.get("#movie-collection-download-all").dispatchEvent(new Event("click"));
  assert.equal(requests.length, 5, "duplicate clicks cannot submit twice");
  const third = model.open(3);
  requests[4].resolve({ skipped_details: { "tmdb:2": "späte Antwort" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(queueUpdates, 1, "the shared queue snapshot still receives its response");
  assert.equal(model.get().availability.size, 0);
  model.unmount();
  assert.equal(requests[5].options.signal.aborted, true);
  requests[5].resolve({ collection: { title: "Too late", parts: [] } }); await third;
  assert.equal(model.get().collection, null);
});

test("movie mutations deduplicate clicks and stop cache and queue writes after session disposal", async () => {
  const { createMovieDownloads } = await import("../web/js/features/downloads/movies.js");
  const nodes = new Map();
  const root = { hidden: false, querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, Object.assign(new EventTarget(), { textContent: "", hidden: false }));
    return nodes.get(id);
  } };
  const movieState = { selectedSlug: "one", moviesCache: {}, metadataCache: {}, results: [], downloadSelections: new Map() };
  const requests = [], shown = [], queue = [];
  const request = (url, body, options) => new Promise(resolve => requests.push({ url, body, options, resolve }));
  const model = createMovieDownloads(root, { movieState, getQueuedSlugs: () => new Set(), homeMovieBySlug: () => null,
    updateFpResultCard() {}, showFpDetail: slug => shown.push(slug), setDownloadState() {},
    refreshQueueUiAfterChange: response => queue.push(response), refreshFpQueuePresentation() {}, trackDiscoveryPreference() {},
    metadataPreviewMovie: item => item, basicMovieMetadata: item => item, fpDetailJellyfinValue: () => false,
    needsLanguageChoice: () => false, chooseLanguage: async () => "de",
    client: { get: (url, options) => request(url, null, options), post: request },
  });
  model.mount(); model.mount();
  const movie = { title: "One", hosters: [{}] };
  const first = model.toggle("one", { movie });
  await model.toggle("one", { movie });
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0].body, { slugs: ["one"], preferences: {}, source: "web" });
  movieState.selectedSlug = "two"; model.closeDetail();
  requests[0].resolve({ added: 1 }); await first;
  assert.equal(queue.length, 1);
  assert.deepEqual(shown, []);
  assert.equal(model.pending("one"), false);
  const second = model.toggle("two");
  assert.match(requests[1].url, /\/api\/movie\/two/);
  model.unmount(); model.mount();
  assert.equal(requests[1].options.signal.aborted, true);
  requests[1].resolve({ title: "Late", hosters: [{}] }); await second;
  assert.deepEqual(movieState.moviesCache, {});
  assert.equal(requests.length, 2);
  assert.equal(queue.length, 1);
  model.unmount();
});

test("series queue responses preserve a newly opened selection and stop at session end", async () => {
  const { createSeriesEpisodes } = await import("../web/js/features/media-details/series-episodes.js");
  const node = () => Object.assign(new EventTarget(), { dataset: {}, textContent: "", innerHTML: "",
    setAttribute() {}, removeAttribute() {}, append() {}, appendChild() {}, prepend() {},
    querySelector: () => null, querySelectorAll: () => [],
  });
  const nodes = new Map();
  const root = Object.assign(node(), { hidden: false, ownerDocument: { createElement: node }, querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, node());
    return nodes.get(id);
  } });
  const firstSeries = { title: "First", seasons: [{ season: 1, episodes: [{ slug: "one", episode: 1 }] }] };
  const nextSeries = { title: "Next", seasons: [{ season: 1, episodes: [{ slug: "two", episode: 1 }] }] };
  const seriesState = { current: firstSeries, epPicked: new Set(["one"]), viewGeneration: 1 };
  const requests = [], tracked = [], queue = [], status = { textContent: "" };
  const model = createSeriesEpisodes(root, { status, seriesState, getQueuedSlugs: () => new Set(),
    getEnabledLanguages: () => [], verifyHuhuEpisodeLanguages: async () => {},
    trackDiscoveryPreference: (_kind, series) => tracked.push(series), refreshQueueUiAfterChange: data => queue.push(data),
    client: { post: (url, body, options) => new Promise(resolve => requests.push({ url, body, options, resolve })) },
  });
  model.mount(); model.mount();
  const first = model.seriesAddSelected(); await model.seriesAddSelected();
  assert.equal(requests.length, 1);
  seriesState.current = nextSeries; seriesState.viewGeneration++;
  seriesState.epPicked = new Set(["two"]); status.textContent = "New detail";
  requests[0].resolve({ added: 1 }); await first;
  assert.deepEqual([...seriesState.epPicked], ["two"]);
  assert.equal(status.textContent, "New detail");
  assert.deepEqual(tracked, [firstSeries]); assert.equal(queue.length, 1);
  const second = model.seriesAddSelected(); model.unmount();
  assert.equal(requests[1].options.signal.aborted, true);
  requests[1].resolve({ added: 1 }); await second;
  assert.deepEqual([...seriesState.epPicked], ["two"]);
  assert.equal(queue.length, 1);
});

test("movie availability cancellation cannot drain pending work or clear a newer worker", async () => {
  const { createMovieStatus } = await import("../web/js/features/integrations/movie-status.js");
  const requests = [], movieState = { results: [{ slug: "one" }], selectedSlug: "one" };
  let rendered = 0;
  const model = createMovieStatus({ movieState, homeMovieBySlug: () => null, homeMovieEntry: item => ({ item }),
    updateFpJellyfinBadges: () => rendered++, setFpDetailJellyfinStatus: () => rendered++,
    refreshCatalogJellyfinStatus: (entries, _render, options) => new Promise(resolve => requests.push({ entries, options, resolve })),
  });
  const first = model.refresh(); model.refresh([{ slug: "pending" }]); model.cancel();
  assert.equal(requests[0].options.signal.aborted, true);
  const next = model.refresh([{ slug: "next" }]);
  requests[0].resolve(); await first;
  model.refresh([{ slug: "third" }]);
  assert.equal(requests.length, 2, "the cancelled worker cannot release its replacement");
  requests[1].resolve(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 3);
  assert.equal(requests[2].entries[0].item.slug, "third");
  requests[2].resolve(); await next;
  assert.equal(rendered, 2);
  model.unmount(); await model.refresh();
  assert.equal(requests.length, 3);
});

test("localization cancels translations at session end without persisting late replies", async t => {
  const { createLocalization } = await import("../web/js/core/localization.js");
  const previousNode = globalThis.Node; globalThis.Node = { TEXT_NODE: 3, ELEMENT_NODE: 1, DOCUMENT_NODE: 9 };
  t.after(() => { if (previousNode === undefined) delete globalThis.Node; else globalThis.Node = previousNode; });
  const stored = new Map(), requests = [], observers = [];
  const document = { documentElement: { nodeType: 0 }, getElementById: () => null,
    defaultView: { localStorage: { getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value) },
      MutationObserver: class { constructor() { observers.push(this); } observe() { this.active = true; } disconnect() { this.active = false; } },
    },
  };
  const model = createLocalization(document, { client: {
    get: async () => ({ language: "en", configured: true }),
    post: (url, body, options) => new Promise(resolve => requests.push({ url, body, options, resolve })),
  } });
  await model.initialize(); model.mount();
  const first = model.translateTexts(["Fixture text"]);
  model.unmount();
  assert.equal(requests[0].options.signal.aborted, true); assert.equal(observers[0].active, false);
  requests[0].resolve({ translations: ["Late translation"] });
  assert.deepEqual(await first, ["Fixture text"]);
  assert.equal(stored.has("royal.ui.translations.en"), false);
  model.mount(); model.mount();
  const next = model.translateTexts(["Fixture text"]);
  assert.equal(requests.length, 2); assert.equal(observers.length, 2);
  requests[1].resolve({ translations: ["Current translation"] });
  assert.deepEqual(await next, ["Current translation"]);
  assert.equal(JSON.parse(stored.get("royal.ui.translations.en"))["Fixture text"], "Current translation");
  model.unmount();
});

test("shell mounts controls once and ignores command responses after unmount", async () => {
  const { createShell } = await import("../web/js/core/shell.js");
  const nodes = new Map(), requests = [], accepted = [];
  const node = () => Object.assign(new EventTarget(), { hidden: true, disabled: false, classList: { add() {} } });
  const document = Object.assign(new EventTarget(), { defaultView: new EventTarget(), querySelectorAll: () => [],
    querySelector: () => node(), getElementById(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
  });
  const noop = () => {};
  const shell = createShell(document, { switchTab: noop, openMobileQueue: noop, closeMobileQueue: noop,
    toggleDesktopQueue: noop, closeMediaModal: noop, openWatchModeModal: noop, handleMediaModalKeydown: noop,
    closeNotifications: noop, setQueueDockExpanded: noop, refreshQueueUiAfterChange: data => accepted.push(data),
    renderSerienstreamHealth: noop, setDownloadState: noop, getDownloadPercent: () => 0, openDirectory: noop,
    client: { post: (url, body, options) => new Promise(resolve => requests.push({ url, body, options, resolve })) },
  });
  shell.mount(); shell.mount();
  nodes.get("queue-clear").dispatchEvent(new Event("click")); nodes.get("queue-clear").dispatchEvent(new Event("click"));
  assert.equal(requests.length, 1);
  shell.unmount(); assert.equal(requests[0].options.signal.aborted, true);
  requests[0].resolve({ queue: {} }); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(accepted, []);
  nodes.get("queue-clear").dispatchEvent(new Event("click")); assert.equal(requests.length, 1);
  shell.mount(); nodes.get("queue-clear").dispatchEvent(new Event("click"));
  requests[1].resolve({ queue: {} }); await new Promise(resolve => setImmediate(resolve));
  assert.equal(accepted.length, 1); shell.unmount();
});
