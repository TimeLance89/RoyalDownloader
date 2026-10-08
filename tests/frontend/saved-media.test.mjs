import assert from "node:assert/strict";
import test from "node:test";
import { createSavedMediaAction } from "../../web/js/features/media-details/saved-media.js";

const payload = saved => ({ items: saved ? [{ media_type: "movie", tmdb_id: 7 }] : [], sync: { state: "pending", ready: [] } });
function controls() {
  const button = new EventTarget(), attributes = {};
  button.setAttribute = (key, value) => { attributes[key] = value; };
  return { button, note: {}, attributes };
}

test("provider and metadata updates preserve the saved state and use the latest title", async () => {
  const { button, note, attributes } = controls();
  let reads = 0;
  const writes = [];
  const action = createSavedMediaAction(button, note, { client: {
    get: async () => { reads++; return payload(true); },
    post: async (_url, body) => { writes.push(body); return payload(false); },
  } });
  try {
    action.show({ tmdb_id: 7, title: "Initial title" }, "movie");
    await Promise.resolve();
    for (const title of ["Metadata title", "Resolved title"]) {
      action.show({ tmdb_id: 7, title }, "movie");
      assert.equal(button.disabled, false);
      assert.equal(attributes["aria-pressed"], "true");
      assert.equal(button.textContent, "Gemerkt ✓");
    }
    assert.equal(reads, 1);
    button.dispatchEvent(new Event("click"));
    await Promise.resolve();
    assert.deepEqual(writes, [{ media_type: "movie", tmdb_id: 7, title: "Resolved title", saved: false }]);
    assert.equal(attributes["aria-pressed"], "false");
  } finally { action.close(); }
});

test("content updates keep an in-flight status read alive", async () => {
  const { button, note, attributes } = controls();
  const reads = [];
  const action = createSavedMediaAction(button, note, { client: {
    get: (_url, options) => new Promise(resolve => { reads.push({ resolve, ...options }); }),
  } });
  try {
    action.show({ tmdb_id: 7, title: "Initial" }, "movie");
    action.show({ tmdb_id: 7, title: "With hosters" }, "movie");
    assert.equal(reads.length, 1);
    assert.equal(reads[0].signal.aborted, false);
    assert.equal(button.disabled, true);
    reads[0].resolve(payload(true));
    await Promise.resolve();
    assert.equal(attributes["aria-pressed"], "true");
    assert.equal(button.disabled, false);
  } finally { action.close(); }
});

test("a detail update cannot cancel a pending save or add another click handler", async () => {
  const { button, note, attributes } = controls();
  const writes = [];
  const action = createSavedMediaAction(button, note, { client: {
    get: async () => payload(false),
    post: (_url, body, options) => new Promise(resolve => { writes.push({ body, resolve, ...options }); }),
  } });
  try {
    action.show({ tmdb_id: 7, title: "Initial" }, "movie");
    await Promise.resolve();
    button.dispatchEvent(new Event("click"));
    action.show({ tmdb_id: 7, title: "Resolved" }, "movie");
    assert.equal(button.disabled, true);
    assert.equal(writes[0].signal.aborted, false);
    button.dispatchEvent(new Event("click"));
    assert.equal(writes.length, 1);
    writes[0].resolve(payload(true));
    await Promise.resolve();
    assert.equal(button.disabled, false);
    assert.equal(attributes["aria-pressed"], "true");
  } finally { action.close(); }
});

test("closing, another profile, and another media type require a new personal status", async () => {
  const { button, note, attributes } = controls();
  let reads = 0, saved = true;
  const action = createSavedMediaAction(button, note, { client: {
    get: async () => { reads++; return payload(saved); },
  } });
  try {
    action.show({ tmdb_id: 7 }, "movie");
    await Promise.resolve();
    assert.equal(attributes["aria-pressed"], "true");
    action.close(); saved = false;
    action.show({ tmdb_id: 7 }, "movie");
    await Promise.resolve();
    assert.equal(reads, 2);
    assert.equal(attributes["aria-pressed"], "false");
    saved = true;
    action.show({ tmdb_id: 7 }, "tv");
    await Promise.resolve();
    assert.equal(reads, 3);
    assert.equal(attributes["aria-pressed"], "false");
  } finally { action.close(); }
});

test("a late status poll cannot undo a successful personal save", async context => {
  context.mock.timers.enable({ apis: ["setInterval"] });
  const button = new EventTarget();
  button.setAttribute = () => {};
  const note = {};
  const payload = saved => ({ items: saved ? [{ media_type: "movie", tmdb_id: 7 }] : [], sync: { state: "pending", ready: [] } });
  let resolvePoll, reads = 0;
  const client = {
    get: () => ++reads === 1 ? Promise.resolve(payload(false)) : new Promise(resolve => { resolvePoll = resolve; }),
    post: () => Promise.resolve(payload(true)),
  };
  const action = createSavedMediaAction(button, note, { client });
  try {
    action.show({ tmdb_id: 7, title: "Film" }, "movie");
    await Promise.resolve();
    assert.equal(button.disabled, false);
    context.mock.timers.tick(15_000);
    button.dispatchEvent(new Event("click"));
    await Promise.resolve();
    assert.equal(button.textContent, "Gemerkt ✓");
    resolvePoll(payload(false));
    await Promise.resolve();
    assert.equal(button.textContent, "Gemerkt ✓");
    assert.match(note.textContent, /sobald verfügbar/);
  } finally { action.close(); }
});
