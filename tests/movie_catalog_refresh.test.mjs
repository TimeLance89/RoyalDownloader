import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../web/catalog-runtime.js", import.meta.url), "utf8");

function runtime(fetch) {
  const timers = [];
  const applied = [];
  const context = vm.createContext({
    console, Date, Map, Set,
    document: { hidden: false },
    state: { tab: "filme", fp: {
      category: "new", page: 1, requestSeq: 1, lastCatalogRefreshAt: 0,
      results: [], lastPageFull: true,
    } },
    api: { movies: fetch },
    setTimeout: (callback, delay) => { timers.push({ callback, delay }); return timers.length; },
    clearTimeout: () => {},
    applyFpResults: (data) => applied.push(data),
    mergeCatalogItems: (incoming, current) => [
      ...incoming, ...current.filter((item) => !incoming.some((other) => other.slug === item.slug)),
    ],
  });
  vm.runInContext(source, context);
  return { context, timers, applied, settle: () => vm.runInContext("fpCatalogRefreshPromise", context) };
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
