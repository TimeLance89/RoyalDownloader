// ── Anime ─────────────────────────────────────────────────────────────────
function animeModeTitle(mode) {
  return {
    latest: "Neu im Archiv",
    trending: "Aktuell im Trend",
    popular: "Beliebte Anime",
    search: "Suchergebnisse",
  }[mode] || "Anime";
}

function setAnimeMode(mode) {
  for (const [id, value] of [
    ["anime-latest-btn", "latest"],
    ["anime-trending-btn", "trending"],
    ["anime-popular-btn", "popular"],
  ]) {
    document.getElementById(id).classList.toggle("is-active", mode === value);
  }
  document.getElementById("anime-catalog-title").textContent = animeModeTitle(mode);
}

function renderAnimeFeature() {
  const feature = document.getElementById("anime-featured");
  const anime = state.anime.results[0];
  if (!anime) {
    feature.hidden = true;
    feature.onclick = null;
    return;
  }
  const artwork = anime.banner_url || anime.cover_url || "";
  document.getElementById("anime-featured-art").style.backgroundImage =
    artwork ? `url("${artwork.replace(/"/g, "%22")}")` : "";
  document.getElementById("anime-featured-title").textContent = anime.title;
  const tracks = [
    anime.translations?.dub ? "DUB" : "",
    anime.translations?.sub ? "SUB" : "",
  ].filter(Boolean).join(" + ");
  document.getElementById("anime-featured-meta").textContent = [
    anime.year,
    anime.media_type || "Anime",
    tracks,
    jellyfinStatusText(mediaJellyfinStatus(anime)),
  ].filter(Boolean).join(" · ");
  feature.setAttribute("aria-label", `${anime.title} öffnen`);
  feature.onclick = () => openAnimeDetail(anime, feature);
  feature.hidden = false;
}

function renderAnimeResults() {
  const container = document.getElementById("anime-results");
  container.innerHTML = "";
  for (const anime of state.anime.results) {
    const card = document.createElement("button");
    card.className = "anime-card";
    card.type = "button";
    card.dataset.animeId = anime.id;
    const dubCount = Number(anime.translations?.dub || 0);
    const subCount = Number(anime.translations?.sub || 0);
    const count = Math.max(dubCount, subCount, Number(anime.episode_count || 0));
    card.setAttribute("aria-label", `${anime.title}, ${count} Episoden`);
    card.innerHTML = `
      <span class="anime-card-poster">
        ${anime.cover_url
    ? `<img src="${escapeHtml(api.coverUrl(anime.cover_url))}" alt="" loading="lazy">`
    : ""}
        <span class="anime-card-fallback">${escapeHtml(mediaCardInitials(anime.title))}</span>
        <span class="anime-card-type" translate="no">${escapeHtml(anime.media_type || "TV")}</span>
        <span class="catalog-jellyfin-badge is-${escapeHtml(mediaJellyfinStatus(anime))}"
          title="${escapeHtml(jellyfinStatusText(mediaJellyfinStatus(anime)))}">
          ${mediaJellyfinStatus(anime) === "owned" ? "✓ JF" : mediaJellyfinStatus(anime) === "missing" ? "– JF" : "JF ?"}
        </span>
        <span class="anime-card-open" aria-hidden="true">↗</span>
      </span>
      <span class="anime-card-copy">
        <strong translate="no">${escapeHtml(anime.title)}</strong>
        <span class="anime-card-subtitle" translate="no">
          ${escapeHtml([anime.year, count ? `${count} Episoden` : ""].filter(Boolean).join(" · ") || "Anime")}
        </span>
        <span class="anime-card-meta" translate="no">
          ${dubCount ? `<span class="is-dub">DUB <b>${dubCount}</b></span>` : ""}
          ${subCount ? `<span class="is-sub">SUB <b>${subCount}</b></span>` : ""}
        </span>
      </span>
    `;
    card.addEventListener("click", () => openAnimeDetail(anime, card));
    container.appendChild(card);
  }
  if (!state.anime.results.length) {
    const empty = document.createElement("div");
    empty.className = "anime-empty";
    empty.textContent = state.anime.disabledReason
      || (state.anime.mode === "search"
        ? "Kein Anime passt zu dieser Suche."
        : "MKissa meldet momentan keine Anime.");
    container.appendChild(empty);
  }
  renderAnimeFeature();
  document.getElementById("anime-page-label").textContent =
    `Seite ${state.anime.page} · ${state.anime.results.length} Titel`;
  document.getElementById("anime-prev").disabled = state.anime.loading || state.anime.page <= 1;
  document.getElementById("anime-next").disabled = state.anime.loading || !state.anime.hasMore;
}

function clearAnimeSearchContext() {
  state.anime.searchReturn = null;
  state.anime.query = "";
  document.getElementById("anime-search").value = "";
}

function rememberAnimeSearchContext() {
  if (state.anime.searchReturn || state.anime.mode === "search") return;
  if (!state.anime.loaded && !state.anime.results.length) return;
  state.anime.searchReturn = {
    results: state.anime.results.slice(),
    mode: state.anime.mode || "latest",
    query: state.anime.query,
    page: state.anime.page,
    hasMore: state.anime.hasMore,
    disabledReason: state.anime.disabledReason || "",
    status: document.getElementById("anime-status").textContent,
  };
}

async function restoreAnimeSearchContext() {
  if (state.anime.mode !== "search" && !state.anime.searchReturn) return;
  const saved = state.anime.searchReturn;
  state.anime.searchReturn = null;
  document.getElementById("anime-search").value = "";
  ++state.anime.requestSeq;
  state.anime.loading = false;
  if (!saved) {
    await animeBrowse("latest", 1);
    return;
  }
  state.anime.results = saved.results;
  state.anime.mode = saved.mode;
  state.anime.query = saved.query;
  state.anime.page = saved.page;
  state.anime.hasMore = saved.hasMore;
  state.anime.disabledReason = saved.disabledReason;
  setAnimeMode(saved.mode);
  renderAnimeResults();
  document.getElementById("anime-status").textContent = saved.status;
}

async function animeBrowse(mode, page = 1) {
  const query = mode === "search"
    ? document.getElementById("anime-search").value.trim()
    : "";
  if (mode === "search" && !query) {
    await restoreAnimeSearchContext();
    return;
  }
  if (state.anime.loading) return;
  if (mode === "search") rememberAnimeSearchContext();
  else clearAnimeSearchContext();
  state.anime.loading = true;
  const requestSeq = ++state.anime.requestSeq;
  setAnimeMode(mode);
  document.getElementById("anime-status").textContent =
    mode === "search" ? `Suche nach «${query}» …` : `${animeModeTitle(mode)} werden geladen …`;
  renderAnimeResults();
  try {
    const response = await api.anime({ mode, query, page });
    if (requestSeq !== state.anime.requestSeq) return;
    state.anime.results = response.results || [];
    state.anime.mode = mode;
    state.anime.query = query;
    state.anime.page = Number(response.page) || page;
    state.anime.hasMore = !!response.has_more;
    state.anime.loaded = true;
    state.anime.disabledReason = response.disabled ? response.disabled_reason : "";
    const total = Number(response.total) || state.anime.results.length;
    document.getElementById("anime-status").textContent = response.disabled
      ? response.disabled_reason
      : `${state.anime.results.length} Titel auf dieser Seite · ${total.toLocaleString("de-DE")} im Katalog`;
  } catch (error) {
    if (requestSeq !== state.anime.requestSeq) return;
    state.anime.results = [];
    state.anime.hasMore = false;
    state.anime.loaded = true;
    state.anime.disabledReason = error.message;
    document.getElementById("anime-status").textContent = `Fehler: ${error.message}`;
  } finally {
    if (requestSeq === state.anime.requestSeq) {
      state.anime.loading = false;
      renderAnimeResults();
      void refreshCatalogJellyfinStatus(
        state.anime.results.map(homeAnimeEntry),
        () => {
          if (requestSeq === state.anime.requestSeq) renderAnimeResults();
        },
      );
    }
  }
}

async function openAnimeDetail(anime, returnFocus = null) {
  state.anime.currentId = anime.id;
  state.anime.current = { ...anime, episodes: [] };
  state.anime.translation = anime.translations?.dub
    ? "dub"
    : (anime.translations?.sub ? "sub" : Object.keys(anime.translations || {})[0] || "");
  state.anime.episodePage = 1;
  state.anime.picked.clear();
  openMediaModal("anime-detail-modal", returnFocus);
  document.getElementById("anime-detail-title").textContent = anime.title;
  document.getElementById("anime-detail-description").textContent = "Episoden und Sprachspuren werden geladen …";
  trackDiscoveryPreference("anime", { ...anime, base_slug: anime.id }, 0.8, "open");
  await loadAnimeDetail();
}

async function loadAnimeDetail({ keepSelection = false } = {}) {
  const animeId = state.anime.currentId;
  if (!animeId) return;
  const detailSeq = ++state.anime.detailSeq;
  if (!keepSelection) state.anime.picked.clear();
  document.getElementById("anime-pick-count").textContent = "wird geladen";
  document.getElementById("anime-add-btn").disabled = true;
  try {
    const detail = await api.animeDetail(
      animeId,
      state.anime.translation,
      state.anime.episodePage,
    );
    if (detailSeq !== state.anime.detailSeq || animeId !== state.anime.currentId) return;
    state.anime.current = {
      ...detail,
      jellyfin_status: state.anime.current?.jellyfin_status || "checking",
      in_jellyfin: state.anime.current?.in_jellyfin,
    };
    state.anime.translation = detail.translation;
    state.anime.episodePage = detail.page;
    syncAnimeQueueFlags();
    renderAnimeDetail();
  } catch (error) {
    if (detailSeq !== state.anime.detailSeq) return;
    document.getElementById("anime-detail-description").textContent = error.message;
    document.getElementById("anime-pick-count").textContent = "nicht verfügbar";
  }
}

function renderAnimeDetail() {
  const anime = state.anime.current;
  if (!anime) return;
  document.getElementById("anime-detail-title").textContent = anime.title;
  const cover = document.getElementById("anime-detail-cover");
  cover.src = api.coverUrl(anime.cover_url || "");
  cover.alt = anime.title;
  document.getElementById("anime-detail-type").textContent = anime.media_type || "TV";
  const banner = document.getElementById("anime-detail-banner");
  banner.style.backgroundImage = anime.banner_url
    ? `url("${api.coverUrl(anime.banner_url).replace(/"/g, "%22")}")`
    : "";
  document.getElementById("anime-detail-description").textContent =
    anime.description || "Keine Beschreibung verfügbar.";
  const meta = [
    anime.year,
    anime.rating ? `★ ${Number(anime.rating).toFixed(1)}` : "",
    ...(anime.genres || []).slice(0, 4),
    jellyfinStatusText(mediaJellyfinStatus(anime)),
  ].filter(Boolean);
  document.getElementById("anime-detail-meta").innerHTML =
    meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("");

  const trackOptions = document.getElementById("anime-track-options");
  trackOptions.innerHTML = "";
  for (const [track, countValue] of Object.entries(anime.translations || {})) {
    const count = Number(countValue) || 0;
    if (!count) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `anime-track-option ${track === state.anime.translation ? "is-active" : ""}`;
    button.dataset.track = track;
    button.innerHTML = `
      <strong translate="no">${escapeHtml(track.toUpperCase())}</strong>
      <small translate="no">${escapeHtml(anime.translation_labels?.[track] || track)} · ${count} EP</small>
    `;
    button.addEventListener("click", () => {
      if (track === state.anime.translation) return;
      state.anime.translation = track;
      state.anime.episodePage = 1;
      loadAnimeDetail();
    });
    trackOptions.appendChild(button);
  }
  renderAnimeEpisodes();
}

function renderAnimeEpisodes() {
  const anime = state.anime.current;
  const container = document.getElementById("anime-episode-grid");
  container.innerHTML = "";
  if (!anime?.episodes?.length) {
    container.innerHTML = '<div class="anime-empty">Keine Episoden in dieser Sprachspur.</div>';
    return;
  }
  for (const episode of anime.episodes) {
    const selected = state.anime.picked.has(episode.slug);
    const queued = episode.queued || state.queuedSlugs.has(episode.slug);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "anime-episode"
      + (selected ? " is-selected" : "")
      + (queued ? " is-queued" : "")
      + (episode.downloaded ? " is-downloaded" : "");
    button.textContent = episode.number;
    button.title = episode.downloaded
      ? `${episode.label} · bereits geladen`
      : queued ? `${episode.label} · in der Warteschlange` : episode.label;
    button.disabled = queued || episode.downloaded;
    button.addEventListener("click", () => {
      if (state.anime.picked.has(episode.slug)) state.anime.picked.delete(episode.slug);
      else state.anime.picked.add(episode.slug);
      renderAnimeEpisodes();
    });
    container.appendChild(button);
  }
  const first = anime.episodes[0]?.number || 0;
  const last = anime.episodes.at(-1)?.number || 0;
  document.getElementById("anime-episode-page-label").textContent =
    `Episoden ${first}–${last} · Seite ${anime.page}/${anime.page_count}`;
  document.getElementById("anime-episode-prev").disabled = anime.page <= 1;
  document.getElementById("anime-episode-next").disabled = anime.page >= anime.page_count;
  document.getElementById("anime-pick-count").textContent = `${state.anime.picked.size} ausgewählt`;
  document.getElementById("anime-select-none").disabled = !state.anime.picked.size;
  document.getElementById("anime-add-btn").disabled = !state.anime.picked.size;
}

function syncAnimeQueueFlags() {
  const anime = state.anime.current;
  if (!anime?.episodes) return;
  for (const episode of anime.episodes) {
    episode.queued = state.queuedSlugs.has(episode.slug);
    if (episode.queued) state.anime.picked.delete(episode.slug);
  }
  if (!document.getElementById("anime-detail-modal").hidden) renderAnimeEpisodes();
}

function markAnimeSlugDownloaded(slug) {
  const anime = state.anime.current;
  const episode = anime?.episodes?.find((item) => item.slug === slug);
  if (!episode) return;
  episode.downloaded = true;
  episode.queued = false;
  state.anime.picked.delete(slug);
  renderAnimeEpisodes();
}

async function animeAddSelected() {
  const slugs = [...state.anime.picked];
  if (!slugs.length) return;
  const button = document.getElementById("anime-add-btn");
  button.disabled = true;
  document.getElementById("anime-pick-count").textContent = "wird eingeplant …";
  try {
    const response = await api.queueAdd(slugs, {}, "anime");
    refreshQueueUiAfterChange(response);
    state.anime.picked.clear();
    document.getElementById("anime-status").textContent =
      `${response.added}/${slugs.length} Anime-Episode(n) gestartet`;
  } catch (error) {
    document.getElementById("anime-status").textContent = `Download fehlgeschlagen: ${error.message}`;
  } finally {
    renderAnimeEpisodes();
  }
}

function closeWatchModeModal() {
  document.getElementById("watch-mode-modal").classList.add("hidden");
  document.getElementById("watch-mode-status").textContent = "";
  watchModeContext = null;
  if (watchModeReturnFocus instanceof HTMLElement && watchModeReturnFocus.isConnected) {
    watchModeReturnFocus.focus();
  }
  watchModeReturnFocus = null;
}

function normalizeSeriesIdentityTitle(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function watchlistEntryForSeries(series, items = state.wl.items) {
  if (!series) return null;
  const exact = items.find((item) => item.base_slug === series.base_slug);
  if (exact) return exact;
  const tmdbId = String(series.tmdb_id || "").trim();
  if (tmdbId) {
    const stable = items.filter((item) => String(item.tmdb_id || "").trim() === tmdbId);
    if (stable.length === 1) return stable[0];
  }
  const wantedTitles = new Set([
    series.title, series.original_title, ...(series.aliases || []),
  ].map(normalizeSeriesIdentityTitle).filter(Boolean));
  const matches = items.filter((item) => {
    const storedTmdb = String(item.tmdb_id || "").trim();
    if (tmdbId && storedTmdb && storedTmdb !== tmdbId) return false;
    return [item.title, ...(item.aliases || [])]
      .map(normalizeSeriesIdentityTitle)
      .some((title) => wantedTitles.has(title));
  });
  return matches.length === 1 ? matches[0] : null;
}

function openWatchModeModal(entry = null) {
  const series = state.series.current;
  const stored = entry || watchlistEntryForSeries(series);
  const baseSlug = stored?.base_slug || series?.base_slug;
  if (!baseSlug) return;
  const tracked = Boolean(stored || series?.watchlisted);
  const mode = stored?.download_mode || series?.watch_mode || WATCH_MODE_DEFAULT;
  const cleanupMode = tracked
    ? (stored?.cleanup_mode || series?.cleanup_mode || WATCH_CLEANUP_DEFAULT)
    : state.watchlistCleanupDefault;
  watchModeReturnFocus = document.activeElement;
  const knownSlugs = series?.base_slug === baseSlug
    ? series.seasons.flatMap((season) => season.episodes.map((episode) => episode.slug))
    : (stored?.known_slugs || []);
  watchModeContext = {
    baseSlug,
    title: stored?.title || series?.title || baseSlug,
    sampleUrl: stored?.sample_url || series?.url || "",
    knownSlugs,
    tmdbId: stored?.tmdb_id || series?.tmdb_id || null,
    aliases: stored?.aliases || series?.aliases || [],
    seasonEpisodeCounts: stored?.season_episode_counts || series?.season_episode_counts || {},
    seasonCountsCheckedAt: stored?.season_counts_checked_at || series?.season_counts_checked_at || 0,
    tracked,
  };

  document.getElementById("watch-mode-title").textContent = watchModeContext.title;
  document.querySelectorAll('input[name="watch-mode"]').forEach((radio) => {
    radio.checked = radio.value === mode;
  });
  document.querySelectorAll('input[name="watch-cleanup"]').forEach((radio) => {
    radio.checked = radio.value === cleanupMode;
  });
  document.getElementById("watch-cleanup-description").textContent = tracked
    ? "Diese Löschregel gilt nur für diese Serie und nutzt den Gesehen-Status des gewählten Jellyfin-Profils."
    : `Vorausgewählt aus den Einstellungen: ${WATCH_CLEANUP_LABELS[cleanupMode] || WATCH_CLEANUP_LABELS[WATCH_CLEANUP_DEFAULT]}. Du kannst für diese Serie abweichen.`;
  document.getElementById("watch-mode-remove").classList.toggle("hidden", !tracked);
  document.getElementById("watch-mode-save").textContent = tracked ? "Regel übernehmen" : "Abo speichern";
  document.getElementById("watch-mode-status").textContent = "";
  document.getElementById("watch-mode-modal").classList.remove("hidden");
  updateWatchModeRequirement();
  setTimeout(() => document.querySelector('input[name="watch-mode"]:checked')?.focus(), 0);
}

function updateWatchModeRequirement() {
  const selected = document.querySelector('input[name="watch-mode"]:checked')?.value;
  const cleanupSelected = document.querySelector('input[name="watch-cleanup"]:checked')?.value
    || WATCH_CLEANUP_DEFAULT;
  const status = document.getElementById("watch-mode-status");
  const explanation = WATCH_MODE_EXPLANATIONS[selected] || WATCH_MODE_EXPLANATIONS[WATCH_MODE_DEFAULT];
  document.getElementById("watch-mode-outcome-title").textContent = explanation.title;
  document.getElementById("watch-mode-outcome-copy").textContent = explanation.copy;
  if (!state.jellyfinUserConfigured && (selected === "next_season" || cleanupSelected !== WATCH_CLEANUP_DEFAULT)) {
    const affected = selected === "next_season" && cleanupSelected !== WATCH_CLEANUP_DEFAULT
      ? "Download- und Löschregel warten"
      : (selected === "next_season" ? "Die Downloadregel wartet" : "Die Löschregel wartet");
    status.textContent = `Voraussetzung fehlt: Wähle unter Einstellungen → Jellyfin ein Wiedergabeprofil. ${affected}.`;
  } else if (status.textContent.startsWith("Diese Regel wartet")) {
    status.textContent = "";
  } else if (status.textContent.startsWith("Voraussetzung fehlt")) {
    status.textContent = "";
  }
}

async function saveWatchMode() {
  if (!watchModeContext) return;
  const selected = document.querySelector('input[name="watch-mode"]:checked')?.value;
  const cleanupSelected = document.querySelector('input[name="watch-cleanup"]:checked')?.value
    || WATCH_CLEANUP_DEFAULT;
  if (!selected) return;
  const saveBtn = document.getElementById("watch-mode-save");
  saveBtn.disabled = true;
  try {
    const data = watchModeContext.tracked
      ? await api.watchlistMode(watchModeContext.baseSlug, selected, cleanupSelected)
      : await api.watchlistAdd({
        base_slug: watchModeContext.baseSlug,
        title: watchModeContext.title,
        sample_url: watchModeContext.sampleUrl,
        known_slugs: watchModeContext.knownSlugs,
        download_mode: selected,
        cleanup_mode: cleanupSelected,
        tmdb_id: watchModeContext.tmdbId,
        aliases: watchModeContext.aliases,
        season_episode_counts: watchModeContext.seasonEpisodeCounts,
        season_counts_checked_at: watchModeContext.seasonCountsCheckedAt,
      });
    if (state.series.current?.base_slug === watchModeContext.baseSlug) {
      state.series.current.watchlisted = true;
      state.series.current.watch_mode = selected;
      state.series.current.cleanup_mode = cleanupSelected;
    }
    applyWatchlist(data.watchlist);
    closeWatchModeModal();
  } catch (error) {
    document.getElementById("watch-mode-status").textContent = error.message;
  } finally {
    saveBtn.disabled = false;
  }
}

async function removeWatchModeSubscription() {
  if (!watchModeContext?.tracked) return;
  const data = await api.watchlistRemove([watchModeContext.baseSlug]);
  applyWatchlist(data.watchlist);
  await syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung");
  closeWatchModeModal();
}
