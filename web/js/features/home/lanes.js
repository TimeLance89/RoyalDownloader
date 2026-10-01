export function createHomeLanes(root, {
  allowedHomeEntries, uniqueHomeEntries, homeMovieEntry, homeSeriesEntry, interleaveHomeEntries,
  loadDiscoveryProfile, stableDailyOrder, homeEntryMedia, homeEntryKey, homeTopEntries,
  stableDiscoveryHash, localDateKey, homeHeroCandidates, homePersonalizedEntries, currentHomeLayout,
  mediaJellyfinStatus, getJellyfinStatus, getData, discoveryV2ExposurePenalty,
}) {
  function rotatingOrder(entries, lane) {
    return stableDailyOrder(entries, lane)
      .map((entry, index) => ({
        entry, index, penalty: Number(discoveryV2ExposurePenalty?.(entry, lane) || 0),
      }))
      .sort((left, right) => left.penalty - right.penalty || left.index - right.index)
      .map(({ entry }) => entry);
  }
  function homeAllEntries() {
    return allowedHomeEntries(uniqueHomeEntries([
      ...getData().topMovies.map(homeMovieEntry),
      ...getData().newMovies.map(homeMovieEntry),
      ...(getData().cinemaMovies || []).map(homeMovieEntry),
      ...getData().discoveryMovies.map(homeMovieEntry),
      ...getData().trendingSeries.map(homeSeriesEntry),
      ...getData().newSeries.map(homeSeriesEntry),
      ...getData().discoverySeries.map(homeSeriesEntry),
    ]));
  }

  function homeNewEntries() {
    return allowedHomeEntries(interleaveHomeEntries(
      getData().newMovies.map(homeMovieEntry),
      getData().newSeries.map(homeSeriesEntry),
      24,
    ));
  }

  function homePopularSeriesEntries() {
    const preferred = getData().trendingSeries.length
      ? getData().trendingSeries
      : uniqueHomeEntries([
        ...getData().newSeries.map(homeSeriesEntry),
        ...getData().discoverySeries.map(homeSeriesEntry),
      ]).map((entry) => entry.item);
    const title = root.querySelector("#home-series-title");
    if (title) {
      title.textContent = getData().trendingSeries.length
        ? "Serien, die gerade alle sehen"
        : "Serien aus deinen aktiven Quellen";
    }
    return allowedHomeEntries(preferred.map(homeSeriesEntry));
  }

  function favoriteDiscoveryGenre(profile = loadDiscoveryProfile()) {
    return Object.entries(profile.genres)
      .filter(([, score]) => Number(score) > 0.25)
      .sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0], "de"))[0]?.[0] || "";
  }

  function homeGenreEntries() {
    const profile = loadDiscoveryProfile();
    const favorite = favoriteDiscoveryGenre(profile);
    const pool = homeAllEntries();
    if (!favorite) return rotatingOrder(pool, "genre").slice(0, 24);
    const matching = pool.filter((entry) =>
      (homeEntryMedia(entry).genres || []).some((genre) =>
        String(genre).localeCompare(favorite, "de", { sensitivity: "base" }) === 0));
    const matchingKeys = new Set(matching.map(homeEntryKey));
    const adjacent = pool.filter((entry) => !matchingKeys.has(homeEntryKey(entry)));
    const preferred = rotatingOrder(matching, "genre");
    const alternatives = rotatingOrder(adjacent, "genre");
    const result = [];
    while (result.length < 24 && (preferred.length || alternatives.length)) {
      if (preferred.length) result.push(preferred.shift());
      if (preferred.length && result.length < 24) result.push(preferred.shift());
      if (alternatives.length && result.length < 24) result.push(alternatives.shift());
    }
    return result;
  }

  function homeExploreCandidatePool() {
    const profile = loadDiscoveryProfile();
    const avoidedGenres = new Set(Object.entries(profile.genres)
      .filter(([, score]) => Number(score) > 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, 2)
      .map(([genre]) => genre.toLocaleLowerCase()));
    const recent = new Set(profile.recent.slice(0, 30).map((event) => event.key));
    const pool = homeAllEntries().filter((entry) => {
      if (recent.has(homeEntryKey(entry))) return false;
      const genres = (homeEntryMedia(entry).genres || []).map((genre) => String(genre).toLocaleLowerCase());
      return !genres.some((genre) => avoidedGenres.has(genre));
    });
    return rotatingOrder(pool.length >= 8 ? pool : homeAllEntries(), "explore");
  }

  // Keep the original candidates eligible for metadata hydration even before
  // they have a backdrop. The visible Explore rail itself publishes only
  // finished 16:9 artwork, so portrait posters/initial placeholders never
  // become the final presentation.
  function homeExploreArtworkCandidates() {
    return homeExploreCandidatePool().slice(0, 24);
  }

  function homeExploreEntries() {
    return homeExploreCandidatePool()
      .filter((entry) => Boolean(homeEntryMedia(entry).backdrop_url))
      .slice(0, 24);
  }

  function homeGemEntries() {
    const topKeys = new Set(homeTopEntries().map(homeEntryKey));
    const candidates = homeAllEntries()
      .filter((entry) => !topKeys.has(homeEntryKey(entry)))
      .map((entry) => ({
        entry,
        rating: Number(homeEntryMedia(entry).rating || 0),
        penalty: Number(discoveryV2ExposurePenalty?.(entry, "gems") || 0),
        daily: stableDiscoveryHash(`${localDateKey()}|gems|${homeEntryKey(entry)}`) / 4294967295 * 2,
      }))
      .filter(({ rating }) => !rating || rating >= 6.4)
      .sort((a, b) => (b.rating - b.penalty * 0.35 + b.daily)
        - (a.rating - a.penalty * 0.35 + a.daily))
      .map(({ entry }) => entry);
    return candidates.slice(0, 24);
  }

  function takeDistinctHomeLane(entries, seen, limit, minimum = 4) {
    const unique = uniqueHomeEntries(entries);
    const selected = unique.filter((entry) => !seen.has(homeEntryKey(entry))).slice(0, limit);
    if (selected.length < minimum) {
      const selectedKeys = new Set(selected.map(homeEntryKey));
      selected.push(...unique
        .filter((entry) => !selectedKeys.has(homeEntryKey(entry)))
        .slice(0, minimum - selected.length));
    }
    selected.forEach((entry) => seen.add(homeEntryKey(entry)));
    return selected;
  }

  function homeDiscoveryLanes() {
    const top = homeTopEntries();
    const heroKeys = new Set(homeHeroCandidates().map(homeEntryKey));
    const seen = new Set([...heroKeys, ...top.map(homeEntryKey)]);
    return {
      personal: takeDistinctHomeLane(homePersonalizedEntries(), seen, 7, 7),
      explore: takeDistinctHomeLane(homeExploreEntries(), seen, 16),
      series: takeDistinctHomeLane(rotatingOrder(homePopularSeriesEntries(), "series"), seen, 16),
      top,
      genre: takeDistinctHomeLane(homeGenreEntries(), seen, 16, 16),
      gems: takeDistinctHomeLane(homeGemEntries(), seen, 16),
      // "Neu hinzugefügt" ist eine chronologische Katalogreihe, keine Discovery-Reihe.
      // Titel dürfen hier auch vorkommen, wenn sie bereits weiter oben empfohlen wurden.
      fresh: homeNewEntries(),
      new_movies: uniqueHomeEntries(getData().newMovies.map(homeMovieEntry)).slice(0, 24),
      new_series: uniqueHomeEntries(getData().newSeries.map(homeSeriesEntry)).slice(0, 24),
      high_rated: homeRatedEntries(),
      movies: stableDailyOrder(uniqueHomeEntries([
        ...getData().newMovies, ...getData().topMovies, ...getData().discoveryMovies,
      ].map(homeMovieEntry)), "movie-night").slice(0, 24),
      library: homeLibraryEntries(),
    };
  }

  function homeRatedEntries() {
    return rotatingOrder(uniqueHomeEntries(homeAllEntries())
      .filter((entry) => Number(homeEntryMedia(entry).rating || 0) >= 7), "high-rated")
      .slice(0, 24);
  }

  function homeLibraryEntries() {
    return uniqueHomeEntries(homeAllEntries())
      .filter((entry) => getJellyfinStatus(homeEntryKey(entry)) === "owned"
        || mediaJellyfinStatus(homeEntryMedia(entry)) === "owned")
      .slice(0, 24);
  }

  function homeArtworkEntriesInLayout() {
    const lanes = homeDiscoveryLanes();
    const layout = currentHomeLayout();
    const hidden = new Set(layout.hidden_rails);
    const exploreVisible = layout.rail_order.includes("explore") && !hidden.has("explore");
    return uniqueHomeEntries([
      ...layout.rail_order
        .filter((railId) => !hidden.has(railId))
        .flatMap((railId) => lanes[railId] || []),
      ...(exploreVisible ? homeExploreArtworkCandidates() : []),
      ...homeHeroCandidates(),
    ]);
  }

  return { homeAllEntries, homeNewEntries, homePopularSeriesEntries, favoriteDiscoveryGenre, homeGenreEntries, homeExploreEntries, homeExploreArtworkCandidates, homeGemEntries, takeDistinctHomeLane, homeDiscoveryLanes, homeRatedEntries, homeLibraryEntries, homeArtworkEntriesInLayout };
}
