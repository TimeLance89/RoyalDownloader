// ── AniWorld: deutscher Anime-Bereich ──────────────────────────────────────
(function createAniworldScreen() {
  const source = document.getElementById("tab-anime");
  if (!source || document.getElementById("tab-aniworld")) return;
  const screen = source.cloneNode(true);
  screen.id = "tab-aniworld";
  screen.classList.remove("active");
  for (const node of screen.querySelectorAll("[id]")) {
    node.id = node.id.replace(/^anime-/, "aniworld-");
  }
  for (const node of screen.querySelectorAll("*")) {
    for (const attribute of ["aria-labelledby", "aria-controls", "data-modal-close", "for"]) {
      const value = node.getAttribute(attribute);
      if (value) node.setAttribute(attribute, value.replace(/^anime-/, "aniworld-"));
    }
  }
  screen.querySelector(".anime-kicker").textContent = "ROYAL ANIME ARCHIV · DEUTSCH";
  screen.querySelector(".anime-hero-copy h1").textContent = "AniWorld";
  screen.querySelector(".anime-hero-copy p").textContent =
    "Deutsche Synchronisationen und deutsche Untertitel in einem eigenen Bereich.";
  const tracks = screen.querySelectorAll(".anime-hero-tracks span");
  tracks[0].innerHTML = "<b>DUB</b> Deutsche Sprache";
  tracks[1].innerHTML = "<b>SUB</b> Deutsche Untertitel";
  screen.querySelector("#aniworld-featured-meta").textContent = "AniWorld · DE";
  screen.querySelector("#aniworld-search").placeholder = "Deutschen Anime-Titel suchen";
  screen.querySelector(".anime-catalog-index").textContent = "ANIWORLD KATALOG";
  source.after(screen);
})();

function aniworldModeTitle(mode) {
  return {
    latest: "Neu bei AniWorld",
    trending: "Aktuell im Trend",
    popular: "Beliebte Anime",
    search: "Suchergebnisse",
  }[mode] || "AniWorld";
}

function setAniworldMode(mode) {
  for (const [id, value] of [
    ["aniworld-latest-btn", "latest"],
    ["aniworld-trending-btn", "trending"],
    ["aniworld-popular-btn", "popular"],
  ]) {
    document.getElementById(id).classList.toggle("is-active", mode === value);
  }
  document.getElementById("aniworld-catalog-title").textContent = aniworldModeTitle(mode);
}

function renderAniworldFeature() {
  const feature = document.getElementById("aniworld-featured");
  const anime = state.aniworld.results[0];
  if (!anime) {
    feature.hidden = true;
    feature.onclick = null;
    return;
  }
  const artwork = anime.banner_url || anime.cover_url || "";
  document.getElementById("aniworld-featured-art").style.backgroundImage =
    artwork ? `url("${artwork.replace(/"/g, "%22")}")` : "";
  document.getElementById("aniworld-featured-title").textContent = anime.title;
  document.getElementById("aniworld-featured-meta").textContent = [
    anime.year, "AniWorld", "DE",
  ].filter(Boolean).join(" · ");
  feature.setAttribute("aria-label", `${anime.title} öffnen`);
  feature.onclick = () => openAniworldDetail(anime, feature);
  feature.hidden = false;
}

function renderAniworldResults() {
  const container = document.getElementById("aniworld-results");
  container.innerHTML = "";
  for (const anime of state.aniworld.results) {
    const card = document.createElement("button");
    card.className = "anime-card";
    card.type = "button";
    card.dataset.aniworldId = anime.id;
    const count = Number(anime.episode_count || 0);
    card.setAttribute("aria-label", `${anime.title}${count ? `, ${count} Episoden` : ""}`);
    card.innerHTML = `
      <span class="anime-card-poster">
        ${anime.cover_url
    ? `<img src="${escapeHtml(api.coverUrl(anime.cover_url))}" alt="" loading="lazy">`
    : ""}
        <span class="anime-card-fallback">${escapeHtml(mediaCardInitials(anime.title))}</span>
        <span class="anime-card-type" translate="no">DE</span>
      </span>
      <span class="anime-card-copy">
        <strong>${escapeHtml(anime.title)}</strong>
        <small>${escapeHtml([anime.year, count ? `${count} Episoden` : "AniWorld"].filter(Boolean).join(" · "))}</small>
        <span class="anime-card-tracks"><span class="is-dub">DUB / SUB</span></span>
      </span>
    `;
    card.addEventListener("click", () => openAniworldDetail(anime, card));
    container.appendChild(card);
  }
  if (!state.aniworld.results.length) {
    const empty = document.createElement("div");
    empty.className = "anime-empty";
    empty.textContent = state.aniworld.disabledReason
      || (state.aniworld.mode === "search"
        ? "Kein Anime passt zu dieser Suche."
        : "AniWorld meldet momentan keine Anime.");
    container.appendChild(empty);
  }
  renderAniworldFeature();
  document.getElementById("aniworld-page-label").textContent =
    `Seite ${state.aniworld.page} · ${state.aniworld.results.length} Titel`;
  document.getElementById("aniworld-prev").disabled =
    state.aniworld.loading || state.aniworld.page <= 1;
  document.getElementById("aniworld-next").disabled =
    state.aniworld.loading || !state.aniworld.hasMore;
}

async function aniworldBrowse(mode, page = 1) {
  const query = mode === "search"
    ? document.getElementById("aniworld-search").value.trim()
    : "";
  if (mode === "search" && !query) return;
  if (state.aniworld.loading) return;
  state.aniworld.loading = true;
  const requestSeq = ++state.aniworld.requestSeq;
  setAniworldMode(mode);
  document.getElementById("aniworld-status").textContent =
    mode === "search" ? `Suche nach «${query}» …` : `${aniworldModeTitle(mode)} werden geladen …`;
  renderAniworldResults();
  try {
    const response = await api.aniworld({ mode, query, page });
    if (requestSeq !== state.aniworld.requestSeq) return;
    state.aniworld.results = response.results || [];
    state.aniworld.mode = mode;
    state.aniworld.query = query;
    state.aniworld.page = Number(response.page) || page;
    state.aniworld.hasMore = !!response.has_more;
    state.aniworld.loaded = true;
    state.aniworld.disabledReason = response.disabled ? response.disabled_reason : "";
    const total = Number(response.total) || state.aniworld.results.length;
    document.getElementById("aniworld-status").textContent = response.disabled
      ? response.disabled_reason
      : `${state.aniworld.results.length} Titel auf dieser Seite · ${total.toLocaleString("de-DE")} im Katalog`;
  } catch (error) {
    if (requestSeq !== state.aniworld.requestSeq) return;
    state.aniworld.results = [];
    state.aniworld.hasMore = false;
    state.aniworld.loaded = true;
    state.aniworld.disabledReason = error.message;
    document.getElementById("aniworld-status").textContent = `Fehler: ${error.message}`;
  } finally {
    if (requestSeq === state.aniworld.requestSeq) {
      state.aniworld.loading = false;
      renderAniworldResults();
    }
  }
}

async function openAniworldDetail(anime, returnFocus = null) {
  state.aniworld.currentId = anime.id;
  state.aniworld.current = { ...anime, episodes: [] };
  state.aniworld.translation = anime.translations?.dub
    ? "dub" : (anime.translations?.sub ? "sub" : "");
  state.aniworld.episodePage = 1;
  state.aniworld.picked.clear();
  openMediaModal("aniworld-detail-modal", returnFocus);
  document.getElementById("aniworld-detail-title").textContent = anime.title;
  document.getElementById("aniworld-detail-description").textContent =
    "Staffeln und Sprachspuren werden geladen …";
  await loadAniworldDetail();
}

async function loadAniworldDetail({ keepSelection = false } = {}) {
  const animeId = state.aniworld.currentId;
  if (!animeId) return;
  const detailSeq = ++state.aniworld.detailSeq;
  if (!keepSelection) state.aniworld.picked.clear();
  document.getElementById("aniworld-pick-count").textContent = "wird geladen";
  document.getElementById("aniworld-add-btn").disabled = true;
  try {
    const detail = await api.aniworldDetail(
      animeId, state.aniworld.translation, state.aniworld.episodePage,
    );
    if (detailSeq !== state.aniworld.detailSeq || animeId !== state.aniworld.currentId) return;
    state.aniworld.current = detail;
    state.aniworld.translation = detail.translation;
    state.aniworld.episodePage = detail.page;
    syncAniworldQueueFlags();
    renderAniworldDetail();
  } catch (error) {
    if (detailSeq !== state.aniworld.detailSeq) return;
    document.getElementById("aniworld-detail-description").textContent = error.message;
    document.getElementById("aniworld-pick-count").textContent = "nicht verfügbar";
  }
}

function renderAniworldDetail() {
  const anime = state.aniworld.current;
  if (!anime) return;
  document.getElementById("aniworld-detail-title").textContent = anime.title;
  const cover = document.getElementById("aniworld-detail-cover");
  cover.src = api.coverUrl(anime.cover_url || "");
  cover.alt = anime.title;
  document.getElementById("aniworld-detail-type").textContent = "DE Anime";
  document.getElementById("aniworld-detail-banner").style.backgroundImage = anime.banner_url
    ? `url("${api.coverUrl(anime.banner_url).replace(/"/g, "%22")}")` : "";
  document.getElementById("aniworld-detail-description").textContent =
    anime.description || "Keine Beschreibung verfügbar.";
  document.getElementById("aniworld-detail-meta").innerHTML = [
    anime.year, ...(anime.genres || []).slice(0, 4),
  ].filter(Boolean).map((value) => `<span>${escapeHtml(value)}</span>`).join("");

  const options = document.getElementById("aniworld-track-options");
  options.innerHTML = "";
  for (const [track, countValue] of Object.entries(anime.translations || {})) {
    const count = Number(countValue) || 0;
    if (!count) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `anime-track-option ${track === state.aniworld.translation ? "is-active" : ""}`;
    button.innerHTML = `
      <strong translate="no">${escapeHtml(track.toUpperCase())}</strong>
      <small>${escapeHtml(anime.translation_labels?.[track] || track)} · ${count} EP</small>
    `;
    button.addEventListener("click", () => {
      if (track === state.aniworld.translation) return;
      state.aniworld.translation = track;
      state.aniworld.episodePage = 1;
      loadAniworldDetail();
    });
    options.appendChild(button);
  }
  renderAniworldEpisodes();
}

function renderAniworldEpisodes() {
  const anime = state.aniworld.current;
  const container = document.getElementById("aniworld-episode-grid");
  container.innerHTML = "";
  if (!anime?.episodes?.length) {
    container.innerHTML = '<div class="anime-empty">Keine Episoden in dieser Sprachspur.</div>';
    return;
  }
  for (const episode of anime.episodes) {
    const selected = state.aniworld.picked.has(episode.slug);
    const queued = episode.queued || state.queuedSlugs.has(episode.slug);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "anime-episode"
      + (selected ? " is-selected" : "")
      + (queued ? " is-queued" : "")
      + (episode.downloaded ? " is-downloaded" : "");
    button.textContent = `S${episode.season} · ${episode.number}`;
    button.title = episode.title ? `${episode.label} · ${episode.title}` : episode.label;
    button.disabled = queued || episode.downloaded;
    button.addEventListener("click", () => {
      if (state.aniworld.picked.has(episode.slug)) state.aniworld.picked.delete(episode.slug);
      else state.aniworld.picked.add(episode.slug);
      renderAniworldEpisodes();
    });
    container.appendChild(button);
  }
  const first = anime.episodes[0];
  const last = anime.episodes.at(-1);
  document.getElementById("aniworld-episode-page-label").textContent =
    `S${first.season}E${first.number}–S${last.season}E${last.number} · Seite ${anime.page}/${anime.page_count}`;
  document.getElementById("aniworld-episode-prev").disabled = anime.page <= 1;
  document.getElementById("aniworld-episode-next").disabled = anime.page >= anime.page_count;
  document.getElementById("aniworld-pick-count").textContent = `${state.aniworld.picked.size} ausgewählt`;
  document.getElementById("aniworld-select-none").disabled = !state.aniworld.picked.size;
  document.getElementById("aniworld-add-btn").disabled = !state.aniworld.picked.size;
}

function syncAniworldQueueFlags() {
  const anime = state.aniworld.current;
  if (!anime?.episodes) return;
  for (const episode of anime.episodes) {
    episode.queued = state.queuedSlugs.has(episode.slug);
    if (episode.queued) state.aniworld.picked.delete(episode.slug);
  }
  const modal = document.getElementById("aniworld-detail-modal");
  if (modal && !modal.hidden) renderAniworldEpisodes();
}

function markAniworldSlugDownloaded(slug) {
  const anime = state.aniworld.current;
  const episode = anime?.episodes?.find((item) => item.slug === slug);
  if (!episode) return;
  episode.downloaded = true;
  episode.queued = false;
  state.aniworld.picked.delete(slug);
  renderAniworldEpisodes();
}

async function aniworldAddSelected() {
  const slugs = [...state.aniworld.picked];
  if (!slugs.length) return;
  document.getElementById("aniworld-add-btn").disabled = true;
  document.getElementById("aniworld-pick-count").textContent = "wird eingeplant …";
  try {
    const response = await api.queueAdd(slugs, {}, "anime");
    refreshQueueUiAfterChange(response);
    state.aniworld.picked.clear();
    document.getElementById("aniworld-status").textContent =
      `${response.added}/${slugs.length} AniWorld-Episode(n) gestartet`;
  } catch (error) {
    document.getElementById("aniworld-status").textContent =
      `Download fehlgeschlagen: ${error.message}`;
  } finally {
    renderAniworldEpisodes();
  }
}
