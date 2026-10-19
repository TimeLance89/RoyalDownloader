import { test } from "node:test";
import assert from "node:assert/strict";
import { createTasteProfile } from "../../web/js/features/profile/taste.js";

test("opening a recommendation resolves its taste event before Home refetch is safe", async () => {
  const store = new Map();
  const storage = { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value) };
  let fulfill, sent;
  const client = { post: (path, payload) => {
    sent = { path, payload };
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
  let finished = false;
  void promise.then(() => { finished = true; });
  await Promise.resolve();
  assert.equal(finished, false, "must not refresh Home while server taste write is pending");
  fulfill({ profile: { dimensions: { genres: { Drama: 2 } }, interactions: 1 } });
  await promise;
  assert.equal(profile.load().genres.Drama, 2);
  profile.unmount();
});
