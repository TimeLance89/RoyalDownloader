const state = {
  tab: "home",
  globalSearch: {
    query: "", results: [], active: false, loading: false,
    requestSeq: 0, debounceTimer: null,
  },
  home: {
    newMovies: [], topMovies: [], trendingSeries: [], newSeries: [],
    discoveryMovies: [], discoverySeries: [],
    heroIndex: 0, heroTimer: null, loading: true, discoveryDay: "",
    search: { scope: "all", query: "", results: [], active: false, loading: false, requestSeq: 0 },
  },
  fp: {
    results: [], moviesCache: {}, category: null, page: 1, lastPageFull: false,
    activeGenre: "Alle Genres", selectedSlug: null, pendingPreload: null,
    metadataCache: {}, requestSeq: 0, sources: [],
    loadingMore: false, loadError: "",
    searchActive: false, searchReturn: null,
    featureCandidates: [], featureIndex: 0, featureTimer: null, featurePaused: false,
    downloadSelections: new Map(),
  },
  series: {
    results: [], browseMode: null, page: 1, lastPageFull: false,
    sources: [], browseRequestSeq: 0, loadingBrowse: false, loadError: "",
    current: null, currentSampleSlug: "", epPicked: new Set(),
    cache: {}, pendingBaseSlug: "", requestSeq: 0, viewGeneration: 0,
    jellyfinRefreshSeq: 0, jellyfinRefreshByBase: new Map(),
    searchReturn: null,
  },
  anime: {
    results: [], mode: null, query: "", page: 1, hasMore: false,
    loaded: false, loading: false, requestSeq: 0, detailSeq: 0,
    currentId: "", current: null, translation: "", episodePage: 1,
    picked: new Set(),
    searchReturn: null,
  },
  wl: { items: [], selected: new Set(), loaded: false },
  movieSubscriptions: { items: [], loaded: false },
  queue: { count: 0, groups: [], loaded: false },
  download: { active: false, percent: 0, completed: 0, total: 0, failed: 0 },
  providers: {
    movies: [],
    series: [],
    anime: [],
    labels: {},
    catalog: {},
    languages: {},
    contentLanguages: new Set(),
    enabledMovies: new Set(),
    enabledSeries: new Set(),
    enabledAnime: new Set(),
  },
  queuedSlugs: new Set(),
  jellyfinUserConfigured: false,
  watchlistCleanupDefault: "keep",
};

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
// Auto-Nachladen ist ueber einen simplen Scroll-Listener am tatsaechlichen
// Scroll-Container geloest (siehe initCatalogInfiniteScroll). Das funktioniert
// in allen Zielbrowsern; die Konstante bleibt fuer die Retry-Button-Logik als
// "Auto-Nachladen verfuegbar" erhalten.
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

// ── Anmeldung ────────────────────────────────────────────────────────────
// Ein einziges Administratorkonto, Sitzung über ein HttpOnly-Cookie. Die
// Maske blockiert den Start der Oberfläche, solange keine gültige Sitzung
// besteht; laeuft eine Sitzung waehrend der Nutzung ab, kommt sie erneut.
let authStatus = { configured: false, authenticated: true, prompt_setup: false };
let loginResolve = null;
let loginVisible = false;

function setLoginStatus(message = "", error = false) {
  const el = document.getElementById("login-status");
  el.textContent = message;
  el.classList.toggle("error", !!error);
}

function showLoginScreen({ expired = false } = {}) {
  const screen = document.getElementById("login-screen");
  if (loginVisible) return;
  loginVisible = true;
  document.body.classList.add("login-open");
  screen.classList.remove("hidden");
  setLoginStatus(expired ? "Die Sitzung ist abgelaufen. Bitte erneut anmelden." : "", expired);
  const username = document.getElementById("login-username");
  const password = document.getElementById("login-password");
  password.value = "";
  window.setTimeout(() => (username.value.trim() ? password : username).focus(), 60);
}

function hideLoginScreen() {
  loginVisible = false;
  document.body.classList.remove("login-open");
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("login-password").value = "";
  setLoginStatus();
}

async function submitLogin(event) {
  if (event) event.preventDefault();
  const button = document.getElementById("login-submit");
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  if (!username || !password) {
    setLoginStatus("Benutzername und Passwort werden benötigt.", true);
    return;
  }
  button.disabled = true;
  setLoginStatus("Anmeldung läuft …");
  try {
    authStatus = await api.authLogin(username, password);
    hideLoginScreen();
    if (loginResolve) {
      // Anmeldung beim Start: der reguläre Startablauf läuft danach weiter.
      const resolve = loginResolve;
      loginResolve = null;
      resolve();
    } else {
      // Abgelaufene Sitzung mitten im Betrieb: neu laden ist der einzige
      // Weg, der jeden Teilzustand (Queue, Katalog, Abos) zuverlässig wieder
      // in Übereinstimmung mit dem Server bringt.
      location.reload();
    }
  } catch (error) {
    setLoginStatus(error.message, true);
    document.getElementById("login-password").select();
  } finally {
    button.disabled = false;
  }
}

function handleUnauthorized() {
  if (loginVisible || setupRequired) return;
  showLoginScreen({ expired: true });
}

async function requireLogin() {
  try {
    authStatus = await api.authStatus();
  } catch (error) {
    // Server nicht erreichbar: die Oberfläche startet trotzdem und zeigt den
    // Fehler an der jeweiligen Stelle an, statt hier hängen zu bleiben.
    console.warn("Anmeldestatus konnte nicht geprüft werden:", error);
    return;
  }
  if (!authStatus.configured || authStatus.authenticated) return;
  showLoginScreen();
  await new Promise((resolve) => { loginResolve = resolve; });
}

function initLoginScreen() {
  api.onUnauthorized = handleUnauthorized;
  document.getElementById("login-form").addEventListener("submit", submitLogin);
  document.getElementById("login-password-toggle").addEventListener("click", (event) => {
    const button = event.currentTarget;
    const password = document.getElementById("login-password");
    const visible = password.type === "text";
    password.type = visible ? "password" : "text";
    button.setAttribute("aria-pressed", String(!visible));
    button.setAttribute("aria-label", visible ? "Passwort anzeigen" : "Passwort verbergen");
    password.focus();
  });
}

// ── WebSocket ────────────────────────────────────────────────────────────
let wsReconnectTimer = null;
let wsConnectionGeneration = 0;
let queueSnapshotGeneration = 0;
let watchlistSnapshotGeneration = 0;

async function syncQueueSnapshot(context = "Queue-Synchronisierung", shouldApply = null) {
  const snapshotGeneration = ++queueSnapshotGeneration;
  try {
    const response = await api.queueGet();
    if (snapshotGeneration !== queueSnapshotGeneration || (shouldApply && !shouldApply())) return false;
    renderQueue(response.queue);
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
  for (const g of payload.groups) for (const it of g.items) state.queuedSlugs.add(it.slug);
  syncSeriesQueueFlags();
  syncAnimeQueueFlags();

  const count = Number(payload.count) || 0;
  document.getElementById("queue-count").textContent =
    `${count} ${count === 1 ? "Eintrag" : "Einträge"}`;
  document.getElementById("mobile-queue-count").textContent = String(count);
  document.getElementById("queue-dock").classList.toggle("has-items", count > 0);

  const list = document.getElementById("queue-list");
  list.innerHTML = "";
  if (!payload.groups.length) {
    list.innerHTML = `<div class="queue-empty"><strong>Der Downloadplan ist leer</strong><span>Filme oder Episoden erscheinen hier, sobald du sie hinzufügst.</span></div>`;
    syncFpQueueIndicators();
    return;
  }

  let queuePosition = 0;
  for (const g of payload.groups) {
    const gEl = document.createElement("div");
    gEl.className = "queue-group";
    gEl.translate = false;
    gEl.textContent = `${g.name}  (${g.items.length})`;
    list.appendChild(gEl);
    for (const it of g.items) {
      queuePosition += 1;
      const row = document.createElement("div");
      row.className = "queue-item" + (it.done ? " done" : "");
      const position = document.createElement("span");
      position.className = "queue-position";
      position.textContent = String(queuePosition).padStart(2, "0");
      const content = document.createElement("span");
      content.className = "queue-item-content";
      const label = document.createElement("strong");
      label.className = "queue-item-title";
      label.translate = false;
      label.textContent = it.title;
      const route = document.createElement("span");
      route.className = "queue-item-route";
      route.translate = false;
      const language = String(it.content_language || "").toUpperCase();
      route.textContent = [language, it.hoster_label].filter(Boolean).join(" · ");
      content.append(label, route);
      const status = document.createElement("span");
      status.className = "queue-item-status";
      status.textContent = it.done
        ? "Fertig"
        : (it.status === "downloading"
          ? "Lädt"
          : (it.status === "download_ready"
            ? "Download bereit"
          : (it.status === "waiting_provider"
          ? "Provider-Pause"
          : (it.status === "checking_fallback"
            ? "Prüft Ersatz"
            : (it.status === "preparing_source"
              ? "Prüft Quelle"
              : (it.status === "queued_fallback" ? "Fallback vorgemerkt" : "Wartet"))))));
      const removeBtn = document.createElement("button");
      removeBtn.className = "remove-btn";
      removeBtn.type = "button";
      removeBtn.textContent = "✕";
      removeBtn.setAttribute("aria-label", `${it.title} aus der Queue entfernen`);
      removeBtn.addEventListener("click", async () => {
        removeBtn.disabled = true;
        try {
          const resp = await api.queueRemove(it.slug);
          renderQueue(resp.queue);
        } catch (error) {
          console.warn("Queue-Eintrag konnte nicht entfernt werden:", error);
          removeBtn.disabled = false;
        }
      });
      row.append(position, content, status, removeBtn);
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
    setDownloadState(
      "active",
      activeDownloads === 1 ? "Download läuft" : `${activeDownloads} Downloads laufen`,
      pendingDownloads
        ? `${pendingDownloads} weiterer Download ist bereit`
        : "Stream geladen · Download aktiv",
      state.download.percent,
    );
  } else if (!activeDownloads && activePreparations) {
    const serienstreamPaused = ["cooldown", "probing", "blocked"].includes(
      payload.providers?.serienstream?.state,
    );
    setDownloadState(
      "active",
      serienstreamPaused ? "Ersatzquelle wird gesucht" : "Quelle wird geprüft",
      `${activePreparations} aktiv · ${pendingPreparations} Folgen vorgemerkt`,
      state.download.percent,
    );
  } else if (!activeDownloads && !activePreparations && pendingPreparations) {
    setDownloadState(
      "active",
      "Fallback-Warteschlange läuft",
      `${pendingPreparations} Folgen werden nacheinander geprüft`,
      state.download.percent,
    );
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
  if (restoreFocus && returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus();
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
  if (resp.auto_started) {
    state.download.completed = resp.done_jobs;
    state.download.total = resp.total_jobs;
    const percent = resp.total_jobs ? (resp.done_jobs / resp.total_jobs) * 100 : 0;
    setDownloadState("active", "Automatischer Download", `${resp.done_jobs}/${resp.total_jobs} fertig`, percent);
  }
  renderFpResults();
  renderSeriesTiles();
}

// ── Filme-Tab ──────────────────────────────────────────────────────────────
const MOVIE_FEATURE_INTERVAL_MS = 9000;
const MOVIE_FEATURE_MAX_AGE_DAYS = 270;
const MOVIE_FEATURE_MAX_FUTURE_DAYS = 45;

function movieFeatureCandidate(result) {
  const metadata = state.fp.metadataCache[result.slug] || {};
  const backdrop = metadata.backdrop_url || result.backdrop_url || "";
  const cover = metadata.cover_url || result.cover_url || "";
  const artwork = backdrop || cover;

  const now = new Date();
  const release = metadata.release_date ? new Date(`${metadata.release_date}T12:00:00`) : null;
  let ageDays = null;
  if (release && !Number.isNaN(release.getTime())) {
    ageDays = (now.getTime() - release.getTime()) / 86400000;
    if (ageDays > MOVIE_FEATURE_MAX_AGE_DAYS || ageDays < -MOVIE_FEATURE_MAX_FUTURE_DAYS) {
      return null;
    }
  } else {
    const year = Number(metadata.year || result.year) || 0;
    if (year && year < now.getFullYear() - 1) return null;
  }

  const year = Number(metadata.year || result.year) || 0;
  const rating = Number(metadata.rating) || 0;
  const votes = Number(metadata.vote_count) || 0;
  const recencyScore = ageDays == null
    ? (year === now.getFullYear() ? 36 : (year === now.getFullYear() - 1 ? 20 : 26))
    : (ageDays >= 0 ? 70 - Math.min(ageDays, 365) * 0.1 : 54 - Math.abs(ageDays) * 0.2);
  const score = recencyScore
    + rating * 2
    + Math.min(14, Math.log10(votes + 1) * 3)
    + (backdrop ? 24 : 8)
    + (metadata.description ? 7 : 0);
  return {
    ...result,
    ...metadata,
    artwork,
    artworkKind: backdrop ? "backdrop" : (cover ? "poster" : "none"),
    featureScore: score,
  };
}

function stopMovieFeatureRotation() {
  if (!state.fp.featureTimer) return;
  clearInterval(state.fp.featureTimer);
  state.fp.featureTimer = null;
}

function scheduleMovieFeatureRotation() {
  stopMovieFeatureRotation();
  const feature = document.getElementById("movie-feature");
  if (
    !feature
    || feature.classList.contains("hidden")
    || state.tab !== "filme"
    || state.fp.featurePaused
    || state.fp.featureCandidates.length < 2
    || feature.matches(":hover")
    || feature.contains(document.activeElement)
    || document.hidden
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) return;
  state.fp.featureTimer = window.setInterval(() => {
    showMovieFeature(state.fp.featureIndex + 1);
  }, MOVIE_FEATURE_INTERVAL_MS);
}

function setMovieFeaturePaused(paused) {
  state.fp.featurePaused = paused;
  const button = document.getElementById("movie-feature-pause");
  if (button) {
    button.textContent = paused ? "▶" : "Ⅱ";
    button.setAttribute("aria-label", paused ? "Rotation fortsetzen" : "Rotation pausieren");
    button.setAttribute("aria-pressed", String(paused));
  }
  if (paused) stopMovieFeatureRotation();
  else scheduleMovieFeatureRotation();
}

function movieFeatureDate(candidate) {
  if (!candidate.release_date) return candidate.year || "";
  const date = new Date(`${candidate.release_date}T12:00:00`);
  if (Number.isNaN(date.getTime())) return candidate.year || "";
  return date.toLocaleDateString(i18n.locale(), {
    day: "2-digit", month: "short", year: "numeric",
  });
}

function renderMovieFeature() {
  const feature = document.getElementById("movie-feature");
  const candidates = state.fp.featureCandidates;
  const candidate = candidates[state.fp.featureIndex];
  if (!feature || !candidate) {
    feature?.classList.add("hidden");
    stopMovieFeatureRotation();
    return;
  }

  feature.classList.remove("hidden");
  feature.classList.toggle("is-poster-art", candidate.artworkKind === "poster");
  feature.classList.toggle("has-no-art", candidate.artworkKind === "none");
  feature.setAttribute("aria-label", `Aktuelle Kinofilme: ${candidate.title}`);
  document.getElementById("movie-feature-art").style.backgroundImage = candidate.artwork
    ? `url("${api.coverUrl(candidate.artwork).replace(/"/g, "%22")}")`
    : "";
  document.getElementById("movie-feature-title").textContent = candidate.title;
  document.getElementById("movie-feature-count").textContent =
    `${state.fp.featureIndex + 1} / ${candidates.length}`;
  document.getElementById("movie-feature-description").textContent =
    candidate.description || "Neu bei deinen ausgewählten Filmquellen.";
  const provider = state.providers.labels[candidate.provider] || "";
  document.getElementById("movie-feature-meta").textContent = [
    movieFeatureDate(candidate),
    candidate.rating ? `★ ${candidate.rating}` : "",
    ...(candidate.genres || []).slice(0, 2),
    provider,
  ].filter(Boolean).join(" · ");
  document.getElementById("movie-feature-open").dataset.slug = candidate.slug;

  const dots = document.getElementById("movie-feature-dots");
  dots.innerHTML = "";
  candidates.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = index === state.fp.featureIndex ? "is-active" : "";
    button.setAttribute("aria-label", `${item.title} anzeigen`);
    button.setAttribute("aria-pressed", String(index === state.fp.featureIndex));
    button.addEventListener("click", () => {
      showMovieFeature(index, true);
      scheduleMovieFeatureRotation();
    });
    dots.appendChild(button);
  });
}

function showMovieFeature(index, userInitiated = false) {
  const count = state.fp.featureCandidates.length;
  if (!count) return;
  state.fp.featureIndex = ((index % count) + count) % count;
  const feature = document.getElementById("movie-feature");
  if (!userInitiated && feature) {
    feature.classList.add("is-changing");
    window.setTimeout(() => feature.classList.remove("is-changing"), 360);
  }
  renderMovieFeature();
}

function refreshMovieFeatureCandidates() {
  if (state.fp.category !== "new") {
    document.getElementById("movie-feature")?.classList.add("hidden");
    stopMovieFeatureRotation();
    return;
  }
  const currentSlug = state.fp.featureCandidates[state.fp.featureIndex]?.slug;
  const seenTitles = new Set();
  const allCandidates = state.fp.results
    .map(movieFeatureCandidate)
    .filter(Boolean)
    .sort((a, b) => b.featureScore - a.featureScore)
    .filter((candidate) => {
      const key = String(candidate.title || "").trim().toLocaleLowerCase();
      if (!key || seenTitles.has(key)) return false;
      seenTitles.add(key);
      return true;
    });
  const artworkCandidates = allCandidates.filter((candidate) => candidate.artwork);
  const candidates = (artworkCandidates.length ? artworkCandidates : allCandidates).slice(0, 5);
  state.fp.featureCandidates = candidates;
  const preservedIndex = candidates.findIndex((candidate) => candidate.slug === currentSlug);
  state.fp.featureIndex = preservedIndex >= 0 ? preservedIndex : 0;
  renderMovieFeature();
  scheduleMovieFeatureRotation();
  renderHomeHero();
}

function homeMovieBySlug(slug) {
  return [
    ...state.home.newMovies,
    ...state.home.topMovies,
    ...state.home.discoveryMovies,
    ...state.home.search.results.filter((entry) => entry.kind === "movie").map((entry) => entry.item),
    ...state.globalSearch.results.filter((entry) => entry.kind === "movie").map((entry) => entry.item),
  ]
    .find((item) => item.slug === slug) || null;
}

function homeSeriesBySlug(baseSlug) {
  return [
    ...state.home.trendingSeries,
    ...state.home.newSeries,
    ...state.home.discoverySeries,
    ...state.home.search.results.filter((entry) => entry.kind === "series").map((entry) => entry.item),
    ...state.globalSearch.results.filter((entry) => entry.kind === "series").map((entry) => entry.item),
  ]
    .find((item) => item.base_slug === baseSlug) || null;
}

function uniqueHomeEntries(entries) {
  const seen = new Set();
  return entries.filter((entry) => {
    if (!entry?.item) return false;
    const key = `${entry.kind}:${entry.kind === "movie" ? entry.item.slug : entry.item.base_slug}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function interleaveHomeEntries(primary, secondary, limit = 20) {
  const mixed = [];
  const max = Math.max(primary.length, secondary.length);
  for (let index = 0; index < max && mixed.length < limit; index += 1) {
    if (primary[index]) mixed.push(primary[index]);
    if (secondary[index] && mixed.length < limit) mixed.push(secondary[index]);
  }
  return uniqueHomeEntries(mixed).slice(0, limit);
}

function homeMovieEntry(item) {
  return { kind: "movie", item };
}

function homeSeriesEntry(item) {
  return { kind: "series", item };
}

const HOME_DISCOVERY_PROFILE_KEY = "royal-discovery-profile-v1";
const HOME_WEEKLY_TOP_KEY = "royal-home-weekly-top-v1";

function homeEntryKey(entry) {
  if (!entry?.item) return "";
  return `${entry.kind}:${entry.kind === "movie" ? entry.item.slug : entry.item.base_slug}`;
}

function homeEntryMedia(entry) {
  if (!entry?.item) return {};
  const metadata = entry.kind === "movie"
    ? (state.fp.metadataCache[entry.item.slug] || {})
    : {};
  return { ...entry.item, ...metadata };
}

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localWeekKey(date = new Date()) {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const weekday = monday.getDay() || 7;
  monday.setDate(monday.getDate() - weekday + 1);
  return localDateKey(monday);
}

function stableDiscoveryHash(value) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function stableDailyOrder(entries, lane) {
  const seed = `${localDateKey()}|${lane}`;
  return entries.slice().sort((a, b) =>
    stableDiscoveryHash(`${seed}|${homeEntryKey(a)}`)
    - stableDiscoveryHash(`${seed}|${homeEntryKey(b)}`));
}

function loadDiscoveryProfile() {
  let profile = null;
  try {
    profile = JSON.parse(localStorage.getItem(HOME_DISCOVERY_PROFILE_KEY) || "null");
  } catch {
    profile = null;
  }
  if (!profile || typeof profile !== "object") {
    profile = { genres: {}, kinds: {}, dimensions: {}, recent: [], blocked_items: [], item_feedback: {}, interactions: 0, updatedAt: Date.now() };
  }
  profile.genres = profile.genres && typeof profile.genres === "object" ? profile.genres : {};
  profile.kinds = profile.kinds && typeof profile.kinds === "object" ? profile.kinds : {};
  profile.dimensions = profile.dimensions && typeof profile.dimensions === "object" ? profile.dimensions : {};
  profile.blocked_items = Array.isArray(profile.blocked_items) ? profile.blocked_items : [];
  profile.item_feedback = profile.item_feedback && typeof profile.item_feedback === "object" ? profile.item_feedback : {};
  profile.recent = Array.isArray(profile.recent) ? profile.recent.slice(0, 60) : [];
  profile.interactions = Number(profile.interactions || 0);
  const elapsedDays = Math.floor((Date.now() - Number(profile.updatedAt || Date.now())) / 86400000);
  if (elapsedDays > 0 && !Object.keys(profile.dimensions).length) {
    const factor = Math.pow(0.985, Math.min(elapsedDays, 120));
    Object.keys(profile.genres).forEach((genre) => {
      profile.genres[genre] = Number(profile.genres[genre] || 0) * factor;
    });
    Object.keys(profile.kinds).forEach((kind) => {
      profile.kinds[kind] = Number(profile.kinds[kind] || 0) * factor;
    });
    profile.updatedAt = Date.now();
    saveDiscoveryProfile(profile);
  }
  return profile;
}

function saveDiscoveryProfile(profile) {
  try {
    localStorage.setItem(HOME_DISCOVERY_PROFILE_KEY, JSON.stringify(profile));
  } catch {
    // Private Modi können lokalen Speicher blockieren; Entdecken bleibt nutzbar.
  }
}

function applyServerTasteProfile(serverProfile) {
  if (!serverProfile || typeof serverProfile !== "object") return loadDiscoveryProfile();
  const profile = {
    ...serverProfile,
    genres: serverProfile.genres || serverProfile.dimensions?.genres || {},
    kinds: serverProfile.kinds || serverProfile.dimensions?.media_types || {},
    dimensions: serverProfile.dimensions || {},
    recent: Array.isArray(serverProfile.recent) ? serverProfile.recent : [],
    blocked_items: Array.isArray(serverProfile.blocked_items) ? serverProfile.blocked_items : [],
    item_feedback: serverProfile.item_feedback || {},
    interactions: Number(serverProfile.interactions || 0),
    updatedAt: Number(serverProfile.updated_at || 0) * 1000 || Date.now(),
  };
  saveDiscoveryProfile(profile);
  renderTasteProfileSummary(profile);
  updateTasteFeedbackButtons();
  return profile;
}

async function syncTasteProfile() {
  const localProfile = loadDiscoveryProfile();
  try {
    let serverProfile = await api.tasteProfile();
    if (!serverProfile.legacy_imported && localProfile.interactions > 0) {
      const imported = await api.tasteImport({
        genres: localProfile.genres || {},
        kinds: localProfile.kinds || {},
      });
      serverProfile = imported.profile || serverProfile;
    }
    applyServerTasteProfile(serverProfile);
    if (state.tab === "home") renderHome();
  } catch (error) {
    console.warn("Geschmacksprofil konnte nicht synchronisiert werden:", error);
    renderTasteProfileSummary(localProfile, true);
  }
}

function tasteMetadata(kind, item = {}) {
  const cast = (item.cast || []).map((person) => typeof person === "string" ? person : person?.name).filter(Boolean);
  return {
    genres: item.genres || [],
    tags: item.keywords || item.tags || [],
    studios: item.production_companies || item.studios || [],
    directors: item.directors || [],
    actors: cast,
    languages: item.spoken_languages || item.languages || item.content_language || [],
    year: item.year || item.release_date || "",
    runtime: item.runtime || "",
    media_type: kind,
  };
}

function renderTasteProfileSummary(profile = loadDiscoveryProfile(), offline = false) {
  const target = document.getElementById("taste-profile-summary");
  if (!target) return;
  const favorites = Object.entries(profile.genres || {})
    .filter(([, score]) => Number(score) > .25)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 5)
    .map(([name]) => name);
  const learned = Number(profile.interactions || 0);
  target.textContent = learned
    ? `${learned} Signale${favorites.length ? ` · Besonders: ${favorites.join(", ")}` : ""}${offline ? " · nur lokaler Stand" : ""}`
    : "Noch neutral – Royal lernt erst durch deine Bedienung.";
}

function currentTasteTarget(kind) {
  if (kind === "movie") {
    const slug = state.fp.selectedSlug || "";
    const item = {
      ...(homeMovieBySlug(slug) || {}),
      ...(state.fp.moviesCache[slug] || {}),
      ...(state.fp.metadataCache[slug] || {}),
      slug,
    };
    return slug ? { key: `movie:${slug}`, item } : null;
  }
  const item = state.series.current;
  return item?.base_slug ? { key: `series:${item.base_slug}`, item } : null;
}

function updateTasteFeedbackButtons() {
  const profile = loadDiscoveryProfile();
  for (const [kind, prefix] of [["movie", "fp"], ["series", "series"]]) {
    const target = currentTasteTarget(kind);
    const action = target ? profile.item_feedback?.[target.key] : "";
    const like = document.getElementById(`${prefix}-taste-like`);
    const dislike = document.getElementById(`${prefix}-taste-dislike`);
    if (!like || !dislike) continue;
    like.disabled = !target;
    dislike.disabled = !target;
    like.setAttribute("aria-pressed", String(action === "like" || action === "favorite"));
    dislike.setAttribute("aria-pressed", String(action === "dislike" || action === "dismiss"));
  }
}

async function setTasteFeedback(kind, requestedAction) {
  const target = currentTasteTarget(kind);
  if (!target) return;
  const currentAction = loadDiscoveryProfile().item_feedback?.[target.key] || "";
  const sameChoice = requestedAction === "like"
    ? ["like", "favorite"].includes(currentAction)
    : ["dislike", "dismiss"].includes(currentAction);
  const action = sameChoice ? "clear" : requestedAction;
  try {
    const response = await api.tasteFeedback({
      item_key: target.key,
      action,
      source: "web",
      media_type: kind,
      title: target.item.title || "",
      metadata: tasteMetadata(kind, target.item),
    });
    applyServerTasteProfile(response.profile);
    renderHome();
  } catch (error) {
    console.warn("Bewertung konnte nicht gespeichert werden:", error);
  }
}

function trackDiscoveryPreference(kind, item, weight = 1, action = "open") {
  if (!item) return;
  const entry = kind === "movie" ? homeMovieEntry(item) : homeSeriesEntry(item);
  const media = kind === "anime" ? item : homeEntryMedia(entry);
  const key = kind === "anime"
    ? `anime:${item.id || item.base_slug || item.slug || "unknown"}`
    : homeEntryKey(entry);
  const profile = loadDiscoveryProfile();
  const cleanGenres = [...new Set((media.genres || [])
    .map((genre) => String(genre || "").trim())
    .filter(Boolean))].slice(0, 5);
  for (const genre of cleanGenres) {
    profile.genres[genre] = Math.min(80, Number(profile.genres[genre] || 0) + weight);
  }
  profile.kinds[kind] = Math.min(80, Number(profile.kinds[kind] || 0) + weight * 0.45);
  profile.recent = [
    { key, action, at: Date.now() },
    ...profile.recent.filter((event) => event?.key !== key),
  ].slice(0, 60);
  profile.interactions += 1;
  profile.updatedAt = Date.now();
  saveDiscoveryProfile(profile);
  api.tasteEvent({
    action,
    source: "web",
    media_type: kind,
    item_key: key,
    title: item.title || "",
    metadata: tasteMetadata(kind, media),
  }).then((response) => {
    if (response?.profile) applyServerTasteProfile(response.profile);
  }).catch((error) => console.warn("Geschmackssignal konnte nicht gespeichert werden:", error));
}

function allowedHomeEntries(entries, profile = loadDiscoveryProfile()) {
  const blocked = new Set(profile.blocked_items || []);
  return entries.filter((entry) => !blocked.has(homeEntryKey(entry)));
}

function homeAllEntries() {
  return allowedHomeEntries(uniqueHomeEntries([
    ...state.home.topMovies.map(homeMovieEntry),
    ...state.home.newMovies.map(homeMovieEntry),
    ...state.home.discoveryMovies.map(homeMovieEntry),
    ...state.home.trendingSeries.map(homeSeriesEntry),
    ...state.home.newSeries.map(homeSeriesEntry),
    ...state.home.discoverySeries.map(homeSeriesEntry),
  ]));
}

function weeklyStableEntries(entries, limit = 10) {
  const period = localWeekKey();
  const available = new Map(entries.map((entry) => [homeEntryKey(entry), entry]));
  let stored = null;
  try {
    stored = JSON.parse(localStorage.getItem(HOME_WEEKLY_TOP_KEY) || "null");
  } catch {
    stored = null;
  }
  const previousKeys = stored?.period === period && Array.isArray(stored.keys) ? stored.keys : [];
  const ordered = previousKeys.map((key) => available.get(key)).filter(Boolean);
  const known = new Set(ordered.map(homeEntryKey));
  const fill = entries
    .filter((entry) => !known.has(homeEntryKey(entry)))
    .sort((a, b) =>
      stableDiscoveryHash(`${period}|top|${homeEntryKey(a)}`)
      - stableDiscoveryHash(`${period}|top|${homeEntryKey(b)}`));
  const selected = [...ordered, ...fill].slice(0, limit);
  try {
    localStorage.setItem(HOME_WEEKLY_TOP_KEY, JSON.stringify({
      period,
      keys: selected.map(homeEntryKey),
    }));
  } catch {
    // Die Reihenfolge bleibt für diese Sitzung trotzdem stabil.
  }
  return selected;
}

function homeTopEntries() {
  return weeklyStableEntries(allowedHomeEntries(interleaveHomeEntries(
    state.home.topMovies.map(homeMovieEntry),
    state.home.trendingSeries.map(homeSeriesEntry),
    20,
  )), 10);
}

function homeNewEntries() {
  return allowedHomeEntries(interleaveHomeEntries(
    state.home.newMovies.map(homeMovieEntry),
    state.home.newSeries.map(homeSeriesEntry),
    24,
  ));
}

function homePersonalizedEntries() {
  const profile = loadDiscoveryProfile();
  const recent = new Set(profile.recent.slice(0, 18).map((event) => event.key));
  const pool = homeAllEntries();
  if (profile.interactions < 2 || !Object.keys(profile.genres).length) {
    return stableDailyOrder(pool.filter((entry) => !recent.has(homeEntryKey(entry))), "starter").slice(0, 24);
  }
  return pool
    .filter((entry) => !recent.has(homeEntryKey(entry)))
    .map((entry) => {
      const media = homeEntryMedia(entry);
      const metadata = tasteMetadata(entry.kind, media);
      const dimensionScore = Object.entries(metadata).reduce((total, [dimension, values]) => {
        if (!["genres", "tags", "studios", "directors", "actors", "languages"].includes(dimension)) return total;
        const list = Array.isArray(values) ? values : [values];
        return total + list.reduce(
          (sum, value) => sum + Number(profile.dimensions?.[dimension]?.[String(value)] || 0), 0,
        );
      }, 0);
      const year = Number(String(metadata.year || "").slice(0, 4));
      const decadeScore = year
        ? Number(profile.dimensions?.decades?.[`${Math.floor(year / 10) * 10}er`] || 0)
        : 0;
      const kindScore = Number(profile.kinds[entry.kind] || 0);
      const rating = Number(media.rating || 0);
      const discoveryNoise = stableDiscoveryHash(`${localDateKey()}|personal|${homeEntryKey(entry)}`) / 4294967295;
      return { entry, score: dimensionScore + decadeScore + kindScore + rating * 0.12 + discoveryNoise * 2.2 };
    })
    .sort((a, b) => b.score - a.score)
    .map(({ entry }) => entry)
    .slice(0, 24);
}

function favoriteDiscoveryGenre(profile = loadDiscoveryProfile()) {
  return Object.entries(profile.genres)
    .filter(([, score]) => Number(score) > 0.25)
    .sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0], "de"))[0]?.[0] || "";
}

function homeGenreEntries() {
  const profile = loadDiscoveryProfile();
  const favorite = favoriteDiscoveryGenre(profile);
  const pool = homeAllEntries();
  if (!favorite) return stableDailyOrder(pool, "genre-starter").slice(0, 24);
  const matching = pool.filter((entry) =>
    (homeEntryMedia(entry).genres || []).some((genre) =>
      String(genre).localeCompare(favorite, "de", { sensitivity: "base" }) === 0));
  return stableDailyOrder(matching.length >= 6 ? matching : pool, `genre-${favorite}`).slice(0, 24);
}

function homeExploreEntries() {
  const profile = loadDiscoveryProfile();
  const avoidedGenres = new Set(Object.entries(profile.genres)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 2)
    .map(([genre]) => genre.toLocaleLowerCase()));
  const recent = new Set(profile.recent.slice(0, 30).map((event) => event.key));
  const pool = homeAllEntries().filter((entry) => {
    if (recent.has(homeEntryKey(entry))) return false;
    const genres = (homeEntryMedia(entry).genres || []).map((genre) => String(genre).toLocaleLowerCase());
    return !genres.some((genre) => avoidedGenres.has(genre));
  });
  return stableDailyOrder(pool.length >= 8 ? pool : homeAllEntries(), "explore").slice(0, 24);
}

function homeGemEntries() {
  const topKeys = new Set(homeTopEntries().map(homeEntryKey));
  const candidates = homeAllEntries()
    .filter((entry) => !topKeys.has(homeEntryKey(entry)))
    .map((entry) => ({ entry, rating: Number(homeEntryMedia(entry).rating || 0) }))
    .filter(({ rating }) => !rating || rating >= 6.4)
    .sort((a, b) => b.rating - a.rating
      || stableDiscoveryHash(`${localDateKey()}|gems|${homeEntryKey(a.entry)}`)
      - stableDiscoveryHash(`${localDateKey()}|gems|${homeEntryKey(b.entry)}`))
    .map(({ entry }) => entry);
  return candidates.slice(0, 24);
}

function homeHeroCandidates() {
  const entries = uniqueHomeEntries([
    ...homePersonalizedEntries().slice(0, 4),
    ...stableDailyOrder(homeTopEntries(), "hero").slice(0, 3),
  ]).slice(0, 7);
  return entries.map((entry) => {
    const metadata = entry.kind === "movie"
      ? (state.fp.metadataCache[entry.item.slug] || {})
      : {};
    const media = { ...entry.item, ...metadata };
    return {
      ...entry,
      media,
      artwork: media.backdrop_url || media.cover_url || "",
      artworkKind: media.backdrop_url ? "backdrop" : (media.cover_url ? "poster" : "none"),
    };
  });
}

function stopHomeHeroRotation() {
  if (!state.home.heroTimer) return;
  window.clearInterval(state.home.heroTimer);
  state.home.heroTimer = null;
}

function scheduleHomeHeroRotation() {
  stopHomeHeroRotation();
  const hero = document.getElementById("home-hero");
  if (
    !hero
    || state.tab !== "home"
    || homeHeroCandidates().length < 2
    || hero.matches(":hover")
    || hero.contains(document.activeElement)
    || document.hidden
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) return;
  state.home.heroTimer = window.setInterval(() => {
    showHomeHero(state.home.heroIndex + 1);
  }, 9000);
}

function renderHomeHero() {
  const hero = document.getElementById("home-hero");
  if (!hero) return;
  const candidates = homeHeroCandidates();
  if (!candidates.length) {
    hero.classList.add("is-loading", "has-no-art");
    document.getElementById("home-hero-open").disabled = true;
    return;
  }
  state.home.heroIndex = ((state.home.heroIndex % candidates.length) + candidates.length) % candidates.length;
  const candidate = candidates[state.home.heroIndex];
  const media = candidate.media;
  hero.classList.remove("is-loading");
  hero.classList.toggle("is-poster-art", candidate.artworkKind === "poster");
  hero.classList.toggle("has-no-art", candidate.artworkKind === "none");
  hero.setAttribute("aria-label", `${candidate.kind === "movie" ? "Film" : "Serie"}: ${media.title}`);
  document.getElementById("home-hero-art").style.backgroundImage = candidate.artwork
    ? `url("${api.coverUrl(candidate.artwork).replace(/"/g, "%22")}")`
    : "";
  document.getElementById("home-hero-kind").textContent =
    candidate.kind === "movie" ? "ROYAL FILM" : "ROYAL SERIE";
  document.getElementById("home-hero-title").textContent = media.title || "Royal";
  document.getElementById("home-hero-meta").textContent = [
    media.year || (media.first_air_date ? String(media.first_air_date).slice(0, 4) : ""),
    media.rating ? `★ ${media.rating}` : "",
    ...(media.genres || []).slice(0, 2),
    candidate.kind === "movie" ? "Film" : "Serie",
  ].filter(Boolean).join(" · ");
  document.getElementById("home-hero-description").textContent =
    media.description
    || (candidate.kind === "movie"
      ? "Neu und beliebt bei deinen ausgewählten Filmquellen."
      : "Eine aktuell angesagte Serie aus deinen eingerichteten Quellen.");
  const open = document.getElementById("home-hero-open");
  open.disabled = false;
  open.dataset.kind = candidate.kind;
  open.dataset.key = candidate.kind === "movie" ? media.slug : media.base_slug;
  document.getElementById("home-hero-position").textContent =
    `${state.home.heroIndex + 1} / ${candidates.length}`;
}

function showHomeHero(index, userInitiated = false) {
  const count = homeHeroCandidates().length;
  if (!count) return;
  state.home.heroIndex = ((index % count) + count) % count;
  const hero = document.getElementById("home-hero");
  if (!userInitiated && hero) {
    hero.classList.add("is-changing");
    window.setTimeout(() => hero.classList.remove("is-changing"), 380);
  }
  renderHomeHero();
}

function openHomeEntry(kind, key) {
  if (kind === "movie") {
    const movie = homeMovieBySlug(key);
    closeGlobalSearch();
    if (movie) selectFpRow(movie.slug, movie);
    return;
  }
  const series = homeSeriesBySlug(key);
  closeGlobalSearch();
  if (series) loadSeries(series);
}

function updateHomeCardHoverEdge(card) {
  if (!card || card.classList.contains("is-ranked")) return;
  const track = card.closest(".home-track");
  if (!track) return;
  const cardRect = card.getBoundingClientRect();
  const trackRect = track.getBoundingClientRect();
  const growth = cardRect.width * 0.35;
  const clipsLeft = cardRect.left - growth < trackRect.left;
  const clipsRight = cardRect.right + growth > trackRect.right;
  card.classList.toggle("is-hover-edge-left", clipsLeft && !clipsRight);
  card.classList.toggle("is-hover-edge-right", clipsRight && !clipsLeft);
  if (clipsLeft && clipsRight) {
    const useLeft = cardRect.left + (cardRect.width / 2) < trackRect.left + (trackRect.width / 2);
    card.classList.toggle("is-hover-edge-left", useLeft);
    card.classList.toggle("is-hover-edge-right", !useLeft);
  }
}

function updateHomeRailNavigation(track) {
  if (!track?.id) return;
  const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
  const canScroll = maxScroll > 2;
  const atStart = track.scrollLeft <= 2;
  const atEnd = track.scrollLeft >= maxScroll - 2;
  document.querySelectorAll(`[data-home-scroll="${track.id}"]`).forEach((button) => {
    const direction = Number(button.dataset.direction) || 1;
    button.hidden = !canScroll || (direction < 0 ? atStart : atEnd);
  });
}

function createHomeCard(entry, rank = 0, eager = false) {
  const { kind, item } = entry;
  const metadata = kind === "movie" ? (state.fp.metadataCache[item.slug] || {}) : {};
  const media = { ...item, ...metadata };
  const key = kind === "movie" ? item.slug : item.base_slug;
  const card = document.createElement("button");
  card.type = "button";
  card.className = `home-card home-card-${kind}${rank ? " is-ranked" : ""}`;
  card.dataset.kind = kind;
  card.dataset.key = key;
  card.setAttribute("aria-label", `${rank ? `Platz ${rank}: ` : ""}${media.title}, ${kind === "movie" ? "Film" : "Serie"}`);

  if (rank) {
    const number = document.createElement("span");
    number.className = "home-card-rank";
    number.textContent = String(rank);
    number.setAttribute("aria-hidden", "true");
    card.appendChild(number);
  }

  const art = document.createElement("span");
  art.className = "home-card-art";
  const fallback = document.createElement("span");
  fallback.className = "home-card-fallback";
  fallback.textContent = mediaCardInitials(media.title);
  art.appendChild(fallback);
  // Das bevorzugte Format bleibt erhalten, vorhandenes alternatives Artwork
  // verhindert aber leere Karten bei Titeln ohne TMDB-Backdrop oder -Poster.
  const artworkCandidates = [
    rank ? media.cover_url : media.backdrop_url,
    rank ? media.backdrop_url : media.cover_url,
  ]
    .flatMap((url) => api.coverCandidates(url))
    .filter((url, index, urls) => url && urls.indexOf(url) === index);
  if (artworkCandidates.length) {
    const image = document.createElement("img");
    let artworkIndex = 0;
    image.src = artworkCandidates[artworkIndex];
    image.alt = "";
    // Die Startseite zeigt nur kuratierte Rails. Ihre Bilder werden sofort
    // geladen, damit beim horizontalen Scrollen keine Platzhalter aufblitzen.
    image.loading = "eager";
    image.fetchPriority = eager ? "high" : "auto";
    image.decoding = "async";
    image.addEventListener("error", () => {
      artworkIndex += 1;
      if (artworkIndex < artworkCandidates.length) image.src = artworkCandidates[artworkIndex];
      else image.remove();
    });
    art.appendChild(image);
  }
  const type = document.createElement("span");
  type.className = "home-card-type";
  type.textContent = kind === "movie" ? "FILM" : "SERIE";
  const overlay = document.createElement("span");
  overlay.className = "home-card-overlay";
  const title = document.createElement("strong");
  title.translate = false;
  title.textContent = media.title;
  const meta = document.createElement("span");
  meta.textContent = [
    media.year || "",
    media.rating ? `★ ${media.rating}` : "",
  ].filter(Boolean).join(" · ") || (kind === "movie" ? "Film" : "Serie");
  overlay.append(title, meta);

  const preview = document.createElement("span");
  preview.className = "home-card-preview";
  preview.setAttribute("aria-hidden", "true");
  const previewActions = document.createElement("span");
  previewActions.className = "home-card-preview-actions";
  const playMark = document.createElement("span");
  playMark.className = "is-play";
  playMark.textContent = "▶";
  const addMark = document.createElement("span");
  addMark.className = "is-add";
  addMark.textContent = "+";
  const moreMark = document.createElement("span");
  moreMark.className = "is-more";
  moreMark.textContent = "⌄";
  previewActions.append(playMark, addMark, moreMark);
  const previewTitle = document.createElement("strong");
  previewTitle.translate = false;
  previewTitle.textContent = media.title;
  const previewMeta = document.createElement("span");
  previewMeta.className = "home-card-preview-meta";
  previewMeta.textContent = [
    media.rating ? `★ ${media.rating}` : "",
    media.year || "",
    media.runtime || "",
    kind === "movie" ? "Film" : "Serie",
  ].filter(Boolean).join(" · ");
  const previewGenres = document.createElement("span");
  previewGenres.className = "home-card-preview-genres";
  previewGenres.textContent = (media.genres || []).slice(0, 3).join(" · ")
    || (kind === "movie" ? "Film entdecken" : "Serie entdecken");
  preview.append(previewActions, previewTitle, previewMeta, previewGenres);

  art.append(type, overlay, preview);
  card.appendChild(art);
  card.addEventListener("pointerenter", () => updateHomeCardHoverEdge(card));
  card.addEventListener("pointerleave", () => {
    card.classList.remove("is-hover-edge-left", "is-hover-edge-right");
  });
  card.addEventListener("focus", () => updateHomeCardHoverEdge(card));
  card.addEventListener("blur", () => {
    card.classList.remove("is-hover-edge-left", "is-hover-edge-right");
  });
  card.addEventListener("click", () => openHomeEntry(kind, key));
  return card;
}

function renderHomeRail(trackId, entries, { ranked = false } = {}) {
  const track = document.getElementById(trackId);
  if (!track) return;
  track.replaceChildren();
  requestAnimationFrame(() => updateHomeRailNavigation(track));
  if (!entries.length) {
    if (!state.home.loading) {
      const empty = document.createElement("span");
      empty.className = "home-rail-empty";
      empty.textContent = "Noch keine Titel aus den aktiven Quellen verfügbar.";
      track.appendChild(empty);
      return;
    }
    for (let index = 0; index < 6; index += 1) {
      const skeleton = document.createElement("span");
      skeleton.className = "home-card-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      track.appendChild(skeleton);
    }
    return;
  }
  entries.forEach((entry, index) => {
    const eagerCount = ranked ? 5 : 3;
    track.appendChild(createHomeCard(entry, ranked ? index + 1 : 0, index < eagerCount));
  });
}

function renderHome() {
  state.home.discoveryDay = localDateKey();
  const profile = loadDiscoveryProfile();
  const favoriteGenre = favoriteDiscoveryGenre(profile);
  const personalTitle = document.getElementById("home-movies-title");
  const genreTitle = document.getElementById("home-genre-title");
  const genreEyebrow = document.getElementById("home-genre-eyebrow");
  if (personalTitle) {
    personalTitle.textContent = profile.interactions >= 2 ? "Für dich ausgewählt" : "Heute für dich";
  }
  if (genreTitle) {
    genreTitle.textContent = favoriteGenre ? `Weil dir ${favoriteGenre} gefällt` : "Genres zum Entdecken";
  }
  if (genreEyebrow) {
    genreEyebrow.textContent = favoriteGenre ? "Aus deinen Klicks und Downloads" : "Zum Kennenlernen";
  }
  renderHomeHero();
  renderHomeRail("home-top-track", homeTopEntries(), { ranked: true });
  renderHomeRail("home-movies-track", homePersonalizedEntries());
  renderHomeRail("home-series-track", allowedHomeEntries(state.home.trendingSeries.map(homeSeriesEntry)));
  renderHomeRail("home-genre-track", homeGenreEntries());
  renderHomeRail("home-explore-track", homeExploreEntries());
  renderHomeRail("home-gems-track", homeGemEntries());
  renderHomeRail("home-new-track", homeNewEntries());
  scheduleHomeHeroRotation();
}

const SEARCH_HISTORY_KEY = "royal-search-history-v1";
const HOME_CACHE_KEY = "royal-home-cache-v2";
const HOME_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function restoreHomeCache() {
  try {
    const cached = JSON.parse(localStorage.getItem(HOME_CACHE_KEY) || "null");
    if (
      !cached
      || Date.now() - Number(cached.savedAt || 0) > HOME_CACHE_MAX_AGE_MS
      || !cached.home
    ) return false;
    const keys = [
      "newMovies", "topMovies", "trendingSeries", "newSeries",
      "discoveryMovies", "discoverySeries",
    ];
    if (!keys.some((key) => Array.isArray(cached.home[key]) && cached.home[key].length)) return false;
    keys.forEach((key) => {
      state.home[key] = Array.isArray(cached.home[key]) ? cached.home[key] : [];
    });
    Object.assign(state.fp.metadataCache, cached.movieMetadata || {});
    state.home.loading = false;
    renderHome();
    return true;
  } catch {
    return false;
  }
}

function saveHomeCache() {
  try {
    const movieSlugs = new Set([
      ...state.home.newMovies,
      ...state.home.topMovies,
      ...state.home.discoveryMovies,
    ].map((item) => item?.slug).filter(Boolean));
    const movieMetadata = Object.fromEntries(
      [...movieSlugs]
        .filter((slug) => state.fp.metadataCache[slug])
        .map((slug) => [slug, state.fp.metadataCache[slug]]),
    );
    localStorage.setItem(HOME_CACHE_KEY, JSON.stringify({
      savedAt: Date.now(),
      home: {
        newMovies: state.home.newMovies,
        topMovies: state.home.topMovies,
        trendingSeries: state.home.trendingSeries,
        newSeries: state.home.newSeries,
        discoveryMovies: state.home.discoveryMovies,
        discoverySeries: state.home.discoverySeries,
      },
      movieMetadata,
    }));
  } catch {
    // Ein voller oder gesperrter Browser-Speicher darf die Startseite nicht blockieren.
  }
}

function searchHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(SEARCH_HISTORY_KEY) || "[]");
    return Array.isArray(value) ? value.filter((entry) => entry?.query).slice(0, 6) : [];
  } catch {
    return [];
  }
}

function rememberSearch(query, kind) {
  const normalized = query.trim();
  if (!normalized) return;
  const next = [
    { query: normalized, kind },
    ...searchHistory().filter((entry) => entry.query.toLocaleLowerCase() !== normalized.toLocaleLowerCase()),
  ].slice(0, 6);
  try {
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(next));
  } catch {
    // Private Modi können lokalen Speicher blockieren; die Suche bleibt nutzbar.
  }
  const matchingGenre = [...document.querySelectorAll("#genre-filter [data-genre]")]
    .map((element) => element.dataset.genre || "")
    .find((genre) => genre && genre !== "Alle Genres"
      && genre.localeCompare(normalized, "de", { sensitivity: "base" }) === 0);
  api.tasteEvent({
    action: "search", source: "web", media_type: kind, query: normalized,
    metadata: matchingGenre ? { genres: [matchingGenre] } : {},
  }).catch((error) => console.warn("Suchsignal konnte nicht gespeichert werden:", error));
}

function searchCandidates(kind) {
  const movies = uniqueHomeEntries([
    ...state.fp.results.map(homeMovieEntry),
    ...state.home.topMovies.map(homeMovieEntry),
    ...state.home.newMovies.map(homeMovieEntry),
    ...state.home.discoveryMovies.map(homeMovieEntry),
  ]);
  const series = uniqueHomeEntries([
    ...state.series.results.map(homeSeriesEntry),
    ...state.home.trendingSeries.map(homeSeriesEntry),
    ...state.home.newSeries.map(homeSeriesEntry),
    ...state.home.discoverySeries.map(homeSeriesEntry),
  ]);
  if (kind === "movie") return movies;
  if (kind === "series") return series;
  return interleaveHomeEntries(movies, series, 40);
}

function searchEntryText(entry) {
  const item = entry.item;
  return [
    item.title,
    item.year,
    ...(item.genres || []),
    ...(item.actors || item.cast || []),
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function rankedSearchCandidates(kind, query) {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [];
  return searchCandidates(kind)
    .map((entry) => {
      const title = String(entry.item.title || "").toLocaleLowerCase();
      const text = searchEntryText(entry);
      const score = title === needle ? 0 : title.startsWith(needle) ? 1 : title.includes(needle) ? 2 : text.includes(needle) ? 3 : 99;
      return { entry, score };
    })
    .filter(({ score }) => score < 99)
    .sort((a, b) => a.score - b.score || String(a.entry.item.title).localeCompare(String(b.entry.item.title), "de"))
    .slice(0, 6)
    .map(({ entry }) => entry);
}

function closeSearchSuggestions(panelId, inputId) {
  const panel = document.getElementById(panelId);
  const input = document.getElementById(inputId);
  if (panel) panel.hidden = true;
  if (input) input.setAttribute("aria-expanded", "false");
}

function renderSearchSuggestions(kind, inputId, panelId, runSearch) {
  const input = document.getElementById(inputId);
  const panel = document.getElementById(panelId);
  if (!input || !panel) return;
  const query = input.value.trim();
  const matches = rankedSearchCandidates(kind, query);
  const recent = query ? [] : searchHistory().filter((entry) => kind === "all" || entry.kind === kind).slice(0, 4);
  panel.replaceChildren();
  const rows = matches.length
    ? matches.map((entry) => ({
        label: entry.item.title,
        meta: `${entry.kind === "movie" ? "Film" : "Serie"}${entry.item.year ? ` · ${entry.item.year}` : ""}`,
      }))
    : recent.map((entry) => ({ label: entry.query, meta: "Zuletzt gesucht" }));
  if (!rows.length) {
    closeSearchSuggestions(panelId, inputId);
    return;
  }
  const heading = document.createElement("span");
  heading.className = "smart-search-suggestions-label";
  heading.textContent = matches.length ? "Direkte Treffer" : "Letzte Suchen";
  panel.appendChild(heading);
  rows.forEach((row) => {
    const button = document.createElement("button");
    button.type = "button";
    const label = document.createElement("strong");
    label.textContent = row.label;
    const meta = document.createElement("span");
    meta.textContent = row.meta;
    button.append(label, meta);
    button.addEventListener("click", () => {
      input.value = row.label;
      syncSearchClearButtons();
      closeSearchSuggestions(panelId, inputId);
      runSearch();
    });
    panel.appendChild(button);
  });
  panel.hidden = false;
  input.setAttribute("aria-expanded", "true");
}

function syncSearchClearButtons() {
  [
    ["home-search", "home-search-clear"],
    ["fp-search", "fp-search-clear"],
    ["series-search", "series-search-clear"],
  ].forEach(([inputId, clearId]) => {
    const input = document.getElementById(inputId);
    const clear = document.getElementById(clearId);
    if (input && clear) clear.hidden = !input.value;
  });
}

function renderGlobalSearchResults() {
  const page = document.getElementById("global-search-page");
  const grid = document.getElementById("global-search-grid");
  const status = document.getElementById("global-search-status");
  const shell = document.getElementById("global-search-shell");
  const input = document.getElementById("global-search-input");
  const clear = document.getElementById("global-search-clear");
  const toggle = document.getElementById("global-search-toggle");
  if (!page || !grid || !status || !shell || !input || !clear || !toggle) return;

  page.hidden = !state.globalSearch.active;
  document.body.classList.toggle("global-search-open", state.globalSearch.active);
  shell.classList.toggle("has-value", Boolean(input.value));
  clear.hidden = !input.value;
  toggle.setAttribute("aria-expanded", String(state.globalSearch.active || document.activeElement === input));
  input.setAttribute("aria-expanded", String(state.globalSearch.active));
  if (!state.globalSearch.active) return;

  grid.replaceChildren();
  status.textContent = state.globalSearch.loading
    ? `Suche nach «${state.globalSearch.query}» …`
    : `${state.globalSearch.results.length} Treffer für «${state.globalSearch.query}»`;
  page.classList.toggle("is-loading", state.globalSearch.loading);
  if (state.globalSearch.loading) {
    for (let index = 0; index < 12; index += 1) {
      const skeleton = document.createElement("span");
      skeleton.className = "home-card-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      grid.appendChild(skeleton);
    }
    return;
  }
  if (!state.globalSearch.results.length) {
    const empty = document.createElement("div");
    empty.className = "global-search-empty";
    empty.innerHTML = "<strong>Nichts gefunden</strong><span>Versuche einen anderen Titel, Namen oder ein Genre.</span>";
    grid.appendChild(empty);
    return;
  }
  state.globalSearch.results.forEach((entry, index) => {
    grid.appendChild(createHomeCard(entry, 0, index < 8));
  });
}

async function performGlobalSearch(query, requestId) {
  rememberSearch(query, "all");
  const settled = await Promise.allSettled([
    api.movies({ mode: "search", query }).then((data) => (data.results || []).map(homeMovieEntry)),
    api.series({ mode: "search", query }).then((data) => (data.results || []).map(homeSeriesEntry)),
  ]);
  if (requestId !== state.globalSearch.requestSeq) return;
  const groups = settled
    .filter((result) => result.status === "fulfilled")
    .map((result) => result.value);
  state.globalSearch.results = groups.length > 1
    ? interleaveHomeEntries(groups[0], groups[1], 60)
    : uniqueHomeEntries(groups[0] || []).slice(0, 60);

  await Promise.allSettled([
    hydrateHomeMovieArtwork(
      state.globalSearch.results
        .filter((entry) => entry.kind === "movie")
        .map((entry) => entry.item),
      { render: false },
    ),
    hydrateHomeSeriesArtwork(
      state.globalSearch.results
        .filter((entry) => entry.kind === "series")
        .map((entry) => entry.item),
      { render: false },
    ),
  ]);
  if (requestId !== state.globalSearch.requestSeq) return;
  state.globalSearch.loading = false;
  renderGlobalSearchResults();
}

function queueGlobalSearch(immediate = false) {
  const input = document.getElementById("global-search-input");
  const query = input.value.trim();
  window.clearTimeout(state.globalSearch.debounceTimer);
  const requestId = ++state.globalSearch.requestSeq;
  state.globalSearch.query = query;
  if (!query) {
    state.globalSearch.active = false;
    state.globalSearch.loading = false;
    state.globalSearch.results = [];
    renderGlobalSearchResults();
    return;
  }
  state.globalSearch.active = true;
  state.globalSearch.loading = true;
  state.globalSearch.results = [];
  renderGlobalSearchResults();
  state.globalSearch.debounceTimer = window.setTimeout(
    () => performGlobalSearch(query, requestId),
    immediate ? 0 : 320,
  );
}

function closeGlobalSearch({ restoreFocus = false } = {}) {
  const input = document.getElementById("global-search-input");
  if (!input) return;
  window.clearTimeout(state.globalSearch.debounceTimer);
  ++state.globalSearch.requestSeq;
  state.globalSearch.query = "";
  state.globalSearch.results = [];
  state.globalSearch.active = false;
  state.globalSearch.loading = false;
  input.value = "";
  renderGlobalSearchResults();
  if (restoreFocus) document.getElementById("global-search-toggle")?.focus();
}

function renderHomeSearchResults() {
  const section = document.getElementById("home-search-results");
  const track = document.getElementById("home-search-track");
  const status = document.getElementById("home-search-status");
  if (!section || !track || !status) return;
  section.hidden = !state.home.search.active;
  if (!state.home.search.active) return;
  track.replaceChildren();
  status.textContent = state.home.search.loading
    ? `Suche nach «${state.home.search.query}» …`
    : `${state.home.search.results.length} Treffer für «${state.home.search.query}»`;
  section.classList.toggle("is-loading", state.home.search.loading);
  if (state.home.search.loading) {
    for (let index = 0; index < 6; index += 1) {
      const skeleton = document.createElement("span");
      skeleton.className = "home-card-skeleton";
      track.appendChild(skeleton);
    }
    return;
  }
  if (!state.home.search.results.length) {
    const empty = document.createElement("div");
    empty.className = "home-search-empty";
    empty.innerHTML = "<strong>Nichts gefunden</strong><span>Versuche einen kürzeren Titel, ein Genre oder einen Schauspieler.</span>";
    track.appendChild(empty);
    return;
  }
  state.home.search.results.forEach((entry, index) => track.appendChild(createHomeCard(entry, 0, index < 4)));
}

async function homeSearch() {
  const input = document.getElementById("home-search");
  const query = input.value.trim();
  if (!query) {
    renderSearchSuggestions("all", "home-search", "home-search-suggestions", homeSearch);
    return;
  }
  rememberSearch(query, state.home.search.scope);
  closeSearchSuggestions("home-search-suggestions", "home-search");
  const requestId = ++state.home.search.requestSeq;
  state.home.search.query = query;
  state.home.search.active = true;
  state.home.search.loading = true;
  renderHomeSearchResults();
  const requests = [];
  if (state.home.search.scope !== "series") {
    requests.push(api.movies({ mode: "search", query }).then((data) => (data.results || []).map(homeMovieEntry)));
  }
  if (state.home.search.scope !== "movie") {
    requests.push(api.series({ mode: "search", query }).then((data) => (data.results || []).map(homeSeriesEntry)));
  }
  const settled = await Promise.allSettled(requests);
  if (requestId !== state.home.search.requestSeq) return;
  const groups = settled.filter((result) => result.status === "fulfilled").map((result) => result.value);
  state.home.search.results = groups.length > 1
    ? interleaveHomeEntries(groups[0], groups[1], 36)
    : uniqueHomeEntries(groups[0] || []).slice(0, 36);
  state.home.search.loading = false;
  renderHomeSearchResults();
  hydrateHomeMovieArtwork(
    state.home.search.results.filter((entry) => entry.kind === "movie").map((entry) => entry.item),
    { render: false },
  ).then(renderHomeSearchResults);
  hydrateHomeSeriesArtwork(
    state.home.search.results.filter((entry) => entry.kind === "series").map((entry) => entry.item),
    { render: false },
  ).then(renderHomeSearchResults);
}

function closeHomeSearch() {
  ++state.home.search.requestSeq;
  state.home.search.active = false;
  state.home.search.loading = false;
  state.home.search.results = [];
  document.getElementById("home-search").value = "";
  syncSearchClearButtons();
  renderHomeSearchResults();
}

async function loadHomeData() {
  state.home.loading = true;
  if (!homeAllEntries().length) renderHome();
  const newMoviesRequest = api.movies({ mode: "new", page: 1 });
  const trendingSeriesRequest = api.series({ mode: "trending", page: 1 });
  const topMoviesRequest = api.movies({ mode: "top", page: 1 });
  const newSeriesRequest = api.series({ mode: "new", page: 1 });
  const discoveryMoviesRequest = Promise.allSettled([
    api.movies({ mode: "new", page: 2 }),
    api.movies({ mode: "top", page: 2 }),
  ]).then((results) => {
    return results
      .filter((result) => result.status === "fulfilled")
      .flatMap((result) => result.value.results || []);
  });
  const discoverySeriesRequest = api.series({ mode: "discover", page: 1 });
  const results = await Promise.allSettled([
    newMoviesRequest,
    trendingSeriesRequest,
    topMoviesRequest,
    newSeriesRequest,
    discoveryMoviesRequest,
    discoverySeriesRequest,
  ]);
  if (results[0].status === "fulfilled") state.home.newMovies = results[0].value.results || [];
  if (results[1].status === "fulfilled") state.home.trendingSeries = results[1].value.results || [];
  if (results[2].status === "fulfilled") state.home.topMovies = results[2].value.results || [];
  if (results[3].status === "fulfilled") state.home.newSeries = results[3].value.results || [];
  if (results[4].status === "fulfilled" && results[4].value.length) {
    state.home.discoveryMovies = results[4].value;
  }
  if (results[5].status === "fulfilled") state.home.discoverySeries = results[5].value.results || [];
  if (!state.home.topMovies.length) state.home.topMovies = state.home.newMovies.slice();
  if (!state.home.newSeries.length) state.home.newSeries = state.home.trendingSeries.slice();
  renderHome();
  await Promise.allSettled([
    hydrateHomeMovieArtwork([
      ...state.home.newMovies,
      ...state.home.topMovies,
      ...state.home.discoveryMovies,
    ], { render: false }),
    hydrateHomeSeriesArtwork([
      ...state.home.trendingSeries,
      ...state.home.newSeries,
      ...state.home.discoverySeries,
    ], { render: false }),
  ]);
  state.home.loading = false;
  saveHomeCache();
  renderHome();
}

async function hydrateHomeMovieArtwork(items, { render = true } = {}) {
  const targets = [
    ...new Map(
      items
        .filter((item) => {
          if (!item?.slug) return false;
          const known = { ...item, ...(state.fp.metadataCache[item.slug] || {}) };
          return !known.cover_url || !known.backdrop_url;
        })
        .map((item) => [item.slug, item]),
    ).values(),
  ];
  if (!targets.length) return;
  try {
    const response = await api.tmdbMovies(targets.map((item) => ({
      slug: item.slug,
      title: item.title,
      year: item.year || "",
    })));
    for (const [slug, metadata] of Object.entries(response.movies || {})) {
      if (metadata) {
        state.fp.metadataCache[slug] = { ...(state.fp.metadataCache[slug] || {}), ...metadata };
      }
    }
    if (render) renderHome();
  } catch (error) {
    console.warn("Startseitenbilder konnten nicht ergänzt werden:", error);
  }
}

async function hydrateHomeSeriesArtwork(items, { render = true } = {}) {
  const targets = [
    ...new Map(
      items
        .filter((item) => item?.base_slug && (!item.cover_url || !item.backdrop_url))
        .map((item) => [item.base_slug, item]),
    ).values(),
  ];
  if (!targets.length) return [];
  const hydratedBaseSlugs = [];
  try {
    const response = await api.tmdbSeries(targets.map((item) => ({
      base_slug: item.base_slug,
      title: item.title,
      year: item.year || "",
    })));
    for (const item of targets) {
      const metadata = response.series?.[item.base_slug];
      if (!metadata) continue;
      const hadCover = Boolean(item.cover_url);
      const hadBackdrop = Boolean(item.backdrop_url);
      Object.assign(item, metadata, {
        cover_url: metadata.cover_url || item.cover_url || "",
        backdrop_url: metadata.backdrop_url || item.backdrop_url || "",
      });
      if ((!hadCover && item.cover_url) || (!hadBackdrop && item.backdrop_url)) {
        hydratedBaseSlugs.push(item.base_slug);
      }
    }
    if (render) renderHome();
  } catch (error) {
    console.warn("Serien-Wallpaper konnten nicht ergänzt werden:", error);
  }
  return hydratedBaseSlugs;
}

function fpStatusMessage() {
  const visibleSlugs = new Set(state.fp.results.map((r) => r.slug));
  const visiblePicks = [...state.queuedSlugs].filter((s) => visibleSlugs.has(s)).length;
  const otherPicks = state.queuedSlugs.size - visiblePicks;
  let msg;
  if (state.fp.searchActive) {
    msg = `${state.fp.results.length} Filme auf TMDB`;
  } else if (state.fp.activeGenre === "Alle Genres") {
    msg = `${state.fp.results.length} Treffer`;
  } else {
    msg = `Genre: ${state.fp.activeGenre}  ·  ${state.fp.results.length} Treffer`;
  }
  if (state.queuedSlugs.size) {
    const extra = otherPicks ? `  ·  ${otherPicks} von anderen Seiten` : "";
    msg += `  ·  ${state.queuedSlugs.size} markiert${extra}`;
  }
  return msg;
}

function setActiveGenreFilter(genre) {
  const activeGenre = genre || "Alle Genres";
  state.fp.activeGenre = activeGenre;
  const activeLabel = document.getElementById("genre-active");
  if (activeLabel) activeLabel.textContent = activeGenre === "Alle Genres" ? "Alle Filme" : activeGenre;
  document.querySelectorAll("#genre-filter [data-genre]").forEach((button) => {
    const selected = button.dataset.genre === activeGenre;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function mergeCatalogItems(current, incoming, keyFor) {
  const merged = current.slice();
  const known = new Set(current.map(keyFor));
  for (const item of incoming) {
    const key = keyFor(item);
    if (!key || known.has(key)) continue;
    known.add(key);
    merged.push(item);
  }
  return merged;
}

function mergeCatalogSources(current, incoming, append) {
  const cleanIncoming = Array.isArray(incoming)
    ? incoming.filter((source) => Number(source.count) > 0)
    : [];
  if (!append) return cleanIncoming;
  const merged = new Map(current.map((source) => [source.key || source.label, { ...source }]));
  for (const source of cleanIncoming) {
    const key = source.key || source.label;
    const existing = merged.get(key);
    if (existing) existing.count = Number(existing.count || 0) + Number(source.count || 0);
    else merged.set(key, { ...source });
  }
  return [...merged.values()];
}

function updateFpInfiniteState() {
  const sentinel = document.getElementById("fp-infinite");
  if (!sentinel) return;
  const label = document.getElementById("fp-infinite-label");
  const retry = document.getElementById("fp-infinite-retry");
  const browsable = Boolean(state.fp.category && !state.fp.searchActive && state.fp.results.length);
  sentinel.classList.toggle("hidden", !browsable);
  if (!browsable) return;

  const count = state.fp.results.length;
  sentinel.setAttribute("aria-busy", String(state.fp.loadingMore));
  retry.hidden = !state.fp.loadError
    && (catalogInfiniteObserverSupported || !state.fp.lastPageFull);
  retry.textContent = state.fp.loadError ? "Erneut versuchen" : "Weitere laden";
  if (state.fp.loadingMore) {
    sentinel.dataset.state = "loading";
    label.textContent = "Weitere Filme werden geladen …";
  } else if (state.fp.loadError) {
    sentinel.dataset.state = "error";
    label.textContent = `Nachladen fehlgeschlagen · ${count} Filme geladen`;
  } else if (state.fp.lastPageFull) {
    sentinel.dataset.state = "ready";
    label.textContent = `${count} Filme geladen · Weiter scrollen`;
  } else {
    sentinel.dataset.state = "complete";
    label.textContent = `${count} Filme geladen · Ende des Katalogs`;
  }
  const sourceSummary = state.fp.sources
    .map((source) => `${source.label} ${source.count}`)
    .join(" · ");
  sentinel.title = sourceSummary;
}

// Bestes bekanntes Jahr eines Filmtreffers. Anbieterlisten liefern teils ein
// falsches Jahr (Re-Release/Scraping-Fehler), das den jahrgenauen
// Jellyfin-Abgleich sonst fälschlich scheitern lässt und im UI verkehrt
// angezeigt wird. Das per TMDB aufgelöste Jahr ist verlässlicher.
function fpResultYear(result) {
  return state.fp.metadataCache[result.slug]?.year || result.year || "";
}

async function refreshFpJellyfinStatus() {
  const items = state.fp.results.map((r) => ({
    slug: r.slug,
    title: r.title,
    year: fpResultYear(r),
    tmdb_id: state.fp.metadataCache[r.slug]?.tmdb_id || null,
  }));
  if (!items.length) return;
  try {
    const response = await api.jellyfinMatches(items);
    for (const result of state.fp.results) {
      if (Object.hasOwn(response.matches || {}, result.slug)) {
        result.in_jellyfin = !!response.matches[result.slug];
      }
    }
    updateFpJellyfinBadges();
  } catch (e) { /* JF bleibt optional. */ }
}

function updateSeriesStatus(series) {
  if (!series) return;
  updateSeriesJellyfinBadge(series);
  const status = document.getElementById("series-status");
  if (series.availability_error) {
    status.textContent = `${series.episode_count} Episoden · Verfügbarkeitsprüfung fehlgeschlagen`;
    return;
  }
  if (series.availability_pending) {
    status.textContent = `${series.episode_count} Episoden · Verfügbarkeit wird geprüft …`;
    return;
  }
  if (series.jellyfin_available === false) {
    status.textContent = `${series.episode_count} Episoden · Jellyfin-Abgleich nicht verfügbar`;
    return;
  }
  if (series.jellyfin_configured) {
    const jellyfinCount = (series.seasons || []).reduce(
      (sum, season) => sum + season.episodes.filter((episode) => episode.in_jellyfin).length,
      0,
    );
    status.textContent = `${series.episode_count} Episoden · ${jellyfinCount} in Jellyfin`;
    return;
  }
  status.textContent = `${series.episode_count} Episoden`;
}

function updateSeriesJellyfinBadge(series, checking = false) {
  const badge = document.getElementById("series-jellyfin-status");
  if (!badge) return;
  const label = badge.querySelector("strong");
  badge.className = "series-jellyfin-status";
  if (checking || series?.jellyfin_pending) {
    badge.classList.add("is-checking");
    label.textContent = "Jellyfin wird geprüft";
    return;
  }
  if (series?.jellyfin_stale) {
    const episodes = (series.seasons || []).flatMap((season) => season.episodes || []);
    const jellyfinCount = episodes.filter((episode) => episode.in_jellyfin).length;
    badge.classList.add("is-unavailable");
    label.textContent = `${jellyfinCount} Episoden · letzter Jellyfin-Stand`;
    return;
  }
  if (series?.availability_error || series?.jellyfin_available === false) {
    badge.classList.add("is-unavailable");
    label.textContent = "Jellyfin-Abgleich nicht verfügbar";
    return;
  }
  if (!series?.jellyfin_configured) {
    badge.classList.add("is-disconnected");
    label.textContent = "Jellyfin nicht verbunden";
    return;
  }
  const episodes = (series.seasons || []).flatMap((season) => season.episodes || []);
  const jellyfinCount = episodes.filter((episode) => episode.in_jellyfin).length;
  badge.classList.add(jellyfinCount ? "is-owned" : "is-missing");
  label.textContent = jellyfinCount === episodes.length && episodes.length
    ? "Vollständig in Jellyfin"
    : jellyfinCount
      ? `${jellyfinCount} Episoden in Jellyfin`
      : "Nicht in Jellyfin";
}

async function refreshSeriesJellyfinStatus(force = false) {
  const current = state.series.current;
  if (!current) return false;
  const baseSlug = current.base_slug;
  const sampleSlug = state.series.currentSampleSlug || firstEpisodeSlug(current) || current.url;
  const viewGeneration = state.series.viewGeneration;
  const refreshGeneration = ++state.series.jellyfinRefreshSeq;
  state.series.jellyfinRefreshByBase.set(baseSlug, refreshGeneration);
  const quickStatusPromise = api.seriesJellyfinStatus(current, force).then((status) => {
    const isLatestForSeries = state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration;
    const isSameView = state.series.viewGeneration === viewGeneration;
    if (!isLatestForSeries || !isSameView || state.series.current?.base_slug !== baseSlug) return;
    const live = state.series.current;
    for (const season of live.seasons || []) {
      for (const episode of season.episodes || []) {
        if (Object.hasOwn(status.episodes || {}, episode.slug)) {
          episode.in_jellyfin = Boolean(status.episodes[episode.slug]);
        }
      }
    }
    live.jellyfin_configured = Boolean(status.configured);
    live.jellyfin_pending = false;
    live.jellyfin_available = Boolean(status.available);
    live.jellyfin_stale = Boolean(status.stale);
    live.jellyfin_checked_at = Number(status.checked_at || 0);
    state.series.cache[baseSlug] = live;
    pruneSeriesEpisodeSelection();
    renderSeriesTiles();
    updateSeriesStatus(live);
  }).catch((error) => {
    console.warn("Schneller Jellyfin-Abgleich fehlgeschlagen:", error);
  });
  try {
    // Der gezielte Status oben übernimmt ein erzwungenes Live-Refresh. Das
    // vollständige Enrichment nutzt danach denselben Cache und lädt nicht
    // parallel erneut die komplette Jellyfin-Struktur.
    const refreshed = await api.seriesLoad(sampleSlug, baseSlug, false);
    const isLatestForSeries = state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration;
    const isSameView = state.series.viewGeneration === viewGeneration;
    if (!isLatestForSeries || !isSameView || state.series.current?.base_slug !== baseSlug) return false;
    syncSeriesQueueFlags(refreshed);
    const enriched = {
      ...current,
      ...refreshed,
      backdrop_url: refreshed.backdrop_url || current.backdrop_url || "",
    };
    state.series.current = enriched;
    state.series.cache[baseSlug] = enriched;
    pruneSeriesEpisodeSelection();
    updateSeriesOverview(enriched);
    updateWatchBtn();
    renderSeriesTiles();
    updateSeriesStatus(enriched);
    return true;
  } catch (error) {
    console.warn("Serienstatus konnte nicht live aktualisiert werden:", error);
    const isLatestForSeries = state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration;
    const isSameView = state.series.viewGeneration === viewGeneration;
    if (
      isLatestForSeries
      && isSameView
      && state.series.current?.base_slug === baseSlug
      && state.series.current.availability_pending
    ) {
      state.series.current.availability_error = true;
      state.series.cache[baseSlug] = state.series.current;
      renderSeriesTiles();
      updateSeriesStatus(state.series.current);
    }
    return false;
  } finally {
    await quickStatusPromise;
    if (state.series.jellyfinRefreshByBase.get(baseSlug) === refreshGeneration) {
      state.series.jellyfinRefreshByBase.delete(baseSlug);
    }
  }
}

function setFpJellyfinBadge(badge, owned) {
  badge.className = `jellyfin-badge ${owned ? "owned" : "dim"}`;
  badge.textContent = owned ? "JF · DA" : "—";
  badge.title = owned
    ? "Bereits in der Jellyfin-Bibliothek gefunden"
    : "Nicht in der Jellyfin-Bibliothek gefunden";
}

function setFpPosterJellyfinBadge(badge, owned) {
  badge.hidden = !owned;
  badge.textContent = "In Jellyfin";
  badge.title = "Bereits in der Jellyfin-Bibliothek gefunden";
  badge.setAttribute("aria-label", "In Jellyfin vorhanden");
}

function updateFpJellyfinBadges() {
  const resultsBySlug = new Map(state.fp.results.map((result) => [result.slug, result]));
  for (const row of document.querySelectorAll("#fp-results .row")) {
    const result = resultsBySlug.get(row.dataset.slug);
    const badge = row.querySelector(".jellyfin-badge");
    if (result && badge) setFpJellyfinBadge(badge, !!result.in_jellyfin);
    const posterBadge = row.querySelector(".result-card-library-badge");
    if (result && posterBadge) setFpPosterJellyfinBadge(posterBadge, !!result.in_jellyfin);
  }
  const selected = resultsBySlug.get(state.fp.selectedSlug);
  if (selected && typeof selected.in_jellyfin === "boolean") {
    setFpDetailJellyfinStatus(selected.in_jellyfin);
  }
}

function mediaCardInitials(title) {
  const words = String(title || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "RD";
  return (words.length === 1 ? words[0].slice(0, 2) : words.slice(0, 2).map((word) => word[0]).join(""))
    .toUpperCase();
}

function createResultCardVisual(media, title, kind, inJellyfin = false) {
  const visual = document.createElement("span");
  visual.className = "result-card-visual";

  const fallback = document.createElement("span");
  fallback.className = "result-card-fallback";
  fallback.textContent = mediaCardInitials(title);
  visual.appendChild(fallback);

  const coverCandidates = api.coverCandidates(media?.cover_url);
  if (coverCandidates.length) {
    const image = document.createElement("img");
    image.className = "result-card-poster";
    image.alt = "";
    // Infinite catalogs keep poster traffic proportional to the visible area.
    image.loading = "lazy";
    image.fetchPriority = "low";
    image.decoding = "async";
    let coverIndex = 0;
    image.src = coverCandidates[coverIndex];
    image.addEventListener("error", () => {
      coverIndex += 1;
      if (coverIndex < coverCandidates.length) image.src = coverCandidates[coverIndex];
      else image.remove();
    });
    visual.appendChild(image);
  }

  const kindMark = document.createElement("span");
  kindMark.className = "result-card-kind";
  kindMark.textContent = kind === "series" ? "S" : "F";
  const openMark = document.createElement("span");
  openMark.className = "result-card-open";
  openMark.textContent = "↗";
  openMark.setAttribute("aria-hidden", "true");
  visual.append(kindMark, openMark);
  if (kind === "movie") {
    const libraryBadge = document.createElement("span");
    libraryBadge.className = "result-card-library-badge";
    setFpPosterJellyfinBadge(libraryBadge, inJellyfin);
    visual.appendChild(libraryBadge);
  }
  return visual;
}

function activateResultCard(row, callback) {
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-haspopup", "dialog");
  row.addEventListener("click", callback);
  row.addEventListener("keydown", (event) => {
    if (event.target !== row || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    callback();
  });
}

function fpResultMedia(result) {
  return state.fp.moviesCache[result.slug] || state.fp.metadataCache[result.slug] || result;
}

function fpResultAvailability(result) {
  const movie = state.fp.moviesCache[result.slug];
  const queued = state.queuedSlugs.has(result.slug);
  if (queued) return { label: "In Queue", tag: "picked" };
  if (movie) {
    if (!movie.hosters || movie.hosters.length === 0) return { label: "Kein Hoster", tag: "novoe" };
    return {
      label: movie.provider_count ? `${movie.provider_count} Anbieter` : (movie.hoster_label || "Bereit"),
      tag: "ready",
    };
  }
  if (String(result.slug || "").startsWith("tmdb:")) return { label: "Auswählen", tag: "idle" };
  if (state.fp.pendingPreload?.has(result.slug)) return { label: "Lädt …", tag: "pending" };
  return { label: "Wird geprüft", tag: "idle" };
}

function findFpResultCard(slug) {
  return [...document.querySelectorAll("#fp-results .result-card")]
    .find((row) => row.dataset.slug === slug) || null;
}

function updateFpResultCard(slug) {
  const result = state.fp.results.find((item) => item.slug === slug);
  const row = findFpResultCard(slug);
  if (!result || !row) return;
  const oldVisual = row.querySelector(".result-card-visual");
  oldVisual?.replaceWith(createResultCardVisual(
    fpResultMedia(result), result.title, "movie", !!result.in_jellyfin,
  ));
  const availability = fpResultAvailability(result);
  const stateLabel = row.querySelector(".result-card-state");
  if (stateLabel) {
    stateLabel.className = `result-card-state status-${availability.tag}`;
    stateLabel.textContent = availability.label;
  }
  const subtitle = row.querySelector(".result-card-subtitle");
  if (subtitle) {
    const resolved = state.fp.moviesCache[result.slug];
    subtitle.textContent = (resolved?.source_providers || []).map((source) => source.label).join(" · ")
      || (fpResultMedia(result).genres || []).slice(0, 2).join(" · ")
      || "Film";
  }
  const rating = row.querySelector(".result-card-rating");
  if (rating) rating.textContent = fpResultMedia(result).rating ? `★ ${fpResultMedia(result).rating}` : "★ —";
  const yearEl = row.querySelector(".result-card-year");
  if (yearEl) yearEl.textContent = fpResultYear(result) || "Jahr offen";
}

function syncFpDetailQueueAction() {
  const slug = state.fp.selectedSlug;
  const detailPanel = document.getElementById("fp-detail-panel");
  if (!slug || detailPanel.classList.contains("is-empty")) return;
  const movie = state.fp.moviesCache[slug];
  const metadata = state.fp.metadataCache[slug];
  if (movie) configureFpDetailAction(slug, movie, false);
  else if (metadata) configureFpDetailAction(slug, metadataPreviewMovie(metadata), true);
}

function syncFpQueueIndicators() {
  for (const result of state.fp.results) {
    const row = findFpResultCard(result.slug);
    if (!row) continue;
    const queued = state.queuedSlugs.has(result.slug);
    row.classList.toggle("queued", queued);
    const toggle = row.querySelector(".result-queue-toggle");
    if (toggle) {
      toggle.classList.toggle("is-queued", queued);
      toggle.textContent = queued ? "✓" : "+";
      toggle.setAttribute("aria-label", queued
        ? `${result.title} aus der Queue entfernen`
        : `${result.title} zur Queue hinzufügen`);
    }
    const availability = fpResultAvailability(result);
    const stateLabel = row.querySelector(".result-card-state");
    if (stateLabel) {
      stateLabel.className = `result-card-state status-${availability.tag}`;
      stateLabel.textContent = availability.label;
    }
  }
  if (state.fp.results.length) {
    document.getElementById("fp-status").textContent = fpStatusMessage();
  }
  syncFpDetailQueueAction();
}

function updateFpResultSelection() {
  for (const row of document.querySelectorAll("#fp-results .row")) {
    const selected = row.dataset.slug === state.fp.selectedSlug;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-current", String(selected));
  }
}

function renderFpResults(appendFrom = 0) {
  const container = document.getElementById("fp-results");
  if (appendFrom <= 0) container.innerHTML = "";

  for (const result of state.fp.results.slice(appendFrom)) {
    const selected = result.slug === state.fp.selectedSlug;
    const queued = state.queuedSlugs.has(result.slug);
    const availability = fpResultAvailability(result);
    const media = fpResultMedia(result);

    const row = document.createElement("div");
    row.className = "row result-card" + (selected ? " selected" : "") + (queued ? " queued" : "");
    row.dataset.slug = result.slug;
    row.setAttribute("aria-current", String(selected));
    row.setAttribute("aria-label", [result.title, result.year].filter(Boolean).join(", "));

    const visual = createResultCardVisual(media, result.title, "movie", !!result.in_jellyfin);

    const copy = document.createElement("span");
    copy.className = "result-card-copy";
    const title = document.createElement("strong");
    title.className = "result-card-title";
    title.translate = false;
    title.textContent = result.title;
    const subtitle = document.createElement("span");
    subtitle.className = "result-card-subtitle";
    subtitle.textContent = (media.genres || []).slice(0, 2).join(" · ") || "Film";
    const meta = document.createElement("span");
    meta.className = "result-card-meta";
    const rating = document.createElement("span");
    rating.className = "result-card-rating";
    rating.textContent = media.rating ? `★ ${media.rating}` : "★ —";
    const year = document.createElement("span");
    year.className = "result-card-year";
    year.textContent = fpResultYear(result) || "Jahr offen";
    const status = document.createElement("span");
    status.className = `result-card-state status-${availability.tag}`;
    status.textContent = availability.label;
    const jellyfin = document.createElement("span");
    setFpJellyfinBadge(jellyfin, !!result.in_jellyfin);
    meta.append(rating, year, status, jellyfin);
    copy.append(title, subtitle, meta);

    const queueToggle = document.createElement("button");
    queueToggle.type = "button";
    queueToggle.className = "pick-flag result-queue-toggle" + (queued ? " is-queued" : "");
    queueToggle.textContent = queued ? "✓" : "+";
    queueToggle.setAttribute("aria-label", queued
      ? `${result.title} aus der Queue entfernen`
      : `${result.title} zur Queue hinzufügen`);
    queueToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleFpPick(result.slug);
    });

    row.append(visual, copy, queueToggle);
    activateResultCard(row, () => selectFpRow(result.slug));
    container.appendChild(row);
  }

  document.getElementById("fp-status").textContent = fpStatusMessage();
}

function applyFpResults(data, { append = false } = {}) {
  const incoming = Array.isArray(data.results) ? data.results : [];
  for (const result of incoming) {
    if (result?.tmdb_id) state.fp.metadataCache[result.slug] = { ...result };
  }
  const appendFrom = append ? state.fp.results.length : 0;
  state.fp.results = append
    ? mergeCatalogItems(state.fp.results, incoming, (item) => item.slug)
    : incoming;
  state.fp.page = data.page || 1;
  state.fp.category = data.category ?? state.fp.category;
  state.fp.lastPageFull = Boolean(data.has_more ?? data.last_page_full);
  state.fp.sources = mergeCatalogSources(state.fp.sources, data.sources, append);
  state.fp.loadingMore = false;
  state.fp.loadError = "";
  if (!append) state.fp.selectedSlug = null;
  const pendingSlugs = new Set(
    state.fp.results
      .filter((result) => !state.fp.metadataCache[result.slug])
      .map((result) => result.slug),
  );
  state.fp.pendingPreload = pendingSlugs.size ? pendingSlugs : null;
  renderFpResults(appendFrom);
  refreshMovieFeatureCandidates();
  updateFpInfiniteState();
  if (pendingSlugs.size) void preloadTmdbMetadata(state.fp.requestSeq);
}

async function loadFpMetadata(item, requestId = state.fp.requestSeq) {
  let metadata = state.fp.metadataCache[item.slug];
  if (metadata && state.fp.selectedSlug === item.slug) {
    showFpDetail(item.slug, metadataPreviewMovie(metadata), true);
  }
  try {
    if (!metadata) {
      const response = await api.tmdbMovies([{ slug: item.slug, title: item.title, year: item.year || "" }]);
      if (requestId !== state.fp.requestSeq) return null;
      metadata = response.movies?.[item.slug] || null;
      if (metadata) {
        state.fp.metadataCache[item.slug] = metadata;
        updateFpResultCard(item.slug);
        refreshMovieFeatureCandidates();
      }
      if (state.fp.selectedSlug === item.slug) {
        showFpDetail(item.slug, metadataPreviewMovie(metadata || basicMovieMetadata(item)), true);
      }
    }
    if (metadata && !metadata.details_loaded) {
      const detailResponse = await api.tmdbMovie({
        slug: item.slug,
        title: item.title,
        year: item.year || "",
        tmdb_id: item.tmdb_id || null,
      });
      if (requestId !== state.fp.requestSeq) return metadata;
      if (detailResponse.movie) {
        metadata = detailResponse.movie;
        state.fp.metadataCache[item.slug] = metadata;
        updateFpResultCard(item.slug);
        refreshMovieFeatureCandidates();
        if (state.fp.selectedSlug === item.slug) showFpDetail(item.slug, metadataPreviewMovie(metadata), true);
      }
    }
    if (metadata?.tmdb_id) refreshFpJellyfinStatus();
    return metadata || null;
  } catch (e) {
    if (requestId === state.fp.requestSeq && state.fp.selectedSlug === item.slug) {
      showFpDetail(item.slug, metadataPreviewMovie(metadata || basicMovieMetadata(item)), true);
    }
    return metadata || null;
  }
}

async function preloadTmdbMetadata(requestId) {
  const items = state.fp.results
    .filter((r) => !state.fp.metadataCache[r.slug])
    .map((r) => ({ slug: r.slug, title: r.title, year: r.year || "" }));
  if (!items.length) {
    state.fp.pendingPreload = null;
    return;
  }
  const visibleSlugs = new Set(items.map((item) => item.slug));
  const batches = [];
  for (let index = 0; index < items.length; index += FP_METADATA_BATCH_SIZE) {
    batches.push(items.slice(index, index + FP_METADATA_BATCH_SIZE));
  }
  let nextBatch = 0;

  const loadNextBatch = async () => {
    while (nextBatch < batches.length) {
      const batch = batches[nextBatch++];
      let response;
      try {
        response = await api.tmdbMovies(batch);
      } catch (e) {
        continue;
      }
      if (requestId !== state.fp.requestSeq) return;
      for (const [slug, metadata] of Object.entries(response.movies || {})) {
        if (!visibleSlugs.has(slug)) continue;
        if (!state.fp.metadataCache[slug]?.details_loaded) {
          state.fp.metadataCache[slug] = metadata;
        }
        state.fp.pendingPreload?.delete(slug);
        updateFpResultCard(slug);
      }
      refreshMovieFeatureCandidates();
      const selected = state.fp.selectedSlug;
      if (selected && batch.some((item) => item.slug === selected)
          && !state.fp.moviesCache[selected] && state.fp.metadataCache[selected]) {
        showFpDetail(selected, metadataPreviewMovie(state.fp.metadataCache[selected]), true);
      }
    }
  };

  try {
    const workerCount = Math.min(FP_METADATA_BATCH_CONCURRENCY, batches.length);
    await Promise.all(Array.from({ length: workerCount }, () => loadNextBatch()));
    if (requestId !== state.fp.requestSeq) return;
    refreshFpJellyfinStatus();
  } catch (e) { /* Anbieter-Metadaten bleiben als Fallback sichtbar. */ }
  finally {
    if (requestId !== state.fp.requestSeq) return;
    state.fp.pendingPreload = null;
    for (const slug of visibleSlugs) updateFpResultCard(slug);
    refreshMovieFeatureCandidates();
  }
}

function clearFpSearchContext() {
  state.fp.searchActive = false;
  state.fp.searchReturn = null;
  document.getElementById("fp-search").value = "";
  syncSearchClearButtons();
  closeSearchSuggestions("fp-search-suggestions", "fp-search");
}

function rememberFpSearchContext() {
  if (state.fp.searchActive || state.fp.searchReturn) return;
  if (!state.fp.category && !state.fp.results.length) return;
  state.fp.searchReturn = {
    results: state.fp.results.slice(),
    category: state.fp.category,
    page: state.fp.page,
    lastPageFull: state.fp.lastPageFull,
    activeGenre: state.fp.activeGenre,
    selectedSlug: state.fp.selectedSlug,
    sources: state.fp.sources.slice(),
  };
}

async function restoreFpSearchContext() {
  if (!state.fp.searchActive && !state.fp.searchReturn) return;
  const saved = state.fp.searchReturn;
  state.fp.searchActive = false;
  state.fp.searchReturn = null;
  document.getElementById("fp-search").value = "";
  ++state.fp.requestSeq;
  if (!saved) {
    await fpShowList("new");
    return;
  }
  applyFpResults({
    results: saved.results,
    category: saved.category,
    page: saved.page,
    has_more: saved.lastPageFull,
    sources: saved.sources,
  });
  setActiveGenreFilter(saved.activeGenre);
  state.fp.selectedSlug = saved.selectedSlug;
  renderFpResults();
}

async function fpSearch() {
  const q = document.getElementById("fp-search").value.trim();
  if (!q) {
    await restoreFpSearchContext();
    return;
  }
  rememberSearch(q, "movie");
  closeSearchSuggestions("fp-search-suggestions", "fp-search");
  rememberFpSearchContext();
  state.fp.searchActive = true;
  state.fp.category = null;
  state.fp.lastPageFull = false;
  state.fp.loadingMore = false;
  state.fp.loadError = "";
  updateFpInfiniteState();
  refreshMovieFeatureCandidates();
  document.getElementById("fp-status").textContent = `Suche nach «${q}» …`;
  setActiveGenreFilter("Alle Genres");
  const requestId = ++state.fp.requestSeq;
  try {
    const data = await api.movies({ mode: "search", query: q });
    if (requestId !== state.fp.requestSeq) return;
    applyFpResults(data);
  } catch (error) {
    // Ohne diesen Zweig blieb der Status bei «Suche nach …» stehen: eine
    // abgelaufene Sitzung oder ein Providerfehler sah aus wie „kein Treffer“.
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadingMore = false;
    state.fp.loadError = error.message;
    updateFpInfiniteState();
    document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
  }
}

async function fpShowList(category) {
  clearFpSearchContext();
  state.fp.category = category;
  state.fp.lastPageFull = false;
  state.fp.loadingMore = true;
  state.fp.loadError = "";
  updateFpInfiniteState();
  refreshMovieFeatureCandidates();
  setActiveGenreFilter("Alle Genres");
  document.getElementById("fp-status").textContent = `Lade ${category === "new" ? "Neu" : "Top"}-Filme …`;
  const requestId = ++state.fp.requestSeq;
  try {
    const data = await api.movies({ mode: category, page: 1 });
    if (requestId !== state.fp.requestSeq) return;
    applyFpResults(data);
  } catch (error) {
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadingMore = false;
    state.fp.loadError = error.message;
    updateFpInfiniteState();
    document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
  }
}

function ensureFpResults() {
  if (state.fp.results.length || state.fp.loadingMore) return;
  fpShowList("new");
}

async function fpGenreChange(genre) {
  clearFpSearchContext();
  if (genre === "Alle Genres") {
    await fpShowList("new");
    return;
  }
  state.fp.category = "genre";
  state.fp.lastPageFull = false;
  state.fp.loadingMore = true;
  state.fp.loadError = "";
  updateFpInfiniteState();
  refreshMovieFeatureCandidates();
  setActiveGenreFilter(genre);
  document.getElementById("fp-status").textContent = `Lade Genre ${genre} …`;
  const requestId = ++state.fp.requestSeq;
  try {
    const data = await api.movies({ mode: "genre", genre, page: 1 });
    if (requestId !== state.fp.requestSeq) return;
    applyFpResults(data);
  } catch (error) {
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadingMore = false;
    state.fp.loadError = error.message;
    updateFpInfiniteState();
    document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
  }
}

async function loadNextFpPage() {
  if (
    state.tab !== "filme"
    || !state.fp.category
    || state.fp.searchActive
    || state.fp.loadingMore
    || !state.fp.lastPageFull
  ) return;
  const newPage = state.fp.page + 1;
  const params = state.fp.category === "genre"
    ? { mode: "genre", genre: state.fp.activeGenre, page: newPage }
    : { mode: state.fp.category, page: newPage };
  const requestId = ++state.fp.requestSeq;
  state.fp.loadingMore = true;
  state.fp.loadError = "";
  updateFpInfiniteState();
  try {
    const data = await api.movies(params);
    if (requestId !== state.fp.requestSeq) return;
    applyFpResults(data, { append: true });
  } catch (error) {
    if (requestId !== state.fp.requestSeq) return;
    state.fp.loadError = error.message;
    document.getElementById("fp-status").textContent = `Nachladen fehlgeschlagen: ${error.message}`;
  } finally {
    if (requestId === state.fp.requestSeq) {
      state.fp.loadingMore = false;
      updateFpInfiniteState();
      // Fuellt einen noch zu kurzen Container automatisch weiter, ohne dass der
      // Nutzer scrollen muss. Bricht von selbst ab, sobald genug Inhalt da ist
      // oder der Katalog endet (Guards in loadNextFpPage).
      recheckFpInfinite();
    }
  }
}

async function toggleFpPick(slug) {
  if (state.queuedSlugs.has(slug)) {
    const resp = await api.queueRemove(slug);
    refreshQueueUiAfterChange(resp);
    return;
  }
  const resp = await api.queueAdd([slug]);
  if (Number(resp.added || 0) > 0) {
    const item = state.fp.moviesCache[slug]
      || state.fp.metadataCache[slug]
      || state.fp.results.find((movie) => movie.slug === slug)
      || homeMovieBySlug(slug);
    trackDiscoveryPreference("movie", { ...item, slug }, 5, "download");
  }
  if (!state.fp.moviesCache[slug]) {
    try {
      state.fp.moviesCache[slug] = await api.movie(slug);
      updateFpResultCard(slug);
    } catch (e) { /* server logs */ }
  }
  refreshQueueUiAfterChange(resp);
}

async function selectFpRow(slug, initialItem = null) {
  state.fp.selectedSlug = slug;
  updateFpResultSelection();
  const movie = state.fp.moviesCache[slug];
  const item = state.fp.results.find((r) => r.slug === slug)
    || homeMovieBySlug(slug)
    || initialItem;
  if (!item) return;
  const metadata = state.fp.metadataCache[slug];
  trackDiscoveryPreference("movie", { ...item, ...metadata, slug }, 0.8, "open");
  if (movie) showFpDetail(slug, movie);
  else if (metadata) showFpDetail(slug, metadataPreviewMovie(metadata), true);
  else {
    showFpDetail(slug, basicMovieMetadata(item), true);
    setFpDetailAvailability("Metadaten werden geladen", "loading");
  }
  openMediaModal("fp-detail-modal", findFpResultCard(slug));
  if (movie) return;
  await loadFpMetadata(item);
  if (!String(slug).startsWith("tmdb:") || state.fp.selectedSlug !== slug) return;
  setFpDetailAvailability("Alle Anbieter werden durchsucht", "loading");
  try {
    const resolved = await api.movie(slug);
    state.fp.moviesCache[slug] = resolved;
    updateFpResultCard(slug);
    if (state.fp.selectedSlug === slug) showFpDetail(slug, resolved);
  } catch (error) {
    console.warn("Anbietersuche fehlgeschlagen:", error);
    if (state.fp.selectedSlug === slug) {
      const preview = state.fp.metadataCache[slug] || basicMovieMetadata(item);
      showFpDetail(slug, metadataPreviewMovie(preview), true);
      setFpDetailAvailability(error.message, "error");
    }
  }
}

function basicMovieMetadata(item) {
  return { title: item.title, year: item.year || "", cover_url: "", description: "", genres: [], runtime: "" };
}

function metadataPreviewMovie(metadata) {
  return {
    ...metadata,
    hosters: [],
    hoster_route: "wird geladen",
    hoster_score: null,
    hoster_fallback_count: 0,
  };
}

function renderFpDetailItems(id, values, emptyText = "") {
  const element = document.getElementById(id);
  element.innerHTML = "";
  const items = (values || []).filter(Boolean);
  if (!items.length && emptyText) items.push(emptyText);
  for (const value of items) {
    const item = document.createElement("span");
    item.textContent = value;
    element.appendChild(item);
  }
}

function setFpDetailAvailability(text, state = "ready") {
  const badge = document.getElementById("fp-detail-availability");
  badge.textContent = text;
  badge.className = `detail-availability is-${state}`;
}

function setFpDetailJellyfinStatus(owned) {
  const badge = document.getElementById("fp-detail-jellyfin");
  const label = badge.querySelector("strong");
  badge.className = "detail-jellyfin";
  if (owned === true) {
    badge.classList.add("is-owned");
    label.textContent = "In Jellyfin vorhanden";
    return;
  }
  if (owned === false) {
    badge.classList.add("is-missing");
    label.textContent = "Nicht in Jellyfin";
    return;
  }
  badge.classList.add("is-checking");
  label.textContent = "Jellyfin wird geprüft";
}

function fpDetailJellyfinValue(slug, movie) {
  const catalogItem = state.fp.results.find((item) => item.slug === slug)
    || homeMovieBySlug(slug);
  if (typeof catalogItem?.in_jellyfin === "boolean") return catalogItem.in_jellyfin;
  if (typeof movie?.in_jellyfin === "boolean") return movie.in_jellyfin;
  return null;
}

function formatMovieDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) return value || "—";
  const date = new Date(`${value}T00:00:00Z`);
  return new Intl.DateTimeFormat(i18n.locale(), {
    day: "2-digit", month: "long", year: "numeric", timeZone: "UTC",
  }).format(date);
}

function formatMovieNumber(value) {
  const number = Number(value || 0);
  return number > 0 ? new Intl.NumberFormat(i18n.locale()).format(number) : "";
}

function formatMovieMoney(value) {
  const number = Number(value || 0);
  if (number <= 0) return "";
  return new Intl.NumberFormat(i18n.locale(), {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
    notation: number >= 1_000_000 ? "compact" : "standard",
  }).format(number);
}

function movieCertificationLabel(movie) {
  const certification = String(movie.certification || "").trim();
  if (!certification) return "Nicht angegeben";
  const country = String(movie.certification_country || "").toUpperCase();
  if (country === "DE") return `FSK ${certification}`;
  return country ? `${country} ${certification}` : certification;
}

function movieStatusLabel(status) {
  return ({
    Released: "Veröffentlicht",
    "Post Production": "Postproduktion",
    "In Production": "In Produktion",
    Planned: "Geplant",
    Rumored: "Gerücht",
    Canceled: "Abgebrochen",
  })[status] || status || "";
}

function setFpDetailText(id, value, fallback = "—") {
  document.getElementById(id).textContent = value || fallback;
}

function renderFpCast(cast, tmdbUrl) {
  const section = document.getElementById("fp-detail-cast-section");
  const container = document.getElementById("fp-detail-cast");
  const link = document.getElementById("fp-detail-tmdb-link");
  const members = Array.isArray(cast) ? cast.filter((member) => member?.name) : [];
  section.hidden = !members.length;
  container.innerHTML = "";
  const safeTmdbUrl = /^https:\/\/www\.themoviedb\.org\/movie\/\d+$/.test(tmdbUrl || "");
  link.href = safeTmdbUrl ? tmdbUrl : "https://www.themoviedb.org";
  if (!members.length) return;
  for (const member of members) {
    const card = document.createElement("div");
    card.className = "detail-cast-card";
    const portrait = document.createElement("div");
    portrait.className = "detail-cast-portrait";
    if (member.profile_url) {
      const image = document.createElement("img");
      image.src = api.coverUrl(member.profile_url);
      image.alt = "";
      image.loading = "lazy";
      portrait.appendChild(image);
    } else {
      portrait.textContent = member.name
        .split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
    }
    const copy = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = member.name;
    const role = document.createElement("small");
    role.textContent = member.character || "Besetzung";
    copy.append(name, role);
    card.append(portrait, copy);
    container.appendChild(card);
  }
}

let fpDetailHeroTrailerTimer = null;
let fpDetailHeroTrailerToken = 0;
let fpDetailHeroTrailerCurrentTime = 0;
let fpDetailHeroTrailerKey = "";
const FP_TRAILER_MUTED_KEY = "royal-trailer-muted-v1";
const heroTrailerTimeResolvers = new Map();

function loadFpDetailHeroTrailerMuted() {
  try {
    const saved = localStorage.getItem(FP_TRAILER_MUTED_KEY);
    return saved === null ? true : saved !== "false";
  } catch {
    return true;
  }
}

let fpDetailHeroTrailerMuted = loadFpDetailHeroTrailerMuted();

function fpTrailerYoutubeKey(movie) {
  const trailer = movie?.trailer;
  const key = String(trailer?.key || "").trim();
  return trailer?.site === "YouTube" && /^[A-Za-z0-9_-]{6,20}$/.test(key) ? key : "";
}

function setFpDetailHeroTrailerMuted(muted, { persist = false } = {}) {
  fpDetailHeroTrailerMuted = Boolean(muted);
  if (persist) {
    try {
      localStorage.setItem(FP_TRAILER_MUTED_KEY, String(fpDetailHeroTrailerMuted));
    } catch {
      // Gesperrter Browser-Speicher darf die Trailersteuerung nicht blockieren.
    }
  }
  const enabled = !fpDetailHeroTrailerMuted;
  for (const [frameId, buttonId] of [
    ["fp-detail-hero-frame", "fp-detail-hero-mute"],
    ["series-detail-hero-frame", "series-detail-hero-mute"],
  ]) {
    const frame = document.getElementById(frameId);
    const button = document.getElementById(buttonId);
    frame?.contentWindow?.postMessage(JSON.stringify({
      event: "command",
      func: fpDetailHeroTrailerMuted ? "mute" : "unMute",
      args: [],
    }), "*");
    if (!button) continue;
    button.setAttribute("aria-pressed", String(enabled));
    button.setAttribute("aria-label", enabled ? "Trailerton ausschalten" : "Trailerton einschalten");
    button.title = enabled ? "Trailerton ausschalten" : "Trailerton einschalten";
    button.querySelector("span").textContent = enabled ? "🔊" : "🔇";
  }
}

window.addEventListener("message", (event) => {
  if (!["https://www.youtube-nocookie.com", "https://www.youtube.com"].includes(event.origin)) return;
  let payload = event.data;
  if (typeof payload === "string") {
    try { payload = JSON.parse(payload); } catch { return; }
  }
  const currentTime = Number(payload?.info?.currentTime);
  if (!Number.isFinite(currentTime) || currentTime < 0) return;
  for (const [frameId, kind] of [
    ["fp-detail-hero-frame", "film"],
    ["series-detail-hero-frame", "series"],
  ]) {
    const frame = document.getElementById(frameId);
    if (!frame || event.source !== frame.contentWindow) continue;
    if (kind === "film") fpDetailHeroTrailerCurrentTime = currentTime;
    else seriesDetailHeroTrailerCurrentTime = currentTime;
    const resolve = heroTrailerTimeResolvers.get(frameId);
    if (resolve) {
      heroTrailerTimeResolvers.delete(frameId);
      resolve(currentTime);
    }
    break;
  }
});

function listenForHeroTrailerTime(frame) {
  if (!frame?.contentWindow) return;
  const subscribe = () => frame.contentWindow?.postMessage(JSON.stringify({
    event: "listening",
    id: frame.id,
    channel: frame.id,
  }), "*");
  subscribe();
  window.setTimeout(subscribe, 250);
  window.setTimeout(subscribe, 750);
}

function readHeroTrailerCurrentTime(frameId, fallback = 0) {
  const frame = document.getElementById(frameId);
  if (!frame?.getAttribute("src") || !frame.contentWindow) return Promise.resolve(fallback);
  return new Promise((resolve) => {
    let finished = false;
    const finish = (value) => {
      if (finished) return;
      finished = true;
      heroTrailerTimeResolvers.delete(frameId);
      resolve(Number.isFinite(value) ? value : fallback);
    };
    heroTrailerTimeResolvers.set(frameId, finish);
    listenForHeroTrailerTime(frame);
    frame.contentWindow.postMessage(JSON.stringify({
      event: "command", func: "getCurrentTime", args: [],
    }), "*");
    window.setTimeout(() => finish(fallback), 500);
  });
}

function stopFpDetailHeroTrailer() {
  fpDetailHeroTrailerToken += 1;
  if (fpDetailHeroTrailerTimer) clearTimeout(fpDetailHeroTrailerTimer);
  fpDetailHeroTrailerTimer = null;
  const panel = document.getElementById("fp-detail-panel");
  const shell = document.getElementById("fp-detail-hero-trailer");
  const frame = document.getElementById("fp-detail-hero-frame");
  const muteButton = document.getElementById("fp-detail-hero-mute");
  shell.classList.remove("is-playing");
  panel.classList.remove("is-trailer-playing");
  muteButton.hidden = true;
  frame.onload = null;
  frame.removeAttribute("src");
  shell.hidden = true;
  setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
  fpDetailHeroTrailerKey = "";
}

function scheduleFpDetailHeroTrailer(movie) {
  stopFpDetailHeroTrailer();
  const key = fpTrailerYoutubeKey(movie);
  if (!key || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  fpDetailHeroTrailerKey = key;
  fpDetailHeroTrailerCurrentTime = 0;
  const token = fpDetailHeroTrailerToken;
  fpDetailHeroTrailerTimer = setTimeout(() => {
    if (
      token !== fpDetailHeroTrailerToken
      || document.getElementById("fp-detail-modal").hidden
    ) return;
    const panel = document.getElementById("fp-detail-panel");
    const shell = document.getElementById("fp-detail-hero-trailer");
    const frame = document.getElementById("fp-detail-hero-frame");
    const muteButton = document.getElementById("fp-detail-hero-mute");
    setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
    shell.hidden = false;
    frame.onload = () => {
      if (token !== fpDetailHeroTrailerToken) return;
      listenForHeroTrailerTime(frame);
      shell.classList.add("is-playing");
      panel.classList.add("is-trailer-playing");
      muteButton.hidden = false;
      setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
    };
    frame.src =
      `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
      + `?autoplay=1&mute=1&controls=0&loop=1&playlist=${encodeURIComponent(key)}`
      + `&playsinline=1&rel=0&modestbranding=1&enablejsapi=1`
      + `&origin=${encodeURIComponent(window.location.origin)}`;
  }, 2000);
}

function closeFpTrailerModal(restoreFocus = true) {
  const modal = document.getElementById("fp-trailer-modal");
  if (!modal || modal.hidden) return;
  const returnFocus = modal._returnFocus;
  modal.classList.remove("is-open");
  modal.hidden = true;
  document.body.classList.remove("trailer-modal-open");
  document.getElementById("fp-trailer-frame")?.removeAttribute("src");
  if (restoreFocus && returnFocus instanceof HTMLElement && returnFocus.isConnected) {
    returnFocus.focus();
  }
}

async function openFpTrailerModal(movie, trigger, heroKind = "film") {
  const trailer = movie?.trailer;
  const key = String(trailer?.key || "").trim();
  if (trailer?.site !== "YouTube" || !/^[A-Za-z0-9_-]{6,20}$/.test(key)) return;
  const isSeriesHero = heroKind === "series" && seriesDetailHeroTrailerKey === key;
  const isFilmHero = heroKind === "film" && fpDetailHeroTrailerKey === key;
  const startAt = isSeriesHero
    ? await readHeroTrailerCurrentTime("series-detail-hero-frame", seriesDetailHeroTrailerCurrentTime)
    : isFilmHero
      ? await readHeroTrailerCurrentTime("fp-detail-hero-frame", fpDetailHeroTrailerCurrentTime)
      : 0;
  stopFpDetailHeroTrailer();
  stopSeriesDetailHeroTrailer();
  const modal = document.getElementById("fp-trailer-modal");
  modal._returnFocus = trigger instanceof HTMLElement ? trigger : document.activeElement;
  document.getElementById("fp-trailer-title").textContent = `${movie.title || "Film"} · Trailer`;
  document.getElementById("fp-trailer-caption").textContent = trailer.name || "Offizieller Trailer";
  document.getElementById("fp-trailer-frame").src =
    `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}?autoplay=1&rel=0`
    + `${startAt >= 1 ? `&start=${Math.floor(startAt)}` : ""}`
    + `&origin=${encodeURIComponent(window.location.origin)}`;
  modal.hidden = false;
  modal.classList.add("is-open");
  document.body.classList.add("trailer-modal-open");
  requestAnimationFrame(() => document.getElementById("fp-trailer-close")?.focus());
}

function configureFpTrailer(movie) {
  const button = document.getElementById("fp-detail-trailer");
  const trailerKey = fpTrailerYoutubeKey(movie);
  const available = Boolean(trailerKey);
  const trailer = movie?.trailer;
  button.hidden = !available;
  const trailerMovie = available
    ? { ...movie, trailer: { ...trailer, key: trailerKey } }
    : null;
  button.onclick = trailerMovie ? () => openFpTrailerModal(trailerMovie, button, "film") : null;
  if (!available) {
    closeFpTrailerModal(false);
    stopFpDetailHeroTrailer();
  } else {
    scheduleFpDetailHeroTrailer(trailerMovie);
  }
}

function configureFpDetailAction(slug, movie, metadataOnly = false) {
  const addBtn = document.getElementById("fp-detail-add");
  const queued = state.queuedSlugs.has(slug);
  const hasHosters = Array.isArray(movie.hosters) && movie.hosters.length > 0;
  addBtn.disabled = !queued && !metadataOnly && !hasHosters;
  addBtn.textContent = queued ? "✕ Aus Queue entfernen" : "↓ Herunterladen";

  addBtn.onclick = async () => {
    const shouldRemove = state.queuedSlugs.has(slug);
    addBtn.disabled = true;
    addBtn.textContent = shouldRemove ? "Entferne …" : metadataOnly ? "Prüfe …" : "Füge hinzu …";
    try {
      if (metadataOnly) {
        await toggleFpPick(slug);
        const loaded = state.fp.moviesCache[slug];
        if (loaded && state.fp.selectedSlug === slug) showFpDetail(slug, loaded);
        else if (state.fp.selectedSlug === slug) showFpDetail(slug, movie, true);
        return;
      }
      const selection = state.fp.downloadSelections.get(slug);
      const resp = shouldRemove
        ? await api.queueRemove(slug)
        : await api.queueAdd([slug], selection ? { [slug]: selection } : {});
      if (!shouldRemove && Number(resp.added || 0) > 0) {
        trackDiscoveryPreference("movie", { ...movie, slug }, 5, "download");
      }
      refreshQueueUiAfterChange(resp);
      if (state.fp.selectedSlug === slug) showFpDetail(slug, movie);
    } catch (error) {
      console.warn("Film konnte nicht zur Queue hinzugefügt werden:", error);
      configureFpDetailAction(slug, movie, metadataOnly);
    }
  };
}

function movieSubscriptionFor(slug, movie) {
  const tmdbId = String(movie?.tmdb_id || "").trim();
  if (tmdbId) {
    return state.movieSubscriptions.items.find(
      (entry) => String(entry.tmdb_id || "") === tmdbId,
    ) || null;
  }
  return state.movieSubscriptions.items.find(
    (entry) => entry.source_slug === slug,
  ) || null;
}

function configureFpSubscriptionAction(slug, movie) {
  const button = document.getElementById("fp-detail-subscribe");
  const fallback = state.fp.results.find((item) => item.slug === slug) || homeMovieBySlug(slug);
  const resolvedMovie = {
    ...(fallback || {}),
    ...(movie || {}),
    title: movie?.title || fallback?.title || "Film",
    year: movie?.year || fallback?.year || "",
  };
  const entry = movieSubscriptionFor(slug, resolvedMovie);
  button.disabled = !slug;
  button.dataset.slug = slug || "";
  button.classList.toggle("is-active", Boolean(entry));
  button.textContent = entry ? "⚙ Film-Abo" : "+ Film abonnieren";
}

function openSelectedMovieSubscription() {
  const button = document.getElementById("fp-detail-subscribe");
  const slug = button?.dataset.slug || state.fp.selectedSlug;
  if (!slug) return;
  const fallback = state.fp.results.find((item) => item.slug === slug) || homeMovieBySlug(slug);
  const movie = {
    ...(fallback || {}),
    ...(state.fp.metadataCache[slug] || {}),
    ...(state.fp.moviesCache[slug] || {}),
  };
  openMovieSubscriptionModal(slug, movie, movieSubscriptionFor(slug, movie));
}

function closeMovieSubscriptionModal() {
  document.getElementById("movie-subscription-modal").classList.add("hidden");
  document.getElementById("movie-subscription-status").textContent = "";
  movieSubscriptionContext = null;
  if (movieSubscriptionReturnFocus instanceof HTMLElement && movieSubscriptionReturnFocus.isConnected) {
    movieSubscriptionReturnFocus.focus();
  }
  movieSubscriptionReturnFocus = null;
}

function openMovieSubscriptionModal(slug, movie, stored = null) {
  const entry = stored || movieSubscriptionFor(slug, movie);
  movieSubscriptionReturnFocus = document.activeElement;
  movieSubscriptionContext = {
    key: entry?.key || "",
    sourceSlug: entry?.source_slug || slug,
    title: entry?.title || movie?.title || "Film",
    year: String(entry?.year || movie?.year || ""),
    tmdbId: entry?.tmdb_id || movie?.tmdb_id || null,
    coverUrl: entry?.cover_url || movie?.cover_url || "",
    tracked: Boolean(entry),
  };
  document.getElementById("movie-subscription-title").textContent = movieSubscriptionContext.title;
  document.querySelectorAll('input[name="movie-target-quality"]').forEach((radio) => {
    radio.checked = radio.value === (entry?.target_quality || "best");
  });
  document.querySelectorAll('input[name="movie-cleanup"]').forEach((radio) => {
    radio.checked = radio.value === (entry?.cleanup_mode || "keep");
  });
  document.getElementById("movie-upgrade-enabled").checked = entry?.upgrade_enabled !== false;
  document.getElementById("movie-subscription-remove").classList.toggle("hidden", !entry);
  document.getElementById("movie-subscription-save").textContent =
    entry ? "Regel übernehmen" : "Abo speichern";
  document.getElementById("movie-subscription-status").textContent =
    !state.jellyfinUserConfigured
      && document.querySelector('input[name="movie-cleanup"]:checked')?.value === "watched"
      ? "Für die Gesehen-Löschung muss unter Einstellungen ein Jellyfin-Profil gewählt sein."
      : "";
  document.getElementById("movie-subscription-modal").classList.remove("hidden");
  setTimeout(() => document.querySelector('input[name="movie-target-quality"]:checked')?.focus(), 0);
}

async function saveMovieSubscription() {
  if (!movieSubscriptionContext) return;
  const button = document.getElementById("movie-subscription-save");
  button.disabled = true;
  try {
    const response = await api.movieSubscriptionSave({
      source_slug: movieSubscriptionContext.sourceSlug,
      title: movieSubscriptionContext.title,
      year: movieSubscriptionContext.year,
      tmdb_id: movieSubscriptionContext.tmdbId,
      cover_url: movieSubscriptionContext.coverUrl,
      target_quality: document.querySelector('input[name="movie-target-quality"]:checked')?.value || "best",
      cleanup_mode: document.querySelector('input[name="movie-cleanup"]:checked')?.value || "keep",
      upgrade_enabled: document.getElementById("movie-upgrade-enabled").checked,
    });
    applyMovieSubscriptions(response.movie_subscriptions || []);
    closeMovieSubscriptionModal();
  } catch (error) {
    document.getElementById("movie-subscription-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function removeMovieSubscription() {
  if (!movieSubscriptionContext?.key) return;
  const response = await api.movieSubscriptionsRemove([movieSubscriptionContext.key]);
  applyMovieSubscriptions(response.movie_subscriptions || []);
  closeMovieSubscriptionModal();
}

function movieSubscriptionStatus(entry) {
  if (entry.status === "watched_deleted") return "Gesehen · gelöscht";
  if (entry.cleanup_last_error) return entry.cleanup_last_error;
  if (entry.status === "queued") return `Upgrade ${entry.upgrade_available_quality || ""} in Queue`.trim();
  if (entry.status === "failed") return entry.last_error || "Prüfung fehlgeschlagen";
  if (entry.status === "upgrade") return `${entry.upgrade_available_quality || "Besser"} verfügbar`;
  const current = entry.current_quality || (
    entry.current_quality_rank ? `${entry.current_quality_rank}p` : "Noch keine Fassung"
  );
  return `${current} · Ziel ${entry.target_quality_label || "Beste Qualität"}`;
}

function applyMovieSubscriptions(items) {
  state.movieSubscriptions.items = items;
  state.movieSubscriptions.loaded = true;
  renderMovieSubscriptions();
  if (state.fp.selectedSlug) {
    const movie = state.fp.moviesCache[state.fp.selectedSlug]
      || state.fp.metadataCache[state.fp.selectedSlug];
    if (movie) configureFpSubscriptionAction(state.fp.selectedSlug, movie);
  }
}

function renderMovieSubscriptions() {
  const container = document.getElementById("movie-subscriptions-list");
  if (!container) return;
  const items = state.movieSubscriptions.items;
  document.getElementById("movie-subscriptions-count").textContent =
    items.length
      ? `${items.length} ${items.length === 1 ? "Film wird" : "Filme werden"} überwacht`
      : "Noch keine Filme überwacht";
  document.getElementById("movie-subscriptions-check").disabled = !items.length;
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "subscriptions-empty";
    const mark = document.createElement("span");
    mark.className = "subscriptions-empty-mark";
    mark.textContent = "＋";
    mark.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = "Erstes Film-Abo anlegen";
    const hint = document.createElement("small");
    hint.textContent = "Film öffnen und „Film abonnieren“ wählen.";
    copy.append(title, hint);
    empty.append(mark, copy);
    container.appendChild(empty);
    return;
  }
  for (const entry of items) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "subscription-card"
      + (["failed", "upgrade"].includes(entry.status) ? " has-new" : "");
    card.dataset.status = entry.status || "current";
    card.setAttribute("aria-label", `${entry.title}: ${movieSubscriptionStatus(entry)}`);
    const monogram = document.createElement("span");
    monogram.className = "subscription-monogram";
    monogram.textContent = subscriptionMonogram(entry.title);
    const copy = document.createElement("span");
    copy.className = "subscription-text";
    const title = document.createElement("span");
    title.className = "subscription-name";
    title.textContent = entry.title;
    title.translate = false;
    const meta = document.createElement("span");
    meta.className = "subscription-meta";
    meta.textContent = movieSubscriptionStatus(entry);
    copy.append(title, meta);
    const signal = document.createElement("span");
    signal.className = "movie-subscription-signal";
    const signalDot = document.createElement("i");
    signalDot.setAttribute("aria-hidden", "true");
    const signalLabel = document.createElement("span");
    signalLabel.textContent = {
      queued: "In Queue",
      failed: "Fehler",
      upgrade: "Upgrade",
      watched_deleted: "Erledigt",
    }[entry.status] || "Aktuell";
    signal.append(signalDot, signalLabel);
    const open = document.createElement("span");
    open.className = "movie-subscription-open";
    open.textContent = "›";
    open.setAttribute("aria-hidden", "true");
    card.append(monogram, copy, signal, open);
    card.addEventListener("click", () => openMovieSubscriptionModal(entry.source_slug, null, entry));
    container.appendChild(card);
  }
}

function movieQualityRank(value) {
  const text = String(value || "").toUpperCase();
  const resolution = Number(text.match(/(\d{3,4})\s*P?/)?.[1] || 0);
  if (resolution) return resolution;
  if (text.includes("UHD") || text.includes("4K")) return 2160;
  if (text.includes("FULL HD") || text.includes("FHD")) return 1080;
  if (text.includes("HD")) return 720;
  if (text.includes("SD")) return 480;
  return 0;
}

function renderFpDownloadSources(slug, movie, metadataOnly) {
  const section = document.getElementById("fp-detail-sources-section");
  const container = document.getElementById("fp-detail-sources");
  container.innerHTML = "";
  const sources = metadataOnly || !Array.isArray(movie.source_providers)
    ? []
    : movie.source_providers.filter((source) => Array.isArray(source.hosters) && source.hosters.length);
  section.hidden = !sources.length;
  if (!sources.length) return;

  const options = [];
  for (const source of sources) {
    const qualities = [...new Set(source.hosters.map((hoster) => String(hoster.quality || "").trim()))];
    qualities.sort((a, b) => movieQualityRank(b) - movieQualityRank(a) || a.localeCompare(b));
    for (const quality of qualities) {
      const matching = source.hosters.filter(
        (hoster) => String(hoster.quality || "").trim() === quality,
      );
      options.push({
        provider: source.key,
        providerLabel: source.label || source.key,
        quality,
        qualityLabel: quality || "Qualität unbekannt",
        hosterCount: matching.length,
        rank: movieQualityRank(quality),
      });
    }
  }
  options.sort((a, b) => b.rank - a.rank);
  const stored = state.fp.downloadSelections.get(slug);
  const selected = options.find(
    (option) => option.provider === stored?.provider && option.quality === stored?.quality,
  ) || options[0];
  if (selected) {
    state.fp.downloadSelections.set(slug, {
      provider: selected.provider,
      quality: selected.quality,
    });
  }

  for (const option of options) {
    const label = document.createElement("label");
    label.className = "detail-source-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = `movie-source-${slug}`;
    input.checked = option === selected;
    input.addEventListener("change", () => {
      state.fp.downloadSelections.set(slug, {
        provider: option.provider,
        quality: option.quality,
      });
    });
    const copy = document.createElement("span");
    const provider = document.createElement("strong");
    provider.textContent = option.providerLabel;
    const details = document.createElement("small");
    details.textContent = `${option.qualityLabel} · ${option.hosterCount} Hoster`;
    copy.append(provider, details);
    label.append(input, copy);
    container.appendChild(label);
  }
}

function showFpDetail(slug, movie, metadataOnly = false) {
  const detailPanel = document.getElementById("fp-detail-panel");
  const cover = document.getElementById("fp-detail-cover");
  // Die Abo-Aktion darf nicht von späteren Metadaten-/Hosterfeldern abhängen.
  configureFpSubscriptionAction(slug, movie);
  cover.loading = "eager";
  cover.fetchPriority = "high";
  detailPanel.classList.remove("is-empty");
  detailPanel.classList.toggle("has-no-cover", !movie.cover_url);
  if (movie.cover_url) {
    const coverUrl = api.coverUrl(movie.cover_url);
    if (cover.getAttribute("src") !== coverUrl) cover.src = coverUrl;
    const backdropUrl = api.coverUrl(movie.backdrop_url || movie.cover_url).replace(/"/g, "%22");
    detailPanel.style.setProperty("--detail-backdrop-image", `url("${backdropUrl}")`);
  } else if (cover.hasAttribute("src")) {
    cover.removeAttribute("src");
    detailPanel.style.removeProperty("--detail-backdrop-image");
  } else {
    detailPanel.style.removeProperty("--detail-backdrop-image");
  }
  cover.alt = movie.title ? `Poster zu ${movie.title}` : "Filmplakat";
  document.getElementById("fp-detail-title").textContent = movie.title;
  const metaParts = [];
  if (movie.year) metaParts.push(movie.year);
  if (movie.runtime) metaParts.push(movie.runtime);
  if (movie.rating) {
    metaParts.push(
      `★ ${movie.rating}/10${movie.vote_count ? ` · ${formatMovieNumber(movie.vote_count)} Stimmen` : ""}`,
    );
  }
  if (!metadataOnly) {
    if (movie.provider_count) {
      metaParts.push(`${movie.provider_count} Anbieter`);
    }
    metaParts.push(movie.hoster_total
      ? `${movie.hoster_total} Hoster gesamt`
      : (movie.hosters.length ? `${movie.hosters.length} Hoster` : "kein Hoster"));
  }
  if (movie.metadata_source) metaParts.push(movie.metadata_source);
  renderFpDetailItems("fp-detail-meta", metaParts, "Keine Metadaten");
  renderFpDetailItems("fp-detail-genres", movie.genres, "Genre unbekannt");
  const tagline = document.getElementById("fp-detail-tagline");
  tagline.textContent = movie.tagline || "";
  tagline.hidden = !movie.tagline;
  setFpDetailJellyfinStatus(fpDetailJellyfinValue(slug, movie));
  if (metadataOnly) setFpDetailAvailability("Streams werden geprüft", "loading");
  else if (movie.hosters.length) {
    setFpDetailAvailability(
      movie.provider_count
        ? `${movie.provider_count} Anbieter · ${movie.hoster_total || movie.hosters.length} Hoster`
        : `${movie.hosters.length} Hoster bereit`,
      "ready",
    );
  }
  else setFpDetailAvailability("Kein Hoster verfügbar", "error");
  setFpDetailText("fp-detail-original-title", movie.original_title);
  setFpDetailText("fp-detail-release", formatMovieDate(movie.release_date));
  setFpDetailText("fp-detail-certification", movieCertificationLabel(movie));
  const languages = (movie.spoken_languages || []).slice(0, 2).join(", ")
    || (movie.original_language ? movie.original_language.toUpperCase() : "");
  const origin = [
    languages,
    ...(movie.countries || []),
  ].filter(Boolean).join(" · ");
  setFpDetailText("fp-detail-origin", origin);
  setFpDetailText("fp-detail-directors", (movie.directors || []).join(", "));
  setFpDetailText("fp-detail-writers", (movie.writers || []).join(", "));
  setFpDetailText("fp-detail-studios", (movie.production_companies || []).join(", "));
  const insights = [];
  const status = movieStatusLabel(movie.status);
  const budget = formatMovieMoney(movie.budget);
  const revenue = formatMovieMoney(movie.revenue);
  if (status) insights.push(`Status · ${status}`);
  if (movie.collection) insights.push(`Reihe · ${movie.collection}`);
  if (budget) insights.push(`Budget · ${budget}`);
  if (revenue) insights.push(`Einspiel · ${revenue}`);
  renderFpDetailItems("fp-detail-insights", insights);
  renderFpDetailItems("fp-detail-keywords", movie.keywords || []);
  renderFpCast(movie.cast, movie.tmdb_url);
  renderFpDownloadSources(slug, movie, metadataOnly);
  document.getElementById("fp-detail-route-card").classList.toggle("is-loading", metadataOnly);
  setFpDetailText(
    "fp-detail-route",
    metadataOnly ? "Streams werden geprüft" : (movie.provider_route || movie.hoster_route),
  );
  setFpDetailText(
    "fp-detail-score",
    metadataOnly ? "Noch offen" : (movie.hoster_score != null ? String(movie.hoster_score) : ""),
  );
  setFpDetailText(
    "fp-detail-fallback",
    metadataOnly
      ? "Noch offen"
      : (movie.hosters.length
        ? (movie.provider_count
          ? `${movie.provider_fallback_count || 0} Anbieter · ${movie.hoster_fallback_count || 0} Hoster`
          : `${movie.hoster_fallback_count} Alternativen`)
        : ""),
  );
  document.getElementById("fp-detail-desc").textContent = movie.description || "(keine Beschreibung)";

  configureFpTrailer(movie);
  configureFpDetailAction(slug, movie, metadataOnly);
  updateTasteFeedbackButtons();
}

// ── Serien-Tab ─────────────────────────────────────────────────────────────
function buildAlphaBar() {
  const bar = document.getElementById("series-alpha-bar");
  const letters = ["0-9", ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))];
  for (const l of letters) {
    const btn = document.createElement("button");
    btn.textContent = l;
    btn.addEventListener("click", () => seriesBrowse(`alpha:${l}`, 1));
    bar.appendChild(btn);
  }
}

function firstEpisodeSlug(series) {
  for (const s of series.seasons) if (s.episodes.length) return s.episodes[0].slug;
  return "";
}

function seriesEpisodes(series = state.series.current) {
  return series?.seasons?.flatMap((season) => season.episodes || []) || [];
}

function isEpisodeQueued(episode) {
  return Boolean(episode?.queued || state.queuedSlugs.has(episode?.slug));
}

function isEpisodeSelectable(episode) {
  return Boolean(
    episode
    && state.series.current?.availability_pending !== true
    && state.series.current?.jellyfin_pending !== true
    && state.series.current?.jellyfin_available !== false
    && !episode.downloaded
    && !episode.in_jellyfin
    && !episode.unreleased
    && !isEpisodeQueued(episode)
  );
}

function syncSeriesQueueFlags(series = null) {
  const candidates = series
    ? [series]
    : [state.series.current, ...Object.values(state.series.cache)];
  const visited = new Set();
  for (const candidate of candidates) {
    if (!candidate || visited.has(candidate)) continue;
    visited.add(candidate);
    if (state.queue.loaded) {
      for (const episode of seriesEpisodes(candidate)) {
        episode.queued = state.queuedSlugs.has(episode.slug);
      }
    }
  }
  if (!series || series === state.series.current) {
    pruneSeriesEpisodeSelection();
    renderSeriesTiles();
  }
}

function pruneSeriesEpisodeSelection() {
  const selectableSlugs = new Set(
    seriesEpisodes().filter(isEpisodeSelectable).map((episode) => episode.slug),
  );
  state.series.epPicked = new Set(
    [...state.series.epPicked].filter((slug) => selectableSlugs.has(slug)),
  );
}

function findCurrentEpisode(slug) {
  return seriesEpisodes().find((episode) => episode.slug === slug) || null;
}

function updateSeriesInfiniteState() {
  const sentinel = document.getElementById("series-infinite");
  if (!sentinel) return;
  const label = document.getElementById("series-infinite-label");
  const retry = document.getElementById("series-infinite-retry");
  const mode = state.series.browseMode;
  const browsable = Boolean(mode && mode !== "search" && state.series.results.length);
  sentinel.classList.toggle("hidden", !browsable);
  if (!browsable) return;

  const count = state.series.results.length;
  sentinel.setAttribute("aria-busy", String(state.series.loadingBrowse));
  retry.hidden = !state.series.loadError
    && (catalogInfiniteObserverSupported || !state.series.lastPageFull);
  retry.textContent = state.series.loadError ? "Erneut versuchen" : "Weitere laden";
  if (state.series.loadingBrowse) {
    sentinel.dataset.state = "loading";
    label.textContent = "Weitere Serien werden geladen …";
  } else if (state.series.loadError) {
    sentinel.dataset.state = "error";
    label.textContent = `Nachladen fehlgeschlagen · ${count} Serien geladen`;
  } else if (state.series.lastPageFull) {
    sentinel.dataset.state = "ready";
    label.textContent = `${count} Serien geladen · Weiter scrollen`;
  } else {
    sentinel.dataset.state = "complete";
    label.textContent = `${count} Serien geladen · Ende des Katalogs`;
  }
  const sourceSummary = state.series.sources
    .map((source) => `${source.label} ${source.count}`)
    .join(" · ");
  sentinel.title = sourceSummary;
}

function renderSeriesCatalogHero() {
  const feature = document.getElementById("series-feature");
  if (!feature) return;
  const catalogCandidate = state.series.results.find((result) => result.backdrop_url);
  const featuredHomeSeries = [
    ...state.home.trendingSeries,
    ...state.home.newSeries,
    ...state.home.discoverySeries,
  ].find((result) => result.backdrop_url);
  const candidate = catalogCandidate
    || (state.series.browseMode !== "search" ? featuredHomeSeries : null)
    || state.series.results[0];
  if (!candidate) {
    feature.classList.add("hidden");
    return;
  }
  const artwork = candidate.backdrop_url || candidate.cover_url || "";
  const posterArtwork = !candidate.backdrop_url && Boolean(candidate.cover_url);
  feature.classList.remove("hidden");
  feature.classList.toggle("has-no-art", !artwork);
  feature.classList.toggle("is-poster-art", posterArtwork);
  feature.setAttribute("aria-label", `Serie im Fokus: ${candidate.title}`);
  document.getElementById("series-feature-art").style.backgroundImage = artwork
    ? `url("${api.coverUrl(artwork).replace(/"/g, "%22")}")`
    : "";
  document.getElementById("series-feature-title").textContent = candidate.title;
  const sources = Array.isArray(candidate.sources) ? candidate.sources : [];
  document.getElementById("series-feature-meta").textContent = [
    candidate.year || "",
    candidate.rating ? `★ ${candidate.rating}` : "",
    ...(candidate.genres || []).slice(0, 2),
    sources.length > 1 ? `${sources.length} Quellen` : (candidate.provider_label || sources[0]?.label || ""),
  ].filter(Boolean).join(" · ");
  document.getElementById("series-feature-description").textContent =
    candidate.description || "Staffeln, Episoden und Verfügbarkeit direkt im Royal Archiv entdecken.";
  document.getElementById("series-feature-open").onclick = () => loadSeries(candidate);
}

function renderSeriesResults(appendFrom = 0) {
  const container = document.getElementById("series-results");
  if (appendFrom <= 0) container.innerHTML = "";

  for (const result of state.series.results.slice(appendFrom)) {
    const selectedBase = state.series.pendingBaseSlug || state.series.current?.base_slug;
    const selected = selectedBase === result.base_slug;
    const loading = state.series.pendingBaseSlug === result.base_slug;
    const resultSources = Array.isArray(result.sources) ? result.sources : [];
    const sourceLabels = resultSources.map((source) => source.label).filter(Boolean);
    const sourceSummary = sourceLabels.length > 1
      ? `${sourceLabels.length} Quellen`
      : (sourceLabels[0] || result.provider_label || "Quelle offen");

    const row = document.createElement("div");
    row.className = "series-row result-card" + (selected ? " selected" : "") + (loading ? " loading" : "");
    row.dataset.baseSlug = result.base_slug;
    row.setAttribute("aria-current", String(selected));
    row.setAttribute("aria-label", [result.title, result.year].filter(Boolean).join(", "));
    if (loading) row.setAttribute("aria-busy", "true");

    const visual = createResultCardVisual(result, result.title, "series");
    const copy = document.createElement("span");
    copy.className = "result-card-copy";
    const title = document.createElement("strong");
    title.className = "result-card-title";
    title.translate = false;
    title.textContent = result.title;
    const subtitle = document.createElement("span");
    subtitle.className = "result-card-subtitle";
    subtitle.textContent = sourceSummary;
    subtitle.title = sourceLabels.join(" · ");
    const meta = document.createElement("span");
    meta.className = "result-card-meta";
    const year = document.createElement("span");
    year.textContent = result.year || "Jahr offen";
    const stateLabel = document.createElement("span");
    stateLabel.className = "result-card-state status-ready";
    stateLabel.textContent = loading ? "Öffnet …" : "Staffeln öffnen";
    meta.append(year, stateLabel);
    copy.append(title, subtitle, meta);

    row.append(visual, copy);
    activateResultCard(row, () => loadSeries(result));
    container.appendChild(row);
  }
}

function findSeriesResultCard(baseSlug) {
  return [...document.querySelectorAll("#series-results .series-row")]
    .find((row) => row.dataset.baseSlug === baseSlug) || null;
}

function updateSeriesResultArtwork(baseSlug) {
  const result = state.series.results.find((item) => item.base_slug === baseSlug);
  const row = findSeriesResultCard(baseSlug);
  if (!result || !row) return;
  row.querySelector(".result-card-visual")?.replaceWith(
    createResultCardVisual(result, result.title, "series"),
  );
}

function updateSeriesResultSelection() {
  const selectedBase = state.series.pendingBaseSlug || state.series.current?.base_slug;
  document.querySelectorAll("#series-results .series-row").forEach((row) => {
    const loading = state.series.pendingBaseSlug === row.dataset.baseSlug;
    const selected = selectedBase === row.dataset.baseSlug;
    row.classList.toggle("selected", selected);
    row.classList.toggle("loading", loading);
    row.setAttribute("aria-current", String(selected));
    if (loading) row.setAttribute("aria-busy", "true");
    else row.removeAttribute("aria-busy");
  });
}

function applySeriesResults(data, { append = false } = {}) {
  const incoming = Array.isArray(data.results) ? data.results : [];
  const appendFrom = append ? state.series.results.length : 0;
  state.series.results = append
    ? mergeCatalogItems(
      state.series.results,
      incoming,
      (item) => item.base_slug || item.sample_slug || item.sample_url,
    )
    : incoming;
  state.series.page = data.page || 1;
  state.series.lastPageFull = Boolean(data.has_more ?? data.last_page_full);
  state.series.sources = mergeCatalogSources(state.series.sources, data.sources, append);
  state.series.loadError = "";
  renderSeriesResults(appendFrom);
  renderSeriesCatalogHero();
  void hydrateHomeSeriesArtwork(state.series.results, { render: false }).then((hydratedBaseSlugs) => {
    for (const baseSlug of hydratedBaseSlugs) updateSeriesResultArtwork(baseSlug);
    renderSeriesCatalogHero();
  });
  updateSeriesInfiniteState();
  const sourceCount = state.series.sources.length;
  document.getElementById("series-status").textContent =
    state.series.results.length
      ? (sourceCount
        ? `${state.series.results.length} Serie(n) · ${sourceCount} ${sourceCount === 1 ? "Quelle" : "Quellen"}`
        : `${state.series.results.length} Serie(n) gefunden`)
      : "Keine Serie gefunden.";
}

function clearSeriesSearchContext() {
  state.series.searchReturn = null;
  document.getElementById("series-search").value = "";
  syncSearchClearButtons();
  closeSearchSuggestions("series-search-suggestions", "series-search");
}

function rememberSeriesSearchContext() {
  if (state.series.searchReturn || state.series.browseMode === "search") return;
  if (!state.series.browseMode && !state.series.results.length) return;
  state.series.searchReturn = {
    results: state.series.results.slice(),
    browseMode: state.series.browseMode,
    page: state.series.page,
    lastPageFull: state.series.lastPageFull,
    sources: state.series.sources.slice(),
    current: state.series.current,
    currentSampleSlug: state.series.currentSampleSlug,
    epPicked: new Set(state.series.epPicked),
  };
}

async function restoreSeriesSearchContext() {
  if (state.series.browseMode !== "search" && !state.series.searchReturn) return;
  const saved = state.series.searchReturn;
  state.series.searchReturn = null;
  document.getElementById("series-search").value = "";
  ++state.series.browseRequestSeq;
  state.series.loadingBrowse = false;
  if (!saved) {
    await seriesBrowse("discover", 1);
    return;
  }
  state.series.browseMode = saved.browseMode;
  state.series.current = saved.current;
  state.series.currentSampleSlug = saved.currentSampleSlug;
  state.series.epPicked = new Set(saved.epPicked);
  applySeriesResults({
    results: saved.results,
    page: saved.page,
    has_more: saved.lastPageFull,
    sources: saved.sources,
  });
  renderSeriesTiles();
}

async function seriesSearch() {
  const q = document.getElementById("series-search").value.trim();
  if (!q) {
    await restoreSeriesSearchContext();
    return;
  }
  rememberSearch(q, "series");
  closeSearchSuggestions("series-search-suggestions", "series-search");
  rememberSeriesSearchContext();
  const requestId = ++state.series.browseRequestSeq;
  const previousMode = state.series.browseMode;
  state.series.browseMode = "search";
  state.series.loadingBrowse = true;
  state.series.loadError = "";
  updateSeriesInfiniteState();
  document.getElementById("series-status").textContent = `Suche nach «${q}» …`;
  try {
    const data = await api.series({ mode: "search", query: q });
    if (requestId !== state.series.browseRequestSeq) return;
    applySeriesResults(data);
    if (data.direct_series) {
      showSeriesDetail(data.direct_series, firstEpisodeSlug(data.direct_series));
      updateSeriesStatus(data.direct_series);
      refreshSeriesJellyfinStatus();
    }
  } catch (error) {
    if (requestId !== state.series.browseRequestSeq) return;
    state.series.browseMode = state.series.results.length ? previousMode : null;
    updateSeriesInfiniteState();
    document.getElementById("series-status").textContent = `Fehler: ${error.message}`;
  } finally {
    if (requestId === state.series.browseRequestSeq) {
      state.series.loadingBrowse = false;
      updateSeriesInfiniteState();
      // Fuellt einen noch zu kurzen Container automatisch weiter (Guards in
      // loadNextSeriesPage brechen ab, sobald genug da ist oder Ende erreicht).
      recheckSeriesInfinite();
    }
  }
}

function seriesParams(mode, page) {
  // Alpha-Modi kommen als "alpha:X"; "new"/"trending" direkt als Modusname.
  return mode.startsWith("alpha:")
    ? { mode: "alpha", letter: mode.split(":")[1], page }
    : { mode, page };
}

async function seriesBrowse(mode, page, { append = false } = {}) {
  if (mode !== "search") clearSeriesSearchContext();
  const requestId = ++state.series.browseRequestSeq;
  const previousMode = state.series.browseMode;
  const previousLastPageFull = state.series.lastPageFull;
  state.series.browseMode = mode;
  state.series.loadingBrowse = true;
  state.series.loadError = "";
  if (!append) state.series.lastPageFull = false;
  updateSeriesInfiniteState();
  const modeLabels = { discover: "interessante Serien", new: "neue Serien", trending: "angesagte Serien" };
  if (!append) {
    document.getElementById("series-status").textContent = `Lade ${modeLabels[mode] || "Serien"} …`;
  }
  try {
    const data = await api.series(seriesParams(mode, page));
    if (requestId !== state.series.browseRequestSeq) return false;
    applySeriesResults(data, { append });
    return true;
  } catch (error) {
    if (requestId !== state.series.browseRequestSeq) return false;
    document.getElementById("series-status").textContent = append
      ? `Nachladen fehlgeschlagen: ${error.message}`
      : `Fehler: ${error.message}`;
    if (append) {
      state.series.loadError = error.message;
    } else {
      state.series.loadError = "";
      state.series.browseMode = state.series.results.length ? previousMode : null;
      state.series.lastPageFull = previousLastPageFull;
    }
    return false;
  } finally {
    if (requestId === state.series.browseRequestSeq) {
      state.series.loadingBrowse = false;
      updateSeriesInfiniteState();
    }
  }
}

function ensureSeriesResults() {
  if (state.series.results.length || state.series.loadingBrowse) return;
  seriesBrowse("discover", 1);
}

async function loadNextSeriesPage() {
  const mode = state.series.browseMode;
  if (
    state.tab !== "serien"
    || !mode
    || mode === "search"
    || state.series.loadingBrowse
    || !state.series.lastPageFull
  ) return;
  await seriesBrowse(mode, state.series.page + 1, { append: true });
}

async function loadSeries(result) {
  const cacheKey = result.base_slug || result.sample_slug;
  if (state.series.pendingBaseSlug === cacheKey) return;
  trackDiscoveryPreference("series", result, 0.8, "open");
  const requestId = ++state.series.requestSeq;
  state.series.pendingBaseSlug = cacheKey;
  updateSeriesResultSelection();
  showSeriesLoading(result);
  openMediaModal("series-detail-modal", findSeriesResultCard(result.base_slug));

  const cached = state.series.cache[cacheKey];
  if (cached) {
    const enriched = {
      ...result,
      ...cached,
      backdrop_url: cached.backdrop_url || result.backdrop_url || "",
    };
    showSeriesDetail(enriched, result.sample_slug);
    updateSeriesStatus(enriched);
    refreshSeriesJellyfinStatus();
    return;
  }

  document.getElementById("series-status").textContent = `Öffne Staffeln für «${result.title}» …`;
  try {
    const loaded = await api.seriesLoad(result.sample_slug, result.base_slug || "", false, true);
    if (requestId !== state.series.requestSeq) return;
    const series = {
      ...result,
      ...loaded,
      backdrop_url: loaded.backdrop_url || result.backdrop_url || "",
    };
    showSeriesDetail(series, result.sample_slug);
    updateSeriesStatus(series);
    refreshSeriesJellyfinStatus();
  } catch (e) {
    if (requestId !== state.series.requestSeq) return;
    state.series.pendingBaseSlug = "";
    updateSeriesResultSelection();
    document.getElementById("series-status").textContent = `Fehler: ${e.message}`;
    document.getElementById("series-detail-title").textContent = `${result.title} · Laden fehlgeschlagen`;
    document.getElementById("series-desc").textContent = e.message;
    const loading = document.querySelector("#series-tiles .series-loading");
    if (loading) loading.textContent = "Serie konnte nicht geladen werden";
  }
}

function showSeriesLoading(result) {
  state.series.viewGeneration += 1;
  state.series.current = null;
  document.getElementById("series-detail-title").textContent = result.title;
  updateSeriesJellyfinBadge(result, true);
  setSeriesDetailArtwork(result);
  const cover = document.getElementById("series-cover");
  cover.loading = "eager";
  cover.fetchPriority = "high";
  if (result.cover_url) cover.src = api.coverUrl(result.cover_url);
  else cover.removeAttribute("src");
  const sourceLabels = (Array.isArray(result.sources) ? result.sources : [])
    .map((source) => source.label)
    .filter(Boolean);
  const previewMeta = [result.year, ...sourceLabels].filter(Boolean);
  if (!sourceLabels.length && result.provider_label) previewMeta.push(result.provider_label);
  renderSeriesDetailMeta(previewMeta);
  document.getElementById("series-desc").textContent =
    "Die Serie ist geöffnet. Staffel- und Episodenstruktur wird beim Anbieter eingelesen.";
  configureSeriesTrailer(result);
  const tiles = document.getElementById("series-tiles");
  tiles.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "series-loading";
  loading.textContent = "Staffeln werden eingelesen …";
  tiles.appendChild(loading);
  document.getElementById("series-pick-count").textContent = "wird geladen";
  document.getElementById("series-watch-btn").disabled = true;
  document.getElementById("series-select-all").disabled = true;
  document.getElementById("series-select-none").disabled = true;
  document.getElementById("series-add-btn").disabled = true;
}

function renderSeriesDetailMeta(values) {
  const container = document.getElementById("series-genres");
  container.replaceChildren();
  for (const value of values.filter(Boolean)) {
    const item = document.createElement("span");
    item.textContent = value;
    container.appendChild(item);
  }
}

function updateWatchBtn() {
  const btn = document.getElementById("series-watch-btn");
  const series = state.series.current;
  if (!series) return;
  const tracked = series.watchlisted;
  const label = WATCH_MODE_LABELS[series.watch_mode] || WATCH_MODE_LABELS[WATCH_MODE_DEFAULT];
  btn.textContent = tracked ? `✓ Abo · ${label}` : "+ Abonnieren";
  btn.title = tracked ? "Abo-Regel ändern" : "Serie abonnieren und Downloadumfang festlegen";
  btn.classList.toggle("btn-accent", tracked);
}

function setSeriesDetailArtwork(series) {
  const panel = document.querySelector("#series-detail-modal .series-detail-panel");
  // Das Hero ist ein 16:9-Wallpaper. Hochformat-Poster dürfen hier nie als
  // Ersatz erscheinen, da sie aufgezoomt und abgeschnitten wirken.
  const artwork = series?.backdrop_url || "";
  panel.classList.toggle("has-no-art", !artwork);
  if (!artwork) {
    panel.style.removeProperty("--series-backdrop-image");
    return;
  }
  const backdropUrl = api.coverUrl(artwork).replace(/"/g, "%22");
  panel.style.setProperty("--series-backdrop-image", `url("${backdropUrl}")`);
}

let seriesDetailHeroTrailerTimer = null;
let seriesDetailHeroTrailerToken = 0;
let seriesDetailHeroTrailerCurrentTime = 0;
let seriesDetailHeroTrailerKey = "";

function stopSeriesDetailHeroTrailer() {
  seriesDetailHeroTrailerToken += 1;
  if (seriesDetailHeroTrailerTimer) clearTimeout(seriesDetailHeroTrailerTimer);
  seriesDetailHeroTrailerTimer = null;
  const panel = document.querySelector("#series-detail-modal .series-detail-panel");
  const shell = document.getElementById("series-detail-hero-trailer");
  const frame = document.getElementById("series-detail-hero-frame");
  const muteButton = document.getElementById("series-detail-hero-mute");
  if (!panel || !shell || !frame || !muteButton) return;
  shell.classList.remove("is-playing");
  panel.classList.remove("is-trailer-playing");
  muteButton.hidden = true;
  frame.onload = null;
  frame.removeAttribute("src");
  shell.hidden = true;
  seriesDetailHeroTrailerKey = "";
  setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
}

function scheduleSeriesDetailHeroTrailer(series) {
  const key = fpTrailerYoutubeKey(series);
  if (!key || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
    stopSeriesDetailHeroTrailer();
    return;
  }
  const shell = document.getElementById("series-detail-hero-trailer");
  if (seriesDetailHeroTrailerKey === key && (!shell.hidden || seriesDetailHeroTrailerTimer)) return;
  stopSeriesDetailHeroTrailer();
  seriesDetailHeroTrailerKey = key;
  seriesDetailHeroTrailerCurrentTime = 0;
  const token = seriesDetailHeroTrailerToken;
  seriesDetailHeroTrailerTimer = setTimeout(() => {
    if (
      token !== seriesDetailHeroTrailerToken
      || document.getElementById("series-detail-modal").hidden
    ) return;
    const panel = document.querySelector("#series-detail-modal .series-detail-panel");
    const frame = document.getElementById("series-detail-hero-frame");
    const muteButton = document.getElementById("series-detail-hero-mute");
    shell.hidden = false;
    frame.onload = () => {
      if (token !== seriesDetailHeroTrailerToken) return;
      listenForHeroTrailerTime(frame);
      shell.classList.add("is-playing");
      panel.classList.add("is-trailer-playing");
      muteButton.hidden = false;
      setFpDetailHeroTrailerMuted(fpDetailHeroTrailerMuted);
    };
    frame.src =
      `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}`
      + `?autoplay=1&mute=1&controls=0&loop=1&playlist=${encodeURIComponent(key)}`
      + `&playsinline=1&rel=0&modestbranding=1&enablejsapi=1`
      + `&origin=${encodeURIComponent(window.location.origin)}`;
  }, 2000);
}

function configureSeriesTrailer(series) {
  const button = document.getElementById("series-detail-trailer");
  const trailerKey = fpTrailerYoutubeKey(series);
  const available = Boolean(trailerKey);
  const trailerSeries = available
    ? { ...series, trailer: { ...series.trailer, key: trailerKey } }
    : null;
  button.hidden = !available;
  button.onclick = trailerSeries
    ? () => openFpTrailerModal(trailerSeries, button, "series")
    : null;
  if (available) scheduleSeriesDetailHeroTrailer(trailerSeries);
  else stopSeriesDetailHeroTrailer();
}

function updateSeriesOverview(series) {
  document.getElementById("series-detail-title").textContent = series.title;
  setSeriesDetailArtwork(series);
  const cover = document.getElementById("series-cover");
  cover.loading = "eager";
  cover.fetchPriority = "high";
  if (series.cover_url) cover.src = api.coverUrl(series.cover_url);
  else cover.removeAttribute("src");
  const seriesMeta = [];
  if (series.year) seriesMeta.push(series.year);
  if (series.runtime) seriesMeta.push(series.runtime);
  seriesMeta.push(...(series.genres || []));
  seriesMeta.push(
    `${series.seasons.length} ${series.seasons.length === 1 ? "Staffel" : "Staffeln"}`,
    `${series.episode_count} ${series.episode_count === 1 ? "Episode" : "Episoden"}`,
  );
  if (series.metadata_source) seriesMeta.push(`Metadaten: ${series.metadata_source}`);
  renderSeriesDetailMeta(seriesMeta);
  document.getElementById("series-desc").textContent = series.description || "(keine Beschreibung verfügbar)";
  configureSeriesTrailer(series);
}

function showSeriesDetail(series, sampleSlug) {
  state.series.viewGeneration += 1;
  syncSeriesQueueFlags(series);
  state.series.current = series;
  state.series.currentSampleSlug = sampleSlug;
  state.series.cache[series.base_slug] = series;
  state.series.pendingBaseSlug = "";
  state.series.epPicked = new Set();
  updateSeriesResultSelection();
  updateSeriesOverview(series);
  document.getElementById("series-watch-btn").disabled = false;
  document.getElementById("series-select-all").disabled = false;
  document.getElementById("series-select-none").disabled = false;
  updateWatchBtn();
  renderSeriesTiles();
  updateSeriesStatus(series);
  updateTasteFeedbackButtons();
  openMediaModal("series-detail-modal", findSeriesResultCard(series.base_slug));
}

function tileClass(ep) {
  if (isEpisodeQueued(ep)) return "queued";
  if (ep.downloaded) return "downloaded";
  if (state.series.epPicked.has(ep.slug) && isEpisodeSelectable(ep)) return "selected";
  return "available";
}

function renderSeriesTiles() {
  const container = document.getElementById("series-tiles");
  container.innerHTML = "";
  const series = state.series.current;
  if (!series) { document.getElementById("series-pick-count").textContent = "0 ausgewählt"; return; }
  pruneSeriesEpisodeSelection();
  if (series.availability_pending) {
    const warning = document.createElement("div");
    warning.className = "series-loading";
    warning.textContent = series.availability_error
      ? "Auswahl pausiert: Die Verfügbarkeit konnte noch nicht geprüft werden."
      : "Staffeln sind da · Bestand und Metadaten werden im Hintergrund geprüft …";
    container.appendChild(warning);
  } else if (series.jellyfin_available === false) {
    const warning = document.createElement("div");
    warning.className = "series-loading";
    warning.textContent = "Auswahl pausiert: Jellyfin konnte nicht eindeutig abgeglichen werden.";
    container.appendChild(warning);
  }
  const selectableCount = seriesEpisodes(series).filter(isEpisodeSelectable).length;
  for (const seasonObj of series.seasons) {
    const pickedCount = seasonObj.episodes.filter((e) => state.series.epPicked.has(e.slug)).length;
    const row = document.createElement("div");
    row.className = "season-row";
    const seasonBtn = document.createElement("button");
    seasonBtn.className = "season-btn";
    seasonBtn.setAttribute("aria-label", `Staffel ${seasonObj.season}: ${pickedCount} von ${seasonObj.episodes.length} ausgewählt`);
    const seasonLabel = document.createElement("span");
    seasonLabel.textContent = "STAFFEL";
    const seasonNumber = document.createElement("strong");
    seasonNumber.textContent = String(seasonObj.season).padStart(2, "0");
    const seasonCount = document.createElement("small");
    seasonCount.textContent = `${pickedCount}/${seasonObj.episodes.length} gewählt`;
    seasonBtn.append(seasonLabel, seasonNumber, seasonCount);
    seasonBtn.disabled = !seasonObj.episodes.some(isEpisodeSelectable);
    seasonBtn.addEventListener("click", () => toggleSeasonTiles(seasonObj.season));
    row.appendChild(seasonBtn);
    const tiles = document.createElement("div");
    tiles.className = "ep-tiles";
    for (const ep of seasonObj.episodes) {
      const tile = document.createElement("button");
      tile.className = "ep-tile " + tileClass(ep) + (ep.in_jellyfin ? " in-jellyfin" : "");
      tile.setAttribute("aria-label", `Folge ${ep.episode}`);
      const episodeLabel = document.createElement("span");
      episodeLabel.textContent = "FOLGE";
      const episodeNumber = document.createElement("strong");
      episodeNumber.textContent = String(ep.episode).padStart(2, "0");
      tile.append(episodeLabel, episodeNumber);
      tile.disabled = !isEpisodeSelectable(ep);
      if (series.availability_error) tile.title = "Verfügbarkeitsprüfung fehlgeschlagen";
      else if (series.availability_pending) tile.title = "Verfügbarkeit wird geprüft";
      else if (ep.in_jellyfin) tile.title = "Bereits in Jellyfin vorhanden";
      else if (ep.downloaded) tile.title = "Bereits heruntergeladen";
      else if (isEpisodeQueued(ep)) tile.title = "Bereits in der Warteschlange";
      else if (ep.unreleased) tile.title = "Noch nicht veröffentlicht";
      tile.addEventListener("click", () => toggleEpisodeTile(ep.slug));
      tiles.appendChild(tile);
    }
    row.appendChild(tiles);
    container.appendChild(row);
  }
  document.getElementById("series-pick-count").textContent = `${state.series.epPicked.size} ausgewählt`;
  document.getElementById("series-select-all").disabled = selectableCount === 0;
  document.getElementById("series-select-none").disabled = state.series.epPicked.size === 0;
  document.getElementById("series-add-btn").disabled = state.series.epPicked.size === 0;
}

function toggleEpisodeTile(slug) {
  const episode = findCurrentEpisode(slug);
  if (!isEpisodeSelectable(episode)) {
    state.series.epPicked.delete(slug);
    renderSeriesTiles();
    return;
  }
  if (state.series.epPicked.has(slug)) state.series.epPicked.delete(slug);
  else state.series.epPicked.add(slug);
  renderSeriesTiles();
}

function toggleSeasonTiles(season) {
  const seasonObj = state.series.current.seasons.find((s) => s.season === season);
  if (!seasonObj) return;
  const selectable = seasonObj.episodes.filter(isEpisodeSelectable);
  if (!selectable.length) return;
  const allPicked = selectable.every((episode) => state.series.epPicked.has(episode.slug));
  for (const ep of seasonObj.episodes) {
    if (!isEpisodeSelectable(ep) || allPicked) state.series.epPicked.delete(ep.slug);
    else state.series.epPicked.add(ep.slug);
  }
  renderSeriesTiles();
}

function markSeriesSlugDownloaded(slug) {
  const series = state.series.current;
  if (!series) return;
  for (const s of series.seasons) {
    for (const ep of s.episodes) {
      if (ep.slug === slug) { ep.downloaded = true; renderSeriesTiles(); return; }
    }
  }
}

async function seriesAddSelected() {
  pruneSeriesEpisodeSelection();
  if (!state.series.epPicked.size) {
    document.getElementById("series-status").textContent =
      "Keine herunterladbaren Episoden ausgewählt.";
    renderSeriesTiles();
    return;
  }
  const slugs = [...state.series.epPicked];
  document.getElementById("series-status").textContent = `Lade ${slugs.length} Episode(n) …`;
  const addButton = document.getElementById("series-add-btn");
  addButton.disabled = true;
  try {
    const resp = await api.queueAdd(slugs);
    if (Number(resp.added || 0) > 0 && state.series.current) {
      trackDiscoveryPreference("series", state.series.current, 5, "download");
    }
    refreshQueueUiAfterChange(resp);
    document.getElementById("series-status").textContent =
      `${resp.added}/${slugs.length} Episode(n) automatisch gestartet`;
    state.series.epPicked.clear();
  } catch (error) {
    document.getElementById("series-status").textContent =
      `Download konnte nicht gestartet werden: ${error.message}`;
  } finally {
    renderSeriesTiles();
  }
}

// ── Anime ─────────────────────────────────────────────────────────────────
function animeModeTitle(mode) {
  return {
    latest: "Neu im Archiv",
    trending: "Aktuell im Trend",
    popular: "Beliebte Anime",
    search: "Suchergebnisse",
  }[mode] || "Anime";
}

function setAnimeMode(mode) {
  for (const [id, value] of [
    ["anime-latest-btn", "latest"],
    ["anime-trending-btn", "trending"],
    ["anime-popular-btn", "popular"],
  ]) {
    document.getElementById(id).classList.toggle("is-active", mode === value);
  }
  document.getElementById("anime-catalog-title").textContent = animeModeTitle(mode);
}

function renderAnimeFeature() {
  const feature = document.getElementById("anime-featured");
  const anime = state.anime.results[0];
  if (!anime) {
    feature.hidden = true;
    feature.onclick = null;
    return;
  }
  const artwork = anime.banner_url || anime.cover_url || "";
  document.getElementById("anime-featured-art").style.backgroundImage =
    artwork ? `url("${artwork.replace(/"/g, "%22")}")` : "";
  document.getElementById("anime-featured-title").textContent = anime.title;
  const tracks = [
    anime.translations?.dub ? "DUB" : "",
    anime.translations?.sub ? "SUB" : "",
  ].filter(Boolean).join(" + ");
  document.getElementById("anime-featured-meta").textContent = [
    anime.year,
    anime.media_type || "Anime",
    tracks,
  ].filter(Boolean).join(" · ");
  feature.setAttribute("aria-label", `${anime.title} öffnen`);
  feature.onclick = () => openAnimeDetail(anime, feature);
  feature.hidden = false;
}

function renderAnimeResults() {
  const container = document.getElementById("anime-results");
  container.innerHTML = "";
  for (const anime of state.anime.results) {
    const card = document.createElement("button");
    card.className = "anime-card";
    card.type = "button";
    card.dataset.animeId = anime.id;
    const dubCount = Number(anime.translations?.dub || 0);
    const subCount = Number(anime.translations?.sub || 0);
    const count = Math.max(dubCount, subCount, Number(anime.episode_count || 0));
    card.setAttribute("aria-label", `${anime.title}, ${count} Episoden`);
    card.innerHTML = `
      <span class="anime-card-poster">
        ${anime.cover_url
    ? `<img src="${escapeHtml(api.coverUrl(anime.cover_url))}" alt="" loading="lazy">`
    : ""}
        <span class="anime-card-fallback">${escapeHtml(mediaCardInitials(anime.title))}</span>
        <span class="anime-card-type" translate="no">${escapeHtml(anime.media_type || "TV")}</span>
        <span class="anime-card-open" aria-hidden="true">↗</span>
      </span>
      <span class="anime-card-copy">
        <strong translate="no">${escapeHtml(anime.title)}</strong>
        <span class="anime-card-subtitle" translate="no">
          ${escapeHtml([anime.year, count ? `${count} Episoden` : ""].filter(Boolean).join(" · ") || "Anime")}
        </span>
        <span class="anime-card-meta" translate="no">
          ${dubCount ? `<span class="is-dub">DUB <b>${dubCount}</b></span>` : ""}
          ${subCount ? `<span class="is-sub">SUB <b>${subCount}</b></span>` : ""}
        </span>
      </span>
    `;
    card.addEventListener("click", () => openAnimeDetail(anime, card));
    container.appendChild(card);
  }
  if (!state.anime.results.length) {
    const empty = document.createElement("div");
    empty.className = "anime-empty";
    empty.textContent = state.anime.disabledReason
      || (state.anime.mode === "search"
        ? "Kein Anime passt zu dieser Suche."
        : "MKissa meldet momentan keine Anime.");
    container.appendChild(empty);
  }
  renderAnimeFeature();
  document.getElementById("anime-page-label").textContent =
    `Seite ${state.anime.page} · ${state.anime.results.length} Titel`;
  document.getElementById("anime-prev").disabled = state.anime.loading || state.anime.page <= 1;
  document.getElementById("anime-next").disabled = state.anime.loading || !state.anime.hasMore;
}

function clearAnimeSearchContext() {
  state.anime.searchReturn = null;
  state.anime.query = "";
  document.getElementById("anime-search").value = "";
}

function rememberAnimeSearchContext() {
  if (state.anime.searchReturn || state.anime.mode === "search") return;
  if (!state.anime.loaded && !state.anime.results.length) return;
  state.anime.searchReturn = {
    results: state.anime.results.slice(),
    mode: state.anime.mode || "latest",
    query: state.anime.query,
    page: state.anime.page,
    hasMore: state.anime.hasMore,
    disabledReason: state.anime.disabledReason || "",
    status: document.getElementById("anime-status").textContent,
  };
}

async function restoreAnimeSearchContext() {
  if (state.anime.mode !== "search" && !state.anime.searchReturn) return;
  const saved = state.anime.searchReturn;
  state.anime.searchReturn = null;
  document.getElementById("anime-search").value = "";
  ++state.anime.requestSeq;
  state.anime.loading = false;
  if (!saved) {
    await animeBrowse("latest", 1);
    return;
  }
  state.anime.results = saved.results;
  state.anime.mode = saved.mode;
  state.anime.query = saved.query;
  state.anime.page = saved.page;
  state.anime.hasMore = saved.hasMore;
  state.anime.disabledReason = saved.disabledReason;
  setAnimeMode(saved.mode);
  renderAnimeResults();
  document.getElementById("anime-status").textContent = saved.status;
}

async function animeBrowse(mode, page = 1) {
  const query = mode === "search"
    ? document.getElementById("anime-search").value.trim()
    : "";
  if (mode === "search" && !query) {
    await restoreAnimeSearchContext();
    return;
  }
  if (state.anime.loading) return;
  if (mode === "search") rememberAnimeSearchContext();
  else clearAnimeSearchContext();
  state.anime.loading = true;
  const requestSeq = ++state.anime.requestSeq;
  setAnimeMode(mode);
  document.getElementById("anime-status").textContent =
    mode === "search" ? `Suche nach «${query}» …` : `${animeModeTitle(mode)} werden geladen …`;
  renderAnimeResults();
  try {
    const response = await api.anime({ mode, query, page });
    if (requestSeq !== state.anime.requestSeq) return;
    state.anime.results = response.results || [];
    state.anime.mode = mode;
    state.anime.query = query;
    state.anime.page = Number(response.page) || page;
    state.anime.hasMore = !!response.has_more;
    state.anime.loaded = true;
    state.anime.disabledReason = response.disabled ? response.disabled_reason : "";
    const total = Number(response.total) || state.anime.results.length;
    document.getElementById("anime-status").textContent = response.disabled
      ? response.disabled_reason
      : `${state.anime.results.length} Titel auf dieser Seite · ${total.toLocaleString("de-DE")} im Katalog`;
  } catch (error) {
    if (requestSeq !== state.anime.requestSeq) return;
    state.anime.results = [];
    state.anime.hasMore = false;
    state.anime.loaded = true;
    state.anime.disabledReason = error.message;
    document.getElementById("anime-status").textContent = `Fehler: ${error.message}`;
  } finally {
    if (requestSeq === state.anime.requestSeq) {
      state.anime.loading = false;
      renderAnimeResults();
    }
  }
}

async function openAnimeDetail(anime, returnFocus = null) {
  state.anime.currentId = anime.id;
  state.anime.current = { ...anime, episodes: [] };
  state.anime.translation = anime.translations?.dub
    ? "dub"
    : (anime.translations?.sub ? "sub" : Object.keys(anime.translations || {})[0] || "");
  state.anime.episodePage = 1;
  state.anime.picked.clear();
  openMediaModal("anime-detail-modal", returnFocus);
  document.getElementById("anime-detail-title").textContent = anime.title;
  document.getElementById("anime-detail-description").textContent = "Episoden und Sprachspuren werden geladen …";
  trackDiscoveryPreference("anime", { ...anime, base_slug: anime.id }, 0.8, "open");
  await loadAnimeDetail();
}

async function loadAnimeDetail({ keepSelection = false } = {}) {
  const animeId = state.anime.currentId;
  if (!animeId) return;
  const detailSeq = ++state.anime.detailSeq;
  if (!keepSelection) state.anime.picked.clear();
  document.getElementById("anime-pick-count").textContent = "wird geladen";
  document.getElementById("anime-add-btn").disabled = true;
  try {
    const detail = await api.animeDetail(
      animeId,
      state.anime.translation,
      state.anime.episodePage,
    );
    if (detailSeq !== state.anime.detailSeq || animeId !== state.anime.currentId) return;
    state.anime.current = detail;
    state.anime.translation = detail.translation;
    state.anime.episodePage = detail.page;
    syncAnimeQueueFlags();
    renderAnimeDetail();
  } catch (error) {
    if (detailSeq !== state.anime.detailSeq) return;
    document.getElementById("anime-detail-description").textContent = error.message;
    document.getElementById("anime-pick-count").textContent = "nicht verfügbar";
  }
}

function renderAnimeDetail() {
  const anime = state.anime.current;
  if (!anime) return;
  document.getElementById("anime-detail-title").textContent = anime.title;
  const cover = document.getElementById("anime-detail-cover");
  cover.src = api.coverUrl(anime.cover_url || "");
  cover.alt = anime.title;
  document.getElementById("anime-detail-type").textContent = anime.media_type || "TV";
  const banner = document.getElementById("anime-detail-banner");
  banner.style.backgroundImage = anime.banner_url
    ? `url("${api.coverUrl(anime.banner_url).replace(/"/g, "%22")}")`
    : "";
  document.getElementById("anime-detail-description").textContent =
    anime.description || "Keine Beschreibung verfügbar.";
  const meta = [
    anime.year,
    anime.rating ? `★ ${Number(anime.rating).toFixed(1)}` : "",
    ...(anime.genres || []).slice(0, 4),
  ].filter(Boolean);
  document.getElementById("anime-detail-meta").innerHTML =
    meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("");

  const trackOptions = document.getElementById("anime-track-options");
  trackOptions.innerHTML = "";
  for (const [track, countValue] of Object.entries(anime.translations || {})) {
    const count = Number(countValue) || 0;
    if (!count) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `anime-track-option ${track === state.anime.translation ? "is-active" : ""}`;
    button.dataset.track = track;
    button.innerHTML = `
      <strong translate="no">${escapeHtml(track.toUpperCase())}</strong>
      <small translate="no">${escapeHtml(anime.translation_labels?.[track] || track)} · ${count} EP</small>
    `;
    button.addEventListener("click", () => {
      if (track === state.anime.translation) return;
      state.anime.translation = track;
      state.anime.episodePage = 1;
      loadAnimeDetail();
    });
    trackOptions.appendChild(button);
  }
  renderAnimeEpisodes();
}

function renderAnimeEpisodes() {
  const anime = state.anime.current;
  const container = document.getElementById("anime-episode-grid");
  container.innerHTML = "";
  if (!anime?.episodes?.length) {
    container.innerHTML = '<div class="anime-empty">Keine Episoden in dieser Sprachspur.</div>';
    return;
  }
  for (const episode of anime.episodes) {
    const selected = state.anime.picked.has(episode.slug);
    const queued = episode.queued || state.queuedSlugs.has(episode.slug);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "anime-episode"
      + (selected ? " is-selected" : "")
      + (queued ? " is-queued" : "")
      + (episode.downloaded ? " is-downloaded" : "");
    button.textContent = episode.number;
    button.title = episode.downloaded
      ? `${episode.label} · bereits geladen`
      : queued ? `${episode.label} · in der Warteschlange` : episode.label;
    button.disabled = queued || episode.downloaded;
    button.addEventListener("click", () => {
      if (state.anime.picked.has(episode.slug)) state.anime.picked.delete(episode.slug);
      else state.anime.picked.add(episode.slug);
      renderAnimeEpisodes();
    });
    container.appendChild(button);
  }
  const first = anime.episodes[0]?.number || 0;
  const last = anime.episodes.at(-1)?.number || 0;
  document.getElementById("anime-episode-page-label").textContent =
    `Episoden ${first}–${last} · Seite ${anime.page}/${anime.page_count}`;
  document.getElementById("anime-episode-prev").disabled = anime.page <= 1;
  document.getElementById("anime-episode-next").disabled = anime.page >= anime.page_count;
  document.getElementById("anime-pick-count").textContent = `${state.anime.picked.size} ausgewählt`;
  document.getElementById("anime-select-none").disabled = !state.anime.picked.size;
  document.getElementById("anime-add-btn").disabled = !state.anime.picked.size;
}

function syncAnimeQueueFlags() {
  const anime = state.anime.current;
  if (!anime?.episodes) return;
  for (const episode of anime.episodes) {
    episode.queued = state.queuedSlugs.has(episode.slug);
    if (episode.queued) state.anime.picked.delete(episode.slug);
  }
  if (!document.getElementById("anime-detail-modal").hidden) renderAnimeEpisodes();
}

function markAnimeSlugDownloaded(slug) {
  const anime = state.anime.current;
  const episode = anime?.episodes?.find((item) => item.slug === slug);
  if (!episode) return;
  episode.downloaded = true;
  episode.queued = false;
  state.anime.picked.delete(slug);
  renderAnimeEpisodes();
}

async function animeAddSelected() {
  const slugs = [...state.anime.picked];
  if (!slugs.length) return;
  const button = document.getElementById("anime-add-btn");
  button.disabled = true;
  document.getElementById("anime-pick-count").textContent = "wird eingeplant …";
  try {
    const response = await api.queueAdd(slugs, {}, "anime");
    refreshQueueUiAfterChange(response);
    state.anime.picked.clear();
    document.getElementById("anime-status").textContent =
      `${response.added}/${slugs.length} Anime-Episode(n) gestartet`;
  } catch (error) {
    document.getElementById("anime-status").textContent = `Download fehlgeschlagen: ${error.message}`;
  } finally {
    renderAnimeEpisodes();
  }
}

function closeWatchModeModal() {
  document.getElementById("watch-mode-modal").classList.add("hidden");
  document.getElementById("watch-mode-status").textContent = "";
  watchModeContext = null;
  if (watchModeReturnFocus instanceof HTMLElement && watchModeReturnFocus.isConnected) {
    watchModeReturnFocus.focus();
  }
  watchModeReturnFocus = null;
}

function normalizeSeriesIdentityTitle(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function watchlistEntryForSeries(series, items = state.wl.items) {
  if (!series) return null;
  const exact = items.find((item) => item.base_slug === series.base_slug);
  if (exact) return exact;
  const tmdbId = String(series.tmdb_id || "").trim();
  if (tmdbId) {
    const stable = items.filter((item) => String(item.tmdb_id || "").trim() === tmdbId);
    if (stable.length === 1) return stable[0];
  }
  const wantedTitles = new Set([
    series.title, series.original_title, ...(series.aliases || []),
  ].map(normalizeSeriesIdentityTitle).filter(Boolean));
  const matches = items.filter((item) => {
    const storedTmdb = String(item.tmdb_id || "").trim();
    if (tmdbId && storedTmdb && storedTmdb !== tmdbId) return false;
    return [item.title, ...(item.aliases || [])]
      .map(normalizeSeriesIdentityTitle)
      .some((title) => wantedTitles.has(title));
  });
  return matches.length === 1 ? matches[0] : null;
}

function openWatchModeModal(entry = null) {
  const series = state.series.current;
  const stored = entry || watchlistEntryForSeries(series);
  const baseSlug = stored?.base_slug || series?.base_slug;
  if (!baseSlug) return;
  const tracked = Boolean(stored || series?.watchlisted);
  const mode = stored?.download_mode || series?.watch_mode || WATCH_MODE_DEFAULT;
  const cleanupMode = tracked
    ? (stored?.cleanup_mode || series?.cleanup_mode || WATCH_CLEANUP_DEFAULT)
    : state.watchlistCleanupDefault;
  watchModeReturnFocus = document.activeElement;
  const knownSlugs = series?.base_slug === baseSlug
    ? series.seasons.flatMap((season) => season.episodes.map((episode) => episode.slug))
    : (stored?.known_slugs || []);
  watchModeContext = {
    baseSlug,
    title: stored?.title || series?.title || baseSlug,
    sampleUrl: stored?.sample_url || series?.url || "",
    knownSlugs,
    tmdbId: stored?.tmdb_id || series?.tmdb_id || null,
    aliases: stored?.aliases || series?.aliases || [],
    seasonEpisodeCounts: stored?.season_episode_counts || series?.season_episode_counts || {},
    seasonCountsCheckedAt: stored?.season_counts_checked_at || series?.season_counts_checked_at || 0,
    tracked,
  };

  document.getElementById("watch-mode-title").textContent = watchModeContext.title;
  document.querySelectorAll('input[name="watch-mode"]').forEach((radio) => {
    radio.checked = radio.value === mode;
  });
  document.querySelectorAll('input[name="watch-cleanup"]').forEach((radio) => {
    radio.checked = radio.value === cleanupMode;
  });
  document.getElementById("watch-cleanup-description").textContent = tracked
    ? "Diese Löschregel gilt nur für diese Serie und nutzt den Gesehen-Status des gewählten Jellyfin-Profils."
    : `Vorausgewählt aus den Einstellungen: ${WATCH_CLEANUP_LABELS[cleanupMode] || WATCH_CLEANUP_LABELS[WATCH_CLEANUP_DEFAULT]}. Du kannst für diese Serie abweichen.`;
  document.getElementById("watch-mode-remove").classList.toggle("hidden", !tracked);
  document.getElementById("watch-mode-save").textContent = tracked ? "Regel übernehmen" : "Abo speichern";
  document.getElementById("watch-mode-status").textContent = "";
  document.getElementById("watch-mode-modal").classList.remove("hidden");
  updateWatchModeRequirement();
  setTimeout(() => document.querySelector('input[name="watch-mode"]:checked')?.focus(), 0);
}

function updateWatchModeRequirement() {
  const selected = document.querySelector('input[name="watch-mode"]:checked')?.value;
  const cleanupSelected = document.querySelector('input[name="watch-cleanup"]:checked')?.value
    || WATCH_CLEANUP_DEFAULT;
  const status = document.getElementById("watch-mode-status");
  const explanation = WATCH_MODE_EXPLANATIONS[selected] || WATCH_MODE_EXPLANATIONS[WATCH_MODE_DEFAULT];
  document.getElementById("watch-mode-outcome-title").textContent = explanation.title;
  document.getElementById("watch-mode-outcome-copy").textContent = explanation.copy;
  if (!state.jellyfinUserConfigured && (selected === "next_season" || cleanupSelected !== WATCH_CLEANUP_DEFAULT)) {
    const affected = selected === "next_season" && cleanupSelected !== WATCH_CLEANUP_DEFAULT
      ? "Download- und Löschregel warten"
      : (selected === "next_season" ? "Die Downloadregel wartet" : "Die Löschregel wartet");
    status.textContent = `Voraussetzung fehlt: Wähle unter Einstellungen → Jellyfin ein Wiedergabeprofil. ${affected}.`;
  } else if (status.textContent.startsWith("Diese Regel wartet")) {
    status.textContent = "";
  } else if (status.textContent.startsWith("Voraussetzung fehlt")) {
    status.textContent = "";
  }
}

async function saveWatchMode() {
  if (!watchModeContext) return;
  const selected = document.querySelector('input[name="watch-mode"]:checked')?.value;
  const cleanupSelected = document.querySelector('input[name="watch-cleanup"]:checked')?.value
    || WATCH_CLEANUP_DEFAULT;
  if (!selected) return;
  const saveBtn = document.getElementById("watch-mode-save");
  saveBtn.disabled = true;
  try {
    const data = watchModeContext.tracked
      ? await api.watchlistMode(watchModeContext.baseSlug, selected, cleanupSelected)
      : await api.watchlistAdd({
        base_slug: watchModeContext.baseSlug,
        title: watchModeContext.title,
        sample_url: watchModeContext.sampleUrl,
        known_slugs: watchModeContext.knownSlugs,
        download_mode: selected,
        cleanup_mode: cleanupSelected,
        tmdb_id: watchModeContext.tmdbId,
        aliases: watchModeContext.aliases,
        season_episode_counts: watchModeContext.seasonEpisodeCounts,
        season_counts_checked_at: watchModeContext.seasonCountsCheckedAt,
      });
    if (state.series.current?.base_slug === watchModeContext.baseSlug) {
      state.series.current.watchlisted = true;
      state.series.current.watch_mode = selected;
      state.series.current.cleanup_mode = cleanupSelected;
    }
    applyWatchlist(data.watchlist);
    closeWatchModeModal();
  } catch (error) {
    document.getElementById("watch-mode-status").textContent = error.message;
  } finally {
    saveBtn.disabled = false;
  }
}

async function removeWatchModeSubscription() {
  if (!watchModeContext?.tracked) return;
  const data = await api.watchlistRemove([watchModeContext.baseSlug]);
  applyWatchlist(data.watchlist);
  await syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung");
  closeWatchModeModal();
}

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

// ── Einstellungen (Speicherort) ──────────────────────────────────────────────
let dirModalPath = "";
let dirModalTarget = "save-path";   // welches Feld der Ordner-Dialog befüllt

function fillJellyfinUserSelect(selectId, users, selectedId = "", selectedName = "") {
  const select = document.getElementById(selectId);
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = users.length ? "Benutzer auswählen …" : "Benutzer laden …";
  select.appendChild(placeholder);
  for (const user of users) {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.name;
    option.translate = false;
    option.dataset.name = user.name;
    select.appendChild(option);
  }
  if (selectedId && !users.some((user) => user.id === selectedId)) {
    const option = document.createElement("option");
    option.value = selectedId;
    option.textContent = selectedName || "Gespeicherter Benutzer";
    option.translate = false;
    option.dataset.name = selectedName || "";
    select.appendChild(option);
  }
  select.value = selectedId && [...select.options].some((option) => option.value === selectedId)
    ? selectedId
    : (users.length === 1 ? users[0].id : "");
}

async function loadJellyfinUsers({ urlId, keyId, selectId, buttonId, statusId = "" }) {
  const button = document.getElementById(buttonId);
  const select = document.getElementById(selectId);
  const status = statusId ? document.getElementById(statusId) : null;
  const url = document.getElementById(urlId).value.trim();
  const apiKey = document.getElementById(keyId).value.trim();
  button.disabled = true;
  if (status) status.textContent = "Lade Jellyfin-Benutzer …";
  try {
    const data = await api.jellyfinUsers(url, apiKey);
    const previous = select.value;
    fillJellyfinUserSelect(selectId, data.users || [], previous);
    if (status) status.textContent = data.users?.length
      ? `${data.users.length} ${data.users.length === 1 ? "Benutzer" : "Benutzer"} gefunden`
      : "Keine aktiven Jellyfin-Benutzer gefunden";
  } catch (error) {
    if (status) status.textContent = error.message;
    else setSetupStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function providerEnabledSet(mediaType) {
  if (mediaType === "movies") return state.providers.enabledMovies;
  if (mediaType === "anime") return state.providers.enabledAnime;
  return state.providers.enabledSeries;
}

function providerLanguage(provider) {
  return String(state.providers.catalog[provider]?.content_language || "").toLowerCase();
}

function providersForLanguage(language, mediaType) {
  return (state.providers[mediaType] || []).filter(
    (provider) => providerLanguage(provider) === language,
  );
}

function renderContentLanguageSelectors() {
  const ids = ["content-language-options", "setup-content-language-options"];
  const selected = state.providers.contentLanguages;
  for (const id of ids) {
    const container = document.getElementById(id);
    if (!container) continue;
    const context = id.startsWith("setup-") ? "setup" : "settings";
    container.innerHTML = Object.entries(state.providers.languages).map(([language, label]) => {
      const active = selected.has(language);
      const providerCount = new Set([
        ...providersForLanguage(language, "movies"),
        ...providersForLanguage(language, "series"),
        ...providersForLanguage(language, "anime"),
      ]).size;
      return `
        <button class="content-language-card ${active ? "is-selected" : ""}" type="button"
          data-language="${escapeHtml(language)}" aria-pressed="${active}">
          <span class="content-language-code" translate="no">${escapeHtml(language.toUpperCase())}</span>
          <span class="content-language-copy">
            <strong translate="no">${escapeHtml(label)}</strong>
            <small>${providerCount} ${providerCount === 1 ? "Quelle" : "Quellen"}</small>
          </span>
          <span class="content-language-signal" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        </button>
      `;
    }).join("");
    container.querySelectorAll(".content-language-card").forEach((button) => {
      button.addEventListener("click", () => {
        const language = button.dataset.language;
        if (selected.has(language) && selected.size <= 1) {
          setProviderSelectionStatus(context, "Mindestens eine Inhaltssprache muss aktiv bleiben.", true);
          return;
        }
        if (selected.has(language)) {
          const remaining = new Set(selected);
          remaining.delete(language);
          const leavesMovies = state.providers.movies.some(
            (provider) => remaining.has(providerLanguage(provider)),
          );
          const leavesSeries = state.providers.series.some(
            (provider) => remaining.has(providerLanguage(provider)),
          );
          if (!leavesMovies || !leavesSeries) {
            setProviderSelectionStatus(
              context,
              "Die Auswahl benötigt mindestens eine Sprache mit Film- und Serienquellen.",
              true,
            );
            return;
          }
          selected.delete(language);
          for (const mediaType of ["movies", "series", "anime"]) {
            const enabled = providerEnabledSet(mediaType);
            providersForLanguage(language, mediaType).forEach((provider) => enabled.delete(provider));
          }
        } else {
          selected.add(language);
          for (const mediaType of ["movies", "series", "anime"]) {
            const enabled = providerEnabledSet(mediaType);
            providersForLanguage(language, mediaType).forEach((provider) => enabled.add(provider));
          }
        }
        const labels = [...selected].map((key) => state.providers.languages[key] || key.toUpperCase());
        setProviderSelectionStatus(context, `Inhaltssprachen: ${labels.join(" + ")}.`);
        renderAllProviderBoards();
      });
    });
  }
  const labels = [...selected].map(
    (language) => state.providers.languages[language] || language.toUpperCase(),
  );
  const summary = labels.length > 1
    ? `${labels.join(" + ")} · gemischter Katalog`
    : `${labels[0] || "Keine"} · fokussierter Katalog`;
  ["content-language-summary", "setup-content-language-summary"].forEach((id) => {
    const element = document.getElementById(id);
    if (element) element.textContent = summary;
  });
}

function providerMonogram(label) {
  const words = String(label || "").match(/[\p{L}\p{N}]+/gu) || [];
  return (words.length > 1
    ? words.slice(0, 2).map((word) => word[0]).join("")
    : String(words[0] || "?").slice(0, 2)
  ).toUpperCase();
}

function providerLogoUrl(meta) {
  const homepage = String(meta?.homepage || "").trim();
  if (!homepage) return "";
  return `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(homepage)}&sz=128`;
}

function providerListIds(mediaType) {
  if (mediaType === "movies") {
    return ["movie-provider-priority", "setup-movie-provider-priority"];
  }
  if (mediaType === "anime") {
    return ["anime-provider-priority", "setup-anime-provider-priority"];
  }
  return ["series-provider-priority", "setup-series-provider-priority"];
}

function setProviderSelectionStatus(context, message, error = false) {
  if (context === "setup") {
    setSetupStatus(message, error);
    return;
  }
  const status = document.getElementById("provider-selection-status");
  if (!status) return;
  status.textContent = message || "";
  status.classList.toggle("error", error);
}

function renderProviderList(list, mediaType) {
  const providers = state.providers[mediaType] || [];
  const enabled = providerEnabledSet(mediaType);
  const isSetup = list.id.startsWith("setup-");
  const context = isSetup ? "setup" : "settings";
  const mediaLabel = {
    movies: "Filmquelle",
    series: "Serienquelle",
    anime: "Animequelle",
  }[mediaType];
  list.innerHTML = providers.map((provider, index) => {
    const meta = state.providers.catalog[provider] || {};
    const label = state.providers.labels[provider] || meta.label || provider;
    const languageActive = state.providers.contentLanguages.has(providerLanguage(provider));
    const active = languageActive && enabled.has(provider);
    const logoUrl = providerLogoUrl(meta);
    const languageCode = String(meta.content_language || "").toUpperCase();
    const languageLabel = meta.language_label || languageCode;
    return `
      <li class="provider-source-card ${active ? "is-enabled" : "is-disabled"} ${languageActive ? "" : "is-language-muted"} ${mediaType === "series" ? "is-series" : ""}"
          data-provider="${escapeHtml(provider)}">
        <label class="provider-source-toggle">
          <input type="checkbox" ${active ? "checked" : ""}
            ${languageActive ? "" : "disabled"}
            aria-label="${escapeHtml(`${label} als ${mediaLabel} verwenden`)}">
          <span class="provider-logo-frame" aria-hidden="true">
            <span class="provider-logo-monogram">${escapeHtml(providerMonogram(label))}</span>
            ${logoUrl ? `<img class="provider-logo-image" src="${escapeHtml(logoUrl)}" alt="">` : ""}
          </span>
          <span class="provider-source-copy">
            <strong class="provider-name" translate="no">${escapeHtml(label)}</strong>
            <span class="provider-source-meta" translate="no">
              <em>${escapeHtml(languageCode)}</em>
              <small>${escapeHtml(languageLabel)}</small>
            </span>
          </span>
          <span class="provider-source-state" aria-hidden="true">
            <i>✓</i><small>${active ? "aktiv" : (languageActive ? "aus" : "Sprache aus")}</small>
          </span>
        </label>
        <span class="provider-source-order">
          <b title="Priorität">${String(index + 1).padStart(2, "0")}</b>
          <button class="provider-order-button" type="button" data-direction="-1"
            aria-label="${escapeHtml(`${label} nach oben`)}"
            ${index === 0 ? "disabled" : ""}>↑</button>
          <button class="provider-order-button" type="button" data-direction="1"
            aria-label="${escapeHtml(`${label} nach unten`)}"
            ${index === providers.length - 1 ? "disabled" : ""}>↓</button>
        </span>
      </li>
    `;
  }).join("");

  list.querySelectorAll(".provider-logo-image").forEach((image) => {
    image.addEventListener("error", () => image.remove(), { once: true });
  });
  list.querySelectorAll('.provider-source-toggle input[type="checkbox"]').forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const provider = checkbox.closest(".provider-source-card").dataset.provider;
      if (mediaType !== "anime" && !checkbox.checked && enabled.size <= 1) {
        checkbox.checked = true;
        setProviderSelectionStatus(
          context,
          `Mindestens eine ${mediaType === "movies" ? "Filmquelle" : "Serienquelle"} muss aktiv bleiben.`,
          true,
        );
        return;
      }
      if (checkbox.checked) enabled.add(provider);
      else enabled.delete(provider);
      setProviderSelectionStatus(
        context,
        `${enabled.size} ${{
          movies: "Filmquellen",
          series: "Serienquellen",
          anime: "Animequellen",
        }[mediaType]} aktiv.`,
      );
      renderAllProviderBoards();
    });
  });
  list.querySelectorAll(".provider-order-button").forEach((button) => {
    button.addEventListener("click", () => {
      const item = button.closest(".provider-source-card");
      const from = state.providers[mediaType].indexOf(item.dataset.provider);
      const to = from + Number(button.dataset.direction);
      if (from < 0 || to < 0 || to >= state.providers[mediaType].length) return;
      [state.providers[mediaType][from], state.providers[mediaType][to]] =
        [state.providers[mediaType][to], state.providers[mediaType][from]];
      renderAllProviderBoards();
    });
  });
}

function renderAllProviderBoards() {
  renderContentLanguageSelectors();
  for (const mediaType of ["movies", "series", "anime"]) {
    for (const id of providerListIds(mediaType)) {
      const list = document.getElementById(id);
      if (list) renderProviderList(list, mediaType);
    }
    const enabledCount = providerEnabledSet(mediaType).size;
    const eligibleCount = (state.providers[mediaType] || []).filter(
      (provider) => state.providers.contentLanguages.has(providerLanguage(provider)),
    ).length;
    const summary = `${enabledCount} aktiv · ${eligibleCount} passend`;
    const ids = {
      movies: ["movie-provider-summary", "setup-movie-provider-summary"],
      series: ["series-provider-summary", "setup-series-provider-summary"],
      anime: ["anime-provider-summary", "setup-anime-provider-summary"],
    }[mediaType];
    ids.forEach((id) => {
      const element = document.getElementById(id);
      if (element) element.textContent = summary;
    });
  }
  syncAnimeNavigationVisibility();
}

function applyProviderPriority(cfg) {
  state.providers.movies = [...(cfg.movies || [])];
  state.providers.series = [...(cfg.series || [])];
  state.providers.anime = [...(cfg.anime || [])];
  state.providers.labels = { ...(cfg.labels || {}) };
  state.providers.catalog = { ...(cfg.catalog || {}) };
  state.providers.languages = { ...(cfg.languages || {}) };
  state.providers.enabledMovies = new Set(
    cfg.enabled_movies?.length ? cfg.enabled_movies : state.providers.movies,
  );
  state.providers.enabledSeries = new Set(
    cfg.enabled_series?.length ? cfg.enabled_series : state.providers.series,
  );
  state.providers.enabledAnime = new Set(
    Array.isArray(cfg.enabled_anime) ? cfg.enabled_anime : state.providers.anime,
  );
  if (!Object.keys(state.providers.languages).length) {
    for (const meta of Object.values(state.providers.catalog)) {
      const language = String(meta.content_language || "").toLowerCase();
      if (language) state.providers.languages[language] = meta.language_label || language.toUpperCase();
    }
  }
  const inferredLanguages = [
    ...state.providers.enabledMovies,
    ...state.providers.enabledSeries,
    ...state.providers.enabledAnime,
  ].map(providerLanguage).filter(Boolean);
  state.providers.contentLanguages = new Set(
    cfg.content_languages?.length
      ? cfg.content_languages
      : (inferredLanguages.length ? inferredLanguages : Object.keys(state.providers.languages)),
  );
  for (const mediaType of ["movies", "series", "anime"]) {
    const enabled = providerEnabledSet(mediaType);
    [...enabled].forEach((provider) => {
      if (!state.providers.contentLanguages.has(providerLanguage(provider))) enabled.delete(provider);
    });
  }
  state.anime.loaded = false;
  state.anime.disabledReason = "";
  renderAllProviderBoards();
}

async function initSettings() {
  document.getElementById("ui-language").value = i18n.language;
  const cfg = await api.configGet();
  document.getElementById("save-path").value = cfg.save_path;
  document.getElementById("series-path").value = cfg.series_path || "";
  const jf = await api.jellyfinConfigGet();
  document.getElementById("jellyfin-url").value = jf.url || "";
  const jfKey = document.getElementById("jellyfin-api-key");
  jfKey.value = "";
  jfKey.placeholder = jf.has_api_key ? "Gespeichert · leer lassen zum Beibehalten" : "API-Schlüssel";
  fillJellyfinUserSelect("jellyfin-user-id", [], jf.user_id || "", jf.user_name || "");
  state.watchlistCleanupDefault = WATCH_CLEANUP_LABELS[jf.cleanup_default]
    ? jf.cleanup_default
    : WATCH_CLEANUP_DEFAULT;
  document.querySelectorAll('input[name="jellyfin-cleanup-default"]').forEach((radio) => {
    radio.checked = radio.value === state.watchlistCleanupDefault;
  });
  state.jellyfinUserConfigured = !!(jf.url && jf.has_api_key && jf.user_id);
  document.getElementById("jellyfin-user-status").textContent = jf.user_id
    ? `Gesehen-Status: ${jf.user_name || "Benutzer gewählt"}`
    : "Für „Nächste Staffel“ und automatische Löschregeln erforderlich.";
  const tmdb = await api.tmdbConfigGet();
  applyTmdbCfg(tmdb);
  const auto = await api.automationConfigGet();
  applyAutomationCfg(auto);
  applyUpdaterConfig(await api.updaterConfigGet());
  const seerr = await api.seerrConfigGet();
  applySeerrCfg(seerr);
  const telegram = await api.telegramConfigGet();
  applyTelegramCfg(telegram);
  applyProviderPriority(await api.providerPriorityGet());
  await refreshAccountCard();
  checkForUpdates(false);
}

// ── Zugang (Einstellungen) ───────────────────────────────────────────────
function setAccountStatus(message = "", error = false) {
  const el = document.getElementById("account-status");
  el.textContent = message;
  el.classList.toggle("error", !!error);
}

function applyAccountCfg(cfg) {
  const configured = !!cfg.configured;
  const card = document.getElementById("account-card");
  card.dataset.state = configured ? "configured" : "open";
  document.getElementById("account-warning").classList.toggle("hidden", configured);
  document.getElementById("account-username").value = cfg.username || "";
  // Ohne bestehendes Konto gibt es kein aktuelles Passwort zu bestätigen.
  document.getElementById("account-current-label").classList.toggle("hidden", !configured);
  document.getElementById("account-current-password").classList.toggle("hidden", !configured);
  document.getElementById("account-logout").classList.toggle("hidden", !configured);
  document.getElementById("account-state").textContent = configured
    ? (cfg.source === "env"
      ? `Angemeldet als „${cfg.username}“ · Zugangsdaten stammen aus APP_USERNAME/APP_PASSWORD. Beim Speichern werden sie in die Einstellungen übernommen.`
      : `Angemeldet als „${cfg.username}“.`)
    : "Es ist kein Konto eingerichtet – die Oberfläche ist ungeschützt erreichbar.";
  document.getElementById("account-sessions-count").textContent =
    `${cfg.active_sessions ?? 0} aktive Sitzung(en)`;
  document.getElementById("account-save").textContent = configured
    ? "Zugangsdaten speichern"
    : "Konto anlegen";
}

async function refreshAccountCard() {
  try {
    applyAccountCfg(await api.authConfigGet());
  } catch (error) {
    document.getElementById("account-state").textContent =
      `Kontostatus nicht abrufbar: ${error.message}`;
  }
}

async function saveAccount() {
  const button = document.getElementById("account-save");
  const username = document.getElementById("account-username").value.trim();
  const password = document.getElementById("account-password").value;
  const repeat = document.getElementById("account-password-repeat").value;
  const current = document.getElementById("account-current-password").value;
  if (!username) {
    setAccountStatus("Der Benutzername fehlt.", true);
    return;
  }
  if (!password) {
    setAccountStatus("Bitte ein neues Passwort eingeben.", true);
    return;
  }
  if (password !== repeat) {
    setAccountStatus("Die beiden Passwörter stimmen nicht überein.", true);
    return;
  }
  button.disabled = true;
  setAccountStatus("Wird gespeichert …");
  try {
    const result = await api.authConfigSet(username, password, current);
    document.getElementById("account-password").value = "";
    document.getElementById("account-password-repeat").value = "";
    document.getElementById("account-current-password").value = "";
    applyAccountCfg(result);
    authStatus = { ...authStatus, configured: true, authenticated: true, username };
    setAccountStatus("✓ Gespeichert. Andere Geräte müssen sich neu anmelden.");
  } catch (error) {
    setAccountStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function revokeOtherSessions() {
  const status = document.getElementById("account-revoke-status");
  status.classList.remove("error");
  status.textContent = "Sitzungen werden beendet …";
  try {
    const result = await api.authSessionsRevoke();
    status.textContent = `✓ ${result.revoked} Sitzung(en) beendet.`;
    document.getElementById("account-sessions-count").textContent =
      `${result.active_sessions ?? 0} aktive Sitzung(en)`;
  } catch (error) {
    status.textContent = error.message;
    status.classList.add("error");
  }
}

async function logoutAccount() {
  try {
    await api.authLogout();
  } catch (error) {
    console.warn("Abmeldung fehlgeschlagen:", error);
  }
  location.reload();
}

function applySeerrCfg(cfg) {
  document.getElementById("seerr-enabled").checked = !!cfg.enabled;
  document.getElementById("seerr-url").value = cfg.url || "";
  document.getElementById("seerr-poll-interval").value = cfg.poll_interval_seconds ?? 60;
  const key = document.getElementById("seerr-api-key");
  key.value = "";
  key.placeholder = cfg.has_api_key
    ? "Gespeichert · leer lassen zum Beibehalten"
    : "Seerr → Einstellungen → Allgemein";
  const status = document.getElementById("seerr-status");
  const counts = cfg.requests || {};
  const queued = (counts.queued || 0) + (counts.resolving || 0);
  if (!cfg.enabled) status.textContent = "Seerr-Brücke aus";
  else if (cfg.last_error) status.textContent = `✗ ${cfg.last_error}`;
  else if (cfg.moonfin_error) status.textContent = `Seerr aktiv · ${cfg.moonfin_error}`;
  else if (!cfg.connected) status.textContent = "Konfiguriert · Verbindung wird beim nächsten Abgleich geprüft";
  else status.textContent = `Verbunden${cfg.moonfin_configured ? " · Moonfin bereit" : ""} · ${queued} offen · ${counts.completed || 0} abgeschlossen`;
}

function applyTmdbCfg(cfg) {
  const input = document.getElementById("tmdb-api-key");
  input.value = "";
  input.placeholder = cfg.has_api_key ? "Gespeichert · leer lassen zum Beibehalten" : "TMDB API-Key";
  const status = document.getElementById("tmdb-status");
  if (!cfg.configured) status.textContent = "TMDB aus · Anbieterdaten werden verwendet";
  else if (cfg.valid === false) status.textContent = "✗ API-Key ungültig oder TMDB nicht erreichbar";
  else status.textContent = `TMDB aktiv · Sprache ${cfg.language === "de-DE" ? "Deutsch" : "Englisch"}`;
}

function applyTelegramCfg(cfg) {
  document.getElementById("telegram-enabled").checked = !!cfg.enabled;
  const token = document.getElementById("telegram-token");
  token.value = "";
  token.placeholder = cfg.has_bot_token ? "Gespeichert · leer lassen zum Beibehalten" : "123456789:AA…";
  document.getElementById("telegram-chat-id").value = cfg.chat_id || "";
  const status = document.getElementById("telegram-status");
  if (!cfg.enabled) status.textContent = "Telegram-Bot aus";
  else if (!cfg.has_bot_token) status.textContent = "Bot-Token fehlt";
  else if (!cfg.chat_id) status.textContent = "Einrichtungsmodus · /start an den Bot senden";
  else status.textContent = `Aktiv · nur Chat ${cfg.chat_id}`;
}

function applyAutomationCfg(auto) {
  document.getElementById("auto-download").checked = !!auto.auto_download;
  document.getElementById("check-interval").value = auto.check_interval_min ?? 30;
  document.getElementById("dl-window-start").value =
    auto.dl_window_start === null || auto.dl_window_start === undefined ? "" : auto.dl_window_start;
  document.getElementById("dl-window-end").value =
    auto.dl_window_end === null || auto.dl_window_end === undefined ? "" : auto.dl_window_end;
  const st = document.getElementById("auto-status");
  if (!auto.auto_download) {
    st.textContent = "Auto-Download aus";
  } else {
    const win = (auto.dl_window_start === null || auto.dl_window_end === null)
      ? "jederzeit"
      : `${auto.dl_window_start}–${auto.dl_window_end} Uhr` + (auto.in_window ? " (aktiv)" : " (wartet)");
    st.textContent = `Auto-Download an · alle ${auto.check_interval_min} Min · ${win}`;
  }
}

function shortRevision(value) {
  const revision = String(value || "").trim();
  return revision ? revision.slice(0, 8) : "unbekannt";
}

function applyUpdaterConfig(cfg) {
  const mode = cfg.update_mode === "automatic" ? "automatic" : "manual";
  const interval = Math.max(1, Math.min(168, Number(cfg.auto_update_interval_hours) || 6));
  const modeSelect = document.getElementById("updater-mode");
  const intervalInput = document.getElementById("updater-interval");
  const status = document.getElementById("updater-mode-status");
  modeSelect.value = mode;
  intervalInput.value = String(interval);
  intervalInput.disabled = mode !== "automatic";

  if (mode !== "automatic") {
    status.textContent = "Manuell · Updates werden nur nach Klick installiert.";
    return;
  }
  if (cfg.auto_update_state === "deferred") {
    status.textContent = `Automatisch zurückgestellt · ${cfg.auto_update_message || "Download-Queue ist belegt."}`;
    return;
  }
  if (cfg.auto_update_state === "error") {
    status.textContent = `Automatische Prüfung fehlgeschlagen · ${cfg.auto_update_message || "Neuer Versuch folgt."}`;
    return;
  }
  if (["unavailable", "manual_required"].includes(cfg.auto_update_state)) {
    status.textContent = `Automatische Installation pausiert · ${cfg.auto_update_message || "Manuelle Prüfung erforderlich."}`;
    return;
  }
  if (cfg.auto_update_state === "installing") {
    status.textContent = "Automatisch · Update wird installiert.";
    return;
  }
  status.textContent = `Automatisch · alle ${interval} Std. · Installation nur bei leerer Queue.`;
}

function applyUpdaterStatus(data) {
  const card = document.getElementById("updater-card");
  const status = document.getElementById("updater-status");
  const detail = document.getElementById("updater-detail");
  const badge = document.getElementById("updater-badge");
  const repository = document.getElementById("updater-repository");
  const installButton = document.getElementById("updater-install");
  if (data.config) applyUpdaterConfig(data.config);
  document.getElementById("updater-current").textContent = shortRevision(data.current_sha);
  document.getElementById("updater-latest").textContent = shortRevision(data.latest_sha);
  installButton.dataset.sha = String(data.latest_sha || "");
  document.getElementById("updater-branch-label").textContent = `GitHub · ${data.branch || "main"}`;
  if (String(data.repository_url || "").startsWith("https://github.com/")) {
    repository.href = data.repository_url;
  }
  const installer = data.installer || {};
  if (installer.active || installer.state === "error") {
    installButton.classList.toggle("hidden", installer.state !== "error");
    applyUpdaterInstallStatus(installer);
    return;
  }
  installButton.disabled = installer.supported === false;
  installButton.title = installer.supported === false ? (installer.reason || "Automatisches Update nicht möglich") : "";
  installButton.classList.add("hidden");

  if (data.error) {
    card.dataset.state = "error";
    badge.textContent = "!";
    status.textContent = "GitHub-Prüfung fehlgeschlagen";
    detail.textContent = data.error;
    return;
  }
  if (data.update_available === true) {
    const commits = Number(data.ahead_by || 0);
    card.dataset.state = "available";
    badge.textContent = "↑";
    status.textContent = "Update verfügbar";
    detail.textContent = commits
      ? `${commits} ${commits === 1 ? "neuer Commit" : "neue Commits"} auf ${data.branch || "main"}`
      : `Neuer Stand auf ${data.branch || "main"}`;
    installButton.classList.remove("hidden");
    if (installer.supported === false) {
      detail.textContent += ` · ${installer.reason || "Automatische Installation nicht möglich"}`;
    }
    return;
  }
  if (data.comparison === "identical") {
    card.dataset.state = "current";
    badge.textContent = "✓";
    status.textContent = "Auf dem neuesten Stand";
    detail.textContent = data.latest_message || "Lokaler Build und GitHub stimmen überein.";
    return;
  }
  if (data.comparison === "behind") {
    card.dataset.state = "current";
    badge.textContent = "DEV";
    status.textContent = "Lokaler Entwicklungsstand";
    detail.textContent = "Dieser Build liegt vor dem Main-Branch.";
    return;
  }
  card.dataset.state = "unknown";
  badge.textContent = "?";
  status.textContent = "Repository erreichbar";
  detail.textContent = data.current_sha
    ? "Der lokale Stand konnte nicht eindeutig mit main verglichen werden."
    : "Der lokale Quellstand konnte weder Git-Metadaten noch einem GitHub-Dateibaum zugeordnet werden.";
}

let updaterInstallPollTimer = null;

function applyUpdaterInstallStatus(installer) {
  const card = document.getElementById("updater-card");
  const status = document.getElementById("updater-status");
  const detail = document.getElementById("updater-detail");
  const badge = document.getElementById("updater-badge");
  const checkButton = document.getElementById("updater-check");
  const installButton = document.getElementById("updater-install");
  const active = !!installer.active;
  card.dataset.installing = active ? "true" : "false";
  checkButton.disabled = active;
  installButton.disabled = active || installer.supported === false;
  if (installer.target_sha) installButton.dataset.sha = installer.target_sha;

  if (installer.state === "error") {
    card.dataset.state = "error";
    badge.textContent = "!";
    status.textContent = "Update fehlgeschlagen";
    detail.textContent = installer.error || installer.message || "Unbekannter Fehler";
    installButton.textContent = "Erneut versuchen";
    installButton.classList.remove("hidden");
    return;
  }
  if (!active) return;
  card.dataset.state = "checking";
  badge.textContent = installer.state === "restarting" ? "↻" : "↓";
  status.textContent = installer.message || "Update läuft";
  detail.textContent = installer.state === "restarting"
    ? "Die Oberfläche verbindet sich nach dem Neustart automatisch neu."
    : "Einstellungen, Abos und Downloads bleiben erhalten.";
  installButton.textContent = "Update läuft …";
  installButton.classList.remove("hidden");
  if (installer.state === "restarting") waitForUpdatedServer();
}

function scheduleUpdaterInstallPoll() {
  if (updaterInstallPollTimer) clearTimeout(updaterInstallPollTimer);
  updaterInstallPollTimer = setTimeout(async () => {
    try {
      const response = await api.updaterInstallStatus();
      const installer = response.installer || {};
      applyUpdaterInstallStatus(installer);
      if (installer.active && installer.state !== "restarting") scheduleUpdaterInstallPoll();
    } catch (error) {
      scheduleUpdaterInstallPoll();
    }
  }, 900);
}

async function waitForUpdatedServer() {
  if (updaterInstallPollTimer) clearTimeout(updaterInstallPollTimer);
  updaterInstallPollTimer = setTimeout(async () => {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      location.reload();
    } catch (error) {
      waitForUpdatedServer();
    }
  }, 3000);
}

async function installUpdate() {
  const button = document.getElementById("updater-install");
  const targetSha = button.dataset.sha || "";
  if (!targetSha) return;
  button.disabled = true;
  try {
    const response = await api.updaterInstall(targetSha);
    applyUpdaterInstallStatus(response.installer || {});
    scheduleUpdaterInstallPoll();
  } catch (error) {
    applyUpdaterInstallStatus({ state: "error", error: error.message, supported: true });
  }
}

async function checkForUpdates(force = false) {
  const button = document.getElementById("updater-check");
  const card = document.getElementById("updater-card");
  const status = document.getElementById("updater-status");
  const detail = document.getElementById("updater-detail");
  button.disabled = true;
  card.dataset.state = "checking";
  status.textContent = "Prüfe GitHub …";
  detail.textContent = "Neuester Stand wird geladen.";
  try {
    applyUpdaterStatus(await api.updaterStatus(force));
  } catch (error) {
    applyUpdaterStatus({ error: error.message });
  } finally {
    button.disabled = card.dataset.installing === "true";
  }
}

function initSettingsNavigation() {
  const root = document.getElementById("tab-einstellungen");
  const panel = root?.querySelector(".settings-panel");
  const links = [...(root?.querySelectorAll("[data-settings-target]") || [])];
  const sections = [...(root?.querySelectorAll("[data-settings-section]") || [])];
  if (!root || !panel || !links.length || !sections.length) return;

  const activate = (id) => {
    links.forEach((link) => {
      const active = link.dataset.settingsTarget === id;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    });
  };

  let scrollFrame = 0;
  const updateFromScroll = () => {
    scrollFrame = 0;
    if (window.innerWidth <= 820) return;
    const rootTop = root.getBoundingClientRect().top;
    let current = sections[0];
    for (const section of sections) {
      if (section.getBoundingClientRect().top - rootTop <= 130) current = section;
      else break;
    }
    activate(current.id);
  };
  root.addEventListener("scroll", () => {
    if (!scrollFrame) scrollFrame = requestAnimationFrame(updateFromScroll);
  }, { passive: true });

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const section = document.getElementById(link.dataset.settingsTarget);
      if (!section) return;
      const top = root.scrollTop
        + section.getBoundingClientRect().top
        - root.getBoundingClientRect().top
        - 14;
      root.scrollTo({
        top,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
      activate(section.id);
    });
  });

  const markDirty = () => {
    const status = document.getElementById("settings-saved-status");
    if (status) status.textContent = "Ungespeicherte Änderungen.";
  };
  panel.addEventListener("input", markDirty);
  panel.addEventListener("change", markDirty);
  panel.addEventListener("click", (event) => {
    if (event.target.closest(".provider-order-button, .content-language-card")) markDirty();
  });
  window.addEventListener("resize", updateFromScroll, { passive: true });
}

async function saveAllSettings() {
  const btn = document.getElementById("settings-save");
  const status = document.getElementById("settings-saved-status");
  const parseHour = (id) => {
    const v = document.getElementById(id).value.trim();
    return v === "" ? null : Math.max(0, Math.min(23, parseInt(v, 10) || 0));
  };
  btn.disabled = true;
  status.textContent = "Speichere …";
  try {
    await api.uiConfigSet(document.getElementById("ui-language").value);
    await api.configSet(
      document.getElementById("save-path").value.trim(),
      document.getElementById("series-path").value.trim(),
    );
    applyProviderPriority(await api.providerPrioritySet({
      movies: state.providers.movies,
      series: state.providers.series,
      anime: state.providers.anime,
      enabled_movies: [...state.providers.enabledMovies],
      enabled_series: [...state.providers.enabledSeries],
      enabled_anime: [...state.providers.enabledAnime],
      content_languages: [...state.providers.contentLanguages],
    }));
    const jfUserSelect = document.getElementById("jellyfin-user-id");
    const cleanupDefault = document.querySelector('input[name="jellyfin-cleanup-default"]:checked')?.value
      || WATCH_CLEANUP_DEFAULT;
    const jfConfig = await api.jellyfinConfigSet(
      document.getElementById("jellyfin-url").value.trim(),
      document.getElementById("jellyfin-api-key").value.trim(),
      jfUserSelect.value,
      jfUserSelect.value
        ? (jfUserSelect.selectedOptions[0]?.dataset.name || jfUserSelect.selectedOptions[0]?.textContent || "")
        : "",
      cleanupDefault,
    );
    state.watchlistCleanupDefault = WATCH_CLEANUP_LABELS[jfConfig.cleanup_default]
      ? jfConfig.cleanup_default
      : WATCH_CLEANUP_DEFAULT;
    state.jellyfinUserConfigured = !!(jfConfig.url && jfConfig.has_api_key && jfConfig.user_id);
    document.getElementById("jellyfin-user-status").textContent = jfConfig.user_id
      ? `Gesehen-Status: ${jfConfig.user_name || "Benutzer gewählt"}`
      : "Für „Nächste Staffel“ und automatische Löschregeln erforderlich.";
    const tmdb = await api.tmdbConfigSet(
      document.getElementById("tmdb-api-key").value.trim(),
    );
    applyTmdbCfg(tmdb);
    const auto = await api.automationConfigSet({
      auto_download: document.getElementById("auto-download").checked,
      check_interval_min: Math.max(5, parseInt(document.getElementById("check-interval").value, 10) || 30),
      dl_window_start: parseHour("dl-window-start"),
      dl_window_end: parseHour("dl-window-end"),
    });
    applyAutomationCfg(auto);
    applyUpdaterConfig(await api.updaterConfigSet({
      update_mode: document.getElementById("updater-mode").value,
      auto_update_interval_hours: Math.max(
        1,
        Math.min(168, parseInt(document.getElementById("updater-interval").value, 10) || 6),
      ),
    }));
    const seerr = await api.seerrConfigSet({
      enabled: document.getElementById("seerr-enabled").checked,
      url: document.getElementById("seerr-url").value.trim(),
      api_key: document.getElementById("seerr-api-key").value.trim(),
      poll_interval_seconds: Math.max(
        15,
        Math.min(3600, parseInt(document.getElementById("seerr-poll-interval").value, 10) || 60),
      ),
    });
    applySeerrCfg(seerr);
    const telegram = await api.telegramConfigSet({
      enabled: document.getElementById("telegram-enabled").checked,
      bot_token: document.getElementById("telegram-token").value.trim(),
      chat_id: document.getElementById("telegram-chat-id").value.trim(),
    });
    applyTelegramCfg(telegram);
    state.fp.results = [];
    state.fp.moviesCache = {};
    state.fp.metadataCache = {};
    state.fp.sources = [];
    state.series.results = [];
    state.series.sources = [];
    state.series.browseMode = null;
    state.series.page = 1;
    state.series.cache = {};
    await refreshGenres().catch((error) => {
      document.getElementById("genre-count").textContent = "Genres nicht verfügbar";
      console.error("Genres konnten nach dem Quellenwechsel nicht geladen werden:", error);
    });
    fpShowList("new").catch((error) => {
      document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
    });
    const t = new Date().toLocaleTimeString(i18n.locale(), { hour: "2-digit", minute: "2-digit" });
    status.textContent = `✓ Gespeichert (${t})`;
    if (state.wl.loaded) refreshWatchlist();
  } catch (e) {
    status.textContent = "✗ Fehler: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function openDirModal(path) {
  const data = await api.browseDir(path);
  dirModalPath = data.path;
  document.getElementById("dir-modal").classList.remove("hidden");
  document.getElementById("dir-modal-path").textContent = data.path;
  const list = document.getElementById("dir-modal-list");
  list.innerHTML = "";
  document.getElementById("dir-modal-up").disabled = !data.parent;
  document.getElementById("dir-modal-up").onclick = () => { if (data.parent) openDirModal(data.parent); };
  for (const d of data.dirs) {
    const item = document.createElement("div");
    item.className = "dir-item";
    item.translate = false;
    item.textContent = d.name;
    item.addEventListener("click", () => openDirModal(d.path));
    list.appendChild(item);
  }
}

// ── Ersteinrichtung ─────────────────────────────────────────────────────────
let setupStep = 1;
let setupRequired = false;
let initialDataStarted = false;

const setupStepCopy = {
  1: {
    title: "Welche Sprache passt zu dir?",
    intro: "Die Oberfläche wechselt sofort. Inhalte und Anbieternamen bleiben unverändert.",
  },
  2: {
    title: "Welche Inhalte möchtest du?",
    intro: "Wähle Inhaltssprachen und passende Quellen. Die Reihenfolge bestimmt Suche und Fallbacks.",
  },
  3: {
    title: "Wohin sollen deine Medien?",
    intro: "Die Ordner werden bei Bedarf angelegt. Beide müssen für den Downloader beschreibbar sein.",
  },
  4: {
    title: "Bibliothek und Filmdaten",
    intro: "Beide Verbindungen sind optional und können später in den Einstellungen ergänzt werden.",
  },
  5: {
    title: "Downloads automatisieren",
    intro: "Lege fest, was selbstständig laufen darf. Alle Werte bleiben später änderbar.",
  },
  6: {
    title: "Zugang sichern",
    intro: "Ein Konto schützt die Oberfläche. Ohne Anmeldung könnte jedes Gerät im Netzwerk Downloads auslösen.",
  },
};

const SETUP_STEP_COUNT = 6;

function setSetupStatus(message = "", error = false) {
  const el = document.getElementById("setup-status");
  el.textContent = message;
  el.classList.toggle("error", error);
}

function showSetupStep(nextStep) {
  setupStep = Math.max(1, Math.min(SETUP_STEP_COUNT, nextStep));
  document.querySelectorAll("[data-setup-step]").forEach((panel) => {
    panel.classList.toggle("hidden", Number(panel.dataset.setupStep) !== setupStep);
  });
  document.querySelectorAll("[data-setup-marker]").forEach((marker) => {
    const markerStep = Number(marker.dataset.setupMarker);
    marker.classList.toggle("active", markerStep === setupStep);
    marker.classList.toggle("complete", markerStep < setupStep);
    if (markerStep === setupStep) marker.setAttribute("aria-current", "step");
    else marker.removeAttribute("aria-current");
  });
  document.getElementById("setup-step-label").textContent = `SCHRITT ${setupStep} VON ${SETUP_STEP_COUNT}`;
  document.getElementById("setup-title").textContent = setupStepCopy[setupStep].title;
  document.getElementById("setup-intro").textContent = setupStepCopy[setupStep].intro;
  document.getElementById("setup-back").classList.toggle("hidden", setupStep === 1);
  document.getElementById("setup-next").classList.toggle("hidden", setupStep === SETUP_STEP_COUNT);
  document.getElementById("setup-finish").classList.toggle("hidden", setupStep !== SETUP_STEP_COUNT);
  setSetupStatus();
  const focusTarget = document.querySelector(
    `[data-setup-step="${setupStep}"] select, `
    + `[data-setup-step="${setupStep}"] input:not([type="checkbox"])`,
  );
  if (focusTarget) window.setTimeout(() => focusTarget.focus(), 40);
}

function validateSetupStep(step) {
  if (step === 2) {
    if (!state.providers.contentLanguages.size) {
      setSetupStatus("Mindestens eine Inhaltssprache muss aktiv sein.", true);
      return false;
    }
    if (!state.providers.enabledMovies.size || !state.providers.enabledSeries.size) {
      setSetupStatus("Für Filme und Serien muss jeweils mindestens eine Quelle aktiv sein.", true);
      return false;
    }
  }
  if (step === 3) {
    const movie = document.getElementById("setup-save-path");
    const series = document.getElementById("setup-series-path");
    movie.removeAttribute("aria-invalid");
    series.removeAttribute("aria-invalid");
    if (!movie.value.trim() || !series.value.trim()) {
      if (!movie.value.trim()) movie.setAttribute("aria-invalid", "true");
      if (!series.value.trim()) series.setAttribute("aria-invalid", "true");
      setSetupStatus("Film- und Serienordner müssen angegeben werden.", true);
      (!movie.value.trim() ? movie : series).focus();
      return false;
    }
  }
  if (step === 5 && document.getElementById("setup-telegram-enabled").checked) {
    const token = document.getElementById("setup-telegram-token");
    token.removeAttribute("aria-invalid");
    if (!token.value.trim() && token.dataset.hasSecret !== "true") {
      token.setAttribute("aria-invalid", "true");
      setSetupStatus("Für den aktivierten Telegram-Bot fehlt der Bot-Token.", true);
      token.focus();
      return false;
    }
  }
  if (step === 6) {
    const username = document.getElementById("setup-auth-username");
    const password = document.getElementById("setup-auth-password");
    const repeat = document.getElementById("setup-auth-password-repeat");
    [username, password, repeat].forEach((field) => field.removeAttribute("aria-invalid"));
    if (username.value.trim().length < 3) {
      username.setAttribute("aria-invalid", "true");
      setSetupStatus("Der Benutzername braucht mindestens 3 Zeichen.", true);
      username.focus();
      return false;
    }
    if (password.value.length < 8) {
      password.setAttribute("aria-invalid", "true");
      setSetupStatus("Das Passwort braucht mindestens 8 Zeichen.", true);
      password.focus();
      return false;
    }
    if (password.value !== repeat.value) {
      repeat.setAttribute("aria-invalid", "true");
      setSetupStatus("Die beiden Passwörter stimmen nicht überein.", true);
      repeat.focus();
      return false;
    }
  }
  return true;
}

function parseSetupHour(id) {
  const value = document.getElementById(id).value.trim();
  if (value === "") return null;
  return Math.max(0, Math.min(23, parseInt(value, 10) || 0));
}

async function finishSetup() {
  if (!validateSetupStep(5) || !validateSetupStep(6)) return;
  const finish = document.getElementById("setup-finish");
  const back = document.getElementById("setup-back");
  finish.disabled = true;
  back.disabled = true;
  setSetupStatus("Ordner und Einstellungen werden angelegt …");
  try {
    await api.setupComplete({
      save_path: document.getElementById("setup-save-path").value.trim(),
      series_path: document.getElementById("setup-series-path").value.trim(),
      ui_language: document.getElementById("setup-ui-language").value,
      movie_provider_order: state.providers.movies,
      series_provider_order: state.providers.series,
      anime_provider_order: state.providers.anime,
      movie_providers: [...state.providers.enabledMovies],
      series_providers: [...state.providers.enabledSeries],
      anime_providers: [...state.providers.enabledAnime],
      content_languages: [...state.providers.contentLanguages],
      jellyfin_url: document.getElementById("setup-jellyfin-url").value.trim(),
      jellyfin_api_key: document.getElementById("setup-jellyfin-key").value.trim(),
      jellyfin_user_id: document.getElementById("setup-jellyfin-user").value,
      jellyfin_user_name: document.getElementById("setup-jellyfin-user").value
        ? (document.getElementById("setup-jellyfin-user").selectedOptions[0]?.dataset.name
          || document.getElementById("setup-jellyfin-user").selectedOptions[0]?.textContent || "")
        : "",
      tmdb_api_key: document.getElementById("setup-tmdb-key").value.trim(),
      auto_download: document.getElementById("setup-auto-download").checked,
      check_interval_min: Math.max(5, parseInt(document.getElementById("setup-check-interval").value, 10) || 30),
      dl_window_start: parseSetupHour("setup-window-start"),
      dl_window_end: parseSetupHour("setup-window-end"),
      telegram_enabled: document.getElementById("setup-telegram-enabled").checked,
      telegram_bot_token: document.getElementById("setup-telegram-token").value.trim(),
      telegram_chat_id: document.getElementById("setup-telegram-chat").value.trim(),
      auth_username: document.getElementById("setup-auth-username").value.trim(),
      auth_password: document.getElementById("setup-auth-password").value,
    });
    document.getElementById("setup-auth-password").value = "";
    document.getElementById("setup-auth-password-repeat").value = "";
    setupRequired = false;
    document.body.classList.remove("setup-open");
    document.getElementById("setup-wizard").classList.add("hidden");
    await initSettings();
    startInitialData();
  } catch (e) {
    setSetupStatus(`Einrichtung fehlgeschlagen: ${e.message}`, true);
  } finally {
    finish.disabled = false;
    back.disabled = false;
  }
}

async function initSetupWizard() {
  try {
    const data = await api.setupStatus();
    if (!data.required) return false;
    setupRequired = true;
    const defaults = data.defaults || {};
    const jf = defaults.jellyfin || {};
    const tmdb = defaults.tmdb || {};
    const telegram = defaults.telegram || {};
    const automation = defaults.automation || {};
    const providers = defaults.providers || {};
    if (providers.movies?.length && providers.series?.length) {
      applyProviderPriority(providers);
    }
    const setupLanguage = defaults.ui_language_configured
      ? defaults.ui_language
      : i18n.browserDefaultLanguage();
    document.getElementById("setup-ui-language").value = setupLanguage;
    document.getElementById("ui-language").value = setupLanguage;
    if (setupLanguage !== i18n.language) {
      await i18n.changeLanguage(setupLanguage);
    }
    document.getElementById("setup-save-path").value = defaults.save_path || "";
    document.getElementById("setup-series-path").value = defaults.series_path || defaults.save_path || "";
    document.getElementById("setup-jellyfin-url").value = jf.url || "";
    const setupJfKey = document.getElementById("setup-jellyfin-key");
    setupJfKey.value = "";
    setupJfKey.dataset.hasSecret = jf.has_api_key ? "true" : "false";
    if (jf.has_api_key) setupJfKey.placeholder = "Bereits hinterlegt";
    fillJellyfinUserSelect("setup-jellyfin-user", [], jf.user_id || "", jf.user_name || "");
    const setupTmdbKey = document.getElementById("setup-tmdb-key");
    setupTmdbKey.value = "";
    setupTmdbKey.dataset.hasSecret = tmdb.has_api_key ? "true" : "false";
    if (tmdb.has_api_key) setupTmdbKey.placeholder = "Bereits hinterlegt";
    document.getElementById("setup-auto-download").checked = !!automation.auto_download;
    document.getElementById("setup-check-interval").value = automation.check_interval_min || 30;
    document.getElementById("setup-window-start").value = automation.dl_window_start ?? "";
    document.getElementById("setup-window-end").value = automation.dl_window_end ?? "";
    document.getElementById("setup-telegram-enabled").checked = !!telegram.enabled;
    const setupTelegramToken = document.getElementById("setup-telegram-token");
    setupTelegramToken.value = "";
    setupTelegramToken.dataset.hasSecret = telegram.has_bot_token ? "true" : "false";
    if (telegram.has_bot_token) setupTelegramToken.placeholder = "Bereits hinterlegt";
    document.getElementById("setup-telegram-chat").value = telegram.chat_id || "";
    document.getElementById("setup-config-path").textContent = data.config_path || "DATA/FilmeDownloader/settings.ini";
    document.body.classList.add("setup-open");
    document.getElementById("setup-wizard").classList.remove("hidden");
    showSetupStep(1);
    return true;
  } catch (e) {
    console.error("Ersteinrichtung konnte nicht geprüft werden:", e);
    return false;
  }
}

function retryFpInfiniteLoad() {
  if (state.fp.loadingMore || !state.fp.category) return;
  if (state.fp.lastPageFull) {
    loadNextFpPage();
  } else if (state.fp.category === "genre") {
    fpGenreChange(state.fp.activeGenre);
  } else {
    fpShowList(state.fp.category);
  }
}

function retrySeriesInfiniteLoad() {
  const mode = state.series.browseMode;
  if (state.series.loadingBrowse || !mode || mode === "search") return;
  if (state.series.lastPageFull) loadNextSeriesPage();
  else seriesBrowse(mode, 1);
}

// Vorlauf in Pixeln: sobald weniger als so viel bis zum unteren Rand des
// intern scrollenden Tabs fehlt, wird die naechste Seite geladen. Grosszuegig
// genug gewaehlt, dass die Folge-Eintraege laengst da sind, bevor man das Ende
// sieht – aber kleiner als eine typische Seite an Inhalt, damit nie mehrere
// Seiten auf einmal in einem Schwall nachgeladen werden.
const CATALOG_PRELOAD_PX = 1400;

function initCatalogInfiniteScroll() {
  document.getElementById("fp-infinite-retry").addEventListener("click", retryFpInfiniteLoad);
  document.getElementById("series-infinite-retry").addEventListener("click", retrySeriesInfiniteLoad);

  // Ein Scroll-Listener direkt am echten Scroll-Container ist zuverlaessiger
  // als ein IntersectionObserver: dessen rootMargin greift bei verschachtelten
  // Scroll-Containern (Tab scrollt intern, Dokument nicht) je nach Browser
  // nicht sauber, wodurch der Vorlauf verpuffte oder in Schueben nachlud.
  const bind = (containerId, loadNext) => {
    const container = document.getElementById(containerId);
    if (!container) return () => {};
    let scheduled = false;
    const run = () => {
      scheduled = false;
      const remaining = container.scrollHeight - container.scrollTop - container.clientHeight;
      if (remaining <= CATALOG_PRELOAD_PX) loadNext();
    };
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(run);
    };
    container.addEventListener("scroll", schedule, { passive: true });
    return schedule;
  };

  recheckFpInfinite = bind("tab-filme", loadNextFpPage);
  recheckSeriesInfinite = bind("tab-serien", loadNextSeriesPage);
}

function startInitialData() {
  if (initialDataStarted) return;
  initialDataStarted = true;
  restoreHomeCache();
  syncTasteProfile();
  refreshGenres().catch((e) => {
    document.getElementById("genre-count").textContent = "Genres nicht verfügbar";
    console.error("Genres konnten nicht geladen werden:", e);
  });
  syncQueueSnapshot("Initiale Queue-Synchronisierung");
  refreshWatchlist();
  syncMovieSubscriptions();
  loadHomeData().catch((e) => {
    document.getElementById("fp-status").textContent = `Fehler: ${e.message}`;
    state.home.loading = false;
    renderHome();
  });
}

async function refreshGenres() {
  const data = await api.genres();
  const genres = Array.isArray(data.genres) ? data.genres : [];
  const filter = document.getElementById("genre-filter");
  filter.querySelectorAll('.genre-chip:not([data-genre="Alle Genres"])').forEach((button) => {
    button.remove();
  });
  for (const genre of genres) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "genre-chip";
    button.dataset.genre = genre;
    button.setAttribute("aria-pressed", "false");
    button.textContent = genre;
    filter.appendChild(button);
  }
  if (state.fp.activeGenre !== "Alle Genres" && !genres.includes(state.fp.activeGenre)) {
    state.fp.activeGenre = "Alle Genres";
  }
  document.getElementById("genre-count").textContent = `${genres.length} Genres verfügbar`;
  const genresAvailable = genres.length > 0;
  document.getElementById("genre-random").disabled = !genresAvailable;
  document.getElementById("genre-toggle").disabled = !genresAvailable;
  setActiveGenreFilter(state.fp.activeGenre);
}

// ── Init ─────────────────────────────────────────────────────────────────
async function initApp() {
  await i18n.initialize();
  initLoginScreen();
  // Blockiert, bis eine gültige Sitzung besteht. Ohne eingerichtetes Konto
  // oder vor der Ersteinrichtung kehrt der Aufruf sofort zurück.
  await requireLogin();
  document.querySelectorAll(".media-modal").forEach((modal) => document.body.appendChild(modal));
  buildAlphaBar();
  connectWs();
  initSettingsNavigation();
  initCatalogInfiniteScroll();

  document.querySelectorAll(".tab-btn").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

  document.getElementById("mobile-queue-btn").addEventListener("click", openMobileQueue);
  document.getElementById("mobile-queue-close").addEventListener("click", closeMobileQueue);
  document.getElementById("mobile-queue-backdrop").addEventListener("click", closeMobileQueue);
  document.getElementById("queue-dock-toggle").addEventListener("click", toggleDesktopQueue);
  document.querySelectorAll("[data-modal-close]").forEach((button) => {
    button.addEventListener("click", () => closeMediaModal(button.dataset.modalClose));
  });
  document.getElementById("fp-taste-like").addEventListener("click", () => setTasteFeedback("movie", "like"));
  document.getElementById("fp-taste-dislike").addEventListener("click", () => setTasteFeedback("movie", "dislike"));
  document.getElementById("series-taste-like").addEventListener("click", () => setTasteFeedback("series", "like"));
  document.getElementById("series-taste-dislike").addEventListener("click", () => setTasteFeedback("series", "dislike"));

  // Startseite
  document.getElementById("home-hero-open").addEventListener("click", (event) => {
    const { kind, key } = event.currentTarget.dataset;
    if (kind && key) openHomeEntry(kind, key);
  });
  document.getElementById("home-hero-list").addEventListener("click", () => switchTab("bibliothek"));
  document.getElementById("home-hero-prev").addEventListener("click", () => {
    showHomeHero(state.home.heroIndex - 1, true);
    scheduleHomeHeroRotation();
  });
  document.getElementById("home-hero-next").addEventListener("click", () => {
    showHomeHero(state.home.heroIndex + 1, true);
    scheduleHomeHeroRotation();
  });
  const homeHero = document.getElementById("home-hero");
  homeHero.addEventListener("pointerenter", stopHomeHeroRotation);
  homeHero.addEventListener("pointerleave", scheduleHomeHeroRotation);
  homeHero.addEventListener("focusin", stopHomeHeroRotation);
  homeHero.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!homeHero.contains(document.activeElement)) scheduleHomeHeroRotation();
    }, 0);
  });
  document.querySelectorAll("[data-home-scroll]").forEach((button) => {
    button.addEventListener("click", () => {
      const track = document.getElementById(button.dataset.homeScroll);
      const direction = Number(button.dataset.direction) || 1;
      track?.scrollBy({ left: direction * Math.max(280, track.clientWidth * 0.82), behavior: "smooth" });
    });
  });
  document.querySelectorAll("#tab-home .home-track").forEach((track) => {
    let navigationFrame = 0;
    track.addEventListener("scroll", () => {
      cancelAnimationFrame(navigationFrame);
      navigationFrame = requestAnimationFrame(() => updateHomeRailNavigation(track));
    }, { passive: true });
    updateHomeRailNavigation(track);
  });
  window.addEventListener("resize", () => {
    document.querySelectorAll("#tab-home .home-track").forEach(updateHomeRailNavigation);
  });
  const globalSearchInput = document.getElementById("global-search-input");
  const globalSearchToggle = document.getElementById("global-search-toggle");
  globalSearchToggle.addEventListener("click", () => globalSearchInput.focus());
  globalSearchInput.addEventListener("focus", () => {
    document.getElementById("global-search-shell").classList.add("is-expanded");
    globalSearchToggle.setAttribute("aria-expanded", "true");
  });
  globalSearchInput.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (globalSearchInput.value || document.getElementById("global-search-shell").contains(document.activeElement)) return;
      document.getElementById("global-search-shell").classList.remove("is-expanded");
      globalSearchToggle.setAttribute("aria-expanded", "false");
    }, 0);
  });
  globalSearchInput.addEventListener("input", () => queueGlobalSearch());
  globalSearchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      queueGlobalSearch(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeGlobalSearch({ restoreFocus: true });
      document.getElementById("global-search-shell").classList.remove("is-expanded");
    }
  });
  document.getElementById("global-search-clear").addEventListener("click", () => {
    closeGlobalSearch({ restoreFocus: true });
    document.getElementById("global-search-shell").classList.remove("is-expanded");
  });
  document.getElementById("home-search-btn").addEventListener("click", homeSearch);
  document.getElementById("home-search-close").addEventListener("click", closeHomeSearch);
  document.getElementById("home-search-clear").addEventListener("click", closeHomeSearch);
  document.getElementById("home-search").addEventListener("input", () => {
    syncSearchClearButtons();
    renderSearchSuggestions("all", "home-search", "home-search-suggestions", homeSearch);
  });
  document.getElementById("home-search").addEventListener("focus", () => {
    renderSearchSuggestions("all", "home-search", "home-search-suggestions", homeSearch);
  });
  document.getElementById("home-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      homeSearch();
    } else if (event.key === "Escape") {
      event.stopPropagation();
      closeSearchSuggestions("home-search-suggestions", "home-search");
    }
  });
  window.setInterval(() => {
    if (state.tab !== "home" || state.home.discoveryDay === localDateKey()) return;
    state.home.heroIndex = 0;
    renderHome();
  }, 5 * 60 * 1000);
  document.querySelectorAll("[data-home-search-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      state.home.search.scope = button.dataset.homeSearchScope;
      document.querySelectorAll("[data-home-search-scope]").forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
      if (document.getElementById("home-search").value.trim()) homeSearch();
    });
  });

  // Filme
  document.getElementById("fp-search-btn").addEventListener("click", fpSearch);
  document.getElementById("fp-search-clear").addEventListener("click", async () => {
    document.getElementById("fp-search").value = "";
    syncSearchClearButtons();
    closeSearchSuggestions("fp-search-suggestions", "fp-search");
    await restoreFpSearchContext();
  });
  document.getElementById("fp-search").addEventListener("input", () => {
    syncSearchClearButtons();
    renderSearchSuggestions("movie", "fp-search", "fp-search-suggestions", fpSearch);
  });
  document.getElementById("fp-search").addEventListener("focus", () => {
    renderSearchSuggestions("movie", "fp-search", "fp-search-suggestions", fpSearch);
  });
  document.getElementById("fp-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      fpSearch();
    } else if (event.key === "Escape") {
      event.stopPropagation();
      closeSearchSuggestions("fp-search-suggestions", "fp-search");
    }
  });
  document.getElementById("fp-search").addEventListener("blur", (event) => {
    if (!event.currentTarget.value.trim()) restoreFpSearchContext();
  });
  document.getElementById("fp-new-btn").addEventListener("click", () => fpShowList("new"));
  document.getElementById("fp-top-btn").addEventListener("click", () => fpShowList("top"));
  document.getElementById("fp-trailer-close").addEventListener("click", () => {
    closeFpTrailerModal();
  });
  document.getElementById("fp-trailer-backdrop").addEventListener("click", () => {
    closeFpTrailerModal();
  });
  document.getElementById("fp-detail-hero-mute").addEventListener("click", () => {
    setFpDetailHeroTrailerMuted(!fpDetailHeroTrailerMuted, { persist: true });
  });
  document.getElementById("series-detail-hero-mute").addEventListener("click", () => {
    setFpDetailHeroTrailerMuted(!fpDetailHeroTrailerMuted, { persist: true });
  });
  document.getElementById("movie-feature-open").addEventListener("click", (event) => {
    const slug = event.currentTarget.dataset.slug;
    if (slug) selectFpRow(slug);
  });
  document.getElementById("movie-feature-prev").addEventListener("click", () => {
    showMovieFeature(state.fp.featureIndex - 1, true);
    scheduleMovieFeatureRotation();
  });
  document.getElementById("movie-feature-next").addEventListener("click", () => {
    showMovieFeature(state.fp.featureIndex + 1, true);
    scheduleMovieFeatureRotation();
  });
  document.getElementById("movie-feature-pause").addEventListener("click", () => {
    setMovieFeaturePaused(!state.fp.featurePaused);
  });
  const movieFeature = document.getElementById("movie-feature");
  movieFeature.addEventListener("pointerenter", stopMovieFeatureRotation);
  movieFeature.addEventListener("pointerleave", scheduleMovieFeatureRotation);
  movieFeature.addEventListener("focusin", stopMovieFeatureRotation);
  movieFeature.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!movieFeature.contains(document.activeElement)) scheduleMovieFeatureRotation();
    }, 0);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopMovieFeatureRotation();
      stopHomeHeroRotation();
    } else {
      scheduleMovieFeatureRotation();
      scheduleHomeHeroRotation();
    }
  });
  document.getElementById("genre-filter").addEventListener("click", (e) => {
    const button = e.target.closest("[data-genre]");
    if (button) fpGenreChange(button.dataset.genre);
  });
  document.getElementById("genre-toggle").addEventListener("click", (e) => {
    const filter = document.getElementById("genre-filter");
    const expanded = filter.classList.toggle("is-expanded");
    e.currentTarget.setAttribute("aria-expanded", String(expanded));
    e.currentTarget.querySelector(".genre-toggle-label").textContent = expanded ? "Weniger zeigen" : "Alle zeigen";
  });
  document.getElementById("genre-random").addEventListener("click", () => {
    const genres = [...document.querySelectorAll("#genre-filter [data-genre]")]
      .map((button) => button.dataset.genre)
      .filter((genre) => genre !== "Alle Genres" && genre !== state.fp.activeGenre);
    if (!genres.length) return;
    fpGenreChange(genres[Math.floor(Math.random() * genres.length)]);
  });
  document.getElementById("movie-subscriptions-check").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Prüfe …";
    try {
      const response = await api.movieSubscriptionsCheck();
      applyMovieSubscriptions(response.movie_subscriptions || []);
    } finally {
      button.textContent = "↻ Qualitäten prüfen";
      button.disabled = !state.movieSubscriptions.items.length;
    }
  });
  document.getElementById("fp-detail-subscribe").addEventListener("click", openSelectedMovieSubscription);
  document.getElementById("movie-subscription-close").addEventListener("click", closeMovieSubscriptionModal);
  document.getElementById("movie-subscription-cancel").addEventListener("click", closeMovieSubscriptionModal);
  document.getElementById("movie-subscription-save").addEventListener("click", saveMovieSubscription);
  document.getElementById("movie-subscription-remove").addEventListener("click", removeMovieSubscription);
  document.getElementById("movie-subscription-modal").addEventListener("click", (event) => {
    if (event.target.id === "movie-subscription-modal") closeMovieSubscriptionModal();
  });
  document.querySelectorAll('input[name="movie-cleanup"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const status = document.getElementById("movie-subscription-status");
      status.textContent = !state.jellyfinUserConfigured && radio.checked && radio.value === "watched"
        ? "Für die Gesehen-Löschung muss unter Einstellungen ein Jellyfin-Profil gewählt sein."
        : "";
    });
  });
  // Serien
  document.getElementById("series-search-btn").addEventListener("click", seriesSearch);
  document.getElementById("series-search-clear").addEventListener("click", async () => {
    document.getElementById("series-search").value = "";
    syncSearchClearButtons();
    closeSearchSuggestions("series-search-suggestions", "series-search");
    await restoreSeriesSearchContext();
  });
  document.getElementById("series-search").addEventListener("input", () => {
    syncSearchClearButtons();
    renderSearchSuggestions("series", "series-search", "series-search-suggestions", seriesSearch);
  });
  document.getElementById("series-search").addEventListener("focus", () => {
    renderSearchSuggestions("series", "series-search", "series-search-suggestions", seriesSearch);
  });
  document.getElementById("series-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      seriesSearch();
    } else if (event.key === "Escape") {
      event.stopPropagation();
      closeSearchSuggestions("series-search-suggestions", "series-search");
    }
  });
  document.getElementById("series-search").addEventListener("blur", (event) => {
    if (!event.currentTarget.value.trim()) restoreSeriesSearchContext();
  });
  document.getElementById("series-discover-btn").addEventListener("click", () => seriesBrowse("discover", 1));
  document.getElementById("series-new-btn").addEventListener("click", () => seriesBrowse("new", 1));
  document.getElementById("series-trending-btn").addEventListener("click", () => seriesBrowse("trending", 1));
  document.getElementById("series-az-btn").addEventListener("click", () => {
    document.getElementById("series-alpha-bar").classList.toggle("hidden");
  });
  document.getElementById("series-select-all").addEventListener("click", () => {
    if (!state.series.current) return;
    state.series.epPicked = new Set(
      seriesEpisodes().filter(isEpisodeSelectable).map((episode) => episode.slug),
    );
    renderSeriesTiles();
  });
  document.getElementById("series-select-none").addEventListener("click", () => {
    state.series.epPicked.clear();
    renderSeriesTiles();
  });
  document.getElementById("series-add-btn").addEventListener("click", seriesAddSelected);
  document.getElementById("series-watch-btn").addEventListener("click", () => openWatchModeModal());
  document.getElementById("series-subscriptions-manage").addEventListener("click", () => switchTab("bibliothek"));
  document.addEventListener("keydown", (event) => {
    if (
      event.key !== "/"
      || event.ctrlKey
      || event.metaKey
      || event.altKey
      || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")
      || document.activeElement?.isContentEditable
    ) return;
    const input = document.getElementById("global-search-input");
    if (!input) return;
    event.preventDefault();
    document.getElementById("global-search-shell").classList.add("is-expanded");
    input.focus();
  });
  document.getElementById("anime-search-btn").addEventListener("click", () => animeBrowse("search", 1));
  document.getElementById("anime-search").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    animeBrowse("search", 1);
  });
  document.getElementById("anime-search").addEventListener("blur", (event) => {
    if (!event.currentTarget.value.trim()) restoreAnimeSearchContext();
  });
  document.getElementById("anime-latest-btn").addEventListener("click", () => animeBrowse("latest", 1));
  document.getElementById("anime-trending-btn").addEventListener("click", () => animeBrowse("trending", 1));
  document.getElementById("anime-popular-btn").addEventListener("click", () => animeBrowse("popular", 1));
  document.getElementById("anime-prev").addEventListener("click", () => {
    animeBrowse(state.anime.mode || "latest", Math.max(1, state.anime.page - 1));
  });
  document.getElementById("anime-next").addEventListener("click", () => {
    animeBrowse(state.anime.mode || "latest", state.anime.page + 1);
  });
  document.getElementById("anime-select-page").addEventListener("click", () => {
    for (const episode of state.anime.current?.episodes || []) {
      if (!episode.queued && !episode.downloaded) state.anime.picked.add(episode.slug);
    }
    renderAnimeEpisodes();
  });
  document.getElementById("anime-select-none").addEventListener("click", () => {
    state.anime.picked.clear();
    renderAnimeEpisodes();
  });
  document.getElementById("anime-episode-prev").addEventListener("click", () => {
    if (!state.anime.current || state.anime.current.page <= 1) return;
    state.anime.episodePage = state.anime.current.page - 1;
    loadAnimeDetail({ keepSelection: true });
  });
  document.getElementById("anime-episode-next").addEventListener("click", () => {
    if (!state.anime.current || state.anime.current.page >= state.anime.current.page_count) return;
    state.anime.episodePage = state.anime.current.page + 1;
    loadAnimeDetail({ keepSelection: true });
  });
  document.getElementById("anime-add-btn").addEventListener("click", animeAddSelected);
  document.getElementById("watch-mode-close").addEventListener("click", closeWatchModeModal);
  document.getElementById("watch-mode-cancel").addEventListener("click", closeWatchModeModal);
  document.getElementById("watch-mode-save").addEventListener("click", saveWatchMode);
  document.getElementById("watch-mode-remove").addEventListener("click", removeWatchModeSubscription);
  document.querySelectorAll('input[name="watch-mode"]').forEach((radio) => {
    radio.addEventListener("change", updateWatchModeRequirement);
  });
  document.querySelectorAll('input[name="watch-cleanup"]').forEach((radio) => {
    radio.addEventListener("change", updateWatchModeRequirement);
  });
  document.getElementById("watch-mode-modal").addEventListener("click", (event) => {
    if (event.target.id === "watch-mode-modal") closeWatchModeModal();
  });

  // Bibliothek
  document.getElementById("wl-check-all").addEventListener("click", async () => {
    document.getElementById("wl-status").textContent = `Prüfe ${state.wl.items.length} Serie(n) …`;
    const data = await api.watchlistCheck(null);
    applyWatchlist(data.watchlist);
    document.getElementById("wl-status").textContent = `${data.checked}/${data.total} geprüft`;
  });
  document.getElementById("wl-check-selected").addEventListener("click", async () => {
    if (!state.wl.selected.size) { alert("Bitte zuerst Serien in der Liste auswählen."); return; }
    const slugs = [...state.wl.selected];
    document.getElementById("wl-status").textContent = `Prüfe ${slugs.length} Serie(n) …`;
    const data = await api.watchlistCheck(slugs);
    applyWatchlist(data.watchlist);
    document.getElementById("wl-status").textContent = `${data.checked}/${data.total} geprüft`;
  });
  document.getElementById("wl-open").addEventListener("click", () => {
    const first = [...state.wl.selected][0];
    if (first) openWatchlistEntry(first);
  });
  document.getElementById("wl-remove").addEventListener("click", async () => {
    if (!state.wl.selected.size) return;
    const data = await api.watchlistRemove([...state.wl.selected]);
    state.wl.selected.clear();
    applyWatchlist(data.watchlist);
    await syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung");
  });

  // Benachrichtigungs-Glocke
  document.getElementById("notif-bell").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleNotifDropdown();
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".bell-wrap")) closeNotifDropdown();
  });
  document.getElementById("notif-refresh").addEventListener("click", refreshNotifications);
  document.getElementById("notif-library").addEventListener("click", () => {
    closeNotifDropdown();
    switchTab("bibliothek");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("movie-subscription-modal").classList.contains("hidden")) {
      event.preventDefault();
      closeMovieSubscriptionModal();
      return;
    }
    if (event.key === "Escape" && !document.getElementById("watch-mode-modal").classList.contains("hidden")) {
      event.preventDefault();
      closeWatchModeModal();
      return;
    }
    if (handleMediaModalKeydown(event)) return;
    if (event.key !== "Escape") return;
    closeNotifDropdown();
    setQueueDockExpanded(false);
    closeMobileQueue();
  });

  // Warteschlange / Downloads / Einstellungen
  document.getElementById("queue-clear").addEventListener("click", async () => {
    const resp = await api.queueClear();
    refreshQueueUiAfterChange(resp);
  });
  document.getElementById("serienstream-retry").addEventListener("click", async () => {
    const button = document.getElementById("serienstream-retry");
    button.disabled = true;
    try {
      const response = await api.serienstreamRetry();
      renderSerienstreamHealth(response.provider || {});
    } catch (error) {
      console.warn("SerienStream-Probe konnte nicht gestartet werden:", error);
    } finally {
      setTimeout(() => { button.disabled = false; }, 1500);
    }
  });
  document.getElementById("cancel-btn").addEventListener("click", async () => {
    const resp = await api.downloadCancel();
    renderQueue(resp.queue);
    setDownloadState("cancelled", "Abgebrochen", "Downloads wurden gestoppt", state.download.percent);
  });
  document.getElementById("settings-btn").addEventListener("click", () => switchTab("einstellungen"));
  document.getElementById("settings-save").addEventListener("click", saveAllSettings);
  document.getElementById("taste-profile-reset").addEventListener("click", async () => {
    if (!window.confirm("Geschmacksprofil wirklich vollständig zurücksetzen?")) return;
    try {
      const response = await api.tasteReset();
      applyServerTasteProfile(response.profile);
      renderHome();
    } catch (error) {
      window.alert(`Profil konnte nicht zurückgesetzt werden: ${error.message}`);
    }
  });
  document.getElementById("ui-language").addEventListener("change", (event) => {
    i18n.changeLanguage(event.target.value, { userInitiated: true }).catch((error) => {
      console.warn("Sprache konnte nicht gewechselt werden:", error);
    });
  });
  document.getElementById("updater-check").addEventListener("click", () => checkForUpdates(true));
  document.getElementById("updater-install").addEventListener("click", installUpdate);
  document.getElementById("updater-mode").addEventListener("change", (event) => {
    document.getElementById("updater-interval").disabled = event.target.value !== "automatic";
    document.getElementById("updater-mode-status").textContent = event.target.value === "automatic"
      ? "Automatisch · wird nach dem Speichern aktiviert."
      : "Manuell · wird nach dem Speichern aktiviert.";
  });
  document.getElementById("seerr-sync").addEventListener("click", async () => {
    const button = document.getElementById("seerr-sync");
    const status = document.getElementById("seerr-status");
    button.disabled = true;
    status.textContent = "Prüfe Seerr-Anfragen …";
    try {
      applySeerrCfg(await api.seerrSync());
    } catch (error) {
      status.textContent = `✗ ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById("jellyfin-users-load").addEventListener("click", () => loadJellyfinUsers({
    urlId: "jellyfin-url", keyId: "jellyfin-api-key", selectId: "jellyfin-user-id",
    buttonId: "jellyfin-users-load", statusId: "jellyfin-user-status",
  }));
  document.getElementById("browse-dir-btn").addEventListener("click", () => {
    dirModalTarget = "save-path";
    openDirModal(document.getElementById("save-path").value);
  });
  document.getElementById("browse-series-btn").addEventListener("click", () => {
    dirModalTarget = "series-path";
    openDirModal(document.getElementById("series-path").value);
  });
  document.getElementById("dir-modal-close").addEventListener("click", () => {
    document.getElementById("dir-modal").classList.add("hidden");
  });
  document.getElementById("dir-modal-select").addEventListener("click", () => {
    // Nur ins gewählte Feld übernehmen – persistiert wird über "Speichern".
    document.getElementById(dirModalTarget).value = dirModalPath;
    document.getElementById("dir-modal").classList.add("hidden");
  });

  // Ersteinrichtung
  document.getElementById("setup-browse-movies").addEventListener("click", () => {
    dirModalTarget = "setup-save-path";
    openDirModal(document.getElementById("setup-save-path").value);
  });
  document.getElementById("setup-browse-series").addEventListener("click", () => {
    dirModalTarget = "setup-series-path";
    openDirModal(document.getElementById("setup-series-path").value);
  });
  document.getElementById("setup-jellyfin-users-load").addEventListener("click", () => loadJellyfinUsers({
    urlId: "setup-jellyfin-url", keyId: "setup-jellyfin-key", selectId: "setup-jellyfin-user",
    buttonId: "setup-jellyfin-users-load",
  }));
  document.getElementById("setup-ui-language").addEventListener("change", (event) => {
    i18n.changeLanguage(event.target.value, { userInitiated: true }).catch((error) => {
      setSetupStatus(`Sprache konnte nicht geladen werden: ${error.message}`, true);
    });
  });
  document.getElementById("setup-next").addEventListener("click", () => {
    if (validateSetupStep(setupStep)) showSetupStep(setupStep + 1);
  });
  document.getElementById("setup-back").addEventListener("click", () => showSetupStep(setupStep - 1));
  document.getElementById("setup-finish").addEventListener("click", finishSetup);
  document.getElementById("setup-wizard").addEventListener("keydown", (e) => {
    if (!setupRequired || e.key !== "Enter" || e.target.closest("button") || e.target.type === "checkbox") return;
    e.preventDefault();
    if (setupStep < SETUP_STEP_COUNT) {
      if (validateSetupStep(setupStep)) showSetupStep(setupStep + 1);
    } else {
      finishSetup();
    }
  });

  document.getElementById("account-save").addEventListener("click", saveAccount);
  document.getElementById("account-logout").addEventListener("click", logoutAccount);
  document.getElementById("account-revoke").addEventListener("click", revokeOtherSessions);

  try {
    await initSettings();
  } catch (e) {
    console.error("Einstellungen konnten nicht geladen werden:", e);
  }
  const needsSetup = await initSetupWizard();
  if (!needsSetup) startInitialData();
}

document.addEventListener("DOMContentLoaded", initApp);
