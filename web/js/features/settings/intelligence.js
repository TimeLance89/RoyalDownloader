import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createIntelligenceSettings(root, { client = api, onConfig = () => {} } = {}) {
  const config = { enabled: false, configured: false, model: "", moduleAvailable: false };
  const byId = id => root.querySelector(`#${id}`);
  let scope;
  let testing = false;
  let initialization = null;
  let initializeScope;
  let initialized = false;
  let dirty = false, revision = 0;
  const fields = ["ai-enabled", "ai-url", "ai-model", "ai-timeout"];
  const edits = new Map();
  function aiFormConfig() {
    return {
      enabled: Boolean(byId("ai-enabled")?.checked),
      url: byId("ai-url")?.value.trim() || "http://127.0.0.1:11434",
      model: byId("ai-model")?.value.trim() || "llama3.2:3b",
      timeout_seconds: Math.max(
        30,
        Math.min(300, Number(byId("ai-timeout")?.value) || 180),
      ),
    };
  }

  function syncAiSettingsState() {
    const enabled = Boolean(byId("ai-enabled")?.checked);
    ["ai-url", "ai-model", "ai-test"].forEach((id) => {
      const element = byId(id);
      if (element) element.disabled = !enabled;
    });
    const status = byId("ai-status");
    if (!status) return;
    const badge = byId("ai-provider-badge");
    const privacy = byId("ai-privacy-note");
    if (badge) badge.textContent = "LOKAL";
    if (privacy) privacy.textContent = "Royal Reflex verarbeitet kompakte Katalogmetadaten und dein Geschmacksprofil ausschließlich lokal über Ollama.";
    if (enabled !== config.enabled) {
      status.textContent = enabled
        ? "Aktivierung noch speichern."
        : "Deaktivierung noch speichern.";
    } else if (enabled) {
      status.textContent = `Aktiviert · ${config.model || "Royal Intelligence"} kuratiert die Discovery.`;
    } else {
      status.textContent = "Deaktiviert · Royal nutzt das klassische Ranking.";
    }
  }

  function applyAiConfig(value = {}, preserveForm = dirty) {
    initialized = true;
    config.enabled = Boolean(value.enabled);
    config.configured = Boolean(value.configured);
    config.model = String(value.model || "");
    config.moduleAvailable = Boolean(value.module_available);
    const enabled = byId("ai-enabled");
    const url = byId("ai-url");
    const model = byId("ai-model");
    const timeout = byId("ai-timeout");
    if (enabled && (!preserveForm || !edits.has("ai-enabled"))) enabled.checked = config.enabled;
    if (url && (!preserveForm || !edits.has("ai-url"))) url.value = value.url || "http://127.0.0.1:11434";
    if (model && (!preserveForm || !edits.has("ai-model"))) model.value = value.model || "llama3.2:3b";
    if (timeout && (!preserveForm || !edits.has("ai-timeout"))) timeout.value = String(value.timeout_seconds || 180);
    syncAiSettingsState();
    onConfig();
  }

  async function testAiConnection() {
    if (!scope?.active || testing) return;
    const current = scope;
    testing = true;
    const button = byId("ai-test");
    const status = byId("ai-status");
    if (!button || !status) { testing = false; return; }
    button.disabled = true;
    status.textContent = "Provider wird geprüft …";
    try {
      const result = await client.post("/api/intelligence/test", aiFormConfig(), { signal: current.signal });
      if (!current.active) return;
      const models = Array.isArray(result.models) ? result.models : [];
      const datalist = byId("ai-models");
      if (datalist) {
        datalist.replaceChildren(...models.map((name) => {
          const option = root.ownerDocument.createElement("option");
          option.value = name;
          return option;
        }));
      }
      status.textContent = result.model_available
        ? `Verbunden · ${models.length} Modell(e) verfügbar.`
        : `Verbunden · Modell noch nicht geladen (${models.length} verfügbar).`;
      if (Boolean(byId("ai-enabled")?.checked) !== config.enabled) {
        status.textContent += " · Aktivierung noch speichern.";
      }
    } catch (error) {
      if (!current.active) return;
      status.textContent = `Nicht erreichbar · ${error.message}`;
    } finally {
      if (current.active) { testing = false; button.disabled = !byId("ai-enabled")?.checked; }
    }
  }

  async function saveAiSettings() {
    const current = scope;
    if (!current?.active) return;
    if (initialization) await initialization;
    if (!current.active) return;
    if (!dirty) return { ...config };
    if (!initialized) throw new Error("KI-Konfiguration muss vor dem Speichern geladen werden.");
    const atRevision = revision;
    const value = await client.post("/api/intelligence/config", aiFormConfig(), { signal: current.signal });
    if (current.active) {
      for (const [id, version] of edits) if (version <= atRevision) edits.delete(id);
      dirty = edits.size > 0;
      applyAiConfig(value);
    }
    return value;
  }

  function initialize() {
    if (initialization) return initialization;
    const current = createScope();
    initializeScope = current;
    const request = client.get("/api/intelligence/config", { signal: current.signal })
      .then(value => { if (current.active) applyAiConfig(value); })
      .finally(() => {
        current.dispose();
        if (initialization === request) initialization = null;
      });
    initialization = request;
    return request;
  }

  return {
    get: () => Object.freeze({ ...config }), apply: applyAiConfig, save: saveAiSettings,
    initialize,
    mount() {
      if (scope) return;
      scope = createScope();
      const changed = event => {
        dirty = true; revision++;
        const changedFields = fields.includes(event.target.id) ? [event.target.id] : fields;
        changedFields.forEach(id => edits.set(id, revision));
      };
      scope.listen(root, "input", changed);
      scope.listen(root, "change", changed);
      scope.listen(byId("ai-test"), "click", testAiConnection);
      scope.listen(byId("ai-enabled"), "change", syncAiSettingsState);
      syncAiSettingsState();
      if (!initialized) void initialize().catch(error => { if (scope?.active) byId("ai-status").textContent = error.message; });
    },
    refresh: syncAiSettingsState,
    unmount() { scope?.dispose(); scope = null; testing = false; initializeScope?.dispose(); initialization = null; },
  };
}
