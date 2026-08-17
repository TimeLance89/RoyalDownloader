(() => {
  if (window.__royalStorageManagerInstalled) return;
  window.__royalStorageManagerInstalled = true;

  const POLL_MS = 5000;
  let liveTimer = null;
  let scanRunning = false;

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
    if (document.querySelector('link[data-royal-storage-style]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/styles/storage-manager.css?v=royal-20260817-1";
    link.dataset.royalStorageStyle = "true";
    document.head.appendChild(link);
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
        <span class="settings-launch-copy"><small>SPEICHER</small><strong>Live-Belegung &amp; Bereinigung</strong><em>Kapazität, große Inhalte und sichere Freigabe</em></span>
        <i aria-hidden="true">→</i>
      </button>`);

    const general = document.getElementById("settings-general");
    general?.insertAdjacentHTML("afterend", `
      <section id="settings-storage" class="settings-section royal-storage-section" data-settings-section aria-labelledby="settings-storage-title">
        <header class="settings-section-heading">
          <span class="settings-section-mark is-storage" aria-hidden="true">▰</span>
          <div><span>SPEICHER</span><h2 id="settings-storage-title">Speicher überwachen &amp; bereinigen</h2>
          <p>Live-Kapazität der hinterlegten Medienpfade und ein sicherer Smart Scan für große Inhalte.</p></div>
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
          <div class="storage-summary-copy"><span>GESAMTÜBERSICHT</span><h3>Speicher wird abgefragt …</h3><p>Film- und Serienpfad werden direkt auf ihrem Dateisystem gemessen.</p></div>
          <div class="storage-summary-numbers"><span><small>Belegt</small><strong>—</strong></span><span><small>Frei</small><strong>—</strong></span><span><small>Kapazität</small><strong>—</strong></span></div>
        </div>
        <div id="storage-volume-grid" class="storage-volume-grid" aria-live="polite"></div>
        <section class="storage-insights-card" aria-labelledby="storage-insights-title">
          <header class="storage-insights-head"><div><span>SMART SCAN</span><h3 id="storage-insights-title">Große Inhalte &amp; Speicherfresser</h3>
          <p>Royal misst Serienordner als Einheit und erkennt zusätzlich ungewöhnlich große Einzeldateien.</p></div><strong id="storage-scan-summary">Noch nicht analysiert</strong></header>
          <div id="storage-large-content-list" class="storage-content-list"><div class="storage-empty-state"><strong>Analyse auf Abruf</strong><span>Der rekursive Scan läuft bewusst nur bei Bedarf und belastet das NAS nicht dauerhaft.</span></div></div>
        </section>
        <div id="storage-cleanup-status" class="storage-cleanup-status" role="status" aria-live="polite"></div>
        <p class="storage-danger-note"><span>!</span><span>Bereinigungen sind dauerhaft. Royal akzeptiert nur kurzlebige, erneut geprüfte Treffer innerhalb der konfigurierten Medienordner.</span></p>
      </section>`);

    document.querySelector('[data-settings-target="settings-storage"]')?.addEventListener("click", (event) => {
      event.preventDefault(); activateStorage();
    });
    document.querySelector('[data-settings-open="settings-storage"]')?.addEventListener("click", activateStorage);
    document.getElementById("storage-refresh")?.addEventListener("click", () => refreshStatus(false));
    document.getElementById("storage-scan")?.addEventListener("click", scanStorage);
    document.getElementById("storage-large-content-list")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-storage-cleanup]");
      if (button) void cleanup(button);
    });
  }

  function renderStatus(payload) {
    const live = document.getElementById("storage-live-state");
    const summary = document.getElementById("storage-summary");
    const grid = document.getElementById("storage-volume-grid");
    if (!live || !summary || !grid) return;
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
    summary.querySelector(".storage-summary-copy h3").textContent = `${formatBytes(total.free_bytes)} frei`;
    summary.querySelector(".storage-summary-copy p").textContent = payload.deployment_mode === "nas"
      ? "Direkt vom eingebundenen NAS-Dateisystem gemessen · nicht aus dem Container geschätzt."
      : "Direkt auf den konfigurierten lokalen Medienpfaden gemessen.";
    const values = summary.querySelectorAll(".storage-summary-numbers strong");
    if (values[0]) values[0].textContent = formatBytes(total.used_bytes);
    if (values[1]) values[1].textContent = formatBytes(total.free_bytes);
    if (values[2]) values[2].textContent = formatBytes(total.total_bytes);
    live.textContent = `${payload.volumes?.length || 0} Volume${payload.volumes?.length === 1 ? "" : "s"} · ${new Date((payload.observed_at || Date.now() / 1000) * 1000).toLocaleTimeString("de-DE")}`;

    const roots = payload.roots || [];
    grid.innerHTML = roots.map((root) => root.available ? `
      <article class="storage-volume-card"><header><span>${html(root.label)}</span><strong>${formatPercent(root.used_percent)}</strong></header>
      <code title="${html(root.resolved_path || root.path)}">${html(root.path || root.resolved_path)}</code>
      <div class="storage-meter" style="--storage-used:${Number(root.used_percent) || 0}%"><i></i></div>
      <div class="storage-volume-numbers"><span><small>Belegt</small><b>${formatBytes(root.used_bytes)}</b></span><span><small>Frei</small><b>${formatBytes(root.free_bytes)}</b></span><span><small>Gesamt</small><b>${formatBytes(root.total_bytes)}</b></span></div>
      <p>${root.measurement === "nas_mount" ? "NAS-Mount live" : "Lokales Dateisystem live"}</p></article>` : `
      <article class="storage-volume-card is-error"><header><span>${html(root.label || root.key)}</span><strong>nicht erreichbar</strong></header><code>${html(root.path || "Nicht konfiguriert")}</code><p>${html(root.error || "Pfad konnte nicht gelesen werden.")}</p></article>`).join("");
  }

  async function refreshStatus(silent = true) {
    const live = document.getElementById("storage-live-state");
    if (!silent && live) live.textContent = "wird aktualisiert …";
    try { renderStatus(await api.get("/api/storage/status")); }
    catch (error) { if (live) live.textContent = `Live-Abfrage fehlgeschlagen · ${error.message}`; }
  }

  function renderScan(payload) {
    const list = document.getElementById("storage-large-content-list");
    const summary = document.getElementById("storage-scan-summary");
    if (!list || !summary) return;
    const candidates = payload.candidates || [];
    summary.textContent = `${Number(payload.scanned_files) || 0} Dateien geprüft · ${candidates.length} Treffer${payload.truncated ? " · Scanlimit erreicht" : ""}`;
    if (!candidates.length) {
      list.innerHTML = '<div class="storage-empty-state"><strong>Keine auffälligen großen Inhalte gefunden</strong><span>Aktuell sticht kein sicherer Bereinigungstreffer hervor.</span></div>';
      return;
    }
    list.innerHTML = candidates.map((candidate, index) => `
      <article class="storage-content-candidate"><div class="storage-candidate-rank">${String(index + 1).padStart(2, "0")}</div>
      <div class="storage-candidate-copy"><span>${html(candidate.root_label)} · ${candidate.kind === "directory" ? "Ordner" : "Datei"}</span><strong title="${html(candidate.relative_path)}">${html(candidate.name || candidate.relative_path)}</strong><small>${html(candidate.reason)} · ${Number(candidate.file_count) || 0} Dateien</small></div>
      <div class="storage-candidate-size"><strong>${formatBytes(candidate.size_bytes)}</strong><small>${Number(candidate.media_file_count) || 0} Medien</small></div>
      <button class="storage-cleanup-button" type="button" data-storage-cleanup data-root="${html(candidate.root)}" data-relative-path="${html(candidate.relative_path)}" data-token="${html(candidate.token)}" data-size="${Number(candidate.size_bytes) || 0}" data-expires-at="${Number(candidate.expires_at) || 0}" data-name="${html(candidate.name || candidate.relative_path)}">Bereinigen</button></article>`).join("");
  }

  async function scanStorage() {
    if (scanRunning) return;
    const button = document.getElementById("storage-scan");
    const summary = document.getElementById("storage-scan-summary");
    scanRunning = true;
    if (button) { button.disabled = true; button.textContent = "Analysiere …"; }
    if (summary) summary.textContent = "Medienordner werden analysiert …";
    try { renderScan(await api.post("/api/storage/scan", { max_candidates: 40 })); }
    catch (error) { if (summary) summary.textContent = `Analyse fehlgeschlagen · ${error.message}`; }
    finally { scanRunning = false; if (button) { button.disabled = false; button.textContent = "Große Inhalte analysieren"; } }
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
