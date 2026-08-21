/* Combined, non-destructive filtering for the movie catalog. */

function fpSmartFilters() {
  state.fp.filters = state.fp.filters || {
    period: "all", rating: "all", availability: "all", language: "all", sort: "default",
  };
  return state.fp.filters;
}

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
  if (filters.availability === "queued" && !state.queuedSlugs.has(result.slug)) return false;
  if (filters.language !== "all" && !mediaContentLanguages(media).has(filters.language)) return false;
  return true;
}

function fpSmartFilteredResults() {
  return state.fp.results.filter(fpSmartFilterMatches);
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
  if (state.fp.activeGenre !== "Alle Genres") labels.push(state.fp.activeGenre);
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
    [...document.querySelectorAll("#fp-results .result-card")]
      .map((row) => [row.dataset.slug, row]),
  );
  for (const result of state.fp.results) {
    const row = rowsBySlug.get(result.slug);
    if (!row) continue;
    const shown = orderBySlug.has(result.slug);
    row.hidden = !shown;
    row.style.order = shown && filters.sort !== "default" ? String(orderBySlug.get(result.slug)) : "";
  }
  const labels = fpActiveFilterLabels();
  const chips = document.getElementById("movie-filter-chips");
  if (chips) {
    chips.replaceChildren();
    if (!labels.length) {
      const empty = document.createElement("span");
      empty.textContent = "Keine Einschränkungen";
      chips.appendChild(empty);
    } else {
      for (const label of labels) {
        const chip = document.createElement("span");
        chip.className = "is-active";
        chip.textContent = label;
        chips.appendChild(chip);
      }
    }
  }
  const count = document.getElementById("genre-count");
  if (count) count.textContent = `${visible.length} von ${state.fp.results.length} Filmen sichtbar`;
  const reset = document.getElementById("movie-filter-reset");
  if (reset) reset.disabled = labels.length === 0;
  const status = document.getElementById("fp-status");
  if (status) status.textContent = fpStatusMessage();
}

function resetFpSmartFilters() {
  state.fp.filters = {
    period: "all", rating: "all", availability: "all", language: "all", sort: "default",
  };
  for (const [id, value] of Object.entries(state.fp.filters)) {
    const select = document.getElementById(`movie-filter-${id}`);
    if (select) select.value = value;
  }
  if (state.fp.activeGenre !== "Alle Genres") void fpGenreChange("Alle Genres");
  else applyFpSmartFilters();
}
