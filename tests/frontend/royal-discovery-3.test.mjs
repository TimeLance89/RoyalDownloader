import { test } from "node:test";
import assert from "node:assert/strict";
import { createHomeData } from "../../web/js/features/home/data.js";
import { homeTasteReady } from "../../web/js/features/home/taste-readiness.js";
import { HOME_RAIL_CATALOG, normalizeHomeLayout } from "../../web/js/features/home/layout-model.js";

function fixture() {
  let owner = "account-A";
  const requests = [], rendered = [];
  const client = { get: (url) => new Promise((resolve, reject) =>
    requests.push({ url, resolve, reject })) };
  const data = createHomeData({
    client, storage: { getItem: () => null, setItem() {} },
    getTasteStorageKey: () => owner,
    getMovieMetadata: () => ({}), isRendered: () => true,
    homeAllEntries: () => [], homeArtworkEntriesInLayout: () => [],
    renderHome: options => rendered.push(options),
    syncFpCatalogFromHome() {}, syncSeriesCatalogFromHome() {},
    hydrateHomeMovieArtwork: async () => {},
    hydrateHomeSeriesArtwork: async () => {},
    refreshCatalogJellyfinStatus: async () => {},
    discoveryV2MergeItems: (_items, previous) => previous,
    homeMovieEntry: item => ({ kind: "movie", item }),
    homeSeriesEntry: item => ({ kind: "series", item }),
  });
  return { data, requests, rendered, switchTo(id) { owner = id; } };
}

function response(tmdbId) {
  return { results: [{ kind: "movie", item: { tmdb_discovery: true,
    tmdb_id: tmdbId, title: `Recommendation ${tmdbId}` } }] };
}

test("Home-only cold start uses meaningful onboarding taste", () => {
  assert.equal(homeTasteReady({ interactions: 5, confidence: .0234,
    dimensions: { genres: { Thriller: 12 } } }), true);
  assert.equal(homeTasteReady({ interactions: 2, confidence: .01,
    dimensions: { media_types: { movie: 6 } } }), false);
});

test("old saved Home layout migrates and keeps an explicitly customized order", () => {
  assert.ok(HOME_RAIL_CATALOG.some(rail => rail.id === "discovered"));
  const oldOrder = ["personal", "top", "series", "genre", "explore", "gems",
    "fresh", "new_movies", "new_series", "high_rated", "movies", "library"];
  assert.equal(normalizeHomeLayout({ rail_order: oldOrder }).rail_order[1], "discovered");
  const customOrder = ["library", "top", "personal"];
  assert.deepEqual(normalizeHomeLayout({ rail_order: customOrder }).rail_order.slice(0, 3), customOrder);
});

test("Household profile switch immediately masks previous recommendations", async () => {
  const f = fixture();
  f.data.refreshDiscovery();
  assert.equal(f.requests.length, 1);
  f.switchTo("account-B");
  assert.deepEqual(f.data.get().personalDiscoveries, []);
  f.data.refreshDiscovery();
  assert.equal(f.requests.length, 2);
  f.requests[1].resolve(response(22));
  await Promise.resolve(); await Promise.resolve();
  assert.equal(f.data.get().personalDiscoveries[0]?.item?.tmdb_id, 22);
  f.requests[0].resolve(response(11));
  await Promise.resolve(); await Promise.resolve();
  assert.equal(f.data.get().personalDiscoveries[0]?.item?.tmdb_id, 22);
  f.switchTo("account-C");
  assert.deepEqual(f.data.get().personalDiscoveries, []);
  f.data.unmount();
});

test("Unmount aborts in-flight Home discovery without publishing stale results", async () => {
  const f = fixture();
  f.data.refreshDiscovery();
  f.data.unmount();
  f.requests[0].resolve(response(88));
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(f.data.get().personalDiscoveries, []);
});

test("Invalid TMDB candidate data is never added to Home", async () => {
  const f = fixture();
  f.data.refreshDiscovery();
  f.requests[0].resolve({ results: [
    { kind: "movie", item: { title: "Missing marker" } },
    { kind: "other", item: { tmdb_discovery: true } },
    { kind: "series", item: { tmdb_discovery: true, tmdb_id: 9 } },
  ] });
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(f.data.get().personalDiscoveries.map(x => x.item.tmdb_id), [9]);
  f.data.unmount();
});
