import test from "node:test";
import assert from "node:assert/strict";
import { createHomeSavedMedia, savedHomeEntries } from "../../web/js/features/home/saved-media.js";
import { HOME_RAIL_CATALOG, defaultHomeLayout, normalizeHomeLayout } from "../../web/js/features/home/layout-model.js";

const saved = (type, id, title, created) => ({
  media_type: type, tmdb_id: id, title, created_at: created,
});
const tick = () => new Promise(resolve => setImmediate(resolve));

function homeFixture({ defer = false } = {}) {
  const document = new EventTarget();
  document.hidden = false;
  const section = { hidden: true };
  const track = { id: "home-saved-track" };
  const root = {
    ownerDocument: document,
    querySelector(selector) {
      if (selector === '[data-home-rail="saved"]') return section;
      if (selector === "#home-saved-track") return track;
      return null;
    },
  };
  let state = { user: { id: "account-A" }, navigation: "home" };
  const observers = new Set(), requests = [], posts = [], paints = [];
  const store = {
    get: () => state,
    subscribe(observer) {
      observers.add(observer);
      return () => observers.delete(observer);
    },
  };
  const client = {
    get(url, options) {
      assert.equal(url, "/api/me/saved-media");
      return new Promise(resolve => {
        requests.push({ owner: state.user?.id, options, resolve });
      });
    },
    async post(url, body) {
      posts.push({ url, body });
      const movies = url === "/api/tmdb/movies"
        ? Object.fromEntries(body.items.map(item => [item.slug, {
          title: "External TMDB title", cover_url: "/poster.svg", backdrop_url: "/wide.svg",
        }])) : {};
      const series = url === "/api/tmdb/series"
        ? Object.fromEntries(body.items.map(item => [item.base_slug, {
          title: "External TV name", cover_url: "/series-poster.svg",
        }])) : {};
      return { movies, series };
    },
  };
  const rail = createHomeSavedMedia(root, {
    client, store, getOwner: () => state.user?.id || "",
    renderHomeRail(id, entries, options) {
      paints.push({ id, entries: entries.map(entry => ({
        kind: entry.kind, item: { ...entry.item },
      })), options });
    },
  });
  return {
    document, section, requests, posts, paints, rail,
    last() { return paints.at(-1)?.entries || []; },
    setOwner(id) {
      const previous = state;
      state = { ...state, user: id ? { id } : null };
      for (const observer of observers) observer(state, previous);
    },
    respond(index, items, owner = "account-A") {
      requests[index].resolve({ owner_user_id: owner, items,
        sync: { state: "unlinked", ready: [] } });
    },
  };
}

test("Merkliste is a normal configurable Home rail immediately before Discovery", () => {
  const order = defaultHomeLayout().rail_order;
  const target = order.indexOf("discovered");
  assert.equal(order[target - 1], "saved");
  assert.equal(defaultHomeLayout().hidden_rails.includes("saved"), false);
  assert.equal(HOME_RAIL_CATALOG.find(rail => rail.id === "saved")?.title, "Deine Merkliste");
  const old = normalizeHomeLayout({
    rail_order: ["personal", "discovered", "top", "genre"],
    hidden_rails: ["top"],
  });
  assert.equal(old.rail_order.indexOf("saved"), old.rail_order.indexOf("discovered") - 1);
  assert.ok(old.hidden_rails.includes("top"), "existing layout choices remain intact");
});

test("Saved wishes keep TMDB identity, media type, descending order and deduplication", () => {
  const entries = savedHomeEntries([
    saved("movie", 7, "Film", 2), saved("tv", 7, "Serie", 3),
    saved("movie", "07", "Duplicate", 1),
    saved("movie", 8, "Newest Film", 4),
    saved("tv", 0, "Invalid", 8),
    saved("anime", 10, "Unsupported", 9),
  ]);
  assert.deepEqual(entries.map(e => [e.kind, e.item.tmdb_id, e.item.title]),
    [["movie", 8, "Newest Film"], ["series", 7, "Serie"], ["movie", 7, "Film"]]);
  assert.ok(entries.every(e => e.item.tmdb_discovery && e.item.saved_media));
  assert.equal(savedHomeEntries(null).length, 0);
  assert.equal(savedHomeEntries([saved("movie", 1, "A", 2), saved("movie", 2, "B", 1)], 1).length, 1);
});

test("Home carousel shows saved movies and TV without a Jellyfin dependency", async () => {
  const h = homeFixture();
  h.rail.mount();
  try {
    assert.equal(h.requests.length, 1);
    h.respond(0, [saved("movie", 7, "Gespeicherter Film", 2),
      saved("tv", 7, "Gespeicherte Serie", 1)]);
    await tick(); await tick();
    assert.equal(h.section.hidden, false);
    assert.deepEqual(h.last().map(entry => [entry.kind, entry.item.tmdb_id]),
      [["movie", 7], ["series", 7]]);
    assert.equal(h.posts.length, 2);
    assert.deepEqual(h.posts.map(p => p.url),
      ["/api/tmdb/movies", "/api/tmdb/series"]);
    assert.equal(h.last()[0].item.title, "Gespeicherter Film",
      "TMDB enrichment must not replace a saved user's title");
    assert.equal(h.last()[0].item.backdrop_url, "/wide.svg");

    h.document.dispatchEvent(new Event("royal:saved-media-changed"));
    assert.equal(h.requests.length, 2);
    h.respond(1, [saved("tv", 7, "Gespeicherte Serie", 1)]);
    await tick(); await tick();
    assert.deepEqual(h.last().map(entry => entry.kind), ["series"],
      "removing Merken removes only the corresponding movie card");

    h.document.dispatchEvent(new Event("royal:saved-media-changed"));
    h.respond(2, []);
    await tick();
    assert.equal(h.section.hidden, true, "empty Merkliste rail takes no Home space");
  } finally { h.rail.unmount(); }
});

test("An old profile's delayed response never reaches the new user's Home rail", async () => {
  const h = homeFixture();
  h.rail.mount();
  try {
    assert.equal(h.requests[0].owner, "account-A");
    h.setOwner("account-B");
    assert.equal(h.requests.length, 2);
    assert.equal(h.requests[0].options.signal.aborted, true);
    h.respond(1, [saved("movie", 18, "B item", 1)], "account-B");
    await tick(); await tick();
    assert.equal(h.last()[0]?.item.title, "B item");

    h.respond(0, [saved("movie", 17, "Secret A", 4)], "account-A");
    await tick();
    assert.deepEqual(h.last().map(e => e.item.title), ["B item"]);
    h.setOwner(null);
    assert.equal(h.section.hidden, true);
    assert.deepEqual(h.last(), []);
  } finally { h.rail.unmount(); }
});

test("A mismatched server owner is rejected without rendering personal items", async () => {
  const h = homeFixture();
  h.rail.mount();
  try {
    h.respond(0, [saved("movie", 66, "Other profile", 1)], "account-B");
    await tick();
    assert.equal(h.section.hidden, true);
    assert.deepEqual(h.last(), []);
  } finally { h.rail.unmount(); }
});
