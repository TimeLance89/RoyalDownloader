function bindLibraryEnhancementControls() {
  document.getElementById("wl-search-clear").addEventListener("click", () => {
    state.wl.query = "";
    state.wl.draftQuery = "";
    state.wl.selected.clear();
    document.getElementById("wl-search").value = "";
    document.getElementById("wl-search-clear").hidden = true;
    renderWatchlist();
    document.getElementById("wl-search").focus();
  });
  document.querySelectorAll("[data-library-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.wl.view = button.dataset.libraryView || "grid";
      renderWatchlist();
    });
  });
  document.getElementById("wl-select-visible").addEventListener("click", () => {
    const visible = libraryVisibleItems().map((entry) => entry.base_slug);
    const allSelected = visible.length > 0 && visible.every((slug) => state.wl.selected.has(slug));
    visible.forEach((slug) => allSelected ? state.wl.selected.delete(slug) : state.wl.selected.add(slug));
    renderWatchlist();
  });
  document.querySelectorAll("[data-notif-filter]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.wl.notifFilter = button.dataset.notifFilter || "all";
      renderNotifBell();
    });
  });
}

function watchlistNeedsAttention(entry) {
  return Boolean(
    entry.new_count || entry.cleanup_last_error
    || entry.status === "blocked" || entry.status === "failed",
  );
}

function libraryVisibleItems() {
  const query = String(state.wl.query || "").trim().toLocaleLowerCase("de-DE");
  const filtered = state.wl.items.filter((entry) => {
    if (query && !String(entry.title || "").toLocaleLowerCase("de-DE").includes(query)) return false;
    if (state.wl.filter === "attention") return watchlistNeedsAttention(entry);
    if (state.wl.filter === "current") return entry.status === "current";
    if (state.wl.filter === "queued") return entry.status === "queued" || Number(entry.queued_count) > 0;
    return true;
  });
  return filtered.sort((left, right) => {
    if (state.wl.sort === "title") return String(left.title).localeCompare(String(right.title), "de");
    if (state.wl.sort === "recent") return Number(right.last_checked || 0) - Number(left.last_checked || 0);
    return Number(watchlistNeedsAttention(right)) - Number(watchlistNeedsAttention(left))
      || Number(right.new_count || 0) - Number(left.new_count || 0)
      || String(left.title).localeCompare(String(right.title), "de");
  });
}

function showLibraryHero(entry) {
  state.wl.heroBaseSlug = entry?.base_slug || "";
  const heroArt = document.getElementById("library-hero-art");
  const heroArtwork = api.coverUrl(entry?.backdrop_url || "").replace(/"/g, "%22");
  heroArt.style.backgroundImage = heroArtwork ? `url("${heroArtwork}")` : "";
  heroArt.classList.toggle("has-artwork", Boolean(heroArtwork));
  document.getElementById("library-hero-title").textContent = entry?.title || "Meine Liste";
  document.getElementById("library-hero-description").textContent = entry
    ? `${watchlistStatusText(entry)} · ${libraryCheckedLabel(entry)}`
    : "Neue Folgen erkennen, Regeln ändern und deine Serien an einem Ort steuern.";
  document.getElementById("wl-hero-open").disabled = !entry;
  document.getElementById("wl-hero-check").disabled = !entry;
}

function libraryCheckedLabel(entry) {
  const timestamp = Number(entry?.last_checked || 0);
  if (!timestamp) return "Noch nicht geprüft";
  const elapsed = Math.max(0, Date.now() - timestamp * 1000);
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "Gerade geprüft";
  if (minutes < 60) return `Vor ${minutes} Min. geprüft`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Vor ${hours} Std. geprüft`;
  const days = Math.floor(hours / 24);
  return `Vor ${days} ${days === 1 ? "Tag" : "Tagen"} geprüft`;
}

function renderWatchlist() {
  const container = document.getElementById("wl-list");
  container.innerHTML = "";
  const knownSlugs = new Set(state.wl.items.map((entry) => entry.base_slug));
  for (const slug of state.wl.selected) {
    if (!knownSlugs.has(slug)) state.wl.selected.delete(slug);
  }

  const attentionCount = state.wl.items.reduce((sum, entry) => {
    if (entry.new_count) return sum + entry.new_count;
    return sum + (entry.cleanup_last_error || entry.status === "blocked" || entry.status === "failed" ? 1 : 0);
  }, 0);
  document.getElementById("wl-total-count").textContent = String(state.wl.items.length);
  document.getElementById("wl-attention-count").textContent = String(attentionCount);
  document.getElementById("wl-current-count").textContent = String(
    state.wl.items.filter((entry) => entry.status === "current").length,
  );
  document.getElementById("wl-queued-count").textContent = String(
    state.wl.items.reduce((sum, entry) => sum + Number(entry.queued_count || 0), 0),
  );
  const filterCounts = {
    all: state.wl.items.length,
    attention: state.wl.items.filter(watchlistNeedsAttention).length,
    current: state.wl.items.filter((entry) => entry.status === "current").length,
    queued: state.wl.items.filter((entry) => entry.status === "queued" || Number(entry.queued_count) > 0).length,
  };
  Object.entries(filterCounts).forEach(([filter, count]) => {
    document.getElementById(`wl-filter-${filter}-count`).textContent = String(count);
  });
  document.getElementById("wl-selected-count").textContent = String(state.wl.selected.size);
  const globalError = String(state.wl.health?.error || "");
  if (globalError) document.getElementById("wl-status").textContent = globalError;
  const heroEntry = state.wl.items.find((entry) => entry.base_slug === state.wl.heroBaseSlug)
    || state.wl.items.find(watchlistNeedsAttention) || state.wl.items[0];
  showLibraryHero(heroEntry);
  const visibleItems = libraryVisibleItems();
  document.getElementById("wl-visible-count").textContent = String(visibleItems.length);
  document.querySelectorAll("[data-library-filter]").forEach((button) => {
    const active = button.dataset.libraryFilter === state.wl.filter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll("[data-library-view]").forEach((button) => {
    const active = button.dataset.libraryView === state.wl.view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  container.classList.toggle("is-list-view", state.wl.view === "list");
  document.getElementById("wl-check-all").disabled = state.wl.items.length === 0 || state.wl.checkRunning;
  document.getElementById("wl-select-visible").disabled = visibleItems.length === 0 || state.wl.checkRunning;
  document.getElementById("wl-select-visible").querySelector("span").textContent =
    visibleItems.length > 0 && visibleItems.every((entry) => state.wl.selected.has(entry.base_slug))
      ? "Auswahl lösen" : "Sichtbare wählen";
  for (const id of ["wl-check-selected", "wl-open", "wl-remove"]) {
    document.getElementById(id).disabled = state.wl.selected.size === 0 || state.wl.checkRunning;
  }

  if (!state.wl.items.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty";
    empty.innerHTML = `
      <span class="library-empty-mark" aria-hidden="true">＋</span>
      <strong>Deine Liste ist noch leer</strong>
      <span>Öffne eine Serie und wähle „Meine Liste“, um sie hier zu sehen.</span>
    `;
    container.appendChild(empty);
    return;
  }

  if (!visibleItems.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty is-filtered";
    empty.innerHTML = `
      <span class="library-empty-mark" aria-hidden="true">⌕</span>
      <strong>Kein Archivtreffer</strong>
      <span>Filter ändern oder einen anderen Titel mit Enter suchen.</span>
    `;
    container.appendChild(empty);
    return;
  }

  visibleItems.forEach((entry, index) => {
    const isSelected = state.wl.selected.has(entry.base_slug);
    const needsAttention = watchlistNeedsAttention(entry);
    const row = document.createElement("div");
    row.className = "wl-row library-card"
      + (isSelected ? " selected" : "")
      + (needsAttention ? " has-new" : "");
    row.tabIndex = 0;
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", `${entry.title} öffnen oder auswählen`);

    const top = document.createElement("div");
    top.className = "library-card-top";
    const select = document.createElement("label");
    select.className = "library-card-select";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = isSelected;
    cb.setAttribute("aria-label", `${entry.title} auswählen`);
    cb.addEventListener("click", (e) => { e.stopPropagation(); toggleWlSelect(entry.base_slug); });
    const archiveNumber = document.createElement("span");
    archiveNumber.textContent = `ABO ${String(index + 1).padStart(2, "0")}`;
    select.append(cb, archiveNumber);

    const stateBadge = document.createElement("span");
    const visibleStatus = entry.checking ? "checking" : (entry.status || "current");
    stateBadge.className = `library-state is-${visibleStatus}`;
    stateBadge.textContent = ({
      checking: "Prüft …",
      blocked: "Blockiert",
      failed: "Fehler",
      queued: "In Queue",
      waiting_window: "Zeitfenster",
      waiting_release: "Noch nicht erschienen",
      missing: "Offen",
      current: "Aktuell",
    })[visibleStatus] || "Aktuell";
    top.append(select, stateBadge);

    const identity = document.createElement("div");
    identity.className = "library-card-identity";
    const artwork = document.createElement("span");
    artwork.className = "library-card-artwork";
    if (entry.backdrop_url) {
      const image = document.createElement("img");
      image.src = api.coverUrl(entry.backdrop_url);
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => artwork.classList.add("is-fallback"), { once: true });
      artwork.appendChild(image);
    } else {
      artwork.classList.add("is-fallback");
    }
    const monogram = document.createElement("span");
    monogram.className = "library-card-monogram";
    monogram.textContent = subscriptionMonogram(entry.title);
    artwork.appendChild(monogram);
    const copy = document.createElement("span");
    copy.className = "library-card-copy";
    const title = document.createElement("strong");
    title.className = "library-card-title";
    title.translate = false;
    title.textContent = entry.title;
    const statusText = document.createElement("span");
    statusText.className = "library-card-status";
    statusText.textContent = watchlistStatusText(entry);
    const checked = document.createElement("span");
    checked.className = "library-card-checked";
    checked.textContent = libraryCheckedLabel(entry);
    copy.append(title, statusText, checked);
    identity.append(artwork, copy);

    const knownEpisodes = Array.isArray(entry.known_slugs) ? entry.known_slugs.length : 0;
    const missingEpisodes = Number(entry.new_count || 0);
    const archivePercent = entry.download_mode === "all" && knownEpisodes
      ? Math.max(0, Math.min(100, ((knownEpisodes - missingEpisodes) / knownEpisodes) * 100))
      : null;
    const progress = document.createElement("span");
    progress.className = "library-card-progress";
    progress.hidden = archivePercent === null;
    progress.setAttribute(
      "aria-label",
      archivePercent === null
        ? "Fortschritt für diese Abo-Regel nicht berechenbar"
        : `Archivstand ${Math.round(archivePercent)} Prozent`,
    );
    const progressFill = document.createElement("i");
    progressFill.style.width = `${archivePercent || 0}%`;
    progress.appendChild(progressFill);

    const episodeStatus = document.createElement("div");
    episodeStatus.className = "library-episode-status";
    const episodeValue = document.createElement("strong");
    episodeValue.textContent = entry.status === "waiting_release"
      ? "○"
      : (needsAttention
        ? (entry.status === "blocked" || entry.cleanup_last_error ? "!" : String(entry.failed_count || entry.new_count || "!"))
        : "✓");
    const episodeLabel = document.createElement("span");
    episodeLabel.textContent = entry.status === "waiting_release"
      ? "Release ausstehend"
      : (needsAttention
        ? (entry.new_count === 1 ? "Episode offen" : (entry.new_count ? "Episoden offen" : "Prüfung nötig"))
        : "Vollständig");
    episodeStatus.append(episodeValue, episodeLabel);

    const downloadReceipt = document.createElement("div");
    downloadReceipt.className = "library-download-receipt"
      + (Number(entry.downloaded_count || 0) > 0 ? " is-unread" : "");
    downloadReceipt.hidden = !entry.last_downloaded_episode;
    downloadReceipt.textContent = entry.last_downloaded_episode
      ? `✓ ${downloadedEpisodeLabel(entry)} geladen`
      : "";

    const footer = document.createElement("div");
    footer.className = "library-card-footer";
    const rule = document.createElement("button");
    rule.type = "button";
    rule.className = "wl-rule-btn";
    const downloadLabel = entry.download_mode_label || WATCH_MODE_LABELS[entry.download_mode] || WATCH_MODE_LABELS[WATCH_MODE_DEFAULT];
    const cleanupLabel = WATCH_CLEANUP_LABELS[entry.cleanup_mode] || WATCH_CLEANUP_LABELS[WATCH_CLEANUP_DEFAULT];
    rule.textContent = `${downloadLabel}${entry.cleanup_mode !== WATCH_CLEANUP_DEFAULT ? ` · ${cleanupLabel}` : ""}`;
    rule.title = "Abo- und Löschregel ändern";
    rule.addEventListener("click", (event) => {
      event.stopPropagation();
      openWatchModeModal(entry);
    });
    const open = document.createElement("button");
    open.type = "button";
    open.className = "library-card-open";
    open.textContent = "Öffnen  →";
    open.addEventListener("click", (event) => {
      event.stopPropagation();
      openWatchlistEntry(entry.base_slug);
    });
    footer.append(rule, open);

    row.append(top, identity, progress, episodeStatus, downloadReceipt, footer);
    row.addEventListener("focusin", () => showLibraryHero(entry));
    row.addEventListener("click", () => openWatchlistEntry(entry.base_slug));
    row.addEventListener("keydown", (event) => {
      if (event.target !== row || (event.key !== " " && event.key !== "Enter")) return;
      event.preventDefault();
      if (event.key === "Enter") openWatchlistEntry(entry.base_slug);
      else toggleWlSelect(entry.base_slug);
    });
    container.appendChild(row);
  });
}

function toggleWlSelect(baseSlug) {
  if (state.wl.selected.has(baseSlug)) state.wl.selected.delete(baseSlug);
  else state.wl.selected.add(baseSlug);
  renderWatchlist();
}

async function openWatchlistEntry(baseSlug) {
  switchTab("serien", { autoLoad: false });
  state.series.browseRequestSeq += 1;
  state.series.loadingBrowse = false;
  const openGeneration = ++state.series.viewGeneration;
  document.getElementById("series-status").textContent = "Lade abonnierte Serie …";
  try {
    const series = await api.watchlistOpen(baseSlug);
    if (state.series.viewGeneration !== openGeneration) return;
    const preselect = series.preselect_slugs || [];
    delete series.preselect_slugs;
    showSeriesDetail(series, firstEpisodeSlug(series));
    const selectable = new Set(
      seriesEpisodes(series).filter(isEpisodeSelectable).map((episode) => episode.slug),
    );
    state.series.epPicked = new Set(preselect.filter((slug) => selectable.has(slug)));
    renderSeriesTiles();
    await syncWatchlistSnapshot("Abo-Aktualisierung nach Öffnen");
  } catch (error) {
    if (state.series.viewGeneration !== openGeneration) return;
    document.getElementById("series-status").textContent =
      `Serie konnte nicht geöffnet werden: ${error.message}`;
  }
}

// ── Abo-Inbox v2 ─────────────────────────────────────────────────────────
// Statusmengen sind orthogonal: Ein Abo kann zugleich offene, geplante,
// geladene und fehlgeschlagene Folgen besitzen. Die Inbox zeigt es nur einmal.
function notificationCount(value) {
  const count = Number(value);
  return Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0;
}

function notificationHasIssue(entry) {
  return Boolean(
    entry.cleanup_last_error || entry.last_error
    || notificationCount(entry.failed_count) > 0
    || entry.status === "blocked" || entry.status === "failed"
  );
}

function buildSubscriptionInbox(items, health = {}) {
  const entries = (Array.isArray(items) ? items : []).map((entry) => ({
    entry,
    // Alte Server kennen open_count noch nicht. new_count darf dann nicht um
    // queued/failed reduziert werden, weil diese Mengen überlappen konnten.
    openCount: notificationCount(entry.open_count ?? entry.new_count),
    queuedCount: notificationCount(entry.queued_count),
    downloadedCount: notificationCount(entry.downloaded_count),
    hasIssue: notificationHasIssue(entry),
  })).filter((item) => (
    item.openCount || item.queuedCount || item.downloadedCount || item.hasIssue
  ));
  const globalError = String(health?.error || "").trim();
  const counts = {
    all: entries.length + (globalError ? 1 : 0),
    new: entries.filter((item) => item.openCount > 0).length,
    queued: entries.filter((item) => item.queuedCount > 0).length,
    downloaded: entries.filter((item) => item.downloadedCount > 0).length,
    issue: entries.filter((item) => item.hasIssue).length + (globalError ? 1 : 0),
  };
  const totals = entries.reduce((sum, item) => ({
    open: sum.open + item.openCount,
    queued: sum.queued + item.queuedCount,
    downloaded: sum.downloaded + item.downloadedCount,
  }), { open: 0, queued: 0, downloaded: 0 });
  return { entries, counts, totals, globalError };
}

function inboxEntriesForFilter(model, filter = "all") {
  return model.entries.filter((item) => {
    if (filter === "new") return item.openCount > 0;
    if (filter === "queued") return item.queuedCount > 0;
    if (filter === "downloaded") return item.downloadedCount > 0;
    if (filter === "issue") return item.hasIssue;
    return true;
  }).sort((left, right) => {
    if (filter === "downloaded") {
      const timestamp = (item) => Number(
        (item.entry.last_unread_downloaded_episode
          || item.entry.last_downloaded_episode)?.downloaded_at || 0
      );
      return timestamp(right) - timestamp(left)
        || String(left.entry.title || "").localeCompare(String(right.entry.title || ""), "de");
    }
    return Number(right.hasIssue) - Number(left.hasIssue)
      || right.openCount - left.openCount
      || right.queuedCount - left.queuedCount
      || String(left.entry.title || "").localeCompare(String(right.entry.title || ""), "de");
  });
}

function downloadedEpisodeLabel(entry) {
  const episode = entry?.last_unread_downloaded_episode || entry?.last_downloaded_episode;
  if (!episode) return "";
  return `S${String(episode.season || 0).padStart(2, "0")}E${String(episode.episode || 0).padStart(2, "0")}`;
}

function inboxCheckBusy() {
  return Boolean(
    state.wl.checkRunning || notificationCount(state.wl.health?.checking_count)
    || state.wl.items.some((entry) => entry.checking)
  );
}

function ensureSubscriptionCenterStyles() {
  if (document.querySelector('link[data-subscription-center-styles]')) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/styles/subscription-center.css?v=royal-20260908-1";
  link.dataset.subscriptionCenterStyles = "true";
  document.head.appendChild(link);
}

function ensureSubscriptionCenterChrome() {
  ensureSubscriptionCenterStyles();
  const bell = document.getElementById("notif-bell");
  if (!document.getElementById("notif-issue-badge")) {
    const badge = document.createElement("span");
    badge.id = "notif-issue-badge";
    badge.className = "notif-issue-badge hidden";
    badge.textContent = "!";
    badge.setAttribute("aria-hidden", "true");
    bell.appendChild(badge);
  }
  const close = document.getElementById("notif-close");
  if (close && !close.dataset.bound) {
    close.dataset.bound = "true";
    close.addEventListener("click", () => closeNotifDropdown(true));
  }
  if (!document.getElementById("notif-feedback")) {
    const feedback = document.createElement("p");
    feedback.id = "notif-feedback";
    feedback.className = "notif-feedback";
    feedback.hidden = true;
    feedback.setAttribute("role", "status");
    (document.querySelector(".notif-head") || document.body).appendChild(feedback);
  }
}

function inboxIssueDetail(entry) {
  const parts = [];
  const failed = notificationCount(entry.failed_count);
  if (failed) parts.push(`${failed} ${failed === 1 ? "Download ist" : "Downloads sind"} fehlgeschlagen.`);
  if (entry.last_error) parts.push(String(entry.last_error));
  else if (entry.status === "blocked") parts.push("Die Quelle konnte nicht geprüft werden.");
  else if (entry.status === "failed" && !failed) parts.push("Ein Download ist fehlgeschlagen.");
  if (entry.cleanup_last_error) parts.push(`Bereinigung pausiert: ${entry.cleanup_last_error}`);
  return parts.join(" ");
}

function inboxDownloadDetail(entry) {
  const episode = entry.last_unread_downloaded_episode || entry.last_downloaded_episode;
  const timestamp = Number(episode?.downloaded_at || 0);
  const when = timestamp ? new Date(timestamp * 1000).toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }) : "";
  return [`Zuletzt geladen: ${downloadedEpisodeLabel(entry) || "Folge"}`, when]
    .filter(Boolean).join(" · ");
}

function buildNotificationItem(item) {
  const { entry, openCount, queuedCount, downloadedCount, hasIssue } = item;
  const stateName = hasIssue ? "issue" : openCount ? "new" : queuedCount ? "queued" : "downloaded";
  const row = document.createElement("article");
  row.className = `notif-item is-${stateName}`;
  row.dataset.baseSlug = entry.base_slug;

  const open = document.createElement("button");
  open.type = "button";
  open.className = "notif-item-open";
  open.setAttribute("aria-label", `${entry.title} öffnen`);
  const art = document.createElement("span");
  art.className = "notif-item-art";
  if (entry.backdrop_url) {
    const image = document.createElement("img");
    image.src = api.coverUrl(entry.backdrop_url);
    image.alt = "";
    image.loading = "lazy";
    image.addEventListener("error", () => art.classList.add("is-fallback"), { once: true });
    art.appendChild(image);
  } else {
    art.classList.add("is-fallback");
  }
  const monogram = document.createElement("span");
  monogram.className = "notif-item-monogram";
  monogram.textContent = subscriptionMonogram(entry.title);
  art.appendChild(monogram);

  const copy = document.createElement("span");
  copy.className = "notif-item-copy";
  const title = document.createElement("strong");
  title.translate = false;
  title.textContent = entry.title;
  const meta = document.createElement("small");
  meta.className = "notif-item-meta";
  meta.textContent = entry.checking ? "Wird gerade geprüft …" : libraryCheckedLabel(entry);
  const signals = document.createElement("span");
  signals.className = "notif-item-signals";
  const signal = (kind, text) => {
    const pill = document.createElement("span");
    pill.className = `notif-state is-${kind}`;
    pill.textContent = text;
    signals.appendChild(pill);
  };
  if (openCount) signal("new", `${openCount} ${openCount === 1 ? "Folge offen" : "Folgen offen"}`);
  if (queuedCount) signal("queued", `${queuedCount} im Downloadplan`);
  if (downloadedCount) signal("downloaded", `${downloadedCount} ${downloadedCount === 1 ? "Folge geladen" : "Folgen geladen"}`);
  if (hasIssue) signal("issue", "Problem");
  copy.append(title, meta, signals);
  const arrow = document.createElement("span");
  arrow.className = "notif-item-arrow";
  arrow.textContent = "›";
  open.append(art, copy, arrow);
  open.addEventListener("click", () => {
    closeNotifDropdown();
    openWatchlistEntry(entry.base_slug);
  });
  row.appendChild(open);

  const detailText = hasIssue ? inboxIssueDetail(entry)
    : entry.status === "waiting_window" && openCount
      ? "Der automatische Download wartet auf das nächste Zeitfenster."
      : openCount ? "Serie öffnen, um die offenen Folgen auszuwählen."
        : queuedCount ? "Diese Folgen stehen im Downloadplan." : "";
  if (detailText) {
    const detail = document.createElement("p");
    detail.className = "notif-item-detail";
    detail.textContent = detailText;
    row.appendChild(detail);
  }
  if (downloadedCount) {
    const receipt = document.createElement("small");
    receipt.className = "notif-item-download";
    receipt.textContent = inboxDownloadDetail(entry);
    row.appendChild(receipt);
  }
  const actions = document.createElement("div");
  actions.className = "notif-item-actions";
  if (openCount || hasIssue) {
    const check = document.createElement("button");
    check.type = "button";
    check.className = "notif-item-check";
    check.textContent = entry.checking ? "Prüft …" : "Erneut prüfen";
    check.disabled = inboxCheckBusy();
    check.addEventListener("click", async () => {
      check.disabled = true;
      try { await runNotificationCheck([entry.base_slug]); }
      finally { check.disabled = false; }
    });
    actions.appendChild(check);
  }
  if (downloadedCount) {
    const read = document.createElement("button");
    read.type = "button";
    read.className = "notif-item-read";
    read.textContent = state.wl.notifReading === entry.base_slug ? "Wird gespeichert …" : "Als gelesen";
    read.disabled = Boolean(state.wl.notifReading);
    read.addEventListener("click", async () => {
      read.disabled = true;
      try { await markNotificationDownloadsRead(entry); }
      finally { read.disabled = false; }
    });
    actions.appendChild(read);
  }
  if (actions.children.length) row.appendChild(actions);
  return row;
}

function inboxContext(model, filter) {
  if (filter === "new") return `${model.totals.open} Folgen offen. Fehlgeschlagene Downloads bleiben hier sichtbar.`;
  if (filter === "queued") return `${model.totals.queued} Folgen im Downloadplan.`;
  if (filter === "downloaded") return `${model.totals.downloaded} Downloads sind noch ungelesen.`;
  if (filter === "issue") return "Download-, Prüf- und Bereinigungsfehler.";
  return "Ein Eintrag pro Abo. Ein Abo kann mehrere Zustände haben.";
}

function appendInboxEmpty(list, filter) {
  const empty = document.createElement("div");
  empty.className = "notif-empty";
  const seal = document.createElement("span");
  seal.className = "notif-empty-seal";
  const title = document.createElement("strong");
  const detail = document.createElement("small");
  if (!state.wl.loaded) {
    seal.textContent = "…";
    title.textContent = "Abonnements werden geladen";
    detail.textContent = "Der Status wird abgerufen.";
  } else if (!state.wl.items.length) {
    seal.textContent = "+";
    title.textContent = "Noch keine Abonnements";
    detail.textContent = "Abonniere eine Serie, damit Meldungen hier erscheinen.";
  } else if (inboxCheckBusy()) {
    seal.textContent = "…";
    title.textContent = "Abonnements werden geprüft";
    detail.textContent = "Die Meldungen werden gleich aktualisiert.";
  } else {
    const messages = {
      all: ["Keine aktuellen Meldungen", "Neue Funde, Downloads und Probleme erscheinen hier."],
      new: ["Keine offenen Folgen", "Zurzeit ist keine Folge zur Auswahl offen."],
      queued: ["Keine geplanten Downloads", "Keine Abo-Folge steht im Downloadplan."],
      downloaded: ["Keine ungelesenen Downloads", "Geladene Folgen wurden bereits bestätigt."],
      issue: ["Keine Probleme gemeldet", "Aktuell liegt kein Abo-Fehler vor."],
    }[filter];
    seal.textContent = "✓";
    title.textContent = messages[0];
    detail.textContent = messages[1];
  }
  empty.append(seal, title, detail);
  list.appendChild(empty);
}

function renderNotifBell() {
  ensureSubscriptionCenterChrome();
  const model = buildSubscriptionInbox(state.wl.items, state.wl.health);
  const filter = Object.hasOwn(model.counts, state.wl.notifFilter) ? state.wl.notifFilter : "all";
  state.wl.notifFilter = filter;
  const badge = document.getElementById("notif-badge");
  const issueBadge = document.getElementById("notif-issue-badge");
  const bell = document.getElementById("notif-bell");
  const summary = model.counts.all
    ? `${model.counts.all} ${model.counts.all === 1 ? "Eintrag" : "Einträge"}`
    : state.wl.loaded ? "Keine Meldungen" : "Wird geladen …";
  badge.textContent = String(model.counts.all);
  badge.classList.toggle("hidden", model.counts.all === 0);
  issueBadge.classList.toggle("hidden", model.counts.issue === 0);
  bell.classList.toggle("is-active", model.counts.all > 0);
  bell.setAttribute("aria-label", `Abo-Inbox öffnen: ${summary}`);
  document.getElementById("notif-trigger-label").textContent = summary;
  document.getElementById("notif-summary").textContent = inboxCheckBusy()
    ? "Abonnements werden geprüft …" : summary;
  document.getElementById("notif-subscription-count").textContent =
    `${state.wl.items.length} ${state.wl.items.length === 1 ? "Abo" : "Abos"}`;
  const refresh = document.getElementById("notif-refresh");
  refresh.disabled = inboxCheckBusy() || !state.wl.loaded || !state.wl.items.length;
  refresh.classList.toggle("is-loading", inboxCheckBusy());
  const feedback = document.getElementById("notif-feedback");
  if (feedback) {
    feedback.textContent = state.wl.notifFeedback || "";
    feedback.hidden = !feedback.textContent;
    feedback.classList.toggle("is-error", Boolean(state.wl.notifFeedbackError));
  }
  document.querySelectorAll("[data-notif-filter]").forEach((button) => {
    const kind = button.dataset.notifFilter;
    const active = kind === filter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    const count = button.querySelector(".notif-filter-count");
    if (count) count.textContent = String(model.counts[kind]);
  });

  const list = document.getElementById("notif-list");
  list.replaceChildren();
  const visible = inboxEntriesForFilter(model, filter);
  const showGlobalError = Boolean(model.globalError && (filter === "all" || filter === "issue"));
  if (visible.length || showGlobalError) {
    const context = document.createElement("p");
    context.className = "notif-context";
    context.textContent = inboxContext(model, filter);
    list.appendChild(context);
  }
  if (showGlobalError) {
    const problem = document.createElement("div");
    problem.className = "notif-global-issue";
    const title = document.createElement("strong");
    title.textContent = "Abonnements konnten nicht geprüft werden";
    const detail = document.createElement("small");
    detail.textContent = model.globalError;
    problem.append(title, detail);
    list.appendChild(problem);
  }
  visible.forEach((item) => list.appendChild(buildNotificationItem(item)));
  if (!visible.length && !showGlobalError) appendInboxEmpty(list, filter);
}

function toggleNotifDropdown() {
  const dropdown = document.getElementById("notif-dropdown");
  const open = dropdown.classList.contains("hidden");
  if (open) renderNotifBell();
  dropdown.classList.toggle("hidden", !open);
  document.getElementById("notif-bell").setAttribute("aria-expanded", String(open));
}

function closeNotifDropdown(restoreFocus = false) {
  const dropdown = document.getElementById("notif-dropdown");
  dropdown.classList.add("hidden");
  document.getElementById("notif-bell").setAttribute("aria-expanded", "false");
  if (restoreFocus && typeof document.getElementById("notif-bell").focus === "function") {
    document.getElementById("notif-bell").focus({ preventScroll: true });
  }
}

async function runNotificationCheck(baseSlugs) {
  if (inboxCheckBusy()) return;
  state.wl.notifFeedback = "";
  try {
    const data = await performWatchlistCheck(baseSlugs || null);
    state.wl.notifFeedback = data?.health?.error
      ? String(data.health.error) : "Prüfung abgeschlossen. Meldungen wurden aktualisiert.";
    state.wl.notifFeedbackError = Boolean(data?.health?.error);
  } catch (error) {
    state.wl.notifFeedback = `Prüfung fehlgeschlagen: ${error.message || error}`;
    state.wl.notifFeedbackError = true;
  }
  renderNotifBell();
}

async function markNotificationDownloadsRead(entry) {
  if (state.wl.notifReading) return;
  state.wl.notifReading = entry.base_slug;
  state.wl.notifFeedback = "";
  try {
    const receipt = entry.last_unread_downloaded_episode || entry.last_downloaded_episode;
    await api.watchlistDownloadsRead(entry.base_slug, Number(receipt?.downloaded_at || 0));
    await refreshWatchlist();
    state.wl.notifFeedback = `Download-Meldungen für ${entry.title} als gelesen markiert.`;
    state.wl.notifFeedbackError = false;
  } catch (error) {
    state.wl.notifFeedback = `Lesestatus konnte nicht aktualisiert werden: ${error.message || error}`;
    state.wl.notifFeedbackError = true;
  } finally {
    state.wl.notifReading = "";
    renderNotifBell();
  }
}

async function refreshNotifications() {
  return runNotificationCheck(null);
}
