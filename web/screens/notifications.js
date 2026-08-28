// ── Benachrichtigungs-Glocke ─────────────────────────────────────────────
function ensureSubscriptionCenterStyles() {
  if (document.querySelector('link[data-subscription-center-styles]')) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/styles/subscription-center.css?v=royal-20260828-1";
  link.dataset.subscriptionCenterStyles = "true";
  document.head.appendChild(link);
}

function notificationHasIssue(entry) {
  return Boolean(entry.cleanup_last_error || entry.status === "blocked" || entry.status === "failed");
}

function notificationState(entry) {
  if (notificationHasIssue(entry)) return "issue";
  if (Number(entry.queued_count || 0) > 0 || entry.status === "queued") return "queued";
  return "new";
}

function downloadedEpisodeLabel(entry) {
  const episode = entry?.last_downloaded_episode;
  if (!episode) return "";
  return `S${String(episode.season || 0).padStart(2, "0")}E${String(episode.episode || 0).padStart(2, "0")}`;
}

function notificationStateLabel(entry) {
  if (entry.status === "blocked") return "Quelle blockiert";
  if (entry.status === "failed") return "Prüfung fehlgeschlagen";
  if (entry.cleanup_last_error) return "Bereinigung prüfen";
  const queued = Number(entry.queued_count || 0);
  if (queued > 0 || entry.status === "queued") return `${queued || entry.new_count || 1} im Downloadplan`;
  return `${Number(entry.new_count || 0)} neu`;
}

function ensureSubscriptionCenterChrome() {
  ensureSubscriptionCenterStyles();
  const bell = document.getElementById("notif-bell");
  let issueBadge = document.getElementById("notif-issue-badge");
  if (!issueBadge) {
    issueBadge = document.createElement("span");
    issueBadge.id = "notif-issue-badge";
    issueBadge.className = "notif-issue-badge hidden";
    issueBadge.textContent = "!";
    issueBadge.setAttribute("aria-hidden", "true");
    bell.appendChild(issueBadge);
  }

  let stats = document.getElementById("notif-stats");
  if (!stats) {
    stats = document.createElement("div");
    stats.id = "notif-stats";
    stats.className = "notif-stats";
    stats.setAttribute("aria-label", "Abo-Status");
    stats.innerHTML = `
      <span class="notif-stat is-new"><strong id="notif-new-count">0</strong><small>Neue Episoden</small></span>
      <span class="notif-stat is-downloaded"><strong id="notif-downloaded-count">0</strong><small>Heruntergeladen</small></span>
      <span class="notif-stat is-issue"><strong id="notif-issue-count">0</strong><small>Probleme</small></span>
      <span class="notif-stat is-ok"><strong id="notif-center-subscriptions">0</strong><small>Abonnements</small></span>
    `;
    const head = document.querySelector(".notif-head");
    head?.insertBefore(stats, head.querySelector(".notif-filters"));
  }
}

function buildNotificationItem(entry, forcedState = "") {
  const item = document.createElement("article");
  const stateName = forcedState || notificationState(entry);
  item.className = `notif-item is-${stateName}`;

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
  const mode = document.createElement("small");
  mode.textContent = watchlistStatusText(entry);
  const statePill = document.createElement("span");
  statePill.className = `notif-state is-${stateName}`;
  statePill.textContent = stateName === "downloaded"
    ? `${downloadedEpisodeLabel(entry)} heruntergeladen`
    : notificationStateLabel(entry);
  copy.append(title, mode, statePill);

  const count = document.createElement("span");
  count.className = "notif-count";
  const countValue = document.createElement("strong");
  countValue.textContent = stateName === "downloaded"
    ? String(entry.downloaded_count || 1)
    : notificationHasIssue(entry)
    ? "!"
    : String(entry.failed_count || entry.new_count || entry.queued_count || 0);
  const countLabel = document.createElement("small");
  countLabel.textContent = stateName === "downloaded"
    ? "Geladen"
    : notificationHasIssue(entry)
    ? "Prüfen"
    : (entry.new_count === 1 ? "Episode" : "Episoden");
  count.append(countValue, countLabel);

  const arrow = document.createElement("span");
  arrow.className = "notif-item-arrow";
  arrow.textContent = "›";
  open.append(art, copy, count, arrow);
  open.addEventListener("click", () => {
    closeNotifDropdown();
    if (stateName === "downloaded") {
      api.watchlistDownloadsRead(entry.base_slug)
        .then((data) => applyWatchlist(data.watchlist))
        .catch(() => {});
    }
    openWatchlistEntry(entry.base_slug);
  });

  const check = document.createElement("button");
  check.type = "button";
  check.className = "notif-item-check";
  check.textContent = "Prüfen";
  check.setAttribute("aria-label", `${entry.title} jetzt prüfen`);
  check.addEventListener("click", async () => {
    check.disabled = true;
    check.textContent = "Prüft …";
    try {
      const data = await api.watchlistCheck([entry.base_slug]);
      applyWatchlist(data.watchlist);
    } catch (error) {
      document.getElementById("notif-summary").textContent = `Prüfung fehlgeschlagen: ${error.message}`;
    } finally {
      check.disabled = false;
      check.textContent = "Prüfen";
    }
  });
  item.append(open, check);
  return item;
}

function appendNotificationSection(list, className, label, entries) {
  if (!entries.length) return;
  const section = document.createElement("section");
  section.className = `notif-section ${className}`;
  const heading = document.createElement("div");
  heading.className = "notif-section-title";
  const title = document.createElement("span");
  title.textContent = label;
  const count = document.createElement("span");
  count.textContent = String(entries.length);
  heading.append(title, count);
  section.appendChild(heading);
  entries.forEach((entry) => section.appendChild(buildNotificationItem(
    entry,
    className === "is-downloaded" ? "downloaded" : "",
  )));
  list.appendChild(section);
}

function renderNotifBell() {
  ensureSubscriptionCenterChrome();
  const withNotice = state.wl.items.filter((e) => e.new_count || e.downloaded_count || notificationHasIssue(e));
  const total = withNotice.reduce((sum, e) => sum + Number(e.new_count || 0), 0);
  const downloadedTotal = withNotice.reduce((sum, e) => sum + Number(e.downloaded_count || 0), 0);
  const noticeTotal = total + downloadedTotal;
  const issueEntries = withNotice.filter(notificationHasIssue);
  const issueCount = issueEntries.length;
  const bell = document.getElementById("notif-bell");
  const badge = document.getElementById("notif-badge");
  const issueBadge = document.getElementById("notif-issue-badge");
  const triggerLabel = document.getElementById("notif-trigger-label");

  badge.textContent = String(noticeTotal);
  badge.classList.toggle("hidden", noticeTotal === 0);
  issueBadge.classList.toggle("hidden", issueCount === 0);
  bell.classList.toggle("is-active", noticeTotal > 0 || issueCount > 0);
  bell.setAttribute("aria-label", noticeTotal || issueCount
    ? `Abo-Inbox öffnen: ${total} neue Episoden, ${downloadedTotal} heruntergeladen, ${issueCount} Probleme`
    : "Abo-Inbox öffnen: alles aktuell");
  triggerLabel.textContent = noticeTotal
    ? `${noticeTotal} ${noticeTotal === 1 ? "Hinweis" : "Hinweise"}`
    : total
    ? `${total} ${total === 1 ? "neue Episode" : "neue Episoden"}`
    : (issueCount ? `${issueCount} ${issueCount === 1 ? "Problem" : "Probleme"}` : "Alles aktuell");

  const summary = document.getElementById("notif-summary");
  summary.textContent = noticeTotal || issueCount
    ? `${total} neu · ${downloadedTotal} geladen · ${issueCount} ${issueCount === 1 ? "Problem" : "Probleme"}`
    : "Alle abonnierten Serien sind vollständig";
  document.getElementById("notif-subscription-count").textContent =
    `${state.wl.items.length} ${state.wl.items.length === 1 ? "Abo" : "Abos"}`;
  document.getElementById("notif-new-count").textContent = String(total);
  document.getElementById("notif-downloaded-count").textContent = String(downloadedTotal);
  document.getElementById("notif-issue-count").textContent = String(issueCount);
  document.getElementById("notif-center-subscriptions").textContent = String(state.wl.items.length);

  document.querySelectorAll("[data-notif-filter]").forEach((button) => {
    const active = button.dataset.notifFilter === state.wl.notifFilter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  const list = document.getElementById("notif-list");
  list.innerHTML = "";
  if (!withNotice.length) {
    list.innerHTML = `
      <div class="notif-empty">
        <span class="notif-empty-seal">✓</span>
        <strong>Alles auf dem neuesten Stand</strong>
        <small>Royal überwacht deine abonnierten Serien weiter automatisch. Momentan fehlen keine Episoden und es gibt nichts zu prüfen.</small>
        <span class="notif-empty-meta">${state.wl.items.length} ${state.wl.items.length === 1 ? "Abo wird" : "Abos werden"} überwacht</span>
      </div>
    `;
    return;
  }

  const issueSorted = [...issueEntries].sort((a, b) =>
    (b.failed_count || 0) - (a.failed_count || 0)
    || (b.new_count || 0) - (a.new_count || 0)
    || a.title.localeCompare(b.title, "de"));
  const newSorted = withNotice
    .filter((entry) => !notificationHasIssue(entry) && Number(entry.new_count || 0) > 0)
    .sort((a, b) =>
      Number(b.queued_count || 0) - Number(a.queued_count || 0)
      || Number(b.new_count || 0) - Number(a.new_count || 0)
      || a.title.localeCompare(b.title, "de"));
  const downloadedSorted = withNotice
    .filter((entry) => Number(entry.downloaded_count || 0) > 0)
    .sort((a, b) => Number(b.last_downloaded_episode?.downloaded_at || 0)
      - Number(a.last_downloaded_episode?.downloaded_at || 0));

  const filter = state.wl.notifFilter || "all";
  if (filter === "all") appendNotificationSection(list, "is-downloaded", "Heruntergeladen", downloadedSorted);
  if (filter !== "issue") appendNotificationSection(list, "is-new", "Neue Folgen", newSorted);
  if (filter !== "new") appendNotificationSection(list, "is-issue", "Probleme", issueSorted);
  if (!list.children.length) {
    const label = filter === "issue" ? "Keine Probleme" : "Keine neuen Folgen";
    list.innerHTML = `
      <div class="notif-empty is-filtered">
        <span class="notif-empty-seal">✓</span>
        <strong>${label}</strong>
        <small>In diesem Bereich gibt es gerade nichts zu bearbeiten.</small>
      </div>
    `;
  }
}

function toggleNotifDropdown() {
  const dropdown = document.getElementById("notif-dropdown");
  const open = dropdown.classList.contains("hidden");
  if (open) renderNotifBell();
  dropdown.classList.toggle("hidden", !open);
  document.getElementById("notif-bell").setAttribute("aria-expanded", String(open));
}

function closeNotifDropdown() {
  document.getElementById("notif-dropdown").classList.add("hidden");
  document.getElementById("notif-bell").setAttribute("aria-expanded", "false");
}

async function refreshNotifications() {
  ensureSubscriptionCenterChrome();
  const button = document.getElementById("notif-refresh");
  button.disabled = true;
  button.classList.add("is-loading");
  const summary = document.getElementById("notif-summary");
  summary.textContent = "Abonnements werden geprüft …";
  try {
    const data = await api.watchlistCheck(null);
    applyWatchlist(data.watchlist);
    const total = state.wl.items.reduce((sum, entry) => sum + Number(entry.new_count || 0), 0);
    const downloaded = state.wl.items.reduce((sum, entry) => sum + Number(entry.downloaded_count || 0), 0);
    const issues = state.wl.items.filter(notificationHasIssue).length;
    summary.textContent = total || downloaded || issues
      ? `Gerade eben geprüft · ${total} neu · ${downloaded} geladen · ${issues} ${issues === 1 ? "Problem" : "Probleme"}`
      : "Gerade eben geprüft · alles vollständig";
  } catch (error) {
    summary.textContent = `Prüfung fehlgeschlagen: ${error.message}`;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
  }
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
  document.getElementById("wl-check-all").disabled = state.wl.items.length === 0;
  document.getElementById("wl-select-visible").disabled = visibleItems.length === 0;
  document.getElementById("wl-select-visible").querySelector("span").textContent =
    visibleItems.length > 0 && visibleItems.every((entry) => state.wl.selected.has(entry.base_slug))
      ? "Auswahl lösen" : "Sichtbare wählen";
  for (const id of ["wl-check-selected", "wl-open", "wl-remove"]) {
    document.getElementById(id).disabled = state.wl.selected.size === 0;
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
    row.setAttribute("role", "checkbox");
    row.setAttribute("aria-checked", String(isSelected));

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
    stateBadge.className = `library-state is-${entry.status || "current"}`;
    stateBadge.textContent = ({
      blocked: "Blockiert",
      failed: "Fehler",
      queued: "In Queue",
      waiting_window: "Zeitfenster",
      waiting_release: "Noch nicht erschienen",
      missing: "Offen",
      current: "Aktuell",
    })[entry.status] || "Aktuell";
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
    const archivePercent = knownEpisodes
      ? Math.max(0, Math.min(100, ((knownEpisodes - missingEpisodes) / knownEpisodes) * 100))
      : (needsAttention ? 18 : 100);
    const progress = document.createElement("span");
    progress.className = "library-card-progress";
    progress.setAttribute("aria-label", `Archivstand ${Math.round(archivePercent)} Prozent`);
    const progressFill = document.createElement("i");
    progressFill.style.width = `${archivePercent}%`;
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
    row.addEventListener("pointerenter", () => showLibraryHero(entry));
    row.addEventListener("focusin", () => showLibraryHero(entry));
    row.addEventListener("click", () => toggleWlSelect(entry.base_slug));
    row.addEventListener("dblclick", () => openWatchlistEntry(entry.base_slug));
    row.addEventListener("keydown", (event) => {
      if (event.target !== row || (event.key !== " " && event.key !== "Enter")) return;
      event.preventDefault();
      toggleWlSelect(entry.base_slug);
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
