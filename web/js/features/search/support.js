/** Per-user recent queries and presentation helpers shared by catalog search inputs. */
export function createSearchSupport(root, { personalStorageKey, getGenres, recordTasteEvent, storage }) {
  const SEARCH_HISTORY_KEY = "royal-search-history-v1";
  function searchHistory() {
    try {
      const value = JSON.parse((storage || root.defaultView.localStorage).getItem(personalStorageKey(SEARCH_HISTORY_KEY)) || "[]");
      return Array.isArray(value) ? value.filter((entry) => entry?.query).slice(0, 6) : [];
    } catch {
      return [];
    }
  }

  function rememberSearch(query, kind) {
    const normalized = query.trim();
    if (!normalized) return;
    const next = [
      { query: normalized, kind },
      ...searchHistory().filter((entry) => entry.query.toLocaleLowerCase() !== normalized.toLocaleLowerCase()),
    ].slice(0, 6);
    try {
      (storage || root.defaultView.localStorage).setItem(personalStorageKey(SEARCH_HISTORY_KEY), JSON.stringify(next));
    } catch {
      // Private Modi können lokalen Speicher blockieren; die Suche bleibt nutzbar.
    }
    const matchingGenre = getGenres()
      .map((genre) => String(genre || ""))
      .find((genre) => genre && genre !== "Alle Genres"
        && genre.localeCompare(normalized, "de", { sensitivity: "base" }) === 0);
    void recordTasteEvent({
      action: "search", source: "web", media_type: kind, query: normalized,
      metadata: matchingGenre ? { genres: [matchingGenre] } : {},
    });
  }

  function closeSearchSuggestions(panelId, inputId) {
    const panel = root.getElementById(panelId);
    const input = root.getElementById(inputId);
    if (panel) panel.hidden = true;
    if (input) input.setAttribute("aria-expanded", "false");
  }

  function syncSearchClearButtons() {
    [
      ["home-search", "home-search-clear"],
      ["fp-search", "fp-search-clear"],
      ["series-search", "series-search-clear"],
    ].forEach(([inputId, clearId]) => {
      const input = root.getElementById(inputId);
      const clear = root.getElementById(clearId);
      if (input && clear) clear.hidden = !input.value;
    });
  }

  return { history: searchHistory, remember: rememberSearch, closeSuggestions: closeSearchSuggestions, syncClearButtons: syncSearchClearButtons };
}
