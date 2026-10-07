import assert from "node:assert/strict";
import test from "node:test";
import { filterCredits } from "../../web/js/features/people/index.js";

test("filmography preserves film and TV identities and applies independent role and title filters", () => {
  const credits = [
    { tmdb_id: 7, media_type: "movie", title: "Remake", original_title: "Original", departments: ["Acting"], release_date: "2023-01-01", popularity: 5 },
    { tmdb_id: 7, media_type: "tv", title: "Series", departments: ["Acting"], release_date: "1999-01-01", popularity: 9 },
    { tmdb_id: 8, media_type: "movie", title: "Production", departments: ["Production"], release_date: "2025-01-01", popularity: 10 },
  ];
  assert.equal(filterCredits(credits).length, 2);
  assert.deepEqual(filterCredits(credits, { type: "tv" }).map(item => item.title), ["Series"]);
  assert.deepEqual(filterCredits(credits, { query: "original" }).map(item => item.title), ["Remake"]);
  assert.deepEqual(filterCredits(credits, { role: "all", sort: "newest" }).map(item => item.title), ["Production", "Remake", "Series"]);
  assert.equal(credits[0].title, "Remake", "sorting never mutates the stored filmography");
});
