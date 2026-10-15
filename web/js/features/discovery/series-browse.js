import { api } from "../../core/api.js";
import { createScope, delay } from "../../core/lifecycle.js";

export function createSeriesBrowse(root, {
  seriesState, getActiveTab, syncSearchClearButtons, closeSearchSuggestions, rememberSearch, applySeriesResults,
  renderSeriesTiles, updateSeriesInfiniteState, showSeriesDetail, firstEpisodeSlug,
  updateSeriesStatus, refreshSeriesJellyfinStatus, recheckSeriesInfinite, preloadSeriesPosterImages,
  syncSeriesCatalogFromHome, renderSeriesResults, refreshSeriesCatalogInBackground, client = api,
  waitForRetry = delay, scheduleRecheck = null,
}) {
  const byId = id => root.querySelector(`#${id}`);
  let scope = null, request = null, cancelRequest = null;
  let nextPage = null;
  const current = id => scope?.active && request?.scope.active
    && request.id === id && seriesState.browseRequestSeq === id;
  const transientCatalogError = error => error?.code === "series_catalog_pending"
    || [409, 429, 502, 503, 504, 520, 521, 522, 524].includes(Number(error?.status))
    || ["network_error", "request_timeout"].includes(error?.code);
  function scheduleInfiniteRecheck(next = recheckSeriesInfinite) {
    const owner = scope;
    const callback = () => {
      if (!owner?.active || getActiveTab() !== "serien"
          || seriesState.loadingBrowse || seriesState.loadError) return;
      next();
    };
    if (typeof scheduleRecheck === "function") {
      scheduleRecheck(callback);
      return;
    }
    owner?.timeout(callback, 1500);
  }
  async function load(params, id, retryTransient = false) {
    cancelRequest?.();
    const job = createScope();
    request = { id, scope: job };
    cancelRequest = scope.add(() => job.dispose());
    const url = `/api/series?${new URLSearchParams(params)}`;
    const deadline = Date.now() + 30_000;
    for (let attempt = 0; ; attempt++) {
      try {
        return await client.get(url, { signal: job.signal, timeoutMs: Math.max(1, deadline - Date.now()) });
      } catch (error) {
        const transient = transientCatalogError(error);
        const backoff = 700 * (attempt + 1);
        if (!retryTransient || !transient || attempt >= 2 || !current(id)
            || Date.now() + backoff >= deadline) throw error;
        await waitForRetry(backoff, job.signal);
        if (!current(id)) throw new DOMException("Anfrage abgebrochen", "AbortError");
      }
    }
  }
  function buildAlphaBar() {
    const bar = byId("series-alpha-bar");
    bar.replaceChildren();
    const letters = ["0-9", ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))];
    for (const l of letters) {
      const btn = root.ownerDocument.createElement("button");
      btn.textContent = l;
      scope.listen(btn, "click", () => seriesBrowse(`alpha:${l}`, 1));
      bar.appendChild(btn);
    }
  }

  function clearSeriesSearchContext() {
    seriesState.searchReturn = null;
    byId("series-search").value = "";
    syncSearchClearButtons();
    closeSearchSuggestions("series-search-suggestions", "series-search");
  }

  function rememberSeriesSearchContext() {
    if (seriesState.searchReturn || seriesState.browseMode === "search") return;
    if (!seriesState.browseMode && !seriesState.results.length) return;
    seriesState.searchReturn = {
      results: seriesState.results.slice(),
      browseMode: seriesState.browseMode,
      page: seriesState.page,
      lastPageFull: seriesState.lastPageFull,
      sources: seriesState.sources.slice(),
      current: seriesState.current,
      currentSampleSlug: seriesState.currentSampleSlug,
      epPicked: new Set(seriesState.epPicked),
    };
  }

  async function restoreSeriesSearchContext() {
    if (!scope?.active) return;
    if (seriesState.browseMode !== "search" && !seriesState.searchReturn) return;
    cancelRequest?.();
    nextPage = null;
    const saved = seriesState.searchReturn;
    seriesState.searchReturn = null;
    byId("series-search").value = "";
    ++seriesState.browseRequestSeq;
    seriesState.loadingBrowse = false;
    if (!saved) {
      await seriesBrowse("discover", 1);
      return;
    }
    seriesState.browseMode = saved.browseMode;
    seriesState.current = saved.current;
    seriesState.currentSampleSlug = saved.currentSampleSlug;
    seriesState.epPicked = new Set(saved.epPicked);
    applySeriesResults({
      results: saved.results,
      page: saved.page,
      has_more: saved.lastPageFull,
      sources: saved.sources,
    });
    renderSeriesTiles();
    void prepareNextSeriesPage();
  }

  async function seriesSearch() {
    if (!scope?.active) return;
    const q = byId("series-search").value.trim();
    if (!q) {
      await restoreSeriesSearchContext();
      return;
    }
    rememberSearch(q, "series");
    closeSearchSuggestions("series-search-suggestions", "series-search");
    rememberSeriesSearchContext();
    nextPage = null;
    const requestId = ++seriesState.browseRequestSeq;
    const previousMode = seriesState.browseMode;
    seriesState.browseMode = "search";
    seriesState.loadingBrowse = true;
    seriesState.loadError = "";
    updateSeriesInfiniteState();
    byId("series-status").textContent = `Suche nach «${q}» …`;
    try {
      const data = await load({ mode: "search", query: q }, requestId);
      if (!current(requestId)) return;
      applySeriesResults(data);
      if (data.direct_series) {
        showSeriesDetail(data.direct_series, firstEpisodeSlug(data.direct_series));
        updateSeriesStatus(data.direct_series);
        refreshSeriesJellyfinStatus();
      }
    } catch (error) {
      if (!current(requestId)) return;
      seriesState.browseMode = seriesState.results.length ? previousMode : null;
      updateSeriesInfiniteState();
      byId("series-status").textContent = `Fehler: ${error.message}`;
    } finally {
      if (current(requestId)) {
        seriesState.loadingBrowse = false;
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

  function prepareNextSeriesPage() {
    const mode = seriesState.browseMode;
    if (!scope?.active || getActiveTab() !== "serien" || seriesState.loadingBrowse
        || !mode || mode === "search" || !seriesState.lastPageFull) return;
    const id = seriesState.browseRequestSeq;
    const page = seriesState.page + 1;
    if (nextPage?.id === id && nextPage.mode === mode && nextPage.page === page) return nextPage.promise;
    const pending = { id, mode, page, data: null, error: null };
    nextPage = pending;
    const valid = () => nextPage === pending && current(id)
      && seriesState.browseMode === mode && seriesState.page + 1 === page;
    pending.promise = load(seriesParams(mode, page), id, true)
      .then(async data => {
        if (!valid()) return;
        await preloadSeriesPosterImages(data.results || [], 2000, scope.signal);
        if (valid()) pending.data = data;
      })
      .catch(error => {
        if (!valid()) return;
        if (transientCatalogError(error)) {
          scheduleInfiniteRecheck(() => {
            if (!valid()) return;
            nextPage = null;
            void prepareNextSeriesPage();
          });
        } else pending.error = error;
      });
    return pending.promise;
  }

  async function seriesBrowse(mode, page, { append = false } = {}) {
    if (!scope?.active) return;
    nextPage = null;
    if (mode !== "search") clearSeriesSearchContext();
    const requestId = ++seriesState.browseRequestSeq;
    const previousMode = seriesState.browseMode;
    const previousLastPageFull = seriesState.lastPageFull;
    seriesState.browseMode = mode;
    seriesState.loadingBrowse = true;
    seriesState.loadError = "";
    if (!append) seriesState.lastPageFull = false;
    updateSeriesInfiniteState();
    const modeLabels = { discover: "interessante Serien", new: "neue Serien", trending: "angesagte Serien" };
    if (!append) {
      byId("series-status").textContent = `Lade ${modeLabels[mode] || "Serien"} …`;
    }
    let recheckAfterSettle = false;
    let retryInitialPage = false;
    try {
      const data = await load(seriesParams(mode, page), requestId, true);
      if (!current(requestId)) return false;
      // Serienkarten sofort stabil anhaengen; Poster, TMDB und Jellyfin werden
      // parallel pro Karte ergaenzt statt die ganze Folgeseite zu sperren.
      applySeriesResults(data, { append });
      if (append) void preloadSeriesPosterImages(data.results || [], 2000, scope.signal);
      if (!append) seriesState.previewFromHome = false;
      if (!append && page === 1) seriesState.lastCatalogRefreshAt = Date.now();
      recheckAfterSettle = true;
      return true;
    } catch (error) {
      if (!current(requestId)) return false;
      byId("series-status").textContent = append
        ? `Nachladen fehlgeschlagen: ${error.message}`
        : `Fehler: ${error.message}`;
      if (transientCatalogError(error)) {
        // A cold provider page is not a permanent pagination failure. Keep the
        // sentinel armed and try again once the in-flight provider futures had
        // time to populate the cache. A persistent loadError would otherwise
        // disable infinite scrolling until some unrelated refresh clears it.
        seriesState.loadError = "";
        byId("series-status").textContent = "Weitere Serien werden vorbereitet …";
        recheckAfterSettle = true;
        retryInitialPage = !append;
      } else if (append) {
        seriesState.loadError = error.message;
      } else {
        seriesState.loadError = "";
        seriesState.browseMode = seriesState.results.length ? previousMode : null;
        seriesState.lastPageFull = previousLastPageFull;
      }
      return false;
    } finally {
      if (current(requestId)) {
        seriesState.loadingBrowse = false;
        updateSeriesInfiniteState();
        if (retryInitialPage) {
          scheduleInfiniteRecheck(() => {
            if (current(requestId)) void seriesBrowse(mode, page);
          });
        } else if (recheckAfterSettle) void prepareNextSeriesPage();
      }
    }
  }

  function ensureSeriesResults() {
    if (!scope?.active) return;
    syncSeriesCatalogFromHome();
    if (seriesState.results.length) {
      if (!byId("series-results").childElementCount) renderSeriesResults();
      refreshSeriesCatalogInBackground();
      void prepareNextSeriesPage();
      return;
    }
    if (seriesState.loadingBrowse) return;
    seriesBrowse("discover", 1);
  }

  async function loadNextSeriesPage({ retry = false, reveal = false } = {}) {
    if (!scope?.active) return;
    const mode = seriesState.browseMode;
    if (
      getActiveTab() !== "serien"
      || !mode
      || mode === "search"
      || seriesState.loadingBrowse
      || (seriesState.loadError && !retry)
      || !seriesState.lastPageFull
    ) return;
    if (retry) {
      if (nextPage?.error) nextPage = null;
      seriesState.loadError = "";
      updateSeriesInfiniteState();
    }
    if ((reveal || retry) && nextPage?.data) {
      const data = nextPage.data;
      nextPage = null;
      ++seriesState.browseRequestSeq;
      applySeriesResults(data, { append: true });
      void prepareNextSeriesPage();
      return;
    }
    if ((reveal || retry) && nextPage?.error) {
      seriesState.loadError = nextPage.error.message;
      updateSeriesInfiniteState();
      return;
    }
    // Completion only fills this buffer. A later downward scroll reveals it.
    await prepareNextSeriesPage();
  }

  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      buildAlphaBar();
      // Serien
      scope.listen(byId("series-search-btn"), "click", seriesSearch);
      scope.listen(byId("series-search-clear"), "click", async () => {
        byId("series-search").value = "";
        syncSearchClearButtons();
        closeSearchSuggestions("series-search-suggestions", "series-search");
        await restoreSeriesSearchContext();
      });
      scope.listen(byId("series-search"), "input", () => {
        syncSearchClearButtons();
        closeSearchSuggestions("series-search-suggestions", "series-search");
      });
      scope.listen(byId("series-search"), "keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          seriesSearch();
        } else if (event.key === "Escape") {
          event.stopPropagation();
          closeSearchSuggestions("series-search-suggestions", "series-search");
        }
      });
      scope.listen(byId("series-search"), "blur", (event) => {
        if (!event.currentTarget.value.trim()) restoreSeriesSearchContext();
      });
      scope.listen(byId("series-discover-btn"), "click", () => seriesBrowse("discover", 1));
      scope.listen(byId("series-new-btn"), "click", () => seriesBrowse("new", 1));
      scope.listen(byId("series-trending-btn"), "click", () => seriesBrowse("trending", 1));
      scope.listen(byId("series-az-btn"), "click", () => {
        byId("series-alpha-bar").classList.toggle("hidden");
      });
    },
    unmount() {
      scope?.dispose(); scope = null; request = null; cancelRequest = null;
      nextPage = null;
      seriesState.loadingBrowse = false;
    },
    clear: clearSeriesSearchContext, remember: rememberSeriesSearchContext, restore: restoreSeriesSearchContext,
    search: seriesSearch, browse: seriesBrowse, ensure: ensureSeriesResults, next: loadNextSeriesPage,
  };
}
