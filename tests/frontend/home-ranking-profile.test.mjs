import { test } from "node:test";
import assert from "node:assert/strict";
import { createTasteRanking } from "../../web/js/features/home/taste-ranking.js";

test("late quick-dismiss response cannot replace another profile's taste", async () => {
  let owner = "A", resolve;
  const applied = [], listeners = new Map();
  const button = { dataset: {}, setAttribute() {} };
  const root = { ownerDocument: { createElement: () => button },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener: (name, callback) => listeners.set(name, callback),
    removeEventListener: name => listeners.delete(name) };
  const ranking = createTasteRanking(root, {}, {
    getOwner: () => owner, homeEntryMedia: entry => entry.item, homeEntryKey: () => "movie:one",
    tasteMetadata: () => ({}), loadDiscoveryProfile: () => ({}), homeAllEntries: () => [],
    getShuffle: () => 0, renderHome() {}, applyServerTasteProfile: profile => applied.push(profile),
    client: { post: () => new Promise(done => { resolve = done; }) },
  });
  ranking.mount();
  const art = { appendChild() {} };
  const card = { dataset: {}, querySelector: selector => selector === ".home-card-art" ? art : null };
  ranking.enhance(card, { kind: "movie", item: { title: "One" } });
  const pending = listeners.get("click")({ target: { closest: () => button }, preventDefault() {}, stopPropagation() {} });
  owner = "B";
  resolve({ profile: { owner: "A" } });
  await pending;
  assert.deepEqual(applied, []);
  ranking.unmount();
});
