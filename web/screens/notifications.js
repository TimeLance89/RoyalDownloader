// ── Benachrichtigungs-Glocke ─────────────────────────────────────────────
function renderNotifBell() {
  const withNotice = state.wl.items.filter((e) => e.new_count || e.cleanup_last_error || e.status === "blocked" || e.status === "failed");
  const total = withNotice.reduce((sum, e) => sum + e.new_count, 0);
  const issueCount = withNotice.filter((entry) => entry.cleanup_last_error || entry.status === "blocked" || entry.status === "failed").length;
  const bell = document.getElementById("notif-bell");
  const badge = document.getElementById("notif-badge");
  const triggerLabel = document.getElementById("notif-trigger-label");
  badge.textContent = total ? String(total) : "!";
  badge.classList.toggle("hidden", total === 0 && issueCount === 0);
  bell.classList.toggle("is-active", total > 0 || issueCount > 0);
  bell.setAttribute("aria-label", total || issueCount
    ? `Abo-Postfach öffnen: ${total} fehlende Episoden, ${issueCount} Probleme`
    : "Abo-Postfach öffnen: alles aktuell");
  triggerLabel.textContent = total
    ? `${total} ${total === 1 ? "Episode fehlt" : "Episoden fehlen"}`
    : (issueCount ? `${issueCount} ${issueCount === 1 ? "Problem" : "Probleme"}` : "Alles aktuell");
  document.getElementById("notif-summary").textContent = total || issueCount
    ? `${total} fehlend · ${issueCount} problematisch`
    : "Alles vollständig";
  document.getElementById("notif-subscription-count").textContent =
    `${state.wl.items.length} ${state.wl.items.length === 1 ? "Abo" : "Abos"}`;

  const list = document.getElementById("notif-list");
  list.innerHTML = "";
  if (!withNotice.length) {
    list.innerHTML = `<div class="notif-empty"><span class="notif-empty-seal">✓</span><strong>Alles vollständig</strong><small>Abonnierte Serien werden weiter automatisch auf fehlende Episoden geprüft.</small></div>`;
    return;
  }
  const sorted = [...withNotice].sort((a, b) =>
    (b.failed_count || 0) - (a.failed_count || 0)
    || (b.new_count || 0) - (a.new_count || 0)
    || a.title.localeCompare(b.title, "de"));
  for (const entry of sorted) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "notif-item";
    const mark = document.createElement("span");
    mark.className = "notif-item-mark";
    mark.textContent = subscriptionMonogram(entry.title);
    const copy = document.createElement("span");
    copy.className = "notif-item-copy";
    const title = document.createElement("strong");
    title.textContent = entry.title;
    const mode = document.createElement("small");
    mode.textContent = watchlistStatusText(entry);
    copy.append(title, mode);
    const count = document.createElement("span");
    count.className = "notif-count";
    const countValue = document.createElement("strong");
    countValue.textContent = entry.status === "blocked" || entry.cleanup_last_error ? "!" : String(entry.failed_count || entry.new_count);
    const countLabel = document.createElement("small");
    countLabel.textContent = entry.status === "blocked"
      ? "Blockiert"
      : (entry.status === "failed"
        ? "Fehler"
        : (entry.cleanup_last_error ? "Löschen" : (entry.new_count === 1 ? "Episode" : "Episoden")));
    count.append(countValue, countLabel);
    const arrow = document.createElement("span");
    arrow.className = "notif-item-arrow";
    arrow.textContent = "›";
    item.append(mark, copy, count, arrow);
    item.addEventListener("click", () => {
      closeNotifDropdown();
      openWatchlistEntry(entry.base_slug);
    });
    list.appendChild(item);
  }
}

function toggleNotifDropdown() {
  const dropdown = document.getElementById("notif-dropdown");
  const open = dropdown.classList.contains("hidden");
  dropdown.classList.toggle("hidden", !open);
  document.getElementById("notif-bell").setAttribute("aria-expanded", String(open));
}

function closeNotifDropdown() {
  document.getElementById("notif-dropdown").classList.add("hidden");
  document.getElementById("notif-bell").setAttribute("aria-expanded", "false");
}

async function refreshNotifications() {
  const button = document.getElementById("notif-refresh");
  button.disabled = true;
  button.classList.add("is-loading");
  document.getElementById("notif-summary").textContent = "Abonnements werden geprüft …";
  try {
    const data = await api.watchlistCheck(null);
    applyWatchlist(data.watchlist);
  } catch (error) {
    document.getElementById("notif-summary").textContent = `Prüfung fehlgeschlagen: ${error.message}`;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
  }
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
  document.getElementById("wl-selected-count").textContent = String(state.wl.selected.size);
  const heroEntry = state.wl.items.find((entry) =>
    entry.new_count || entry.cleanup_last_error || entry.status === "blocked" || entry.status === "failed"
  ) || state.wl.items[0];
  const heroArt = document.getElementById("library-hero-art");
  const heroArtwork = api.coverUrl(heroEntry?.backdrop_url || heroEntry?.cover_url || "").replace(/"/g, "%22");
  heroArt.style.backgroundImage = heroArtwork ? `url("${heroArtwork}")` : "";
  heroArt.classList.toggle("has-artwork", Boolean(heroArtwork));
  document.getElementById("library-hero-description").textContent = heroEntry
    ? (attentionCount
      ? `${attentionCount} ${attentionCount === 1 ? "Update wartet" : "Updates warten"} auf dich.`
      : "Alles, was du verfolgst – vollständig und startklar.")
    : "Füge Serien hinzu und baue deine persönliche Sammlung auf.";
  document.getElementById("wl-check-all").disabled = state.wl.items.length === 0;
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

  state.wl.items.forEach((entry, index) => {
    const isSelected = state.wl.selected.has(entry.base_slug);
    const needsAttention = Boolean(
      entry.new_count || entry.cleanup_last_error || entry.status === "blocked" || entry.status === "failed"
    );
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
      missing: "Offen",
      current: "Aktuell",
    })[entry.status] || "Aktuell";
    top.append(select, stateBadge);

    const identity = document.createElement("div");
    identity.className = "library-card-identity";
    const artwork = document.createElement("span");
    artwork.className = "library-card-artwork";
    if (entry.cover_url) {
      const image = document.createElement("img");
      image.src = api.coverUrl(entry.cover_url);
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
    copy.append(title, statusText);
    identity.append(artwork, copy);

    const episodeStatus = document.createElement("div");
    episodeStatus.className = "library-episode-status";
    const episodeValue = document.createElement("strong");
    episodeValue.textContent = needsAttention
      ? (entry.status === "blocked" || entry.cleanup_last_error ? "!" : String(entry.failed_count || entry.new_count || "!"))
      : "✓";
    const episodeLabel = document.createElement("span");
    episodeLabel.textContent = needsAttention
      ? (entry.new_count === 1 ? "Episode offen" : (entry.new_count ? "Episoden offen" : "Prüfung nötig"))
      : "Vollständig";
    episodeStatus.append(episodeValue, episodeLabel);

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

    row.append(top, identity, episodeStatus, footer);
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
