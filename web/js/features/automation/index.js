import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { installAutomationUi } from "./layout.js";
import { createAutomationView } from "./view.js";

const POLICY_URL = "/api/automation/policy";
const REFRESH_MS = 15_000;

export function createAutomation(root) {
  installAutomationUi(root);
  const view = createAutomationView(root);
  const byId = id => root.querySelector(`#${id}`);
  const section = byId("smart-automation-policy").closest("[data-settings-section]");
  let scope;
  let bootstrap;
  let pending;
  let pendingOwner;
  let pollScope;
  let edits = 0;
  let stopPolling;
  const draft = new Map();
  const settingsHaveUnsavedChanges = () => byId("settings-saved-status")?.textContent?.trim() === "Ungespeicherte Änderungen.";

  // The settings bootstrap loads this once even before its view is first visited.
  // That one-shot request has its own owner; session/page disposal cancels it too.
  function initialize(owner) {
    if (pending && pendingOwner?.active) return pending;
    const current = owner || scope || (bootstrap ||= createScope());
    const version = edits;
    section.dataset.viewState = "loading";
    const request = api.get(POLICY_URL, { signal: current.signal }).then(policy => {
      if (!current.active) return;
      if (!view.ready) {
        view.render(policy);
        for (const [input, value] of draft) { input.value = value.value; input.checked = value.checked; }
        view.sync();
      } else if (version === edits && !settingsHaveUnsavedChanges()) view.render(policy);
      section.dataset.viewState = "ready";
      return policy;
    }).catch(error => {
      if (!current.active || isAbortError(error)) return;
      section.dataset.viewState = "error";
      byId("auto-status").textContent = `Automatik-Regeln nicht abrufbar: ${error.message}`;
      throw error;
    }).finally(() => {
      if (pending === request) { pending = null; pendingOwner = null; }
      if (bootstrap === current) { bootstrap.dispose(); bootstrap = null; }
    });
    pendingOwner = current;
    pending = request;
    return request;
  }
  function refresh() {
    if (!scope?.active || document.hidden || section.hidden || settingsHaveUnsavedChanges()) return Promise.resolve();
    // A background refresh reports its error in the existing status element.
    return initialize(pollScope).catch(() => {});
  }
  function syncPolling() {
    if (!scope?.active || section.hidden || document.hidden) {
      stopPolling?.(); stopPolling = null;
      pollScope?.dispose(); pollScope = null;
      return;
    }
    if (!pollScope?.active) pollScope = createScope();
    if (!stopPolling) stopPolling = scope.interval(() => void refresh(), REFRESH_MS);
    void refresh();
  }
  return {
    initialize,
    refresh,
    async save() {
      const current = scope;
      if (!current?.active) throw new DOMException("Abgebrochen", "AbortError");
      if (!view.ready) await initialize();
      if (!current.active) throw new DOMException("Abgebrochen", "AbortError");
      if (!view.ready) throw new Error("Automatik-Regeln müssen vor dem Speichern geladen werden.");
      const body = view.build({
        auto_download: byId("auto-download").checked,
        check_interval_min: Math.max(5, parseInt(byId("check-interval").value, 10) || 30),
      });
      const version = edits;
      const policy = await api.post(POLICY_URL, body, { signal: current.signal });
      if (!current.active) throw new DOMException("Abgebrochen", "AbortError");
      if (edits === version) { draft.clear(); view.render(policy); }
      return policy;
    },
    mount() {
      if (scope?.active) return;
      scope = createScope();
      view.bind(scope);
      const remember = event => {
        const input = event.target;
        if (!input.matches("input, select, textarea")) return;
        edits++;
        draft.delete(input);
        draft.set(input, { value: input.value, checked: input.checked });
      };
      scope.listen(section, "input", remember);
      scope.listen(section, "change", remember);
      scope.listen(document, "visibilitychange", syncPolling);
      const observer = new MutationObserver(syncPolling);
      observer.observe(section, { attributes: true, attributeFilter: ["hidden"] });
      scope.observe(observer);
      // Runtime policy/streaming state has no WebSocket topic in the existing API.
      syncPolling();
    },
    unmount() { stopPolling?.(); stopPolling = null; pollScope?.dispose(); pollScope = null; scope?.dispose(); bootstrap?.dispose(); scope = null; bootstrap = null; pending = null; pendingOwner = null; },
  };
}
