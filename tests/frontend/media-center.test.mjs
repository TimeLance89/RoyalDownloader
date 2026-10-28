import assert from "node:assert/strict";
import test from "node:test";
import { createMovieFilters } from "../../web/js/features/discovery/movie-filters.js";
import { setMediaCenter } from "../../web/js/shared/media-center.js";

for (const provider of ["jellyfin", "plex"]) {
  test(`${provider}: existing and missing filters keep their meaning`, () => {
    setMediaCenter(provider);
    const entries = [
      { slug: "owned", jellyfin_status: "owned", year: "2026" },
      { slug: "missing", jellyfin_status: "missing", year: "2026" },
    ];
    const filters = createMovieFilters({ querySelector: () => null }, {
      movieState: { results: entries, activeGenre: "Alle Genres" }, getQueuedSlugs: () => new Set(),
      fpResultMedia: item => item, fpResultYear: item => item.year,
      mediaJellyfinStatus: item => item.jellyfin_status, mediaContentLanguages: () => new Set(["de"]),
    });
    filters.set("availability", "owned");
    assert.deepEqual(filters.results().map(item => item.slug), ["owned"]);
    assert.deepEqual(filters.labels(), [`In ${provider === "plex" ? "Plex" : "Jellyfin"}`]);
    filters.set("availability", "missing");
    assert.deepEqual(filters.results().map(item => item.slug), ["missing"]);
  });
}
