import test from "node:test";
import assert from "node:assert/strict";
import { withHomeRender, memoHomeRender, invalidateHomeRender } from "../../web/js/features/home/render-pass.js";

test("Home snapshots are shared in nested paints, invalidated on writes and discarded after errors", () => {
  const key = Symbol("profile");
  let reads = 0;
  const read = () => memoHomeRender(key, () => ++reads);
  withHomeRender(() => {
    assert.equal(read(), 1);
    withHomeRender(() => assert.equal(read(), 1));
    invalidateHomeRender(key);
    assert.equal(read(), 2);
  });
  assert.equal(withHomeRender(read), 3);
  assert.throws(() => withHomeRender(() => { assert.equal(read(), 4); throw new Error("paint failed"); }));
  assert.equal(withHomeRender(read), 5);
  assert.equal(read(), 6);
  assert.equal(read(), 7);
});
