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
  assert.deepEqual(highlights(credits), [credits[2]], "unreleased titles and other departments never lead an acting profile");
  assert.equal(filmCandidate(credits[0], statuses, new Set()), false);
  assert.equal(filmCandidate({ ...credits[1], media_type: "movie" }, statuses, new Set()), false);
  assert.equal(filmCandidate({ ...credits[2], slug: "tmdb:2" }, statuses, new Set(["tmdb:2"])), false);
});

test("known for favors established acting works over popular self appearances", () => {
  const work = (id, title, extra = {}) => ({ tmdb_id: id, media_type: "movie", title, cover_url: "poster", departments: ["Acting"], characters: ["Character"], ...extra });
  const forrest = work(1, "Forrest Gump", { vote_count: 28000, popularity: 20 });
  const toy = work(2, "Toy Story", { vote_count: 21000, characters: ["Woody (voice)"] });
  const simpsons = work(3, "The Simpsons", { media_type: "tv", vote_count: 10000, characters: ["Self (voice)"] });
  const talk = work(4, "Late Night", { media_type: "tv", popularity: 10000, vote_count: 100, characters: ["Self"], roles: ["Self", "Producer"] });
  const archive = work(5, "Archive", { vote_count: 50000, characters: ["Tom (archive footage)"] });
  const production = work(6, "Produced film", { vote_count: 100000, departments: ["Production"] });
  const upcoming = work(7, "Future", { release_date: "2099-01-01", vote_count: 100000 });
  assert.deepEqual(highlights([talk, simpsons, archive, production, upcoming, toy, forrest, forrest]), [forrest, toy]);
  assert.deepEqual(highlights([talk, simpsons]), [simpsons, talk], "presenters retain self credits when those are their body of work");
});

test("known for respects directors, TV actors and distinct movie/TV identities", () => {
  const work = (id, media_type, title, departments, votes) => ({ tmdb_id: id, media_type, title, departments, vote_count: votes, cover_url: "poster" });
  const directed = work(1, "movie", "Directed", ["Directing"], 100);
  const series = work(1, "tv", "Defining series", ["Acting"], 20000);
  const movie = work(1, "movie", "Acted", ["Acting"], 10000);
  assert.deepEqual(highlights([directed, movie, series], "Directing"), [directed]);
  assert.deepEqual(highlights([movie, series]), [series, movie], "TV is not demoted and equal numeric IDs stay separate");
  assert.deepEqual(highlights([{ ...movie, cover_url: "" }]), []);
});
