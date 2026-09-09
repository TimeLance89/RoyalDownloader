import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../web/screens/series.js", import.meta.url), "utf8");
function summary(result, cache = {}) {
  const context = vm.createContext({ state: { series: { cache } } });
  vm.runInContext(source, context);
  return context.seriesCardSeasonSummary(result);
}

test("unknown series structure offers navigation without invented counts", () => {
  assert.equal(summary({ base_slug: "show" }), "Staffeln & Episoden öffnen");
});

test("loaded structure counts regular seasons and episodes, excluding specials", () => {
  assert.equal(summary({ base_slug: "show" }, { show: { seasons: [
    { season: 0, episodes: [{}, {}] },
    { season: 1, episodes: [{}, {}] },
    { season: 2, episodes: [{}] },
  ] } }), "2 Staffeln · 3 Episoden");
});

test("singular counts and unknown episode lists are labelled accurately", () => {
  assert.equal(summary({ seasons: [{ season: 1, episodes: [{}] }] }), "1 Staffel · 1 Episode");
  assert.equal(summary({ seasons: [{ season: 1 }] }), "1 Staffel");
});
