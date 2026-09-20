(() => {
  const activate = (target) => {
    const root = document.getElementById("tab-einstellungen"); if (!root || !target) return;
    root.querySelectorAll("[data-settings-section]").forEach((section) => { const active = section === target; section.hidden = !active; section.classList.toggle("is-active", active); section.setAttribute("aria-hidden", String(!active)); });
    root.querySelectorAll("[data-settings-target]").forEach((link) => link.classList.toggle("is-active", link.dataset.settingsTarget === target.id));
  };
  const render = async () => {
    const host = document.getElementById("module-manager-list"); if (!host) return;
    try {
      const data = await api.get("/api/modules");
      host.innerHTML = data.modules.map((module) => `<article class="settings-card"><div class="settings-section-heading"><div><span>${module.category.toUpperCase()}</span><h3>${module.name}</h3><p>${module.description}</p></div><label><input type="checkbox" data-module="${module.id}" ${module.enabled ? "checked" : ""}> ${module.enabled ? "Aktiv" : "Deaktiviert"}</label></div><p class="dim">CPU ${module.resources.cpu} · RAM ${module.resources.ram} · Netzwerk ${module.resources.network} · Speicher ${module.resources.storage}</p><p class="dim">Dienste: ${module.background_services.join(", ") || "keine"} · Status: ${module.status}</p></article>`).join("");
      host.querySelectorAll("[data-module]").forEach((input) => input.addEventListener("change", async () => { try { await api._req("PUT", `/api/modules/${input.dataset.module}`, { enabled: input.checked }); await render(); } catch (error) { input.checked = !input.checked; alert(error.message); } }));
    } catch (error) { host.textContent = `Module konnten nicht geladen werden: ${error.message}`; }
  };
  const install = () => {
    if (document.getElementById("settings-modules")) return;
    document.querySelector('[data-settings-target="settings-system"]')?.insertAdjacentHTML("beforebegin", '<a href="#settings-modules" data-settings-target="settings-modules"><span>◈</span><strong>Module</strong><small>Optionale Funktionen</small></a>');
    document.getElementById("settings-system")?.insertAdjacentHTML("beforebegin", '<section id="settings-modules" class="settings-section" data-settings-section aria-hidden="true" hidden><header class="settings-section-heading"><span class="settings-section-mark">◈</span><div><span>MODULE</span><h2>Module verwalten</h2><p>Optionale Funktionen können Ressourcen und Hintergrunddienste nutzen.</p></div></header><div id="module-manager-list" class="settings-card-grid"></div></section>');
    document.querySelector('[data-settings-target="settings-modules"]')?.addEventListener("click", (event) => { event.preventDefault(); activate(document.getElementById("settings-modules")); render(); });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, { once: true }); else install();
})();
