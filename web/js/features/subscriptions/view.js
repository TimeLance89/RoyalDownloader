import { createScope } from "../../core/lifecycle.js";
import { createViewState } from "../../shared/components/view-state.js";
import { libraryVisibleItems, libraryCheckedLabel, watchlistNeedsAttention } from "./model.js";

export function createLibraryView(root, { subscriptions, ui, coverUrl, watchlistStatusText, subscriptionMonogram, downloadedEpisodeLabel, openWatchModeModal, openWatchlistEntry, WATCH_MODE_LABELS, WATCH_MODE_DEFAULT, WATCH_CLEANUP_LABELS, WATCH_CLEANUP_DEFAULT }) {
  const byId = id => root.querySelector(`#${id}`);
  let rowsScope;
  function showLibraryHero(entry) {
    ui.heroBaseSlug = entry?.base_slug || "";
    const heroArt = byId("library-hero-art");
    const heroArtwork = coverUrl(entry?.backdrop_url || "").replace(/"/g, "%22");
    heroArt.style.backgroundImage = heroArtwork ? `url("${heroArtwork}")` : "";
    heroArt.classList.toggle("has-artwork", Boolean(heroArtwork));
    byId("library-hero-title").textContent = entry?.title || "Meine Liste";
    byId("library-hero-description").textContent = entry
      ? `${watchlistStatusText(entry)} · ${libraryCheckedLabel(entry)}`
      : "Neue Folgen erkennen, Regeln ändern und deine Serien an einem Ort steuern.";
    byId("wl-hero-open").disabled = !entry;
    byId("wl-hero-check").disabled = !entry;
  }

  function renderWatchlist() {
    rowsScope?.dispose();
    rowsScope = createScope();
    const container = byId("wl-list");
    container.innerHTML = "";
    const knownSlugs = new Set(subscriptions.get().items.map((entry) => entry.base_slug));
    for (const slug of ui.selected) {
      if (!knownSlugs.has(slug)) ui.selected.delete(slug);
    }

    const attentionCount = subscriptions.get().items.reduce((sum, entry) => {
      if (entry.new_count) return sum + entry.new_count;
      return sum + (entry.cleanup_last_error || entry.status === "blocked" || entry.status === "failed" ? 1 : 0);
    }, 0);
    byId("wl-total-count").textContent = String(subscriptions.get().items.length);
    byId("wl-attention-count").textContent = String(attentionCount);
    byId("wl-current-count").textContent = String(
      subscriptions.get().items.filter((entry) => entry.status === "current").length,
    );
    byId("wl-queued-count").textContent = String(
      subscriptions.get().items.reduce((sum, entry) => sum + Number(entry.queued_count || 0), 0),
    );
    const filterCounts = {
      all: subscriptions.get().items.length,
      attention: subscriptions.get().items.filter(watchlistNeedsAttention).length,
      current: subscriptions.get().items.filter((entry) => entry.status === "current").length,
      queued: subscriptions.get().items.filter((entry) => entry.status === "queued" || Number(entry.queued_count) > 0).length,
    };
    Object.entries(filterCounts).forEach(([filter, count]) => {
      byId(`wl-filter-${filter}-count`).textContent = String(count);
    });
    byId("wl-selected-count").textContent = String(ui.selected.size);
    const globalError = String(subscriptions.get().error || subscriptions.get().health?.error || "");
    byId("wl-status").textContent = globalError || ui.feedback || "Bereit zur Prüfung";
    const heroEntry = subscriptions.get().items.find((entry) => entry.base_slug === ui.heroBaseSlug)
      || subscriptions.get().items.find(watchlistNeedsAttention) || subscriptions.get().items[0];
    showLibraryHero(heroEntry);
    const visibleItems = libraryVisibleItems(subscriptions.get().items, ui);
    byId("wl-visible-count").textContent = String(visibleItems.length);
    root.querySelectorAll("[data-library-filter]").forEach((button) => {
      const active = button.dataset.libraryFilter === ui.filter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    root.querySelectorAll("[data-library-view]").forEach((button) => {
      const active = button.dataset.libraryView === ui.view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    container.classList.toggle("is-list-view", ui.view === "list");
    byId("wl-check-all").disabled = subscriptions.get().items.length === 0 || subscriptions.get().checkRunning || ui.removing;
    byId("wl-select-visible").disabled = visibleItems.length === 0 || subscriptions.get().checkRunning || ui.removing;
    byId("wl-select-visible").querySelector("span").textContent =
      visibleItems.length > 0 && visibleItems.every((entry) => ui.selected.has(entry.base_slug))
        ? "Auswahl lösen" : "Sichtbare wählen";
    for (const id of ["wl-check-selected", "wl-open", "wl-remove"]) {
      byId(id).disabled = ui.selected.size === 0 || subscriptions.get().checkRunning || ui.removing;
    }

    if (!subscriptions.get().items.length && !subscriptions.get().loaded) {
      const failed = subscriptions.get().status === "error";
      container.append(createViewState({ state: failed ? "error" : "loading", className: "library-empty",
        title: failed ? "Abos konnten nicht geladen werden" : "Abos werden geladen …",
        detail: subscriptions.get().error, retry: failed ? () => { if (rowsScope?.active) void subscriptions.refresh(); } : undefined }));
      return;
    }
    if (!subscriptions.get().items.length) {
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
      const isSelected = ui.selected.has(entry.base_slug);
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
      rowsScope.listen(cb, "click", (e) => { e.stopPropagation(); toggleWlSelect(entry.base_slug); });
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
        image.src = coverUrl(entry.backdrop_url);
        image.alt = "";
        image.loading = "lazy";
        rowsScope.listen(image, "error", () => artwork.classList.add("is-fallback"), { once: true });
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
      rowsScope.listen(rule, "click", (event) => {
        event.stopPropagation();
        openWatchModeModal(entry);
      });
      const open = document.createElement("button");
      open.type = "button";
      open.className = "library-card-open";
      open.textContent = "Öffnen  →";
      rowsScope.listen(open, "click", (event) => {
        event.stopPropagation();
        openWatchlistEntry(entry.base_slug);
      });
      footer.append(rule, open);

      row.append(top, identity, progress, episodeStatus, downloadReceipt, footer);
      rowsScope.listen(row, "focusin", () => showLibraryHero(entry));
      rowsScope.listen(row, "click", () => openWatchlistEntry(entry.base_slug));
      rowsScope.listen(row, "keydown", (event) => {
        if (event.target !== row || (event.key !== " " && event.key !== "Enter")) return;
        event.preventDefault();
        if (event.key === "Enter") openWatchlistEntry(entry.base_slug);
        else toggleWlSelect(entry.base_slug);
      });
      container.appendChild(row);
    });
  }

  function toggleWlSelect(baseSlug) {
    if (ui.selected.has(baseSlug)) ui.selected.delete(baseSlug);
    else ui.selected.add(baseSlug);
    renderWatchlist();
  }

  return { render: renderWatchlist, dispose() { rowsScope?.dispose(); rowsScope = null; } };
}
