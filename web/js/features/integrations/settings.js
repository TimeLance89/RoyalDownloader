import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { integrationHealth } from "./health.js";

export function createIntegrationSettings(root, { client = api } = {}) {
  const byId = id => root.querySelector(`#${id}`);
  const kinds = ["seerr", "tmdb", "telegram"];
  const dirty = new Set();
  const revisions = new Map();
  const server = new Map();
  let scope;
  let pending;
  function applySeerrCfg(cfg, preserveForm = false) {
    if (!preserveForm) {
      byId("seerr-enabled").checked = !!cfg.enabled;
      byId("seerr-url").value = cfg.url || "";
      byId("seerr-poll-interval").value = cfg.poll_interval_seconds ?? 60;
      const key = byId("seerr-api-key");
      key.value = "";
      key.placeholder = cfg.has_api_key
        ? "Gespeichert · leer lassen zum Beibehalten"
        : "Seerr → Einstellungen → Allgemein";
    }
    const status = byId("seerr-status");
    const counts = cfg.requests || {};
    const queued = (counts.queued || 0) + (counts.resolving || 0);
    if (!cfg.enabled) status.textContent = "Seerr-Brücke aus";
    else if (cfg.last_error) status.textContent = `✗ ${cfg.last_error}`;
    else if (cfg.moonfin_error) status.textContent = `Seerr aktiv · ${cfg.moonfin_error}`;
    else if (!cfg.connected) status.textContent = "Konfiguriert · Verbindung wird beim nächsten Abgleich geprüft";
    else status.textContent = `Verbunden${cfg.moonfin_configured ? " · Moonfin bereit" : ""} · ${queued} offen · ${counts.completed || 0} abgeschlossen`;
  }

  function applyTmdbCfg(cfg, preserveForm = false) {
    if (!preserveForm) {
      const input = byId("tmdb-api-key");
      input.value = "";
      input.placeholder = cfg.has_api_key ? "Gespeichert · leer lassen zum Beibehalten" : "TMDB API-Key";
    }
    const status = byId("tmdb-status");
    if (!cfg.configured) status.textContent = "TMDB aus · Anbieterdaten werden verwendet";
    else if (cfg.valid === false) status.textContent = "✗ API-Key ungültig oder TMDB nicht erreichbar";
    else status.textContent = `TMDB aktiv · Sprache ${cfg.language === "de-DE" ? "Deutsch" : "Englisch"}`;
  }

  function applyTelegramCfg(cfg, preserveForm = false) {
    if (!preserveForm) {
      byId("telegram-enabled").checked = !!cfg.enabled;
      const token = byId("telegram-token");
      token.value = "";
      token.placeholder = cfg.has_bot_token ? "Gespeichert · leer lassen zum Beibehalten" : "123456789:AA…";
      byId("telegram-chat-id").value = cfg.chat_id || "";
    }
    const status = byId("telegram-status");
    if (!cfg.enabled) status.textContent = "Telegram-Bot aus";
    else if (!cfg.has_bot_token) status.textContent = "Bot-Token fehlt";
    else if (!cfg.chat_id) status.textContent = "Einrichtungsmodus · /start an den Bot senden";
    else status.textContent = `Aktiv · nur Chat ${cfg.chat_id}`;
  }


  const renderers = { seerr: applySeerrCfg, tmdb: applyTmdbCfg, telegram: applyTelegramCfg };
  function payload(kind) {
    if (kind === "tmdb") return { api_key: byId("tmdb-api-key").value.trim() };
    if (kind === "telegram") return { enabled: byId("telegram-enabled").checked,
      bot_token: byId("telegram-token").value.trim(), chat_id: byId("telegram-chat-id").value.trim() };
    return { enabled: byId("seerr-enabled").checked, url: byId("seerr-url").value.trim(),
      api_key: byId("seerr-api-key").value.trim(),
      poll_interval_seconds: Math.max(15, Math.min(3600, parseInt(byId("seerr-poll-interval").value, 10) || 60)) };
  }
  async function syncFeatureCapabilities() {
    if (!scope?.active) return;
    const current = scope;
    const button = byId("seerr-sync"), status = byId("seerr-status");
    try {
      const result = await client.get("/api/modules", { signal: current.signal });
      if (!current.active) return;
      const seerr = (result.modules || []).find(module => module.id === "seerr-sync");
      const available = Boolean(seerr?.enabled && seerr.runtime_status === "running"
        && ["healthy", "degraded"].includes(integrationHealth(seerr).state));
      button.disabled = !available; button.dataset.moduleAvailable = String(available);
      if (!available && seerr) status.textContent = seerr.enabled
        ? `Seerr-Modul nicht bereit · ${seerr.configuration_detail}` : "Seerr-Modul deaktiviert · Einstellungen → Module";
    } catch (error) {
      if (!current.active) return;
      button.disabled = true; status.textContent = `Modulstatus nicht erreichbar: ${error.message}`;
    }
  }
  function refresh() {
    if (!scope?.active) return Promise.resolve();
    if (pending) return pending;
    const current = scope;
    const request = Promise.all(kinds.map(async kind => {
      try {
        const value = await client.get(`/api/${kind}/config`, { signal: current.signal });
        if (!current.active) return;
        server.set(kind, value);
        renderers[kind](value, dirty.has(kind));
      } catch (error) { if (current.active) byId(`${kind}-status`).textContent = `Konfiguration nicht abrufbar: ${error.message}`; }
    })).then(() => { if (current.active) return syncFeatureCapabilities(); })
      .finally(() => { if (pending === request) pending = null; });
    pending = request;
    return request;
  }
  async function save(kind) {
    if (!scope?.active) return;
    const current = scope;
    if (pending) await pending;
    if (!current.active) return;
    if (!dirty.has(kind)) return server.get(kind);
    if (!server.has(kind)) throw new Error("Konfiguration muss vor dem Speichern erfolgreich geladen werden.");
    const revision = revisions.get(kind);
    const value = await client.post(`/api/${kind}/config`, payload(kind), { signal: current.signal });
    if (!current.active) return;
    server.set(kind, value);
    if (revisions.get(kind) === revision) dirty.delete(kind);
    renderers[kind](value, dirty.has(kind));
    if (kind === "seerr") await syncFeatureCapabilities();
    return value;
  }
  async function syncSeerr() {
    if (!scope?.active) return;
    const current = scope;
    const button = byId("seerr-sync"), status = byId("seerr-status");
    if (button.disabled) return;
    button.disabled = true; status.textContent = "Prüfe Seerr-Anfragen …";
    try {
      const value = await client.post("/api/seerr/sync", {}, { signal: current.signal });
      if (current.active) { server.set("seerr", value); applySeerrCfg(value, dirty.has("seerr")); }
    } catch (error) { if (current.active) status.textContent = `✗ ${error.message}`; }
    finally { if (current.active) button.disabled = button.dataset.moduleAvailable !== "true"; }
  }
  return {
    refresh, save,
    mount() {
      if (scope) return;
      scope = createScope();
      for (const kind of kinds) {
        const card = root.querySelector(`.${kind}-settings`);
        const changed = () => { dirty.add(kind); revisions.set(kind, (revisions.get(kind) || 0) + 1); };
        scope.listen(card, "input", changed); scope.listen(card, "change", changed);
      }
      scope.listen(byId("seerr-sync"), "click", syncSeerr);
      scope.listen(root.ownerDocument, "royal:modules-changed", syncFeatureCapabilities);
      void refresh();
    },
    unmount() { scope?.dispose(); scope = null; pending = null; },
  };
}
