import assert from "node:assert/strict";
import test from "node:test";
import { createMovieFilters } from "../web/js/features/discovery/movie-filters.js";

function filtersFor(results = []) {
  return createMovieFilters({ ownerDocument: { documentElement: { lang: "en" } }, querySelector: () => null }, {
    movieState: { results, activeGenre: "Alle Genres" }, getQueuedSlugs: () => new Set(["queued"]),
    fpResultMedia: item => item, fpResultYear: item => item.year,
    mediaJellyfinStatus: item => item.status, mediaContentLanguages: item => new Set(item.languages || []),
  });
}

test("library filters require confirmed ownership or absence", () => {
  const filters = filtersFor();
  filters.set("availability", "owned");
  assert.equal(filters.matches({ status: "owned" }), true);
  assert.equal(filters.matches({ status: "missing" }), false);
  filters.set("availability", "missing");
  assert.equal(filters.matches({ status: "missing" }), true);
  for (const status of ["owned", "unknown", "checking", "error", undefined]) {
    assert.equal(filters.matches({ status }), false);
  }
});

test("decades, rating, queue and verified audio language combine", () => {
  const filters = filtersFor();
  filters.set("period", "1990s");
  filters.set("rating", "8");
  filters.set("language", "en");
  filters.set("availability", "queued");
  const movie = { slug: "queued", year: "1994", rating: "8,4", languages: ["en", "de"] };
  assert.equal(filters.matches(movie), true);
  for (const patch of [{ year: "2000" }, { year: "" }, { rating: 7.9 }, { languages: [] }, { slug: "other" }]) {
    assert.equal(filters.matches({ ...movie, ...patch }), false);
  }
  filters.set("period", "1980s");
  assert.equal(filters.matches({ ...movie, year: "1989" }), true);
});
