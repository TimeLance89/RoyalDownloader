const state = createInitialState();
// Synchronous adapter to module presenters; initialized by the module entry before app startup.
const sharedPresentation = {};

const WATCH_MODE_DEFAULT = "latest_season";
const WATCH_MODE_LABELS = {
  all: "Alles Fehlende",
  latest_season: "Neueste Staffel",
  next_season: "Nächste Staffel nach Gesehen-Status",
};
const WATCH_MODE_EXPLANATIONS = {
  all: {
    title: "Das Abo hält die komplette Serie vollständig",
    copy: "Royal prüft sofort alle Staffeln und danach regelmäßig weiter. Bei aktivem Auto-Download landen Treffer in der Queue, sonst in der Abo-Inbox.",
  },
  latest_season: {
    title: "Die neueste Staffel bleibt im Fokus",
    copy: "Royal prüft sofort die höchste Staffel. Sobald eine neue Staffel erscheint, wird diese zum neuen Ziel. Treffer landen je nach Automatik in der Queue oder Abo-Inbox.",
  },
  next_season: {
    title: "Das Abo folgt deinem Sehfortschritt",
    copy: "Royal prüft den gewählten Jellyfin-Benutzer regelmäßig. Eine weitere Staffel wird erst freigegeben, wenn die vorherige vollständig als gesehen markiert ist.",
  },
};
const WATCH_CLEANUP_DEFAULT = "keep";
const WATCH_CLEANUP_LABELS = {
  keep: "Behalten",
  watched_seasons: "Staffel-Löschung",
  watched_episodes: "Episoden-Löschung",
};
function recheckFpInfinite() { sharedPresentation.infinite.movies.refresh(); }
function recheckSeriesInfinite() { sharedPresentation.infinite.series.refresh(); }
function recheckAniworldInfinite() { sharedPresentation.infinite.aniworld.refresh(); }

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ── Tabs ─────────────────────────────────────────────────────────────────
function animeNavigationAvailable() {
  return sharedPresentation.providers.get().contentLanguages.has("en");
}

function syncAnimeNavigationVisibility() {
  const visible = animeNavigationAvailable();
  document.querySelectorAll(".anime-tab-button").forEach((element) => {
    element.classList.toggle("hidden", !visible);
  });
  const providerLaneVisible = (sharedPresentation.providers.get().anime || []).some(
    (provider) => sharedPresentation.providers.get().contentLanguages.has(providerLanguage(provider)),
  );
  document.querySelectorAll(".provider-source-lane.is-anime").forEach((element) => {
    element.classList.toggle("hidden", !providerLaneVisible);
  });
  const animeContent = document.getElementById("tab-anime");
  if (animeContent) animeContent.setAttribute("aria-hidden", String(!visible));
  if (!visible && state.tab === "anime") switchTab("filme");
}

function aniworldNavigationAvailable() {
  return sharedPresentation.providers.get().contentLanguages.has("de");
}

function syncAniworldNavigationVisibility() {
  const visible = aniworldNavigationAvailable();
  document.querySelectorAll(".aniworld-tab-button").forEach((element) => {
    element.classList.toggle("hidden", !visible);
  });
  const content = document.getElementById("tab-aniworld");
  if (content) content.setAttribute("aria-hidden", String(!visible));
  if (!visible && state.tab === "aniworld") switchTab("filme");
}

function setNavigationMenuOpen(...args) { return sharedPresentation.shell.setMenuOpen(...args); }
function closeNavigationMenus(...args) { return sharedPresentation.shell.closeMenus(...args); }
function initNavigationMenus() { sharedPresentation.shell.mount(); }

function switchTab(name, { autoLoad = true } = {}) {
  if (name === "anime" && !animeNavigationAvailable()) name = "filme";
  if (name === "aniworld" && !aniworldNavigationAvailable()) name = "filme";
  if (sharedPresentation.search.get().active) closeGlobalSearch();
  closeAllMediaModals(false);
  document.querySelectorAll(".tabs [data-tab], .mobile-tabs [data-tab]").forEach((b) => {
    const active = b.dataset.tab === name;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".tab-content").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  // Im Einstellungen-Bereich die Download-Sidebar ausblenden (eigener Vollbereich).
  document.body.classList.toggle("settings-active", name === "einstellungen");
  closeMobileQueue();
  if (name === "einstellungen") setQueueDockExpanded(false);
  state.tab = name;
  document.dispatchEvent(new CustomEvent("royal:navigate", { detail: { name, autoLoad } }));
  if (name === "home") renderHome();
  if (name === "filme" && autoLoad) ensureFpResults();
  if (name === "serien" && autoLoad) ensureSeriesResults();
  if (name === "anime" && autoLoad && !sharedPresentation.anime.get().loaded) animeBrowse("latest", 1);
  if (name === "aniworld" && autoLoad && !sharedPresentation.aniworld.get().loaded) aniworldBrowse("catalog", 1);
  if (name !== "home") stopHomeHeroRotation();
  if (name === "filme") recheckFpInfinite();
  if (name === "serien") recheckSeriesInfinite();
  if (name === "aniworld") recheckAniworldInfinite();
}

// ── Log console ──────────────────────────────────────────────────────────
function appendLog(msg, level) {
  const el = document.getElementById("log-console");
  const low = (msg || "").toLowerCase();
  let tag = "";
  if (low.includes("fertig") || low.includes(" ok")) tag = "ok";
  else if (low.includes("fehler") || low.includes("error") || low.includes("nicht")) tag = "err";
  else if (low.includes("warn")) tag = "warn";
  const ts = new Date().toLocaleTimeString(sharedPresentation.localization.locale());
  const line = document.createElement("div");
  line.className = "log-line " + tag;
  line.translate = false;
  line.textContent = `[${ts}] ${msg}`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

// ── WebSocket ────────────────────────────────────────────────────────────
function syncQueueSnapshot(...args) { return sharedPresentation.queueSync.refresh(...args); }

function syncWatchlistSnapshot(context = "Abo-Synchronisierung", shouldApply = null) {
  return sharedPresentation.subscriptions.refresh({ shouldApply });
}

function syncMovieSubscriptions(context = "Film-Abo-Synchronisierung", shouldApply = null) {
  return sharedPresentation.movieSubscriptions.refresh({ shouldApply });
}

async function resyncAfterWsOpen({ isCurrent: isCurrentConnection }) {
  const queueSync = syncQueueSnapshot(
    "Queue-Synchronisierung nach Verbindung", isCurrentConnection,
  );
  await queueSync;
  if (!isCurrentConnection()) return;
  await Promise.allSettled([
    refreshAllCatalogJellyfinStatuses(),
    refreshSeriesJellyfinStatus(true),
    refreshFpJellyfinStatus(),
  ]);
}

function handleLiveMessage(data) {
    try {
      if (data.type === "log") {
        appendLog(data.message, data.level);
    } else if (data.type === "jellyfin_update") {
      refreshFpJellyfinStatus();
      refreshSeriesJellyfinStatus();
      refreshAllCatalogJellyfinStatuses();

      }
    } catch (error) {
      console.warn("WebSocket-Aktualisierung konnte nicht verarbeitet werden:", error);
    }
}

// ── Queue (Warteschlange, gemeinsam für Filme + Serien) ───────────────────
function showPersistenceWarning(label, persistence) {
  if (!persistence || persistence.ok !== false) return;
  const retry = persistence.pending_retry
    ? "Automatischer Speicherversuch läuft"
    : "Bitte Änderung erneut versuchen";
  setDownloadState(
    "error",
    "Speicherung ausstehend",
    `${label}: ${retry}`,
    state.download.percent,
  );
}

// Temporary adapter for classic catalogue/subscription presenters.
function renderQueue(payload) { sharedPresentation.queueView.render(payload); }
function renderQueueHistory(jobs) { sharedPresentation.queueView.renderHistory(jobs); }
function updateQueueJobProgress(jobId, job) { sharedPresentation.queueView.updateProgress(jobId, job); }

function renderSerienstreamHealth(provider) {
  const box = document.getElementById("serienstream-health");
  if (!box) return;
  const paused = ["cooldown", "probing", "blocked"].includes(provider.state);
  box.classList.toggle("hidden", !paused);
  if (!paused) return;
  const reasonLabels = {
    captcha_gate: "CAPTCHA/Rate-Limit",
    rate_limit: "Rate-Limit",
    provider_error: "Provider vorübergehend nicht erreichbar",
    probe_failed: "Testanfrage fehlgeschlagen",
  };
  const remaining = Math.max(0, Number(provider.remaining_seconds) || 0);
  const minutes = Math.max(1, Math.ceil(remaining / 60));
  const waiting = Math.max(0, Number(provider.waiting_episode_count) || 0);
  const checking = Math.max(0, Number(provider.checking_episode_count) || 0);
  const queued = Math.max(0, Number(provider.queued_fallback_episode_count) || 0);
  const activeDownloads = Math.max(0, Number(provider.active_fallback_download_count) || 0);
  const readyDownloads = Math.max(0, Number(provider.ready_fallback_download_count) || 0);
  const probeText = provider.state === "probing"
    ? "Automatischer Test läuft"
    : `Nächster automatischer Test: in ${minutes} Minuten`;
  const queueParts = [];
  if (checking) {
    queueParts.push(`${checking} ${checking === 1 ? "Episode prüft" : "Episoden prüfen"} Ersatzquellen`);
  }
  if (queued) {
    queueParts.push(`${queued} ${queued === 1 ? "Episode ist" : "Episoden sind"} vorgemerkt`);
  }
  if (activeDownloads) {
    queueParts.push(`${activeDownloads} ${activeDownloads === 1 ? "Episode lädt" : "Episoden laden"}`);
  }
  if (readyDownloads) {
    queueParts.push(`${readyDownloads} ${readyDownloads === 1 ? "Download ist" : "Downloads sind"} bereit`);
  }
  if (waiting || (!checking && !queued)) {
    queueParts.push(`${waiting} ${waiting === 1 ? "Episode wartet" : "Episoden warten"}`);
  }
  document.getElementById("serienstream-health-detail").textContent =
    `Grund: ${reasonLabels[provider.reason] || provider.reason || "Schutzsperre"} · ${probeText} · ${queueParts.join(" · ")}`;
  document.getElementById("serienstream-retry").disabled = provider.state === "probing";
}

function setQueueDockExpanded(expanded) {
  if (window.matchMedia("(max-width: 820px)").matches) return;
  const dock = document.getElementById("queue-dock");
  const drawer = document.getElementById("queue-drawer");
  const toggle = document.getElementById("queue-dock-toggle");
  dock.classList.toggle("queue-expanded", expanded);
  drawer.setAttribute("aria-hidden", String(!expanded));
  drawer.inert = !expanded;
  toggle.setAttribute("aria-expanded", String(expanded));
  toggle.querySelector(".queue-toggle-label").textContent = expanded
    ? "Downloadplan schließen"
    : "Downloadplan öffnen";
}

function toggleDesktopQueue() {
  const dock = document.getElementById("queue-dock");
  setQueueDockExpanded(!dock.classList.contains("queue-expanded"));
}

function openMobileQueue() {
  document.body.classList.add("queue-open");
  document.getElementById("mobile-queue-backdrop").setAttribute("aria-hidden", "false");
  document.getElementById("queue-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("queue-drawer").inert = false;
  document.getElementById("mobile-queue-close").focus();
}

function closeMobileQueue() {
  document.body.classList.remove("queue-open");
  document.getElementById("mobile-queue-backdrop").setAttribute("aria-hidden", "true");
  if (window.matchMedia("(max-width: 820px)").matches) {
    document.getElementById("queue-drawer").setAttribute("aria-hidden", "true");
    document.getElementById("queue-drawer").inert = true;
  }
}

function setDownloadState(kind, title, detail, percent = state.download.percent) {
  const safePercent = Number.isFinite(Number(percent)) && Number(percent) >= 0
    ? Math.max(0, Math.min(100, Number(percent))) : state.download.percent;
  state.download.active = kind === "active";
  state.download.percent = safePercent;
  const stage = document.getElementById("download-stage");
  stage.dataset.state = kind;
  document.getElementById("dl-state-icon").textContent = kind === "done" ? "✓" : kind === "active" ? "↓" : kind === "error" ? "!" : kind === "cancelled" ? "×" : "↓";
  document.getElementById("dl-state-title").textContent = title;
  document.getElementById("dl-status").textContent = detail;
  document.getElementById("dl-percent").textContent = `${Math.round(safePercent)}%`;
  document.getElementById("progress-fill").style.width = `${safePercent}%`;
  stage.querySelector(".progress-bar").setAttribute("aria-valuenow", String(Math.round(safePercent)));
  document.getElementById("mobile-queue-btn").classList.toggle("downloading", state.download.active);
  document.getElementById("cancel-btn").disabled = !state.download.active;
}

function activeMediaModal() { return sharedPresentation.modal.active(); }
function openMediaModal(id, trigger = null) { sharedPresentation.modal.open(id, trigger); }
function closeMediaModal(id, restoreFocus = true) { sharedPresentation.modal.close(id, restoreFocus); }
function closeAllMediaModals(restoreFocus = true) { sharedPresentation.modal.closeAll(restoreFocus); }
function handleMediaModalKeydown(event) { return sharedPresentation.modal.keydown(event); }

function refreshFpQueuePresentation() {
  for (const row of document.querySelectorAll("#fp-results .result-card")) {
    const slug = row.dataset.slug;
    const result = sharedPresentation.movieState.results.find((item) => item.slug === slug);
    if (!result) continue;
    const queued = state.queuedSlugs.has(slug);
    row.classList.toggle("queued", queued);
    const toggle = row.querySelector(".result-queue-toggle");
    if (toggle) {
      toggle.classList.toggle("is-queued", queued);
      toggle.textContent = queued ? "✓" : "+";
      toggle.disabled = sharedPresentation.movieDownloads.pending(slug);
      toggle.setAttribute("aria-label", queued
        ? `${result.title} aus der Queue entfernen`
        : `${result.title} zur Queue hinzufügen`);
    }
    const availability = fpResultAvailability(result);
    const status = row.querySelector(".result-card-state");
    if (status) {
      status.className = `result-card-state status-${availability.tag}`;
      status.textContent = availability.label;
    }
  }
  document.getElementById("fp-status").textContent = fpStatusMessage();
}

function refreshQueueUiAfterChange(...args) { return sharedPresentation.queueSync.acceptMutation(...args); }
