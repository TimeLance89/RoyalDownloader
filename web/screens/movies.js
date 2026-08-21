// ── Filmkatalog und Filmdetails ──────────────────────────────────────────
const fpJellyfinPending = new Map();
let fpJellyfinWorker = null;
const fpQueueMutations = new Set();

function fpStatusMessage() {
  const filteredResults = fpSmartFilteredResults();
  const visibleSlugs = new Set(filteredResults.map((r) => r.slug));
  const visiblePicks = [...state.queuedSlugs].filter((s) => visibleSlugs.has(s)).length;
  const otherPicks = state.queuedSlugs.size - visiblePicks;
  let msg;
  if (state.fp.searchActive) {
    msg = `${filteredResults.length} Filme auf TMDB`;
  } else if (state.fp.activeGenre === "Alle Genres") {
    msg = `${filteredResults.length} von ${state.fp.results.length} Treffern`;
  } else {
    msg = `${state.fp.activeGenre} · ${filteredResults.length} von ${state.fp.results.length} Treffern`;
  }
  if (state.queuedSlugs.size) {
    const extra = otherPicks ? `  ·  ${otherPicks} von anderen Seiten` : "";
    msg += `  ·  ${state.queuedSlugs.size} markiert${extra}`;
  }
  return msg;
}

function setActiveGenreFilter(genre) {
  const activeGenre = genre || "Alle Genres";
  state.fp.activeGenre = activeGenre;
  const activeLabel = document.getElementById("genre-active");
  if (activeLabel) activeLabel.textContent = activeGenre === "Alle Genres" ? "Alle Filme" : activeGenre;
  const select = document.getElementById("movie-filter-genre");
  if (select) select.value = activeGenre;
}

function mergeCatalogItems(current, incoming, keyFor) {
  const merged = current.slice();
  const known = new Set(current.map(keyFor));
  for (const item of incoming) {
    const key = keyFor(item);
    if (!key || known.has(key)) continue;
    known.add(key);
    merged.push(item);
  }
  return merged;
}

function mergeCatalogSources(current, incoming, append) {
  const cleanIncoming = Array.isArray(incoming)
    ? incoming.filter((source) => Number(source.count) > 0)
    : [];
  if (!append) return cleanIncoming;
  const merged = new Map(current.map((source) => [source.key || source.label, { ...source }]));
  for (const source of cleanIncoming) {
    const key = source.key || source.label;
    const existing = merged.get(key);
    if (existing) existing.count = Number(existing.count || 0) + Number(source.count || 0);
    else merged.set(key, { ...source });
  }
  return [...merged.values()];
}

function updateFpInfiniteState() {
  const sentinel = document.getElementById("fp-infinite");
  if (!sentinel) return;
  const label = document.getElementById("fp-infinite-label");
  const retry = document.getElementById("fp-infinite-retry");
  const browsable = Boolean(state.fp.category && !state.fp.searchActive && state.fp.results.length);
  sentinel.classList.toggle("hidden", !browsable);
  if (!browsable) return;

  const count = state.fp.results.length;
  sentinel.setAttribute("aria-busy", String(state.fp.loadingMore));
  retry.hidden = !state.fp.loadError
    && (catalogInfiniteObserverSupported || !state.fp.lastPageFull);
  retry.textContent = state.fp.loadError ? "Erneut versuchen" : "Weitere laden";
  if (state.fp.loadingMore) {
    sentinel.dataset.state = "loading";
    label.textContent = "Weitere Filme werden geladen …";
  } else if (state.fp.loadError) {
    sentinel.dataset.state = "error";
    label.textContent = `Nachladen fehlgeschlagen · ${count} Filme geladen`;
  } else if (state.fp.lastPageFull) {
    sentinel.dataset.state = "ready";
    label.textContent = `${count} Filme geladen · Weiter scrollen`;
  } else {
    sentinel.dataset.state = "complete";
    label.textContent = `${count} Filme geladen · Ende des Katalogs`;
  }
  const sourceSummary = state.fp.sources
    .map((source) => `${source.label} ${source.count}`)
    .join(" · ");
  sentinel.title = sourceSummary;
}

// Bestes bekanntes Jahr eines Filmtreffers. Anbieterlisten liefern teils ein
// falsches Jahr (Re-Release/Scraping-Fehler), das den jahrgenauen
// Jellyfin-Abgleich sonst fälschlich scheitern lässt und im UI verkehrt
// angezeigt wird. Das per TMDB aufgelöste Jahr ist verlässlicher.
function fpResultYear(result) {
  return state.fp.metadataCache[result.slug]?.year || result.year || "";
}

async function drainFpJellyfinQueue() {
  while (fpJellyfinPending.size) {
    const targets = [...fpJellyfinPending.values()].slice(0, 100);
    targets.forEach((item) => fpJellyfinPending.delete(item.slug));
    try {
      await refreshCatalogJellyfinStatus(targets.map(homeMovieEntry), null);
      updateFpJellyfinBadges();
    } catch (e) {
      if (targets.some((item) => item.slug === state.fp.selectedSlug)) {
        setFpDetailJellyfinStatus("unavailable");
      }
    }
  }
}

function refreshFpJellyfinStatus(items = null) {
  const targets = Array.isArray(items) ? [...items] : [...state.fp.results];
  if (!items) {
    const selectedHomeMovie = homeMovieBySlug(state.fp.selectedSlug);
    if (selectedHomeMovie && !targets.some((item) => item.slug === selectedHomeMovie.slug)) {
      targets.push(selectedHomeMovie);
    }
  }
  for (const item of targets) {
    if (item?.slug) fpJellyfinPending.set(item.slug, item);
  }
  if (!fpJellyfinPending.size || fpJellyfinWorker) return fpJellyfinWorker;
  fpJellyfinWorker = drainFpJellyfinQueue().finally(() => {
    fpJellyfinWorker = null;
  });
  return fpJellyfinWorker;
}

function updateSeriesStatus(series) {
  if (!series) return;
  updateSeriesJellyfinBadge(series);
  const status = document.getElementById("series-status");
  if (series.availability_error) {
    status.textContent = `${series.episode_count} Episoden · Verfügbarkeitsprüfung fehlgeschlagen`;
    return;
  }
  if (series.availability_pending) {
    status.textContent = `${series.episode_count} Episoden · Verfügbarkeit wird geprüft …`;
    return;
  }
  if (series.jellyfin_available === false) {
    status.textContent = `${series.episode_count} Episoden · Jellyfin-Abgleich nicht verfügbar`;
    return;
  }
  if (series.jellyfin_configured) {
    const jellyfinCount = (series.seasons || []).reduce(
      (sum, season) => sum + season.episodes.filter((episode) => episode.in_jellyfin).length,
      0,
    );
    status.textContent = `${series.episode_count} Episoden · ${jellyfinCount} in Jellyfin`;
    return;
  }
  status.textContent = `${series.episode_count} Episoden`;
}

function updateSeriesJellyfinBadge(series, checking = false) {
  const badge = document.getElementById("series-jellyfin-status");
  if (!badge) return;
  const label = badge.querySelector("strong");
  badge.className = "series-jellyfin-status";
  if (checking || series?.jellyfin_pending) {
    badge.classList.add("is-checking");
    label.textContent = "Jellyfin wird geprüft";
    return;
  }
  if (series?.jellyfin_stale) {
    const episodes = (series.seasons || []).flatMap((season) => season.episodes || []);
    const jellyfinCount = episodes.filter((episode) => episode.in_jellyfin).length;
    badge.classList.add("is-unavailable");
    label.textContent = `${jellyfinCount} Episoden · letzter Jellyfin-Stand`;
    return;
  }
  if (series?.availability_error || series?.jellyfin_available === false) {
    badge.classList.add("is-unavailable");
    label.textContent = "Jellyfin-Abgleich nicht verfügbar";
    return;
  }
  if (!series?.jellyfin_configured) {
    badge.classList.add("is-disconnected");
    label.textContent = "Jellyfin nicht verbunden";
    return;
  }
  const episodes = (series.seasons || []).flatMap((season) => season.episodes || []);
  const jellyfinCount = episodes.filter((episode) => episode.in_jellyfin).length;
  badge.classList.add(jellyfinCount ? "is-owned" : "is-missing");
  label.textContent = jellyfinCount === episodes.length && episodes.length
    ? "Vollständig in Jellyfin"
    : jellyfinCount
      ? `${jellyfinCount} Episoden in Jellyfin`
      : "Nicht in Jellyfin";
}

async function refreshSeriesJellyfinStatus(force = false) {
  const current = state.series.current;
  if (!current) return false;
  const baseSlug = current.base_slug;
  const sampleSlug = state.series.currentSampleSlug || firstEpisodeSlug(current) || current.url;
  const viewGeneration = state.series.viewGeneration;
  const refreshGeneration = ++state.series.jellyfinRefreshSeq;
  state.series.jellyfinRefreshByBase.set(baseSlug, refreshGeneration);
  const quickStatusPromise = api.seriesJellyfinStatus(current, force).then((status) => {
    const isLatestForSeries = state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration;
    const isSameView = state.series.viewGeneration === viewGeneration;
    if (!isLatestForSeries || !isSameView || state.series.current?.base_slug !== baseSlug) return;
    const live = state.series.current;
    for (const season of live.seasons || []) {
      for (const episode of season.episodes || []) {
        if (Object.hasOwn(status.episodes || {}, episode.slug)) {
          episode.in_jellyfin = Boolean(status.episodes[episode.slug]);
        }
      }
    }
    live.jellyfin_configured = Boolean(status.configured);
    live.jellyfin_pending = false;
    live.jellyfin_available = Boolean(status.available);
    live.jellyfin_stale = Boolean(status.stale);
    live.jellyfin_checked_at = Number(status.checked_at || 0);
    state.series.cache[baseSlug] = live;
    pruneSeriesEpisodeSelection();
    refreshSeriesTileStates();
    updateSeriesStatus(live);
  }).catch((error) => {
    console.warn("Schneller Jellyfin-Abgleich fehlgeschlagen:", error);
  });
  try {
    // Der gezielte Status oben übernimmt ein erzwungenes Live-Refresh. Das
    // vollständige Enrichment nutzt danach denselben Cache und lädt nicht
    // parallel erneut die komplette Jellyfin-Struktur.
    const refreshed = await api.seriesLoad(sampleSlug, baseSlug, false);
    const isLatestForSeries = state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration;
    const isSameView = state.series.viewGeneration === viewGeneration;
    if (!isLatestForSeries || !isSameView || state.series.current?.base_slug !== baseSlug) return false;
    syncSeriesQueueFlags(refreshed);
    const previousStructure = seriesStructureFingerprint(state.series.current);
    const enriched = mergeSeriesDetailPayload(state.series.current || current, refreshed);
    state.series.current = enriched;
    state.series.cache[baseSlug] = enriched;
    pruneSeriesEpisodeSelection();
    updateSeriesOverview(enriched);
    updateWatchBtn();
    if (seriesStructureFingerprint(enriched) !== previousStructure) renderSeriesTiles();
    else refreshSeriesTileStates();
    updateSeriesStatus(enriched);
    return true;
  } catch (error) {
    console.warn("Serienstatus konnte nicht live aktualisiert werden:", error);
    const isLatestForSeries = state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration;
    const isSameView = state.series.viewGeneration === viewGeneration;
    if (
      isLatestForSeries
      && isSameView
      && state.series.current?.base_slug === baseSlug
      && state.series.current.availability_pending
    ) {
      state.series.current.availability_error = true;
      state.series.cache[baseSlug] = state.series.current;
      refreshSeriesTileStates();
      updateSeriesStatus(state.series.current);
    }
    return false;
  } finally {
    await quickStatusPromise;
    if (state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration) {
      state.series.jellyfinRefreshByBase.delete(baseSlug);
    }
  }
}

function setFpJellyfinBadge(badge, status) {
  const normalized = typeof status === "boolean" ? (status ? "owned" : "missing") : status;
  setCatalogJellyfinBadge(badge, normalized);
  badge.classList.add("jellyfin-badge");
}

function setFpPosterJellyfinBadge(badge, status) {
  const normalized = typeof status === "boolean" ? (status ? "owned" : "missing") : status;
  setCatalogJellyfinBadge(badge, normalized);
  badge.classList.add("result-card-library-badge");
  badge.textContent = {
    owned: "In Jellyfin",
    missing: "Nicht in Jellyfin",
    checking: "Jellyfin wird geprüft",
    unavailable: "Jellyfin nicht erreichbar",
    blocked: "Jellyfin-Statusanfrage blockiert",
    unconfigured: "Jellyfin nicht verbunden",
    ambiguous: "Jellyfin-Zuordnung unklar",
  }[normalized] || "Jellyfin wird geprüft";
  badge.hidden = false;
}

function updateFpJellyfinBadges() {
  const resultsBySlug = new Map(state.fp.results.map((result) => [result.slug, result]));
  for (const row of document.querySelectorAll("#fp-results .row")) {
    const result = resultsBySlug.get(row.dataset.slug);
    const badge = row.querySelector(".jellyfin-badge");
    if (result && badge) setFpJellyfinBadge(badge, mediaJellyfinStatus(result));
    const posterBadge = row.querySelector(".result-card-library-badge");
    if (result && posterBadge) setFpPosterJellyfinBadge(posterBadge, mediaJellyfinStatus(result));
  }
  const selected = resultsBySlug.get(state.fp.selectedSlug) || homeMovieBySlug(state.fp.selectedSlug);
  if (selected) {
    const selectedStatus = mediaJellyfinStatus(selected);
    setFpDetailJellyfinStatus(selectedStatus === "owned" ? true
      : selectedStatus === "missing" ? false : selectedStatus);
    const movie = state.fp.moviesCache[selected.slug]
      || metadataPreviewMovie(state.fp.metadataCache[selected.slug] || basicMovieMetadata(selected));
    configureFpDetailAction(selected.slug, movie, !state.fp.moviesCache[selected.slug]);
  }
  if (fpSmartFilters().availability !== "all") applyFpSmartFilters();
}

function mediaCardInitials(title) {
  const words = String(title || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "RD";
  return (words.length === 1 ? words[0].slice(0, 2) : words.slice(0, 2).map((word) => word[0]).join(""))
    .toUpperCase();
}

function syncResultCardPoster(visual, media) {
  const current = visual.querySelector(".result-card-poster:not(.is-pending-poster)");
  // Das Anbieterposter startet sofort. Sobald TMDB ein besseres Poster liefert,
  // wird es parallel geladen und erst nach erfolgreichem Decode ausgetauscht.
  const coverCandidates = api.coverThumbnailCandidates(media?.cover_url);
  if (!coverCandidates.length) return;

  const posterKey = coverCandidates.join("\n");
  if (current?.dataset.posterKey === posterKey) return;
  const pending = visual.querySelector(".result-card-poster.is-pending-poster");
  if (pending?.dataset.posterKey === posterKey) return;
  pending?.remove();

  const image = document.createElement("img");
  image.className = "result-card-poster";
  image.dataset.posterKey = posterKey;
  image.alt = "";
  image.loading = "lazy";
  image.fetchPriority = "auto";
  image.decoding = "async";
  // Auch das allererste Poster bleibt bis zum vollständigen Decode unsichtbar.
  // Der ruhige Platzhalter darunter verhindert progressive Bildaufbauten und
  // helle Zwischenframes beim schnellen Scrollen.
  image.classList.add("is-pending-poster");
  image.addEventListener("load", async () => {
    try { await image.decode(); } catch (e) { /* Das Bild ist bereits nutzbar. */ }
    if (!image.isConnected) return;
    requestAnimationFrame(() => {
      if (!image.isConnected) return;
      image.classList.remove("is-pending-poster");
      if (!current?.isConnected) return;
      let cleaned = false;
      const removePreviousPoster = () => {
        if (cleaned) return;
        cleaned = true;
        current.remove();
      };
      image.addEventListener("transitionend", removePreviousPoster, { once: true });
      window.setTimeout(removePreviousPoster, 360);
    });
  }, { once: true });
  scheduleResultPoster(image, coverCandidates);
  visual.appendChild(image);
}

function createResultCardVisual(media, title, kind, jellyfinStatus = "checking") {
  const visual = document.createElement("span");
  visual.className = "result-card-visual";

  const fallback = document.createElement("span");
  fallback.className = "result-card-fallback";
  fallback.textContent = mediaCardInitials(title);
  visual.appendChild(fallback);

  syncResultCardPoster(visual, media);

  const kindMark = document.createElement("span");
  kindMark.className = "result-card-kind";
  kindMark.textContent = kind === "series" ? "S" : "F";
  const openMark = document.createElement("span");
  openMark.className = "result-card-open";
  openMark.textContent = "↗";
  openMark.setAttribute("aria-hidden", "true");
  visual.append(kindMark, openMark);
  const libraryBadge = document.createElement("span");
  setFpPosterJellyfinBadge(libraryBadge, jellyfinStatus);
  visual.appendChild(libraryBadge);
  return visual;
}

function activateResultCard(row, callback) {
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-haspopup", "dialog");
  row.addEventListener("click", callback);
  row.addEventListener("keydown", (event) => {
    if (event.target !== row || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    callback();
  });
}

function fpResultMedia(result) {
  return {
    ...result,
    ...(state.fp.metadataCache[result.slug] || {}),
    ...(state.fp.moviesCache[result.slug] || {}),
    slug: result.slug,
  };
}

function fpResultAvailability(result) {
  const movie = state.fp.moviesCache[result.slug];
  const queued = state.queuedSlugs.has(result.slug);
  if (queued) return { label: "In Queue", tag: "picked" };
  if (movie) {
    if (!movie.hosters || movie.hosters.length === 0) return { label: "Kein Hoster", tag: "novoe" };
    return {
      label: movie.provider_count ? `${movie.provider_count} Anbieter` : (movie.hoster_label || "Bereit"),
      tag: "ready",
    };
  }
  if (String(result.slug || "").startsWith("tmdb:")) return { label: "Auswählen", tag: "idle" };
  if (state.fp.pendingPreload?.has(result.slug)) return { label: "Lädt …", tag: "pending" };
  return { label: "Wird geprüft", tag: "idle" };
}

function findFpResultCard(slug) {
  return [...document.querySelectorAll("#fp-results .result-card")]
    .find((row) => row.dataset.slug === slug) || null;
}

function updateFpResultCard(slug) {
  const result = state.fp.results.find((item) => item.slug === slug);
  const row = findFpResultCard(slug);
  if (!result || !row) return;
  const visual = row.querySelector(".result-card-visual");
  const media = fpResultMedia(result);
  row.setAttribute("aria-label", [result.title, result.year].filter(Boolean).join(", "));
  const title = row.querySelector(".result-card-title");
  if (title) title.textContent = result.title;
  if (visual) {
    syncResultCardPoster(visual, media);
    const posterBadge = visual.querySelector(".result-card-library-badge");
    if (posterBadge) setFpPosterJellyfinBadge(posterBadge, mediaJellyfinStatus(result));
  }
  const availability = fpResultAvailability(result);
  const stateLabel = row.querySelector(".result-card-state");
  if (stateLabel) {
    stateLabel.className = `result-card-state status-${availability.tag}`;
    stateLabel.textContent = availability.label;
  }
  const subtitle = row.querySelector(".result-card-subtitle");
  if (subtitle) {
    const resolved = state.fp.moviesCache[result.slug];
    subtitle.textContent = (resolved?.source_providers || []).map((source) => source.label).join(" · ")
      || (media.genres || []).slice(0, 2).join(" · ")
      || "Film";
  }
  const rating = row.querySelector(".result-card-rating");
  if (rating) rating.textContent = media.rating ? `★ ${media.rating}` : "★ —";
  const yearEl = row.querySelector(".result-card-year");
  if (yearEl) yearEl.textContent = fpResultYear(result) || "Jahr offen";
}

function syncFpDetailQueueAction() {
  const slug = state.fp.selectedSlug;
  const detailPanel = document.getElementById("fp-detail-panel");
  if (!slug || detailPanel.classList.contains("is-empty")) return;
  const movie = state.fp.moviesCache[slug];
  const metadata = state.fp.metadataCache[slug];
  if (movie) configureFpDetailAction(slug, movie, false);
  else if (metadata) configureFpDetailAction(slug, metadataPreviewMovie(metadata), true);
}

function syncFpQueueIndicators() {
  for (const result of state.fp.results) {
    const row = findFpResultCard(result.slug);
    if (!row) continue;
    const queued = state.queuedSlugs.has(result.slug);
    row.classList.toggle("queued", queued);
    const toggle = row.querySelector(".result-queue-toggle");
    if (toggle) {
      toggle.classList.toggle("is-queued", queued);
      toggle.textContent = queued ? "✓" : "+";
      toggle.setAttribute("aria-label", queued
        ? `${result.title} aus der Queue entfernen`
        : `${result.title} zur Queue hinzufügen`);
    }
    const availability = fpResultAvailability(result);
    const stateLabel = row.querySelector(".result-card-state");
    if (stateLabel) {
      stateLabel.className = `result-card-state status-${availability.tag}`;
      stateLabel.textContent = availability.label;
    }
  }
  if (state.fp.results.length) {
    document.getElementById("fp-status").textContent = fpStatusMessage();
  }
  syncFpDetailQueueAction();
  if (fpSmartFilters().availability === "queued") applyFpSmartFilters();
}

function updateFpResultSelection() {
  for (const row of document.querySelectorAll("#fp-results .row")) {
    const selected = row.dataset.slug === state.fp.selectedSlug;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-current", String(selected));
  }
}

function renderFpResults(appendFrom = 0) {
  const container = document.getElementById("fp-results");
  if (appendFrom <= 0) {
    discardObservedResultPosters(container);
    container.innerHTML = "";
  }

  for (const result of state.fp.results.slice(appendFrom)) {
    const selected = result.slug === state.fp.selectedSlug;
    const queued = state.queuedSlugs.has(result.slug);
    const availability = fpResultAvailability(result);
    const media = fpResultMedia(result);

    const row = document.createElement("div");
    row.className = "row result-card" + (selected ? " selected" : "") + (queued ? " queued" : "");
    row.dataset.slug = result.slug;
    row.setAttribute("aria-current", String(selected));
    row.setAttribute("aria-label", [result.title, result.year].filter(Boolean).join(", "));

    const visual = createResultCardVisual(media, result.title, "movie", mediaJellyfinStatus(result));

    const copy = document.createElement("span");
    copy.className = "result-card-copy";
    const title = document.createElement("strong");
    title.className = "result-card-title";
    title.translate = false;
    title.textContent = result.title;
    const subtitle = document.createElement("span");
    subtitle.className = "result-card-subtitle";
    subtitle.textContent = (media.genres || []).slice(0, 2).join(" · ") || "Film";
    const meta = document.createElement("span");
    meta.className = "result-card-meta";
    const rating = document.createElement("span");
    rating.className = "result-card-rating";
    rating.textContent = media.rating ? `★ ${media.rating}` : "★ —";
    const year = document.createElement("span");
    year.className = "result-card-year";
    year.textContent = fpResultYear(result) || "Jahr offen";
    const status = document.createElement("span");
    status.className = `result-card-state status-${availability.tag}`;
    status.textContent = availability.label;
    const jellyfin = document.createElement("span");
    setFpJellyfinBadge(jellyfin, mediaJellyfinStatus(result));
    meta.append(rating, year, status, jellyfin);
    copy.append(title, subtitle, meta);

    const queueToggle = document.createElement("button");
    queueToggle.type = "button";
    queueToggle.className = "pick-flag result-queue-toggle" + (queued ? " is-queued" : "");
    queueToggle.textContent = queued ? "✓" : "+";
    queueToggle.setAttribute("aria-label", queued
      ? `${result.title} aus der Queue entfernen`
      : `${result.title} zur Queue hinzufügen`);
    queueToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleFpPick(result.slug);
    });

    row.append(visual, copy, queueToggle);
    activateResultCard(row, () => selectFpRow(result.slug));
    container.appendChild(row);
  }

  applyFpSmartFilters();
}

function applyFpResults(data, { append = false, metadataPrepared = false } = {}) {
  const incoming = Array.isArray(data.results) ? data.results : [];
  const renderedCards = document.querySelectorAll("#fp-results .result-card");
  const preserveRenderedCards = !append
    && incoming.length === state.fp.results.length
    && renderedCards.length === incoming.length
    && incoming.every((result, index) => result.slug === state.fp.results[index]?.slug);
  for (const result of incoming) {
    if (result?.tmdb_id) {
      state.fp.metadataCache[result.slug] = mergeFpMetadata(
        state.fp.metadataCache[result.slug], result,
      );
    }
  }
  const appendFrom = append ? state.fp.results.length : 0;
  state.fp.results = append
    ? mergeCatalogItems(state.fp.results, incoming, (item) => item.slug)
    : incoming;
  const responsePage = Number(data.page || 1);
  // Eine wegen langsamer Quellen nur teilweise gelieferte Folgeseite wird
  // beim naechsten Scrollen erneut angefordert. Bereits sichtbare Treffer
  // bleiben dank mergeCatalogItems stabil und fehlende Filme gehen nicht
  // durch ein vorschnelles Weiterschalten auf die naechste Seite verloren.
  state.fp.page = append && data.page_complete === false
    ? Math.max(1, responsePage - 1)
    : responsePage;
  state.fp.category = data.category ?? state.fp.category;
  state.fp.lastPageFull = Boolean(data.has_more ?? data.last_page_full);
  state.fp.sources = mergeCatalogSources(state.fp.sources, data.sources, append);
  state.fp.loadingMore = false;
  state.fp.loadError = "";
  if (!append) state.fp.selectedSlug = null;
  if (!append) state.fp.metadataRequestSeq += 1;
  const metadataItems = fpMetadataPreloadItems(incoming);
  const pendingSlugs = new Set(
    metadataPrepared ? [] : metadataItems.map((item) => item.slug),
  );
  state.fp.pendingPreload = append && state.fp.pendingPreload
    ? state.fp.pendingPreload
    : new Set();
  for (const slug of pendingSlugs) state.fp.pendingPreload.add(slug);
  if (preserveRenderedCards) {
    for (const result of incoming) updateFpResultCard(result.slug);
    document.getElementById("fp-status").textContent = fpStatusMessage();
  } else {
    renderFpResults(appendFrom);
  }
  void refreshFpJellyfinStatus(incoming);
  refreshMovieFeatureCandidates();
  updateFpInfiniteState();
  if (metadataItems.length && !metadataPrepared) {
    void preloadTmdbMetadata(state.fp.metadataRequestSeq, metadataItems);
  } else if (!state.fp.pendingPreload.size) {
    state.fp.pendingPreload = null;
  }
}

async function loadFpMetadata(item, requestId = state.fp.requestSeq) {
  let metadata = state.fp.metadataCache[item.slug];
  if (metadata && state.fp.selectedSlug === item.slug) {
    showFpDetail(item.slug, metadataPreviewMovie(metadata), true);
  }
  try {
    if (!metadata?.details_loaded) {
      const detailResponse = await api.tmdbMovie({
        slug: item.slug,
        title: item.title,
        year: item.year || "",
        tmdb_id: metadata?.tmdb_id || item.tmdb_id || null,
      });
      if (requestId !== state.fp.requestSeq) return metadata || null;
      if (detailResponse.movie) {
        metadata = detailResponse.movie;
        state.fp.metadataCache[item.slug] = metadata;
        updateFpResultCard(item.slug);
        refreshMovieFeatureCandidates();
        if (state.fp.selectedSlug === item.slug) showFpDetail(item.slug, metadataPreviewMovie(metadata), true);
      } else if (state.fp.selectedSlug === item.slug) {
        showFpDetail(item.slug, metadataPreviewMovie(basicMovieMetadata({ ...item, ...metadata })), true);
        setFpDetailAvailability("Metadaten nicht verfügbar", "error");
      }
    }
    if (metadata?.tmdb_id) void refreshFpJellyfinStatus([item]);
    return metadata || null;
  } catch (e) {
    if (requestId === state.fp.requestSeq && state.fp.selectedSlug === item.slug) {
      showFpDetail(
        item.slug,
        metadataPreviewMovie(basicMovieMetadata({ ...item, ...metadata })),
        true,
      );
      setFpDetailAvailability("Metadaten konnten nicht geladen werden", "error");
    }
    return metadata || null;
  }
}

function clearFpSearchContext() {
  state.fp.searchActive = false;
  state.fp.searchReturn = null;
  document.getElementById("fp-search").value = "";
  syncSearchClearButtons();
  closeSearchSuggestions("fp-search-suggestions", "fp-search");
}

function rememberFpSearchContext() {
  if (state.fp.searchActive || state.fp.searchReturn) return;
  if (!state.fp.category && !state.fp.results.length) return;
  state.fp.searchReturn = {
    results: state.fp.results.slice(),
    category: state.fp.category,
    page: state.fp.page,
    lastPageFull: state.fp.lastPageFull,
    activeGenre: state.fp.activeGenre,
    selectedSlug: state.fp.selectedSlug,
    sources: state.fp.sources.slice(),
  };
}

async function restoreFpSearchContext() {
  if (!state.fp.searchActive && !state.fp.searchReturn) return;
  const saved = state.fp.searchReturn;
  state.fp.searchActive = false;
  state.fp.searchReturn = null;
  document.getElementById("fp-search").value = "";
  ++state.fp.requestSeq;
  if (!saved) {
    await fpShowList("new");
    return;
  }
  applyFpResults({
    results: saved.results,
    category: saved.category,
    page: saved.page,
    has_more: saved.lastPageFull,
    sources: saved.sources,
  });
  setActiveGenreFilter(saved.activeGenre);
  state.fp.selectedSlug = saved.selectedSlug;
  renderFpResults();
}

async function fpSearch() {
  const q = document.getElementById("fp-search").value.trim();
  if (!q) {
    await restoreFpSearchContext();
    return;
  }
  rememberSearch(q, "movie");
  closeSearchSuggestions("fp-search-suggestions", "fp-search");
  rememberFpSearchContext();
  state.fp.searchActive = true;
  state.fp.category = null;
  state.fp.lastPageFull = false;
  state.fp.loadingMore = false;
  state.fp.loadError = "";
  updateFpInfiniteState();
  refreshMovieFeatureCandidates();
  document.getElementById("fp-status").textContent = `Suche nach «${q}» …`;
  setActiveGenreFilter("Alle Genres");
  const requestId = ++state.fp.requestSeq;
  try {
    const data = await api.movies({ mode: "search", query: q });
    if (requestId !== state.fp.requestSeq) return;
    applyFpResults(data);
  } catch (error) {
    // Ohne diesen Zweig blieb der Status bei «Suche nach …» stehen: eine
    // abgelaufene Sitzung oder ein Providerfehler sah aus wie „kein Treffer“.
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadingMore = false;
    state.fp.loadError = error.message;
    updateFpInfiniteState();
    document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
  }
}

async function fpShowList(category) {
  clearFpSearchContext();
  state.fp.category = category;
  state.fp.lastPageFull = false;
  state.fp.loadingMore = true;
  state.fp.loadError = "";
  updateFpInfiniteState();
  refreshMovieFeatureCandidates();
  setActiveGenreFilter("Alle Genres");
  document.getElementById("fp-status").textContent = `Lade ${category === "new" ? "Neu" : "Top"}-Filme …`;
  const requestId = ++state.fp.requestSeq;
  try {
    const data = await api.movies({ mode: category, page: 1 });
    if (requestId !== state.fp.requestSeq) return;
    applyFpResults(data);
    state.fp.previewFromHome = false;
    state.fp.lastCatalogRefreshAt = Date.now();
  } catch (error) {
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadingMore = false;
    state.fp.loadError = error.message;
    updateFpInfiniteState();
    document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
  }
}

function ensureFpResults() {
  syncFpCatalogFromHome();
  if (state.fp.results.length) {
    if (!document.getElementById("fp-results").childElementCount) renderFpResults();
    refreshFpCatalogInBackground();
    return;
  }
  if (state.fp.loadingMore) return;
  fpShowList("new");
}

async function fpGenreChange(genre) {
  clearFpSearchContext();
  if (genre === "Alle Genres") {
    await fpShowList("new");
    return;
  }
  state.fp.category = "genre";
  state.fp.lastPageFull = false;
  state.fp.loadingMore = true;
  state.fp.loadError = "";
  updateFpInfiniteState();
  refreshMovieFeatureCandidates();
  setActiveGenreFilter(genre);
  document.getElementById("fp-status").textContent = `Lade Genre ${genre} …`;
  const requestId = ++state.fp.requestSeq;
  try {
    const data = await api.movies({ mode: "genre", genre, page: 1 });
    if (requestId !== state.fp.requestSeq) return;
    applyFpResults(data);
  } catch (error) {
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadingMore = false;
    state.fp.loadError = error.message;
    updateFpInfiniteState();
    document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
  }
}

async function loadNextFpPage() {
  if (
    state.tab !== "filme"
    || !state.fp.category
    || state.fp.searchActive
    || state.fp.loadingMore
    || !state.fp.lastPageFull
  ) return;
  const newPage = state.fp.page + 1;
  const params = state.fp.category === "genre"
    ? { mode: "genre", genre: state.fp.activeGenre, page: newPage }
    : { mode: state.fp.category, page: newPage };
  const requestId = ++state.fp.requestSeq;
  state.fp.loadingMore = true;
  state.fp.loadError = "";
  updateFpInfiniteState();
  try {
    const data = await api.movies(params);
    if (requestId !== state.fp.requestSeq) return;
    // Inhalte zuerst stabil anhaengen. Poster und TMDB-Daten laden danach
    // parallel pro Karte; die langsamste Bildantwort sperrt nicht mehr die
    // komplette 32er-Seite.
    applyFpResults(data, { append: true });
  } catch (error) {
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadError = error.message;
    document.getElementById("fp-status").textContent = `Nachladen fehlgeschlagen: ${error.message}`;
  } finally {
    if (requestId === state.fp.requestSeq) {
      state.fp.loadingMore = false;
      updateFpInfiniteState();
    }
  }
}

async function toggleFpPick(slug) {
  if (fpQueueMutations.has(slug)) return;
  fpQueueMutations.add(slug);
  refreshFpQueuePresentation();
  try {
    if (state.queuedSlugs.has(slug)) {
      const resp = await api.queueRemove(slug);
      setFpDownloadFeedback(slug);
      refreshQueueUiAfterChange(resp);
      return;
    }
    setFpDownloadFeedback(slug);
    const resp = await api.queueAdd([slug]);
    refreshQueueUiAfterChange(resp);
    if (applyFpQueueAddResponse(slug, resp)) {
      const item = state.fp.moviesCache[slug]
        || state.fp.metadataCache[slug]
        || state.fp.results.find((movie) => movie.slug === slug)
        || homeMovieBySlug(slug);
      trackDiscoveryPreference("movie", { ...item, slug }, 5, "download");
    }
    if (!state.fp.moviesCache[slug]) {
      void api.movie(slug).then((movie) => {
        state.fp.moviesCache[slug] = movie;
        updateFpResultCard(slug);
        if (state.fp.selectedSlug === slug) showFpDetail(slug, movie);
      }).catch(() => { /* server logs */ });
    }
  } catch (error) {
    const reason = error?.message || "Unbekannter Fehler";
    setFpDownloadFeedback(slug, `Download nicht gestartet: ${reason}`, "error");
    setDownloadState("error", "Download nicht gestartet", reason, 0);
    console.warn("Film konnte nicht zur Queue hinzugefügt werden:", error);
  } finally {
    fpQueueMutations.delete(slug);
    refreshFpQueuePresentation();
    const movie = state.fp.moviesCache[slug]
      || metadataPreviewMovie(state.fp.metadataCache[slug] || basicMovieMetadata(
        state.fp.results.find((item) => item.slug === slug) || homeMovieBySlug(slug) || {},
      ));
    if (state.fp.selectedSlug === slug) {
      configureFpDetailAction(slug, movie, !state.fp.moviesCache[slug]);
    }
  }
}

async function selectFpRow(slug, initialItem = null) {
  state.fp.selectedSlug = slug;
  updateFpResultSelection();
  const movie = state.fp.moviesCache[slug];
  const item = state.fp.results.find((r) => r.slug === slug)
    || homeMovieBySlug(slug)
    || initialItem;
  if (!item) return;
  const metadata = state.fp.metadataCache[slug];
  trackDiscoveryPreference("movie", { ...item, ...metadata, slug }, 0.8, "open");
  if (movie) showFpDetail(slug, movie);
  else if (metadata) showFpDetail(slug, metadataPreviewMovie(metadata), true);
  else {
    showFpDetail(slug, basicMovieMetadata(item), true);
    setFpDetailAvailability("Metadaten werden geladen", "loading");
  }
  openMediaModal("fp-detail-modal", findFpResultCard(slug));
  if (movie) return;
  await loadFpMetadata(item);
  if (!String(slug).startsWith("tmdb:") || state.fp.selectedSlug !== slug) return;
  setFpDetailAvailability("Alle Anbieter werden durchsucht", "loading");
  try {
    const resolved = await api.movie(slug);
    state.fp.moviesCache[slug] = resolved;
    updateFpResultCard(slug);
    if (state.fp.selectedSlug === slug) showFpDetail(slug, resolved);
  } catch (error) {
    console.warn("Anbietersuche fehlgeschlagen:", error);
    if (state.fp.selectedSlug === slug) {
      const preview = state.fp.metadataCache[slug] || basicMovieMetadata(item);
      showFpDetail(slug, metadataPreviewMovie(preview), true);
      setFpDetailAvailability(error.message, "error");
    }
  }
}

function basicMovieMetadata(item) {
  return {
    ...item,
    title: item.title,
    year: item.year || "",
    cover_url: item.cover_url || "",
    backdrop_url: item.backdrop_url || "",
    description: item.description || "",
    genres: Array.isArray(item.genres) ? item.genres : [],
    runtime: item.runtime || "",
  };
}

function metadataPreviewMovie(metadata) {
  return {
    ...metadata,
    hosters: [],
    hoster_route: "wird geladen",
    hoster_score: null,
    hoster_fallback_count: 0,
  };
}

function renderFpDetailItems(id, values, emptyText = "") {
  const element = document.getElementById(id);
  element.innerHTML = "";
  const items = (values || []).filter(Boolean);
  if (!items.length && emptyText) items.push(emptyText);
  for (const value of items) {
    const item = document.createElement("span");
    item.textContent = value;
    element.appendChild(item);
  }
}

function setFpDetailAvailability(text, state = "ready") {
  const badge = document.getElementById("fp-detail-availability");
  badge.textContent = text;
  badge.className = `detail-availability is-${state}`;
}

function setFpDetailJellyfinStatus(owned) {
  const badge = document.getElementById("fp-detail-jellyfin");
  const label = badge.querySelector("strong");
  badge.className = "detail-jellyfin";
  if (owned === true) {
    badge.classList.add("is-owned");
    label.textContent = "In Jellyfin vorhanden";
    return;
  }
  if (owned === false) {
    badge.classList.add("is-missing");
    label.textContent = "Nicht in Jellyfin";
    return;
  }
  if (owned === "unavailable") {
    label.textContent = "Jellyfin nicht erreichbar";
    return;
  }
  if (owned === "blocked") {
    label.textContent = "Jellyfin-Statusanfrage blockiert";
    return;
  }
  if (owned === "unconfigured") {
    label.textContent = "Jellyfin nicht eingerichtet";
    return;
  }
  badge.classList.add("is-checking");
  label.textContent = "Jellyfin wird geprüft";
}

function fpDetailJellyfinValue(slug, movie) {
  const catalogItem = state.fp.results.find((item) => item.slug === slug)
    || homeMovieBySlug(slug);
  if (typeof catalogItem?.in_jellyfin === "boolean") return catalogItem.in_jellyfin;
  if (typeof movie?.in_jellyfin === "boolean") return movie.in_jellyfin;
  return null;
}

function formatMovieDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) return value || "—";
  const date = new Date(`${value}T00:00:00Z`);
  return new Intl.DateTimeFormat(i18n.locale(), {
    day: "2-digit", month: "long", year: "numeric", timeZone: "UTC",
  }).format(date);
}

function formatMovieNumber(value) {
  const number = Number(value || 0);
  return number > 0 ? new Intl.NumberFormat(i18n.locale()).format(number) : "";
}

function formatMovieMoney(value) {
  const number = Number(value || 0);
  if (number <= 0) return "";
  return new Intl.NumberFormat(i18n.locale(), {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
    notation: number >= 1_000_000 ? "compact" : "standard",
  }).format(number);
}

function movieCertificationLabel(movie) {
  const certification = String(movie.certification || "").trim();
  if (!certification) return "Nicht angegeben";
  const country = String(movie.certification_country || "").toUpperCase();
  if (country === "DE") return `FSK ${certification}`;
  return country ? `${country} ${certification}` : certification;
}

function movieStatusLabel(status) {
  return ({
    Released: "Veröffentlicht",
    "Post Production": "Postproduktion",
    "In Production": "In Produktion",
    Planned: "Geplant",
    Rumored: "Gerücht",
    Canceled: "Abgebrochen",
  })[status] || status || "";
}

function setFpDetailText(id, value, fallback = "—") {
  document.getElementById(id).textContent = value || fallback;
}

function renderFpCast(cast, tmdbUrl) {
  const section = document.getElementById("fp-detail-cast-section");
  const container = document.getElementById("fp-detail-cast");
  const link = document.getElementById("fp-detail-tmdb-link");
  const members = Array.isArray(cast) ? cast.filter((member) => member?.name) : [];
  section.hidden = !members.length;
  container.innerHTML = "";
  const safeTmdbUrl = /^https:\/\/www\.themoviedb\.org\/movie\/\d+$/.test(tmdbUrl || "");
  link.href = safeTmdbUrl ? tmdbUrl : "https://www.themoviedb.org";
  if (!members.length) return;
  for (const member of members) {
    const card = document.createElement("div");
    card.className = "detail-cast-card";
    const portrait = document.createElement("div");
    portrait.className = "detail-cast-portrait";
    if (member.profile_url) {
      const image = document.createElement("img");
      image.src = api.coverUrl(member.profile_url);
      image.alt = "";
      image.loading = "lazy";
      portrait.appendChild(image);
    } else {
      portrait.textContent = member.name
        .split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
    }
    const copy = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = member.name;
    const role = document.createElement("small");
    role.textContent = member.character || "Besetzung";
    copy.append(name, role);
    card.append(portrait, copy);
    container.appendChild(card);
  }
}

let fpDetailHeroTrailerTimer = null;
let fpDetailHeroTrailerToken = 0;
let fpDetailHeroTrailerCurrentTime = 0;
let fpDetailHeroTrailerKey = "";
const completedFilmHeroTrailers = new Set();
const completedSeriesHeroTrailers = new Set();
const FP_TRAILER_MUTED_KEY = "royal-trailer-muted-v1";
const heroTrailerTimeResolvers = new Map();

function loadFpDetailHeroTrailerMuted() {
  try {
    const saved = localStorage.getItem(FP_TRAILER_MUTED_KEY);
    return saved === null ? true : saved !== "false";
  } catch {
    return true;
  }
}

let fpDetailHeroTrailerMuted = loadFpDetailHeroTrailerMuted();

function fpTrailerYoutubeKey(movie) {
  const trailer = movie?.trailer;
  const key = String(trailer?.key || "").trim();
  return trailer?.site === "YouTube" && /^[A-Za-z0-9_-]{6,20}$/.test(key) ? key : "";
}

function setFpDetailHeroTrailerMuted(muted, { persist = false } = {}) {
  fpDetailHeroTrailerMuted = Boolean(muted);
  if (persist) {
    try {
      localStorage.setItem(FP_TRAILER_MUTED_KEY, String(fpDetailHeroTrailerMuted));
    } catch {
      // Gesperrter Browser-Speicher darf die Trailersteuerung nicht blockieren.
    }
  }
  const enabled = !fpDetailHeroTrailerMuted;
  for (const [frameId, buttonId] of [
    ["fp-detail-hero-frame", "fp-detail-hero-mute"],
    ["series-detail-hero-frame", "series-detail-hero-mute"],
    ["home-card-dock-preview", "home-card-dock-mute"],
  ]) {
    const frame = document.getElementById(frameId);
    const button = document.getElementById(buttonId);
    frame?.contentWindow?.postMessage(JSON.stringify({
      event: "command",
      func: fpDetailHeroTrailerMuted ? "mute" : "unMute",
      args: [],
    }), "*");
    if (!button) continue;
    button.setAttribute("aria-pressed", String(enabled));
    button.setAttribute("aria-label", enabled ? "Trailerton ausschalten" : "Trailerton einschalten");
    button.title = enabled ? "Trailerton ausschalten" : "Trailerton einschalten";
    button.querySelector("span").textContent = enabled ? "🔊" : "🔇";
  }
}

window.addEventListener("message", (event) => {
  if (!["https://www.youtube-nocookie.com", "https://www.youtube.com"].includes(event.origin)) return;
  let payload = event.data;
  if (typeof payload === "string") {
    try { payload = JSON.parse(payload); } catch { return; }
  }
  if (handleTrailerPlayerMessage(event, payload)) return;
  const playerState = payload?.event === "onStateChange"
    ? Number(payload.info)
    : Number(payload?.info?.playerState);
  if (Number.isFinite(playerState)) {
    for (const [frameId, kind] of [
      ["fp-detail-hero-frame", "film"],
      ["series-detail-hero-frame", "series"],
    ]) {
      const frame = document.getElementById(frameId);
      if (!frame || event.source !== frame.contentWindow) continue;
      if (playerState === 1) {
        // Erst nach echtem Videostart einblenden: So bleibt YouTubes großes
        // Start-/Pause-Piktogramm hinter dem bereits sichtbaren Wallpaper.
        window.setTimeout(() => {
          if (!frame.getAttribute("src")) return;
          frame.parentElement?.classList.add("is-playing");
          frame.closest(".media-modal-panel")?.classList.add("is-trailer-playing");
        }, 350);
      } else if (playerState === 0) {
        if (kind === "film") {
          completedFilmHeroTrailers.add(fpDetailHeroTrailerKey);
          stopFpDetailHeroTrailer();
        } else {
          completedSeriesHeroTrailers.add(seriesDetailHeroTrailerKey);
          stopSeriesDetailHeroTrailer();
        }
      }
      break;
    }
  }
  const currentTime = Number(payload?.info?.currentTime);
  if (!Number.isFinite(currentTime) || currentTime < 0) return;
  for (const [frameId, kind] of [
    ["fp-detail-hero-frame", "film"],
    ["series-detail-hero-frame", "series"],
  ]) {
    const frame = document.getElementById(frameId);
    if (!frame || event.source !== frame.contentWindow) continue;
    if (kind === "film") fpDetailHeroTrailerCurrentTime = currentTime;
    else seriesDetailHeroTrailerCurrentTime = currentTime;
    const resolve = heroTrailerTimeResolvers.get(frameId);
    if (resolve) {
      heroTrailerTimeResolvers.delete(frameId);
      resolve(currentTime);
    }
    break;
  }
});

function listenForHeroTrailerTime(frame) {
  if (!frame?.contentWindow) return;
  const subscribe = () => frame.contentWindow?.postMessage(JSON.stringify({
    event: "listening",
    id: frame.id,
    channel: frame.id,
  }), "*");
  subscribe();
  window.setTimeout(subscribe, 250);
  window.setTimeout(subscribe, 750);
}

function readHeroTrailerCurrentTime(frameId, fallback = 0) {
  const frame = document.getElementById(frameId);
  if (!frame?.getAttribute("src") || !frame.contentWindow) return Promise.resolve(fallback);
  return new Promise((resolve) => {
    let finished = false;
    const finish = (value) => {
      if (finished) return;
      finished = true;
      heroTrailerTimeResolvers.delete(frameId);
      resolve(Number.isFinite(value) ? value : fallback);
    };
    heroTrailerTimeResolvers.set(frameId, finish);
    listenForHeroTrailerTime(frame);
    frame.contentWindow.postMessage(JSON.stringify({
      event: "command", func: "getCurrentTime", args: [],
    }), "*");
    window.setTimeout(() => finish(fallback), 500);
  });
}

function stopFpDetailHeroTrailer() {
  fpDetailHeroTrailerToken += 1;
  if (fpDetailHeroTrailerTimer) clearTimeout(fpDetailHeroTrailerTimer);
  fpDetailHeroTrailerTimer = null;
  const panel = document.getElementById("fp-detail-panel");
  const shell = document.getElementById("fp-detail-hero-trailer");
  const frame = document.getElementById("fp-detail-hero-frame");
  const muteButton = document.getElementById("fp-detail-hero-mute");
  shell.classList.remove("is-playing");
  panel.classList.remove("is-trailer-playing");
  muteButton.hidden = true;
  frame.onload = null;
  frame.removeAttribute("src");
  shell.hidden = true;
  setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
  fpDetailHeroTrailerKey = "";
}

function scheduleFpDetailHeroTrailer(movie) {
  stopFpDetailHeroTrailer();
  const key = fpTrailerYoutubeKey(movie);
  if (
    !key
    || !heroTrailerAutoplayEnabled()
    || completedFilmHeroTrailers.has(key)
    || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  ) return;
  fpDetailHeroTrailerKey = key;
  fpDetailHeroTrailerCurrentTime = 0;
  const token = fpDetailHeroTrailerToken;
  fpDetailHeroTrailerTimer = setTimeout(() => {
    if (
      token !== fpDetailHeroTrailerToken
      || document.getElementById("fp-detail-modal").hidden
    ) return;
    const shell = document.getElementById("fp-detail-hero-trailer");
    const frame = document.getElementById("fp-detail-hero-frame");
    const muteButton = document.getElementById("fp-detail-hero-mute");
    setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
    shell.hidden = false;
    frame.onload = () => {
      if (token !== fpDetailHeroTrailerToken) return;
      listenForHeroTrailerTime(frame);
      muteButton.hidden = false;
      setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
    };
    frame.src =
      `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
      + `?autoplay=1&mute=1&controls=0&playsinline=1&rel=0&modestbranding=1`
      + `&disablekb=1&fs=0&iv_load_policy=3&enablejsapi=1`
      + `&origin=${encodeURIComponent(window.location.origin)}`;
  }, 2000);
}

function closeFpTrailerModal(restoreFocus = true) {
  const modal = document.getElementById("fp-trailer-modal");
  if (!modal || modal.hidden) return;
  const returnFocus = modal._returnFocus;
  modal.classList.remove("is-open");
  modal.hidden = true;
  document.body.classList.remove("trailer-modal-open");
  document.getElementById("fp-trailer-frame")?.removeAttribute("src");
  resetTrailerPlayerState();
  if (restoreFocus && returnFocus instanceof HTMLElement && returnFocus.isConnected) {
    returnFocus.focus();
  }
}

function openFpTrailerModal(movie, trigger, heroKind = "film") {
  const trailer = movie?.trailer;
  const key = String(trailer?.key || "").trim();
  if (trailer?.site !== "YouTube" || !/^[A-Za-z0-9_-]{6,20}$/.test(key)) return;
  const isSeriesHero = heroKind === "series" && seriesDetailHeroTrailerKey === key;
  const isFilmHero = heroKind === "film" && fpDetailHeroTrailerKey === key;
  const startAt = isSeriesHero
    ? seriesDetailHeroTrailerCurrentTime
    : isFilmHero ? fpDetailHeroTrailerCurrentTime : 0;
  stopFpDetailHeroTrailer();
  stopSeriesDetailHeroTrailer();
  openTrailerPlayer(movie, key, startAt, trigger);
}

function configureFpTrailer(movie) {
  const button = document.getElementById("fp-detail-trailer");
  const trailerKey = fpTrailerYoutubeKey(movie);
  const available = Boolean(trailerKey);
  const trailer = movie?.trailer;
  button.hidden = !available;
  const trailerMovie = available
    ? { ...movie, trailer: { ...trailer, key: trailerKey } }
    : null;
  button.onclick = trailerMovie ? () => openFpTrailerModal(trailerMovie, button, "film") : null;
  if (!available) {
    closeFpTrailerModal(false);
    stopFpDetailHeroTrailer();
  } else {
    scheduleFpDetailHeroTrailer(trailerMovie);
  }
}

function configureFpDetailAction(slug, movie, metadataOnly = false) {
  const addBtn = document.getElementById("fp-detail-add");
  const queued = state.queuedSlugs.has(slug);
  const owned = fpDetailJellyfinValue(slug, movie) === true;
  const hasHosters = Array.isArray(movie.hosters) && movie.hosters.length > 0;
  const mutationPending = fpQueueMutations.has(slug);
  renderFpDownloadFeedback(slug);
  addBtn.hidden = owned && !queued;
  addBtn.disabled = mutationPending || (owned && !queued) || (!queued && !metadataOnly && !hasHosters);
  addBtn.textContent = mutationPending
    ? (queued ? "Entferne …" : "Füge hinzu …")
    : (queued ? "✕ Aus Queue entfernen" : "↓ Herunterladen");

  addBtn.onclick = async () => {
    if (fpQueueMutations.has(slug)) return;
    const shouldRemove = state.queuedSlugs.has(slug);
    if (!shouldRemove && fpDetailJellyfinValue(slug, movie) === true) return;
    addBtn.disabled = true;
    addBtn.textContent = shouldRemove ? "Entferne …" : metadataOnly ? "Prüfe …" : "Füge hinzu …";
    try {
      if (metadataOnly) {
        await toggleFpPick(slug);
        const loaded = state.fp.moviesCache[slug];
        if (loaded && state.fp.selectedSlug === slug) showFpDetail(slug, loaded);
        else if (state.fp.selectedSlug === slug) showFpDetail(slug, movie, true);
        return;
      }
      fpQueueMutations.add(slug);
      if (!shouldRemove) setFpDownloadFeedback(slug);
      const selection = state.fp.downloadSelections.get(slug);
      const resp = shouldRemove
        ? await api.queueRemove(slug)
        : await api.queueAdd([slug], selection ? { [slug]: selection } : {});
      const accepted = shouldRemove || applyFpQueueAddResponse(slug, resp);
      if (shouldRemove) setFpDownloadFeedback(slug);
      if (!shouldRemove && accepted) {
        trackDiscoveryPreference("movie", { ...movie, slug }, 5, "download");
      }
      refreshQueueUiAfterChange(resp);
      if (state.fp.selectedSlug === slug) showFpDetail(slug, movie);
    } catch (error) {
      const reason = error?.message || "Unbekannter Fehler";
      setFpDownloadFeedback(slug, `Download nicht gestartet: ${reason}`, "error");
      setDownloadState("error", "Download nicht gestartet", reason, 0);
      console.warn("Film konnte nicht zur Queue hinzugefügt werden:", error);
    } finally {
      fpQueueMutations.delete(slug);
      configureFpDetailAction(slug, movie, metadataOnly);
    }
  };
}

function movieSubscriptionFor(slug, movie) {
  const tmdbId = String(movie?.tmdb_id || "").trim();
  if (tmdbId) {
    return state.movieSubscriptions.items.find(
      (entry) => String(entry.tmdb_id || "") === tmdbId,
    ) || null;
  }
  return state.movieSubscriptions.items.find(
    (entry) => entry.source_slug === slug,
  ) || null;
}

function configureFpSubscriptionAction(slug, movie) {
  const button = document.getElementById("fp-detail-subscribe");
  const fallback = state.fp.results.find((item) => item.slug === slug) || homeMovieBySlug(slug);
  const resolvedMovie = {
    ...(fallback || {}),
    ...(movie || {}),
    title: movie?.title || fallback?.title || "Film",
    year: movie?.year || fallback?.year || "",
  };
  const entry = movieSubscriptionFor(slug, resolvedMovie);
  button.disabled = !slug;
  button.dataset.slug = slug || "";
  button.classList.toggle("is-active", Boolean(entry));
  button.textContent = entry ? "⚙ Film-Abo" : "+ Film abonnieren";
}

function openSelectedMovieSubscription() {
  const button = document.getElementById("fp-detail-subscribe");
  const slug = button?.dataset.slug || state.fp.selectedSlug;
  if (!slug) return;
  const fallback = state.fp.results.find((item) => item.slug === slug) || homeMovieBySlug(slug);
  const movie = {
    ...(fallback || {}),
    ...(state.fp.metadataCache[slug] || {}),
    ...(state.fp.moviesCache[slug] || {}),
  };
  openMovieSubscriptionModal(slug, movie, movieSubscriptionFor(slug, movie));
}

function closeMovieSubscriptionModal() {
  document.getElementById("movie-subscription-modal").classList.add("hidden");
  document.getElementById("movie-subscription-status").textContent = "";
  movieSubscriptionContext = null;
  if (movieSubscriptionReturnFocus instanceof HTMLElement && movieSubscriptionReturnFocus.isConnected) {
    movieSubscriptionReturnFocus.focus();
  }
  movieSubscriptionReturnFocus = null;
}

function openMovieSubscriptionModal(slug, movie, stored = null) {
  const entry = stored || movieSubscriptionFor(slug, movie);
  movieSubscriptionReturnFocus = document.activeElement;
  movieSubscriptionContext = {
    key: entry?.key || "",
    sourceSlug: entry?.source_slug || slug,
    title: entry?.title || movie?.title || "Film",
    year: String(entry?.year || movie?.year || ""),
    tmdbId: entry?.tmdb_id || movie?.tmdb_id || null,
    coverUrl: entry?.cover_url || movie?.cover_url || "",
    tracked: Boolean(entry),
  };
  document.getElementById("movie-subscription-title").textContent = movieSubscriptionContext.title;
  document.querySelectorAll('input[name="movie-target-quality"]').forEach((radio) => {
    radio.checked = radio.value === (entry?.target_quality || "best");
  });
  document.querySelectorAll('input[name="movie-cleanup"]').forEach((radio) => {
    radio.checked = radio.value === (entry?.cleanup_mode || "keep");
  });
  document.getElementById("movie-upgrade-enabled").checked = entry?.upgrade_enabled !== false;
  document.getElementById("movie-subscription-remove").classList.toggle("hidden", !entry);
  document.getElementById("movie-subscription-save").textContent =
    entry ? "Regel übernehmen" : "Abo speichern";
  document.getElementById("movie-subscription-status").textContent =
    !state.jellyfinUserConfigured
      && document.querySelector('input[name="movie-cleanup"]:checked')?.value === "watched"
      ? "Für die Gesehen-Löschung muss unter Einstellungen ein Jellyfin-Profil gewählt sein."
      : "";
  document.getElementById("movie-subscription-modal").classList.remove("hidden");
  setTimeout(() => document.querySelector('input[name="movie-target-quality"]:checked')?.focus(), 0);
}

async function saveMovieSubscription() {
  if (!movieSubscriptionContext) return;
  const button = document.getElementById("movie-subscription-save");
  button.disabled = true;
  try {
    const response = await api.movieSubscriptionSave({
      source_slug: movieSubscriptionContext.sourceSlug,
      title: movieSubscriptionContext.title,
      year: movieSubscriptionContext.year,
      tmdb_id: movieSubscriptionContext.tmdbId,
      cover_url: movieSubscriptionContext.coverUrl,
      target_quality: document.querySelector('input[name="movie-target-quality"]:checked')?.value || "best",
      cleanup_mode: document.querySelector('input[name="movie-cleanup"]:checked')?.value || "keep",
      upgrade_enabled: document.getElementById("movie-upgrade-enabled").checked,
    });
    applyMovieSubscriptions(response.movie_subscriptions || []);
    closeMovieSubscriptionModal();
  } catch (error) {
    document.getElementById("movie-subscription-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function removeMovieSubscription() {
  if (!movieSubscriptionContext?.key) return;
  const response = await api.movieSubscriptionsRemove([movieSubscriptionContext.key]);
  applyMovieSubscriptions(response.movie_subscriptions || []);
  closeMovieSubscriptionModal();
}

function movieSubscriptionStatus(entry) {
  if (entry.status === "watched_deleted") return "Gesehen · gelöscht";
  if (entry.cleanup_last_error) return entry.cleanup_last_error;
  if (entry.status === "queued") return `Upgrade ${entry.upgrade_available_quality || ""} in Queue`.trim();
  if (entry.status === "failed") return entry.last_error || "Prüfung fehlgeschlagen";
  if (entry.status === "upgrade") return `${entry.upgrade_available_quality || "Besser"} verfügbar`;
  const current = entry.current_quality || (
    entry.current_quality_rank ? `${entry.current_quality_rank}p` : "Noch keine Fassung"
  );
  return `${current} · Ziel ${entry.target_quality_label || "Beste Qualität"}`;
}

function applyMovieSubscriptions(items) {
  state.movieSubscriptions.items = items;
  state.movieSubscriptions.loaded = true;
  renderMovieSubscriptions();
  if (state.fp.selectedSlug) {
    const movie = state.fp.moviesCache[state.fp.selectedSlug]
      || state.fp.metadataCache[state.fp.selectedSlug];
    if (movie) configureFpSubscriptionAction(state.fp.selectedSlug, movie);
  }
}

function renderMovieSubscriptions() {
  const container = document.getElementById("movie-subscriptions-list");
  if (!container) return;
  const items = state.movieSubscriptions.items;
  document.getElementById("movie-subscriptions-count").textContent =
    items.length
      ? `${items.length} ${items.length === 1 ? "Film wird" : "Filme werden"} überwacht`
      : "Noch keine Filme überwacht";
  document.getElementById("movie-subscriptions-check").disabled = !items.length;
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "subscriptions-empty";
    const mark = document.createElement("span");
    mark.className = "subscriptions-empty-mark";
    mark.textContent = "＋";
    mark.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = "Erstes Film-Abo anlegen";
    const hint = document.createElement("small");
    hint.textContent = "Film öffnen und „Film abonnieren“ wählen.";
    copy.append(title, hint);
    empty.append(mark, copy);
    container.appendChild(empty);
    return;
  }
  for (const entry of items) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "subscription-card"
      + (["failed", "upgrade"].includes(entry.status) ? " has-new" : "");
    card.dataset.status = entry.status || "current";
    card.setAttribute("aria-label", `${entry.title}: ${movieSubscriptionStatus(entry)}`);
    const monogram = document.createElement("span");
    monogram.className = "subscription-monogram";
    monogram.textContent = subscriptionMonogram(entry.title);
    const copy = document.createElement("span");
    copy.className = "subscription-text";
    const title = document.createElement("span");
    title.className = "subscription-name";
    title.textContent = entry.title;
    title.translate = false;
    const meta = document.createElement("span");
    meta.className = "subscription-meta";
    meta.textContent = movieSubscriptionStatus(entry);
    copy.append(title, meta);
    const signal = document.createElement("span");
    signal.className = "movie-subscription-signal";
    const signalDot = document.createElement("i");
    signalDot.setAttribute("aria-hidden", "true");
    const signalLabel = document.createElement("span");
    signalLabel.textContent = {
      queued: "In Queue",
      failed: "Fehler",
      upgrade: "Upgrade",
      watched_deleted: "Erledigt",
    }[entry.status] || "Aktuell";
    signal.append(signalDot, signalLabel);
    const open = document.createElement("span");
    open.className = "movie-subscription-open";
    open.textContent = "›";
    open.setAttribute("aria-hidden", "true");
    card.append(monogram, copy, signal, open);
    card.addEventListener("click", () => openMovieSubscriptionModal(entry.source_slug, null, entry));
    container.appendChild(card);
  }
}

function movieQualityRank(value) {
  const text = String(value || "").toUpperCase();
  const resolution = Number(text.match(/(\d{3,4})\s*P?/)?.[1] || 0);
  if (resolution) return resolution;
  if (text.includes("UHD") || text.includes("4K")) return 2160;
  if (text.includes("FULL HD") || text.includes("FHD")) return 1080;
  if (text.includes("HD")) return 720;
  if (text.includes("SD")) return 480;
  return 0;
}

function renderFpDownloadSources(slug, movie, metadataOnly) {
  const section = document.getElementById("fp-detail-sources-section");
  const container = document.getElementById("fp-detail-sources");
  container.innerHTML = "";
  const sources = metadataOnly || !Array.isArray(movie.source_providers)
    ? []
    : movie.source_providers.filter((source) => Array.isArray(source.hosters) && source.hosters.length);
  section.hidden = !sources.length;
  if (!sources.length) return;

  const options = [];
  for (const source of sources) {
    const qualities = [...new Set(source.hosters.map((hoster) => String(hoster.quality || "").trim()))];
    qualities.sort((a, b) => movieQualityRank(b) - movieQualityRank(a) || a.localeCompare(b));
    for (const quality of qualities) {
      const matching = source.hosters.filter(
        (hoster) => String(hoster.quality || "").trim() === quality,
      );
      options.push({
        provider: source.key,
        providerLabel: source.label || source.key,
        quality,
        qualityLabel: quality || "Qualität unbekannt",
        hosterCount: matching.length,
        rank: movieQualityRank(quality),
      });
    }
  }
  options.sort((a, b) => b.rank - a.rank);
  const stored = state.fp.downloadSelections.get(slug);
  const selected = options.find(
    (option) => option.provider === stored?.provider && option.quality === stored?.quality,
  ) || options[0];
  if (selected) {
    state.fp.downloadSelections.set(slug, {
      provider: selected.provider,
      quality: selected.quality,
    });
  }

  for (const option of options) {
    const label = document.createElement("label");
    label.className = "detail-source-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = `movie-source-${slug}`;
    input.checked = option === selected;
    input.addEventListener("change", () => {
      state.fp.downloadSelections.set(slug, {
        provider: option.provider,
        quality: option.quality,
      });
    });
    const copy = document.createElement("span");
    const provider = document.createElement("strong");
    provider.textContent = option.providerLabel;
    const details = document.createElement("small");
    details.textContent = `${option.qualityLabel} · ${option.hosterCount} Hoster`;
    copy.append(provider, details);
    label.append(input, copy);
    container.appendChild(label);
  }
}

function showFpDetail(slug, movie, metadataOnly = false) {
  const detailPanel = document.getElementById("fp-detail-panel");
  const cover = document.getElementById("fp-detail-cover");
  // Die Abo-Aktion darf nicht von späteren Metadaten-/Hosterfeldern abhängen.
  configureFpSubscriptionAction(slug, movie);
  cover.loading = "eager";
  cover.fetchPriority = "high";
  detailPanel.classList.remove("is-empty");
  detailPanel.classList.toggle("has-no-cover", !movie.cover_url);
  if (movie.cover_url) {
    const coverUrl = api.coverUrl(movie.cover_url);
    if (cover.getAttribute("src") !== coverUrl) cover.src = coverUrl;
    const backdropUrl = api.coverUrl(movie.backdrop_url || movie.cover_url).replace(/"/g, "%22");
    detailPanel.style.setProperty("--detail-backdrop-image", `url("${backdropUrl}")`);
  } else if (cover.hasAttribute("src")) {
    cover.removeAttribute("src");
    detailPanel.style.removeProperty("--detail-backdrop-image");
  } else {
    detailPanel.style.removeProperty("--detail-backdrop-image");
  }
  cover.alt = movie.title ? `Poster zu ${movie.title}` : "Filmplakat";
  document.getElementById("fp-detail-title").textContent = movie.title;
  const metaParts = [];
  if (movie.year) metaParts.push(movie.year);
  if (movie.runtime) metaParts.push(movie.runtime);
  if (movie.rating) {
    metaParts.push(
      `★ ${movie.rating}/10${movie.vote_count ? ` · ${formatMovieNumber(movie.vote_count)} Stimmen` : ""}`,
    );
  }
  if (!metadataOnly) {
    if (movie.provider_count) {
      metaParts.push(`${movie.provider_count} Anbieter`);
    }
    metaParts.push(movie.hoster_total
      ? `${movie.hoster_total} Hoster gesamt`
      : (movie.hosters.length ? `${movie.hosters.length} Hoster` : "kein Hoster"));
  }
  if (movie.metadata_source) metaParts.push(movie.metadata_source);
  renderFpDetailItems("fp-detail-meta", metaParts, "Keine Metadaten");
  renderFpDetailItems("fp-detail-genres", movie.genres, "Genre unbekannt");
  const tagline = document.getElementById("fp-detail-tagline");
  tagline.textContent = movie.tagline || "";
  tagline.hidden = !movie.tagline;
  setFpDetailJellyfinStatus(fpDetailJellyfinValue(slug, movie));
  if (metadataOnly) setFpDetailAvailability("Streams werden geprüft", "loading");
  else if (movie.hosters.length) {
    setFpDetailAvailability(
      movie.provider_count
        ? `${movie.provider_count} Anbieter · ${movie.hoster_total || movie.hosters.length} Hoster`
        : `${movie.hosters.length} Hoster bereit`,
      "ready",
    );
  }
  else setFpDetailAvailability("Kein Hoster verfügbar", "error");
  setFpDetailText("fp-detail-original-title", movie.original_title);
  setFpDetailText("fp-detail-release", formatMovieDate(movie.release_date));
  setFpDetailText("fp-detail-certification", movieCertificationLabel(movie));
  const languages = (movie.spoken_languages || []).slice(0, 2).join(", ")
    || (movie.original_language ? movie.original_language.toUpperCase() : "");
  const origin = [
    languages,
    ...(movie.countries || []),
  ].filter(Boolean).join(" · ");
  setFpDetailText("fp-detail-origin", origin);
  setFpDetailText("fp-detail-directors", (movie.directors || []).join(", "));
  setFpDetailText("fp-detail-writers", (movie.writers || []).join(", "));
  setFpDetailText("fp-detail-studios", (movie.production_companies || []).join(", "));
  const insights = [];
  const status = movieStatusLabel(movie.status);
  const budget = formatMovieMoney(movie.budget);
  const revenue = formatMovieMoney(movie.revenue);
  if (status) insights.push(`Status · ${status}`);
  if (movie.collection) insights.push(`Reihe · ${movie.collection}`);
  if (budget) insights.push(`Budget · ${budget}`);
  if (revenue) insights.push(`Einspiel · ${revenue}`);
  renderFpDetailItems("fp-detail-insights", insights);
  renderFpDetailItems("fp-detail-keywords", movie.keywords || []);
  renderFpCast(movie.cast, movie.tmdb_url);
  renderFpDownloadSources(slug, movie, metadataOnly);
  document.getElementById("fp-detail-route-card").classList.toggle("is-loading", metadataOnly);
  setFpDetailText(
    "fp-detail-route",
    metadataOnly ? "Streams werden geprüft" : (movie.provider_route || movie.hoster_route),
  );
  setFpDetailText(
    "fp-detail-score",
    metadataOnly ? "Noch offen" : (movie.hoster_score != null ? String(movie.hoster_score) : ""),
  );
  setFpDetailText(
    "fp-detail-fallback",
    metadataOnly
      ? "Noch offen"
      : (movie.hosters.length
        ? (movie.provider_count
          ? `${movie.provider_fallback_count || 0} Anbieter · ${movie.hoster_fallback_count || 0} Hoster`
          : `${movie.hoster_fallback_count} Alternativen`)
        : ""),
  );
  document.getElementById("fp-detail-desc").textContent = movie.description || "(keine Beschreibung)";

  configureFpTrailer(movie);
  configureFpDetailAction(slug, movie, metadataOnly);
  updateTasteFeedbackButtons();
}
