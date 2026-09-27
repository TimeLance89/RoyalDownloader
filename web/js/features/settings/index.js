import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { updateDeploymentModeHints, selectedDeploymentMode } from "./deployment.js";

export function createSettings(root, {
  getFeatures, language, locale, changeLanguage, onSaved = async () => {}, client = api,
}) {
  const byId = id => root.querySelector(`#${id}`);
  let owner = createScope(), scope, pending;
  let config, dirty = false, revision = 0, saving = false;
  function render() {
    if (!config || dirty) return;
    byId("ui-language").value = language();
    const mode = ["desktop", "nas"].includes(config.deployment_mode) ? config.deployment_mode : "desktop";
    const radio = root.querySelector(`input[name="deployment-mode"][value="${mode}"]`);
    if (radio) radio.checked = true;
    updateDeploymentModeHints(root, "settings", mode);
    byId("save-path").value = config.save_path || "";
    byId("series-path").value = config.series_path || "";
  }
  function initialize() {
    if (pending) return pending;
    const current = owner;
    const request = (async () => {
      const value = await client.get("/api/config", { signal: current.signal });
      if (!current.active) return;
      config = value; render();
      const features = getFeatures();
      for (const feature of [features.jellyfin, features.intelligence, features.automation, features.providers]) {
        await feature.initialize();
        if (!current.active) return;
      }
    })().finally(() => { if (pending === request) pending = null; });
    pending = request; return request;
  }
  async function save() {
    if (!scope?.active || saving) return;
    const current = scope, atRevision = revision;
    const button = byId("settings-save"), status = byId("settings-saved-status");
    saving = true; button.disabled = true; status.textContent = "Speichere …";
    try {
      await client.post("/api/ui/config", { language: byId("ui-language").value }, { signal: current.signal });
      if (!current.active) return;
      const value = await client.post("/api/config", {
        save_path: byId("save-path").value.trim(), series_path: byId("series-path").value.trim(),
        deployment_mode: selectedDeploymentMode(root),
      }, { signal: current.signal });
      if (!current.active) return;
      config = value;
      const features = getFeatures();
      const operations = [
        () => features.providers.save({ signal: current.signal }), () => features.jellyfin.save(),
        () => features.integrations.save("tmdb"), () => features.intelligence.save(),
        () => features.automation.save(), () => features.updater.save(),
        () => features.integrations.save("seerr"), () => features.integrations.save("telegram"),
      ];
      for (const operation of operations) {
        await operation();
        if (!current.active) return;
      }
      await onSaved({ signal: current.signal });
      if (!current.active) return;
      if (atRevision === revision) { dirty = false; render(); }
      const time = new Date().toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
      status.textContent = value.restart_required
        ? `✓ Gespeichert (${time}) · Neustart aktiviert den neuen Betriebsmodus.` : `✓ Gespeichert (${time})`;
    } catch (error) {
      if (current.active) status.textContent = "✗ Fehler: " + error.message;
    } finally { if (current.active) { saving = false; button.disabled = false; } }
  }
  return {
    initialize, save,
    mount() {
      if (scope) return;
      if (!owner.active) owner = createScope();
      const current = scope = createScope();
      saving = false; byId("settings-save").disabled = false; render();
      current.listen(byId("settings-save"), "click", save);
      const changed = () => { dirty = true; revision++; };
      for (const id of ["save-path", "series-path", "ui-language"]) current.listen(byId(id), "input", changed);
      for (const radio of root.querySelectorAll('input[name="deployment-mode"]')) current.listen(radio, "change", () => {
        changed(); updateDeploymentModeHints(root, "settings", selectedDeploymentMode(root));
      });
      current.listen(byId("ui-language"), "change", event => {
        changed();
        void changeLanguage(event.target.value).catch(error => {
          if (current.active) byId("settings-saved-status").textContent = error.message;
        });
      });
    },
    refresh() { render(); },
    unmount() { scope?.dispose(); scope = null; saving = false; },
    dispose() { owner.dispose(); scope?.dispose(); scope = null; saving = false; pending = null; },
    resume() { if (!owner.active) owner = createScope(); },
  };
}
