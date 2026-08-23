// ── Bibliothek-Tab ─────────────────────────────────────────────────────────
function applyWatchlist(items) {
  watchlistSnapshotGeneration += 1;
  state.wl.items = items;
  state.wl.loaded = true;
  for (const series of Object.values(state.series.cache)) {
    const entry = watchlistEntryForSeries(series, items);
    series.watchlisted = Boolean(entry);
    series.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
    series.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
  }
  if (state.series.current) {
    const entry = watchlistEntryForSeries(state.series.current, items);
    state.series.current.watchlisted = Boolean(entry);
    state.series.current.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
    state.series.current.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
    updateWatchBtn();
  }
  renderWatchlist();
  renderSeriesSubscriptions();
  renderNotifBell();
}

function subscriptionMonogram(title) {
  const words = String(title || "").trim().split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2)).toUpperCase();
}

function watchlistStatusText(entry) {
  if (entry.status === "blocked") return entry.last_error || "Prüfung blockiert";
  if (entry.status === "failed") return `${entry.failed_count || 1} fehlgeschlagen · Retry geplant`;
  if (entry.cleanup_last_error) return `Löschen pausiert · ${entry.cleanup_last_error}`;
  if (entry.status === "queued") return `${entry.queued_count || entry.new_count} in der Queue`;
  if (entry.status === "waiting_window") return `${entry.new_count} warten auf Zeitfenster`;
  if (entry.status === "waiting_release") return `${entry.waiting_release_count || 1} warten auf Release`;
  if (entry.new_count) return `${entry.new_count} fehlen`;
  return "vollständig";
}

function renderSeriesSubscriptions() {
  const container = document.getElementById("series-subscriptions-list");
  if (!container) return;
  const items = state.wl.items;
  document.getElementById("series-subscriptions-count").textContent =
    `${items.length} ${items.length === 1 ? "Serie" : "Serien"}`;
  container.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "subscriptions-empty";
    empty.textContent = "Noch keine Abos – Serie auswählen und auf „Abonnieren“ klicken.";
    container.appendChild(empty);
    return;
  }

  for (const entry of items) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "subscription-card" + (entry.new_count || entry.cleanup_last_error || entry.status === "blocked" || entry.status === "failed" ? " has-new" : "");
    card.title = `${entry.title} öffnen`;

    const monogram = document.createElement("span");
    monogram.className = "subscription-monogram";
    monogram.textContent = subscriptionMonogram(entry.title);

    const text = document.createElement("span");
    text.className = "subscription-text";
    const title = document.createElement("span");
    title.className = "subscription-name";
    title.translate = false;
    title.textContent = entry.title;
    const meta = document.createElement("span");
    meta.className = "subscription-meta";
    const modeLabel = entry.download_mode_label || WATCH_MODE_LABELS[entry.download_mode] || WATCH_MODE_LABELS[WATCH_MODE_DEFAULT];
    const cleanupLabel = WATCH_CLEANUP_LABELS[entry.cleanup_mode] || WATCH_CLEANUP_LABELS[WATCH_CLEANUP_DEFAULT];
    meta.textContent = `${modeLabel}${entry.cleanup_mode !== WATCH_CLEANUP_DEFAULT ? ` · ${cleanupLabel}` : ""} · ${watchlistStatusText(entry)}`;
    text.append(title, meta);
    card.append(monogram, text);

    if (entry.new_count) {
      const badge = document.createElement("span");
      badge.className = "subscription-new";
      badge.textContent = `+${entry.new_count}`;
      card.appendChild(badge);
    }
    card.addEventListener("click", () => openWatchlistEntry(entry.base_slug));
    container.appendChild(card);
  }
}

async function refreshWatchlist() {
  return syncWatchlistSnapshot("Abo-Aktualisierung");
}

// ── Cross-catalog consistency: logical media identities ────────────────────
// Provider URLs/slugs are source identities, not media identities. The visual
// catalogs therefore collapse the same logical movie/series across providers
// while preserving the first (priority) source as the navigation identity.
function normalizeCatalogIdentityText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase()
    .replace(/&/g, " und ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function catalogIdentityView(item) {
  if (!item) return {};
  const slug = String(item.slug || "").trim();
  const metadata = slug ? state.fp?.metadataCache?.[slug] : null;
  return metadata ? { ...item, ...metadata } : item;
}

function catalogMediaYear(item) {
  const identity = catalogIdentityView(item);
  const raw = String(identity?.year || identity?.release_date || identity?.first_air_date || "");
  return raw.match(/\b(?:19|20)\d{2}\b/)?.[0] || "";
}

function catalogMediaTitles(item) {
  const identity = catalogIdentityView(item);
  return new Set([
    identity?.title,
    identity?.original_title,
    identity?.original_name,
  ].map(normalizeCatalogIdentityText).filter(Boolean));
}

function catalogLogicalMediaMatch(left, right) {
  if (!left || !right) return false;
  const leftIdentity = catalogIdentityView(left);
  const rightIdentity = catalogIdentityView(right);
  const leftTitles = catalogMediaTitles(leftIdentity);
  const rightTitles = catalogMediaTitles(rightIdentity);
  const titleMatches = [...leftTitles].some((title) => rightTitles.has(title));
  const leftSources = new Set([
    ...(leftIdentity.sources || []), ...(leftIdentity.source_providers || []),
  ].map(catalogSourceIdentity).filter(Boolean));
  const sharesSource = [
    ...(rightIdentity.sources || []), ...(rightIdentity.source_providers || []),
  ].map(catalogSourceIdentity).some((source) => leftSources.has(source));
  // Anbieter melden bei Serien teilweise das Jahr der neuesten Staffel statt
  // des Serienstarts. Exakter Titel plus gleiche Quelle ist dennoch eindeutig.
  if (titleMatches && sharesSource) return true;
  const leftTmdb = String(leftIdentity.tmdb_id || "").trim();
  const rightTmdb = String(rightIdentity.tmdb_id || "").trim();
  if (leftTmdb && rightTmdb) return leftTmdb === rightTmdb;

  const leftYear = catalogMediaYear(leftIdentity);
  const rightYear = catalogMediaYear(rightIdentity);
  if (leftYear && rightYear && leftYear !== rightYear) return false;

  if (!titleMatches) return false;

  // With an unknown year, avoid collapsing obvious separate remakes when both
  // records have different explicit TMDB identities. That case was handled
  // above; provider-only records may safely share an exact logical title.
  return true;
}

function mergeCatalogArrayValues(left, right, keyFor = (value) => String(value || "")) {
  const merged = [];
  const known = new Set();
  for (const value of [...(Array.isArray(left) ? left : []), ...(Array.isArray(right) ? right : [])]) {
    if (value == null || value === "") continue;
    const key = keyFor(value);
    if (!key || known.has(key)) continue;
    known.add(key);
    merged.push(value);
  }
  return merged;
}

function catalogSourceIdentity(source) {
  if (!source || typeof source !== "object") return "";
  return String(source.key || source.provider || source.label || source.url || "").trim().toLocaleLowerCase();
}

function mergeCatalogMediaRecord(primary, secondary) {
  const merged = { ...primary };
  const preferSecondaryWhenMissing = [
    "tmdb_id", "original_title", "original_name", "year", "release_date", "first_air_date",
    "cover_url", "backdrop_url", "description", "rating", "vote_count", "content_language",
  ];
  for (const key of preferSecondaryWhenMissing) {
    if ((merged[key] == null || merged[key] === "") && secondary?.[key] != null && secondary[key] !== "") {
      merged[key] = secondary[key];
    }
  }
  if (String(secondary?.description || "").length > String(merged.description || "").length) {
    merged.description = secondary.description;
  }

  merged.genres = mergeCatalogArrayValues(merged.genres, secondary?.genres, (value) => normalizeCatalogIdentityText(value));
  merged.sources = mergeCatalogArrayValues(merged.sources, secondary?.sources, catalogSourceIdentity);
  merged.source_providers = mergeCatalogArrayValues(
    merged.source_providers,
    secondary?.source_providers,
    catalogSourceIdentity,
  );

  const languageValues = [
    ...(Array.isArray(merged.content_languages) ? merged.content_languages : []),
    ...(Array.isArray(secondary?.content_languages) ? secondary.content_languages : []),
    merged.content_language,
    secondary?.content_language,
    ...merged.sources.map((source) => source?.content_language),
    ...merged.source_providers.map((source) => source?.content_language),
  ];
  merged.content_languages = mergeCatalogArrayValues([], languageValues, (value) => String(value || "").toLowerCase());

  if (primary?.in_jellyfin === true || secondary?.in_jellyfin === true) {
    merged.in_jellyfin = true;
    merged.jellyfin_status = "owned";
  } else if (!merged.jellyfin_status && secondary?.jellyfin_status) {
    merged.jellyfin_status = secondary.jellyfin_status;
  }

  // Preserve the first item's slug/base_slug/provider. Provider priority is
  // still meaningful for opening details and fallback order.
  return merged;
}

function dedupeCatalogMedia(items) {
  const output = [];
  for (const item of Array.isArray(items) ? items : []) {
    const duplicateIndex = output.findIndex((known) => catalogLogicalMediaMatch(known, item));
    if (duplicateIndex < 0) {
      output.push(item);
      continue;
    }
    output[duplicateIndex] = mergeCatalogMediaRecord(output[duplicateIndex], item);
  }
  return output;
}

function reconcileMovieCatalogDuplicates() {
  const current = Array.isArray(state.fp.results) ? state.fp.results : [];
  const selected = current.find((item) => item.slug === state.fp.selectedSlug) || null;
  const reconciled = dedupeCatalogMedia(current);
  if (reconciled.length === current.length) return false;

  state.fp.results = reconciled;
  if (selected && !reconciled.some((item) => item.slug === state.fp.selectedSlug)) {
    state.fp.selectedSlug = reconciled.find((item) => catalogLogicalMediaMatch(item, selected))?.slug || null;
  }
  renderFpResults(0);
  refreshMovieFeatureCandidates();
  updateFpInfiniteState();
  const status = document.getElementById("fp-status");
  if (status) status.textContent = fpStatusMessage();
  return true;
}

function reconcileSeriesCatalogDuplicates() {
  const current = Array.isArray(state.series.results) ? state.series.results : [];
  const reconciled = dedupeCatalogMedia(current);
  if (reconciled.length === current.length) return false;

  state.series.results = reconciled;
  renderSeriesResults(0);
  renderSeriesCatalogHero();
  updateSeriesInfiniteState();
  const sourceCount = state.series.sources.length;
  const status = document.getElementById("series-status");
  if (status) {
    status.textContent = reconciled.length
      ? (sourceCount
        ? `${reconciled.length} Serie(n) · ${sourceCount} ${sourceCount === 1 ? "Quelle" : "Quellen"}`
        : `${reconciled.length} Serie(n) gefunden`)
      : "Keine Serie gefunden.";
  }
  return true;
}

function cleanMediaCardInitials(title) {
  const words = String(title || "")
    .trim()
    .split(/\s+/)
    .filter((word) => /[\p{L}\p{N}]/u.test(word));
  if (!words.length) return "RD";
  return (words.length === 1
    ? words[0].slice(0, 2)
    : words.slice(0, 2).map((word) => word.match(/[\p{L}\p{N}]/u)?.[0] || "").join(""))
    .toUpperCase();
}

function installCatalogConsistencyPolicy() {
  if (window.__royalCatalogConsistencyInstalled) return;
  window.__royalCatalogConsistencyInstalled = true;

  if (typeof mergeCatalogItems === "function") {
    const originalMergeCatalogItems = mergeCatalogItems;
    window.mergeCatalogItems = function logicalCatalogMerge(current, incoming, keyFor) {
      const merged = originalMergeCatalogItems(current, incoming, keyFor);
      const looksLikeMedia = merged.some((item) => item?.title && (
        item?.slug || item?.base_slug || item?.sample_slug || item?.tmdb_id
      ));
      return looksLikeMedia ? dedupeCatalogMedia(merged) : merged;
    };
  }

  if (typeof applyFpResults === "function") {
    const originalApplyFpResults = applyFpResults;
    window.applyFpResults = function logicalMovieResults(data, options = {}) {
      const payload = {
        ...(data || {}),
        results: dedupeCatalogMedia(data?.results || []),
      };
      return originalApplyFpResults(payload, options);
    };
  }

  if (typeof applySeriesResults === "function") {
    const originalApplySeriesResults = applySeriesResults;
    window.applySeriesResults = function logicalSeriesResults(data, options = {}) {
      const payload = {
        ...(data || {}),
        results: dedupeCatalogMedia(data?.results || []),
      };
      return originalApplySeriesResults(payload, options);
    };
  }

  // Provider rows often do not yet contain TMDB identity. Reconcile once the
  // asynchronous metadata preload has populated metadataCache, otherwise
  // translated titles such as "Die Odyssee" / "The Odyssey" remain separate.
  if (typeof preloadTmdbMetadata === "function") {
    const originalPreloadTmdbMetadata = preloadTmdbMetadata;
    window.preloadTmdbMetadata = async function logicalMovieMetadataPreload(...args) {
      const result = await originalPreloadTmdbMetadata(...args);
      reconcileMovieCatalogDuplicates();
      return result;
    };
  }

  // Series metadata is assigned to the result objects by this hydrator. The
  // initial result pass therefore needs the same post-hydration reconciliation.
  if (typeof hydrateHomeSeriesArtwork === "function") {
    const originalHydrateHomeSeriesArtwork = hydrateHomeSeriesArtwork;
    window.hydrateHomeSeriesArtwork = async function logicalSeriesMetadataHydration(...args) {
      const result = await originalHydrateHomeSeriesArtwork(...args);
      reconcileSeriesCatalogDuplicates();
      return result;
    };
  }

  if (typeof mediaCardInitials === "function") {
    window.mediaCardInitials = cleanMediaCardInitials;
  }
}

installCatalogConsistencyPolicy();
