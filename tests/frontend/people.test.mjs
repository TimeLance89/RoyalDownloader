import assert from "node:assert/strict";
import test from "node:test";
import { filterCredits } from "../../web/js/features/people/index.js";
import { creditKey, filmCandidate, highlights } from "../../web/js/features/people/model.js";

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

test("advanced filters distinguish roles, release dates and ambiguous library states", () => {
  const credits = [
    { tmdb_id: 1, media_type: "movie", title: "Published", year: "2020", release_date: "2020-02-01", departments: ["Directing"], roles: ["Director"], rating: 7, vote_count: 100, cover_url: "poster" },
    { tmdb_id: 1, media_type: "tv", title: "Upcoming", year: "2099", release_date: "2099-02-01", departments: ["Acting"], rating: 10, vote_count: 1, cover_url: "poster" },
    { tmdb_id: 2, media_type: "movie", title: "No date", year: "", release_date: "", departments: ["Acting"], rating: 8, vote_count: 100, cover_url: "poster" },
  ];
  const statuses = new Map([[creditKey(credits[0]), "owned"], [creditKey(credits[1]), "blocked"]]);
  assert.deepEqual(filterCredits(credits, { role: "Directing", query: "director", year: "2020", release: "released" }), [credits[0]]);
  assert.deepEqual(filterCredits(credits, { role: "all", library: "unavailable" }, statuses), [credits[1]]);
  assert.deepEqual(filterCredits(credits, { role: "all", library: "unchecked" }, statuses), [credits[2]]);
  assert.equal(filterCredits(credits, { role: "all", sort: "newest" }).at(-1), credits[2]);
  assert.equal(filterCredits(credits, { role: "all", sort: "oldest" }).at(-1), credits[2]);
  assert.deepEqual(filterCredits(credits, { role: "all", sort: "rating" }), [credits[2], credits[0], credits[1]], "a single vote cannot outrank established ratings");
  assert.deepEqual(highlights(credits), [credits[2], credits[0]], "unreleased titles never lead the profile");
  assert.equal(filmCandidate(credits[0], statuses, new Set()), false);
  assert.equal(filmCandidate({ ...credits[1], media_type: "movie" }, statuses, new Set()), false);
  assert.equal(filmCandidate({ ...credits[2], slug: "tmdb:2" }, statuses, new Set(["tmdb:2"])), false);
});
