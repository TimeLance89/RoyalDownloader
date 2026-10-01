import { integrationHealth } from "../integrations/health.js";
import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";

export function createModuleSettings(root) {
  let scope;
  let rows;
  let generation = 0;
  const find = id => root.querySelector(`#${id}`);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
  const readable = (value) => ({
    running: "Läuft", disabled: "Deaktiviert", starting: "Startet",
    stopping: "Wird beendet", error: "Fehler", needs_configuration: "Konfiguration fehlt",
    dependency_missing: "Abhängigkeit fehlt",
  }[value] || value);
  const list = (values, fallback = "keine") => values.length
    ? values.map(escapeHtml).join(", ")
    : fallback;

  const moduleCard = (module) => {
    const resources = module.resources || {};
    const health = integrationHealth(module);
    const configuration = module.configured ? "Konfiguriert" : module.configuration_detail;
    const dependencies = [
      module.requires?.length ? `Benötigt: ${list(module.requires)}` : "",
      module.optional_requires?.length ? `Optional: ${list(module.optional_requires)}` : "",
      module.missing_optional?.length ? `Reduziert: ${list(module.missing_optional)}` : "",
      module.used_by?.length ? `Verwendet von: ${list(module.used_by)}` : "",
    ].filter(Boolean).join(" · ");
    return `<article class="settings-card">
      <div class="settings-section-heading">
        <div><span>${escapeHtml(module.category).toUpperCase()}</span><h3>${escapeHtml(module.name)}</h3><p>${escapeHtml(module.description)}</p></div>
        <label><input type="checkbox" data-module="${escapeHtml(module.id)}" ${module.enabled ? "checked" : ""}> ${module.enabled ? "Aktiv" : "Deaktiviert"}</label>
      </div>
      <p class="dim">Status: ${escapeHtml(readable(module.runtime_status))} · Health: ${escapeHtml(health.label)}${health.detail ? ` · ${escapeHtml(health.detail)}` : ""}</p>
      <p class="dim">Konfiguration: ${escapeHtml(configuration)} · Dienste: ${list(module.background_services || [])}</p>
      <p class="dim">CPU ${escapeHtml(resources.cpu)} · RAM ${escapeHtml(resources.ram)} · Netzwerk ${escapeHtml(resources.network)} · Speicher ${escapeHtml(resources.storage)}</p>
      ${dependencies ? `<p class="dim">${dependencies}</p>` : ""}
      ${module.error ? `<p class="dim">Fehler: ${escapeHtml(module.error)}</p>` : ""}
    </article>`;
  };

  const render = async () => {
    const host = find("module-manager-list");
    if (!host) return;
    const current = scope;
    if (!current?.active) return;
    const request = ++generation;
    rows?.dispose();
    host.textContent = "Module werden geladen …";
    try {
      const data = await api.get("/api/modules", { signal: current.signal });
      if (!current.active || request !== generation) return;
      rows = createScope();
      host.innerHTML = data.modules.map(moduleCard).join("");
      if (!data.modules.length) host.textContent = "Keine Module vorhanden.";
      host.querySelectorAll("[data-module]").forEach((input) => {
        // Module are persisted immediately. Keep both event types out of the
        // normal settings form so it never displays a false dirty state.
        rows.listen(input, "input", (event) => event.stopPropagation());
        rows.listen(input, "change", async (event) => {
          event.stopPropagation();
          input.disabled = true;
          try {
            await api.put(`/api/modules/${input.dataset.module}`, {
              enabled: input.checked,
            }, { signal: current.signal });
            if (!current.active) return;
            document.dispatchEvent(new Event("royal:modules-changed"));
            await render();
          } catch (error) {
            if (isAbortError(error) || !current.active) return;
            input.checked = !input.checked;
            input.disabled = false;
            alert(error.message);
          }
        });
      });
    } catch (error) {
      if (isAbortError(error) || !current.active || request !== generation) return;
      host.textContent = `Module konnten nicht geladen werden: ${error.message}`;
    }
  };

  const install = () => {
    if (find("settings-modules")) return;
    root.querySelector('[data-settings-target="settings-system"]')?.insertAdjacentHTML(
      "beforebegin",
      '<a href="#settings-modules" data-settings-target="settings-modules"><span>◈</span><strong>Module</strong><small>Optionale Funktionen</small></a>',
    );
    root.querySelector('[data-settings-open="settings-system"]')?.insertAdjacentHTML(
      "beforebegin",
      '<button class="settings-launch-card is-modules" type="button" data-settings-open="settings-modules"><span class="settings-launch-symbol" aria-hidden="true">◈</span><span class="settings-launch-copy"><small>ERWEITERUNGEN</small><strong>Module</strong><em>Optionale Funktionen und Dienste verwalten</em></span><i aria-hidden="true">→</i></button>',
    );
    find("settings-system")?.insertAdjacentHTML(
      "beforebegin",
      '<section id="settings-modules" class="settings-section" data-settings-section aria-hidden="true" hidden><header class="settings-section-heading"><span class="settings-section-mark">◈</span><div><span>MODULE</span><h2>Module verwalten</h2><p>Module werden sofort gespeichert. Integrationsdaten und Verhalten bleiben in ihren jeweiligen Einstellungen.</p></div></header><div id="module-manager-list" class="settings-card-grid"></div></section>',
    );
  };

  install();
  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      const link = root.querySelector('[data-settings-target="settings-modules"]');
      if (link) scope.listen(link, "click", event => {
        event.preventDefault();
        void render();
      });
      if (!find("settings-modules")?.hidden) void render();
    },
    refresh: render,
    unmount() { generation++; rows?.dispose(); rows = null; scope?.dispose(); scope = null; },
  };
}
