// ── AniWorld: eigenständiges deutsches Anime-Archiv ───────────────────────
(function createAniworldScreen() {
  if (document.getElementById("tab-aniworld")) return;
  const source = document.getElementById("tab-anime");
  if (!source) return;
  source.insertAdjacentHTML("afterend", `
    <section class="tab-content aniworld-tab-content" id="tab-aniworld">
      <header class="aniworld-hero">
        <div class="aniworld-hero-signal" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
        <div class="aniworld-hero-copy">
          <span class="aniworld-kicker">DEUTSCHES ANIME-ARCHIV · ANIWORLD</span>
          <h1>Staffeln. Filme.<br><em>Keine Lücken.</em></h1>
          <p>Durchsuche den vollständigen Katalog, wähle jede verfügbare Sprachspur und plane ganze Staffeln oder einzelne Folgen ein.</p>
          <div class="aniworld-hero-tracks" aria-label="Unterstützte Sprachspuren">
            <span><b>DUB</b> Deutsch</span><span><b>SUB</b> Deutsche Untertitel</span><span><b>EN</b> Englisch</span>
          </div>
        </div>
        <button id="aniworld-featured" class="aniworld-featured" type="button" hidden>
          <span id="aniworld-featured-art" class="aniworld-featured-art" aria-hidden="true"></span>
          <span class="aniworld-featured-shade" aria-hidden="true"></span>
          <span class="aniworld-featured-copy">
            <small>ARCHIV-EMPFEHLUNG</small>
            <strong id="aniworld-featured-title">Anime entdecken</strong>
            <span id="aniworld-featured-meta">AniWorld · DE</span>
          </span>
          <span class="aniworld-featured-open" aria-hidden="true">↗</span>
        </button>
        <dl class="aniworld-hero-metrics">
          <div><dt id="aniworld-result-count">—</dt><dd>Titel im Ergebnis</dd></div>
          <div><dt>3</dt><dd>Sprachspuren</dd></div>
          <div><dt id="aniworld-source-state">LIVE</dt><dd>Quellenstatus</dd></div>
        </dl>
      </header>

      <section class="aniworld-console" aria-labelledby="aniworld-console-title">
        <div class="aniworld-console-head">
          <div><span>ARCHIVSTEUERUNG</span><h2 id="aniworld-console-title">Was möchtest du laden?</h2></div>
          <span id="aniworld-status" role="status" aria-live="polite">Der vollständige Katalog wird beim Öffnen geladen …</span>
        </div>
        <div class="aniworld-command-row">
          <label class="aniworld-search-field">
            <span aria-hidden="true">⌕</span>
            <input id="aniworld-search" type="search" autocomplete="off" placeholder="Titel oder Alternativtitel suchen">
          </label>
          <button id="aniworld-search-btn" class="aniworld-search-submit" type="button">Suchen</button>
          <div class="aniworld-mode-switch" role="group" aria-label="Katalogansicht">
            <button id="aniworld-updates-btn" type="button">Neue Folgen</button>
            <button id="aniworld-latest-btn" type="button">Neue Anime</button>
            <button id="aniworld-trending-btn" type="button">Trending</button>
            <button id="aniworld-popular-btn" type="button">Beliebt</button>
            <button id="aniworld-catalog-btn" class="is-active" type="button">A–Z</button>
          </div>
        </div>
        <div id="aniworld-filters" class="aniworld-filter-deck">
          <div id="aniworld-letter-filter" class="aniworld-letter-filter" role="group" aria-label="Anfangsbuchstabe"></div>
          <label><span>Genre</span><select id="aniworld-genre-filter"><option value="">Alle Genres</option></select></label>
          <button id="aniworld-filter-reset" type="button">Filter löschen</button>
        </div>
      </section>

      <section class="aniworld-catalog-panel" aria-labelledby="aniworld-catalog-title">
        <header class="aniworld-catalog-head">
          <div><span class="aniworld-section-code">ANIWORLD / KATALOG</span><h2 id="aniworld-catalog-title">Vollständiger A–Z-Katalog</h2></div>
          <span id="aniworld-catalog-summary">Titel werden geladen</span>
        </header>
        <div id="aniworld-results" class="aniworld-grid" aria-label="AniWorld-Ergebnisse"></div>
        <div id="aniworld-infinite" class="catalog-infinite aniworld-infinite hidden" role="status" aria-live="polite" aria-atomic="true">
          <span class="catalog-infinite-mark" aria-hidden="true"><i></i><i></i><i></i></span>
          <span id="aniworld-infinite-label">Weitere Anime werden beim Scrollen geladen</span>
          <button id="aniworld-infinite-retry" class="btn btn-ghost btn-sm" type="button" hidden>Erneut versuchen</button>
        </div>
      </section>

      <div id="aniworld-detail-modal" class="media-modal aniworld-detail-modal" role="dialog" aria-modal="true" aria-labelledby="aniworld-detail-title" hidden>
        <div class="media-modal-backdrop" data-modal-close="aniworld-detail-modal" aria-hidden="true"></div>
        <div class="aniworld-detail-panel media-modal-panel" tabindex="-1">
          <button class="media-modal-close" type="button" data-modal-close="aniworld-detail-modal" aria-label="AniWorld-Details schließen">×</button>
          <div id="aniworld-detail-banner" class="aniworld-detail-banner" aria-hidden="true"></div>
          <div class="aniworld-detail-scroll">
            <section class="aniworld-detail-profile">
              <div class="aniworld-detail-visual">
                <img id="aniworld-detail-cover" alt="">
                <span id="aniworld-detail-type">DE Anime</span>
              </div>
              <article class="aniworld-detail-copy">
                <span class="aniworld-kicker">ANIWORLD / TITELAKTE</span>
                <h2 id="aniworld-detail-title">Anime auswählen</h2>
                <div id="aniworld-detail-meta" class="aniworld-detail-meta"></div>
                <p id="aniworld-detail-alternatives" class="aniworld-detail-alternatives"></p>
                <p id="aniworld-detail-description"></p>
                <dl id="aniworld-detail-credits" class="aniworld-detail-credits"></dl>
              </article>
            </section>
            <section class="aniworld-episode-console" aria-labelledby="aniworld-track-title">
              <header class="aniworld-track-head">
                <div><span>SPRACHE · STAFFEL · FOLGEN</span><h3 id="aniworld-track-title">Folgen auswählen</h3></div>
                <strong id="aniworld-pick-count">0 ausgewählt</strong>
              </header>
              <div id="aniworld-track-options" class="aniworld-track-options"></div>
              <div id="aniworld-season-options" class="aniworld-season-options" role="group" aria-label="Staffel wählen"></div>
              <div class="aniworld-episode-tools aniworld-season-toolbar">
                <div><strong id="aniworld-current-season">Staffel</strong><span id="aniworld-episode-count">Folgen werden geladen</span></div>
                <button id="aniworld-select-all" type="button">Alle auswählen</button>
                <button id="aniworld-select-none" type="button">Auswahl leeren</button>
              </div>
              <div id="aniworld-episode-grid" class="aniworld-episode-grid"></div>
              <div class="aniworld-download-bar">
                <span><strong id="aniworld-download-count">Keine Folgen ausgewählt</strong><small>Die Auswahl landet direkt in der Warteschlange.</small></span>
                <button id="aniworld-add-btn" class="aniworld-add-button" type="button" disabled>Auswahl herunterladen</button>
              </div>
            </section>
          </div>
        </div>
      </div>
    </section>
  `);
})();

function aniworldModeTitle(mode) {
  return {
    updates: "Neueste Folgen", latest: "Neue Anime", trending: "Gerade im Trend",
    popular: "Beliebte Anime", catalog: "Vollständiger A–Z-Katalog", search: "Suchergebnisse",
  }[mode] || "AniWorld";
}

function setAniworldMode(mode) {
  for (const [id, value] of [
    ["aniworld-updates-btn", "updates"], ["aniworld-latest-btn", "latest"],
    ["aniworld-trending-btn", "trending"], ["aniworld-popular-btn", "popular"],
    ["aniworld-catalog-btn", "catalog"],
  ]) document.getElementById(id)?.classList.toggle("is-active", mode === value);
  document.getElementById("aniworld-catalog-title").textContent = aniworldModeTitle(mode);
  document.getElementById("aniworld-filters").hidden = mode !== "catalog";
}

function aniworldTrackLabel(track) {
  return { dub: "Deutsch Dub", sub: "Deutsch Sub", eng: "Englisch" }[track] || track;
}

function renderAniworldFeature() {
  const feature = document.getElementById("aniworld-featured");
  const anime = state.aniworld.results.find((item) => item.cover_url) || state.aniworld.results[0];
  if (!anime) { feature.hidden = true; feature.onclick = null; return; }
  const artwork = api.coverUrl(anime.banner_url || anime.cover_url || "");
  document.getElementById("aniworld-featured-art").style.backgroundImage = artwork ? `url("${artwork.replace(/"/g, "%22")}")` : "";
  document.getElementById("aniworld-featured-title").textContent = anime.title;
  document.getElementById("aniworld-featured-meta").textContent = [
    anime.latest_season != null ? `S${String(anime.latest_season).padStart(2, "0")}E${String(anime.latest_episode).padStart(2, "0")}` : "",
    anime.year, ...(anime.genres || []).slice(0, 1), "AniWorld",
  ].filter(Boolean).join(" · ");
  feature.setAttribute("aria-label", `${anime.title} öffnen`);
  feature.onclick = () => openAniworldDetail(anime, feature);
  feature.hidden = false;
}

function aniworldCardTracks(anime) {
  const tracks = Object.keys(anime.translations || {}).length ? Object.keys(anime.translations || {}) : (anime.latest_tracks || []);
  return tracks.length ? tracks : ["dub", "sub"];
}

function applyAniworldPoster(anime, posterUrl) {
  if (!anime || !posterUrl) return;
  anime.cover_url = posterUrl;
  state.aniworld.posterCache.set(anime.id, posterUrl);
  const card = [...document.querySelectorAll("#aniworld-results .aniworld-card")]
    .find((candidate) => candidate.dataset.aniworldId === anime.id);
  const shell = card?.querySelector(".aniworld-card-poster");
  if (!shell) return;
  let image = shell.querySelector("img");
  if (!image) {
    image = document.createElement("img");
    image.alt = "";
    image.loading = "lazy";
    shell.prepend(image);
  }
  image.src = api.coverUrl(posterUrl);
}

async function hydrateAniworldPosters(entries) {
  const candidates = (entries || []).filter((anime) => {
    const cached = state.aniworld.posterCache.get(anime.id);
    if (cached) { applyAniworldPoster(anime, cached); return false; }
    return !anime.cover_url && !state.aniworld.posterLoading.has(anime.id);
  });
  const ids = candidates.map((anime) => anime.id);
  if (!ids.length) return;
  ids.forEach((id) => state.aniworld.posterLoading.add(id));
  try {
    const response = await api.aniworldPosters(ids);
    for (const [animeId, posterUrl] of Object.entries(response.posters || {})) {
      const anime = state.aniworld.results.find((item) => item.id === animeId);
      if (anime) applyAniworldPoster(anime, posterUrl);
      else state.aniworld.posterCache.set(animeId, posterUrl);
    }
    renderAniworldFeature();
  } catch (error) {
    console.warn("AniWorld-Poster konnten nicht geladen werden:", error);
  } finally {
    ids.forEach((id) => state.aniworld.posterLoading.delete(id));
  }
}

function renderAniworldResults(appendFrom = 0) {
  const container = document.getElementById("aniworld-results");
  if (appendFrom <= 0) container.innerHTML = "";
  container.setAttribute("aria-busy", state.aniworld.loading ? "true" : "false");
  if (state.aniworld.loading && !state.aniworld.results.length) {
    for (let index = 0; index < 8; index += 1) {
      const skeleton = document.createElement("div");
      skeleton.className = "aniworld-card aniworld-card-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      container.appendChild(skeleton);
    }
  }
  for (const anime of state.aniworld.results.slice(appendFrom)) {
    const cachedPoster = state.aniworld.posterCache.get(anime.id);
    if (cachedPoster) anime.cover_url = cachedPoster;
    const card = document.createElement("button");
    card.className = "aniworld-card";
    card.type = "button";
    card.dataset.aniworldId = anime.id;
    const count = Number(anime.episode_count || 0);
    const tracks = aniworldCardTracks(anime);
    const latest = anime.latest_season != null ? `S${String(anime.latest_season).padStart(2, "0")} · E${String(anime.latest_episode).padStart(2, "0")}` : "";
    card.setAttribute("aria-label", `${anime.title}${count ? `, ${count} Episoden` : ""}`);
    card.innerHTML = `
      <span class="aniworld-card-poster">
        ${anime.cover_url ? `<img src="${escapeHtml(api.coverUrl(anime.cover_url))}" alt="" loading="lazy">` : ""}
        <span class="aniworld-card-fallback">${escapeHtml(mediaCardInitials(anime.title))}</span>
        <span class="aniworld-card-source">AW</span>${latest ? `<span class="aniworld-card-update">${escapeHtml(latest)}</span>` : ""}
      </span>
      <span class="aniworld-card-copy"><strong>${escapeHtml(anime.title)}</strong>
        <small>${escapeHtml([anime.year, ...(anime.genres || []).slice(0, 2), count ? `${count} Folgen` : ""].filter(Boolean).join(" · ") || "AniWorld-Katalog")}</small>
        <span class="aniworld-card-tracks">${tracks.map((track) => `<b class="is-${escapeHtml(track)}">${escapeHtml(track.toUpperCase())}</b>`).join("")}</span>
      </span><span class="aniworld-card-open" aria-hidden="true">↗</span>`;
    card.addEventListener("click", () => openAniworldDetail(anime, card));
    container.appendChild(card);
  }
  if (!state.aniworld.loading && !state.aniworld.results.length) {
    const empty = document.createElement("div");
    empty.className = "aniworld-empty";
    empty.innerHTML = `<strong>${state.aniworld.disabledReason ? "AniWorld ist nicht verfügbar" : "Keine Treffer"}</strong><span>${escapeHtml(state.aniworld.disabledReason || (state.aniworld.mode === "search" ? "Prüfe Titel oder Alternativtitel und starte die Suche erneut." : "Für diese Auswahl meldet AniWorld keine Einträge."))}</span>`;
    container.appendChild(empty);
  }
  renderAniworldFeature();
  const total = Number(state.aniworld.total) || state.aniworld.results.length;
  document.getElementById("aniworld-result-count").textContent = total.toLocaleString("de-DE");
  document.getElementById("aniworld-source-state").textContent = state.aniworld.disabledReason ? "PAUSE" : "LIVE";
  document.getElementById("aniworld-catalog-summary").textContent = `${total.toLocaleString("de-DE")} Titel · ${state.aniworld.results.length} sichtbar`;
  updateAniworldInfiniteState();
}

function updateAniworldInfiniteState() {
  const sentinel = document.getElementById("aniworld-infinite");
  const label = document.getElementById("aniworld-infinite-label");
  const retry = document.getElementById("aniworld-infinite-retry");
  const browsable = Boolean(state.aniworld.mode === "catalog" && state.aniworld.results.length);
  sentinel.classList.toggle("hidden", !browsable);
  if (!browsable) return;
  const count = state.aniworld.results.length;
  sentinel.setAttribute("aria-busy", String(state.aniworld.loading));
  retry.hidden = !state.aniworld.loadError;
  if (state.aniworld.loading) {
    sentinel.dataset.state = "loading"; label.textContent = "Weitere Anime werden geladen …";
  } else if (state.aniworld.loadError) {
    sentinel.dataset.state = "error"; label.textContent = `Nachladen fehlgeschlagen · ${count} Titel geladen`;
  } else if (state.aniworld.hasMore) {
    sentinel.dataset.state = "ready"; label.textContent = `${count} Titel geladen · Weiter scrollen`;
  } else {
    sentinel.dataset.state = "complete"; label.textContent = `${count} Titel geladen · Ende des Katalogs`;
  }
}

function renderAniworldFacets() {
  const letterContainer = document.getElementById("aniworld-letter-filter");
  const letters = state.aniworld.facets?.letters || {};
  letterContainer.innerHTML = "";
  for (const letter of ["ALL", "#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"]) {
    const button = document.createElement("button");
    button.type = "button"; button.textContent = letter === "ALL" ? "Alle" : letter;
    button.classList.toggle("is-active", state.aniworld.letter === letter);
    button.disabled = letter !== "ALL" && !letters[letter];
    button.title = letter === "ALL" ? "Alle Titel" : `${letters[letter] || 0} Titel`;
    button.addEventListener("click", () => { state.aniworld.letter = letter; aniworldBrowse("catalog", 1); });
    letterContainer.appendChild(button);
  }
  const select = document.getElementById("aniworld-genre-filter");
  const selected = state.aniworld.genre;
  select.innerHTML = '<option value="">Alle Genres</option>';
  for (const [genre, count] of Object.entries(state.aniworld.facets?.genres || {})) {
    const option = document.createElement("option");
    option.value = genre; option.textContent = `${genre} (${count})`; option.selected = genre === selected;
    select.appendChild(option);
  }
}

async function aniworldBrowse(mode, page = 1, { append = false } = {}) {
  const query = mode === "search" ? document.getElementById("aniworld-search").value.trim() : "";
  if (mode === "search" && !query) return;
  if (state.aniworld.loading) return;
  state.aniworld.loading = true; state.aniworld.loadError = "";
  if (!append) state.aniworld.results = [];
  const requestSeq = ++state.aniworld.requestSeq;
  setAniworldMode(mode);
  document.getElementById("aniworld-status").textContent = mode === "search" ? `Suche nach „${query}“ …` : `${aniworldModeTitle(mode)} werden geladen …`;
  if (!append) renderAniworldResults(); else updateAniworldInfiniteState();
  try {
    const response = await api.aniworld({ mode, query, page,
      letter: mode === "catalog" && state.aniworld.letter !== "ALL" ? state.aniworld.letter : "",
      genre: mode === "catalog" ? state.aniworld.genre : "" });
    if (requestSeq !== state.aniworld.requestSeq) return;
    const appendFrom = append ? state.aniworld.results.length : 0;
    const incoming = response.results || [];
    state.aniworld.results = append
      ? [...new Map([...state.aniworld.results, ...incoming].map((item) => [item.id, item])).values()]
      : incoming;
    state.aniworld.mode = mode; state.aniworld.query = query;
    state.aniworld.page = Number(response.page) || page; state.aniworld.hasMore = !!response.has_more;
    state.aniworld.total = Number(response.total) || 0; state.aniworld.loaded = true;
    state.aniworld.disabledReason = response.disabled ? response.disabled_reason : "";
    if (response.facets) state.aniworld.facets = response.facets;
    document.getElementById("aniworld-status").textContent = response.disabled ? response.disabled_reason : `${state.aniworld.total.toLocaleString("de-DE")} Titel gefunden`;
    if (mode === "catalog") renderAniworldFacets();
    renderAniworldResults(appendFrom);
    void hydrateAniworldPosters(incoming);
    recheckAniworldInfinite();
  } catch (error) {
    if (requestSeq !== state.aniworld.requestSeq) return;
    if (!append) {
      state.aniworld.results = []; state.aniworld.hasMore = false; state.aniworld.total = 0;
      state.aniworld.disabledReason = error.message;
    } else state.aniworld.loadError = error.message;
    state.aniworld.loaded = true;
    document.getElementById("aniworld-status").textContent = append ? `Nachladen fehlgeschlagen: ${error.message}` : `AniWorld nicht erreichbar: ${error.message}`;
  } finally {
    if (requestSeq === state.aniworld.requestSeq) {
      state.aniworld.loading = false;
      if (!append || state.aniworld.loadError) renderAniworldResults();
      else updateAniworldInfiniteState();
      recheckAniworldInfinite();
    }
  }
}

async function loadNextAniworldPage() {
  if (state.tab !== "aniworld" || state.aniworld.loading || !state.aniworld.hasMore || state.aniworld.mode !== "catalog") return;
  await aniworldBrowse(state.aniworld.mode, state.aniworld.page + 1, { append: true });
}

async function openAniworldDetail(anime, returnFocus = null) {
  state.aniworld.currentId = anime.id; state.aniworld.current = { ...anime, episodes: [] };
  state.aniworld.translation = anime.translations?.dub ? "dub" : (anime.translations?.sub ? "sub" : "");
  state.aniworld.episodePage = 1; state.aniworld.selectedSeason = null;
  state.aniworld.picked.clear();
  document.querySelector("#aniworld-detail-modal .aniworld-detail-scroll").scrollTop = 0;
  openMediaModal("aniworld-detail-modal", returnFocus);
  document.getElementById("aniworld-detail-title").textContent = anime.title;
  document.getElementById("aniworld-detail-description").textContent = "Staffeln, Filme und Sprachspuren werden geladen …";
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
    const detail = await api.aniworldDetail(animeId, state.aniworld.translation, state.aniworld.episodePage, state.aniworld.selectedSeason);
    if (detailSeq !== state.aniworld.detailSeq || animeId !== state.aniworld.currentId) return;
    state.aniworld.current = detail; state.aniworld.translation = detail.translation;
    state.aniworld.episodePage = 1;
    if (state.aniworld.selectedSeason === null || !detail.seasons?.some((item) => item.season === state.aniworld.selectedSeason)) {
      state.aniworld.selectedSeason = detail.seasons?.find((item) => item.season > 0)?.season ?? detail.seasons?.[0]?.season ?? null;
    }
    syncAniworldQueueFlags(); renderAniworldDetail();
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
  cover.src = anime.cover_url ? api.coverUrl(anime.cover_url) : ""; cover.alt = anime.title;
  document.getElementById("aniworld-detail-type").textContent = anime.season_count ? `${anime.season_count} Staffel${anime.season_count === 1 ? "" : "n"}` : "DE Anime";
  document.getElementById("aniworld-detail-banner").style.backgroundImage = anime.banner_url ? `url("${api.coverUrl(anime.banner_url).replace(/"/g, "%22")}")` : "";
  document.getElementById("aniworld-detail-description").textContent = anime.description || "Keine Beschreibung verfügbar.";
  const rating = Number(anime.rating);
  document.getElementById("aniworld-detail-meta").innerHTML = [anime.status, anime.year, anime.country,
    anime.fsk ? `FSK ${anime.fsk}` : "", Number.isFinite(rating) && rating > 0 ? `★ ${rating.toLocaleString("de-DE")} / 5` : "",
    ...(anime.genres || []).slice(0, 6)].filter(Boolean).map((value) => `<span>${escapeHtml(value)}</span>`).join("");
  const alternatives = (anime.alternative_titles || []).slice(0, 6);
  document.getElementById("aniworld-detail-alternatives").textContent = alternatives.length ? `Auch bekannt als: ${alternatives.join(" · ")}` : "";
  const creditRows = [["Regie", anime.directors], ["Studio", anime.producers], ["Stimmen", (anime.cast || []).slice(0, 5)]].filter(([, values]) => values?.length);
  document.getElementById("aniworld-detail-credits").innerHTML = creditRows.map(([label, values]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(values.join(" · "))}</dd></div>`).join("");
  const options = document.getElementById("aniworld-track-options"); options.innerHTML = "";
  for (const [track, countValue] of Object.entries(anime.translations || {})) {
    const count = Number(countValue) || 0; if (!count) continue;
    const button = document.createElement("button"); button.type = "button";
    button.className = `aniworld-track-option is-${track} ${track === state.aniworld.translation ? "is-active" : ""}`;
    button.innerHTML = `<b>${escapeHtml(track.toUpperCase())}</b><span><strong>${escapeHtml(anime.translation_labels?.[track] || aniworldTrackLabel(track))}</strong><small>${count} Einträge verfügbar</small></span>`;
    button.addEventListener("click", () => {
      if (track === state.aniworld.translation) return;
      state.aniworld.translation = track; state.aniworld.episodePage = 1; state.aniworld.selectedSeason = null;
      loadAniworldDetail();
    });
    options.appendChild(button);
  }
  renderAniworldSeasons(); renderAniworldEpisodes();
}

function renderAniworldSeasons() {
  const anime = state.aniworld.current; const container = document.getElementById("aniworld-season-options"); container.innerHTML = "";
  for (const choice of anime?.seasons || []) {
    const button = document.createElement("button"); button.type = "button";
    button.classList.toggle("is-active", choice.season === state.aniworld.selectedSeason);
    button.innerHTML = `<strong>${escapeHtml(choice.label)}</strong><small>${Number(choice.count) || 0}</small>`;
    button.addEventListener("click", () => {
      if (choice.season === state.aniworld.selectedSeason) return;
      state.aniworld.selectedSeason = choice.season;
      renderAniworldSeasons(); renderAniworldEpisodes();
    });
    container.appendChild(button);
  }
}

function aniworldVisibleEpisodes() {
  return (state.aniworld.current?.episodes || []).filter((episode) => episode.season === state.aniworld.selectedSeason);
}

function aniworldSelectableEpisodes() {
  return aniworldVisibleEpisodes().filter((episode) => !episode.downloaded && !episode.queued && !state.queuedSlugs.has(episode.slug));
}

function renderAniworldEpisodes() {
  const anime = state.aniworld.current; const container = document.getElementById("aniworld-episode-grid"); container.innerHTML = "";
  const visible = aniworldVisibleEpisodes();
  if (!anime?.episodes?.length || !visible.length) container.innerHTML = '<div class="aniworld-empty is-compact"><strong>Keine Folgen verfügbar</strong><span>Wähle eine andere Staffel oder Sprachspur.</span></div>';
  for (const episode of visible) {
    const selected = state.aniworld.picked.has(episode.slug); const queued = episode.queued || state.queuedSlugs.has(episode.slug);
    const button = document.createElement("button"); button.type = "button";
    button.className = "aniworld-episode" + (selected ? " is-selected" : "") + (queued ? " is-queued" : "") + (episode.downloaded ? " is-downloaded" : "");
    const code = episode.kind === "movie" ? `FILM ${String(episode.number).padStart(2, "0")}` : `S${String(episode.season).padStart(2, "0")} · E${String(episode.number).padStart(2, "0")}`;
    const stateLabel = episode.downloaded ? "Geladen" : (queued ? "Queue" : (selected ? "Ausgewählt" : "Verfügbar"));
    const secondary = [episode.original_title && episode.original_title !== episode.title ? episode.original_title : "", ...(episode.hosters || []).slice(0, 3)].filter(Boolean).join(" · ");
    button.innerHTML = `<span class="aniworld-episode-code">${escapeHtml(code)}</span><span class="aniworld-episode-title"><strong>${escapeHtml(episode.title || episode.label)}</strong>${secondary ? `<small>${escapeHtml(secondary)}</small>` : ""}</span><span class="aniworld-episode-state">${escapeHtml(stateLabel)}</span>`;
    button.title = `${episode.label}${episode.title ? ` · ${episode.title}` : ""}`; button.disabled = queued || episode.downloaded;
    button.addEventListener("click", () => { if (selected) state.aniworld.picked.delete(episode.slug); else state.aniworld.picked.add(episode.slug); renderAniworldEpisodes(); });
    container.appendChild(button);
  }
  const season = (anime?.seasons || []).find((item) => item.season === state.aniworld.selectedSeason);
  document.getElementById("aniworld-current-season").textContent = season?.label || "Staffel";
  document.getElementById("aniworld-episode-count").textContent = `${visible.length} ${visible.length === 1 ? "Eintrag" : "Einträge"}`;
  document.getElementById("aniworld-pick-count").textContent = `${state.aniworld.picked.size} ausgewählt`;
  document.getElementById("aniworld-select-all").disabled = !aniworldSelectableEpisodes().length;
  document.getElementById("aniworld-select-none").disabled = !state.aniworld.picked.size;
  document.getElementById("aniworld-add-btn").disabled = !state.aniworld.picked.size;
  document.getElementById("aniworld-add-btn").textContent = state.aniworld.picked.size ? `${state.aniworld.picked.size} Einträge herunterladen` : "Auswahl herunterladen";
  document.getElementById("aniworld-download-count").textContent = state.aniworld.picked.size ? `${state.aniworld.picked.size} ausgewählt` : "Keine Folgen ausgewählt";
}

function syncAniworldQueueFlags() {
  const anime = state.aniworld.current; if (!anime?.episodes) return;
  for (const episode of anime.episodes) { episode.queued = state.queuedSlugs.has(episode.slug); if (episode.queued) state.aniworld.picked.delete(episode.slug); }
  const modal = document.getElementById("aniworld-detail-modal"); if (modal && !modal.hidden) renderAniworldEpisodes();
}

function markAniworldSlugDownloaded(slug) {
  const anime = state.aniworld.current; const episode = anime?.episodes?.find((item) => item.slug === slug); if (!episode) return;
  episode.downloaded = true; episode.queued = false; state.aniworld.picked.delete(slug); renderAniworldEpisodes();
}

async function aniworldAddSelected() {
  const slugs = [...state.aniworld.picked]; if (!slugs.length) return;
  document.getElementById("aniworld-add-btn").disabled = true;
  document.getElementById("aniworld-pick-count").textContent = "wird eingeplant …";
  try {
    const response = await api.queueAdd(slugs, {}, "anime"); refreshQueueUiAfterChange(response); state.aniworld.picked.clear();
    document.getElementById("aniworld-status").textContent = `${response.added}/${slugs.length} AniWorld-Einträge eingeplant`;
  } catch (error) { document.getElementById("aniworld-status").textContent = `Download fehlgeschlagen: ${error.message}`; }
  finally { renderAniworldEpisodes(); }
}
