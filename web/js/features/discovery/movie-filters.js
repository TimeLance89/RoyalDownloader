/** Local filter draft; catalog results remain untouched. */
export function createMovieFilters(root, {
  movieState, getQueuedSlugs, fpResultMedia, fpResultYear, mediaJellyfinStatus, mediaContentLanguages,
  fpStatusMessage, fpGenreChange,
}) {
  const byId = id => root.querySelector(`#${id}`);
  let filters = { period: "all", rating: "all", availability: "all", language: "all", sort: "default" };
  function fpSmartFilters() { return filters; }
  function fpSmartFilterMatches(result) {
    const filters = fpSmartFilters();
    const media = fpResultMedia(result);
    const year = Number.parseInt(fpResultYear(result), 10) || 0;
    const rating = Number.parseFloat(String(media.rating || "").replace(",", ".")) || 0;
    if (filters.period === "2020s" && year < 2020) return false;
    if (filters.period === "2010s" && (year < 2010 || year > 2019)) return false;
    if (filters.period === "2000s" && (year < 2000 || year > 2009)) return false;
    if (filters.period === "classic" && (!year || year >= 2000)) return false;
    if (filters.rating !== "all" && rating < Number(filters.rating)) return false;
    if (filters.availability === "owned" && mediaJellyfinStatus(media) !== "owned") return false;
    if (filters.availability === "missing" && mediaJellyfinStatus(media) === "owned") return false;
    if (filters.availability === "queued" && !getQueuedSlugs().has(result.slug)) return false;
    if (filters.language !== "all" && !mediaContentLanguages(media).has(filters.language)) return false;
    return true;
  }

  function fpSmartFilteredResults() {
    return movieState.results.filter(fpSmartFilterMatches);
  }

  function fpSmartSortValue(result, sort) {
    const media = fpResultMedia(result);
    if (sort === "newest") return Number.parseInt(fpResultYear(result), 10) || 0;
    if (sort === "rating") return Number.parseFloat(String(media.rating || "").replace(",", ".")) || 0;
    return 0;
  }

  function fpActiveFilterLabels() {
    const filters = fpSmartFilters();
    const labels = [];
    if (movieState.activeGenre !== "Alle Genres") labels.push(movieState.activeGenre);
    labels.push({ "2020s": "Seit 2020", "2010s": "2010–2019", "2000s": "2000–2009", classic: "Vor 2000" }[filters.period]);
    if (filters.rating !== "all") labels.push(`★ ${filters.rating}+`);
    labels.push({ owned: "In Jellyfin", missing: "Nicht in Jellyfin", queued: "In Queue" }[filters.availability]);
    labels.push({ de: "Deutsch", en: "Englisch" }[filters.language]);
    labels.push({ newest: "Neueste zuerst", rating: "Beste Bewertung", title: "Titel A–Z" }[filters.sort]);
    return labels.filter(Boolean);
  }

  function applyFpSmartFilters() {
    const filters = fpSmartFilters();
    const visible = fpSmartFilteredResults();
    const ordered = visible.slice();
    if (filters.sort === "title") {
      ordered.sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), "de"));
    } else if (filters.sort !== "default") {
      ordered.sort((a, b) => fpSmartSortValue(b, filters.sort) - fpSmartSortValue(a, filters.sort));
    }
    const orderBySlug = new Map(ordered.map((result, index) => [result.slug, index]));
    const rowsBySlug = new Map(
      [...root.querySelectorAll("#fp-results .result-card")]
        .map((row) => [row.dataset.slug, row]),
    );
    for (const result of movieState.results) {
      const row = rowsBySlug.get(result.slug);
      if (!row) continue;
      const shown = orderBySlug.has(result.slug);
      row.hidden = !shown;
      row.style.order = shown && filters.sort !== "default" ? String(orderBySlug.get(result.slug)) : "";
    }
    const labels = fpActiveFilterLabels();
    const chips = byId("movie-filter-chips");
    if (chips) {
      chips.replaceChildren();
      if (!labels.length) {
        const empty = root.ownerDocument.createElement("span");
        empty.textContent = "Keine Einschränkungen";
        chips.appendChild(empty);
      } else {
        for (const label of labels) {
          const chip = root.ownerDocument.createElement("span");
          chip.className = "is-active";
          chip.textContent = label;
          chips.appendChild(chip);
        }
      }
    }
    const count = byId("genre-count");
    if (count) count.textContent = `${visible.length} von ${movieState.results.length} Filmen sichtbar`;
    const reset = byId("movie-filter-reset");
    if (reset) reset.disabled = labels.length === 0;
    const status = byId("fp-status");
    if (status) status.textContent = fpStatusMessage();
  }

  function resetFpSmartFilters() {
    filters = {
      period: "all", rating: "all", availability: "all", language: "all", sort: "default",
    };
    for (const [id, value] of Object.entries(filters)) {
      const select = byId(`movie-filter-${id}`);
      if (select) select.value = value;
    }
    if (movieState.activeGenre !== "Alle Genres") void fpGenreChange("Alle Genres");
    else applyFpSmartFilters();
  }
  return {
    get: fpSmartFilters, matches: fpSmartFilterMatches, results: fpSmartFilteredResults,
    labels: fpActiveFilterLabels, apply: applyFpSmartFilters, reset: resetFpSmartFilters,
    set(key, value) { if (Object.hasOwn(filters, key)) filters[key] = value; },
  };
}
