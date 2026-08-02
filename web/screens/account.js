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
