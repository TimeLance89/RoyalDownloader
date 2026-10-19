import { test } from "node:test";
import assert from "node:assert/strict";
import { createHomeLanes } from "../../web/js/features/home/lanes.js";

function fixture(profile, items, preferred = []) {
  const asEntry = item => ({ kind: "movie", item });
  const key = entry => `${entry.kind}:${entry.item.slug}`;
  const getData = () => ({
    newMovies: items, topMovies: [], cinemaMovies: [], discoveryMovies: [],
    trendingSeries: [], newSeries: [], discoverySeries: [], personalDiscoveries: [],
  });
  return createHomeLanes({ querySelector: () => null }, {
    allowedHomeEntries: entries => entries,
    uniqueHomeEntries: entries => [...new Map(entries.map(entry => [key(entry), entry])).values()],
    homeMovieEntry: asEntry, homeSeriesEntry: item => ({ kind: "series", item }),
    interleaveHomeEntries: (a, b) => [...a, ...b], loadDiscoveryProfile: () => profile,
    stableDailyOrder: entries => entries, homeEntryMedia: entry => entry.item, homeEntryKey: key,
    homeContentKeys: entry => [key(entry)], homeTopEntries: () => [],
    stableDiscoveryHash: () => 0, localDateKey: () => "2026-10-19",
    homeHeroCandidates: () => [], homePersonalizedEntries: () => preferred.map(asEntry),
    currentHomeLayout: () => ({ rail_order: [], hidden_rails: [] }),
    mediaJellyfinStatus: () => "", getJellyfinStatus: () => "", getData,
    discoveryV2ExposurePenalty: () => 0,
  });
}

test("Explore's fallback never reintroduces explicitly rejected genres", () => {
  const profile = { genres: { Action: 9, Horror: -15 }, recent: [] };
  const items = [
    { slug: "a", genres: ["Action"], rating: 7.8 },
    { slug: "h", genres: ["Horror"], rating: 8.5 },
    { slug: "d", genres: ["Drama"], rating: 7.2 },
  ];
  const result = fixture(profile, items).homeExploreEntries();
  assert.equal(result[0].item.slug, "d");
  assert.ok(!result.some(entry => entry.item.slug === "h"));
});

test("Hidden gems prefer genuine personal matches over marginal ratings", () => {
  const profile = { genres: { Mystery: 10 }, recent: [] };
  const liked = { slug: "liked", genres: ["Mystery"], rating: 7.3 };
  const generic = { slug: "generic", genres: ["Comedy"], rating: 8.0 };
  const result = fixture(profile, [generic, liked], [liked]).homeGemEntries();
  assert.equal(result[0].item.slug, "liked");
});
