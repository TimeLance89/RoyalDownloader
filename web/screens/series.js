// ── Serien-Tab ─────────────────────────────────────────────────────────────
function buildAlphaBar() {
  const bar = document.getElementById("series-alpha-bar");
  const letters = ["0-9", ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))];
  for (const l of letters) {
    const btn = document.createElement("button");
    btn.textContent = l;
    btn.addEventListener("click", () => seriesBrowse(`alpha:${l}`, 1));
    bar.appendChild(btn);
  }
}

function firstEpisodeSlug(series) {
  for (const s of series.seasons) if (s.episodes.length) return s.episodes[0].slug;
  return "";
}

function seriesEpisodes(series = state.series.current) {
  return series?.seasons?.flatMap((season) => season.episodes || []) || [];
}

function isEpisodeQueued(episode) {
  return Boolean(episode?.queued || state.queuedSlugs.has(episode?.slug));
}

function isEpisodeSelectable(episode) {
  return Boolean(
    episode
    && state.series.current?.availability_pending !== true
    && state.series.current?.jellyfin_pending !== true
    && state.series.current?.jellyfin_available !== false
    && !episode.downloaded
    && !episode.in_jellyfin
    && !episode.unreleased
    && !isEpisodeQueued(episode)
  );
}

function syncSeriesQueueFlags(series = null) {
  const candidates = series
    ? [series]
    : [state.series.current, ...Object.values(state.series.cache)];
  const visited = new Set();
  for (const candidate of candidates) {
    if (!candidate || visited.has(candidate)) continue;
    visited.add(candidate);
    if (state.queue.loaded) {
      for (const episode of seriesEpisodes(candidate)) {
        episode.queued = state.queuedSlugs.has(episode.slug);
      }
    }
  }
  if (!series || series === state.series.current) {
    pruneSeriesEpisodeSelection();
    renderSeriesTiles();
  }
}

function pruneSeriesEpisodeSelection() {
  const selectableSlugs = new Set(
    seriesEpisodes().filter(isEpisodeSelectable).map((episode) => episode.slug),
  );
  state.series.epPicked = new Set(
    [...state.series.epPicked].filter((slug) => selectableSlugs.has(slug)),
  );
}

function findCurrentEpisode(slug) {
  return seriesEpisodes().find((episode) => episode.slug === slug) || null;
}

function updateSeriesInfiniteState() {
  const sentinel = document.getElementById("series-infinite");
  if (!sentinel) return;
  const label = document.getElementById("series-infinite-label");
  const retry = document.getElementById("series-infinite-retry");
  const mode = state.series.browseMode;
  const browsable = Boolean(mode && mode !== "search" && state.series.results.length);
  sentinel.classList.toggle("hidden", !browsable);
  if (!browsable) return;

  const count = state.series.results.length;
  sentinel.setAttribute("aria-busy", String(state.series.loadingBrowse));
  retry.hidden = !state.series.loadError
    && (catalogInfiniteObserverSupported || !state.series.lastPageFull);
  retry.textContent = state.series.loadError ? "Erneut versuchen" : "Weitere laden";
  if (state.series.loadingBrowse) {
    sentinel.dataset.state = "loading";
    label.textContent = "Weitere Serien werden geladen …";
  } else if (state.series.loadError) {
    sentinel.dataset.state = "error";
    label.textContent = `Nachladen fehlgeschlagen · ${count} Serien geladen`;
  } else if (state.series.lastPageFull) {
    sentinel.dataset.state = "ready";
    label.textContent = `${count} Serien geladen · Weiter scrollen`;
  } else {
    sentinel.dataset.state = "complete";
    label.textContent = `${count} Serien geladen · Ende des Katalogs`;
  }
  const sourceSummary = state.series.sources
    .map((source) => `${source.label} ${source.count}`)
    .join(" · ");
  sentinel.title = sourceSummary;
}

function updateSeriesFeatureArtwork(featureArt, artwork) {
  const source = artwork ? api.coverUrl(artwork) : "";
  if (!source) {
    const requestId = String(Number(featureArt.dataset.artworkRequest || 0) + 1);
    featureArt.dataset.artworkSource = "";
    featureArt.dataset.artworkRequest = requestId;
    featureArt.style.backgroundImage = "";
    return;
  }
  if (featureArt.dataset.artworkSource === source) return;

  const requestId = String(Number(featureArt.dataset.artworkRequest || 0) + 1);
  featureArt.dataset.artworkSource = source;
  featureArt.dataset.artworkRequest = requestId;
  const nextBackground = `url("${source.replace(/"/g, "%22")}")`;
  const image = new Image();
  image.decoding = "async";
  image.onload = async () => {
    try { await image.decode(); } catch (e) { /* bereits im Browser-Cache */ }
    if (featureArt.dataset.artworkRequest !== requestId) return;
    featureArt.style.backgroundImage = nextBackground;
  };
  image.src = source;
}

function renderSeriesCatalogHero() {
  const feature = document.getElementById("series-feature");
  if (!feature) return;
  const catalogCandidate = state.series.results.find((result) => result.backdrop_url);
  const featuredHomeSeries = [
    ...state.home.trendingSeries,
    ...state.home.newSeries,
    ...state.home.discoverySeries,
  ].find((result) => result.backdrop_url);
  const candidate = catalogCandidate
    || (state.series.browseMode !== "search" ? featuredHomeSeries : null)
    || state.series.results[0];
  if (!candidate) {
    feature.classList.add("hidden");
    return;
  }
  const artwork = candidate.backdrop_url || candidate.cover_url || "";
  const posterArtwork = !candidate.backdrop_url && Boolean(candidate.cover_url);
  feature.classList.remove("hidden");
  feature.classList.toggle("has-no-art", !artwork);
  feature.classList.toggle("is-poster-art", posterArtwork);
  feature.setAttribute("aria-label", `Serie im Fokus: ${candidate.title}`);
  const featureArt = document.getElementById("series-feature-art");
  updateSeriesFeatureArtwork(featureArt, artwork);
  document.getElementById("series-feature-title").textContent = candidate.title;
  const sources = Array.isArray(candidate.sources) ? candidate.sources : [];
  document.getElementById("series-feature-meta").textContent = [
    candidate.year || "",
    candidate.rating ? `★ ${candidate.rating}` : "",
    ...(candidate.genres || []).slice(0, 2),
    sources.length > 1 ? `${sources.length} Quellen` : (candidate.provider_label || sources[0]?.label || ""),
  ].filter(Boolean).join(" · ");
  document.getElementById("series-feature-description").textContent =
    candidate.description || "Staffeln, Episoden und Verfügbarkeit direkt im Royal Archiv entdecken.";
  document.getElementById("series-feature-open").onclick = () => loadSeries(candidate);
}

function createSeriesResultRow(result, { suppressEntryAnimation = false } = {}) {
  const selectedBase = state.series.pendingBaseSlug || state.series.current?.base_slug;
  const selected = selectedBase === result.base_slug;
  const loading = state.series.pendingBaseSlug === result.base_slug;
  const resultSources = Array.isArray(result.sources) ? result.sources : [];
  const sourceLabels = resultSources.map((source) => source.label).filter(Boolean);
  const sourceSummary = sourceLabels.length > 1
    ? `${sourceLabels.length} Quellen`
    : (sourceLabels[0] || result.provider_label || "Quelle offen");

  const row = document.createElement("div");
  row.className = "series-row result-card" + (selected ? " selected" : "") + (loading ? " loading" : "");
  if (suppressEntryAnimation) row.style.animation = "none";
  row.dataset.baseSlug = result.base_slug;
  row.setAttribute("aria-current", String(selected));
  row.setAttribute("aria-label", [result.title, result.year].filter(Boolean).join(", "));
  if (loading) row.setAttribute("aria-busy", "true");

  const visual = createResultCardVisual(result, result.title, "series", mediaJellyfinStatus(result));
  const copy = document.createElement("span");
  copy.className = "result-card-copy";
  const title = document.createElement("strong");
  title.className = "result-card-title";
  title.translate = false;
  title.textContent = result.title;
  const subtitle = document.createElement("span");
  subtitle.className = "result-card-subtitle";
  subtitle.textContent = sourceSummary;
  subtitle.title = sourceLabels.join(" · ");
  const meta = document.createElement("span");
  meta.className = "result-card-meta";
  const year = document.createElement("span");
  year.textContent = result.year || "Jahr offen";
  const stateLabel = document.createElement("span");
  stateLabel.className = "result-card-state status-ready";
  stateLabel.textContent = loading ? "Öffnet …" : "Staffeln öffnen";
  const jellyfin = document.createElement("span");
  setFpJellyfinBadge(jellyfin, mediaJellyfinStatus(result));
  meta.append(year, stateLabel, jellyfin);
  copy.append(title, subtitle, meta);

  row.append(visual, copy);
  const baseSlug = result.base_slug;
  activateResultCard(row, () => loadSeries(
    state.series.results.find((item) => item.base_slug === baseSlug) || result,
  ));
  return row;
}

function renderSeriesResults(appendFrom = 0, { suppressEntryAnimation = false } = {}) {
  const container = document.getElementById("series-results");
  const fragment = document.createDocumentFragment();
  if (appendFrom > 0) {
    for (const result of state.series.results.slice(appendFrom)) {
      fragment.append(createSeriesResultRow(result, { suppressEntryAnimation }));
    }
    container.append(fragment);
    return;
  }

  // Vorhandene Karten bleiben durchgehend mit dem Dokument verbunden. Ein
  // Umweg über ein Fragment würde die alte row-in-Animation erneut starten
  // und die komplette Serienfläche kurz auf opacity: 0 setzen.
  const existingRows = new Map(
    [...container.querySelectorAll(".series-row")]
      .map((row) => [row.dataset.baseSlug, row]),
  );
  const retainedSlugs = new Set();
  let insertionPoint = container.firstElementChild;
  for (const result of state.series.results) {
    let row = existingRows.get(result.base_slug);
    if (row) {
      retainedSlugs.add(result.base_slug);
    } else {
      row = createSeriesResultRow(result, { suppressEntryAnimation });
    }
    if (suppressEntryAnimation) row.style.animation = "none";
    if (row === insertionPoint) {
      insertionPoint = insertionPoint.nextElementSibling;
    } else {
      container.insertBefore(row, insertionPoint);
    }
  }
  for (const [baseSlug, row] of existingRows) {
    if (retainedSlugs.has(baseSlug)) continue;
    discardObservedResultPosters(row);
    row.remove();
  }
  for (const result of state.series.results) updateSeriesResultCard(result.base_slug);
  updateSeriesResultSelection();
}

function findSeriesResultCard(baseSlug) {
  return [...document.querySelectorAll("#series-results .series-row")]
    .find((row) => row.dataset.baseSlug === baseSlug) || null;
}

function updateSeriesResultCard(baseSlug) {
  const result = state.series.results.find((item) => item.base_slug === baseSlug);
  const row = findSeriesResultCard(baseSlug);
  if (!result || !row) return;
  const visual = row.querySelector(".result-card-visual");
  if (visual) {
    syncResultCardPoster(visual, result);
    const posterBadge = visual.querySelector(".result-card-library-badge");
    if (posterBadge) setFpPosterJellyfinBadge(posterBadge, mediaJellyfinStatus(result));
  }
  const title = row.querySelector(".result-card-title");
  if (title) title.textContent = result.title;
  const sources = Array.isArray(result.sources) ? result.sources : [];
  const sourceLabels = sources.map((source) => source.label).filter(Boolean);
  const subtitle = row.querySelector(".result-card-subtitle");
  if (subtitle) {
    subtitle.textContent = sourceLabels.length > 1
      ? `${sourceLabels.length} Quellen`
      : (sourceLabels[0] || result.provider_label || "Quelle offen");
    subtitle.title = sourceLabels.join(" · ");
  }
  const year = row.querySelector(".result-card-meta span:first-child");
  if (year) year.textContent = result.year || "Jahr offen";
  const jellyfin = row.querySelector(".jellyfin-badge");
  if (jellyfin) setFpJellyfinBadge(jellyfin, mediaJellyfinStatus(result));
}

function updateSeriesResultSelection() {
  const selectedBase = state.series.pendingBaseSlug || state.series.current?.base_slug;
  document.querySelectorAll("#series-results .series-row").forEach((row) => {
    const loading = state.series.pendingBaseSlug === row.dataset.baseSlug;
    const selected = selectedBase === row.dataset.baseSlug;
    row.classList.toggle("selected", selected);
    row.classList.toggle("loading", loading);
    row.setAttribute("aria-current", String(selected));
    if (loading) row.setAttribute("aria-busy", "true");
    else row.removeAttribute("aria-busy");
  });
}

function applySeriesResults(data, {
  append = false,
  artworkPrepared = false,
  backgroundRefresh = false,
} = {}) {
  const incoming = Array.isArray(data.results) ? data.results : [];
  const renderedCards = document.querySelectorAll("#series-results .series-row");
  const preserveRenderedCards = !append
    && incoming.length === state.series.results.length
    && renderedCards.length === incoming.length
    && incoming.every((result, index) => (
      result.base_slug === state.series.results[index]?.base_slug
    ));
  const appendFrom = append ? state.series.results.length : 0;
  state.series.results = append
    ? mergeCatalogItems(
      state.series.results,
      incoming,
      (item) => item.base_slug || item.sample_slug || item.sample_url,
    )
    : incoming;
  state.series.page = data.page || 1;
  state.series.lastPageFull = Boolean(data.has_more ?? data.last_page_full);
  state.series.sources = mergeCatalogSources(state.series.sources, data.sources, append);
  state.series.loadError = "";
  if (preserveRenderedCards) {
    if (backgroundRefresh) {
      renderedCards.forEach((row) => { row.style.animation = "none"; });
    }
    for (const result of incoming) updateSeriesResultCard(result.base_slug);
    updateSeriesResultSelection();
  } else {
    renderSeriesResults(appendFrom, { suppressEntryAnimation: backgroundRefresh });
  }
  const browseGeneration = state.series.browseRequestSeq;
  renderSeriesCatalogHero();
  // Jellyfin ist ein eigener Live-Status und darf nie auf Poster/TMDB warten.
  // Das betrifft insbesondere die komplette erste 32er-Katalogseite.
  void refreshCatalogJellyfinStatus(state.series.results.map(homeSeriesEntry), null)
    .then(() => {
      if (browseGeneration !== state.series.browseRequestSeq) return;
      for (const result of state.series.results) updateSeriesResultCard(result.base_slug);
      renderSeriesCatalogHero();
    });
  if (!artworkPrepared) {
    void hydrateHomeSeriesArtwork(incoming, { render: false }).then(async (hydratedBaseSlugs) => {
      for (const baseSlug of hydratedBaseSlugs) updateSeriesResultCard(baseSlug);
      renderSeriesCatalogHero();
    });
  }
  updateSeriesInfiniteState();
  recheckSeriesInfinite();
  const sourceCount = state.series.sources.length;
  document.getElementById("series-status").textContent =
    state.series.results.length
      ? (sourceCount
        ? `${state.series.results.length} Serie(n) · ${sourceCount} ${sourceCount === 1 ? "Quelle" : "Quellen"}`
        : `${state.series.results.length} Serie(n) gefunden`)
      : "Keine Serie gefunden.";
}

function clearSeriesSearchContext() {
  state.series.searchReturn = null;
  document.getElementById("series-search").value = "";
  syncSearchClearButtons();
  closeSearchSuggestions("series-search-suggestions", "series-search");
}

function rememberSeriesSearchContext() {
  if (state.series.searchReturn || state.series.browseMode === "search") return;
  if (!state.series.browseMode && !state.series.results.length) return;
  state.series.searchReturn = {
    results: state.series.results.slice(),
    browseMode: state.series.browseMode,
    page: state.series.page,
    lastPageFull: state.series.lastPageFull,
    sources: state.series.sources.slice(),
    current: state.series.current,
    currentSampleSlug: state.series.currentSampleSlug,
    epPicked: new Set(state.series.epPicked),
  };
}

async function restoreSeriesSearchContext() {
  if (state.series.browseMode !== "search" && !state.series.searchReturn) return;
  const saved = state.series.searchReturn;
  state.series.searchReturn = null;
  document.getElementById("series-search").value = "";
  ++state.series.browseRequestSeq;
  state.series.loadingBrowse = false;
  if (!saved) {
    await seriesBrowse("discover", 1);
    return;
  }
  state.series.browseMode = saved.browseMode;
  state.series.current = saved.current;
  state.series.currentSampleSlug = saved.currentSampleSlug;
  state.series.epPicked = new Set(saved.epPicked);
  applySeriesResults({
    results: saved.results,
    page: saved.page,
    has_more: saved.lastPageFull,
    sources: saved.sources,
  });
  renderSeriesTiles();
}

async function seriesSearch() {
  const q = document.getElementById("series-search").value.trim();
  if (!q) {
    await restoreSeriesSearchContext();
    return;
  }
  rememberSearch(q, "series");
  closeSearchSuggestions("series-search-suggestions", "series-search");
  rememberSeriesSearchContext();
  const requestId = ++state.series.browseRequestSeq;
  const previousMode = state.series.browseMode;
  state.series.browseMode = "search";
  state.series.loadingBrowse = true;
  state.series.loadError = "";
  updateSeriesInfiniteState();
  document.getElementById("series-status").textContent = `Suche nach «${q}» …`;
  try {
    const data = await api.series({ mode: "search", query: q });
    if (requestId !== state.series.browseRequestSeq) return;
    applySeriesResults(data);
    if (data.direct_series) {
      showSeriesDetail(data.direct_series, firstEpisodeSlug(data.direct_series));
      updateSeriesStatus(data.direct_series);
      refreshSeriesJellyfinStatus();
    }
  } catch (error) {
    if (requestId !== state.series.browseRequestSeq) return;
    state.series.browseMode = state.series.results.length ? previousMode : null;
    updateSeriesInfiniteState();
    document.getElementById("series-status").textContent = `Fehler: ${error.message}`;
  } finally {
    if (requestId === state.series.browseRequestSeq) {
      state.series.loadingBrowse = false;
      updateSeriesInfiniteState();
      // Fuellt einen noch zu kurzen Container automatisch weiter (Guards in
      // loadNextSeriesPage brechen ab, sobald genug da ist oder Ende erreicht).
      recheckSeriesInfinite();
    }
  }
}

function seriesParams(mode, page) {
  // Alpha-Modi kommen als "alpha:X"; "new"/"trending" direkt als Modusname.
  return mode.startsWith("alpha:")
    ? { mode: "alpha", letter: mode.split(":")[1], page }
    : { mode, page };
}

async function seriesBrowse(mode, page, { append = false } = {}) {
  if (mode !== "search") clearSeriesSearchContext();
  const requestId = ++state.series.browseRequestSeq;
  const previousMode = state.series.browseMode;
  const previousLastPageFull = state.series.lastPageFull;
  state.series.browseMode = mode;
  state.series.loadingBrowse = true;
  state.series.loadError = "";
  if (!append) state.series.lastPageFull = false;
  updateSeriesInfiniteState();
  const modeLabels = { discover: "interessante Serien", new: "neue Serien", trending: "angesagte Serien" };
  if (!append) {
    document.getElementById("series-status").textContent = `Lade ${modeLabels[mode] || "Serien"} …`;
  }
  try {
    const data = await api.series(seriesParams(mode, page));
    if (requestId !== state.series.browseRequestSeq) return false;
    // Serienkarten sofort stabil anhaengen; Poster, TMDB und Jellyfin werden
    // parallel pro Karte ergaenzt statt die ganze Folgeseite zu sperren.
    applySeriesResults(data, { append });
    if (append) void preloadSeriesPosterImages(data.results || [], 2000);
    if (!append) state.series.previewFromHome = false;
    if (!append && page === 1) state.series.lastCatalogRefreshAt = Date.now();
    return true;
  } catch (error) {
    if (requestId !== state.series.browseRequestSeq) return false;
    document.getElementById("series-status").textContent = append
      ? `Nachladen fehlgeschlagen: ${error.message}`
      : `Fehler: ${error.message}`;
    if (append) {
      state.series.loadError = error.message;
    } else {
      state.series.loadError = "";
      state.series.browseMode = state.series.results.length ? previousMode : null;
      state.series.lastPageFull = previousLastPageFull;
    }
    return false;
  } finally {
    if (requestId === state.series.browseRequestSeq) {
      state.series.loadingBrowse = false;
      updateSeriesInfiniteState();
    }
  }
}

function ensureSeriesResults() {
  syncSeriesCatalogFromHome();
  if (state.series.results.length) {
    if (!document.getElementById("series-results").childElementCount) renderSeriesResults();
    refreshSeriesCatalogInBackground();
    return;
  }
  if (state.series.loadingBrowse) return;
  seriesBrowse("discover", 1);
}

async function loadNextSeriesPage() {
  const mode = state.series.browseMode;
  if (
    state.tab !== "serien"
    || !mode
    || mode === "search"
    || state.series.loadingBrowse
    || !state.series.lastPageFull
  ) return;
  await seriesBrowse(mode, state.series.page + 1, { append: true });
}

function seriesStructureFingerprint(series) {
  return (series?.seasons || []).map((season) =>
    `${season.season}:${(season.episodes || []).map((episode) => episode.slug).join(",")}`,
  ).join("|");
}

function mergeSeriesDetailPayload(previous, fresh) {
  if (!previous) return fresh;
  if (!fresh) return previous;
  const seasons = new Map();
  for (const snapshot of [previous, fresh]) {
    for (const season of snapshot.seasons || []) {
      const seasonNumber = Number(season.season || 0);
      if (seasonNumber <= 0) continue;
      const episodes = seasons.get(seasonNumber) || new Map();
      for (const episode of season.episodes || []) {
        const key = episode.slug || `${seasonNumber}:${episode.episode}`;
        episodes.set(key, { ...(episodes.get(key) || {}), ...episode });
      }
      seasons.set(seasonNumber, episodes);
    }
  }
  const mergedSeasons = [...seasons.entries()]
    .sort(([left], [right]) => left - right)
    .map(([season, episodes]) => ({
      season,
      episodes: [...episodes.values()].sort((left, right) => left.episode - right.episode),
    }));
  return {
    ...previous,
    ...fresh,
    seasons: mergedSeasons,
    episode_count: mergedSeasons.reduce((total, season) => total + season.episodes.length, 0),
    backdrop_url: fresh.backdrop_url || previous.backdrop_url || "",
  };
}

async function loadSeries(result) {
  const cacheKey = result.base_slug || result.sample_slug;
  if (state.series.pendingBaseSlug === cacheKey) return;
  trackDiscoveryPreference("series", result, 0.8, "open");
  const requestId = ++state.series.requestSeq;
  state.series.pendingBaseSlug = cacheKey;
  updateSeriesResultSelection();
  showSeriesLoading(result);
  openMediaModal("series-detail-modal", findSeriesResultCard(result.base_slug));

  const cached = state.series.cache[cacheKey];
  if (cached) {
    const enriched = mergeSeriesDetailPayload(result, cached);
    showSeriesDetail(enriched, result.sample_slug);
    updateSeriesStatus(enriched);
    refreshSeriesJellyfinStatus();
    return;
  }

  document.getElementById("series-status").textContent = `Öffne Staffeln für «${result.title}» …`;
  try {
    const loaded = await api.seriesLoad(result.sample_slug, result.base_slug || "", false, true);
    if (requestId !== state.series.requestSeq) return;
    const series = mergeSeriesDetailPayload(result, loaded);
    showSeriesDetail(series, result.sample_slug);
    updateSeriesStatus(series);
    refreshSeriesJellyfinStatus();
  } catch (e) {
    if (requestId !== state.series.requestSeq) return;
    state.series.pendingBaseSlug = "";
    updateSeriesResultSelection();
    document.getElementById("series-status").textContent = `Fehler: ${e.message}`;
    document.getElementById("series-detail-title").textContent = `${result.title} · Laden fehlgeschlagen`;
    document.getElementById("series-desc").textContent = e.message;
    const loading = document.querySelector("#series-tiles .series-loading");
    if (loading) loading.textContent = "Serie konnte nicht geladen werden";
  }
}

function showSeriesLoading(result) {
  state.series.viewGeneration += 1;
  state.series.current = null;
  document.getElementById("series-detail-title").textContent = result.title;
  updateSeriesJellyfinBadge(result, true);
  setSeriesDetailArtwork(result);
  const cover = document.getElementById("series-cover");
  cover.loading = "eager";
  cover.fetchPriority = "high";
  const previewCover = result.cover_url ? api.coverUrl(result.cover_url) : "";
  if (previewCover) {
    if (cover.getAttribute("src") !== previewCover) cover.src = previewCover;
  } else {
    cover.removeAttribute("src");
  }
  const sourceLabels = (Array.isArray(result.sources) ? result.sources : [])
    .map((source) => source.label)
    .filter(Boolean);
  const previewMeta = [result.year, ...sourceLabels].filter(Boolean);
  if (!sourceLabels.length && result.provider_label) previewMeta.push(result.provider_label);
  renderSeriesDetailMeta(previewMeta);
  document.getElementById("series-desc").textContent =
    "Die Serie ist geöffnet. Staffel- und Episodenstruktur wird beim Anbieter eingelesen.";
  configureSeriesTrailer(result);
  renderSeriesDetailDiscovery(result);
  const tiles = document.getElementById("series-tiles");
  tiles.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "series-loading";
  loading.textContent = "Staffeln werden eingelesen …";
  tiles.appendChild(loading);
  document.getElementById("series-pick-count").textContent = "wird geladen";
  document.getElementById("series-watch-btn").disabled = true;
  document.getElementById("series-select-all").disabled = true;
  document.getElementById("series-select-none").disabled = true;
  document.getElementById("series-add-btn").disabled = true;
}

function renderSeriesDetailMeta(values) {
  const container = document.getElementById("series-genres");
  container.replaceChildren();
  for (const value of values.filter(Boolean)) {
    const item = document.createElement("span");
    item.textContent = value;
    container.appendChild(item);
  }
}

function updateWatchBtn() {
  const btn = document.getElementById("series-watch-btn");
  const series = state.series.current;
  if (!series) return;
  const tracked = series.watchlisted;
  const label = WATCH_MODE_LABELS[series.watch_mode] || WATCH_MODE_LABELS[WATCH_MODE_DEFAULT];
  btn.textContent = tracked ? `✓ Abo · ${label}` : "+ Abonnieren";
  btn.title = tracked ? "Abo-Regel ändern" : "Serie abonnieren und Downloadumfang festlegen";
  btn.classList.toggle("btn-accent", tracked);
}

function setSeriesDetailArtwork(series) {
  const panel = document.querySelector("#series-detail-modal .series-detail-panel");
  // Das Hero ist ein 16:9-Wallpaper. Hochformat-Poster dürfen hier nie als
  // Ersatz erscheinen, da sie aufgezoomt und abgeschnitten wirken.
  const artwork = series?.backdrop_url || "";
  panel.classList.toggle("has-no-art", !artwork);
  if (!artwork) {
    panel.style.removeProperty("--series-backdrop-image");
    return;
  }
  const backdropUrl = api.coverUrl(artwork).replace(/"/g, "%22");
  const nextImage = `url("${backdropUrl}")`;
  if (panel.style.getPropertyValue("--series-backdrop-image") !== nextImage) {
    panel.style.setProperty("--series-backdrop-image", nextImage);
  }
}

let seriesDetailHeroTrailerTimer = null;
let seriesDetailHeroTrailerToken = 0;
let seriesDetailHeroTrailerCurrentTime = 0;
let seriesDetailHeroTrailerKey = "";

function stopSeriesDetailHeroTrailer() {
  seriesDetailHeroTrailerToken += 1;
  if (seriesDetailHeroTrailerTimer) clearTimeout(seriesDetailHeroTrailerTimer);
  seriesDetailHeroTrailerTimer = null;
  const panel = document.querySelector("#series-detail-modal .series-detail-panel");
  const shell = document.getElementById("series-detail-hero-trailer");
  const frame = document.getElementById("series-detail-hero-frame");
  const muteButton = document.getElementById("series-detail-hero-mute");
  if (!panel || !shell || !frame || !muteButton) return;
  shell.classList.remove("is-playing");
  panel.classList.remove("is-trailer-playing");
  muteButton.hidden = true;
  frame.onload = null;
  frame.removeAttribute("src");
  shell.hidden = true;
  seriesDetailHeroTrailerKey = "";
  setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
}

function scheduleSeriesDetailHeroTrailer(series) {
  const key = fpTrailerYoutubeKey(series);
  if (
    !key
    || !heroTrailerAutoplayEnabled()
    || completedSeriesHeroTrailers.has(key)
    || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  ) {
    stopSeriesDetailHeroTrailer();
    return;
  }
  const shell = document.getElementById("series-detail-hero-trailer");
  if (seriesDetailHeroTrailerKey === key && (!shell.hidden || seriesDetailHeroTrailerTimer)) return;
  stopSeriesDetailHeroTrailer();
  seriesDetailHeroTrailerKey = key;
  seriesDetailHeroTrailerCurrentTime = 0;
  const token = seriesDetailHeroTrailerToken;
  seriesDetailHeroTrailerTimer = setTimeout(() => {
    if (
      token !== seriesDetailHeroTrailerToken
      || document.getElementById("series-detail-modal").hidden
    ) return;
    const frame = document.getElementById("series-detail-hero-frame");
    const muteButton = document.getElementById("series-detail-hero-mute");
    shell.hidden = false;
    frame.onload = () => {
      if (token !== seriesDetailHeroTrailerToken) return;
      listenForHeroTrailerTime(frame);
      muteButton.hidden = false;
      setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
      syncDetailHeroScrollPlayback(
        document.querySelector("#series-detail-modal .series-detail-panel"),
        { force: true },
      );
    };
    frame.src =
      `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
      + `?autoplay=1&mute=1&controls=0&playsinline=1&rel=0&modestbranding=1`
      + `&disablekb=1&fs=0&iv_load_policy=3&enablejsapi=1`
      + `&origin=${encodeURIComponent(window.location.origin)}`;
  }, 2000);
}

function configureSeriesTrailer(series) {
  const button = document.getElementById("series-detail-trailer");
  const trailerKey = fpTrailerYoutubeKey(series);
  const available = Boolean(trailerKey);
  const trailerSeries = available
    ? { ...series, trailer: { ...series.trailer, key: trailerKey } }
    : null;
  button.hidden = !available;
  button.onclick = trailerSeries
    ? () => openFpTrailerModal(trailerSeries, button, "series")
    : null;
  if (available) scheduleSeriesDetailHeroTrailer(trailerSeries);
  else stopSeriesDetailHeroTrailer();
}

function updateSeriesOverview(series) {
  document.getElementById("series-detail-title").textContent = series.title;
  setSeriesDetailArtwork(series);
  const cover = document.getElementById("series-cover");
  cover.loading = "eager";
  cover.fetchPriority = "high";
  const nextCover = series.cover_url ? api.coverUrl(series.cover_url) : "";
  if (nextCover) {
    if (cover.getAttribute("src") !== nextCover) cover.src = nextCover;
  } else {
    cover.removeAttribute("src");
  }
  const seriesMeta = [];
  if (series.year) seriesMeta.push(series.year);
  if (series.runtime) seriesMeta.push(series.runtime);
  seriesMeta.push(...(series.genres || []));
  seriesMeta.push(
    `${series.seasons.length} ${series.seasons.length === 1 ? "Staffel" : "Staffeln"}`,
    `${series.episode_count} ${series.episode_count === 1 ? "Episode" : "Episoden"}`,
  );
  if (series.metadata_source) seriesMeta.push(`Metadaten: ${series.metadata_source}`);
  renderSeriesDetailMeta(seriesMeta);
  document.getElementById("series-desc").textContent = series.description || "(keine Beschreibung verfügbar)";
  configureSeriesTrailer(series);
  renderSeriesDetailDiscovery(series);
}

function showSeriesDetail(series, sampleSlug) {
  state.series.viewGeneration += 1;
  syncSeriesQueueFlags(series);
  state.series.current = series;
  state.series.currentSampleSlug = sampleSlug;
  state.series.cache[series.base_slug] = series;
  state.series.pendingBaseSlug = "";
  state.series.epPicked = new Set();
  updateSeriesResultSelection();
  updateSeriesOverview(series);
  document.getElementById("series-watch-btn").disabled = false;
  document.getElementById("series-select-all").disabled = false;
  document.getElementById("series-select-none").disabled = false;
  updateWatchBtn();
  renderSeriesTiles();
  updateSeriesStatus(series);
  updateTasteFeedbackButtons();
  openMediaModal("series-detail-modal", findSeriesResultCard(series.base_slug));
}

function tileClass(ep) {
  if (isEpisodeQueued(ep)) return "queued";
  if (ep.downloaded) return "downloaded";
  if (ep.unreleased) return "scheduled";
  if (state.series.epPicked.has(ep.slug) && isEpisodeSelectable(ep)) return "selected";
  return "available";
}

function episodeReleaseText(ep) {
  const release = new Date(ep?.release_at || "");
  if (!Number.isNaN(release.getTime())) {
    return new Intl.DateTimeFormat("de-DE", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    }).format(release).replace(",", " ·").toLocaleUpperCase("de-DE");
  }
  return ep?.release_label || "DEMNÄCHST";
}

function seriesAvailabilityNotice(series) {
  if (series.availability_pending) {
    return series.availability_error
      ? "Auswahl pausiert: Die Verfügbarkeit konnte noch nicht geprüft werden."
      : "Staffeln sind da · Bestand und Metadaten werden im Hintergrund geprüft …";
  }
  if (series.jellyfin_available === false) {
    return "Auswahl pausiert: Jellyfin konnte nicht eindeutig abgeglichen werden.";
  }
  return "";
}

function syncSeriesAvailabilityNotice(container, series) {
  let notice = container.querySelector(":scope > .series-loading");
  const text = seriesAvailabilityNotice(series);
  if (!text) {
    notice?.remove();
    return;
  }
  if (!notice) {
    notice = document.createElement("div");
    notice.className = "series-loading";
    container.prepend(notice);
  }
  if (notice.textContent !== text) notice.textContent = text;
}

function applySeriesEpisodeTileState(tile, episode, series) {
  tile.className = "ep-tile " + tileClass(episode) + (episode.in_jellyfin ? " in-jellyfin" : "");
  tile.disabled = !isEpisodeSelectable(episode);
  const releaseText = episode.unreleased ? episodeReleaseText(episode) : "";
  if (series.availability_error) tile.title = "Verfügbarkeitsprüfung fehlgeschlagen";
  else if (series.availability_pending) tile.title = "Verfügbarkeit wird geprüft";
  else if (episode.in_jellyfin) tile.title = "Bereits in Jellyfin vorhanden";
  else if (episode.downloaded) tile.title = "Bereits heruntergeladen";
  else if (isEpisodeQueued(episode)) tile.title = "Bereits in der Warteschlange";
  else if (episode.unreleased) tile.title = `Download gesperrt · verfügbar ab ${releaseText}`;
  else tile.removeAttribute("title");
}

function refreshSeriesTileStates() {
  const series = state.series.current;
  const container = document.getElementById("series-tiles");
  if (!series || !container) return;
  syncSeriesAvailabilityNotice(container, series);
  const episodesBySlug = new Map(seriesEpisodes(series).map((episode) => [episode.slug, episode]));
  for (const tile of container.querySelectorAll(".ep-tile[data-episode-slug]")) {
    const episode = episodesBySlug.get(tile.dataset.episodeSlug);
    if (episode) applySeriesEpisodeTileState(tile, episode, series);
  }
  for (const season of series.seasons || []) {
    const row = [...container.querySelectorAll(".season-row")]
      .find((candidate) => Number(candidate.dataset.season) === Number(season.season));
    if (!row) continue;
    const pickedCount = season.episodes.filter((episode) => state.series.epPicked.has(episode.slug)).length;
    const button = row.querySelector(".season-btn");
    const count = button?.querySelector("small");
    if (button) button.disabled = !season.episodes.some(isEpisodeSelectable);
    if (count) count.textContent = `${pickedCount}/${season.episodes.length} gewählt`;
  }
  const selectableCount = seriesEpisodes(series).filter(isEpisodeSelectable).length;
  document.getElementById("series-pick-count").textContent = `${state.series.epPicked.size} ausgewählt`;
  document.getElementById("series-select-all").disabled = selectableCount === 0;
  document.getElementById("series-select-none").disabled = state.series.epPicked.size === 0;
  document.getElementById("series-add-btn").disabled = state.series.epPicked.size === 0;
}

function renderSeriesTiles() {
  const container = document.getElementById("series-tiles");
  container.innerHTML = "";
  const series = state.series.current;
  if (!series) { document.getElementById("series-pick-count").textContent = "0 ausgewählt"; return; }
  pruneSeriesEpisodeSelection();
  syncSeriesAvailabilityNotice(container, series);
  const selectableCount = seriesEpisodes(series).filter(isEpisodeSelectable).length;
  for (const seasonObj of series.seasons) {
    const pickedCount = seasonObj.episodes.filter((e) => state.series.epPicked.has(e.slug)).length;
    const row = document.createElement("div");
    row.className = "season-row";
    row.dataset.season = seasonObj.season;
    const seasonBtn = document.createElement("button");
    seasonBtn.className = "season-btn";
    seasonBtn.setAttribute("aria-label", `Staffel ${seasonObj.season}: ${pickedCount} von ${seasonObj.episodes.length} ausgewählt`);
    const seasonLabel = document.createElement("span");
    seasonLabel.textContent = "STAFFEL";
    const seasonNumber = document.createElement("strong");
    seasonNumber.textContent = String(seasonObj.season).padStart(2, "0");
    const seasonCount = document.createElement("small");
    seasonCount.textContent = `${pickedCount}/${seasonObj.episodes.length} gewählt`;
    seasonBtn.append(seasonLabel, seasonNumber, seasonCount);
    seasonBtn.disabled = !seasonObj.episodes.some(isEpisodeSelectable);
    seasonBtn.addEventListener("click", () => toggleSeasonTiles(seasonObj.season));
    row.appendChild(seasonBtn);
    const tiles = document.createElement("div");
    tiles.className = "ep-tiles";
    for (const ep of seasonObj.episodes) {
      const tile = document.createElement("button");
      tile.dataset.episodeSlug = ep.slug;
      applySeriesEpisodeTileState(tile, ep, series);
      const releaseText = ep.unreleased ? episodeReleaseText(ep) : "";
      tile.setAttribute(
        "aria-label",
        ep.unreleased ? `Folge ${ep.episode}, verfügbar ab ${releaseText}` : `Folge ${ep.episode}`,
      );
      const episodeLabel = document.createElement("span");
      episodeLabel.textContent = "FOLGE";
      const episodeNumber = document.createElement("strong");
      episodeNumber.textContent = String(ep.episode).padStart(2, "0");
      tile.append(episodeLabel, episodeNumber);
      if (ep.unreleased) {
        const release = document.createElement("small");
        release.className = "ep-release";
        release.textContent = releaseText;
        tile.appendChild(release);
      }
      tile.addEventListener("click", () => toggleEpisodeTile(ep.slug));
      tiles.appendChild(tile);
    }
    row.appendChild(tiles);
    container.appendChild(row);
  }
  document.getElementById("series-pick-count").textContent = `${state.series.epPicked.size} ausgewählt`;
  document.getElementById("series-select-all").disabled = selectableCount === 0;
  document.getElementById("series-select-none").disabled = state.series.epPicked.size === 0;
  document.getElementById("series-add-btn").disabled = state.series.epPicked.size === 0;
}

function toggleEpisodeTile(slug) {
  const episode = findCurrentEpisode(slug);
  if (!isEpisodeSelectable(episode)) {
    state.series.epPicked.delete(slug);
    renderSeriesTiles();
    return;
  }
  if (state.series.epPicked.has(slug)) state.series.epPicked.delete(slug);
  else state.series.epPicked.add(slug);
  renderSeriesTiles();
}

function toggleSeasonTiles(season) {
  const seasonObj = state.series.current.seasons.find((s) => s.season === season);
  if (!seasonObj) return;
  const selectable = seasonObj.episodes.filter(isEpisodeSelectable);
  if (!selectable.length) return;
  const allPicked = selectable.every((episode) => state.series.epPicked.has(episode.slug));
  for (const ep of seasonObj.episodes) {
    if (!isEpisodeSelectable(ep) || allPicked) state.series.epPicked.delete(ep.slug);
    else state.series.epPicked.add(ep.slug);
  }
  renderSeriesTiles();
}

function markSeriesSlugDownloaded(slug) {
  const series = state.series.current;
  if (!series) return;
  for (const s of series.seasons) {
    for (const ep of s.episodes) {
      if (ep.slug === slug) { ep.downloaded = true; refreshSeriesTileStates(); return; }
    }
  }
}

async function seriesAddSelected() {
  pruneSeriesEpisodeSelection();
  if (!state.series.epPicked.size) {
    document.getElementById("series-status").textContent =
      "Keine herunterladbaren Episoden ausgewählt.";
    renderSeriesTiles();
    return;
  }
  const slugs = [...state.series.epPicked];
  document.getElementById("series-status").textContent = `Lade ${slugs.length} Episode(n) …`;
  const addButton = document.getElementById("series-add-btn");
  addButton.disabled = true;
  try {
    const resp = await api.queueAdd(slugs);
    if (Number(resp.added || 0) > 0 && state.series.current) {
      trackDiscoveryPreference("series", state.series.current, 5, "download");
    }
    refreshQueueUiAfterChange(resp);
    document.getElementById("series-status").textContent =
      `${resp.added}/${slugs.length} Episode(n) automatisch gestartet`;
    state.series.epPicked.clear();
  } catch (error) {
    document.getElementById("series-status").textContent =
      `Download konnte nicht gestartet werden: ${error.message}`;
  } finally {
    renderSeriesTiles();
  }
}
