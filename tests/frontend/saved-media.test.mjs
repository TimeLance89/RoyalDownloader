import assert from "node:assert/strict";
import test from "node:test";
import { createSavedMediaAction } from "../../web/js/features/media-details/saved-media.js";

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
