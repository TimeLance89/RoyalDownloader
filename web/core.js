const state = createInitialState();

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
const FP_METADATA_BATCH_SIZE = 4;
const FP_METADATA_BATCH_CONCURRENCY = 3;
// Auto-Nachladen beobachtet sowohl intern scrollende Desktop-Tabs als auch den
// Dokument-Viewport der mobilen Ansicht (siehe initCatalogInfiniteScroll).
// Die Konstante bleibt fuer die Retry-Button-Logik als "Auto-Nachladen
// verfuegbar" erhalten.
const catalogInfiniteObserverSupported = true;
// Erneuter Naehe-Check je Tab (nach jedem Laden aufgerufen, damit ein noch zu
// kurzer Container automatisch bis zum Fuellstand nachlaedt).
let recheckFpInfinite = () => {};
let recheckSeriesInfinite = () => {};
let watchModeContext = null;
let watchModeReturnFocus = null;
let movieSubscriptionContext = null;
let movieSubscriptionReturnFocus = null;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ── Tabs ─────────────────────────────────────────────────────────────────
function animeNavigationAvailable() {
  return state.providers.contentLanguages.has("en");
}

function syncAnimeNavigationVisibility() {
  const visible = animeNavigationAvailable();
  document.querySelectorAll(".anime-tab-button, .provider-source-lane.is-anime").forEach((element) => {
    element.classList.toggle("hidden", !visible);
  });
  const animeContent = document.getElementById("tab-anime");
  if (animeContent) animeContent.setAttribute("aria-hidden", String(!visible));
  if (!visible && state.tab === "anime") switchTab("filme");
}

function switchTab(name, { autoLoad = true } = {}) {
  if (name === "anime" && !animeNavigationAvailable()) name = "filme";
  if (state.globalSearch.active) closeGlobalSearch();
  closeAllMediaModals(false);
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-content").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  // Im Einstellungen-Bereich die Download-Sidebar ausblenden (eigener Vollbereich).
  document.body.classList.toggle("settings-active", name === "einstellungen");
  closeMobileQueue();
  if (name === "einstellungen") setQueueDockExpanded(false);
  state.tab = name;
  if (name === "bibliothek" && !state.wl.loaded) refreshWatchlist();
  if (name === "home") renderHome();
  if (name === "filme" && autoLoad) ensureFpResults();
  if (name === "serien" && autoLoad) ensureSeriesResults();
  if (name === "anime" && autoLoad && !state.anime.loaded) animeBrowse("latest", 1);
  if (name === "filme") scheduleMovieFeatureRotation();
  else stopMovieFeatureRotation();
  if (name !== "home") stopHomeHeroRotation();
  if (name === "filme") recheckFpInfinite();
  if (name === "serien") recheckSeriesInfinite();
}

// ── Log console ──────────────────────────────────────────────────────────
function appendLog(msg, level) {
  const el = document.getElementById("log-console");
  const low = (msg || "").toLowerCase();
  let tag = "";
  if (low.includes("fertig") || low.includes(" ok")) tag = "ok";
  else if (low.includes("fehler") || low.includes("error") || low.includes("nicht")) tag = "err";
  else if (low.includes("warn")) tag = "warn";
  const ts = new Date().toLocaleTimeString(i18n.locale());
  const line = document.createElement("div");
  line.className = "log-line " + tag;
  line.translate = false;
  line.textContent = `[${ts}] ${msg}`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

// ── WebSocket ────────────────────────────────────────────────────────────
let wsReconnectTimer = null;
let wsConnectionGeneration = 0;
let queueSnapshotGeneration = 0;
let watchlistSnapshotGeneration = 0;

async function syncQueueSnapshot(context = "Queue-Synchronisierung", shouldApply = null) {
  const snapshotGeneration = ++queueSnapshotGeneration;
  try {
    const [response, history] = await Promise.all([
      api.queueGet(),
      api.queueHistory(),
    ]);
    if (snapshotGeneration !== queueSnapshotGeneration || (shouldApply && !shouldApply())) return false;
    renderQueue(response.queue);
    renderQueueHistory(history.jobs || []);
    return true;
  } catch (error) {
    console.warn(`${context} fehlgeschlagen:`, error);
    return false;
  }
}

async function syncWatchlistSnapshot(context = "Abo-Synchronisierung", shouldApply = null) {
  const snapshotGeneration = ++watchlistSnapshotGeneration;
  try {
    const response = await api.watchlistGet();
    if (snapshotGeneration !== watchlistSnapshotGeneration || (shouldApply && !shouldApply())) return false;
    showPersistenceWarning("Serien-Abos", response.persistence);
    applyWatchlist(response.watchlist || []);
    return true;
  } catch (error) {
    console.warn(`${context} fehlgeschlagen:`, error);
    return false;
  }
}

async function syncMovieSubscriptions(context = "Film-Abo-Synchronisierung") {
  try {
    const response = await api.movieSubscriptionsGet();
    showPersistenceWarning("Film-Abos", response.persistence);
    applyMovieSubscriptions(response.movie_subscriptions || []);
    return true;
  } catch (error) {
    console.warn(`${context} fehlgeschlagen:`, error);
    return false;
  }
}

async function resyncAfterWsOpen(connectionGeneration) {
  const isCurrentConnection = () => connectionGeneration === wsConnectionGeneration;
  const queueSync = syncQueueSnapshot(
    "Queue-Synchronisierung nach Verbindung", isCurrentConnection,
  );
  const watchlistSync = syncWatchlistSnapshot(
    "Abo-Synchronisierung nach Verbindung", isCurrentConnection,
  );
  const movieSubscriptionSync = syncMovieSubscriptions(
    "Film-Abo-Synchronisierung nach Verbindung",
  );
  await Promise.allSettled([queueSync, watchlistSync, movieSubscriptionSync]);
  if (connectionGeneration !== wsConnectionGeneration) return;
  await Promise.allSettled([
    refreshSeriesJellyfinStatus(true),
    refreshFpJellyfinStatus(),
  ]);
}

function connectWs() {
  const connectionGeneration = ++wsConnectionGeneration;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    if (connectionGeneration !== wsConnectionGeneration) {
      ws.close();
      return;
    }
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
    resyncAfterWsOpen(connectionGeneration).catch((error) => {
      console.warn("Live-Ansicht konnte nicht vollständig synchronisiert werden:", error);
    });
  };
  ws.onmessage = (ev) => {
    let data;
    try {
      data = JSON.parse(ev.data);
    } catch (error) {
      console.warn("Ungültige WebSocket-Nachricht verworfen:", error);
      return;
    }
    try {
      if (data.type === "log") {
        appendLog(data.message, data.level);
      } else if (data.type === "progress") {
      const filePercent = Number(data.pct);
      const overallPercent = state.download.total > 0 && filePercent >= 0
        ? ((state.download.completed + filePercent / 100) / state.download.total) * 100
        : filePercent;
      const position = state.download.total
        ? `Datei ${Math.min(state.download.completed + 1, state.download.total)}/${state.download.total} · ` : "";
      setDownloadState("active", data.label || "Download läuft", `${position}${(data.msg || "").slice(0, 70)}`, overallPercent);
      if (data.job_id) updateQueueJobProgress(data.job_id, data.job || data);
    } else if (data.type === "updater_install") {
      applyUpdaterInstallStatus(data.installer || {});
    } else if (data.type === "updater_config") {
      applyUpdaterConfig(data.config || {});
    } else if (data.type === "job_done") {
      state.download.completed = data.done_jobs;
      state.download.total = data.total_jobs;
      state.download.failed = data.failed_jobs || 0;
      const percent = data.total_jobs ? (data.done_jobs / data.total_jobs) * 100 : state.download.percent;
      const moreWork = Number(data.active) + Number(data.pending) > 0;
      const kind = !data.ok && !moreWork ? "error" : "active";
      const title = data.ok ? `${data.done_jobs}/${data.total_jobs} bearbeitet` : "Download fehlgeschlagen";
      const detail = data.ok
        ? `${data.active} aktiv · ${data.pending} warten`
        : String(data.msg || "Alle Anbieter sind ausgefallen").slice(0, 110);
      setDownloadState(kind, title, detail, percent);
      syncQueueSnapshot("Queue-Aktualisierung nach Download");
      if (data.ok && data.slug) {
        markSeriesSlugDownloaded(data.slug);
        markAnimeSlugDownloaded(data.slug);
      }
    } else if (data.type === "queue_started") {
      state.download.completed = data.done_jobs;
      state.download.total = data.total_jobs;
      if (!data.done_jobs) state.download.failed = 0;
      const percent = data.total_jobs ? (data.done_jobs / data.total_jobs) * 100 : 0;
      setDownloadState("active", "Automatischer Download", `${data.done_jobs}/${data.total_jobs} fertig`, percent);
      if (data.queue) renderQueue(data.queue);
      else syncQueueSnapshot("Queue-Start-Synchronisierung");
    } else if (data.type === "queue_update") {
      if (data.queue) renderQueue(data.queue);
      else syncQueueSnapshot("Queue-Live-Synchronisierung");
    } else if (data.type === "provider_status") {
      renderSerienstreamHealth(data.provider || {});
    } else if (data.type === "queue_done") {
      state.download.completed = data.done_jobs;
      state.download.total = data.total_jobs;
      state.download.failed = data.failed_jobs || 0;
      document.getElementById("cancel-btn").disabled = true;
      if (state.download.failed) {
        const successful = data.successful_jobs || 0;
        const title = successful ? "Mit Fehlern beendet" : "Download fehlgeschlagen";
        setDownloadState("error", title,
          `${successful} erfolgreich · ${state.download.failed} fehlgeschlagen`, 100);
      } else {
        setDownloadState("done", "Abgeschlossen", `${data.done_jobs}/${data.total_jobs} Downloads fertig`, 100);
      }
      syncQueueSnapshot("Queue-Abschluss-Synchronisierung");
    } else if (data.type === "jellyfin_update") {
      refreshFpJellyfinStatus();
      refreshSeriesJellyfinStatus();
      refreshAllCatalogJellyfinStatuses();
      showPersistenceWarning("Serien-Abos", data.persistence);
      if (data.watchlist) applyWatchlist(data.watchlist);
      } else if (data.type === "watchlist_update") {
        showPersistenceWarning("Serien-Abos", data.persistence);
        applyWatchlist(data.watchlist || []);
      } else if (data.type === "movie_subscriptions_update") {
        showPersistenceWarning("Film-Abos", data.persistence);
        applyMovieSubscriptions(data.movie_subscriptions || []);
      }
    } catch (error) {
      console.warn("WebSocket-Aktualisierung konnte nicht verarbeitet werden:", error);
    }
  };
  ws.onerror = () => ws.close();
  ws.onclose = (event) => {
    if (connectionGeneration !== wsConnectionGeneration) return;
    // 1008 = der Server hat die Verbindung mangels gültiger Sitzung
    // abgewiesen. Ein Wiederverbindungsversuch im Sekundentakt würde daran
    // nichts ändern; stattdessen wird zur Anmeldung aufgefordert.
    if (event && event.code === 1008) {
      handleUnauthorized();
      return;
    }
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWs, 2000);
  };
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

function renderQueue(payload) {
  queueSnapshotGeneration += 1;
  state.queue = { ...payload, loaded: true };
  showPersistenceWarning("Downloadplan", payload.persistence);
  renderSerienstreamHealth(payload.providers?.serienstream || {});
  state.queuedSlugs = new Set();
  for (const group of payload.groups) for (const item of group.items) state.queuedSlugs.add(item.slug);
  syncSeriesQueueFlags();
  syncAnimeQueueFlags();

  const count = Number(payload.count) || 0;
  document.getElementById("queue-count").textContent = `${count} ${count === 1 ? "Eintrag" : "Einträge"}`;
  document.getElementById("mobile-queue-count").textContent = String(count);
  document.getElementById("queue-dock").classList.toggle("has-items", count > 0);
  const list = document.getElementById("queue-list");
  list.innerHTML = "";
  if (!payload.groups.length) {
    list.innerHTML = `<div class="queue-empty"><strong>Der Downloadplan ist leer</strong><span>Filme oder Episoden erscheinen hier, sobald du sie hinzufügst.</span></div>`;
  }

  let queuePosition = 0;
  for (const group of payload.groups) {
    const heading = document.createElement("div");
    heading.className = "queue-group";
    heading.translate = false;
    heading.textContent = `${group.name}  (${group.items.length})`;
    list.appendChild(heading);
    for (const item of group.items) {
      queuePosition += 1;
      const row = document.createElement("div");
      row.className = "queue-item" + (item.done ? " done" : "");
      row.dataset.jobId = item.job_id || "";
      const position = document.createElement("span");
      position.className = "queue-position";
      position.textContent = String(queuePosition).padStart(2, "0");
      const content = document.createElement("span");
      content.className = "queue-item-content";
      const title = document.createElement("strong");
      title.className = "queue-item-title";
      title.translate = false;
      title.textContent = item.title;
      const route = document.createElement("span");
      route.className = "queue-item-route";
      route.translate = false;
      const language = String(item.content_language || "").toUpperCase();
      route.textContent = [language, item.provider, item.hoster || item.hoster_label].filter(Boolean).join(" · ");
      const metrics = document.createElement("span");
      metrics.className = "queue-item-metrics";
      metrics.textContent = queueJobMetrics(item);
      const progress = document.createElement("span");
      progress.className = "queue-item-progress";
      const progressFill = document.createElement("i");
      progressFill.style.width = `${Math.max(0, Math.min(100, Number(item.progress) || 0))}%`;
      progress.appendChild(progressFill);
      content.append(title, route, metrics, progress);

      const status = document.createElement("span");
      status.className = "queue-item-status";
      const statusLabels = {
        queued: "Wartet", preparing: "Prüft Quelle", waiting_provider: "Provider-Pause",
        downloading: "Lädt", paused: "Pausiert", cancelling: "Wird abgebrochen",
      };
      status.textContent = statusLabels[item.job_status] || statusLabels[item.status] || "Wartet";
      const actions = document.createElement("span");
      actions.className = "queue-item-actions";
      const addAction = (text, label, handler) => {
        const button = document.createElement("button");
        button.className = "queue-action-btn";
        button.type = "button";
        button.textContent = text;
        button.setAttribute("aria-label", label);
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            const response = await handler();
            if (response.queue) renderQueue(response.queue);
            const history = await api.queueHistory();
            renderQueueHistory(history.jobs || []);
          } catch (error) {
            console.warn("Queue-Aktion fehlgeschlagen:", error);
            button.disabled = false;
          }
        });
        actions.appendChild(button);
      };
      if (item.job_id && !["downloading", "cancelling"].includes(item.job_status)) {
        addAction("↑", `${item.title} nach oben`, () => api.queueJobMove(item.job_id, "up"));
        addAction("↓", `${item.title} nach unten`, () => api.queueJobMove(item.job_id, "down"));
      }
      if (item.job_id && item.job_status === "waiting_provider") {
        addAction("▶", `${item.title} fortsetzen`, () => api.queueJobResume(item.job_id));
      }
      if (item.job_status !== "cancelling") {
        addAction("✕", `${item.title} abbrechen`, () => (
          item.job_id ? api.queueJobCancel(item.job_id) : api.queueRemove(item.slug)
        ));
      }
      row.append(position, content, status, actions);
      list.appendChild(row);
    }
  }
  syncFpQueueIndicators();

  const activity = payload.activity || {};
  const activeDownloads = Math.max(0, Number(activity.active_downloads) || 0);
  const activePreparations = Math.max(0, Number(activity.active_preparations) || 0);
  const pendingPreparations = Math.max(0, Number(activity.pending_preparations) || 0);
  const pendingDownloads = Math.max(0, Number(activity.pending_downloads) || 0);
  const downloadStage = document.getElementById("download-stage");
  const hasLiveProgress = downloadStage?.dataset.state === "active"
    && document.getElementById("dl-state-title")?.textContent !== "Bereit";
  if (activeDownloads && !hasLiveProgress) {
    setDownloadState("active", activeDownloads === 1 ? "Download läuft" : `${activeDownloads} Downloads laufen`,
      pendingDownloads ? `${pendingDownloads} weiterer Download ist bereit` : "Stream geladen · Download aktiv",
      state.download.percent);
  } else if (!activeDownloads && activePreparations) {
    const paused = ["cooldown", "probing", "blocked"].includes(payload.providers?.serienstream?.state);
    setDownloadState("active", paused ? "Ersatzquelle wird gesucht" : "Quelle wird geprüft",
      `${activePreparations} aktiv · ${pendingPreparations} Folgen vorgemerkt`, state.download.percent);
  } else if (!activeDownloads && !activePreparations && pendingPreparations) {
    setDownloadState("active", "Fallback-Warteschlange läuft",
      `${pendingPreparations} Folgen werden nacheinander geprüft`, state.download.percent);
  }
}

function formatQueueBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (!bytes) return "";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${Math.round(bytes / 1024)} KiB`;
}

function queueJobMetrics(job) {
  const parts = [];
  const downloaded = formatQueueBytes(job.downloaded_bytes);
  const total = formatQueueBytes(job.total_bytes);
  if (downloaded) parts.push(total ? `${downloaded} / ${total}` : downloaded);
  const speed = formatQueueBytes(job.speed_bps);
  if (speed) parts.push(`${speed}/s`);
  const eta = Number(job.eta_seconds);
  if (Number.isFinite(eta) && eta > 0) parts.push(`ETA ${Math.ceil(eta / 60)} Min.`);
  return parts.join(" · ");
}

function updateQueueJobProgress(jobId, job) {
  const row = [...document.querySelectorAll(".queue-item")]
    .find((item) => item.dataset.jobId === String(jobId));
  if (!row) return;
  const fill = row.querySelector(".queue-item-progress i");
  if (fill) fill.style.width = `${Math.max(0, Math.min(100, Number(job.progress ?? job.pct) || 0))}%`;
  const metrics = row.querySelector(".queue-item-metrics");
  if (metrics) metrics.textContent = queueJobMetrics(job);
  const status = row.querySelector(".queue-item-status");
  if (status) status.textContent = "Lädt";
}

function renderQueueHistory(jobs) {
  const list = document.getElementById("queue-history-list");
  const count = document.getElementById("queue-history-count");
  if (!list || !count) return;
  count.textContent = String(jobs.length);
  list.innerHTML = "";
  if (!jobs.length) {
    list.innerHTML = '<div class="queue-empty">Noch keine abgeschlossenen Downloads.</div>';
    return;
  }
  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = `queue-history-item status-${job.status}`;
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = job.title || job.slug;
    const detail = document.createElement("small");
    const statusLabel = { completed: "Abgeschlossen", failed: "Fehlgeschlagen", cancelled: "Abgebrochen" }[job.status] || job.status;
    detail.textContent = [statusLabel, job.error, job.final_path].filter(Boolean).join(" · ");
    copy.append(title, detail);
    row.appendChild(copy);
    if (["failed", "cancelled"].includes(job.status)) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "queue-action-btn queue-retry-btn";
      retry.textContent = "Retry";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        try {
          const response = await api.queueJobRetry(job.job_id);
          renderQueue(response.queue);
          const history = await api.queueHistory();
          renderQueueHistory(history.jobs || []);
        } catch (error) {
          console.warn("Retry fehlgeschlagen:", error);
          retry.disabled = false;
        }
      });
      row.appendChild(retry);
    }
    list.appendChild(row);
  }
}

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
  toggle.setAttribute("aria-expanded", String(expanded));
  toggle.querySelector(".queue-toggle-label").textContent = expanded ? "Queue schließen" : "Queue öffnen";
}

function toggleDesktopQueue() {
  const dock = document.getElementById("queue-dock");
  setQueueDockExpanded(!dock.classList.contains("queue-expanded"));
}

function openMobileQueue() {
  document.body.classList.add("queue-open");
  document.getElementById("mobile-queue-backdrop").setAttribute("aria-hidden", "false");
  document.getElementById("queue-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("mobile-queue-close").focus();
}

function closeMobileQueue() {
  document.body.classList.remove("queue-open");
  document.getElementById("mobile-queue-backdrop").setAttribute("aria-hidden", "true");
  if (window.matchMedia("(max-width: 820px)").matches) {
    document.getElementById("queue-drawer").setAttribute("aria-hidden", "true");
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

function activeMediaModal() {
  return document.querySelector(".media-modal.is-open:not([hidden])");
}

function openMediaModal(modalId, trigger = null) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  const current = activeMediaModal();
  if (current && current !== modal) closeMediaModal(current.id, false);
  if (!modal.hidden && modal.classList.contains("is-open")) return;
  modal._returnFocus = trigger instanceof HTMLElement ? trigger : document.activeElement;
  modal.hidden = false;
  modal.classList.add("is-open");
  document.body.classList.add("media-modal-open");
  const scrollContainers = modal.querySelectorAll(
    ".media-modal-panel, .detail-body, .tiles-scroll, .anime-detail-content",
  );
  scrollContainers.forEach((element) => { element.scrollTop = 0; element.scrollLeft = 0; });
  requestAnimationFrame(() => {
    scrollContainers.forEach((element) => { element.scrollTop = 0; element.scrollLeft = 0; });
    modal.querySelector(".media-modal-close")?.focus();
  });
}

function closeMediaModal(modalId, restoreFocus = true) {
  const modal = document.getElementById(modalId);
  if (!modal || modal.hidden) return;
  if (modalId === "fp-detail-modal") {
    closeFpTrailerModal(false);
    stopFpDetailHeroTrailer();
  } else if (modalId === "series-detail-modal") {
    closeFpTrailerModal(false);
    stopSeriesDetailHeroTrailer();
  }
  const returnFocus = modal._returnFocus;
  modal.classList.remove("is-open");
  modal.hidden = true;
  if (!activeMediaModal()) document.body.classList.remove("media-modal-open");
  const resumedMood = restoreFocus
    && typeof resumeMoodMatchAfterDetail === "function"
    && resumeMoodMatchAfterDetail();
  if (!resumedMood && restoreFocus && returnFocus instanceof HTMLElement && returnFocus.isConnected) {
    returnFocus.focus();
  }
}

function closeAllMediaModals(restoreFocus = true) {
  closeFpTrailerModal(false);
  document.querySelectorAll(".media-modal:not([hidden])").forEach((modal) => {
    closeMediaModal(modal.id, restoreFocus);
  });
}

function handleMediaModalKeydown(event) {
  const trailerModal = document.getElementById("fp-trailer-modal");
  if (trailerModal && !trailerModal.hidden) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeFpTrailerModal();
      return true;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      document.getElementById("fp-trailer-close")?.focus();
    }
    return true;
  }
  const modal = activeMediaModal();
  if (!modal) return false;
  if (event.key === "Escape") {
    event.preventDefault();
    closeMediaModal(modal.id);
    return true;
  }
  if (event.key !== "Tab") return false;
  const focusable = [...modal.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((element) => !element.hidden && element.getClientRects().length);
  if (!focusable.length) {
    event.preventDefault();
    modal.querySelector(".media-modal-panel")?.focus();
    return true;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
  return true;
}

function refreshQueueUiAfterChange(resp) {
  renderQueue(resp.queue);
  api.queueHistory()
    .then((history) => renderQueueHistory(history.jobs || []))
    .catch((error) => console.warn("Downloadhistorie konnte nicht aktualisiert werden:", error));
  if (resp.auto_started) {
    state.download.completed = resp.done_jobs;
    state.download.total = resp.total_jobs;
    const percent = resp.total_jobs ? (resp.done_jobs / resp.total_jobs) * 100 : 0;
    setDownloadState("active", "Automatischer Download", `${resp.done_jobs}/${resp.total_jobs} fertig`, percent);
  }
  renderFpResults();
  renderSeriesTiles();
}
