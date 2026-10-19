import { test } from "node:test";
import assert from "node:assert/strict";
import { createHomeExposureVisibility } from "../../web/js/features/home/exposure-visibility.js";
import { createDiscoveryPolicy } from "../../web/js/features/home/discovery-policy.js";

function fixture() {
  const observed = new Set();
  const observers = [];
  const callbacks = new Map();
  let now = 0, nextId = 0, owner = "user-a", hidden = false, day = "2026-10-19";
  const events = [];
  class MockObserver {
    constructor(callback, options) {
      this.callback = callback;
      this.options = options;
      observers.push(this);
    }
    observe(node) { observed.add(node); }
    unobserve(node) { observed.delete(node); }
    disconnect() { observed.clear(); }
    emit(node, ratio) {
      this.callback([{ target: node, isIntersecting: ratio > 0, intersectionRatio: ratio }]);
    }
  }
  function element(key, kind = "movie") {
    return { dataset: { kind, key }, isConnected: true,
      classList: { contains: token => token === "home-card" } };
  }
  const a = element("tmdb:12"), b = element("tmdb:13"), hero = element("hero");
  const track = { children: [a, b] };
  const docListeners = new Map();
  const document = { get visibilityState() { return hidden ? "hidden" : "visible"; },
    defaultView: { IntersectionObserver: MockObserver },
    addEventListener: (event, listener) => docListeners.set(event, listener),
    removeEventListener: event => docListeners.delete(event) };
  const root = { ownerDocument: document, isConnected: true, hidden: false,
    getAttribute: () => null,
    querySelector: selector => selector === "#home-discovered-track" ? track : selector === "#home-hero" ? hero : null };
  const visibility = createHomeExposureVisibility(root, {
    record: (lane, entries) => events.push([owner, lane, ...entries.map(x => x.item.tmdb_id)]),
    logicalKey: entry => entry.kind + ":tmdb:" + entry.item.tmdb_id,
    getOwner: () => owner, getDay: () => day,
    Observer: MockObserver, schedule(callback, delay) { const id = ++nextId; callbacks.set(id, { callback, at: now + delay }); return id; },
    cancel: id => callbacks.delete(id), dwellMs: 1500,
  });
  const entries = [12, 13].map(id => ({ kind: "movie", item: { slug: "tmdb:" + id, tmdb_id: id } }));
  return { a, b, hero, track, entries, observers, events, visibility, root,
    see(el, fraction) { observers.at(-1).emit(el, fraction); },
    tick(ms) { now += ms; for (const [id, t] of [...callbacks]) if (t.at <= now) { callbacks.delete(id); t.callback(); } },
    switchOwner(next) { owner = next; },
    setHidden(value) { hidden = value; docListeners.get("visibilitychange")?.(); },
    setDay(value) { day = value; },
  };
}

test("unseen and briefly exposed cards are never counted", () => {
  const f = fixture(); f.visibility.mount(); f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.tick(9000); assert.deepEqual(f.events, []);
  f.see(f.a, 0.7); f.tick(1499); assert.deepEqual(f.events, []);
  f.see(f.a, 0.1); f.tick(6000); assert.deepEqual(f.events, []);
  f.visibility.unmount();
});

test("one sustained genuine viewport exposure records once per user, day and lane", () => {
  const f = fixture(); f.visibility.mount(); f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.a, 0.8); f.tick(1500); assert.deepEqual(f.events, [["user-a", "discovered", 12]]);
  f.see(f.a, 0); f.see(f.a, 1); f.tick(1700);
  assert.equal(f.events.length, 1);
  f.see(f.b, 1); f.tick(1500); assert.equal(f.events.length, 2);
  f.visibility.unmount();
});

test("background tab and account switch invalidate pending impressions", () => {
  const f = fixture(); f.visibility.mount(); f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.a, 1); f.setHidden(true); f.tick(2000); assert.deepEqual(f.events, []);
  f.setHidden(false); f.see(f.a, 1); f.switchOwner("user-b"); f.tick(2000);
  assert.deepEqual(f.events, []);
  f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.a, 0.9); f.tick(1500); assert.deepEqual(f.events, [["user-b", "discovered", 12]]);
  f.visibility.unmount();
});

test("unmount cancels pending work and removes old observers", () => {
  const f = fixture(); f.visibility.mount(); f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.b, 0.85); f.visibility.unmount(); f.tick(2500);
  assert.deepEqual(f.events, []);
});

test("crossing another visible threshold preserves continuous dwell", () => {
  const f = fixture(); f.visibility.mount(); f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.a, 0.65); f.tick(1000); f.see(f.a, 0.9); f.tick(500);
  assert.deepEqual(f.events, [["user-a", "discovered", 12]]);
  f.visibility.unmount();
});

test("remount and return to a previously viewed title do not count twice", () => {
  const f = fixture(); f.visibility.mount(); f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.a, 1); f.tick(1500); f.visibility.unmount();
  f.visibility.mount(); f.see(f.a, 1); f.tick(1500);
  assert.equal(f.events.length, 1);
  f.visibility.unmount();
});

test("hero first rendered before mount is eventually registered, and rotations replace its identity", () => {
  const f = fixture(); f.visibility.syncHero({ kind: "movie", media: { tmdb_id: 41 } });
  f.visibility.mount(); f.see(f.hero, 0.95); f.tick(1500);
  assert.deepEqual(f.events, [["user-a", "hero", 41]]);
  f.visibility.syncHero({ kind: "movie", media: { tmdb_id: 42 } });
  f.see(f.hero, 0.95); f.tick(1500);
  assert.deepEqual(f.events, [["user-a", "hero", 41], ["user-a", "hero", 42]]);
  f.visibility.unmount();
});

test("carousel loop clones count an already-seen title only once", () => {
  const f = fixture();
  const clone = { ...f.a, dataset: { ...f.a.dataset } };
  f.track.children.push(clone);
  f.visibility.mount();
  f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.a, 1); f.see(clone, 1); f.tick(1500);
  assert.deepEqual(f.events, [["user-a", "discovered", 12]]);
  f.visibility.unmount();
});

test("shuffle visibility stays scoped to the current profile and day", () => {
  const f = fixture(); f.visibility.mount(); f.visibility.syncRail("home-discovered-track", "discovered", f.entries);
  f.see(f.a, 1); f.tick(1500);
  assert.equal(f.visibility.hasSeen("movie:tmdb:12"), true);
  f.switchOwner("user-b");
  assert.equal(f.visibility.hasSeen("movie:tmdb:12"), false);
  f.switchOwner("user-a"); f.setDay("2026-10-20");
  assert.equal(f.visibility.hasSeen("movie:tmdb:12"), false);
  f.visibility.unmount();
});

test("several rails cannot multiply a title's daily repetition penalty", () => {
  const history = { version: 2, days: { "2026-10-18": { lanes: {
    personal: ["movie:tmdb:12"], explore: ["movie:tmdb:12"], hero: ["movie:tmdb:12"],
  } } } };
  const policy = createDiscoveryPolicy({ storage: { getItem: () => JSON.stringify(history) },
    personalStorageKey: key => key, homeEntryMedia: entry => entry.item,
    localDateKey: () => "2026-10-19" });
  assert.equal(policy.discoveryV2ExposurePenalty({ kind: "movie", item: { tmdb_id: 12 } }, "personal"), 16);
});
