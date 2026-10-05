import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { escapeHtml } from "../../shared/utils/escape-html.js";
import {
  announceBrowserDownloadStart,
  prepareBrowserDownloads,
  triggerBrowserDownloads,
} from "../downloads/browser.js";

export function createAnime(root, modal, {
  getQueuedSlugs, coverUrl, mediaCardInitials, mediaJellyfinStatus, jellyfinStatusText,
  refreshCatalogJellyfinStatus, homeAnimeEntry, openMediaModal, trackDiscoveryPreference,
  refreshQueueUiAfterChange, client = api,
}) {
  const data = {
    results: [], mode: null, query: "", page: 1, hasMore: false,
    loaded: false, loading: false, requestSeq: 0, detailSeq: 0,
    currentId: "", current: null, translation: "", episodePage: 1,
    picked: new Set(), searchReturn: null, disabledReason: "",
  };
  const byId = id => root.querySelector(`#${id}`) || (modal.id === id ? modal : modal.querySelector(`#${id}`));
  const callbacks = new WeakMap();
  let session = createScope(), view = null, detail = null;
  let cancelBrowse = null, cancelDetail = null, queuePending = false;
  function dispatch(event) {
    for (let node = event.target; node; node = node.parentElement) {
      const callback = callbacks.get(node);
      if (callback) { callback(event); return; }
      if (node === root || node === modal) return;
    }
  }
  function closeDetail() { detail?.dispose(); detail = null; cancelDetail = null; }
  function mountDetail() {
    closeDetail();
    detail = createScope();
    detail.listen(modal, "click", dispatch);
    detail.listen(byId("anime-select-page"), "click", () => {
      for (const episode of data.current?.episodes || []) {
        if (episode.slug) data.picked.add(episode.slug);
      }
      renderAnimeEpisodes();
    });
    detail.listen(byId("anime-select-none"), "click", () => {
      data.picked.clear();
      renderAnimeEpisodes();
    });
    detail.listen(byId("anime-episode-prev"), "click", () => {
      if (!data.current || data.current.page <= 1) return;
      data.episodePage = data.current.page - 1;
      loadAnimeDetail({ keepSelection: true });
    });
    detail.listen(byId("anime-episode-next"), "click", () => {
      if (!data.current || data.current.page >= data.current.page_count) return;
      data.episodePage = data.current.page + 1;
      loadAnimeDetail({ keepSelection: true });
    });
    detail.listen(byId("anime-add-btn"), "click", animeAddSelected);
  }
  function mount() {
    if (view?.active || !session.active) return;
    view = createScope();
    view.listen(root, "click", dispatch);
    view.listen(byId("anime-search-btn"), "click", () => animeBrowse("search", 1));
    view.listen(byId("anime-search"), "keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      animeBrowse("search", 1);
    });
    view.listen(byId("anime-search"), "blur", (event) => {
      if (!event.currentTarget.value.trim()) restoreAnimeSearchContext();
    });
    view.listen(byId("anime-latest-btn"), "click", () => animeBrowse("latest", 1));
    view.listen(byId("anime-trending-btn"), "click", () => animeBrowse("trending", 1));
    view.listen(byId("anime-popular-btn"), "click", () => animeBrowse("popular", 1));
    view.listen(byId("anime-prev"), "click", () => {
      animeBrowse(data.mode || "latest", Math.max(1, data.page - 1));
    });
    view.listen(byId("anime-next"), "click", () => {
      animeBrowse(data.mode || "latest", data.page + 1);
    });
  }
  function unmount() { view?.dispose(); view = null; cancelBrowse = null; data.loading = false; }
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
      byId(id).classList.toggle("is-active", mode === value);
    }
    byId("anime-catalog-title").textContent = animeModeTitle(mode);
  }

  function renderAnimeFeature() {
    const feature = byId("anime-featured");
    const anime = data.results[0];
    if (!anime) {
      feature.hidden = true;
      callbacks.delete(feature);
      return;
    }
    const artwork = anime.banner_url || anime.cover_url || "";
    byId("anime-featured-art").style.backgroundImage =
      artwork ? `url("${artwork.replace(/"/g, "%22")}")` : "";
    byId("anime-featured-title").textContent = anime.title;
    const tracks = [
      anime.translations?.dub ? "DUB" : "",
      anime.translations?.sub ? "SUB" : "",
    ].filter(Boolean).join(" + ");
    byId("anime-featured-meta").textContent = [
      anime.year,
      anime.media_type || "Anime",
      tracks,
      jellyfinStatusText(mediaJellyfinStatus(anime)),
    ].filter(Boolean).join(" · ");
    feature.setAttribute("aria-label", `${anime.title} öffnen`);
    callbacks.set(feature, () => openAnimeDetail(anime, feature));
    feature.hidden = false;
  }

  function renderAnimeResults() {
    const container = byId("anime-results");
    container.innerHTML = "";
    for (const anime of data.results) {
      const card = root.ownerDocument.createElement("button");
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
      ? `<img src="${escapeHtml(coverUrl(anime.cover_url))}" alt="" loading="lazy">`
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
      callbacks.set(card, () => openAnimeDetail(anime, card));
      container.appendChild(card);
    }
    if (!data.results.length) {
      const empty = root.ownerDocument.createElement("div");
      empty.className = "anime-empty";
      empty.textContent = data.disabledReason
        || (data.mode === "search"
          ? "Kein Anime passt zu dieser Suche."
          : "MKissa meldet momentan keine Anime.");
      container.appendChild(empty);
    }
    renderAnimeFeature();
    byId("anime-page-label").textContent =
      `Seite ${data.page} · ${data.results.length} Titel`;
    byId("anime-prev").disabled = data.loading || data.page <= 1;
    byId("anime-next").disabled = data.loading || !data.hasMore;
  }

  function clearAnimeSearchContext() {
    data.searchReturn = null;
    data.query = "";
    byId("anime-search").value = "";
  }

  function rememberAnimeSearchContext() {
    if (data.searchReturn || data.mode === "search") return;
    if (!data.loaded && !data.results.length) return;
    data.searchReturn = {
      results: data.results.slice(),
      mode: data.mode || "latest",
      query: data.query,
      page: data.page,
      hasMore: data.hasMore,
      disabledReason: data.disabledReason || "",
      status: byId("anime-status").textContent,
    };
  }

  async function restoreAnimeSearchContext() {
    if (!view?.active) return;
    cancelBrowse?.();
    if (data.mode !== "search" && !data.searchReturn) return;
    const saved = data.searchReturn;
    data.searchReturn = null;
    byId("anime-search").value = "";
    ++data.requestSeq;
    data.loading = false;
    if (!saved) {
      await animeBrowse("latest", 1);
      return;
    }
    data.results = saved.results;
    data.mode = saved.mode;
    data.query = saved.query;
    data.page = saved.page;
    data.hasMore = saved.hasMore;
    data.disabledReason = saved.disabledReason;
    setAnimeMode(saved.mode);
    renderAnimeResults();
    byId("anime-status").textContent = saved.status;
  }

  async function animeBrowse(mode, page = 1) {
    if (!view?.active) return;
    const mounted = view;
    const query = mode === "search"
      ? byId("anime-search").value.trim()
      : "";
    if (mode === "search" && !query) {
      await restoreAnimeSearchContext();
      return;
    }
    cancelBrowse?.();
    const request = createScope();
    cancelBrowse = view.add(() => request.dispose());
    if (mode === "search") rememberAnimeSearchContext();
    else clearAnimeSearchContext();
    data.loading = true;
    const requestSeq = ++data.requestSeq;
    setAnimeMode(mode);
    byId("anime-status").textContent =
      mode === "search" ? `Suche nach «${query}» …` : `${animeModeTitle(mode)} werden geladen …`;
    renderAnimeResults();
    try {
      const response = await client.get(`/api/anime?${new URLSearchParams({ mode, query, page })}`, { signal: request.signal });
      if (!mounted.active || !request.active || requestSeq !== data.requestSeq) return;
      data.results = response.results || [];
      data.mode = mode;
      data.query = query;
      data.page = Number(response.page) || page;
      data.hasMore = !!response.has_more;
      data.loaded = true;
      data.disabledReason = response.disabled ? response.disabled_reason : "";
      const total = Number(response.total) || data.results.length;
      byId("anime-status").textContent = response.disabled
        ? response.disabled_reason
        : `${data.results.length} Titel auf dieser Seite · ${total.toLocaleString("de-DE")} im Katalog`;
    } catch (error) {
      if (!mounted.active || !request.active || requestSeq !== data.requestSeq) return;
      data.results = [];
      data.hasMore = false;
      data.loaded = true;
      data.disabledReason = error.message;
      byId("anime-status").textContent = `Fehler: ${error.message}`;
    } finally {
      if (mounted.active && request.active && requestSeq === data.requestSeq) {
        data.loading = false;
        renderAnimeResults();
        void refreshCatalogJellyfinStatus(
          data.results.map(homeAnimeEntry),
          () => {
            if (mounted.active && request.active && requestSeq === data.requestSeq) renderAnimeResults();
          },
          { signal: mounted.signal },
        );
      }
    }
  }

  async function openAnimeDetail(anime, returnFocus = null) {
    if (!session.active) return;
    mountDetail();
    data.currentId = anime.id;
    data.current = { ...anime, episodes: [] };
    data.translation = anime.translations?.dub
      ? "dub"
      : (anime.translations?.sub ? "sub" : Object.keys(anime.translations || {})[0] || "");
    data.episodePage = 1;
    data.picked.clear();
    openMediaModal("anime-detail-modal", returnFocus);
    byId("anime-detail-title").textContent = anime.title;
    byId("anime-detail-description").textContent = "Episoden und Sprachspuren werden geladen …";
    byId("anime-track-options").replaceChildren();
    renderAnimeEpisodes();
    trackDiscoveryPreference("anime", { ...anime, base_slug: anime.id }, 0.8, "open");
    await loadAnimeDetail();
  }

  async function loadAnimeDetail({ keepSelection = false } = {}) {
    if (!detail?.active) return;
    cancelDetail?.();
    const request = createScope();
    cancelDetail = detail.add(() => request.dispose());
    const animeId = data.currentId;
    if (!animeId) return;
    const detailSeq = ++data.detailSeq;
    if (!keepSelection) data.picked.clear();
    byId("anime-pick-count").textContent = "wird geladen";
    byId("anime-add-btn").disabled = true;
    for (const id of ["anime-episode-prev", "anime-episode-next", "anime-select-page", "anime-select-none"]) byId(id).disabled = true;
    try {
      const detail = await client.get(`/api/anime/${encodeURIComponent(animeId)}?${new URLSearchParams({
        translation: data.translation, episode_page: String(data.episodePage),
      })}`, { signal: request.signal });
      if (!request.active || detailSeq !== data.detailSeq || animeId !== data.currentId) return;
      data.current = {
        ...detail,
        jellyfin_status: data.current?.jellyfin_status || "checking",
        in_jellyfin: data.current?.in_jellyfin,
      };
      data.translation = detail.translation;
      data.episodePage = detail.page;
      syncAnimeQueueFlags();
      renderAnimeDetail();
    } catch (error) {
      if (!request.active || detailSeq !== data.detailSeq) return;
      byId("anime-detail-description").textContent = error.message;
      byId("anime-pick-count").textContent = "nicht verfügbar";
    }
  }

  function renderAnimeDetail() {
    const anime = data.current;
    if (!anime) return;
    byId("anime-detail-title").textContent = anime.title;
    const cover = byId("anime-detail-cover");
    cover.src = coverUrl(anime.cover_url || "");
    cover.alt = anime.title;
    byId("anime-detail-type").textContent = anime.media_type || "TV";
    const banner = byId("anime-detail-banner");
    banner.style.backgroundImage = anime.banner_url
      ? `url("${coverUrl(anime.banner_url).replace(/"/g, "%22")}")`
      : "";
    byId("anime-detail-description").textContent =
      anime.description || "Keine Beschreibung verfügbar.";
    const meta = [
      anime.year,
      anime.rating ? `★ ${Number(anime.rating).toFixed(1)}` : "",
      ...(anime.genres || []).slice(0, 4),
      jellyfinStatusText(mediaJellyfinStatus(anime)),
    ].filter(Boolean);
    byId("anime-detail-meta").innerHTML =
      meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("");

    const trackOptions = byId("anime-track-options");
    trackOptions.innerHTML = "";
    for (const [track, countValue] of Object.entries(anime.translations || {})) {
      const count = Number(countValue) || 0;
      if (!count) continue;
      const button = root.ownerDocument.createElement("button");
      button.type = "button";
      button.className = `anime-track-option ${track === data.translation ? "is-active" : ""}`;
      button.dataset.track = track;
      button.innerHTML = `
        <strong translate="no">${escapeHtml(track.toUpperCase())}</strong>
        <small translate="no">${escapeHtml(anime.translation_labels?.[track] || track)} · ${count} EP</small>
      `;
      callbacks.set(button, () => {
        if (track === data.translation) return;
        data.translation = track;
        data.episodePage = 1;
        loadAnimeDetail();
      });
      trackOptions.appendChild(button);
    }
    renderAnimeEpisodes();
  }

  function renderAnimeEpisodes() {
    const anime = data.current;
    const container = byId("anime-episode-grid");
    container.innerHTML = "";
    if (!anime?.episodes?.length) {
      container.innerHTML = '<div class="anime-empty">Keine Episoden in dieser Sprachspur.</div>';
      return;
    }
    for (const episode of anime.episodes) {
      const selected = data.picked.has(episode.slug);
      const queued = episode.queued || getQueuedSlugs().has(episode.slug);
      const button = root.ownerDocument.createElement("button");
      button.type = "button";
      button.className = "anime-episode"
        + (selected ? " is-selected" : "")
        + (queued ? " is-queued" : "")
        + (episode.downloaded ? " is-downloaded" : "");
      button.textContent = episode.number;
      button.title = episode.downloaded
        ? `${episode.label} · auf dem Server bereits geladen · Browser-Download möglich`
        : queued
          ? `${episode.label} · serverseitig in der Warteschlange · Browser-Download möglich`
          : `${episode.label} · im Browser herunterladen`;
      button.disabled = false;
      callbacks.set(button, () => {
        if (data.picked.has(episode.slug)) data.picked.delete(episode.slug);
        else data.picked.add(episode.slug);
        renderAnimeEpisodes();
      });
      container.appendChild(button);
    }
    const first = anime.episodes[0]?.number || 0;
    const last = anime.episodes.at(-1)?.number || 0;
    byId("anime-episode-page-label").textContent =
      `Episoden ${first}–${last} · Seite ${anime.page}/${anime.page_count}`;
    byId("anime-episode-prev").disabled = anime.page <= 1;
    byId("anime-episode-next").disabled = anime.page >= anime.page_count;
    byId("anime-pick-count").textContent = `${data.picked.size} ausgewählt`;
    byId("anime-select-page").disabled = false;
    byId("anime-select-none").disabled = !data.picked.size;
    byId("anime-add-btn").disabled = !data.picked.size;
  }

  function syncAnimeQueueFlags() {
    const anime = data.current;
    if (!anime?.episodes) return;
    for (const episode of anime.episodes) {
      episode.queued = getQueuedSlugs().has(episode.slug);
    }
    if (!byId("anime-detail-modal").hidden) renderAnimeEpisodes();
  }

  function markAnimeSlugDownloaded(slug) {
    const anime = data.current;
    const episode = anime?.episodes?.find((item) => item.slug === slug);
    if (!episode) return;
    episode.downloaded = true;
    episode.queued = false;
    if (detail?.active) renderAnimeEpisodes();
  }

  async function animeAddSelected() {
    if (!detail?.active || queuePending) return;
    const mounted = detail;
    const selectedId = data.currentId;
    const slugs = [...data.picked];
    if (!slugs.length) return;
    queuePending = true;
    const button = byId("anime-add-btn");
    button.disabled = true;
    byId("anime-pick-count").textContent = "Browser-Downloads werden vorbereitet …";
    try {
      const response = await prepareBrowserDownloads(
        client,
        slugs,
        {},
        { signal: session.signal },
      );
      if (!session.active) return;
      const started = triggerBrowserDownloads(response.downloads, root.ownerDocument);
      if (!started) throw new Error("RDM hat keine Browser-Downloads erzeugt.");
      if (data.current) {
        trackDiscoveryPreference(
          "anime",
          { ...data.current, base_slug: data.current.id },
          5,
          "download",
        );
      }
      announceBrowserDownloadStart({ quota: response.quota, slugs });
      if (!mounted.active || data.currentId !== selectedId) return;
      data.picked.clear();
      byId("anime-status").textContent = started > 1
        ? `${started} Browser-Downloads gestartet · dein Browser kann nach Erlaubnis für mehrere Dateien fragen.`
        : "Browser-Download gestartet.";
    } catch (error) {
      if (!mounted.active || data.currentId !== selectedId) return;
      byId("anime-status").textContent = `Download fehlgeschlagen: ${error.message}`;
    } finally {
      queuePending = false;
      if (mounted.active && data.currentId === selectedId) renderAnimeEpisodes();
    }
  }

  return {
    get: () => data, mount, unmount, closeDetail,
    invalidate() { cancelBrowse?.(); data.requestSeq++; data.loading = false; data.loaded = false; data.disabledReason = ""; },
    resume() { if (!session.active) session = createScope(); },
    dispose() { unmount(); closeDetail(); session.dispose(); },
    browse: animeBrowse, restore: restoreAnimeSearchContext, open: openAnimeDetail,
    loadDetail: loadAnimeDetail, renderResults: renderAnimeResults, renderDetail: renderAnimeDetail,
    renderEpisodes: renderAnimeEpisodes, syncQueue: syncAnimeQueueFlags,
    markDownloaded: markAnimeSlugDownloaded, addSelected: animeAddSelected,
  };
}
