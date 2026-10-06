import { createScope } from "../../core/lifecycle.js";

export function createSeriesPresentation(catalogRoot, detailRoot, {
  watchModeLabel, seriesState, getHomeData, coverUrl,
  activateResultCard, configureSeriesTrailer, createResultCardVisual, dedupeCatalogMedia, discardObservedResultPosters, homeSeriesEntry, hydrateHomeSeriesArtwork, isEpisodeEligible, loadSeries, mediaJellyfinStatus, mergeCatalogItems, mergeCatalogSources, openMediaModal, refreshCatalogJellyfinStatus, renderSeriesDetailDiscovery, renderSeriesTiles, setFpJellyfinBadge, setFpPosterJellyfinBadge, syncResultCardPoster, syncSeriesQueueFlags, updateSeriesJellyfinBadge, updateSeriesStatus, updateTasteFeedbackButtons, verifyHuhuEpisodeLanguages,
}) {
  const document = catalogRoot.ownerDocument;
  const byId = id => catalogRoot.querySelector(`#${id}`) || detailRoot.querySelector(`#${id}`);
  let scope = null, featureCandidate = null, cancelArtwork = () => {};
  // ── Serien-Tab ─────────────────────────────────────────────────────────────


  function updateSeriesInfiniteState() {
    const sentinel = byId("series-infinite");
    if (!sentinel) return;
    const label = byId("series-infinite-label");
    const retry = byId("series-infinite-retry");
    const mode = seriesState.browseMode;
    const browsable = Boolean(mode && mode !== "search" && seriesState.results.length);
    sentinel.classList.toggle("hidden", !browsable);
    if (!browsable) return;

    const count = seriesState.results.length;
    sentinel.setAttribute("aria-busy", String(seriesState.loadingBrowse));
    retry.hidden = !seriesState.loadError;
    retry.textContent = seriesState.loadError ? "Erneut versuchen" : "Weitere laden";
    if (seriesState.loadingBrowse) {
      sentinel.dataset.state = "loading";
      label.textContent = "Weitere Serien werden geladen …";
    } else if (seriesState.loadError) {
      sentinel.dataset.state = "error";
      label.textContent = `Nachladen fehlgeschlagen · ${count} Serien geladen`;
    } else if (seriesState.lastPageFull) {
      sentinel.dataset.state = "ready";
      label.textContent = `${count} Serien geladen · Weiter scrollen`;
    } else {
      sentinel.dataset.state = "complete";
      label.textContent = `${count} Serien geladen · Ende des Katalogs`;
    }
    const sourceSummary = seriesState.sources
      .map((source) => `${source.label} ${source.count}`)
      .join(" · ");
    sentinel.title = sourceSummary;
  }

  function updateSeriesFeatureArtwork(featureArt, artwork) {
    const source = artwork ? coverUrl(artwork) : "";
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
    cancelArtwork();
    featureArt.dataset.artworkSource = source;
    if (!scope?.active) { featureArt.dataset.artworkSource = ""; return; }
    const owner = scope, image = new document.defaultView.Image();
    cancelArtwork = () => { image.onload = null; image.onerror = null; image.removeAttribute("src"); featureArt.dataset.artworkSource = ""; };
    image.decoding = "async";
    image.onload = async () => {
      try { await image.decode(); } catch (e) { /* already decoded */ }
      if (!owner.active || featureArt.dataset.artworkRequest !== requestId) return;
      featureArt.style.backgroundImage = nextBackground;
      image.onload = null; image.onerror = null; cancelArtwork = () => {};
    };
    image.onerror = () => { image.onload = null; image.onerror = null; cancelArtwork = () => {}; };
    image.src = source;
  }

  function renderSeriesCatalogHero() {
    const feature = byId("series-feature");
    if (!feature) return;
    const catalogCandidate = seriesState.results.find((result) => result.backdrop_url);
    const featuredHomeSeries = [
      ...getHomeData().trendingSeries,
      ...getHomeData().newSeries,
      ...getHomeData().discoverySeries,
    ].find((result) => result.backdrop_url);
    const candidate = catalogCandidate
      || (seriesState.browseMode !== "search" ? featuredHomeSeries : null)
      || seriesState.results[0];
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
    const featureArt = byId("series-feature-art");
    updateSeriesFeatureArtwork(featureArt, artwork);
    byId("series-feature-title").textContent = candidate.title;
    const sources = Array.isArray(candidate.sources) ? candidate.sources : [];
    byId("series-feature-meta").textContent = [
      candidate.year || "",
      candidate.rating ? `★ ${candidate.rating}` : "",
      ...(candidate.genres || []).slice(0, 2),
      sources.length > 1 ? `${sources.length} Quellen` : (candidate.provider_label || sources[0]?.label || ""),
    ].filter(Boolean).join(" · ");
    byId("series-feature-description").textContent =
      candidate.description || "Staffeln, Episoden und Verfügbarkeit direkt im Royal Archiv entdecken.";
    featureCandidate = candidate;
  }

  function seriesCardSeasonSummary(result) {
    const detail = seriesState.cache?.[result.base_slug] || result;
    const seasons = Array.isArray(detail.seasons)
      ? detail.seasons.filter((season) => Number(season.season) > 0)
      : [];
    if (!seasons.length) return "Staffeln & Episoden öffnen";
    const episodes = seasons.reduce((total, season) => total + (Array.isArray(season.episodes) ? season.episodes.length : 0), 0);
    const parts = [`${seasons.length} ${seasons.length === 1 ? "Staffel" : "Staffeln"}`];
    if (episodes) parts.push(`${episodes} ${episodes === 1 ? "Episode" : "Episoden"}`);
    return parts.join(" · ");
  }

  function createSeriesResultRow(result, { suppressEntryAnimation = false } = {}) {
    const selectedBase = seriesState.pendingBaseSlug || seriesState.current?.base_slug;
    const selected = selectedBase === result.base_slug;
    const loading = seriesState.pendingBaseSlug === result.base_slug;
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
    const seasons = document.createElement("span");
    seasons.className = "series-card-seasons";
    seasons.textContent = seriesCardSeasonSummary(result);
    seasons.title = "Verfügbare Staffeln und Episoden öffnen";
    copy.append(title, subtitle, meta, seasons);

    row.append(visual, copy);
    const baseSlug = result.base_slug;
    activateResultCard(row, () => loadSeries(
      seriesState.results.find((item) => item.base_slug === baseSlug) || result,
    ));
    return row;
  }

  function renderSeriesResults(appendFrom = 0, { suppressEntryAnimation = false } = {}) {
    const container = byId("series-results");
    const fragment = document.createDocumentFragment();
    if (appendFrom > 0) {
      for (const result of seriesState.results.slice(appendFrom)) {
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
    for (const result of seriesState.results) {
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
    for (const result of seriesState.results) updateSeriesResultCard(result.base_slug);
    updateSeriesResultSelection();
  }

  function findSeriesResultCard(baseSlug) {
    return [...catalogRoot.querySelectorAll("#series-results .series-row")]
      .find((row) => row.dataset.baseSlug === baseSlug) || null;
  }

  function updateSeriesResultCard(baseSlug) {
    const result = seriesState.results.find((item) => item.base_slug === baseSlug);
    const row = findSeriesResultCard(baseSlug);
    if (!result || !row) return;
    const seasons = row.querySelector(".series-card-seasons");
    if (seasons) seasons.textContent = seriesCardSeasonSummary(result);
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
    const selectedBase = seriesState.pendingBaseSlug || seriesState.current?.base_slug;
    catalogRoot.querySelectorAll("#series-results .series-row").forEach((row) => {
      const loading = seriesState.pendingBaseSlug === row.dataset.baseSlug;
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
    const incoming = dedupeCatalogMedia(data?.results || []);
    const renderedCards = catalogRoot.querySelectorAll("#series-results .series-row");
    const preserveRenderedCards = !append
      && incoming.length === seriesState.results.length
      && renderedCards.length === incoming.length
      && incoming.every((result, index) => (
        result.base_slug === seriesState.results[index]?.base_slug
      ));
    const appendFrom = append ? seriesState.results.length : 0;
    seriesState.results = append
      ? mergeCatalogItems(
        seriesState.results,
        incoming,
        (item) => item.base_slug || item.sample_slug || item.sample_url,
      )
      : incoming;
    seriesState.page = data.page || 1;
    seriesState.lastPageFull = Boolean(data.has_more ?? data.last_page_full);
    seriesState.sources = mergeCatalogSources(seriesState.sources, data.sources, append);
    seriesState.loadError = "";
    if (preserveRenderedCards) {
      if (backgroundRefresh) {
        renderedCards.forEach((row) => { row.style.animation = "none"; });
      }
      for (const result of incoming) updateSeriesResultCard(result.base_slug);
      updateSeriesResultSelection();
    } else {
      renderSeriesResults(appendFrom, { suppressEntryAnimation: backgroundRefresh });
    }
    const browseGeneration = seriesState.browseRequestSeq;
    renderSeriesCatalogHero();
    // Jellyfin ist ein eigener Live-Status und darf nie auf Poster/TMDB warten.
    // Das betrifft insbesondere die komplette erste 32er-Katalogseite.
    const owner = scope;
    if (owner?.active) void refreshCatalogJellyfinStatus(incoming.map(homeSeriesEntry), null, { signal: owner.signal })
      .then(() => {
        if (!owner.active || browseGeneration !== seriesState.browseRequestSeq) return;
        for (const result of seriesState.results) updateSeriesResultCard(result.base_slug);
        renderSeriesCatalogHero();
      });
    if (!artworkPrepared && owner?.active) {
      void hydrateHomeSeriesArtwork(incoming, { render: false, signal: owner.signal }).then(async (hydratedBaseSlugs) => {
        if (!owner.active || browseGeneration !== seriesState.browseRequestSeq) return;
        for (const baseSlug of hydratedBaseSlugs) updateSeriesResultCard(baseSlug);
        renderSeriesCatalogHero();
      });
    }
    updateSeriesInfiniteState();
    const sourceCount = seriesState.sources.length;
    byId("series-status").textContent =
      seriesState.results.length
        ? (sourceCount
          ? `${seriesState.results.length} Serie(n) · ${sourceCount} ${sourceCount === 1 ? "Quelle" : "Quellen"}`
          : `${seriesState.results.length} Serie(n) gefunden`)
        : "Keine Serie gefunden.";
  }


  function seriesStructureFingerprint(series) {
    return (series?.seasons || []).map((season) =>
      `${season.season}:${(season.episodes || []).map((episode) => episode.slug).join(",")}`,
    ).join("|");
  }


  function showSeriesLoading(result) {
    seriesState.viewGeneration += 1;
    seriesState.current = null;
    byId("series-detail-title").textContent = result.title;
    updateSeriesJellyfinBadge(result, true);
    setSeriesDetailArtwork(result);
    const cover = byId("series-cover");
    cover.loading = "eager";
    cover.fetchPriority = "high";
    const previewCover = result.cover_url ? coverUrl(result.cover_url) : "";
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
    byId("series-desc").textContent =
      result.description || "Die Serie ist geöffnet. Staffel- und Episodenstruktur wird beim Anbieter eingelesen.";
    configureSeriesTrailer(result);
    renderSeriesDetailDiscovery(result);
    const tiles = byId("series-tiles");
    tiles.replaceChildren();
    const loading = document.createElement("div");
    loading.className = "series-loading";
    loading.textContent = "Staffeln werden eingelesen …";
    tiles.appendChild(loading);
    byId("series-pick-count").textContent = "wird geladen";
    byId("series-watch-btn").disabled = true;
    byId("series-select-all").disabled = true;
    byId("series-select-none").disabled = true;
    byId("series-add-btn").disabled = true;
  }

  function renderSeriesDetailMeta(values) {
    const container = byId("series-genres");
    container.replaceChildren();
    for (const value of values.filter(Boolean)) {
      const item = document.createElement("span");
      item.textContent = value;
      container.appendChild(item);
    }
  }

  function updateWatchBtn() {
    const btn = byId("series-watch-btn");
    const series = seriesState.current;
    if (!series) return;
    if (series.special_series === "monster_tmdb") {
      btn.disabled = true;
      btn.textContent = "Abo für Sonderzuordnung deaktiviert";
      btn.title = "Diese vier Monster-TMDB-Zuordnungen werden nicht als Anthologie-Abo gespeichert.";
      return;
    }
    btn.disabled = false;
    const tracked = series.watchlisted;
    const label = watchModeLabel(series.watch_mode);
    btn.textContent = tracked ? `✓ Abo · ${label}` : "+ Abonnieren";
    btn.title = tracked ? "Abo-Regel ändern" : "Serie abonnieren und Downloadumfang festlegen";
    btn.classList.toggle("btn-accent", tracked);
  }

  function setSeriesDetailArtwork(series) {
    const panel = detailRoot.querySelector(".series-detail-panel");
    // Das Hero ist ein 16:9-Wallpaper. Hochformat-Poster dürfen hier nie als
    // Ersatz erscheinen, da sie aufgezoomt und abgeschnitten wirken.
    const artwork = series?.backdrop_url || "";
    panel.classList.toggle("has-no-art", !artwork);
    if (!artwork) {
      panel.style.removeProperty("--series-backdrop-image");
      return;
    }
    const backdropUrl = coverUrl(artwork).replace(/"/g, "%22");
    const nextImage = `url("${backdropUrl}")`;
    if (panel.style.getPropertyValue("--series-backdrop-image") !== nextImage) {
      panel.style.setProperty("--series-backdrop-image", nextImage);
    }
  }


  function updateSeriesOverview(series) {
    byId("series-detail-title").textContent = series.title;
    setSeriesDetailArtwork(series);
    const cover = byId("series-cover");
    cover.loading = "eager";
    cover.fetchPriority = "high";
    const nextCover = series.cover_url ? coverUrl(series.cover_url) : "";
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
    byId("series-desc").textContent = series.description || "(keine Beschreibung verfügbar)";
    configureSeriesTrailer(series);
    renderSeriesDetailDiscovery(series);
  }

  function showSeriesDetail(series, sampleSlug) {
    seriesState.viewGeneration += 1;
    syncSeriesQueueFlags(series);
    seriesState.current = series;
    seriesState.currentSampleSlug = sampleSlug;
    seriesState.cache[series.base_slug] = series;
    updateSeriesResultCard(series.base_slug);
    seriesState.pendingBaseSlug = "";
    seriesState.epPicked = new Set();
    updateSeriesResultSelection();
    updateSeriesOverview(series);
    byId("series-watch-btn").disabled = false;
    byId("series-select-all").disabled = false;
    byId("series-select-none").disabled = false;
    updateWatchBtn();
    renderSeriesTiles();
    updateSeriesStatus(series);
    updateTasteFeedbackButtons();
    openMediaModal("series-detail-modal", findSeriesResultCard(series.base_slug));
    const providerLanguages = Array.isArray(series.provider_content_languages)
      ? series.provider_content_languages.filter(Boolean)
      : [];
    const needsExactEpisodeLanguage = ["huhu", "serienstream"].includes(series.provider)
      || providerLanguages.length > 1;
    if (needsExactEpisodeLanguage) {
      const publishedMissingEpisodes = [...(series.seasons || [])]
        .sort((left, right) => Number(right.season || 0) - Number(left.season || 0))
        .flatMap((season) => [...(season.episodes || [])]
          .sort((left, right) => Number(left.episode || 0) - Number(right.episode || 0)))
        .filter((episode) => !episode.downloaded && !episode.in_jellyfin && !episode.unreleased);
      if (publishedMissingEpisodes.length) {
        void verifyHuhuEpisodeLanguages(
          publishedMissingEpisodes, series, { background: true },
        ).catch((error) => {
          if (error.name === "AbortError") return;
          if (seriesState.current === series) {
            byId("series-status").textContent =
              `Stream-Sprachen konnten nicht geprüft werden: ${error.message}`;
          }
        });
      }
    }
  }

  function mount() {
    if (scope?.active) return;
    scope = createScope();
    scope.listen(byId("series-feature-open"), "click", () => { if (featureCandidate) loadSeries(featureCandidate); });
    renderSeriesCatalogHero();
  }
  function unmount() { scope?.dispose(); scope = null; cancelArtwork(); }
  return { mount, unmount, updateSeriesInfiniteState, updateSeriesFeatureArtwork, renderSeriesCatalogHero, seriesCardSeasonSummary, createSeriesResultRow, renderSeriesResults, findSeriesResultCard, updateSeriesResultCard, updateSeriesResultSelection, applySeriesResults, seriesStructureFingerprint, showSeriesLoading, renderSeriesDetailMeta, updateWatchBtn, setSeriesDetailArtwork, updateSeriesOverview, showSeriesDetail };
}
