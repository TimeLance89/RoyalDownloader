import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { createJellyfinUserPicker, fillJellyfinUsers } from "./jellyfin-users.js";

export function createJellyfinSettings(root, { client = api } = {}) {
  const byId = id => root.querySelector(`#${id}`);
  let config = {}, initialized = false;
  let owner = createScope(), scope, pending;
  let revision = 0, dirty = false;
  const picker = createJellyfinUserPicker(root, { client, urlId: "jellyfin-url", keyId: "jellyfin-api-key",
    selectId: "jellyfin-user-id", buttonId: "jellyfin-users-load", statusId: "jellyfin-user-status" });
  const cleanupDefault = () => ["keep", "watched_seasons", "watched_episodes"].includes(config.cleanup_default) ? config.cleanup_default : "keep";
  function render() {
    if (!scope?.active || dirty) return;
    byId("jellyfin-url").value = config.url || "";
    const key = byId("jellyfin-api-key"); key.value = "";
    key.placeholder = config.has_api_key ? "Gespeichert · leer lassen zum Beibehalten" : "API-Schlüssel";
    fillJellyfinUsers(byId("jellyfin-user-id"), [], config.user_id || "", config.user_name || "");
    root.querySelectorAll('input[name="jellyfin-cleanup-default"]').forEach(radio => { radio.checked = radio.value === cleanupDefault(); });
    byId("jellyfin-user-status").textContent = config.user_id
      ? `Gesehen-Status: ${config.user_name || "Benutzer gewählt"}`
      : "Für „Nächste Staffel“ und automatische Löschregeln erforderlich.";
  }
  function initialize() {
    if (pending) return pending;
    const current = owner;
    const request = client.get("/api/jellyfin/config", { signal: current.signal })
      .then(value => { if (current.active) { config = value; initialized = true; render(); } })
      .finally(() => { if (pending === request) pending = null; });
    pending = request; return request;
  }
  async function save() {
    if (!scope?.active) return;
    const current = scope;
    if (pending) await pending;
    if (!current.active) return;
    if (!initialized) throw new Error("Jellyfin-Konfiguration konnte nicht geladen werden.");
    const atRevision = revision;
    const select = byId("jellyfin-user-id");
    const value = await client.post("/api/jellyfin/config", {
      url: byId("jellyfin-url").value.trim(), api_key: byId("jellyfin-api-key").value.trim(),
      user_id: select.value, user_name: select.value ? (select.selectedOptions[0]?.dataset.name || select.selectedOptions[0]?.textContent || "") : "",
      cleanup_default: root.querySelector('input[name="jellyfin-cleanup-default"]:checked')?.value || "keep",
    }, { signal: current.signal });
    if (!current.active) return;
    config = value;
    if (atRevision === revision) dirty = false;
    render(); return value;
  }
  return {
    get: () => Object.freeze({ userConfigured: Boolean(config.url && config.has_api_key && config.user_id), cleanupDefault: cleanupDefault() }),
    initialize, save,
    mount() {
      if (scope) return;
      if (!owner.active) owner = createScope();
      scope = createScope(); picker.mount(); render();
      const changed = () => { dirty = true; revision++; };
      scope.listen(root, "input", changed); scope.listen(root, "change", changed);
      void initialize().catch(error => { if (scope?.active) byId("jellyfin-user-status").textContent = error.message; });
    },
    refresh: initialize,
    unmount() { scope?.dispose(); scope = null; picker.unmount(); },
    dispose() { owner.dispose(); scope?.dispose(); scope = null; picker.unmount(); pending = null; },
    resume() { if (!owner.active) owner = createScope(); },
  };
}
