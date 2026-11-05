import { createOperationSettings } from "./operation.js";
import { createEventSettings } from "./seasonal-events.js";
import { createLanguageSetup } from "./language-setup.js";
import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { updateDeploymentModeHints, selectedDeploymentMode } from "./deployment.js";
import { createAnnouncementSettings } from "../announcements/settings.js";

export function createSettings(root, {
  getFeatures, language, locale, changeLanguage, onSaved = async () => {}, onLanguageReady = onSaved, languageWizard, events, client = api,
}) {
  const byId = id => root.querySelector(`#${id}`);
  let owner = createScope(), scope, pending;
  let config, dirty = false, revision = 0, saving = false;
  const operation = createOperationSettings(root, { getConfig: () => config, client, applyMode: (mode, signal) => savePaths(mode, signal) });
  const announcementSettings = createAnnouncementSettings(root, client);
  const eventSettings = createEventSettings(root, { events });
  const languageSetup = languageWizard || createLanguageSetup(root.ownerDocument.getElementById("language-setup-dialog"), {
    client, language, changeLanguage,
    providers: { apply: value => getFeatures().providers.apply(value) },
    onReady: onLanguageReady,
    onComplete() { render(); byId("language-profile-label").textContent = byId("ui-language").selectedOptions?.[0]?.textContent || language(); },
  });
  function render() {
    if (!config || dirty) return;
    byId("ui-language").value = language();
    byId("language-profile-label").textContent = byId("ui-language").selectedOptions?.[0]?.textContent || language();
    const mode = ["desktop", "nas"].includes(config.deployment_mode) ? config.deployment_mode : "desktop";
    const radio = root.querySelector(`input[name="deployment-mode"][value="${mode}"]`);
    if (radio) radio.checked = true;
    updateDeploymentModeHints(root, "settings", mode);
    byId("save-path").value = config.save_path || "";
    byId("series-path").value = config.series_path || "";
    operation.render();
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
  async function savePaths(mode, signal = scope?.signal) {
    if (!scope?.active || !config) throw new Error("Einstellungen sind noch nicht geladen.");
    const value = await client.post("/api/config", {
      save_path: mode ? config.save_path : byId("save-path").value.trim(),
      series_path: mode ? config.series_path : byId("series-path").value.trim(),
      deployment_mode: mode || config.deployment_mode,
    }, { signal });
    if (signal?.aborted || !scope?.active) return;
    config = value;
    const radio = root.querySelector(`input[name="deployment-mode"][value="${value.deployment_mode}"]`);
    if (radio) radio.checked = true;
    if (!mode) { dirty = false; render(); }
    operation.render();
    root.dispatchEvent(new CustomEvent("royal:storage-paths-changed"));
    return value;
  }
  async function save() {
    if (!scope?.active || saving) return;
    const current = scope, atRevision = revision;
    const button = byId("settings-save"), status = byId("settings-saved-status");
    const completed = [];
    let savingSection = "Betrieb und Speicher";
    let refreshStarted = false;
    saving = true; button.disabled = true; status.textContent = "Speichere …";
    try {
      if (pending) await pending;
      if (!current.active) return;
      if (!config) throw new Error("Einstellungen müssen vor dem Speichern geladen werden.");
      const value = await client.post("/api/config", {
        save_path: byId("save-path").value.trim(), series_path: byId("series-path").value.trim(),
        deployment_mode: selectedDeploymentMode(root),
      }, { signal: current.signal });
      if (!current.active) return;
      config = value;
      completed.push(savingSection);
      const features = getFeatures();
      const operations = [
        ["Quellen", () => features.providers.save({ signal: current.signal })], ["Jellyfin", () => features.jellyfin.save()],
        ["TMDB", () => features.integrations.save("tmdb")], ["KI", () => features.intelligence.save()],
        ["Automatik", () => features.automation.save()], ["Updates", () => features.updater.save()],
        ["Seerr", () => features.integrations.save("seerr")], ["Telegram", () => features.integrations.save("telegram")],
      ];
      for (const [section, operation] of operations) {
        savingSection = section;
        await operation();
        if (!current.active) return;
        completed.push(section);
      }
      savingSection = "Oberfläche aktualisieren";
      refreshStarted = true;
      await onSaved({ signal: current.signal });
      if (!current.active) return;
      if (atRevision === revision) { dirty = false; render(); }
      const time = new Date().toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
      status.textContent = value.restart_required
        ? `✓ Gespeichert (${time}) · Neustart aktiviert den neuen Betriebsmodus.` : `✓ Gespeichert (${time})`;
    } catch (error) {
      if (current.active && completed.includes("Quellen") && !refreshStarted) {
        try { await onSaved({ signal: current.signal }); }
        catch (refreshError) { console.warn("Teilweise gespeicherte Einstellungen konnten nicht aktualisiert werden:", refreshError); }
      }
      if (current.active) status.textContent = completed.length
        ? `Teilweise gespeichert (${completed.join(", ")}). Fehler bei ${savingSection}: ${error.message}`
        : "✗ Fehler: " + error.message;
    } finally { if (current.active) { saving = false; button.disabled = false; } }
  }
  return {
    initialize, save, openLanguageSetup: options => languageSetup.open(options),
    mount() {
      if (scope) return;
      if (!owner.active) owner = createScope();
      const current = scope = createScope();
      saving = false; byId("settings-save").disabled = false; render();
      current.listen(byId("settings-save"), "click", save);
      announcementSettings.mount(); operation.mount();
      eventSettings.mount();
      if (byId("storage-base-save")) current.listen(byId("storage-base-save"), "click", async () => {
        const button = byId("storage-base-save"), status = byId("storage-base-status");
        button.disabled = true; status.textContent = "Ordner werden geprüft …";
        try { await savePaths(); if (current.active) { status.textContent = "Ordner gespeichert. Bestehende Dateien bleiben an ihrem Ort."; byId("settings-saved-status").textContent = "Speicherordner gespeichert."; } }
        catch (error) { if (current.active) status.textContent = error.message; }
        finally { if (current.active) button.disabled = false; }
      });
      const changed = () => { dirty = true; revision++; };
      for (const id of ["save-path", "series-path"]) current.listen(byId(id), "input", changed);
      for (const radio of root.querySelectorAll('input[name="deployment-mode"]')) current.listen(radio, "change", () => {
        changed(); updateDeploymentModeHints(root, "settings", selectedDeploymentMode(root));
      });
      for (const button of root.querySelectorAll("[data-language-setup-open]")) current.listen(button, "click", () => { void languageSetup.open(); });
      current.listen(byId("ui-language"), "change", event => {
        const target = event.target.value;
        event.target.value = language();
        void languageSetup.open({ uiLanguage: target });
      });
    },
    refresh() { render(); },
    unmount() { eventSettings.unmount(); operation.unmount(); announcementSettings.unmount(); languageSetup.dispose(); scope?.dispose(); scope = null; saving = false; },
    dispose() { eventSettings.unmount(); operation.unmount(); announcementSettings.unmount(); languageSetup.dispose(); owner.dispose(); scope?.dispose(); scope = null; saving = false; pending = null; },
    resume() { if (!owner.active) owner = createScope(); },
  };
}
