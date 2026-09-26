// ── Bibliothek-Tab ─────────────────────────────────────────────────────────
function presentWatchlist(snapshot, previous) {
  sharedPresentation.notifications.refresh();
  const items = snapshot.items;
  if (items === previous?.items) return;
  for (const series of Object.values(sharedPresentation.seriesState.cache)) {
    const entry = watchlistEntryForSeries(series, items);
    series.watchlisted = Boolean(entry);
    series.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
    series.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
  }
  if (sharedPresentation.seriesState.current) {
    const entry = watchlistEntryForSeries(sharedPresentation.seriesState.current, items);
    sharedPresentation.seriesState.current.watchlisted = Boolean(entry);
    sharedPresentation.seriesState.current.watch_mode = entry?.download_mode || WATCH_MODE_DEFAULT;
    sharedPresentation.seriesState.current.cleanup_mode = entry?.cleanup_mode || WATCH_CLEANUP_DEFAULT;
    updateWatchBtn();
  }
  renderSeriesSubscriptions();
}

function subscriptionMonogram(title) {
  const words = String(title || "").trim().split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2)).toUpperCase();
}

function watchlistStatusText(entry) {
  if (entry.checking) return "wird geprüft";
  if (entry.status === "blocked") return entry.last_error || "Prüfung blockiert";
  if (entry.status === "failed") return `${entry.failed_count || 1} fehlgeschlagen · Retry geplant`;
  if (entry.cleanup_last_error) return `Löschen pausiert · ${entry.cleanup_last_error}`;
  if (entry.status === "queued") return `${entry.queued_count || entry.new_count} in der Queue`;
  if (entry.status === "waiting_window") return `${entry.new_count} warten auf Zeitfenster`;
  if (entry.status === "waiting_for_language") return `${entry.waiting_language_count || 1} warten auf Deutsch`;
  if (entry.status === "upcoming") return `${entry.upcoming_count || 1} angekündigt`;
  if (entry.status === "waiting_release") return `${entry.waiting_release_count || 1} warten auf Release`;
  if (entry.new_count) return `${entry.new_count} fehlen`;
  return "vollständig";
}

function renderSeriesSubscriptions() {
  const container = document.getElementById("series-subscriptions-list");
  if (!container) return;
  const items = sharedPresentation.subscriptions.get().items;
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

function watchlistCheckResultText(data) {
  return String(data?.health?.error || "")
    || `${Number(data?.checked || 0)}/${Number(data?.total || 0)} geprüft`;
}

function dedupeCatalogMedia(items) { return sharedPresentation.catalogIdentity.dedupe(items); }
function catalogLogicalMediaMatch(left, right) { return sharedPresentation.catalogIdentity.match(left, right); }

function reconcileMovieCatalogDuplicates() {
  const current = Array.isArray(sharedPresentation.movieState.results) ? sharedPresentation.movieState.results : [];
  const selected = current.find((item) => item.slug === sharedPresentation.movieState.selectedSlug) || null;
  const reconciled = dedupeCatalogMedia(current);
  if (reconciled.length === current.length) return false;

  sharedPresentation.movieState.results = reconciled;
  if (selected && !reconciled.some((item) => item.slug === sharedPresentation.movieState.selectedSlug)) {
    sharedPresentation.movieState.selectedSlug = reconciled.find((item) => catalogLogicalMediaMatch(item, selected))?.slug || null;
  }
  renderFpResults(0);
  refreshMovieFeatureCandidates();
  updateFpInfiniteState();
  const status = document.getElementById("fp-status");
  if (status) status.textContent = fpStatusMessage();
  return true;
}

function reconcileSeriesCatalogDuplicates() {
  const current = Array.isArray(sharedPresentation.seriesState.results) ? sharedPresentation.seriesState.results : [];
  const reconciled = dedupeCatalogMedia(current);
  if (reconciled.length === current.length) return false;

  sharedPresentation.seriesState.results = reconciled;
  renderSeriesResults(0);
  renderSeriesCatalogHero();
  updateSeriesInfiniteState();
  const sourceCount = sharedPresentation.seriesState.sources.length;
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

function openWatchlistEntry(...args) { return sharedPresentation.seriesDetailsLoader.openSubscription(...args); }
