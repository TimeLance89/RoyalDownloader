(() => {
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

  const activate = (target) => {
    const root = document.getElementById("tab-einstellungen");
    if (!root || !target) return;
    root.querySelectorAll("[data-settings-section]").forEach((section) => {
      const active = section === target;
      section.hidden = !active;
      section.classList.toggle("is-active", active);
      section.setAttribute("aria-hidden", String(!active));
    });
    root.querySelectorAll("[data-settings-target]").forEach((link) => {
      link.classList.toggle("is-active", link.dataset.settingsTarget === target.id);
    });
  };

  const moduleCard = (module) => {
    const resources = module.resources || {};
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
      <p class="dim">Status: ${escapeHtml(readable(module.runtime_status))} · Health: ${escapeHtml(module.health_detail)}</p>
      <p class="dim">Konfiguration: ${escapeHtml(configuration)} · Dienste: ${list(module.background_services || [])}</p>
      <p class="dim">CPU ${escapeHtml(resources.cpu)} · RAM ${escapeHtml(resources.ram)} · Netzwerk ${escapeHtml(resources.network)} · Speicher ${escapeHtml(resources.storage)}</p>
      ${dependencies ? `<p class="dim">${dependencies}</p>` : ""}
      ${module.error ? `<p class="dim">Fehler: ${escapeHtml(module.error)}</p>` : ""}
    </article>`;
  };

  const syncFeatureCapabilities = async () => {
    const button = document.getElementById("seerr-sync");
    const status = document.getElementById("seerr-status");
    if (!button || !status) return;
    try {
      const payload = await api.get("/api/modules");
      const seerr = payload.modules.find((module) => module.id === "seerr-sync");
      const available = !!(
        seerr
        && seerr.enabled
        && seerr.runtime_status === "running"
        && seerr.health === "healthy"
      );
      button.disabled = !available;
      button.dataset.moduleAvailable = String(available);
      if (!available && seerr) {
        status.textContent = seerr.enabled
          ? `Seerr-Modul nicht bereit · ${seerr.configuration_detail}`
          : "Seerr-Modul deaktiviert · Einstellungen → Module";
      }
    } catch (error) {
      console.warn("Modulstatus konnte nicht geladen werden:", error);
    }
  };

  const render = async () => {
    const host = document.getElementById("module-manager-list");
    if (!host) return;
    try {
      const data = await api.get("/api/modules");
      host.innerHTML = data.modules.map(moduleCard).join("");
      host.querySelectorAll("[data-module]").forEach((input) => {
        // Module are persisted immediately. Keep both event types out of the
        // normal settings form so it never displays a false dirty state.
        input.addEventListener("input", (event) => event.stopPropagation());
        input.addEventListener("change", async (event) => {
          event.stopPropagation();
          input.disabled = true;
          try {
            await api._req("PUT", `/api/modules/${input.dataset.module}`, {
              enabled: input.checked,
            });
            document.dispatchEvent(new Event("royal:modules-changed"));
            await render();
          } catch (error) {
            input.checked = !input.checked;
            input.disabled = false;
            alert(error.message);
          }
        });
      });
    } catch (error) {
      host.textContent = `Module konnten nicht geladen werden: ${error.message}`;
    }
  };

  const install = () => {
    if (document.getElementById("settings-modules")) return;
    document.querySelector('[data-settings-target="settings-system"]')?.insertAdjacentHTML(
      "beforebegin",
      '<a href="#settings-modules" data-settings-target="settings-modules"><span>◈</span><strong>Module</strong><small>Optionale Funktionen</small></a>',
    );
    document.getElementById("settings-system")?.insertAdjacentHTML(
      "beforebegin",
      '<section id="settings-modules" class="settings-section" data-settings-section aria-hidden="true" hidden><header class="settings-section-heading"><span class="settings-section-mark">◈</span><div><span>MODULE</span><h2>Module verwalten</h2><p>Module werden sofort gespeichert. Integrationsdaten und Verhalten bleiben in ihren jeweiligen Einstellungen.</p></div></header><div id="module-manager-list" class="settings-card-grid"></div></section>',
    );
    document.querySelector('[data-settings-target="settings-modules"]')?.addEventListener("click", (event) => {
      event.preventDefault();
      activate(document.getElementById("settings-modules"));
      render();
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
  document.addEventListener("royal:settings-ready", syncFeatureCapabilities);
  document.addEventListener("royal:modules-changed", syncFeatureCapabilities);
})();
