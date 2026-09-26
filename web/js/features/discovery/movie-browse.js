import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createMovieBrowse(root, {
  movieState, getActiveTab, syncSearchClearButtons, closeSearchSuggestions, rememberSearch, applyFpResults,
  setActiveGenreFilter, renderFpResults, updateFpInfiniteState, refreshMovieFeatureCandidates,
  syncFpCatalogFromHome, refreshFpCatalogInBackground, getGenres, applyFpSmartFilters,
  resetFpSmartFilters, setFilter, cancelMetadata, client = api,
}) {
  const byId = id => root.querySelector(`#${id}`);
  let scope = null, request = null, cancelRequest = null;
  const current = id => scope?.active && request?.scope.active
    && request.id === id && movieState.requestSeq === id;
  function load(params, id) {
    cancelRequest?.();
    cancelMetadata();
    const job = createScope();
    request = { id, scope: job };
    cancelRequest = scope.add(() => job.dispose());
    return client.get(`/api/movies?${new URLSearchParams(params)}`, {
      signal: job.signal, timeoutMs: params.mode === "search" ? 0 : 15_000,
      timeoutMessage: "Der Filmkatalog antwortet zu langsam. Die Anbieter laden im Hintergrund weiter.",
    });
  }
  function clearFpSearchContext() {
    movieState.searchActive = false;
    movieState.searchReturn = null;
    byId("fp-search").value = "";
    syncSearchClearButtons();
    closeSearchSuggestions("fp-search-suggestions", "fp-search");
  }

  function rememberFpSearchContext() {
    if (movieState.searchActive || movieState.searchReturn) return;
    if (!movieState.category && !movieState.results.length) return;
    movieState.searchReturn = {
      results: movieState.results.slice(),
      category: movieState.category,
      page: movieState.page,
      lastPageFull: movieState.lastPageFull,
      activeGenre: movieState.activeGenre,
      selectedSlug: movieState.selectedSlug,
      sources: movieState.sources.slice(),
    };
  }

  async function restoreFpSearchContext() {
    if (!scope?.active) return;
    if (!movieState.searchActive && !movieState.searchReturn) return;
    cancelRequest?.();
    const saved = movieState.searchReturn;
    movieState.searchActive = false;
    movieState.searchReturn = null;
    byId("fp-search").value = "";
    ++movieState.requestSeq;
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
    movieState.selectedSlug = saved.selectedSlug;
    renderFpResults();
  }

  async function fpSearch() {
    if (!scope?.active) return;
    const q = byId("fp-search").value.trim();
    if (!q) {
      await restoreFpSearchContext();
      return;
    }
    rememberSearch(q, "movie");
    closeSearchSuggestions("fp-search-suggestions", "fp-search");
    rememberFpSearchContext();
    movieState.searchActive = true;
    movieState.category = null;
    movieState.lastPageFull = false;
    movieState.loadingMore = false;
    movieState.loadError = "";
    updateFpInfiniteState();
    refreshMovieFeatureCandidates();
    byId("fp-status").textContent = `Suche nach «${q}» …`;
    setActiveGenreFilter("Alle Genres");
    const requestId = ++movieState.requestSeq;
    try {
      const data = await load({ mode: "search", query: q }, requestId);
      if (!current(requestId)) return;
      applyFpResults(data);
    } catch (error) {
      // Ohne diesen Zweig blieb der Status bei «Suche nach …» stehen: eine
      // abgelaufene Sitzung oder ein Providerfehler sah aus wie „kein Treffer“.
      if (!current(requestId)) return;
      movieState.loadingMore = false;
      movieState.loadError = error.message;
      updateFpInfiniteState();
      byId("fp-status").textContent = `Fehler: ${error.message}`;
    }
  }

  async function fpShowList(category) {
    if (!scope?.active) return;
    clearFpSearchContext();
    movieState.category = category;
    movieState.lastPageFull = false;
    movieState.loadingMore = true;
    movieState.loadError = "";
    updateFpInfiniteState();
    refreshMovieFeatureCandidates();
    setActiveGenreFilter("Alle Genres");
    byId("fp-status").textContent = `Lade ${category === "new" ? "Neu" : "Top"}-Filme …`;
    const requestId = ++movieState.requestSeq;
    try {
      const data = await load({ mode: category, page: 1 }, requestId);
      if (!current(requestId)) return;
      applyFpResults(data);
      movieState.previewFromHome = false;
      movieState.lastCatalogRefreshAt = Date.now();
    } catch (error) {
      if (!current(requestId)) return;
      movieState.loadingMore = false;
      movieState.loadError = error.message;
      updateFpInfiniteState();
      byId("fp-status").textContent = `Fehler: ${error.message}`;
    }
  }

  function ensureFpResults() {
    if (!scope?.active) return;
    syncFpCatalogFromHome();
    if (movieState.results.length) {
      if (!byId("fp-results").childElementCount) renderFpResults();
      refreshFpCatalogInBackground();
      return;
    }
    if (movieState.loadingMore) return;
    fpShowList("new");
  }

  async function fpGenreChange(genre) {
    if (!scope?.active) return;
    clearFpSearchContext();
    if (genre === "Alle Genres") {
      await fpShowList("new");
      return;
    }
    movieState.category = "genre";
    movieState.lastPageFull = false;
    movieState.loadingMore = true;
    movieState.loadError = "";
    updateFpInfiniteState();
    refreshMovieFeatureCandidates();
    setActiveGenreFilter(genre);
    byId("fp-status").textContent = `Lade Genre ${genre} …`;
    const requestId = ++movieState.requestSeq;
    try {
      const data = await load({ mode: "genre", genre, page: 1 }, requestId);
      if (!current(requestId)) return;
      applyFpResults(data);
    } catch (error) {
      if (!current(requestId)) return;
      movieState.loadingMore = false;
      movieState.loadError = error.message;
      updateFpInfiniteState();
      byId("fp-status").textContent = `Fehler: ${error.message}`;
    }
  }

  async function loadNextFpPage() {
    if (!scope?.active) return;
    if (
      getActiveTab() !== "filme"
      || !movieState.category
      || movieState.searchActive
      || movieState.loadingMore
      || !movieState.lastPageFull
    ) return;
    const newPage = movieState.page + 1;
    const params = movieState.category === "genre"
      ? { mode: "genre", genre: movieState.activeGenre, page: newPage }
      : { mode: movieState.category, page: newPage };
    const requestId = ++movieState.requestSeq;
    movieState.loadingMore = true;
    movieState.loadError = "";
    updateFpInfiniteState();
    try {
      const data = await load(params, requestId);
      if (!current(requestId)) return;
      // Inhalte zuerst stabil anhaengen. Poster und TMDB-Daten laden danach
      // parallel pro Karte; die langsamste Bildantwort sperrt nicht mehr die
      // komplette 32er-Seite.
      applyFpResults(data, { append: true });
    } catch (error) {
      if (!current(requestId)) return;
      movieState.loadError = error.message;
      byId("fp-status").textContent = `Nachladen fehlgeschlagen: ${error.message}`;
    } finally {
      if (current(requestId)) {
        movieState.loadingMore = false;
        updateFpInfiniteState();
      }
    }
  }

  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      // Filme
      scope.listen(byId("fp-search-btn"), "click", fpSearch);
      scope.listen(byId("fp-search-clear"), "click", async () => {
        byId("fp-search").value = "";
        syncSearchClearButtons();
        closeSearchSuggestions("fp-search-suggestions", "fp-search");
        await restoreFpSearchContext();
      });
      scope.listen(byId("fp-search"), "input", () => {
        syncSearchClearButtons();
        closeSearchSuggestions("fp-search-suggestions", "fp-search");
      });
      scope.listen(byId("fp-search"), "keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          fpSearch();
        } else if (event.key === "Escape") {
          event.stopPropagation();
          closeSearchSuggestions("fp-search-suggestions", "fp-search");
        }
      });
      scope.listen(byId("fp-search"), "blur", (event) => {
        if (!event.currentTarget.value.trim()) restoreFpSearchContext();
      });
      scope.listen(byId("fp-new-btn"), "click", () => fpShowList("new"));
      scope.listen(byId("fp-top-btn"), "click", () => fpShowList("top"));
      scope.listen(byId("movie-filter-genre"), "change", (event) => {
        fpGenreChange(event.currentTarget.value);
      });
      for (const id of ["period", "rating", "availability", "language", "sort"]) {
        scope.listen(byId(`movie-filter-${id}`), "change", (event) => {
          setFilter(id, event.currentTarget.value);
          applyFpSmartFilters();
        });
      }
      scope.listen(byId("movie-filter-reset"), "click", resetFpSmartFilters);
      scope.listen(byId("genre-random"), "click", () => {
        const genres = getGenres()
          .filter((genre) => genre !== "Alle Genres" && genre !== movieState.activeGenre);
        if (!genres.length) return;
        fpGenreChange(genres[Math.floor(Math.random() * genres.length)]);
      });
    },
    unmount() {
      scope?.dispose(); scope = null; request = null; cancelRequest = null;
      movieState.loadingMore = false;
    },
    clear: clearFpSearchContext, remember: rememberFpSearchContext, restore: restoreFpSearchContext,
    search: fpSearch, list: fpShowList, ensure: ensureFpResults, genre: fpGenreChange, next: loadNextFpPage,
  };
}
