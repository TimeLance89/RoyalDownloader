import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { escapeHtml } from "../../shared/utils/escape-html.js";

export function createAniworld(root, modal, {
  getQueuedSlugs, coverUrl, mediaCardInitials, openMediaModal, recheckAniworldInfinite,
  refreshQueueUiAfterChange, client = api,
}) {
  const data = {
    results: [], mode: null, query: "", page: 1, hasMore: false,
    total: 0, facets: { letters: {}, genres: {} }, letter: "ALL", genre: "",
    loaded: false, loading: false, requestSeq: 0, detailSeq: 0,
    currentId: "", current: null, translation: "", episodePage: 1,
    selectedSeason: null, picked: new Set(), disabledReason: "", loadError: "", posterCache: new Map(),
  };
  const byId = id => root.querySelector(`#${id}`) || (modal.id === id ? modal : modal.querySelector(`#${id}`));
  const callbacks = new WeakMap(), posterJobs = new Set(), posterLoading = new Map();
  let session = createScope(), view = null, detail = null;
  let cancelBrowse = null, cancelDetail = null, queuePending = false;
  function dispatch(event) {
    for (let node = event.target; node; node = node.parentElement) {
      const callback = callbacks.get(node);
      if (callback) { callback(event); return; }
      if (node === root || node === modal) return;
    }
  }
  function cancelPosters() { for (const job of posterJobs) job.dispose(); posterJobs.clear(); posterLoading.clear(); }
  function closeDetail() { detail?.dispose(); detail = null; cancelDetail = null; }
  function mountDetail() {
    closeDetail(); detail = createScope(); detail.listen(modal, "click", dispatch);
    const selectVisibleAniworldEpisodes = () => {
      for (const episode of aniworldSelectableEpisodes()) data.picked.add(episode.slug);
      renderAniworldEpisodes();
    };
    detail.listen(byId("aniworld-select-all"), "click", selectVisibleAniworldEpisodes);
    detail.listen(byId("aniworld-select-none"), "click", () => {
      data.picked.clear();
      renderAniworldEpisodes();
    });
    detail.listen(byId("aniworld-add-btn"), "click", aniworldAddSelected);
  }
  function mount() {
    if (view?.active || !session.active) return;
    view = createScope(); view.listen(root, "click", dispatch);
    view.listen(byId("aniworld-search-btn"), "click", () => aniworldBrowse("search", 1));
    view.listen(byId("aniworld-search"), "keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      aniworldBrowse("search", 1);
    });
    view.listen(byId("aniworld-latest-btn"), "click", () => aniworldBrowse("latest", 1));
    view.listen(byId("aniworld-updates-btn"), "click", () => aniworldBrowse("updates", 1));
    view.listen(byId("aniworld-trending-btn"), "click", () => aniworldBrowse("trending", 1));
    view.listen(byId("aniworld-popular-btn"), "click", () => aniworldBrowse("popular", 1));
    view.listen(byId("aniworld-catalog-btn"), "click", () => aniworldBrowse("catalog", 1));
    view.listen(byId("aniworld-genre-filter"), "change", (event) => {
      data.genre = event.currentTarget.value; aniworldBrowse("catalog", 1);
    });
    view.listen(byId("aniworld-filter-reset"), "click", () => {
      Object.assign(data, { letter: "ALL", genre: "" }); aniworldBrowse("catalog", 1);
    });
  }
  function unmount() { cancelPosters(); view?.dispose(); view = null; cancelBrowse = null; data.loading = false; }
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
    ]) byId(id)?.classList.toggle("is-active", mode === value);
    byId("aniworld-catalog-title").textContent = aniworldModeTitle(mode);
    byId("aniworld-filters").hidden = mode !== "catalog";
  }

  function aniworldTrackLabel(track) {
    return { dub: "Deutsch Dub", sub: "Deutsch Sub", eng: "Englisch" }[track] || track;
  }

  function renderAniworldFeature() {
    const feature = byId("aniworld-featured");
    const anime = data.results.find((item) => item.cover_url) || data.results[0];
    if (!anime) { feature.hidden = true; callbacks.delete(feature); return; }
    const artwork = coverUrl(anime.banner_url || anime.cover_url || "");
    byId("aniworld-featured-art").style.backgroundImage = artwork ? `url("${artwork.replace(/"/g, "%22")}")` : "";
    byId("aniworld-featured-title").textContent = anime.title;
    byId("aniworld-featured-meta").textContent = [
      anime.latest_season != null ? `S${String(anime.latest_season).padStart(2, "0")}E${String(anime.latest_episode).padStart(2, "0")}` : "",
      anime.year, ...(anime.genres || []).slice(0, 1), "AniWorld",
    ].filter(Boolean).join(" · ");
    feature.setAttribute("aria-label", `${anime.title} öffnen`);
    callbacks.set(feature, () => openAniworldDetail(anime, feature));
    feature.hidden = false;
  }

  function aniworldCardTracks(anime) {
    const tracks = Object.keys(anime.translations || {}).length ? Object.keys(anime.translations || {}) : (anime.latest_tracks || []);
    return tracks.length ? tracks : ["dub", "sub"];
  }

  function applyAniworldPoster(anime, posterUrl) {
    if (!anime || !posterUrl) return;
    anime.cover_url = posterUrl;
    data.posterCache.set(anime.id, posterUrl);
    const card = [...root.querySelectorAll("#aniworld-results .aniworld-card")]
      .find((candidate) => candidate.dataset.aniworldId === anime.id);
    const shell = card?.querySelector(".aniworld-card-poster");
    if (!shell) return;
    let image = shell.querySelector("img");
    if (!image) {
      image = root.ownerDocument.createElement("img");
      image.alt = "";
      image.loading = "lazy";
      shell.prepend(image);
    }
    image.src = coverUrl(posterUrl);
  }

  async function hydrateAniworldPosters(entries) {
    if (!view?.active) return;
    const request = createScope();
    const release = view.add(() => request.dispose());
    posterJobs.add(request);
    const candidates = (entries || []).filter((anime) => {
      const cached = data.posterCache.get(anime.id);
      if (cached) { applyAniworldPoster(anime, cached); return false; }
      return !anime.cover_url && !posterLoading.has(anime.id);
    });
    const ids = candidates.map((anime) => anime.id);
    if (!ids.length) { release(); posterJobs.delete(request); return; }
    ids.forEach(id => posterLoading.set(id, request));
    try {
      const response = await client.post("/api/aniworld/posters", { ids }, { signal: request.signal });
      if (!request.active) return;
      for (const [animeId, posterUrl] of Object.entries(response.posters || {})) {
        const anime = data.results.find((item) => item.id === animeId);
        if (anime) applyAniworldPoster(anime, posterUrl);
        else data.posterCache.set(animeId, posterUrl);
      }
      renderAniworldFeature();
    } catch (error) {
      if (!request.active) return;
      console.warn("AniWorld-Poster konnten nicht geladen werden:", error);
    } finally {
      ids.forEach(id => { if (posterLoading.get(id) === request) posterLoading.delete(id); });
      release(); posterJobs.delete(request);
    }
  }

  function renderAniworldResults(appendFrom = 0) {
    const container = byId("aniworld-results");
    if (appendFrom <= 0) container.innerHTML = "";
    container.setAttribute("aria-busy", data.loading ? "true" : "false");
    if (data.loading && !data.results.length) {
      for (let index = 0; index < 8; index += 1) {
        const skeleton = root.ownerDocument.createElement("div");
        skeleton.className = "aniworld-card aniworld-card-skeleton";
        skeleton.setAttribute("aria-hidden", "true");
        container.appendChild(skeleton);
      }
    }
    for (const anime of data.results.slice(appendFrom)) {
      const cachedPoster = data.posterCache.get(anime.id);
      if (cachedPoster) anime.cover_url = cachedPoster;
      const card = root.ownerDocument.createElement("button");
      card.className = "aniworld-card";
      card.type = "button";
      card.dataset.aniworldId = anime.id;
      const count = Number(anime.episode_count || 0);
      const tracks = aniworldCardTracks(anime);
      const latest = anime.latest_season != null ? `S${String(anime.latest_season).padStart(2, "0")} · E${String(anime.latest_episode).padStart(2, "0")}` : "";
      card.setAttribute("aria-label", `${anime.title}${count ? `, ${count} Episoden` : ""}`);
      card.innerHTML = `
        <span class="aniworld-card-poster">
          ${anime.cover_url ? `<img src="${escapeHtml(coverUrl(anime.cover_url))}" alt="" loading="lazy">` : ""}
          <span class="aniworld-card-fallback">${escapeHtml(mediaCardInitials(anime.title))}</span>
          <span class="aniworld-card-source">AW</span>${latest ? `<span class="aniworld-card-update">${escapeHtml(latest)}</span>` : ""}
        </span>
        <span class="aniworld-card-copy"><strong>${escapeHtml(anime.title)}</strong>
          <small>${escapeHtml([anime.year, ...(anime.genres || []).slice(0, 2), count ? `${count} Folgen` : ""].filter(Boolean).join(" · ") || "AniWorld-Katalog")}</small>
          <span class="aniworld-card-tracks">${tracks.map((track) => `<b class="is-${escapeHtml(track)}">${escapeHtml(track.toUpperCase())}</b>`).join("")}</span>
        </span><span class="aniworld-card-open" aria-hidden="true">↗</span>`;
      callbacks.set(card, () => openAniworldDetail(anime, card));
      container.appendChild(card);
    }
    if (!data.loading && !data.results.length) {
      const empty = root.ownerDocument.createElement("div");
      empty.className = "aniworld-empty";
      empty.innerHTML = `<strong>${data.disabledReason ? "AniWorld ist nicht verfügbar" : "Keine Treffer"}</strong><span>${escapeHtml(data.disabledReason || (data.mode === "search" ? "Prüfe Titel oder Alternativtitel und starte die Suche erneut." : "Für diese Auswahl meldet AniWorld keine Einträge."))}</span>`;
      container.appendChild(empty);
    }
    renderAniworldFeature();
    const total = Number(data.total) || data.results.length;
    byId("aniworld-result-count").textContent = total.toLocaleString("de-DE");
    byId("aniworld-source-state").textContent = data.disabledReason ? "PAUSE" : "LIVE";
    byId("aniworld-catalog-summary").textContent = `${total.toLocaleString("de-DE")} Titel · ${data.results.length} sichtbar`;
    updateAniworldInfiniteState();
  }

  function updateAniworldInfiniteState() {
    const sentinel = byId("aniworld-infinite");
    const label = byId("aniworld-infinite-label");
    const retry = byId("aniworld-infinite-retry");
    const browsable = Boolean(data.mode === "catalog" && data.results.length);
    sentinel.classList.toggle("hidden", !browsable);
    if (!browsable) return;
    const count = data.results.length;
    sentinel.setAttribute("aria-busy", String(data.loading));
    retry.hidden = !data.loadError;
    if (data.loading) {
      sentinel.dataset.state = "loading"; label.textContent = "Weitere Anime werden geladen …";
    } else if (data.loadError) {
      sentinel.dataset.state = "error"; label.textContent = `Nachladen fehlgeschlagen · ${count} Titel geladen`;
    } else if (data.hasMore) {
      sentinel.dataset.state = "ready"; label.textContent = `${count} Titel geladen · Weiter scrollen`;
    } else {
      sentinel.dataset.state = "complete"; label.textContent = `${count} Titel geladen · Ende des Katalogs`;
    }
  }

  function renderAniworldFacets() {
    const letterContainer = byId("aniworld-letter-filter");
    const letters = data.facets?.letters || {};
    letterContainer.innerHTML = "";
    for (const letter of ["ALL", "#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"]) {
      const button = root.ownerDocument.createElement("button");
      button.type = "button"; button.textContent = letter === "ALL" ? "Alle" : letter;
      button.classList.toggle("is-active", data.letter === letter);
      button.disabled = letter !== "ALL" && !letters[letter];
      button.title = letter === "ALL" ? "Alle Titel" : `${letters[letter] || 0} Titel`;
      callbacks.set(button, () => { data.letter = letter; aniworldBrowse("catalog", 1); });
      letterContainer.appendChild(button);
    }
    const select = byId("aniworld-genre-filter");
    const selected = data.genre;
    select.innerHTML = '<option value="">Alle Genres</option>';
    for (const [genre, count] of Object.entries(data.facets?.genres || {})) {
      const option = root.ownerDocument.createElement("option");
      option.value = genre; option.textContent = `${genre} (${count})`; option.selected = genre === selected;
      select.appendChild(option);
    }
  }

  async function aniworldBrowse(mode, page = 1, { append = false } = {}) {
    if (!view?.active) return;
    const mounted = view;
    const query = mode === "search" ? byId("aniworld-search").value.trim() : "";
    if (mode === "search" && !query) return;
    if (data.loading && append) return;
    cancelBrowse?.();
    if (!append) cancelPosters();
    const request = createScope();
    cancelBrowse = view.add(() => request.dispose());
    data.loading = true; data.loadError = "";
    if (!append) data.results = [];
    const requestSeq = ++data.requestSeq;
    setAniworldMode(mode);
    byId("aniworld-status").textContent = mode === "search" ? `Suche nach „${query}“ …` : `${aniworldModeTitle(mode)} werden geladen …`;
    if (!append) renderAniworldResults(); else updateAniworldInfiniteState();
    try {
      const response = await client.get(`/api/aniworld?${new URLSearchParams({ mode, query, page,
        letter: mode === "catalog" && data.letter !== "ALL" ? data.letter : "",
        genre: mode === "catalog" ? data.genre : "" })}`, { signal: request.signal });
      if (!mounted.active || !request.active || requestSeq !== data.requestSeq) return;
      const appendFrom = append ? data.results.length : 0;
      const incoming = response.results || [];
      data.results = append
        ? [...new Map([...data.results, ...incoming].map((item) => [item.id, item])).values()]
        : incoming;
      data.mode = mode; data.query = query;
      data.page = Number(response.page) || page; data.hasMore = !!response.has_more;
      data.total = Number(response.total) || 0; data.loaded = true;
      data.disabledReason = response.disabled ? response.disabled_reason : "";
      if (response.facets) data.facets = response.facets;
      byId("aniworld-status").textContent = response.disabled ? response.disabled_reason : `${data.total.toLocaleString("de-DE")} Titel gefunden`;
      if (mode === "catalog") renderAniworldFacets();
      renderAniworldResults(appendFrom);
      void hydrateAniworldPosters(incoming);
      recheckAniworldInfinite();
    } catch (error) {
      if (!mounted.active || !request.active || requestSeq !== data.requestSeq) return;
      if (!append) {
        data.results = []; data.hasMore = false; data.total = 0;
        data.disabledReason = error.message;
      } else data.loadError = error.message;
      data.loaded = true;
      byId("aniworld-status").textContent = append ? `Nachladen fehlgeschlagen: ${error.message}` : `AniWorld nicht erreichbar: ${error.message}`;
    } finally {
      if (mounted.active && request.active && requestSeq === data.requestSeq) {
        data.loading = false;
        if (!append || data.loadError) renderAniworldResults();
        else updateAniworldInfiniteState();
        recheckAniworldInfinite();
      }
    }
  }

  async function loadNextAniworldPage() {
    if (!view?.active || data.loading || !data.hasMore || data.mode !== "catalog") return;
    await aniworldBrowse(data.mode, data.page + 1, { append: true });
  }

  async function openAniworldDetail(anime, returnFocus = null) {
    if (!session.active) return;
    mountDetail();
    data.currentId = anime.id; data.current = { ...anime, episodes: [] };
    data.translation = anime.translations?.dub ? "dub" : (anime.translations?.sub ? "sub" : "");
    data.episodePage = 1; data.selectedSeason = null;
    data.picked.clear();
    modal.querySelector(".aniworld-detail-scroll").scrollTop = 0;
    openMediaModal("aniworld-detail-modal", returnFocus);
    byId("aniworld-detail-title").textContent = anime.title;
    byId("aniworld-detail-description").textContent = "Staffeln, Filme und Sprachspuren werden geladen …";
    byId("aniworld-track-options").replaceChildren();
    byId("aniworld-season-options").replaceChildren();
    renderAniworldEpisodes();
    await loadAniworldDetail();
  }

  async function loadAniworldDetail({ keepSelection = false } = {}) {
    if (!detail?.active) return;
    cancelDetail?.();
    const request = createScope();
    cancelDetail = detail.add(() => request.dispose());
    const animeId = data.currentId;
    if (!animeId) return;
    const detailSeq = ++data.detailSeq;
    if (!keepSelection) data.picked.clear();
    byId("aniworld-pick-count").textContent = "wird geladen";
    byId("aniworld-add-btn").disabled = true;
    try {
      const params = new URLSearchParams({ translation: data.translation, episode_page: String(data.episodePage) });
      if (data.selectedSeason !== null && data.selectedSeason !== undefined && data.selectedSeason !== "") params.set("season", String(data.selectedSeason));
      const detail = await client.get(`/api/aniworld/${encodeURIComponent(animeId)}?${params}`, { signal: request.signal });
      if (!request.active || detailSeq !== data.detailSeq || animeId !== data.currentId) return;
      data.current = detail; data.translation = detail.translation;
      data.episodePage = 1;
      if (data.selectedSeason === null || !detail.seasons?.some((item) => item.season === data.selectedSeason)) {
        data.selectedSeason = detail.seasons?.find((item) => item.season > 0)?.season ?? detail.seasons?.[0]?.season ?? null;
      }
      syncAniworldQueueFlags(); renderAniworldDetail();
    } catch (error) {
      if (!request.active || detailSeq !== data.detailSeq) return;
      byId("aniworld-detail-description").textContent = error.message;
      byId("aniworld-pick-count").textContent = "nicht verfügbar";
    }
  }

  function renderAniworldDetail() {
    const anime = data.current;
    if (!anime) return;
    byId("aniworld-detail-title").textContent = anime.title;
    const cover = byId("aniworld-detail-cover");
    cover.src = anime.cover_url ? coverUrl(anime.cover_url) : ""; cover.alt = anime.title;
    byId("aniworld-detail-type").textContent = anime.season_count ? `${anime.season_count} Staffel${anime.season_count === 1 ? "" : "n"}` : "DE Anime";
    byId("aniworld-detail-banner").style.backgroundImage = anime.banner_url ? `url("${coverUrl(anime.banner_url).replace(/"/g, "%22")}")` : "";
    byId("aniworld-detail-description").textContent = anime.description || "Keine Beschreibung verfügbar.";
    const rating = Number(anime.rating);
    byId("aniworld-detail-meta").innerHTML = [anime.status, anime.year, anime.country,
      anime.fsk ? `FSK ${anime.fsk}` : "", Number.isFinite(rating) && rating > 0 ? `★ ${rating.toLocaleString("de-DE")} / 5` : "",
      ...(anime.genres || []).slice(0, 6)].filter(Boolean).map((value) => `<span>${escapeHtml(value)}</span>`).join("");
    const alternatives = (anime.alternative_titles || []).slice(0, 6);
    byId("aniworld-detail-alternatives").textContent = alternatives.length ? `Auch bekannt als: ${alternatives.join(" · ")}` : "";
    const creditRows = [["Regie", anime.directors], ["Studio", anime.producers], ["Stimmen", (anime.cast || []).slice(0, 5)]].filter(([, values]) => values?.length);
    byId("aniworld-detail-credits").innerHTML = creditRows.map(([label, values]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(values.join(" · "))}</dd></div>`).join("");
    const options = byId("aniworld-track-options"); options.innerHTML = "";
    for (const [track, countValue] of Object.entries(anime.translations || {})) {
      const count = Number(countValue) || 0; if (!count) continue;
      const button = root.ownerDocument.createElement("button"); button.type = "button";
      button.className = `aniworld-track-option is-${track} ${track === data.translation ? "is-active" : ""}`;
      button.innerHTML = `<b>${escapeHtml(track.toUpperCase())}</b><span><strong>${escapeHtml(anime.translation_labels?.[track] || aniworldTrackLabel(track))}</strong><small>${count} Einträge verfügbar</small></span>`;
      callbacks.set(button, () => {
        if (track === data.translation) return;
        data.translation = track; data.episodePage = 1; data.selectedSeason = null;
        loadAniworldDetail();
      });
      options.appendChild(button);
    }
    renderAniworldSeasons(); renderAniworldEpisodes();
  }

  function renderAniworldSeasons() {
    const anime = data.current; const container = byId("aniworld-season-options"); container.innerHTML = "";
    for (const choice of anime?.seasons || []) {
      const button = root.ownerDocument.createElement("button"); button.type = "button";
      button.classList.toggle("is-active", choice.season === data.selectedSeason);
      button.innerHTML = `<strong>${escapeHtml(choice.label)}</strong><small>${Number(choice.count) || 0}</small>`;
      callbacks.set(button, () => {
        if (choice.season === data.selectedSeason) return;
        data.selectedSeason = choice.season;
        renderAniworldSeasons(); renderAniworldEpisodes();
      });
      container.appendChild(button);
    }
  }

  function aniworldVisibleEpisodes() {
    return (data.current?.episodes || []).filter((episode) => episode.season === data.selectedSeason);
  }

  function aniworldSelectableEpisodes() {
    return aniworldVisibleEpisodes().filter((episode) => !episode.downloaded && !episode.queued && !getQueuedSlugs().has(episode.slug));
  }

  function renderAniworldEpisodes() {
    const anime = data.current; const container = byId("aniworld-episode-grid"); container.innerHTML = "";
    const visible = aniworldVisibleEpisodes();
    if (!anime?.episodes?.length || !visible.length) container.innerHTML = '<div class="aniworld-empty is-compact"><strong>Keine Folgen verfügbar</strong><span>Wähle eine andere Staffel oder Sprachspur.</span></div>';
    for (const episode of visible) {
      const selected = data.picked.has(episode.slug); const queued = episode.queued || getQueuedSlugs().has(episode.slug);
      const button = root.ownerDocument.createElement("button"); button.type = "button";
      button.className = "aniworld-episode" + (selected ? " is-selected" : "") + (queued ? " is-queued" : "") + (episode.downloaded ? " is-downloaded" : "");
      const code = episode.kind === "movie" ? `FILM ${String(episode.number).padStart(2, "0")}` : `S${String(episode.season).padStart(2, "0")} · E${String(episode.number).padStart(2, "0")}`;
      const stateLabel = episode.downloaded ? "Geladen" : (queued ? "Queue" : (selected ? "Ausgewählt" : "Verfügbar"));
      const secondary = [episode.original_title && episode.original_title !== episode.title ? episode.original_title : "", ...(episode.hosters || []).slice(0, 3)].filter(Boolean).join(" · ");
      button.innerHTML = `<span class="aniworld-episode-code">${escapeHtml(code)}</span><span class="aniworld-episode-title"><strong>${escapeHtml(episode.title || episode.label)}</strong>${secondary ? `<small>${escapeHtml(secondary)}</small>` : ""}</span><span class="aniworld-episode-state">${escapeHtml(stateLabel)}</span>`;
      button.title = `${episode.label}${episode.title ? ` · ${episode.title}` : ""}`; button.disabled = queued || episode.downloaded;
      callbacks.set(button, () => { if (selected) data.picked.delete(episode.slug); else data.picked.add(episode.slug); renderAniworldEpisodes(); });
      container.appendChild(button);
    }
    const season = (anime?.seasons || []).find((item) => item.season === data.selectedSeason);
    byId("aniworld-current-season").textContent = season?.label || "Staffel";
    byId("aniworld-episode-count").textContent = `${visible.length} ${visible.length === 1 ? "Eintrag" : "Einträge"}`;
    byId("aniworld-pick-count").textContent = `${data.picked.size} ausgewählt`;
    byId("aniworld-select-all").disabled = !aniworldSelectableEpisodes().length;
    byId("aniworld-select-none").disabled = !data.picked.size;
    byId("aniworld-add-btn").disabled = !data.picked.size;
    byId("aniworld-add-btn").textContent = data.picked.size ? `${data.picked.size} Einträge herunterladen` : "Auswahl herunterladen";
    byId("aniworld-download-count").textContent = data.picked.size ? `${data.picked.size} ausgewählt` : "Keine Folgen ausgewählt";
  }

  function syncAniworldQueueFlags() {
    const anime = data.current; if (!anime?.episodes) return;
    for (const episode of anime.episodes) { episode.queued = getQueuedSlugs().has(episode.slug); if (episode.queued) data.picked.delete(episode.slug); }
    const modal = byId("aniworld-detail-modal"); if (modal && !modal.hidden) renderAniworldEpisodes();
  }

  function markAniworldSlugDownloaded(slug) {
    const anime = data.current; const episode = anime?.episodes?.find((item) => item.slug === slug); if (!episode) return;
    episode.downloaded = true; episode.queued = false; data.picked.delete(slug); if (detail?.active) renderAniworldEpisodes();
  }

  async function aniworldAddSelected() {
    if (!detail?.active || queuePending) return;
    const mounted = detail, selectedId = data.currentId;
    const slugs = [...data.picked]; if (!slugs.length) return;
    queuePending = true;
    byId("aniworld-add-btn").disabled = true;
    byId("aniworld-pick-count").textContent = "wird eingeplant …";
    try {
      const response = await client.post("/api/queue/add", { slugs, preferences: {}, source: "anime" }, { signal: session.signal });
      if (!session.active) return;
      refreshQueueUiAfterChange(response);
      if (!mounted.active || data.currentId !== selectedId) return;
      data.picked.clear();
      byId("aniworld-status").textContent = `${response.added}/${slugs.length} AniWorld-Einträge eingeplant`;
    } catch (error) { if (!mounted.active || data.currentId !== selectedId) return; byId("aniworld-status").textContent = `Download fehlgeschlagen: ${error.message}`; }
    finally { queuePending = false; if (mounted.active && data.currentId === selectedId) renderAniworldEpisodes(); }
  }
  return {
    get: () => data, mount, unmount, closeDetail,
    resume() { if (!session.active) session = createScope(); },
    dispose() { unmount(); closeDetail(); session.dispose(); },
    browse: aniworldBrowse, next: loadNextAniworldPage, open: openAniworldDetail,
    loadDetail: loadAniworldDetail, renderResults: renderAniworldResults, renderDetail: renderAniworldDetail,
    renderEpisodes: renderAniworldEpisodes, syncQueue: syncAniworldQueueFlags,
    markDownloaded: markAniworldSlugDownloaded, addSelected: aniworldAddSelected,
    visibleEpisodes: aniworldVisibleEpisodes, selectableEpisodes: aniworldSelectableEpisodes,
    updateInfinite: updateAniworldInfiniteState,
  };
}
