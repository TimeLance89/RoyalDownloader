import { createProfileActions } from "../../web/js/features/profile/actions.js";
import { supportedProviderLanguages, providerMatchesLanguages } from "../../web/js/shared/utils/provider-languages.js";

test("provider capabilities intersect selection without duplicating legacy primary language", () => {
  const bilingual = { content_language: "de", content_languages: ["de", "en", "de"] };
  assert.deepEqual(supportedProviderLanguages(bilingual), ["de", "en"]);
  assert.equal(providerMatchesLanguages(bilingual, new Set(["en"])), true);
  assert.equal(providerMatchesLanguages(bilingual, new Set(["de"])), true);
  assert.equal(providerMatchesLanguages({ content_language: "en" }, new Set(["de"])), false);
  assert.deepEqual(supportedProviderLanguages({ content_language: "de" }), ["de"]);
});
import { createHomeActions } from "../../web/js/features/home/actions.js";
import { createTabScrollMemory } from "../../web/js/shell/actions.js";

test("home action instances keep injected catalogs isolated and resolve late peers", () => {
  let currentCatalog;
  const first = createHomeActions({ getHomeCatalog: () => currentCatalog });
  const second = createHomeActions({
    getHomeCatalog: () => ({ homeMovieBySlug: slug => ({ slug, owner: "second" }) }),
  });
  // Construction must not access a peer before domain composition finishes.
  currentCatalog = { homeMovieBySlug: slug => ({ slug, owner: "first" }) };
  assert.deepEqual(first.homeMovieBySlug("shared-slug"), { slug: "shared-slug", owner: "first" });
  assert.deepEqual(second.homeMovieBySlug("shared-slug"), { slug: "shared-slug", owner: "second" });
  currentCatalog = { homeMovieBySlug: () => null };
  assert.equal(first.homeMovieBySlug("shared-slug"), null);
  assert.equal(second.homeMovieBySlug("shared-slug").owner, "second");
});
import { createStartupCurtain } from "../../web/js/shared/components/startup-curtain.js";
import { createQueueSync } from "../../web/js/features/downloads/sync.js";
import { queueWaitCopy } from "../../web/js/features/downloads/wait-state.js";
import { createDiscoveryPolicy } from "../../web/js/features/home/discovery-policy.js";
import { createDailyTop } from "../../web/js/features/home/daily-top.js";
import { createCardArtwork } from "../../web/js/shared/components/card-artwork.js";
import { createResultCards } from "../../web/js/shared/components/result-card.js";
import { createTrailers } from "../../web/js/features/trailers/index.js";
import { createCatalogJellyfin } from "../../web/js/features/integrations/catalog-jellyfin.js";
import { createInfiniteScroll } from "../../web/js/shared/components/infinite-scroll.js";
import { createSettings } from "../../web/js/features/settings/index.js";
import { createIntelligenceSettings } from "../../web/js/features/settings/intelligence.js";
import { createIntegrationSettings } from "../../web/js/features/integrations/settings.js";
import { integrationHealth } from "../../web/js/features/integrations/health.js";
import { createUpdater } from "../../web/js/features/settings/updater.js";
import { createSearch } from "../../web/js/features/search/index.js";
import { createRecommendations } from "../../web/js/features/home/recommendations.js";
import { createHomeData } from "../../web/js/features/home/data.js";
import { createHomeLanes } from "../../web/js/features/home/lanes.js";
import { createSubscriptions } from "../../web/js/features/subscriptions/state.js";
import { libraryVisibleItems } from "../../web/js/features/subscriptions/model.js";
import { movieSubscriptionFor } from "../../web/js/features/subscriptions/movie-model.js";
import { createCalendarState } from "../../web/js/features/calendar/state.js";
import { createCalendarStorage } from "../../web/js/features/calendar/storage.js";
import { calendarNormalizeSnapshotPayload } from "../../web/js/features/calendar/model.js";
import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi } from "../../web/js/core/api.js";
import { createScope, delay } from "../../web/js/core/lifecycle.js";
import { createStore } from "../../web/js/core/store.js";
import { createNavigation } from "../../web/js/core/navigation.js";
import { createWebSocketManager } from "../../web/js/core/websocket.js";
import { createLiveUpdates } from "../../web/js/features/downloads/index.js";
import { createDownloadEvents } from "../../web/js/features/downloads/events.js";
import { createServerBuildMonitor } from "../../web/js/features/system/server-build.js";
import { createHeroSelection } from "../../web/js/features/home/hero-selection.js";
import { createTasteRanking } from "../../web/js/features/home/taste-ranking.js";

const json = (data, status = 200) => new Response(JSON.stringify(data), { status });

test("queue wait copy explains source retries and long-term checks", () => {
  const now = 1_000;
  assert.equal(
    queueWaitCopy({
      job_status: "waiting_provider",
      wait_reason: "source_unavailable",
      next_retry_at: now + 27 * 60,
    }, now),
    "Wartet auf Quelle · Nächster Versuch in ~27 Min.",
  );
  assert.equal(
    queueWaitCopy({
      job_status: "waiting_provider",
      wait_reason: "source_unavailable",
      next_retry_at: now + 24 * 60 * 60,
      error: "Noch keine nutzbare Quelle verfügbar · Langzeitprüfung aktiv",
    }, now),
    "Wartet auf Quelle · Langzeitprüfung in ~1 Tag",
  );
  assert.equal(
    queueWaitCopy({
      job_status: "waiting_provider",
      next_probe_at: now + 60,
    }, now),
    "Provider vorübergehend pausiert · Nächster Test in ~1 Min.",
  );
  assert.equal(queueWaitCopy({ job_status: "queued" }, now), "");
});

for (const kind of ["movie", "series"]) test(`${kind} result cards call injected artwork candidates and create lazy posters`, t => {
  class Element extends EventTarget {
    constructor(tag) {
      super(); this.tagName = tag; this.dataset = {}; this.children = [];
      const classes = new Set();
      this.classList = { add: name => classes.add(name), contains: name => classes.has(name) };
    }
    querySelector() { return null; }
    querySelectorAll() { return []; }
    append(...nodes) { this.children.push(...nodes); }
    appendChild(node) { this.append(node); }
    setAttribute() {}
    remove() {}
  }
  const calls = [], scheduled = [];
  const candidates = ["/poster.jpg", "/fallback.jpg"];
  const cards = createResultCards({ createElement: tag => new Element(tag) }, {
    coverCandidates: url => { calls.push(url); return candidates; },
    mediaCardInitials: () => "RT", scheduleResultPoster: (image, urls) => scheduled.push({ image, urls }),
    discardPoster() {}, setFpPosterJellyfinBadge: badge => { badge.textContent = "In Jellyfin"; },
    markLanguage: mark => { mark.dataset.language = "de"; },
  });
  t.after(() => cards.dispose());
  cards.mount(kind, new Element("section"));
  const visual = cards.create({ cover_url: "/poster.jpg" }, "Regression title", kind, "owned");
  assert.deepEqual(calls, ["/poster.jpg"]);
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].urls, candidates);
  const image = visual.children.find(child => child.tagName === "img");
  assert.equal(image, scheduled[0].image);
  assert.equal(image.dataset.posterKey, candidates.join("\n"));
  assert.equal(image.loading, "lazy");
  assert.equal(image.decoding, "async");
  assert.equal(visual.children.at(-1).textContent, "In Jellyfin");
});

test("explore publishes only ready backdrops but keeps unresolved candidates hydratable", () => {
  const data = {
    topMovies: [], newMovies: [], cinemaMovies: [], discoveryMovies: [],
    trendingSeries: [], newSeries: [],
    discoverySeries: [
      { base_slug: "ready", title: "Ready", backdrop_url: "/ready.jpg", genres: [] },
      { base_slug: "pending-a", title: "Pending A", cover_url: "/poster-a.jpg", genres: [] },
      { base_slug: "pending-b", title: "Pending B", cover_url: "/poster-b.jpg", genres: [] },
    ],
  };
  const entryKey = entry => `${entry.kind}:${entry.item.slug || entry.item.base_slug}`;
  const unique = entries => {
    const seen = new Set();
    return entries.filter(entry => {
      const key = entryKey(entry);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };
  const lanes = createHomeLanes({ querySelector: () => null }, {
    allowedHomeEntries: entries => entries,
    uniqueHomeEntries: unique,
    homeMovieEntry: item => ({ kind: "movie", item }),
    homeSeriesEntry: item => ({ kind: "series", item }),
    interleaveHomeEntries: (a, b) => unique([...a, ...b]),
    loadDiscoveryProfile: () => ({ genres: {}, recent: [] }),
    stableDailyOrder: entries => entries.slice(),
    homeEntryMedia: entry => entry.item,
    homeEntryKey: entryKey,
    homeTopEntries: () => [],
    stableDiscoveryHash: () => 1,
    localDateKey: () => "2026-10-01",
    homeHeroCandidates: () => [],
    homePersonalizedEntries: () => [],
    currentHomeLayout: () => ({ rail_order: ["explore"], hidden_rails: [] }),
    mediaJellyfinStatus: () => "missing",
    getJellyfinStatus: () => "",
    getData: () => data,
    discoveryV2ExposurePenalty: () => 0,
  });

  assert.deepEqual(lanes.homeExploreEntries().map(entryKey), ["series:ready"]);
  assert.deepEqual(
    lanes.homeExploreArtworkCandidates().map(entryKey),
    ["series:ready", "series:pending-a", "series:pending-b"],
  );
  assert.deepEqual(
    lanes.homeArtworkEntriesInLayout().map(entryKey),
    ["series:ready", "series:pending-a", "series:pending-b"],
  );
});

test("HTTP sends JSON, cookies and all supported verbs", async () => {
  const calls = [];
  const api = createApi({ fetchImpl: async (url, options) => { calls.push([url, options]); return json({ saved: true }); } });
  for (const method of ["post", "put", "patch"]) assert.deepEqual(await api[method]("/api/test", { value: 2 }), { saved: true });
  await api.delete("/api/test");
  assert.deepEqual(calls.map(([, options]) => options.method), ["POST", "PUT", "PATCH", "DELETE"]);
  assert.equal(calls[0][1].body, '{"value":2}');
  assert.equal(calls[0][1].credentials, "same-origin");
  assert.equal(calls[0][1].headers.get("Content-Type"), "application/json");
});

test("GET deduplicates simultaneous equivalent requests but retains no server cache", async () => {
  let finish, count = 0;
  const api = createApi({ fetchImpl: () => { count++; return new Promise(resolve => { finish = resolve; }); } });
  const a = api.get("/api/a", { timeoutMs: 200 });
  const b = api.get("/api/a", { timeoutMs: 200 });
  assert.equal(a, b);
  finish(json({ items: [1] }));
  await a;
  const c = api.get("/api/a", { timeoutMs: 200 });
  finish(json({ items: [2] }));
  assert.deepEqual(await c, { items: [2] });
  assert.equal(count, 2);
});

test("401 triggers session expiry, login failures preserve the form", async () => {
  const api = createApi({ fetchImpl: async () => json({ detail: { code: "expired", message: "Login", resource: "account" } }, 401) });
  let expired = 0;
  api.onUnauthorized = () => expired++;
  await assert.rejects(api.get("/api/queue"), error => error.status === 401 && error.code === "expired" && error.resource === "account");
  await assert.rejects(api.post("/api/auth/login", {}));
  assert.equal(expired, 1);
});

test("empty bodies, malformed JSON, non-JSON errors and network errors stay distinct", async () => {
  assert.equal(await createApi({ fetchImpl: async () => new Response(null, { status: 204 }) }).delete("/x"), null);
  await assert.rejects(createApi({ fetchImpl: async () => new Response("broken") }).get("/x"), { code: "invalid_json" });
  await assert.rejects(createApi({ fetchImpl: async () => new Response("down", { status: 503 }) }).get("/x"), { status: 503 });
  await assert.rejects(createApi({ fetchImpl: async () => { throw new TypeError("offline"); } }).get("/x"), { code: "network_error" });
});

const pendingFetch = (_url, { signal }) => new Promise((_resolve, reject) => {
  if (signal.aborted) reject(signal.reason);
  else signal.addEventListener("abort", () => reject(signal.reason), { once: true });
});

test("timeout aborts network I/O and reports request_timeout", async () => {
  await assert.rejects(createApi({ fetchImpl: pendingFetch, timeoutMs: 5 }).get("/slow"), { code: "request_timeout" });
});

test("a view abort does not cancel another consumer of the same endpoint", async () => {
  const first = new AbortController(), second = new AbortController();
  const api = createApi({ fetchImpl: pendingFetch });
  const a = api.get("/same", { signal: first.signal });
  const b = api.get("/same", { signal: second.signal });
  first.abort();
  await assert.rejects(a, { name: "AbortError" });
  assert.equal(second.signal.aborted, false);
  second.abort();
  await assert.rejects(b, { name: "AbortError" });
});

test("already aborted calls and delays reject immediately", async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(createApi({ fetchImpl: pendingFetch }).get("/a", { signal: controller.signal }), { name: "AbortError" });
  await assert.rejects(delay(1000, controller.signal), { name: "AbortError" });
});

test("unmount clears timers, listeners, observers and subscriptions once", t => {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const scope = createScope(), target = new EventTarget();
  let count = 0, cleanups = 0;
  scope.listen(target, "change", () => count++);
  scope.interval(() => count++, 10);
  scope.timeout(() => count++, 20);
  scope.observe({ disconnect: () => cleanups++ });
  scope.add(() => cleanups++);
  target.dispatchEvent(new Event("change"));
  scope.dispose(); scope.dispose();
  target.dispatchEvent(new Event("change"));
  t.mock.timers.tick(100);
  assert.equal(scope.signal.aborted, true);
  assert.equal(count, 1);
  assert.equal(cleanups, 2);
  scope.add(() => cleanups++);
  assert.equal(cleanups, 3);
});

test("navigation unmounts before mounting and repeated activation is idempotent", () => {
  const nav = createNavigation(), events = [];
  for (const name of ["a", "b"]) nav.register(name, {
    mount: () => events.push(`mount ${name}`), unmount: () => events.push(`unmount ${name}`), refresh: () => events.push(`refresh ${name}`),
  }, {});
  nav.activate("a"); nav.activate("a"); nav.activate("b"); nav.refresh(); nav.dispose(); nav.dispose();
  assert.deepEqual(events, ["mount a", "unmount a", "mount b", "refresh b", "unmount b"]);
});

test("store notifies only changes and unsubscribe removes consumers", () => {
  const store = createStore({ language: "de" }); let calls = 0;
  const off = store.subscribe(() => calls++);
  store.set({ language: "de" }); store.set({ language: "en" }); off(); store.set({ language: "de" });
  assert.equal(calls, 1);
  assert.equal(Object.isFrozen(store.get()), true);
});

function socketHarness() {
  const connections = [], statuses = [];
  const manager = createWebSocketManager({ url: () => "ws://test/ws", random: () => 0.5,
    status: status => statuses.push(status), createSocket: () => {
      const socket = { close() { socket.onclose?.({ code: 1000 }); } };
      connections.push(socket); return socket;
    },
  });
  return { manager, connections, statuses };
}

test("one socket, parsed topics, unsubscribe, stale socket messages ignored", () => {
  const { manager, connections } = socketHarness(); let received = 0;
  const off = manager.subscribe("progress", () => received++);
  manager.connect(); manager.connect();
  assert.equal(connections.length, 1);
  connections[0].onmessage({ data: "{" });
  connections[0].onmessage({ data: JSON.stringify({ type: "progress" }) });
  off(); connections[0].onmessage({ data: JSON.stringify({ type: "progress" }) });
  manager.disconnect(); manager.connect();
  manager.subscribe("progress", () => received++);
  connections[0].onmessage({ data: JSON.stringify({ type: "progress" }) });
  assert.equal(received, 1);
  manager.disconnect();
});

test("reconnect backs off; snapshot predicates expire on disconnect; auth errors stop retry", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { manager, connections, statuses } = socketHarness();
  let snapshot, expired = 0;
  manager.subscribe("connection.open", event => { snapshot = event; });
  manager.subscribe("session.expired", () => expired++);
  manager.connect(); connections[0].onopen();
  assert.equal(snapshot.isCurrent(), true);
  connections[0].close(); assert.equal(snapshot.isCurrent(), false);
  t.mock.timers.tick(1999); assert.equal(connections.length, 1);
  t.mock.timers.tick(1); assert.equal(connections.length, 2);
  connections[1].close(); t.mock.timers.tick(3999); assert.equal(connections.length, 2);
  t.mock.timers.tick(1); assert.equal(connections.length, 3);
  connections[2].onclose({ code: 1008 }); t.mock.timers.tick(60_000);
  assert.equal(connections.length, 3);
  assert.equal(expired, 1);
  assert.equal(statuses.at(-1), "auth_failed");
});

test("disconnect during reconnect cancels pending retries", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { manager, connections } = socketHarness();
  manager.connect(); connections[0].close(); manager.disconnect(); t.mock.timers.tick(60_000);
  assert.equal(connections.length, 1);
});

test("live feature supports repeated mount/unmount without duplicate subscriptions", () => {
  const { manager, connections } = socketHarness(); let received = 0;
  const feature = createLiveUpdates({ socket: manager, onMessage: () => received++, onOpen() {}, onUnauthorized() {} });
  feature.mount(); feature.mount();
  connections[0].onmessage({ data: '{"type":"queue_update"}' });
  feature.unmount(); feature.mount();
  connections[1].onmessage({ data: '{"type":"queue_update"}' });
  assert.equal(received, 2); feature.unmount();
});

test("download progress combines job and batch progress, failed completion stays visible", () => {
  const state = { download: { total: 4, completed: 1, percent: 25 } };
  const presentations = [], updates = [], marked = [];
  let refreshed = 0, cancelDisabled = false;
  const receive = createDownloadEvents({ state,
    setDownloadState: (...args) => presentations.push(args),
    updateQueueJobProgress: (...args) => updates.push(args),
    applyFpDownloadJobResult() {}, syncQueueSnapshot: () => refreshed++,
    markSeriesSlugDownloaded: slug => marked.push(slug), markAnimeSlugDownloaded() {}, markAniworldSlugDownloaded() {},
    renderQueue() {}, renderSerienstreamHealth() {}, disableCancel: () => { cancelDisabled = true; },
  });
  receive({ type: "progress", pct: 50, job_id: "job", label: "Film" });
  assert.equal(presentations.at(-1)[3], 37.5);
  assert.equal(updates.at(-1)[0], "job");
  receive({ type: "job_done", ok: true, done_jobs: 2, total_jobs: 4, active: 1, pending: 1, slug: "movie" });
  assert.deepEqual(marked, ["movie"]);
  receive({ type: "queue_done", done_jobs: 4, total_jobs: 4, failed_jobs: 1, successful_jobs: 3 });
  assert.equal(cancelDisabled, true);
  assert.equal(presentations.at(-1)[0], "error");
  assert.equal(presentations.at(-1)[1], "Mit Fehlern beendet");
  assert.equal(refreshed, 2);
});

test("GET requests in the same lifecycle scope deduplicate", async () => {
  const controller = new AbortController(); let count = 0;
  const api = createApi({ fetchImpl: async () => { count++; return json({}); } });
  const a = api.get("/queue", { signal: controller.signal });
  const b = api.get("/queue", { signal: controller.signal });
  assert.equal(a, b); await a; assert.equal(count, 1);
});

test("repeated unsubscribe cannot remove a newer subscription", () => {
  const { manager, connections } = socketHarness(); let count = 0;
  const off = manager.subscribe("test", () => {}); off();
  manager.subscribe("test", () => count++); off(); manager.connect();
  connections[0].onmessage({ data: '{"type":"test"}' });
  assert.equal(count, 1); manager.disconnect();
});

test("build monitor tolerates restart outages and reloads only for a different build", async () => {
  const document = new EventTarget(); document.hidden = false;
  let build = "before", reloads = 0, offline = false;
  const monitor = createServerBuildMonitor({ document, location: { reload: () => reloads++ },
    client: { get: async () => { if (offline) throw new Error("restarting"); return { build }; } },
  });
  monitor.mount(); await monitor.refresh();
  assert.equal(reloads, 0);
  offline = true; await monitor.refresh(); assert.equal(reloads, 0);
  offline = false; build = "after"; await monitor.refresh(); assert.equal(reloads, 1);
  monitor.unmount();
});

test("native hero selection keeps provider identity, artwork and blocked-title policy", () => {
  const items = Array.from({ length: 12 }, (_, id) => ({ kind: id % 2 ? "movie" : "series", item: {
    slug: String(id), title: `Title ${id}`, backdrop_url: `backdrop-${id}`, rating: 8, genres: ["Drama"],
  } }));
  items[1].item.in_cinema = true;
  items[1].item.vote_count = 500;
  const key = entry => `${entry.kind}:${entry.item.slug}`;
  const hero = createHeroSelection({
    homeAllEntries: () => items, homeEntryMedia: entry => entry.item, homeEntryKey: key, discoveryV2LogicalKey: key,
    tasteMetadata: (_kind, media) => media, discoveryV2ExposurePenalty: () => 0,
    getHomeData: () => ({ topMovies: [], trendingSeries: [] }), homeMovieEntry: item => ({ kind: "movie", item }),
    homeSeriesEntry: item => ({ kind: "series", item }), mediaJellyfinStatus: () => "missing",
    loadDiscoveryProfile: () => ({ blocked_items: ["series:0"], interactions: 0 }),
  });
  const result = hero.candidates();
  assert.equal(key(result[0]), "movie:1");
  assert.equal(result.length, 7); assert.equal(new Set(result.map(key)).size, 7);
  assert.ok(result.every(entry => key(entry) !== "series:0" && entry.artwork === entry.item.backdrop_url));
  assert.deepEqual(hero.candidates(), result);
});


test("trained hero reserves four slots for current cinema hits ahead of older favorites", () => {
  const items = Array.from({ length: 18 }, (_, id) => ({ kind: id < 12 ? "movie" : "series", item: {
    slug: String(id), title: `Title ${id}`, genres: [id < 4 ? "Thriller" : "Action"],
    backdrop_url: `art-${id}`, rating: 8, vote_count: 500, in_cinema: id < 4,
  } }));
  const key = entry => `${entry.kind}:${entry.item.slug}`;
  const hero = createHeroSelection({ homeAllEntries: () => items,
    homeEntryMedia: entry => entry.item, homeEntryKey: key, discoveryV2LogicalKey: key,
    tasteMetadata: (_kind, media) => media, discoveryV2ExposurePenalty: () => 0,
    getHomeData: () => ({ topMovies: [], trendingSeries: [] }),
    homeMovieEntry: item => ({ kind: "movie", item }), homeSeriesEntry: item => ({ kind: "series", item }),
    loadDiscoveryProfile: () => ({ interactions: 1752, confidence: 0.95,
      dimensions: { genres: { Action: 500, Thriller: 50 } }, genres: { Action: 500, Thriller: 50 } }),
  });
  const result = hero.candidates();
  assert.equal(result.length, 7);
  assert.ok(result.slice(0, 4).every(entry => entry.item.in_cinema));
});

test("personal discovery rotates cold and trained profiles and updates hydrated metadata", () => {
  const items = Array.from({ length: 40 }, (_, id) => ({ kind: "movie", item: {
    slug: String(id), title: `Fresh ${id}`, rating: 8, genres: ["Action"],
  } }));
  let day = 0;
  let previous = new Set();
  const profile = { interactions: 0, confidence: 0, dimensions: {} };
  const ranking = createTasteRanking(null, null, {
    homeEntryMedia: entry => entry.item, homeEntryKey: entry => entry.item.slug,
    tasteMetadata: (_kind, media) => media, loadDiscoveryProfile: () => profile,
    homeAllEntries: () => items, getShuffle: () => 0,
    discoveryV2ExposurePenalty: entry => previous.has(entry.item.slug) ? 16 : 0,
    discoveryV2Noise: entry => ((Number(entry.item.slug) * 17 + day * 23) % 41) / 41 * 6,
  });
  const selection = () => ranking.entries().slice(0, 7).map(entry => entry.item.slug);
  const cold = selection();
  assert.deepEqual(selection(), cold, "stable during the same visit");
  day++;
  assert.notDeepEqual(selection(), cold, "neutral accounts receive daily discoveries");
  Object.assign(profile, { interactions: 1752, confidence: 0.95, dimensions: { genres: { Action: 500 } } });
  const trained = selection();
  previous = new Set(trained);
  day++;
  assert.ok(selection().every(key => !previous.has(key)), "old affinity must not defeat exposure rotation");
  const hydrated = items.find(entry => entry.item.slug === selection()[0]);
  hydrated.item.genres = ["Horror"];
  assert.ok(!selection().includes(hydrated.item.slug), "hydrated metadata invalidates the old taste score");
});

function subscriptionSocket() {
  const topics = new Map();
  return {
    subscribe(topic, listener) {
      if (!topics.has(topic)) topics.set(topic, new Set());
      topics.get(topic).add(listener);
      return () => topics.get(topic).delete(listener);
    },
    emit(topic, data) { for (const listener of topics.get(topic) || []) listener(data); },
    count(topic) { return topics.get(topic)?.size || 0; },
  };
}

test("subscription consumers share one pending snapshot and live updates supersede it", async () => {
  let resolve;
  let requests = 0;
  const socket = subscriptionSocket();
  const model = createSubscriptions({ socket, client: { get() { requests++; return new Promise(done => { resolve = done; }); } } });
  model.mount(); model.mount();
  const first = model.refresh(), second = model.refresh();
  assert.equal(first, second);
  assert.equal(requests, 1);
  socket.emit("watchlist_update", { watchlist: [{ base_slug: "live" }], health: {} });
  resolve({ watchlist: [{ base_slug: "old" }] });
  assert.equal(await first, false);
  assert.equal(model.get().items[0].base_slug, "live");
  assert.equal(socket.count("watchlist_update"), 1);
  model.unmount();
  assert.equal(socket.count("watchlist_update"), 0);
});

test("subscription checks share a mutex and release it when their owner aborts", async () => {
  let requests = 0;
  const model = createSubscriptions({ socket: subscriptionSocket(), client: {
    post(url, body, { signal }) {
      requests++;
      return new Promise((resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }));
    },
  } });
  model.mount();
  const controller = new AbortController();
  const first = model.check(["one"], { signal: controller.signal });
  assert.equal(model.check(["two"]), first);
  assert.equal(model.get().checkRunning, true);
  controller.abort();
  await assert.rejects(first, { name: "AbortError" });
  assert.equal(model.get().checkRunning, false);
  assert.equal(requests, 1);
  model.unmount();
});

test("reconnect replaces the pending subscription request and disposal ignores late results", async () => {
  const calls = [];
  const socket = subscriptionSocket();
  const model = createSubscriptions({ socket, client: {
    get(url, { signal }) { return new Promise(resolve => calls.push({ signal, resolve })); },
  } });
  model.mount();
  socket.emit("connection.open");
  socket.emit("connection.open");
  assert.equal(calls.length, 2);
  assert.equal(calls[0].signal.aborted, true);
  model.unmount();
  assert.equal(calls[1].signal.aborted, true);
  calls.forEach(call => call.resolve({ watchlist: [{ base_slug: "late" }] }));
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(model.get().items, []);
});

test("subscription read errors retain the last snapshot and recovery clears the error", async () => {
  let fail = false;
  const model = createSubscriptions({ socket: subscriptionSocket(), client: {
    async get() { if (fail) throw new Error("offline"); return { watchlist: [{ base_slug: "saved" }], health: {} }; },
  } });
  model.mount();
  await model.refresh();
  fail = true;
  await model.refresh();
  assert.equal(model.get().status, "error");
  assert.equal(model.get().error, "offline");
  assert.equal(model.get().items[0].base_slug, "saved");
  fail = false;
  await model.refresh();
  assert.equal(model.get().status, "ready");
  assert.equal(model.get().error, "");
  model.unmount();
});

test("live subscription updates win against delayed check responses", async () => {
  let resolve;
  const socket = subscriptionSocket();
  const model = createSubscriptions({ socket, client: { post: () => new Promise(done => { resolve = done; }) } });
  model.mount();
  const pending = model.check();
  socket.emit("watchlist_update", { watchlist: [{ base_slug: "new" }], health: {} });
  resolve({ watchlist: [{ base_slug: "old" }], checked: 1 });
  assert.equal((await pending).checked, 1);
  assert.equal(model.get().items[0].base_slug, "new");
  assert.equal(model.get().checkRunning, false);
  model.unmount();
});

test("library filtering and sorting preserve the shared server order", () => {
  const items = [
    { base_slug: "z", title: "Zulu", status: "current", queued_count: 1 },
    { base_slug: "a", title: "Alpha", status: "blocked" },
    { base_slug: "b", title: "Bravo", new_count: 2 },
  ];
  const ids = ui => libraryVisibleItems(items, { query: "", filter: "all", sort: "attention", ...ui }).map(item => item.base_slug);
  assert.deepEqual(ids({}), ["b", "a", "z"]);
  assert.deepEqual(ids({ filter: "queued" }), ["z"]);
  assert.deepEqual(ids({ filter: "attention", query: " ALP " }), ["a"]);
  assert.deepEqual(ids({ sort: "title" }), ["a", "b", "z"]);
  assert.deepEqual(items.map(item => item.base_slug), ["z", "a", "b"]);
});

test("movie subscriptions retain their own endpoint, key payload and live topic", async () => {
  const socket = subscriptionSocket();
  const calls = [];
  const model = createSubscriptions({ kind: "movies", socket, client: {
    async get(path) { calls.push(path); return { movie_subscriptions: [{ key: "initial" }] }; },
    async post(path, body) { calls.push([path, body]); return { movie_subscriptions: [{ key: "checked" }] }; },
  } });
  model.mount();
  await model.refresh();
  assert.equal(model.get().items[0].key, "initial");
  await model.check(["initial"]);
  assert.deepEqual(calls, ["/api/movie-subscriptions", ["/api/movie-subscriptions/check", { keys: ["initial"] }]]);
  socket.emit("watchlist_update", { watchlist: [{ base_slug: "unrelated" }] });
  assert.equal(model.get().items[0].key, "checked");
  socket.emit("movie_subscriptions_update", { movie_subscriptions: [{ key: "live" }] });
  assert.equal(model.get().items[0].key, "live");
  model.unmount();
  assert.equal(socket.count("movie_subscriptions_update"), 0);
});

test("movie subscription lookup prefers stable identity over source slug", () => {
  const items = [{ key: "tmdb:1", tmdb_id: 1, source_slug: "old-source" }];
  assert.equal(movieSubscriptionFor(items, "new-source", { tmdb_id: 1 }), items[0]);
  assert.equal(movieSubscriptionFor(items, "old-source", { tmdb_id: 2 }), null);
  assert.equal(movieSubscriptionFor(items, "old-source", {}), items[0]);
});

const calendarPayload = { ready: true, days: [{ date: "2026-09-26", entries: [
  { title: "Saved", base_slug: "serienstream:saved", season: 1, episode: 2, language_id: 1 },
] }] };

test("calendar snapshot cache validates dates and images and isolates user filters", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const cache = createCalendarStorage(storage);
  const payload = calendarNormalizeSnapshotPayload(calendarPayload);
  cache.storeSnapshot(payload);
  assert.equal(cache.restoreSnapshot().payload.days[0].entries[0].sample_slug, "serienstream:saved-s01e02");
  cache.storeFilters("one", { language: "2", status: "upcoming", view: "week", query: "Saved", subscribedOnly: true });
  assert.equal(cache.restoreFilters("one").query, "Saved");
  assert.deepEqual(cache.restoreFilters("two"), {});
  const unsafe = structuredClone(calendarPayload);
  unsafe.days[0].entries[0].cover_url = "javascript:alert(1)";
  assert.equal(calendarNormalizeSnapshotPayload(unsafe).days[0].entries[0].cover_url, "");
  unsafe.days[0].date = "2026-02-31";
  assert.throws(() => calendarNormalizeSnapshotPayload(unsafe), /keine gültigen Tage/);
  storage.setItem("royal.series-calendar.v2", JSON.stringify({ saved_at: 1, payload }));
  assert.equal(cache.restoreSnapshot(), null);
  storage.setItem("royal.series-calendar.v2", "invalid json");
  assert.equal(cache.restoreSnapshot(), null);
  assert.equal(values.has("royal.series-calendar.v2"), false);
  const blocked = createCalendarStorage({ getItem() { throw new Error("blocked"); } });
  assert.equal(blocked.restoreSnapshot(), null);
  assert.deepEqual(blocked.restoreFilters("one"), {});
});

test("calendar deduplicates pending reads and aborts late responses after navigation", async () => {
  let resolve, signal, writes = 0;
  const model = createCalendarState({
    cache: { restoreSnapshot: () => null, storeSnapshot() { writes++; } },
    client: { get(_path, options) { signal = options.signal; return new Promise(done => { resolve = done; }); } },
  });
  const first = model.refresh();
  assert.equal(model.refresh(true), first);
  model.unmount();
  assert.equal(signal.aborted, true);
  assert.equal(await first, false);
  resolve(calendarPayload);
  await Promise.resolve();
  assert.equal(model.get().loaded, false);
  assert.equal(model.get().loading, false);
  assert.equal(writes, 0);
});

test("calendar keeps a valid cached snapshot on refresh failure and accepts an empty ready day", async () => {
  let fail = true;
  const model = createCalendarState({
    cache: { restoreSnapshot: () => ({ payload: calendarNormalizeSnapshotPayload(calendarPayload), savedAt: 123 }), storeSnapshot() {} },
    client: { async get() { if (fail) throw new Error("offline"); return { ready: true, days: [{ date: "2026-09-26", entries: [] }] }; } },
  });
  assert.equal(model.restore(), true);
  await model.refresh(true);
  assert.equal(model.get().phase, "ready");
  assert.equal(model.get().stale, true);
  assert.equal(model.get().total, 1);
  assert.equal(model.get().error, "offline");
  fail = false;
  await model.refresh(true);
  assert.equal(model.get().loaded, true);
  assert.equal(model.get().total, 0);
  assert.equal(model.get().error, "");
  model.unmount();
});


function homeDataFixture(overrides = {}) {
  const calls = [];
  const writes = [];
  let rendered = false;
  let model;
  const movie = item => ({ kind: "movie", item });
  const series = item => ({ kind: "series", item });
  const entries = () => [...model.get().newMovies.map(movie), ...model.get().trendingSeries.map(series)];
  model = createHomeData({
    storage: { getItem: () => null, setItem: (...args) => writes.push(args) },
    getMovieMetadata: () => ({}), isRendered: () => rendered,
    homeAllEntries: entries, homeArtworkEntriesInLayout: entries,
    renderHome: () => { calls.push("render"); rendered = !model.get().loading; },
    syncFpCatalogFromHome: () => {}, syncSeriesCatalogFromHome: () => {},
    hydrateHomeMovieArtwork: async () => {}, hydrateHomeSeriesArtwork: async () => {},
    refreshCatalogJellyfinStatus: async () => {},
    discoveryV2MergeItems: (a, b) => [...a, ...b], homeMovieEntry: movie, homeSeriesEntry: series,
    client: { get: async (url, { signal }) => {
      calls.push(url);
      assert.equal(signal.aborted, false);
      return { results: url.startsWith("/api/movies") ? [{ slug: url }] : [{ base_slug: url }] };
    } }, ...overrides,
  });
  return { model, calls, writes };
}

test("home data deduplicates loading and preserves every primary and reservoir source", async () => {
  const { model, calls, writes } = homeDataFixture();
  try {
    const load = model.load();
    assert.equal(model.load(), load);
    const warm = model.warm();
    assert.equal(model.warm(), warm);
    await load;
    assert.equal(model.get().loading, false);
    await warm;
    const urls = calls.filter(value => value.startsWith("/api/"));
    assert.equal(urls.length, 18);
    assert.equal(new Set(urls).size, 18);
    assert.ok(urls.includes("/api/tmdb/now-playing"));
    for (const url of ["/api/movies?mode=new&page=1", "/api/series?mode=trending&page=1",
      `/api/movies?mode=top&page=${4 + Math.floor(Date.now() / 86400000) % 5}`,
      "/api/series?mode=new&page=3"]) assert.ok(urls.includes(url));
    assert.equal(calls.filter(value => value === "render").length, 3, "hydrated discoveries appear in the current visit");
    assert.equal(model.get().discoveryMovies.length, 6);
    assert.equal(model.get().discoverySeries.length, 7);
    assert.ok(writes.length >= 2);
  } finally { model.unmount(); }
});

test("home adds current cinema discoveries after the first catalog render", async () => {
  const { model, calls } = homeDataFixture({ client: { get: async (url) => {
    if (url === "/api/tmdb/now-playing") return { available: true, ids: [42], movies: [
      { slug: "tmdb:42", tmdb_id: 42, title: "Cinema hit", backdrop_url: "cinema.jpg", rating: 8, vote_count: 500 },
    ] };
    return { results: url.startsWith("/api/movies")
      ? [{ slug: url, title: "Catalog movie" }] : [{ base_slug: url, title: "Catalog series" }] };
  } } });
  try {
    await model.load();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(model.get().cinemaMovies[0].slug, "tmdb:42");
    assert.ok(calls.filter((call) => call === "render").length >= 2);
  } finally { model.unmount(); }
});

test("cinema feed enriches a known provider title instead of silently discarding the hit", async () => {
  const metadata = {};
  const { model } = homeDataFixture({ getMovieMetadata: () => metadata, client: { get: async url => {
    if (url === "/api/tmdb/now-playing") return { available: true, ids: [42], movies: [
      { slug: "tmdb:42", tmdb_id: 42, title: "Cinema hit", year: "2026", release_date: "2026-09-25",
        backdrop_url: "cinema.jpg", rating: 8, vote_count: 500, popularity: 350 },
    ] };
    return { results: url.startsWith("/api/movies")
      ? [{ slug: "provider-hit", title: "Cinema hit", year: "2026" }] : [] };
  } } });
  try {
    await model.load();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(model.get().newMovies[0].slug, "provider-hit");
    assert.equal(model.get().cinemaMovies.length, 0, "no duplicate TMDB-only card");
    assert.equal(metadata["provider-hit"].in_cinema, true);
    assert.equal(metadata["provider-hit"].backdrop_url, "cinema.jpg");
    assert.equal(metadata["provider-hit"].popularity, 350);
  } finally { model.unmount(); }
});

test("home cancellation rejects stale generations and resumes an interrupted load on mount", async () => {
  const requests = [];
  const { model, writes } = homeDataFixture({ client: { get: (url, { signal }) =>
    new Promise(resolve => requests.push({ url, signal, resolve })) } });
  const first = model.load();
  assert.equal(requests.length, 2);
  model.unmount();
  assert.ok(requests.every(request => request.signal.aborted));
  model.mount();
  const second = model.load();
  assert.equal(requests.length, 4);
  for (const request of requests.slice(0, 2)) request.resolve({ results: [{ slug: "old" }] });
  await first;
  assert.equal(model.get().loading, true);
  assert.deepEqual(model.get().newMovies, []);
  assert.equal(writes.length, 0);
  model.unmount();
  for (const request of requests.slice(2)) request.resolve({ results: [{ slug: "late" }] });
  await second;
  assert.deepEqual(model.get().newMovies, []);
  assert.equal(writes.length, 0);
});

test("home cache survives provider failures without repainting or dropping cached catalog", async () => {
  const persisted = JSON.stringify({ savedAt: Date.now(), home: {
    newMovies: [{ slug: "cached" }], trendingSeries: [{ base_slug: "cached-series" }],
  }, movieMetadata: { cached: { title: "Cached movie" } } });
  const metadata = {};
  const { model, calls } = homeDataFixture({
    storage: { getItem: () => persisted, setItem: () => {} }, getMovieMetadata: () => metadata,
    client: { get: async () => { throw new Error("offline"); } },
  });
  try {
    assert.equal(model.restore(), true);
    await model.load();
    assert.equal(metadata.cached.title, "Cached movie");
    assert.equal(model.get().newMovies[0].slug, "cached");
    assert.equal(model.get().newSeries[0].base_slug, "cached-series");
    assert.equal(model.get().refreshing, false);
    assert.equal(calls.filter(value => value === "render").length, 1);
  } finally { model.unmount(); }
  for (const value of ["invalid", JSON.stringify({ savedAt: 1, home: { newMovies: [{}] } })]) {
    const { model } = homeDataFixture({ storage: { getItem: () => value } });
    assert.equal(model.restore(), false);
    model.unmount();
  }
  const { model: blocked } = homeDataFixture({ storage: {
    getItem() { throw new Error("blocked"); }, setItem() { throw new Error("full"); },
  } });
  assert.equal(blocked.restore(), false);
  assert.doesNotThrow(() => blocked.save());
  blocked.unmount();
});


function recommendationFixture(client) {
  const nodes = new Map();
  const root = Object.assign(new EventTarget(), {
    hidden: true, dataset: {}, querySelectorAll: () => [],
    querySelector(id) {
      if (!nodes.has(id)) nodes.set(id, Object.assign(new EventTarget(), {
        hidden: false, dataset: {}, textContent: "", replaceChildren() {},
      }));
      return nodes.get(id);
    }, ownerDocument: { createElement: () => ({ setAttribute() {} }) },
  });
  let renders = 0;
  const config = { enabled: true, moduleAvailable: true };
  const view = createRecommendations(root, {
    client, getConfig: () => config,
    homeAllEntries: () => [{ kind: "movie", item: { slug: "fixture", title: "Fixture", genres: [] } }],
    homeEntryKey: entry => entry.item.slug, homeEntryMedia: entry => entry.item,
    mediaJellyfinStatus: () => "missing", createHomeCard: () => ({}), syncHomeCardContent() {},
    reconcileHomeRail() { renders++; }, updateHomeRailNavigation() {},
  });
  return { view, root, config, renders: () => renders };
}

test("recommendations ignore late responses after navigation and identity changes", async () => {
  const requests = [];
  const { view, root, renders } = recommendationFixture({ post: (_url, _body, { signal }) =>
    new Promise(resolve => requests.push({ resolve, signal })) });
  view.mount();
  assert.equal(requests.length, 1);
  await view.refresh();
  assert.equal(requests.length, 1);
  view.unmount();
  assert.equal(requests[0].signal.aborted, true);
  view.mount();
  requests[0].resolve({ available: true, recommendations: [{ key: "fixture" }] });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(renders(), 0);
  assert.equal(root.dataset.state, "loading");
  view.invalidate();
  assert.equal(requests[1].signal.aborted, true);
  requests[1].resolve({ available: true, recommendations: [{ key: "fixture" }] });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(renders(), 0);
  view.unmount();
});

test("recommendation refinement retains its timer across identical refreshes and stops on leave", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  const { view, root } = recommendationFixture({ post: async () => {
    calls++;
    return { available: true, recommendations: [{ key: "fixture" }], source: "baseline" };
  } });
  try {
    view.mount();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(root.dataset.state, "ready");
    await view.refresh();
    t.mock.timers.tick(4000);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls, 2);
    view.unmount();
    t.mock.timers.tick(12000);
    assert.equal(calls, 2);
  } finally { view.unmount(); }
});


test("global search keeps progressive results, cancels superseded requests and preserves detail context", async () => {
  const nodes = new Map();
  const makeNode = () => Object.assign(new EventTarget(), {
    value: "", children: [], hidden: false, dataset: {}, textContent: "", classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {}, focus() {}, contains() { return false; }, querySelectorAll: () => [],
    appendChild(node) { this.children.push(node); }, replaceChildren(...nodes) { this.children = nodes; },
    querySelector(id) { if (!nodes.has(id)) nodes.set(id, makeNode()); return nodes.get(id); },
  });
  const doc = Object.assign(new EventTarget(), { body: makeNode(), createElement: makeNode, activeElement: null });
  const page = makeNode(); page.ownerDocument = doc;
  const shell = makeNode(); shell.ownerDocument = doc;
  const requests = [];
  let detailOpen = false;
  const search = createSearch(page, shell, {
    client: { get: (url, { signal }) => new Promise((resolve, reject) => requests.push({ url, signal, resolve, reject })) },
    createHomeCard: makeNode, mediaJellyfinStatus: () => "missing", rememberSearch() {},
    uniqueHomeContentEntries: entries => entries, uniqueHomeEntries: entries => entries,
    homeCollectionEntry: item => ({ kind: "collection", item }), homeMovieEntry: item => ({ kind: "movie", item }),
    homeSeriesEntry: item => ({ kind: "series", item }), homeAnimeEntry: item => ({ kind: "anime", item }),
    hydrateHomeMovieArtwork: async () => {}, hydrateHomeSeriesArtwork: async () => {},
    refreshCatalogJellyfinStatus: async () => {}, mediaDetailModalOpen: () => detailOpen,
  });
  const settle = () => new Promise(resolve => setImmediate(resolve));
  search.mount();
  const input = nodes.get("#global-search-input");
  input.value = "first";
  input.dispatchEvent(new Event("input"));
  assert.equal(requests.length, 0);
  search.search();
  assert.equal(requests.length, 4);
  requests[0].resolve({ results: [] });
  await settle();
  assert.equal(search.get().loading, true);
  requests[1].resolve({ results: Array.from({ length: 80 }, (_, id) => ({ slug: `movie-${id}`, title: `Movie ${id}` })) });
  await settle();
  assert.equal(search.get().results.length, 80);
  assert.equal(search.get().loading, false);
  assert.deepEqual(search.get().pendingCatalogs, ["Serien", "Anime"]);
  input.value = "second";
  search.search();
  assert.ok(requests.slice(0, 4).every(request => request.signal.aborted));
  requests[2].reject(new Error("obsolete error")); requests[3].resolve({ results: [] });
  for (const request of requests.slice(4)) request.resolve({ results: [{ title: "New" }] });
  await settle();
  assert.equal(search.get().failures.length, 0);
  assert.equal(search.get().results.length, 4);
  assert.equal(search.get().query, "second");
  detailOpen = true;
  search.close();
  assert.equal(search.get().active, true);
  search.unmount();
  assert.equal(search.get().active, false);
  search.mount();
  input.value = "third";
  input.dispatchEvent(new Event("keydown"));
  search.search();
  assert.equal(requests.length, 12);
  search.unmount();
  for (const request of requests.slice(8)) request.resolve({ results: [] });
  await settle();
  assert.deepEqual(search.get().results, []);
});


function updaterFixture(client, reload = () => {}) {
  const nodes = new Map();
  const node = () => Object.assign(new EventTarget(), {
    dataset: {}, textContent: "", value: "", disabled: false,
    classList: { toggle() {}, add() {}, remove() {} },
  });
  const root = node();
  root.querySelector = id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); };
  const socket = subscriptionSocket();
  return { view: createUpdater(root, { client, socket, reload }), root, socket, nodes };
}

test("updater presents temporary failures as retryable and recovers on the next check", async () => {
  let fail = true;
  const { view, root, nodes } = updaterFixture({ get: async () => {
    if (fail) throw Object.assign(new Error("raw network error"), { code: "request_timeout" });
    return { comparison: "identical", current_sha: "a", latest_sha: "a" };
  } });
  try {
    view.mount();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(root.dataset.state, "unknown");
    assert.equal(nodes.get("#updater-check").disabled, false);
    assert.equal(nodes.get("#updater-status").textContent, "Bitte erneut prüfen");
    assert.ok(!nodes.get("#updater-detail").textContent.includes("raw"));
    fail = false;
    await view.refresh(true);
    assert.equal(root.dataset.state, "current");
    assert.equal(nodes.get("#updater-check").disabled, false);
  } finally { view.unmount(); }
});

test("updater server busy and deadline statuses leave the retry button available", async () => {
  for (const error_code of ["check_busy", "check_timeout", "github_unavailable"]) {
    const { view, root, nodes } = updaterFixture({ get: async () => ({ error_code, error: "Bitte erneut prüfen." }) });
    try {
      view.mount();
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(root.dataset.state, "unknown");
      assert.equal(nodes.get("#updater-check").disabled, false);
      assert.equal(nodes.get("#updater-install").dataset.sha, "");
    } finally { view.unmount(); }
  }
});

test("updater reloads only for the exact target and removes restart timers on leave", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let installed = "old", checks = 0, reloads = 0;
  const { view, socket } = updaterFixture({ get: async () => {
    checks++;
    return { current_sha: installed, comparison: "identical", installer: { supported: true } };
  } }, () => reloads++);
  try {
    view.mount();
    await new Promise(resolve => setImmediate(resolve));
    socket.emit("updater_install", { installer: { active: true, state: "restarting", target_sha: "target" } });
    t.mock.timers.tick(3000);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(reloads, 0);
    installed = "target";
    t.mock.timers.tick(3000);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(reloads, 1);
    socket.emit("updater_install", { installer: { active: true, state: "restarting", target_sha: "next" } });
    view.unmount();
    const before = checks;
    t.mock.timers.tick(12000);
    assert.equal(checks, before);
    assert.equal(reloads, 1);
  } finally { view.unmount(); }
});

test("updater keeps unsaved mode edits and ignores responses after unmount", async () => {
  let resolve;
  let signal;
  const { view, socket, root, nodes } = updaterFixture({ get: (_url, options) => {
    signal = options.signal; return new Promise(done => { resolve = done; });
  } });
  view.mount();
  socket.emit("updater_config", { config: { update_mode: "manual", update_channel: "stable" } });
  nodes.get("#updater-mode").value = "automatic";
  root.dispatchEvent(new Event("input"));
  socket.emit("updater_config", { config: { update_mode: "manual", update_channel: "stable" } });
  assert.equal(nodes.get("#updater-mode").value, "automatic");
  const before = nodes.get("#updater-status").textContent;
  view.unmount();
  assert.equal(signal.aborted, true);
  resolve({ current_sha: "late", comparison: "identical" });
  await new Promise(done => setImmediate(done));
  assert.equal(nodes.get("#updater-status").textContent, before);
});


test("integration health trusts only the server contract and never Jellyfin media status", () => {
  for (const state of ["healthy", "degraded", "offline", "auth_failed", "disabled", "unknown"]) {
    assert.equal(integrationHealth({ integration_health: { state, detail: "Fixture" } }).state, state);
  }
  assert.equal(integrationHealth({ jellyfin_status: "owned", health: "healthy" }).state, "unknown");
  assert.equal(integrationHealth({ integration_health: { state: "new", detail: "401 offline" } }).state, "unknown");
});

function settingsFormFixture() {
  const nodes = new Map();
  const root = Object.assign(new EventTarget(), {
    ownerDocument: new EventTarget(), querySelectorAll: () => [],
    querySelector(id) {
      if (!nodes.has(id)) nodes.set(id, Object.assign(new EventTarget(), {
        value: "", checked: false, disabled: false, textContent: "", dataset: {},
      }));
      return nodes.get(id);
    },
  });
  return { root, nodes };
}

test("untouched integrations do not block saving when Seerr is offline", async () => {
  const { root, nodes } = settingsFormFixture();
  const posts = [];
  const view = createIntegrationSettings(root, { client: {
    get: async url => {
      if (url === "/api/seerr/config") throw new Error("offline");
      return url === "/api/modules" ? { modules: [] } : { enabled: false };
    },
    post: async (url, body) => { posts.push({ url, body }); return body; },
  } });
  try {
    view.mount(); await view.refresh();
    for (const kind of ["tmdb", "seerr", "telegram"]) await view.save(kind);
    assert.equal(posts.length, 0);
    nodes.get(".seerr-settings").dispatchEvent(new Event("change"));
    await assert.rejects(view.save("seerr"), /erfolgreich geladen/);
    nodes.get("#telegram-enabled").checked = true;
    nodes.get("#telegram-token").value = "fixture";
    nodes.get(".telegram-settings").dispatchEvent(new Event("input"));
    await view.save("telegram");
    assert.equal(posts.length, 1);
    assert.equal(posts[0].body.bot_token, "fixture");
    await view.save("telegram");
    assert.equal(posts.length, 1);
  } finally { view.unmount(); }
});

test("AI preserves edits during initial loading and saving and persists the next draft", async () => {
  const { root, nodes } = settingsFormFixture();
  let load, save;
  const writes = [];
  const view = createIntelligenceSettings(root, { client: {
    get: () => new Promise(resolve => { load = resolve; }),
    post: (_url, body) => { writes.push(body); return new Promise(resolve => { save = resolve; }); },
  } });
  try {
    view.mount();
    nodes.get("#ai-url").value = "http://draft:11434";
    nodes.get("#ai-model").value = "draft-model";
    root.dispatchEvent(new Event("input"));
    const saving = view.save();
    assert.equal(writes.length, 0);
    load({ enabled: false, url: "http://server:11434", model: "server-model" });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(nodes.get("#ai-model").value, "draft-model");
    assert.equal(writes[0].url, "http://draft:11434");
    nodes.get("#ai-model").value = "newer-model";
    root.dispatchEvent(new Event("input"));
    save(writes[0]); await saving;
    assert.equal(nodes.get("#ai-model").value, "newer-model");
    const next = view.save();
    assert.equal(writes[1].model, "newer-model");
    save(writes[1]); await next;
    await view.save();
    assert.equal(writes.length, 2);
  } finally { view.unmount(); }
});

test("AI refuses edited settings when its initial config could not be loaded", async () => {
  const { root } = settingsFormFixture();
  let posts = 0;
  const view = createIntelligenceSettings(root, { client: {
    get: async () => { throw new Error("offline"); },
    post: async () => { posts++; },
  } });
  try {
    view.mount(); await new Promise(resolve => setImmediate(resolve));
    await view.save();
    root.dispatchEvent(new Event("input"));
    await assert.rejects(view.save(), /vor dem Speichern geladen/);
    assert.equal(posts, 0);
  } finally { view.unmount(); }
});

test("early AI edits preserve untouched server fields rather than saving defaults", async () => {
  const { root, nodes } = settingsFormFixture();
  let load, body;
  const view = createIntelligenceSettings(root, { client: {
    get: () => new Promise(resolve => { load = resolve; }),
    post: async (_url, value) => { body = value; return value; },
  } });
  try {
    view.mount();
    nodes.get("#ai-enabled").checked = true;
    const change = new Event("change");
    Object.defineProperty(change, "target", { value: { id: "ai-enabled" } });
    root.dispatchEvent(change);
    load({ enabled: false, url: "http://custom:11434", model: "custom-model", timeout_seconds: 90 });
    await new Promise(resolve => setImmediate(resolve));
    await view.save();
    assert.equal(body.enabled, true);
    assert.equal(body.url, "http://custom:11434");
    assert.equal(body.model, "custom-model");
    assert.equal(body.timeout_seconds, 90);
  } finally { view.unmount(); }
});

test("settings wait for bootstrap and report partial saves with their failing section", async () => {
  const { root, nodes } = settingsFormFixture();
  let load, writes = 0, refreshes = 0;
  const feature = { initialize: async () => {}, save: async () => {} };
  const features = Object.fromEntries(["jellyfin", "intelligence", "automation", "providers", "updater", "integrations"].map(key => [key, feature]));
  features.jellyfin = { ...feature, save: async () => { throw new Error("offline"); } };
  const view = createSettings(root, {
    getFeatures: () => features, language: () => "de", locale: () => "de-DE",
    languageWizard: { dispose() {} }, onSaved: async () => { refreshes++; },
    client: { get: () => new Promise(resolve => { load = resolve; }), post: async () => { writes++; return {}; } },
  });
  try {
    const initializing = view.initialize(); view.mount();
    const saving = view.save();
    assert.equal(writes, 0);
    load({ save_path: "/movies", series_path: "/series" });
    await initializing; await saving;
    assert.equal(writes, 1);
    assert.equal(refreshes, 1);
    assert.match(nodes.get("#settings-saved-status").textContent, /Teilweise gespeichert.*Betrieb und Speicher.*Quellen.*Fehler bei Jellyfin: offline/);
    assert.equal(nodes.get("#settings-save").disabled, false);
  } finally { view.dispose(); }
});

test("updater save acknowledgements preserve edits made while the request is pending", async () => {
  let respond;
  const writes = [];
  const { view, root, nodes } = updaterFixture({
    get: async () => ({ comparison: "identical", config: { update_mode: "manual", update_channel: "stable" } }),
    post: (_url, body) => { writes.push(body); return new Promise(resolve => { respond = resolve; }); },
  });
  try {
    view.mount(); await new Promise(resolve => setImmediate(resolve));
    nodes.get("#updater-mode").value = "automatic";
    root.dispatchEvent(new Event("input"));
    const saving = view.save();
    nodes.get("#updater-mode").value = "manual";
    root.dispatchEvent(new Event("change"));
    respond({ update_mode: "automatic", update_channel: "stable" }); await saving;
    assert.equal(nodes.get("#updater-mode").value, "manual");
    const next = view.save();
    assert.equal(writes[1].update_mode, "manual");
    respond({ update_mode: "manual", update_channel: "stable" }); await next;
  } finally { view.unmount(); }
});


test("settings abort a save sequence on navigation and keep newer edits", async () => {
  const nodes = new Map();
  const root = new EventTarget();
  root.querySelector = id => {
    if (!nodes.has(id)) nodes.set(id, Object.assign(new EventTarget(), { value: "", textContent: "", disabled: false }));
    return nodes.get(id);
  };
  root.querySelectorAll = () => [];
  let complete;
  const calls = [];
  const feature = { initialize: async () => {}, save: async () => { calls.push("feature"); } };
  const settings = createSettings(root, {
    getFeatures: () => Object.fromEntries(["jellyfin", "intelligence", "automation", "providers", "updater", "integrations"].map(key => [key, feature])),
    language: () => "de", locale: () => "de-DE", changeLanguage: async () => {},
    languageWizard: { open() {}, dispose() {} },
    client: { get: async () => ({ save_path: "/server" }), post: (url, body, { signal }) => {
      calls.push({ url, body, signal });
      return new Promise(resolve => { complete = resolve; });
    } },
  });
  await settings.initialize(); settings.mount();
  const input = nodes.get("#save-path"); input.value = "/draft"; input.dispatchEvent(new Event("input"));
  await settings.initialize();
  assert.equal(input.value, "/draft");
  const saving = settings.save();
  assert.equal(calls.length, 1);
  settings.unmount(); assert.equal(calls[0].signal.aborted, true);
  const hiddenStatus = nodes.get("#settings-saved-status").textContent;
  complete({}); await saving;
  assert.equal(calls.length, 1);
  assert.equal(nodes.get("#settings-saved-status").textContent, hiddenStatus);
  settings.mount(); settings.unmount(); settings.mount();
  nodes.get("#settings-save").dispatchEvent(new Event("click"));
  assert.equal(calls.length, 2);
  settings.dispose(); complete({});
});


test("tab scroll memory keeps movie and series positions independent", () => {
  const scroller = { scrollTop: 0 };
  let scrollY = 1700;
  const windowRef = {
    get scrollY() { return scrollY; },
    scrollTo(value, top) {
      scrollY = typeof value === "object" ? Number(value.top || 0) : Number(top || 0);
      scroller.scrollTop = scrollY;
    },
  };
  const documentRef = { scrollingElement: scroller };
  const memory = createTabScrollMemory(windowRef, documentRef);

  memory.save("serien");
  scrollY = 0;
  scroller.scrollTop = 0;
  memory.save("filme");

  assert.equal(memory.restore("serien"), 1700);
  assert.equal(scrollY, 1700);
  assert.equal(memory.restore("filme"), 0);
  assert.equal(scrollY, 0);
});

test("infinite scrolling cancels scheduled work and remounts without duplicate listeners", t => {
  const frames = new Map(); let nextFrame = 0, loads = 0;
  const oldRequest = globalThis.requestAnimationFrame, oldCancel = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = callback => { frames.set(++nextFrame, callback); return nextFrame; };
  globalThis.cancelAnimationFrame = id => frames.delete(id);
  t.after(() => { if (oldRequest) globalThis.requestAnimationFrame = oldRequest; else delete globalThis.requestAnimationFrame; if (oldCancel) globalThis.cancelAnimationFrame = oldCancel; else delete globalThis.cancelAnimationFrame; });
  const win = Object.assign(new EventTarget(), { innerHeight: 800, getComputedStyle: () => ({ overflowY: "visible" }) });
  const root = Object.assign(new EventTarget(), { ownerDocument: { defaultView: win } });
  const sentinel = { classList: { contains: () => false }, getBoundingClientRect: () => ({ top: 1500 }) };
  const feature = createInfiniteScroll(root, { sentinel, loadNext: () => loads++ });
  const flush = () => { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback()); };
  feature.mount(); win.dispatchEvent(new Event("scroll")); root.dispatchEvent(new Event("scroll"));
  assert.equal(frames.size, 1);
  feature.unmount(); flush(); assert.equal(loads, 0);
  win.dispatchEvent(new Event("resize")); assert.equal(frames.size, 0);
  feature.mount(); feature.mount(); flush(); assert.equal(loads, 1);
  feature.unmount(); feature.mount(); win.dispatchEvent(new Event("scroll")); flush(); assert.equal(loads, 2);
  feature.unmount();
});


test("catalog Jellyfin batches preserve newer results and ignore aborted reads", async () => {
  const requests = [];
  const items = Array.from({ length: 205 }, (_, index) => ({ slug: String(index), title: `Film ${index}` }));
  const entries = items.map(item => ({ kind: "movie", item }));
  let renders = 0;
  const model = createCatalogJellyfin({ uniqueHomeEntries: entries => entries,
    homeEntryKey: entry => `${entry.kind}:${entry.item.slug}`, getMovieMetadata: () => ({}),
    getMovieInstances: slug => items.filter(item => item.slug === slug),
    client: { post: (_url, body, { signal }) => new Promise(resolve => requests.push({ body, signal, resolve })) },
  });
  const first = model.refresh([...entries, { kind: "collection", item: { collection_id: 1 } }], () => renders++);
  assert.deepEqual(requests.map(request => request.body.items.length), [100, 100, 5]);
  const second = model.refresh([entries[0]], () => renders++);
  requests[3].resolve({ configured: true, matches: { "movie:0": true } }); await second;
  for (const request of requests.slice(0, 3)) request.resolve({ configured: true, matches: Object.fromEntries(request.body.items.map(item => [item.slug, false])) });
  await first;
  assert.equal(items[0].jellyfin_status, "owned"); assert.equal(items[1].jellyfin_status, "missing");
  assert.equal(model.getStatus("movie:0"), "owned");
  const controller = new AbortController();
  const cancelled = model.refresh([entries[0]], () => renders++, { signal: controller.signal });
  controller.abort(); assert.equal(requests[4].signal.aborted, true);
  requests[4].resolve({ matches: { "movie:0": false } }); await cancelled;
  assert.equal(items[0].in_jellyfin, true); assert.equal(renders, 2);
  const stopped = model.refresh([entries[0]], () => renders++); model.unmount(); model.mount();
  requests[5].resolve({ matches: { "movie:0": false } }); await stopped;
  assert.equal(items[0].in_jellyfin, true); assert.equal(renders, 2); model.unmount();
});



test("catalog Jellyfin propagates one deduplicated series result to every visible instance", async () => {
  const homeSeries = { base_slug: "moflix:42:stargate", title: "Stargate" };
  const catalogSeries = { base_slug: "moflix:42:stargate", title: "Stargate" };
  const entries = [
    { kind: "series", item: homeSeries },
    { kind: "series", item: catalogSeries },
  ];
  const uniqueHomeEntries = values => {
    const seen = new Set();
    return values.filter(entry => {
      const key = `${entry.kind}:${entry.item.base_slug}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };
  const model = createCatalogJellyfin({
    uniqueHomeEntries,
    homeEntryKey: entry => `${entry.kind}:${entry.item.base_slug}`,
    getMovieMetadata: () => ({}),
    getMovieInstances: () => [],
    client: {
      async post(_url, body) {
        assert.equal(body.items.length, 1);
        assert.equal(body.items[0].slug, "series:moflix:42:stargate");
        return {
          configured: true,
          statuses: { "series:moflix:42:stargate": "owned" },
          matches: { "series:moflix:42:stargate": true },
        };
      },
    },
  });

  try {
    await model.refresh(entries);
    assert.equal(homeSeries.jellyfin_status, "owned");
    assert.equal(catalogSeries.jellyfin_status, "owned");
    assert.equal(homeSeries.in_jellyfin, true);
    assert.equal(catalogSeries.in_jellyfin, true);
  } finally {
    model.unmount();
  }
});


test("trailers own pending playback, preserve position and ignore disposed callbacks", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const previousFrame = globalThis.requestAnimationFrame;
  const previousCancel = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = callback => setTimeout(callback, 16);
  globalThis.cancelAnimationFrame = id => clearTimeout(id);
  t.after(() => { globalThis.requestAnimationFrame = previousFrame; globalThis.cancelAnimationFrame = previousCancel; });
  class Element extends EventTarget {
    constructor(id) {
      super(); this.id = id; this.hidden = true; this.dataset = {}; this.attrs = {}; this.isConnected = true;
      this.classList = { add() {}, remove() {} }; this.focusCount = 0;
      this.contentWindow = { postMessage() {} };
    }
    get src() { return this.attrs.src; }
    set src(value) { this.attrs.src = value; }
    getAttribute(name) { return this.attrs[name]; }
    removeAttribute(name) { delete this.attrs[name]; }
    setAttribute(name, value) { this.attrs[name] = value; }
    querySelector() { return { textContent: "" }; }
    querySelectorAll() { return []; }
    closest() { return elements.get("fp-detail-panel"); }
    focus() { this.focusCount++; }
  }
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); };
  const window = new EventTarget();
  window.HTMLElement = Element; window.location = { origin: "http://localhost" };
  window.matchMedia = () => ({ matches: false });
  const document = { getElementById: get, body: get("body"), activeElement: get("trigger"),
    querySelector: selector => get(selector === "#fp-detail-panel" ? "fp-detail-panel" : "series-panel") };
  const trailers = createTrailers(document, { window, storage: { getItem: () => null, setItem() {} } });
  const movie = { title: "Movie", trailer: { site: "YouTube", key: "abcdefghijk" } };
  get("fp-detail-modal").hidden = false;
  trailers.mount(); trailers.mount();
  trailers.film.schedule(movie);
  trailers.film.stop();
  t.mock.timers.tick(2500);
  assert.equal(get("fp-detail-hero-frame").src, undefined);
  trailers.film.schedule(movie);
  t.mock.timers.tick(2000);
  const hero = get("fp-detail-hero-frame");
  const loaded = hero.onload;
  loaded(); // Also checks that the film panel is in scope.
  const src = hero.src;
  trailers.film.schedule(movie);
  assert.equal(hero.src, src);
  const send = (payload, origin = "https://www.youtube-nocookie.com") => {
    const event = new Event("message");
    Object.assign(event, { origin, source: hero.contentWindow, data: payload });
    window.dispatchEvent(event);
  };
  send({ info: { currentTime: 32 } }, "https://untrusted.example");
  send({ info: { currentTime: 17 } });
  trailers.open(movie, get("trigger"));
  assert.match(get("fp-trailer-frame").src, /&start=17&/);
  assert.equal(hero.src, undefined);
  loaded();
  assert.equal(get("fp-detail-hero-mute").hidden, true);
  const staleLoad = get("fp-trailer-frame").onload;
  trailers.close();
  staleLoad();
  t.mock.timers.tick(12000);
  assert.equal(get("fp-trailer-modal").dataset.playerState, "idle");
  assert.equal(get("fp-trailer-close").focusCount, 0);
  assert.equal(get("trigger").focusCount, 1);
  trailers.film.schedule(movie);
  trailers.unmount();
  t.mock.timers.tick(2500);
  assert.equal(hero.src, undefined);
  trailers.open(movie, get("trigger"));
  assert.equal(get("fp-trailer-modal").hidden, true);
  trailers.mount();
  trailers.open(movie, get("trigger"));
  t.mock.timers.tick(10000);
  assert.equal(get("fp-trailer-modal").dataset.playerState, "error");
  trailers.unmount();
});


test("card artwork disconnects observers and fallback listeners across remounts", () => {
  const root = new EventTarget();
  const observed = new Set();
  const callbacks = [];
  let disconnects = 0;
  const image = { isConnected: true, complete: false, classList: { toggle() {} }, remove() { this.removed = true; } };
  root.querySelectorAll = () => [image];
  const artwork = createCardArtwork(root, { window: {
    IntersectionObserver: class {
      constructor(callback) { callbacks.push(callback); }
      observe(image) { observed.add(image); }
      unobserve(image) { observed.delete(image); }
      disconnect() { observed.clear(); disconnects++; }
    },
  } });
  artwork.set(image, [{ url: "first", posterFallback: false }, { url: "second", posterFallback: true }]);
  artwork.mount(); artwork.mount();
  assert.equal(callbacks.length, 1);
  assert.equal(observed.has(image), true);
  callbacks[0]([{ target: image, isIntersecting: true, intersectionRatio: 1 }]);
  assert.equal(image.src, "first");
  assert.equal(observed.size, 0);
  const error = () => {
    const event = new Event("error"); Object.defineProperty(event, "target", { value: image }); root.dispatchEvent(event);
  };
  error();
  assert.equal(image.src, "second");
  artwork.unmount();
  error();
  assert.equal(image.removed, undefined);
  callbacks[0]([{ target: image, isIntersecting: true, intersectionRatio: 1 }]);
  assert.equal(disconnects, 1);
  artwork.mount(); error();
  assert.equal(image.removed, true);
  artwork.unmount();
});


test("discovery exposure is personal, bounded by day and limits repeated identities", () => {
  let day = "2026-09-25";
  const stored = new Map();
  const storage = { getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value) };
  const policy = createDiscoveryPolicy({ storage, personalStorageKey: key => `${key}:user`,
    homeEntryMedia: entry => entry.item, homeEntryKey: entry => entry.item.slug,
    localDateKey: () => day, getShuffle: () => 0, stableDiscoveryHash: () => 0,
    mediaContentLanguages: () => new Set(), getHomeData: () => ({}),
    homeMovieEntry: item => ({ kind: "movie", item }), homeSeriesEntry: item => ({ kind: "series", item }),
    allowedHomeEntries: entries => entries, uniqueHomeEntries: entries => entries,
    normalizeUiContentLanguage: value => value,
  });
  const entries = Array.from({ length: 16 }, (_, id) => ({ kind: "movie", item: { slug: `m${id}`, title: `Movie ${id}`, year: 2026 } }));
  policy.recordDiscoveryExposureV2("top", entries.slice(0, 10));
  assert.equal(policy.discoveryV2ExposurePenalty(entries[0], "top"), 0);
  day = "2026-09-26";
  assert.equal(policy.discoveryV2ExposurePenalty(entries[0], "top"), 16);
  const previous = policy.discoveryV2PreviousLaneKeys("top");
  const picked = policy.discoveryV2SelectDiverse(entries.map((entry, index) => ({ entry, score: 100 - index })), 10, { repeatKeys: previous, repeatLimit: 4 });
  assert.equal(picked.length, 10);
  assert.equal(picked.filter(entry => previous.has(policy.discoveryV2LogicalKey(entry))).length, 4);
  assert.equal([...stored.keys()][0], "royal-home-exposure-v2:user");
  day = "2026-10-30";
  assert.deepEqual(policy.loadDiscoveryExposureV2().days, {});
});

test("daily Top preserves same-day ranks, advances tomorrow and ignores late unmounted responses", async t => {
  let day = "2026-09-25";
  t.mock.timers.enable({ apis: ["Date"], now: new Date(`${day}T10:00:00`).getTime() });
  let resolveRequest, requestSignal;
  const stored = new Map();
  const root = new EventTarget(); root.ownerDocument = new EventTarget(); root.querySelector = () => null;
  let renders = 0;
  const daily = createDailyTop(root, {
    localDateKey: date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`, homeEntryKey: entry => `movie:${entry.item.slug}`,
    discoveryV2LogicalKey: entry => entry.item.slug, loadDiscoveryProfile: () => ({}),
    fallbackEntries: () => [{ kind: "movie", item: { slug: "fallback" } }], renderHome: () => renders++,
    storage: { getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value) },
    client: { get: (_url, { signal }) => { requestSignal = signal; return new Promise(resolve => { resolveRequest = resolve; }); } },
  });
  const candidate = (slug, rank) => ({ kind: "movie", identity: slug, global_rank: rank,
    item: { slug, title: `Movie ${slug}`, cover_url: "poster" } });
  t.after(() => daily.unmount());
  daily.mount();
  resolveRequest({ version: 2, period: day, candidates: [candidate("a", 1), candidate("b", 2)] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(daily.entries().map(entry => entry.item.slug), ["a", "b"]);
  assert.equal(renders, 0);
  day = "2026-09-26";
  t.mock.timers.setTime(new Date(`${day}T10:00:00`).getTime());
  daily.refresh();
  resolveRequest({ version: 2, period: day, candidates: [candidate("b", 1), candidate("a", 2)] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(daily.entries().map(entry => entry.item.slug), ["b", "a"]);
  assert.equal(daily.entries()[0].item.daily_top.movement.label, "↑1");
  assert.equal(renders, 1);
  day = "2026-09-27";
  t.mock.timers.setTime(new Date(`${day}T10:00:00`).getTime());
  daily.refresh();
  daily.unmount();
  assert.equal(requestSignal.aborted, true);
  resolveRequest({ version: 2, period: day, candidates: [candidate("late", 1)] });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(daily.entries()[0].item.slug, "fallback");
  assert.equal(renders, 1);
});


test("updater refresh replaces failed target and retry posts the newly offered commit", async () => {
  const failed = { state: "error", active: false, target_sha: "broken", error: "Missing file", supported: true };
  let latest = "broken";
  const posted = [];
  const { view, socket, nodes, root } = updaterFixture({
    get: async () => ({ latest_sha: latest, update_available: true, update_channel: "overnight", quality_approved: true, installer: failed }),
    post: async (url, body) => { posted.push({ url, body }); return { installer: { state: "idle" } }; },
  });
  try {
    view.mount();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(nodes.get("#updater-install").textContent, "Erneut versuchen");
    latest = "fixed";
    await view.refresh(true);
    assert.equal(nodes.get("#updater-latest").textContent, "fixed");
    assert.equal(nodes.get("#updater-install").dataset.sha, "fixed");
    assert.equal(nodes.get("#updater-status").textContent, "Update verfügbar");
    assert.equal(root.dataset.installing, "false");
    socket.emit("updater_install", { installer: failed });
    assert.equal(nodes.get("#updater-status").textContent, "Update verfügbar");
    nodes.get("#updater-install").dispatchEvent(new Event("click"));
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(posted, [{ url: "/api/updater/install", body: { target_sha: "fixed", confirm_channel_switch: false } }]);
  } finally { view.unmount(); }
});

test("updater does not let a previous installation failure bypass overnight quality checks", async () => {
  const { view, nodes } = updaterFixture({ get: async () => ({
    latest_sha: "failed-ci", update_channel: "overnight", quality_approved: false,
    quality_gate: "failed", update_available: false,
    installer: { state: "error", target_sha: "failed-ci", error: "Old failure" },
  }) });
  try {
    view.mount();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(nodes.get("#updater-status").textContent, "Overnight-Quality fehlgeschlagen");
  } finally { view.unmount(); }
});


test("startup curtain disposes fallback timers after its transition", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let removals = 0, leaving = 0;
  const loader = Object.assign(new EventTarget(), {
    classList: { add() { leaving++; } }, remove() { removals++; },
  });
  const window = Object.assign(new EventTarget(), { matchMedia: () => ({ matches: true }) });
  const curtain = createStartupCurtain({ getElementById: () => loader, defaultView: window });
  curtain.finish(); curtain.finish();
  t.mock.timers.tick(1);
  assert.equal(leaving, 1);
  loader.dispatchEvent(new Event("transitionend"));
  t.mock.timers.tick(20000);
  window.dispatchEvent(new Event("pagehide"));
  assert.equal(removals, 1);
});

test("queue synchronization applies only latest history despite render invalidation", async () => {
  const pending = [], histories = [];
  const controller = new AbortController();
  let sync;
  const view = { active: true, signal: controller.signal,
    render() { sync.invalidate(); }, renderHistory: value => histories.push(value) };
  sync = createQueueSync({ getView: () => view, downloadState: {}, setDownloadState() {},
    refreshFpQueuePresentation() {}, renderSeriesTiles() {},
    client: { get: () => new Promise(resolve => pending.push(resolve)) },
  });
  sync.acceptMutation({ queue: {} });
  sync.acceptMutation({ queue: {} });
  pending[1]({ jobs: ["new"] });
  pending[0]({ jobs: ["old"] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(histories, [["new"]]);
  sync.acceptMutation({ queue: {} });
  controller.abort(); view.active = false;
  pending[2]({ jobs: ["after session"] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(histories, [["new"]]);
});


test("profile actions isolate personal storage and invalidate only on identity changes", () => {
  let user = { id: "first" }, invalidations = 0;
  const actions = createProfileActions({ getUser: () => user,
    invalidateHome: () => invalidations++, invalidateRecommendations: () => invalidations++,
    setUser() {}, household: { mount() {} }, userMenu: { mount() {} },
  });
  actions.initUserProfile(); actions.initUserProfile();
  assert.equal(invalidations, 0);
  assert.equal(actions.personalStorageKey("history"), "history:first");
  user = { id: "second" }; actions.initUserProfile();
  assert.equal(invalidations, 2);
  assert.equal(actions.personalStorageKey("history"), "history:second");
  assert.equal(actions.personalStorageKey("history", "admin-legacy"), "history");
});


test("queue wait copy distinguishes missing requested audio from provider outages", () => {
  assert.equal(queueWaitCopy({ status: "waiting_provider", wait_reason: "language_unavailable",
    content_language: "de", next_retry_at: 1900 }, 1000),
    "Wartet auf passende Sprache (DE) · Nächster Sprachtest in ~15 Min.");
});
