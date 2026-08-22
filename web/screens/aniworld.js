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
          <span id="aniworld-status" role="status" aria-live="polite">Wird beim Öffnen geladen …</span>
        </div>
        <div class="aniworld-command-row">
          <label class="aniworld-search-field">
            <span aria-hidden="true">⌕</span>
            <input id="aniworld-search" type="search" autocomplete="off" placeholder="Titel oder Alternativtitel suchen">
          </label>
          <button id="aniworld-search-btn" class="aniworld-search-submit" type="button">Suchen</button>
          <div class="aniworld-mode-switch" role="group" aria-label="Katalogansicht">
            <button id="aniworld-updates-btn" type="button">Neue Folgen</button>
            <button id="aniworld-latest-btn" class="is-active" type="button">Neue Anime</button>
            <button id="aniworld-trending-btn" type="button">Trending</button>
            <button id="aniworld-popular-btn" type="button">Beliebt</button>
            <button id="aniworld-catalog-btn" type="button">A–Z</button>
          </div>
        </div>
        <div id="aniworld-filters" class="aniworld-filter-deck" hidden>
          <div id="aniworld-letter-filter" class="aniworld-letter-filter" role="group" aria-label="Anfangsbuchstabe"></div>
          <label><span>Genre</span><select id="aniworld-genre-filter"><option value="">Alle Genres</option></select></label>
          <button id="aniworld-filter-reset" type="button">Filter löschen</button>
        </div>
      </section>

      <section class="aniworld-catalog-panel" aria-labelledby="aniworld-catalog-title">
        <header class="aniworld-catalog-head">
          <div><span class="aniworld-section-code">ANIWORLD / KATALOG</span><h2 id="aniworld-catalog-title">Neu im Archiv</h2></div>
          <span id="aniworld-catalog-summary">Seite 1</span>
        </header>
        <div id="aniworld-results" class="aniworld-grid" aria-label="AniWorld-Ergebnisse"></div>
        <div id="aniworld-pager" class="aniworld-pager">
          <button id="aniworld-prev" type="button" disabled>‹ Vorherige</button>
          <span id="aniworld-page-label">Seite 1</span>
          <button id="aniworld-next" type="button" disabled>Nächste ›</button>
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
                <div><span>SPRACHE / STAFFEL / FOLGE</span><h3 id="aniworld-track-title">Download zusammenstellen</h3></div>
                <strong id="aniworld-pick-count">0 ausgewählt</strong>
              </header>
              <div id="aniworld-track-options" class="aniworld-track-options"></div>
              <div id="aniworld-season-options" class="aniworld-season-options" role="group" aria-label="Staffel wählen"></div>
              <div class="aniworld-episode-tools">
                <label class="aniworld-episode-search"><span aria-hidden="true">⌕</span><input id="aniworld-episode-search" type="search" placeholder="Folge oder Titel filtern"></label>
                <label><span>Status</span><select id="aniworld-episode-status"><option value="all">Alle</option><option value="available">Verfügbar</option><option value="queued">In Queue</option><option value="downloaded">Geladen</option></select></label>
                <button id="aniworld-select-page" type="button">Sichtbare wählen</button>
                <button id="aniworld-select-season" type="button">Staffel wählen</button>
                <button id="aniworld-select-none" type="button">Auswahl leeren</button>
              </div>
              <div class="aniworld-episode-nav">
                <span id="aniworld-episode-page-label">Episoden werden geladen</span>
                <button id="aniworld-episode-prev" type="button" disabled aria-label="Vorherige Episodenseite">‹</button>
                <button id="aniworld-episode-next" type="button" disabled aria-label="Nächste Episodenseite">›</button>
              </div>
              <div id="aniworld-episode-grid" class="aniworld-episode-grid"></div>
              <div class="aniworld-episode-legend"><span><i class="is-free"></i>Verfügbar</span><span><i class="is-picked"></i>Ausgewählt</span><span><i class="is-queued"></i>Queue</span><span><i class="is-downloaded"></i>Geladen</span></div>
              <button id="aniworld-add-btn" class="aniworld-add-button" type="button" disabled>Auswahl herunterladen</button>
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

function renderAniworldResults() {
  const container = document.getElementById("aniworld-results");
  container.innerHTML = "";
  container.setAttribute("aria-busy", state.aniworld.loading ? "true" : "false");
  if (state.aniworld.loading && !state.aniworld.results.length) {
    for (let index = 0; index < 8; index += 1) {
      const skeleton = document.createElement("div");
      skeleton.className = "aniworld-card aniworld-card-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      container.appendChild(skeleton);
    }
  }
  for (const anime of state.aniworld.results) {
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
  document.getElementById("aniworld-page-label").textContent = `Seite ${state.aniworld.page}`;
  document.getElementById("aniworld-prev").disabled = state.aniworld.loading || state.aniworld.page <= 1;
  document.getElementById("aniworld-next").disabled = state.aniworld.loading || !state.aniworld.hasMore;
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

async function aniworldBrowse(mode, page = 1) {
  const query = mode === "search" ? document.getElementById("aniworld-search").value.trim() : "";
  if (mode === "search" && !query) return;
  if (state.aniworld.loading) return;
  state.aniworld.loading = true; state.aniworld.results = [];
  const requestSeq = ++state.aniworld.requestSeq;
  setAniworldMode(mode);
  document.getElementById("aniworld-status").textContent = mode === "search" ? `Suche nach „${query}“ …` : `${aniworldModeTitle(mode)} werden geladen …`;
  renderAniworldResults();
  try {
    const response = await api.aniworld({ mode, query, page,
      letter: mode === "catalog" && state.aniworld.letter !== "ALL" ? state.aniworld.letter : "",
      genre: mode === "catalog" ? state.aniworld.genre : "" });
    if (requestSeq !== state.aniworld.requestSeq) return;
    state.aniworld.results = response.results || []; state.aniworld.mode = mode; state.aniworld.query = query;
    state.aniworld.page = Number(response.page) || page; state.aniworld.hasMore = !!response.has_more;
    state.aniworld.total = Number(response.total) || 0; state.aniworld.loaded = true;
    state.aniworld.disabledReason = response.disabled ? response.disabled_reason : "";
    if (response.facets) state.aniworld.facets = response.facets;
    document.getElementById("aniworld-status").textContent = response.disabled ? response.disabled_reason : `${state.aniworld.total.toLocaleString("de-DE")} Titel gefunden`;
    if (mode === "catalog") renderAniworldFacets();
  } catch (error) {
    if (requestSeq !== state.aniworld.requestSeq) return;
    state.aniworld.results = []; state.aniworld.hasMore = false; state.aniworld.total = 0;
    state.aniworld.loaded = true; state.aniworld.disabledReason = error.message;
    document.getElementById("aniworld-status").textContent = `AniWorld nicht erreichbar: ${error.message}`;
  } finally {
    if (requestSeq === state.aniworld.requestSeq) { state.aniworld.loading = false; renderAniworldResults(); }
  }
}

async function openAniworldDetail(anime, returnFocus = null) {
  state.aniworld.currentId = anime.id; state.aniworld.current = { ...anime, episodes: [] };
  state.aniworld.translation = anime.translations?.dub ? "dub" : (anime.translations?.sub ? "sub" : "");
  state.aniworld.episodePage = 1; state.aniworld.selectedSeason = null;
  state.aniworld.episodeQuery = ""; state.aniworld.episodeStatus = "all"; state.aniworld.picked.clear();
  document.getElementById("aniworld-episode-search").value = "";
  document.getElementById("aniworld-episode-status").value = "all";
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
    state.aniworld.episodePage = detail.page; state.aniworld.selectedSeason = detail.season;
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
  const choices = [{ season: null, label: "Alles", count: anime?.translations?.[state.aniworld.translation] || 0 }, ...(anime?.seasons || [])];
  for (const choice of choices) {
    const button = document.createElement("button"); button.type = "button";
    button.classList.toggle("is-active", choice.season === state.aniworld.selectedSeason);
    button.innerHTML = `<strong>${escapeHtml(choice.label)}</strong><small>${Number(choice.count) || 0}</small>`;
    button.addEventListener("click", () => {
      if (choice.season === state.aniworld.selectedSeason) return;
      state.aniworld.selectedSeason = choice.season; state.aniworld.episodePage = 1;
      loadAniworldDetail({ keepSelection: true });
    });
    container.appendChild(button);
  }
  document.getElementById("aniworld-select-season").hidden = state.aniworld.selectedSeason === null;
}

function aniworldVisibleEpisodes() {
  const query = String(state.aniworld.episodeQuery || "").trim().toLowerCase();
  const status = state.aniworld.episodeStatus || "all";
  return (state.aniworld.current?.episodes || []).filter((episode) => {
    const queued = episode.queued || state.queuedSlugs.has(episode.slug);
    const matchesStatus = status === "all" || (status === "available" && !queued && !episode.downloaded)
      || (status === "queued" && queued) || (status === "downloaded" && episode.downloaded);
    const haystack = `${episode.label} ${episode.title || ""} ${episode.original_title || ""}`.toLowerCase();
    return matchesStatus && (!query || haystack.includes(query));
  });
}

function aniworldSelectableEpisodes() {
  return aniworldVisibleEpisodes().filter((episode) => !episode.downloaded && !episode.queued && !state.queuedSlugs.has(episode.slug));
}

function renderAniworldEpisodes() {
  const anime = state.aniworld.current; const container = document.getElementById("aniworld-episode-grid"); container.innerHTML = "";
  const visible = aniworldVisibleEpisodes();
  if (!anime?.episodes?.length || !visible.length) container.innerHTML = '<div class="aniworld-empty is-compact"><strong>Keine passenden Einträge</strong><span>Ändere Staffel, Status oder Suchtext.</span></div>';
  for (const episode of visible) {
    const selected = state.aniworld.picked.has(episode.slug); const queued = episode.queued || state.queuedSlugs.has(episode.slug);
    const button = document.createElement("button"); button.type = "button";
    button.className = "aniworld-episode" + (selected ? " is-selected" : "") + (queued ? " is-queued" : "") + (episode.downloaded ? " is-downloaded" : "");
    const code = episode.kind === "movie" ? `FILM ${String(episode.number).padStart(2, "0")}` : `S${String(episode.season).padStart(2, "0")} · E${String(episode.number).padStart(2, "0")}`;
    const stateLabel = episode.downloaded ? "Geladen" : (queued ? "Queue" : (selected ? "Ausgewählt" : "Verfügbar"));
    button.innerHTML = `<span class="aniworld-episode-code">${escapeHtml(code)}</span><span class="aniworld-episode-title"><strong>${escapeHtml(episode.title || episode.label)}</strong>${episode.original_title && episode.original_title !== episode.title ? `<small>${escapeHtml(episode.original_title)}</small>` : ""}</span><span class="aniworld-episode-hosters">${(episode.hosters || []).slice(0, 3).map((hoster) => `<i>${escapeHtml(hoster)}</i>`).join("") || "Hoster beim Start"}</span><span class="aniworld-episode-state">${escapeHtml(stateLabel)}</span>`;
    button.title = `${episode.label}${episode.title ? ` · ${episode.title}` : ""}`; button.disabled = queued || episode.downloaded;
    button.addEventListener("click", () => { if (selected) state.aniworld.picked.delete(episode.slug); else state.aniworld.picked.add(episode.slug); renderAniworldEpisodes(); });
    container.appendChild(button);
  }
  document.getElementById("aniworld-episode-page-label").textContent = anime ? `${visible.length} von ${anime.total} Einträgen · Seite ${anime.page}/${anime.page_count}` : "Episoden werden geladen";
  document.getElementById("aniworld-episode-prev").disabled = !anime || anime.page <= 1;
  document.getElementById("aniworld-episode-next").disabled = !anime || anime.page >= anime.page_count;
  document.getElementById("aniworld-pick-count").textContent = `${state.aniworld.picked.size} ausgewählt`;
  document.getElementById("aniworld-select-page").disabled = !aniworldSelectableEpisodes().length;
  document.getElementById("aniworld-select-season").disabled = !aniworldSelectableEpisodes().length;
  document.getElementById("aniworld-select-none").disabled = !state.aniworld.picked.size;
  document.getElementById("aniworld-add-btn").disabled = !state.aniworld.picked.size;
  document.getElementById("aniworld-add-btn").textContent = state.aniworld.picked.size ? `${state.aniworld.picked.size} Einträge herunterladen` : "Auswahl herunterladen";
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
