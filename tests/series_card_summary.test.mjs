import assert from "node:assert/strict";
import { createSeriesPresentation } from "../web/js/features/discovery/series-presentation.js";
import test from "node:test";

function summary(result, cache = {}) {
  return createSeriesPresentation({}, {}, { seriesState: { cache } }).seriesCardSeasonSummary(result);
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
