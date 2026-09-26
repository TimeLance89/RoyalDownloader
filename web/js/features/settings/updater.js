import { api } from "../../core/api.js";
import { websocket } from "../../core/websocket.js";
import { createScope } from "../../core/lifecycle.js";

export function createUpdater(root, { client = api, socket = websocket, reload = () => location.reload() } = {}) {
  const byId = id => id === "updater-card" ? root : root.querySelector(`#${id}`);
  let scope;
  let dirty = false;
  let savedConfig = null;
  function shortRevision(value) {
    const revision = String(value || "").trim();
    return revision ? revision.slice(0, 8) : "unbekannt";
  }

  function applyUpdaterConfig(cfg) {
    savedConfig = cfg;
    if (dirty) return;
    const mode = cfg.update_mode === "automatic" ? "automatic" : "manual";
    const channel = cfg.update_channel === "overnight" ? "overnight" : "stable";
    const interval = Math.max(1, Math.min(168, Number(cfg.auto_update_interval_hours) || 6));
    const channelSelect = byId("updater-channel");
    const modeSelect = byId("updater-mode");
    const intervalInput = byId("updater-interval");
    const status = byId("updater-mode-status");
    channelSelect.value = channel;
    channelSelect.dataset.savedChannel = channel;
    byId("updater-channel-hint").textContent = channel === "overnight"
      ? "Overnight · früher Zugriff aus overnight; kann instabil sein."
      : "Stable · geprüfte und freigegebene Änderungen aus main (empfohlen).";
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
    const card = byId("updater-card");
    const status = byId("updater-status");
    const detail = byId("updater-detail");
    const badge = byId("updater-badge");
    const repository = byId("updater-repository");
    const installButton = byId("updater-install");
    const channel = data.update_channel === "overnight" ? "overnight" : "stable";
    const branch = data.update_branch || data.branch || (channel === "overnight" ? "overnight" : "main");
    const channelLabel = channel === "overnight" ? "Overnight" : "Stable";
    const switchWarning = byId("updater-switch-warning");
    if (data.config) applyUpdaterConfig(data.config);
    byId("updater-version").textContent =
      String(data.application_version || "unbekannt");
    byId("updater-current").textContent = shortRevision(data.current_sha);
    byId("updater-latest").textContent = shortRevision(data.latest_sha);
    installButton.dataset.sha = String(data.latest_sha || "");
    installButton.textContent = "Jetzt updaten";
    installButton.dataset.confirmChannelSwitch = data.channel_switch_requires_confirmation ? "true" : "false";
    byId("updater-branch-label").textContent = `${channelLabel} · ${branch}`;
    switchWarning.classList.toggle("hidden", !data.possible_downgrade);
    switchWarning.textContent = data.possible_downgrade
      ? "Rückwechsel zu Stable erkannt: Der Zielstand kann älter sein. Vor der Installation ist eine ausdrückliche Bestätigung erforderlich; der vorhandene Backup- und Rollback-Ablauf bleibt aktiv."
      : "";
    if (String(data.repository_url || "").startsWith("https://github.com/")) {
      repository.href = data.repository_url;
    }
    const installer = data.installer || {};
    const errorForOfferedTarget = installer.state === "error"
      && installer.target_sha === data.latest_sha
      && data.update_available === true
      && !data.error
      && !(channel === "overnight" && data.quality_approved === false);
    if (installer.active || errorForOfferedTarget) {
      installButton.classList.toggle("hidden", installer.state !== "error");
      applyUpdaterInstallStatus(installer);
      return;
    }
    card.dataset.installing = "false";
    byId("updater-check").disabled = false;
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
    if (channel === "overnight" && data.quality_approved === false) {
      card.dataset.state = data.quality_gate === "failed" ? "error" : "unknown";
      badge.textContent = data.quality_gate === "failed" ? "!" : "CI";
      status.textContent = data.quality_gate === "failed"
        ? "Overnight-Quality fehlgeschlagen"
        : "Overnight wird noch geprüft";
      detail.textContent = "Dieser Commit wird erst nach erfolgreichen vollständigen Quality Gates als Update angeboten.";
      return;
    }
    if (data.possible_downgrade) {
      card.dataset.state = "available";
      badge.textContent = "↘";
      status.textContent = "Bestätigter Branchwechsel erforderlich";
      detail.textContent = `Der Stable-Stand auf ${branch} liegt hinter dem installierten Build oder ist davon abgezweigt.`;
      installButton.textContent = "Zu Stable wechseln";
      installButton.classList.remove("hidden");
      return;
    }
    if (data.update_available === true) {
      const commits = Number(data.ahead_by || 0);
      card.dataset.state = "available";
      badge.textContent = "↑";
      status.textContent = "Update verfügbar";
      detail.textContent = commits
        ? `${commits} ${commits === 1 ? "neuer Commit" : "neue Commits"} auf ${channelLabel} (${branch})`
        : `Neuer Stand auf ${channelLabel} (${branch})`;
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

  let cancelPoll = () => {};
  let updaterRestartStartedAt = 0;
  let updaterRestartTarget = "";
  const UPDATER_RESTART_TIMEOUT_MS = 180000;

  function applyUpdaterInstallStatus(installer) {
    const offeredTarget = byId("updater-install").dataset.sha;
    if (!installer.active && installer.state === "error" && installer.target_sha
      && offeredTarget && installer.target_sha !== offeredTarget) return;
    cancelPoll();
    const card = byId("updater-card");
    const status = byId("updater-status");
    const detail = byId("updater-detail");
    const badge = byId("updater-badge");
    const checkButton = byId("updater-check");
    const installButton = byId("updater-install");
    const active = !!installer.active;
    card.dataset.installing = active ? "true" : "false";
    checkButton.disabled = active;
    installButton.disabled = active || installer.supported === false;
    if (installer.target_sha && (active || !offeredTarget)) installButton.dataset.sha = installer.target_sha;

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
    if (installer.state === "restarting") {
      waitForUpdatedServer(installer.target_sha || installButton.dataset.sha || "");
    } else if (active) scheduleUpdaterInstallPoll();
  }

  function scheduleUpdaterInstallPoll() {
    if (!scope?.active) return;
    const current = scope;
    cancelPoll();
    cancelPoll = current.timeout(async () => {
      try {
        const response = await client.get("/api/updater/install/status", { signal: current.signal });
        if (!current.active) return;
        const installer = response.installer || {};
        applyUpdaterInstallStatus(installer);
      } catch (error) {
        if (!current.active) return;
        scheduleUpdaterInstallPoll();
      }
    }, 900);
  }

  async function waitForUpdatedServer(targetSha) {
    if (!scope?.active) return;
    const current = scope;
    const normalizedTarget = String(targetSha || "").trim().toLowerCase();
    if (!normalizedTarget) {
      applyUpdaterInstallStatus({
        state: "error",
        error: "Update-Ziel fehlt; der Neustart kann nicht verifiziert werden.",
        supported: true,
      });
      return;
    }
    if (updaterRestartTarget !== normalizedTarget) {
      updaterRestartTarget = normalizedTarget;
      updaterRestartStartedAt = Date.now();
    }
    cancelPoll();
    cancelPoll = current.timeout(async () => {
      try {
        const payload = await client.get(
          `/api/updater/status?force=true&_=${Date.now()}`,
          { cache: "no-store", signal: current.signal },
        );
        if (!current.active) return;
        const installed = String(payload.current_sha || "").trim().toLowerCase();
        if (installed === normalizedTarget) {
          updaterRestartStartedAt = 0;
          updaterRestartTarget = "";
          reload();
          return;
        }
        if (Date.now() - updaterRestartStartedAt >= UPDATER_RESTART_TIMEOUT_MS) {
          applyUpdaterInstallStatus({
            state: "error",
            error: `Neustart fehlgeschlagen: installiert ${shortRevision(installed)}, erwartet ${shortRevision(normalizedTarget)}.`,
            target_sha: normalizedTarget,
            supported: true,
          });
          return;
        }
        waitForUpdatedServer(normalizedTarget);
      } catch (error) {
        if (!current.active) return;
        if (Date.now() - updaterRestartStartedAt >= UPDATER_RESTART_TIMEOUT_MS) {
          applyUpdaterInstallStatus({
            state: "error",
            error: `Server nach Update nicht erreichbar: ${error.message}`,
            target_sha: normalizedTarget,
            supported: true,
          });
          return;
        }
        waitForUpdatedServer(normalizedTarget);
      }
    }, 3000);
  }

  async function installUpdate() {
    if (!scope?.active) return;
    const current = scope;
    const button = byId("updater-install");
    const targetSha = button.dataset.sha || "";
    if (!targetSha || button.disabled) return;
    const needsConfirmation = button.dataset.confirmChannelSwitch === "true";
    if (needsConfirmation && !window.confirm(
      "Zu Stable wechseln? Der Stable-Build kann älter sein. Einstellungen und Daten werden nicht gelöscht; vor der Aktivierung bleibt der vorhandene Rollback-Punkt erhalten.",
    )) return;
    button.disabled = true;
    try {
      const response = await client.post("/api/updater/install", { target_sha: targetSha, confirm_channel_switch: needsConfirmation }, { signal: current.signal });
      if (!current.active) return;
      applyUpdaterInstallStatus(response.installer || {});
    } catch (error) {
      if (!current.active) return;
      applyUpdaterInstallStatus({ state: "error", error: error.message, supported: true });
    }
  }

  async function checkForUpdates(force = false) {
    if (!scope?.active) return;
    const current = scope;
    const button = byId("updater-check");
    const card = byId("updater-card");
    const status = byId("updater-status");
    const detail = byId("updater-detail");
    button.disabled = true;
    card.dataset.state = "checking";
    status.textContent = "Prüfe GitHub …";
    detail.textContent = "Neuester Stand wird geladen.";
    try {
      const result = await client.get(`/api/updater/status?${new URLSearchParams({ force: String(force) })}`, { signal: current.signal });
      if (!current.active) return;
      applyUpdaterStatus(result);
    } catch (error) {
      if (!current.active) return;
      applyUpdaterStatus({ error: error.message });
    } finally {
      if (current.active) button.disabled = card.dataset.installing === "true";
    }
  }


  async function save() {
    if (!scope?.active) return;
    const current = scope;
    const result = await client.post("/api/updater/config", {
      update_mode: byId("updater-mode").value,
      update_channel: byId("updater-channel").value,
      auto_update_interval_hours: Math.max(1, Math.min(168, parseInt(byId("updater-interval").value, 10) || 6)),
    }, { signal: current.signal });
    if (!current.active) return;
    dirty = false; applyUpdaterConfig(result);
    await checkForUpdates(true);
    return result;
  }
  return {
    save, refresh: checkForUpdates,
    mount() {
      if (scope) return;
      scope = createScope();
      byId("updater-channel").disabled = false;
      if (savedConfig) applyUpdaterConfig(savedConfig);
      scope.listen(root, "input", () => { dirty = true; });
      scope.add(socket.subscribe("updater_install", data => applyUpdaterInstallStatus(data.installer || {})));
      scope.add(socket.subscribe("updater_config", data => applyUpdaterConfig(data.config || {})));
      scope.add(socket.subscribe("connection.open", () => void checkForUpdates(false)));
      scope.listen(byId("updater-check"), "click", () => checkForUpdates(true));
      scope.listen(byId("updater-install"), "click", installUpdate);
      scope.listen(byId("updater-channel"), "change", async (event) => {
        const current = scope;
        const select = event.currentTarget;
        const previous = select.dataset.savedChannel || "stable";
        if (
          select.value === "overnight"
          && previous !== "overnight"
          && !window.confirm(
            "Zum Overnight-Kanal wechseln? Dieser Entwicklungskanal erhält Änderungen früher und kann instabil sein. Updates nutzen weiterhin Backup und Rollback.",
          )
        ) {
          select.value = previous;
          return;
        }
        byId("updater-channel-hint").textContent = select.value === "overnight"
          ? "Overnight · früher Zugriff aus overnight; kann instabil sein."
          : "Stable · geprüfte und freigegebene Änderungen aus main (empfohlen).";
        const status = byId("updater-mode-status");
        const selected = select.value;
        select.disabled = true;
        status.textContent = `${selected === "overnight" ? "Overnight" : "Stable"} wird gespeichert …`;
        try {
          const saved = await client.post("/api/updater/config", {
            update_mode: byId("updater-mode").value,
            update_channel: selected,
            auto_update_interval_hours: Math.max(
              1,
              Math.min(168, parseInt(byId("updater-interval").value, 10) || 6),
            ),
          }, { signal: current.signal });
          if (!current.active) return;
          dirty = false;
          applyUpdaterConfig(saved);
          await checkForUpdates(true);
        } catch (error) {
          if (!current.active) return;
          select.value = previous;
          select.dataset.savedChannel = previous;
          status.textContent = `Kanalwechsel fehlgeschlagen · ${error.message}`;
        } finally {
          if (current.active) select.disabled = false;
        }
      });
      scope.listen(byId("updater-mode"), "change", (event) => {
        byId("updater-interval").disabled = event.target.value !== "automatic";
        byId("updater-mode-status").textContent = event.target.value === "automatic"
          ? "Automatisch · wird nach dem Speichern aktiviert."
          : "Manuell · wird nach dem Speichern aktiviert.";
      });
      void checkForUpdates(false);
    },
    unmount() { scope?.dispose(); scope = null; cancelPoll(); },
  };
}
