import { test } from "node:test";
import assert from "node:assert/strict";
import { homeTasteContext } from "../../web/js/features/home/taste-context.js";

test("Home respects medium context, bounds short-term curiosity and preserves dislikes", () => {
  const profile = { dimensions: { genres: { Horror: 12, Drama: 12, Comedy: -10 } },
    home_preferences: { short_term: { genres: { Drama: 100, Comedy: 100 } },
      by_media_type: { movie: { genres: { Horror: 12 } }, series: { genres: { Drama: 12 } } } } };
  const movie = homeTasteContext(profile, "movie").dimensions.genres;
  const series = homeTasteContext(profile, "series").dimensions.genres;
  assert.ok(movie.Horror > movie.Drama);
  assert.ok(series.Drama > series.Horror);
  assert.equal(movie.Comedy, -10);
  assert.equal(series.Drama, 13.05);
  assert.equal(profile.dimensions.genres.Drama, 12);
});

test("Legacy profiles retain the same Home dimensions", () => {
  const profile = { dimensions: { genres: { Horror: 20 } } };
  assert.deepEqual(homeTasteContext(profile, "movie"), profile);
});
