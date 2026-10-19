import { test } from "node:test";
import assert from "node:assert/strict";
import { createTasteProfile } from "../../web/js/features/profile/taste.js";

test("opening a recommendation resolves its taste event before Home refetch is safe", async () => {
  const store = new Map();
  const storage = { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value) };
  let fulfill, sent;
  const client = { post: (path, payload, options) => {
    sent = { path, payload, options };
    return new Promise(resolve => { fulfill = resolve; });
  } };
  const profile = createTasteProfile({ getElementById: () => null }, {
    getUser: () => ({ id: "home-user-a" }), currentTasteTarget: () => null,
    renderTasteProfileSummary() {}, shouldRenderHome: () => false, renderHome() {},
    homeMovieEntry: item => ({ kind: "movie", item }),
    homeSeriesEntry: item => ({ kind: "series", item }),
    homeEntryMedia: entry => entry.item,
    homeEntryKey: entry => "movie:" + entry.item.slug,
    client, storage,
  });
  const promise = profile.track("movie", { slug: "tmdb:17", title: "Test title", genres: ["Drama"] }, 0.25, "open");
  assert.equal(typeof promise?.then, "function");
  assert.equal(sent.path, "/api/taste/events");
  assert.equal(sent.payload.item_key, "movie:tmdb:17");
  assert.equal(sent.options.headers["X-Royal-Profile"], "home-user-a");
  let finished = false;
  void promise.then(() => { finished = true; });
  await Promise.resolve();
  assert.equal(finished, false, "must not refresh Home while server taste write is pending");
  fulfill({ profile: { dimensions: { genres: { Drama: 2 } }, interactions: 1 } });
  await promise;
  assert.equal(profile.load().genres.Drama, 2);
  profile.unmount();
});


test("server taste synchronization refreshes Home only for the authenticated owner", async () => {
  const store = new Map();
  const storage = { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value) };
  let owner = "profile-a", resolveGet, refreshed = 0;
  const client = { get: () => new Promise(resolve => { resolveGet = resolve; }) };
  const profile = createTasteProfile({ getElementById: () => null }, {
    getUser: () => ({ id: owner }), currentTasteTarget: () => null,
    renderTasteProfileSummary() {}, shouldRenderHome: () => false, renderHome() {},
    homeMovieEntry: item => ({ kind: "movie", item }),
    homeSeriesEntry: item => ({ kind: "series", item }), homeEntryMedia: entry => entry.item,
    homeEntryKey: entry => entry.item.slug, storage, client,
    onProfileSync: () => { refreshed += 1; },
  });
  const obsolete = profile.sync();
  owner = "profile-b";
  resolveGet({ dimensions: { genres: { Horror: 12 } }, interactions: 3, legacy_imported: true });
  await obsolete;
  assert.equal(refreshed, 0, "late profile-a response must never refresh profile-b");
  const current = profile.sync();
  resolveGet({ dimensions: { genres: { Drama: 12 } }, interactions: 4, legacy_imported: true });
  await current;
  assert.equal(refreshed, 1);
  assert.equal(profile.load().genres.Drama, 12);
  profile.unmount();
});

test("failed network taste write is not mistaken for successfully saved feedback", async () => {
  const profile = createTasteProfile({ getElementById: () => null }, {
    getUser: () => ({ id: "user-a" }), currentTasteTarget: () => null,
    renderTasteProfileSummary() {}, shouldRenderHome: () => false, renderHome() {},
    homeMovieEntry: item => ({ kind: "movie", item }),
    homeSeriesEntry: item => ({ kind: "series", item }),
    homeEntryMedia: entry => entry.item, homeEntryKey: entry => "movie:" + entry.item.slug,
    storage: { getItem: () => null, setItem() {} },
    client: { post: () => Promise.reject(new Error("network down")) },
  });
  const warn = console.warn;
  console.warn = () => {};
  try {
    assert.equal(await profile.track("movie", { slug: "tmdb:19", title: "Offline" }, .25, "open"), false);
  } finally {
    console.warn = warn;
    profile.unmount();
  }
});
