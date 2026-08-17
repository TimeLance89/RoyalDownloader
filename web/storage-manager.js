(() => {
  if (window.__royalStorageManagerInstalled) return;
  window.__royalStorageManagerInstalled = true;

  const POLL_MS = 5000;
  let liveTimer = null;
  let scanRunning = false;
  let editingLocationId = "";
  let currentLocations = [];
  let activeMove = null;

  const html = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);

  function formatBytes(value) {
    const bytes = Math.max(0, Number(value) || 0);
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB", "PB"];
    const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    const amount = bytes / (1024 ** index);
    return `${amount.toLocaleString("de-DE", { maximumFractionDigits: index >= 3 ? 2 : 1 })} ${units[index]}`;
  }

  function formatPercent(value) {
    return `${Math.max(0, Math.min(100, Number(value) || 0)).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;
  }

  function storageActive() {
    return document.getElementById("tab-einstellungen")?.classList.contains("active")
      && document.getElementById("settings-storage")?.classList.contains("is-active");
  }

  function activateStorage() {
    const target = document.getElementById("settings-storage");
    if (!target) return;
    document.querySelectorAll("[data-settings-section]").forEach((section) => {
      section.classList.toggle("is-active", section === target);
    });
    document.querySelectorAll(".settings-directory-nav [data-settings-target]").forEach((link) => {
      const active = link.dataset.settingsTarget === "settings-storage";
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    void refreshStatus(false);
  }

  function ensureStyle() {
    if (!document.querySelector('link[data-royal-storage-style]')) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/styles/storage-manager.css?v=royal-20260817-2";
      link.dataset.royalStorageStyle = "true";
      document.head.appendChild(link);
    }
    if (document.querySelector("style[data-royal-storage-move-style]")) return;
    const style = document.createElement("style");
    style.dataset.royalStorageMoveStyle = "true";
    style.textContent = `
      .storage-candidate-actions{display:flex;gap:7px;align-items:center;justify-content:flex-end}
      .storage-move-button{border:1px solid color-mix(in srgb,var(--storage-accent) 35%,transparent);background:color-mix(in srgb,var(--storage-accent) 8%,transparent);color:var(--storage-accent);border-radius:10px;padding:8px 11px;font:inherit;font-size:.78rem;font-weight:700;cursor:pointer}
      .storage-move-button:hover{background:color-mix(in srgb,var(--storage-accent) 15%,transparent)}
      .storage-move-button:disabled{opacity:.5;cursor:wait}
      .storage-move-modal{position:fixed;inset:0;z-index:1200;display:grid;place-items:center;padding:20px;background:rgba(5,7,10,.72);backdrop-filter:blur(8px)}
      .storage-move-modal[hidden]{display:none}
      .storage-move-dialog{width:min(620px,100%);max-height:min(760px,90vh);overflow:auto;border:1px solid color-mix(in srgb,currentColor 15%,transparent);background:var(--panel,#17191f);border-radius:20px;box-shadow:0 28px 80px rgba(0,0,0,.45);padding:22px}
      .storage-move-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.storage-move-head span{font-size:.66rem;letter-spacing:.14em;font-weight:800;color:var(--storage-accent)}.storage-move-head h3{margin:5px 0 0;font-size:1.28rem}.storage-move-close{border:0;background:transparent;color:inherit;font-size:1.4rem;cursor:pointer}
      .storage-move-summary{display:grid;grid-template-columns:1fr auto;gap:14px;margin:18px 0;padding:14px;border-radius:14px;background:color-mix(in srgb,currentColor 4%,transparent)}.storage-move-summary div{display:grid;gap:3px}.storage-move-summary small{color:var(--muted,#9ca4af)}.storage-move-summary strong:last-child{align-self:center}
      .storage-move-field{display:grid;gap:7px}.storage-move-field>span{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted,#9ca4af)}.storage-move-field select{width:100%;padding:11px 12px;border-radius:11px;border:1px solid color-mix(in srgb,currentColor 15%,transparent);background:color-mix(in srgb,var(--panel,#17191f) 96%,white 4%);color:inherit}
      .storage-move-target-note{margin:8px 0 0;color:var(--muted,#9ca4af);font-size:.76rem;line-height:1.45}.storage-move-blocked{display:grid;gap:5px;margin:12px 0 0}.storage-move-blocked span{font-size:.73rem;color:var(--muted,#9ca4af)}
      .storage-move-info{margin:16px 0 0;padding:12px 13px;border-radius:12px;background:color-mix(in srgb,var(--storage-accent) 7%,transparent);font-size:.77rem;line-height:1.5;color:var(--muted,#aeb5bf)}.storage-move-info strong{color:inherit}
      .storage-move-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.storage-move-actions button:disabled{opacity:.5;cursor:wait}
      @media(max-width:900px){.storage-candidate-actions{grid-column:2/-1}.storage-cleanup-button{grid-column:auto}.storage-move-summary{grid-template-columns:1fr}.storage-move-actions{display:grid;grid-template-columns:1fr 1fr}}
      @media(max-width:620px){.storage-candidate-actions{grid-column:2;justify-content:stretch}.storage-candidate-actions button{flex:1}.storage-move-modal{padding:10px}.storage-move-dialog{padding:17px}.storage-move-actions{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function injectUi() {
    if (document.getElementById("settings-storage")) return;
    const nav = document.querySelector(".settings-directory-nav");
    const generalLink = nav?.querySelector('[data-settings-target="settings-general"]');
    generalLink?.insertAdjacentHTML("afterend", `
      <a href="#settings-storage" data-settings-target="settings-storage">
        <span aria-hidden="true">▰</span><strong>Speicher</strong><small>Live-Belegung &amp; Bereinigung</small>
      </a>`);

    const launchGrid = document.querySelector(".settings-launch-grid");
    const generalLaunch = launchGrid?.querySelector('[data-settings-open="settings-general"]');
    generalLaunch?.insertAdjacentHTML("afterend", `
      <button class="settings-launch-card is-storage" type="button" data-settings-open="settings-storage">
        <span class="settings-launch-symbol" aria-hidden="true">▰</span>
        <span class="settings-launch-copy"><small>SPEICHER</small><strong>Live-Belegung &amp; Bereinigung</strong><em>Mehrere Volumes, Kapazität und sichere Freigabe</em></span>
        <i aria-hidden="true">→</i>
      </button>`);

    const general = document.getElementById("settings-general");
    general?.insertAdjacentHTML("afterend", `
      <section id="settings-storage" class="settings-section royal-storage-section" data-settings-section aria-labelledby="settings-storage-title">
        <header class="settings-section-heading">
          <span class="settings-section-mark is-storage" aria-hidden="true">▰</span>
          <div><span>SPEICHER</span><h2 id="settings-storage-title">Speicher überwachen &amp; bereinigen</h2>
          <p>Alle eingebundenen Datenträger live sehen, zusätzliche Speicherorte verwalten und große Medien sicher finden.</p></div>
        </header>
        <div class="storage-live-toolbar">
          <div class="storage-live-indicator"><i></i><span>LIVE</span><strong id="storage-live-state">wird geladen …</strong></div>
          <div class="storage-toolbar-actions">
            <button id="storage-refresh" class="btn btn-ghost btn-sm" type="button">↻ Aktualisieren</button>
            <button id="storage-scan" class="btn btn-primary btn-sm" type="button">Große Inhalte analysieren</button>
          </div>
        </div>
        <div id="storage-summary" class="storage-summary-card" aria-live="polite">
          <div class="storage-summary-ring" style="--storage-used:0%"><span><strong>0 %</strong><small>belegt</small></span></div>
          <div class="storage-summary-copy"><span>GESAMTÜBERSICHT</span><h3>Speicher wird abgefragt …</h3><p>Physische Dateisysteme werden erkannt und niemals doppelt gezählt.</p></div>
          <div class="storage-summary-numbers"><span><small>Belegt</small><strong>—</strong></span><span><small>Frei</small><strong>—</strong></span><span><small>Kapazität</small><strong>—</strong></span></div>
        </div>

        <section class="storage-locations-card" aria-labelledby="storage-locations-title">
          <header class="storage-locations-head">
            <div><span>SPEICHERORTE</span><h3 id="storage-locations-title">Zusätzliche Datenträger</h3><p>Externe HDDs oder weitere NAS-Mounts hinzufügen. „Nur überwachen“ misst ausschließlich Kapazität; „Medien“ erlaubt zusätzlich Smart Scan, Verschieben und die sichere Bereinigung.</p></div>
            <strong id="storage-location-count">0 zusätzlich</strong>
          </header>
          <form id="storage-location-form" class="storage-location-form">
            <label><span>Name</span><input id="storage-location-label" maxlength="80" autocomplete="off" placeholder="z. B. Externe Festplatte" required></label>
            <label class="is-path"><span>Pfad im Royal-Container</span><input id="storage-location-path" maxlength="2048" autocomplete="off" placeholder="z. B. /external-media" required></label>
            <label><span>Typ</span><select id="storage-location-mode"><option value="monitor">Nur überwachen</option><option value="media">Medien</option></select></label>
            <div class="storage-location-form-actions"><button id="storage-location-save" class="btn btn-primary btn-sm" type="submit">Speicher hinzufügen</button><button id="storage-location-cancel" class="btn btn-ghost btn-sm" type="button" hidden>Abbrechen</button></div>
          </form>
          <div id="storage-location-list" class="storage-location-list"><div class="storage-empty-state"><strong>Noch kein zusätzlicher Speicherort</strong><span>Der Film- und Serien-Speicher wird trotzdem automatisch live gemessen.</span></div></div>
          <p class="storage-mount-hint"><span>i</span><span>Bei Docker/NAS muss die Festplatte als Bind-Mount im Royal-Container sichtbar sein. Royal mountet keine Host-Laufwerke selbst und zeigt einen nicht erreichbaren Pfad klar als offline an.</span></p>
        </section>

        <div id="storage-volume-grid" class="storage-volume-grid" aria-live="polite"></div>
        <section class="storage-insights-card" aria-labelledby="storage-insights-title">
          <header class="storage-insights-head"><div><span>SMART SCAN</span><h3 id="storage-insights-title">Große Inhalte &amp; Speicherfresser</h3>
          <p>Treffer können gelöscht oder auf ein anderes physisches Medien-Volume verschoben werden. Bei Serien verschiebt Royal immer den vollständigen Serienordner.</p></div><strong id="storage-scan-summary">Noch nicht analysiert</strong></header>
          <div id="storage-large-content-list" class="storage-content-list"><div class="storage-empty-state"><strong>Analyse auf Abruf</strong><span>Der rekursive Scan läuft bewusst nur bei Bedarf und belastet das NAS nicht dauerhaft.</span></div></div>
        </section>
        <div id="storage-cleanup-status" class="storage-cleanup-status" role="status" aria-live="polite"></div>
        <p class="storage-danger-note"><span>!</span><span>Löschen ist dauerhaft. Beim Verschieben wird das Ziel vollständig hergestellt und die Quelle erst danach entfernt; vorhandene Zieldaten werden niemals überschrieben.</span></p>

        <div id="storage-move-modal" class="storage-move-modal" role="dialog" aria-modal="true" aria-labelledby="storage-move-title" hidden>
          <section class="storage-move-dialog">
            <header class="storage-move-head"><div><span>VERSCHIEBEN</span><h3 id="storage-move-title">Medien verschieben</h3></div><button id="storage-move-close" class="storage-move-close" type="button" aria-label="Schließen">×</button></header>
            <div class="storage-move-summary"><div><small id="storage-move-kind">Inhalt</small><strong id="storage-move-name">—</strong></div><strong id="storage-move-size">—</strong></div>
            <label class="storage-move-field"><span>Ziel-Speichermedium</span><select id="storage-move-target"></select></label>
            <p id="storage-move-target-note" class="storage-move-target-note"></p>
            <div id="storage-move-blocked" class="storage-move-blocked"></div>
            <p class="storage-move-info"><strong>Wichtig:</strong> Zwischen zwei physischen Laufwerken müssen die Daten technisch übertragen werden. Royal führt dies als Verschieben aus: Quelle bleibt bis zum erfolgreichen Transfer geschützt und wird anschließend entfernt. Eine zweite Nutzkopie bleibt nicht bestehen.</p>
            <div class="storage-move-actions"><button id="storage-move-cancel" class="btn btn-ghost btn-sm" type="button">Abbrechen</button><button id="storage-move-confirm" class="btn btn-primary btn-sm" type="button">Jetzt verschieben</button></div>
          </section>
        </div>
      </section>`);

    document.querySelector('[data-settings-target="settings-storage"]')?.addEventListener("click", (event) => {
      event.preventDefault(); activateStorage();
    });
    document.querySelector('[data-settings-open="settings-storage"]')?.addEventListener("click", activateStorage);
    document.getElementById("storage-refresh")?.addEventListener("click", () => refreshStatus(false));
    document.getElementById("storage-scan")?.addEventListener("click", scanStorage);
    document.getElementById("storage-location-form")?.addEventListener("submit", saveLocation);
    document.getElementById("storage-location-cancel")?.addEventListener("click", resetLocationForm);
    document.getElementById("storage-location-list")?.addEventListener("click", handleLocationAction);
    document.getElementById("storage-large-content-list")?.addEventListener("click", (event) => {
      const move = event.target.closest("[data-storage-move]");
      if (move) { void openMove(move); return; }
      const cleanupButton = event.target.closest("[data-storage-cleanup]");
      if (cleanupButton) void cleanup(cleanupButton);
    });
    document.getElementById("storage-move-close")?.addEventListener("click", closeMove);
    document.getElementById("storage-move-cancel")?.addEventListener("click", closeMove);
    document.getElementById("storage-move-confirm")?.addEventListener("click", executeMove);
    document.getElementById("storage-move-target")?.addEventListener("change", renderMoveTargetNote);
    document.getElementById("storage-move-modal")?.addEventListener("click", (event) => {
      if (event.target.id === "storage-move-modal") closeMove();
    });
  }

  function locationStatus(location, roots) {
    return roots.find((root) => root.location_id === location.id) || null;
  }

  function renderLocations(locations, roots) {
    currentLocations = Array.isArray(locations) ? locations : [];
    const list = document.getElementById("storage-location-list");
    const count = document.getElementById("storage-location-count");
    if (!list || !count) return;
    count.textContent = `${currentLocations.length} zusätzlich`;
    if (!currentLocations.length) {
      list.innerHTML = '<div class="storage-empty-state"><strong>Noch kein zusätzlicher Speicherort</strong><span>Der Film- und Serien-Speicher wird trotzdem automatisch live gemessen.</span></div>';
      return;
    }
    list.innerHTML = currentLocations.map((location) => {
      const status = locationStatus(location, roots);
      const available = Boolean(status?.available);
      const state = available ? `${formatPercent(status.used_percent)} belegt · ${formatBytes(status.free_bytes)} frei` : "nicht erreichbar";
      return `
        <article class="storage-location-row${available ? "" : " is-offline"}" data-location-id="${html(location.id)}">
          <div class="storage-location-icon" aria-hidden="true">▰</div>
          <div class="storage-location-copy"><span>${location.mode === "media" ? "MEDIEN" : "NUR ÜBERWACHEN"}</span><strong>${html(location.label)}</strong><code title="${html(location.path)}">${html(location.path)}</code><small>${html(state)}</small></div>
          <div class="storage-location-actions"><button type="button" class="btn btn-ghost btn-sm" data-location-edit="${html(location.id)}">Bearbeiten</button><button type="button" class="storage-location-remove" data-location-remove="${html(location.id)}">Entfernen</button></div>
        </article>`;
    }).join("");
  }

  function volumeCard(volume) {
    const members = Array.isArray(volume.members) ? volume.members : [];
    const tags = members.map((member) => `<span>${html(member.label)}${member.mode === "monitor" ? " · Monitor" : ""}</span>`).join("");
    const paths = (volume.paths || []).map((path) => html(path)).join(" · ");
    const modeText = volume.mode === "media" ? "Smart Scan und Medienaktionen aktiv" : "Nur Live-Monitoring · keine Medienaktionen";
    return `
      <article class="storage-volume-card">
        <header><div><small>PHYSISCHES VOLUME</small><span>${html(volume.label || "Speicher")}</span></div><strong>${formatPercent(volume.used_percent)}</strong></header>
        <code title="${paths}">${paths || "Eingebundenes Dateisystem"}</code>
        <div class="storage-volume-members">${tags}</div>
        <div class="storage-meter" style="--storage-used:${Number(volume.used_percent) || 0}%"><i></i></div>
        <div class="storage-volume-numbers"><span><small>Belegt</small><b>${formatBytes(volume.used_bytes)}</b></span><span><small>Frei</small><b>${formatBytes(volume.free_bytes)}</b></span><span><small>Gesamt</small><b>${formatBytes(volume.total_bytes)}</b></span></div>
        <p>${volume.measurement === "nas_mount" ? "NAS-Mount live" : "Lokales Dateisystem live"} · ${modeText}</p>
      </article>`;
  }

  function unavailableRootCard(root) {
    return `
      <article class="storage-volume-card is-error"><header><div><small>${root.source === "custom" ? "SPEICHERORT" : "MEDIENPFAD"}</small><span>${html(root.label || root.key)}</span></div><strong>offline</strong></header><code>${html(root.path || "Nicht konfiguriert")}</code><p>${html(root.error || "Pfad konnte nicht gelesen werden. Prüfe den NAS-/Docker-Mount.")}</p></article>`;
  }

  function renderStatus(payload) {
    const live = document.getElementById("storage-live-state");
    const summary = document.getElementById("storage-summary");
    const grid = document.getElementById("storage-volume-grid");
    if (!live || !summary || !grid) return;
    const roots = payload.roots || [];
    renderLocations(payload.locations || [], roots);
    if (payload.enabled === false || payload.deployment_mode === "demo") {
      live.textContent = "Demo-Modus · kein realer Speicher";
      summary.classList.add("is-unavailable");
      summary.querySelector(".storage-summary-copy h3").textContent = "Im Demo-Modus deaktiviert";
      summary.querySelector(".storage-summary-copy p").textContent = "Wechsle zu Computer oder NAS, um reale Speicherwerte abzurufen.";
      grid.innerHTML = "";
      return;
    }
    const total = payload.summary || {};
    const percent = Number(total.used_percent) || 0;
    summary.classList.remove("is-unavailable");
    summary.querySelector(".storage-summary-ring").style.setProperty("--storage-used", `${percent}%`);
    summary.querySelector(".storage-summary-ring strong").textContent = formatPercent(percent);
    summary.querySelector(".storage-summary-copy h3").textContent = `${formatBytes(total.free_bytes)} frei über ${Number(total.volume_count) || 0} Volume${Number(total.volume_count) === 1 ? "" : "s"}`;
    summary.querySelector(".storage-summary-copy p").textContent = payload.deployment_mode === "nas"
      ? "Direkt von den eingebundenen NAS-Dateisystemen gemessen · identische Volumes werden nur einmal gezählt."
      : "Direkt auf den konfigurierten Dateisystemen gemessen · identische Volumes werden nur einmal gezählt.";
    const values = summary.querySelectorAll(".storage-summary-numbers strong");
    if (values[0]) values[0].textContent = formatBytes(total.used_bytes);
    if (values[1]) values[1].textContent = formatBytes(total.free_bytes);
    if (values[2]) values[2].textContent = formatBytes(total.total_bytes);
    live.textContent = `${payload.volumes?.length || 0} physische${payload.volumes?.length === 1 ? "s" : ""} Volume${payload.volumes?.length === 1 ? "" : "s"} · ${new Date((payload.observed_at || Date.now() / 1000) * 1000).toLocaleTimeString("de-DE")}`;

    const unavailable = roots.filter((root) => root.configured !== false && !root.available);
    grid.innerHTML = [
      ...(payload.volumes || []).map(volumeCard),
      ...unavailable.map(unavailableRootCard),
    ].join("");
  }

  async function refreshStatus(silent = true) {
    const live = document.getElementById("storage-live-state");
    if (!silent && live) live.textContent = "wird aktualisiert …";
    try { renderStatus(await api.get("/api/storage/status")); }
    catch (error) { if (live) live.textContent = `Live-Abfrage fehlgeschlagen · ${error.message}`; }
  }

  function resetLocationForm() {
    editingLocationId = "";
    const form = document.getElementById("storage-location-form");
    form?.reset();
    const save = document.getElementById("storage-location-save");
    const cancel = document.getElementById("storage-location-cancel");
    if (save) save.textContent = "Speicher hinzufügen";
    if (cancel) cancel.hidden = true;
  }

  function editLocation(locationId) {
    const location = currentLocations.find((item) => item.id === locationId);
    if (!location) return;
    editingLocationId = location.id;
    document.getElementById("storage-location-label").value = location.label;
    document.getElementById("storage-location-path").value = location.path;
    document.getElementById("storage-location-mode").value = location.mode;
    const save = document.getElementById("storage-location-save");
    const cancel = document.getElementById("storage-location-cancel");
    if (save) save.textContent = "Änderungen speichern";
    if (cancel) cancel.hidden = false;
    document.getElementById("storage-location-label")?.focus();
  }

  async function saveLocation(event) {
    event.preventDefault();
    const label = document.getElementById("storage-location-label")?.value.trim() || "";
    const path = document.getElementById("storage-location-path")?.value.trim() || "";
    const mode = document.getElementById("storage-location-mode")?.value || "monitor";
    const save = document.getElementById("storage-location-save");
    const status = document.getElementById("storage-cleanup-status");
    if (!label || !path) return;
    if (save) { save.disabled = true; save.textContent = "Speichere …"; }
    try {
      await api.post("/api/storage/locations/save", {
        location_id: editingLocationId,
        label,
        path,
        mode,
      });
      if (status) status.textContent = `${label} gespeichert. Die Live-Werte werden neu eingelesen.`;
      resetLocationForm();
      await refreshStatus(false);
    } catch (error) {
      if (status) status.textContent = `Speicherort konnte nicht gespeichert werden · ${error.message}`;
    } finally {
      if (save) { save.disabled = false; save.textContent = editingLocationId ? "Änderungen speichern" : "Speicher hinzufügen"; }
    }
  }

  async function removeLocation(locationId) {
    const location = currentLocations.find((item) => item.id === locationId);
    if (!location) return;
    if (!window.confirm(`Speicherort „${location.label}“ aus Royal entfernen?\n\nEs werden keine Dateien gelöscht. Nur die Überwachung dieses Pfads wird entfernt.`)) return;
    const status = document.getElementById("storage-cleanup-status");
    try {
      await api.post("/api/storage/locations/remove", { location_id: location.id });
      if (editingLocationId === location.id) resetLocationForm();
      if (status) status.textContent = `${location.label} aus der Speicherüberwachung entfernt. Dateien wurden nicht verändert.`;
      await refreshStatus(false);
    } catch (error) {
      if (status) status.textContent = `Speicherort konnte nicht entfernt werden · ${error.message}`;
    }
  }

  function handleLocationAction(event) {
    const edit = event.target.closest("[data-location-edit]");
    if (edit) { editLocation(edit.dataset.locationEdit); return; }
    const remove = event.target.closest("[data-location-remove]");
    if (remove) void removeLocation(remove.dataset.locationRemove);
  }

  function candidateData(button) {
    return {
      root: button.dataset.root,
      relative_path: button.dataset.relativePath,
      token: button.dataset.token,
      expected_size: Number(button.dataset.size) || 0,
      expires_at: Number(button.dataset.expiresAt) || 0,
    };
  }

  function renderScan(payload) {
    const list = document.getElementById("storage-large-content-list");
    const summary = document.getElementById("storage-scan-summary");
    if (!list || !summary) return;
    const candidates = payload.candidates || [];
    summary.textContent = `${Number(payload.scanned_files) || 0} Dateien geprüft · ${candidates.length} Treffer${payload.truncated ? " · Scanlimit erreicht" : ""}`;
    if (!candidates.length) {
      list.innerHTML = '<div class="storage-empty-state"><strong>Keine auffälligen großen Inhalte gefunden</strong><span>Aktuell sticht kein sicherer Bereinigungs- oder Verschiebe-Treffer hervor.</span></div>';
      return;
    }
    list.innerHTML = candidates.map((candidate, index) => {
      const attrs = `data-root="${html(candidate.root)}" data-relative-path="${html(candidate.relative_path)}" data-token="${html(candidate.token)}" data-size="${Number(candidate.size_bytes) || 0}" data-expires-at="${Number(candidate.expires_at) || 0}" data-name="${html(candidate.name || candidate.relative_path)}"`;
      return `
      <article class="storage-content-candidate"><div class="storage-candidate-rank">${String(index + 1).padStart(2, "0")}</div>
      <div class="storage-candidate-copy"><span>${html(candidate.root_label)} · ${candidate.kind === "directory" ? "Ordner" : "Datei"}</span><strong title="${html(candidate.relative_path)}">${html(candidate.name || candidate.relative_path)}</strong><small>${html(candidate.reason)} · ${Number(candidate.file_count) || 0} Dateien</small></div>
      <div class="storage-candidate-size"><strong>${formatBytes(candidate.size_bytes)}</strong><small>${Number(candidate.media_file_count) || 0} Medien</small></div>
      <div class="storage-candidate-actions"><button class="storage-move-button" type="button" data-storage-move ${attrs}>Verschieben</button><button class="storage-cleanup-button" type="button" data-storage-cleanup ${attrs}>Löschen</button></div></article>`;
    }).join("");
  }

  async function scanStorage() {
    if (scanRunning) return;
    const button = document.getElementById("storage-scan");
    const summary = document.getElementById("storage-scan-summary");
    scanRunning = true;
    if (button) { button.disabled = true; button.textContent = "Analysiere …"; }
    if (summary) summary.textContent = "Freigegebene Medienordner werden analysiert …";
    try { renderScan(await api.post("/api/storage/scan", { max_candidates: 40 })); }
    catch (error) { if (summary) summary.textContent = `Analyse fehlgeschlagen · ${error.message}`; }
    finally { scanRunning = false; if (button) { button.disabled = false; button.textContent = "Große Inhalte analysieren"; } }
  }

  function closeMove() {
    activeMove = null;
    const modal = document.getElementById("storage-move-modal");
    if (modal) modal.hidden = true;
  }

  function renderMoveTargetNote() {
    const select = document.getElementById("storage-move-target");
    const note = document.getElementById("storage-move-target-note");
    if (!select || !note || !activeMove) return;
    const target = activeMove.plan.targets.find((item) => item.root === select.value);
    note.textContent = target
      ? `${target.path} · ${formatBytes(target.free_bytes)} frei · benötigt ca. ${formatBytes(target.required_bytes)}`
      : "Kein verfügbares Ziel ausgewählt.";
  }

  async function openMove(button) {
    const status = document.getElementById("storage-cleanup-status");
    const payload = candidateData(button);
    button.disabled = true;
    if (status) status.textContent = "Verschiebeziel und vollständiger Inhalt werden sicher geprüft …";
    try {
      const plan = await api.post("/api/storage/move/plan", payload);
      activeMove = { payload, plan };
      const modal = document.getElementById("storage-move-modal");
      const select = document.getElementById("storage-move-target");
      const blocked = document.getElementById("storage-move-blocked");
      const confirm = document.getElementById("storage-move-confirm");
      document.getElementById("storage-move-name").textContent = plan.source_name || "Inhalt";
      document.getElementById("storage-move-size").textContent = formatBytes(plan.size_bytes);
      document.getElementById("storage-move-kind").textContent = plan.source_kind === "series" ? "GESAMTER SERIENORDNER" : "FILMDATEI";
      const eligible = (plan.targets || []).filter((item) => item.eligible);
      select.innerHTML = eligible.length
        ? eligible.map((item) => `<option value="${html(item.root)}">${html(item.label)} · ${formatBytes(item.free_bytes)} frei</option>`).join("")
        : '<option value="">Kein anderes Medien-Volume verfügbar</option>';
      select.disabled = !eligible.length;
      confirm.disabled = !eligible.length;
      blocked.innerHTML = (plan.targets || []).filter((item) => !item.eligible).map((item) => `<span>${html(item.label)}: ${html(item.reason || "nicht verfügbar")}</span>`).join("");
      renderMoveTargetNote();
      if (modal) modal.hidden = false;
      if (status) status.textContent = eligible.length ? `${plan.source_name} kann sicher verschoben werden.` : "Kein geeignetes anderes Medien-Volume gefunden.";
    } catch (error) {
      if (status) status.textContent = `Verschieben nicht möglich · ${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  async function executeMove() {
    if (!activeMove) return;
    const select = document.getElementById("storage-move-target");
    const destinationRoot = select?.value || "";
    const target = activeMove.plan.targets.find((item) => item.root === destinationRoot && item.eligible);
    if (!target) return;
    const name = activeMove.plan.source_name || "Inhalt";
    const kind = activeMove.plan.source_kind === "series" ? "der gesamte Serienordner" : "die Filmdatei";
    if (!window.confirm(`„${name}“ nach „${target.label}“ verschieben?\n\nEs wird ${kind} verschoben. Nach erfolgreichem Transfer wird die Quelle entfernt. Vorhandene Zieldaten werden niemals überschrieben.`)) return;
    const confirm = document.getElementById("storage-move-confirm");
    const cancel = document.getElementById("storage-move-cancel");
    const close = document.getElementById("storage-move-close");
    const status = document.getElementById("storage-cleanup-status");
    if (confirm) { confirm.disabled = true; confirm.textContent = "Verschiebe …"; }
    if (cancel) cancel.disabled = true;
    if (close) close.disabled = true;
    if (status) status.textContent = `${name} wird nach ${target.label} verschoben …`;
    try {
      const result = await api.post("/api/storage/move", {
        ...activeMove.payload,
        destination_root: destinationRoot,
        confirm: true,
      });
      closeMove();
      if (status) status.textContent = `${result.name || name} verschoben · ${formatBytes(result.moved_bytes)} nach ${target.label}. Quelle wurde entfernt.`;
      await refreshStatus(false);
      await scanStorage();
    } catch (error) {
      if (status) status.textContent = `Verschieben abgebrochen · ${error.message}`;
    } finally {
      if (confirm) { confirm.disabled = false; confirm.textContent = "Jetzt verschieben"; }
      if (cancel) cancel.disabled = false;
      if (close) close.disabled = false;
    }
  }

  async function cleanup(button) {
    const name = button.dataset.name || button.dataset.relativePath || "Inhalt";
    const size = Number(button.dataset.size) || 0;
    const status = document.getElementById("storage-cleanup-status");
    if (!window.confirm(`„${name}“ (${formatBytes(size)}) dauerhaft löschen?\n\nDiese Bereinigung kann nicht rückgängig gemacht werden. Royal prüft den Treffer vor dem Löschen erneut.`)) return;
    button.disabled = true;
    if (status) status.textContent = `${name} wird erneut geprüft …`;
    try {
      const result = await api.post("/api/storage/cleanup", {
        root: button.dataset.root,
        relative_path: button.dataset.relativePath,
        token: button.dataset.token,
        expected_size: size,
        expires_at: Number(button.dataset.expiresAt) || 0,
        confirm: true,
      });
      if (status) status.textContent = `${name} entfernt · ca. ${formatBytes(result.freed_bytes)} freigegeben.`;
      await refreshStatus(false);
      await scanStorage();
    } catch (error) {
      if (status) status.textContent = `Bereinigung abgebrochen · ${error.message}`;
      button.disabled = false;
    }
  }

  function install() {
    ensureStyle(); injectUi();
    liveTimer = window.setInterval(() => {
      if (storageActive() && !document.hidden) void refreshStatus(true);
    }, POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && storageActive()) void refreshStatus(true);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, { once: true });
  else install();
})();