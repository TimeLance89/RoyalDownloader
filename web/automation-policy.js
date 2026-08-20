/* Royal Smart Automation: advanced unattended NAS policy UI. */
(() => {
  "use strict";

  if (window.__royalSmartAutomationInstalled) return;
  window.__royalSmartAutomationInstalled = true;

  const POLICY_URL = "/api/automation/policy";
  const REFRESH_MS = 15_000;
  let latestPolicy = null;
  let applyPatched = false;

  function byId(id) { return document.getElementById(id); }
  function numberValue(id, fallback = 0) {
    const value = Number(byId(id)?.value);
    return Number.isFinite(value) ? value : fallback;
  }
  function optionalHour(id) {
    const raw = String(byId(id)?.value ?? "").trim();
    if (!raw) return null;
    const value = Number.parseInt(raw, 10);
    return Number.isInteger(value) && value >= 0 && value <= 23 ? value : null;
  }
  function hourText(value) {
    return value == null ? "—" : `${String(value).padStart(2, "0")}:00`;
  }
  function windowText(start, end) {
    if (start == null || end == null || Number(start) === Number(end)) return "jederzeit";
    return `${hourText(start)}–${hourText(end)}`;
  }

  function ensureStyles() {
    if (document.querySelector("link[data-smart-automation-style]")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/styles/automation-policy.css?v=royal-20260820-1";
    link.dataset.smartAutomationStyle = "true";
    document.head.appendChild(link);
  }

  function injectUi() {
    if (byId("smart-automation-policy")) return true;
    const autoToggle = byId("auto-download");
    const card = autoToggle?.closest(".settings-card");
    const weekdayRow = byId("dl-window-start")?.closest(".path-input-row");
    if (!card || !weekdayRow) return false;

    weekdayRow.classList.add("smart-automation-weekday-row");
    const weekdayLabel = weekdayRow.querySelector("label");
    if (weekdayLabel) weekdayLabel.textContent = "Mo–Fr";

    weekdayRow.insertAdjacentHTML("afterend", `
      <div id="smart-automation-policy" class="smart-automation-policy">
        <div class="smart-policy-heading">
          <div>
            <span class="smart-policy-kicker">ROYAL AUTOMATION ENGINE</span>
            <h4>Intelligente NAS-Regeln</h4>
            <p>Zeitpläne, Lastgrenzen und Schutzregeln greifen nur für unbeaufsichtigte Automatik. Manuelle Downloads bleiben verfügbar.</p>
          </div>
          <span class="smart-policy-live"><i aria-hidden="true"></i> LIVE</span>
        </div>

        <section class="smart-policy-block" aria-labelledby="smart-schedule-title">
          <header><span class="smart-policy-icon" aria-hidden="true">◷</span><div><strong id="smart-schedule-title">Wochenplan</strong><small>Mo–Fr nutzt das Zeitfenster oben. Wochenende kann unabhängig laufen.</small></div></header>
          <div class="smart-policy-fields is-window">
            <label><span>Wochenende ab</span><input id="weekend-window-start" type="number" min="0" max="23" placeholder="–" inputmode="numeric"><small>leer = jederzeit</small></label>
            <label><span>bis</span><input id="weekend-window-end" type="number" min="0" max="23" placeholder="–" inputmode="numeric"><small>Uhr</small></label>
          </div>
        </section>

        <section class="smart-policy-block" aria-labelledby="smart-performance-title">
          <header><span class="smart-policy-icon" aria-hidden="true">⇅</span><div><strong id="smart-performance-title">Leistung</strong><small>Begrenzt die Gesamtlast des Downloaders auf dem NAS.</small></div></header>
          <div class="smart-policy-fields">
            <label><span>Parallele Downloads</span><select id="max-parallel-downloads" aria-label="Maximale parallele Downloads"><option value="1">1 Download</option><option value="2">2 Downloads</option><option value="3">3 Downloads</option><option value="4">4 Downloads</option></select><small>Neue Jobs beachten das Limit sofort.</small></label>
            <label><span>Max. Bandbreite</span><span class="smart-policy-unit"><input id="max-bandwidth-mbps" type="number" min="0" max="10000" step="0.5" value="0" inputmode="decimal"><b>MB/s</b></span><small>0 = unbegrenzt · Gesamtbudget über alle Slots</small></label>
          </div>
        </section>

        <section class="smart-policy-block" aria-labelledby="smart-safety-title">
          <header><span class="smart-policy-icon" aria-hidden="true">▰</span><div><strong id="smart-safety-title">Speicherschutz</strong><small>Verhindert, dass Hintergrund-Automatik den Ziel-Datenträger volllaufen lässt.</small></div></header>
          <div class="smart-policy-fields"><label><span>Mindestens frei halten</span><span class="smart-policy-unit"><input id="min-free-space-gb" type="number" min="0" max="1000000" step="1" value="0" inputmode="decimal"><b>GB</b></span><small>0 = Schutz aus · automatische neue Downloads warten darunter.</small></label></div>
        </section>

        <section class="smart-policy-block" aria-labelledby="smart-jellyfin-title">
          <header><span class="smart-policy-icon" aria-hidden="true">▶</span><div><strong id="smart-jellyfin-title">Jellyfin hat Vorrang</strong><small>Bei aktiver Wiedergabe starten neue Transfers mit einem kleineren Bandbreitenbudget.</small></div></header>
          <label class="smart-policy-toggle"><input id="jellyfin-throttle-enabled" type="checkbox"><span><strong>Beim Streaming automatisch drosseln</strong><small>Royal prüft aktive, nicht pausierte Jellyfin-Sitzungen.</small></span></label>
          <label class="smart-policy-inline"><span>Streaming-Budget</span><span class="smart-policy-unit"><input id="jellyfin-streaming-bandwidth-mbps" type="number" min="0.1" max="10000" step="0.5" value="5" inputmode="decimal"><b>MB/s</b></span></label>
        </section>

        <section class="smart-policy-block" aria-labelledby="smart-movie-title">
          <header><span class="smart-policy-icon" aria-hidden="true">◆</span><div><strong id="smart-movie-title">Film-Upgrades</strong><small>Qualitätswächter dürfen optional nur im ruhigen Nachtfenster arbeiten.</small></div></header>
          <label class="smart-policy-toggle"><input id="movie-upgrades-night-only" type="checkbox"><span><strong>Automatische Film-Upgrades nur nachts</strong><small>Manuelle Abo-Prüfungen bleiben jederzeit möglich.</small></span></label>
          <div class="smart-policy-fields is-window"><label><span>Upgrade ab</span><input id="movie-upgrade-window-start" type="number" min="0" max="23" value="0" inputmode="numeric"><small>Uhr</small></label><label><span>bis</span><input id="movie-upgrade-window-end" type="number" min="0" max="23" value="6" inputmode="numeric"><small>Uhr</small></label></div>
        </section>

        <div class="smart-policy-dashboard" aria-live="polite">
          <div data-policy-state="schedule"><span>Zeitplan</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="performance"><span>Leistung</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="storage"><span>Speicher</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="jellyfin"><span>Jellyfin</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="movies"><span>Film-Upgrades</span><strong>—</strong><small>—</small></div>
        </div>
      </div>`);

    const syncDisabled = () => {
      const jellyfinEnabled = !!byId("jellyfin-throttle-enabled")?.checked;
      if (byId("jellyfin-streaming-bandwidth-mbps")) byId("jellyfin-streaming-bandwidth-mbps").disabled = !jellyfinEnabled;
      const movieNight = !!byId("movie-upgrades-night-only")?.checked;
      for (const id of ["movie-upgrade-window-start", "movie-upgrade-window-end"]) if (byId(id)) byId(id).disabled = !movieNight;
    };
    byId("jellyfin-throttle-enabled")?.addEventListener("change", syncDisabled);
    byId("movie-upgrades-night-only")?.addEventListener("change", syncDisabled);
    syncDisabled();
    return true;
  }

  function buildPolicy(legacy = {}) {
    const saved = latestPolicy || {};
    const weekdayStart = legacy.dl_window_start ?? optionalHour("dl-window-start");
    const weekdayEnd = legacy.dl_window_end ?? optionalHour("dl-window-end");
    return {
      auto_download: !!legacy.auto_download,
      check_interval_min: Math.max(5, Number(legacy.check_interval_min) || 30),
      weekday_window_start: weekdayStart,
      weekday_window_end: weekdayEnd,
      weekend_window_start: latestPolicy ? optionalHour("weekend-window-start") : (saved.weekend_window_start ?? weekdayStart),
      weekend_window_end: latestPolicy ? optionalHour("weekend-window-end") : (saved.weekend_window_end ?? weekdayEnd),
      max_parallel_downloads: Math.max(1, Math.min(4, Math.trunc(numberValue("max-parallel-downloads", saved.max_parallel_downloads ?? 2)) || 2)),
      max_bandwidth_mbps: Math.max(0, numberValue("max-bandwidth-mbps", saved.max_bandwidth_mbps ?? 0)),
      min_free_space_gb: Math.max(0, numberValue("min-free-space-gb", saved.min_free_space_gb ?? 0)),
      jellyfin_throttle_enabled: latestPolicy ? !!byId("jellyfin-throttle-enabled")?.checked : !!saved.jellyfin_throttle_enabled,
      jellyfin_streaming_bandwidth_mbps: Math.max(0.1, numberValue("jellyfin-streaming-bandwidth-mbps", saved.jellyfin_streaming_bandwidth_mbps ?? 5)),
      movie_upgrades_night_only: latestPolicy ? !!byId("movie-upgrades-night-only")?.checked : !!saved.movie_upgrades_night_only,
      movie_upgrade_window_start: latestPolicy ? optionalHour("movie-upgrade-window-start") : (saved.movie_upgrade_window_start ?? 0),
      movie_upgrade_window_end: latestPolicy ? optionalHour("movie-upgrade-window-end") : (saved.movie_upgrade_window_end ?? 6),
    };
  }

  function setField(id, value) { const input = byId(id); if (input) input.value = value == null ? "" : String(value); }
  function dashboardCell(name, strong, detail, state = "") {
    const cell = document.querySelector(`[data-policy-state="${name}"]`);
    if (!cell) return;
    cell.dataset.state = state;
    cell.querySelector("strong").textContent = strong;
    cell.querySelector("small").textContent = detail;
  }

  function renderPolicy(policy) {
    if (!policy || !injectUi()) return;
    latestPolicy = policy;
    setField("dl-window-start", policy.weekday_window_start ?? policy.dl_window_start);
    setField("dl-window-end", policy.weekday_window_end ?? policy.dl_window_end);
    setField("weekend-window-start", policy.weekend_window_start);
    setField("weekend-window-end", policy.weekend_window_end);
    setField("max-parallel-downloads", policy.max_parallel_downloads ?? 2);
    setField("max-bandwidth-mbps", policy.max_bandwidth_mbps ?? 0);
    setField("min-free-space-gb", policy.min_free_space_gb ?? 0);
    byId("jellyfin-throttle-enabled").checked = !!policy.jellyfin_throttle_enabled;
    setField("jellyfin-streaming-bandwidth-mbps", policy.jellyfin_streaming_bandwidth_mbps ?? 5);
    byId("movie-upgrades-night-only").checked = !!policy.movie_upgrades_night_only;
    setField("movie-upgrade-window-start", policy.movie_upgrade_window_start ?? 0);
    setField("movie-upgrade-window-end", policy.movie_upgrade_window_end ?? 6);

    const state = policy.policy_state || {};
    const weekday = windowText(policy.weekday_window_start, policy.weekday_window_end);
    const weekend = windowText(policy.weekend_window_start, policy.weekend_window_end);
    const scheduleOpen = state.schedule_open !== false;
    dashboardCell("schedule", scheduleOpen ? "Automatik offen" : "Automatik wartet", `Mo–Fr ${weekday} · Wochenende ${weekend}`, scheduleOpen ? "ok" : "waiting");

    const bandwidth = state.bandwidth || {};
    const configuredBandwidth = Number(policy.max_bandwidth_mbps || 0);
    const effectiveBandwidth = Number(bandwidth.effective_mbps || configuredBandwidth || 0);
    dashboardCell("performance", `${policy.max_parallel_downloads || 2} Slots`, effectiveBandwidth > 0 ? `${effectiveBandwidth.toLocaleString("de-DE", { maximumFractionDigits: 1 })} MB/s Gesamtbudget` : "Bandbreite unbegrenzt", "ok");

    const storage = state.storage || {};
    if (!Number(policy.min_free_space_gb || 0)) dashboardCell("storage", "Schutz aus", "Kein Mindestfreiraum", "");
    else if (storage.free_gb == null) dashboardCell("storage", storage.ok === false ? "Nicht prüfbar" : "Wird geprüft", storage.error || `${policy.min_free_space_gb} GB Minimum`, storage.ok === false ? "warning" : "");
    else dashboardCell("storage", `${Number(storage.free_gb).toLocaleString("de-DE", { maximumFractionDigits: 1 })} GB frei`, `Minimum ${Number(policy.min_free_space_gb).toLocaleString("de-DE", { maximumFractionDigits: 1 })} GB`, storage.ok === false ? "warning" : "ok");

    const playback = bandwidth.jellyfin || {};
    if (!policy.jellyfin_throttle_enabled) dashboardCell("jellyfin", "Drosselung aus", "Downloads laufen mit normalem Budget", "");
    else if (!playback.configured) dashboardCell("jellyfin", "Nicht verbunden", "Jellyfin-Drosselung wartet auf Konfiguration", "warning");
    else if (!playback.reachable) dashboardCell("jellyfin", "Nicht erreichbar", "Normales Downloadbudget bleibt aktiv", "warning");
    else if (Number(playback.active_streams || 0) > 0) dashboardCell("jellyfin", `${playback.active_streams} aktive Wiedergabe${playback.active_streams === 1 ? "" : "n"}`, `${Number(bandwidth.effective_mbps || 0).toLocaleString("de-DE", { maximumFractionDigits: 1 })} MB/s während Streaming`, "active");
    else dashboardCell("jellyfin", "Kein Stream aktiv", "Normales Downloadbudget", "ok");

    const movieWindow = windowText(policy.movie_upgrade_window_start, policy.movie_upgrade_window_end);
    dashboardCell("movies", policy.movie_upgrades_night_only ? (state.movie_upgrade_window_open === false ? "Wartet auf Nacht" : "Nachtfenster offen") : "Jederzeit", policy.movie_upgrades_night_only ? movieWindow : "Keine Zeitbeschränkung", state.movie_upgrade_window_open === false ? "waiting" : "ok");

    const summary = byId("auto-status");
    if (summary) summary.textContent = !policy.auto_download ? "Auto-Download aus · Regeln bleiben gespeichert." : [state.schedule_open === false ? "Auto-Download wartet" : "Auto-Download bereit", `alle ${policy.check_interval_min} Min.`, `${policy.max_parallel_downloads} Slot${policy.max_parallel_downloads === 1 ? "" : "s"}`, configuredBandwidth > 0 ? `max. ${configuredBandwidth} MB/s` : "ohne Bandbreitenlimit"].join(" · ");

    byId("jellyfin-streaming-bandwidth-mbps").disabled = !policy.jellyfin_throttle_enabled;
    for (const id of ["movie-upgrade-window-start", "movie-upgrade-window-end"]) byId(id).disabled = !policy.movie_upgrades_night_only;
  }

  function installApiBridge() {
    if (typeof api === "undefined" || api.__royalSmartAutomationApi) return false;
    api.__royalSmartAutomationApi = true;
    api.automationConfigGet = function automationPolicyGet() { return this.get(POLICY_URL); };
    api.automationConfigSet = async function automationPolicySet(legacy) {
      if (!latestPolicy) {
        try { latestPolicy = await this.get(POLICY_URL); renderPolicy(latestPolicy); }
        catch (error) { console.warn("Bestehende Automatik-Regeln konnten vor dem Speichern nicht geladen werden:", error); }
      }
      return this.post(POLICY_URL, buildPolicy(legacy));
    };
    return true;
  }

  function patchApplyAutomation() {
    if (applyPatched || typeof applyAutomationCfg !== "function") return false;
    const original = applyAutomationCfg;
    applyAutomationCfg = function applySmartAutomationCfg(policy) { original(policy); renderPolicy(policy); };
    applyPatched = true;
    return true;
  }

  async function refreshPolicy() {
    if (typeof api === "undefined" || !injectUi()) return;
    try { renderPolicy(await api.get(POLICY_URL)); }
    catch (error) {
      const summary = byId("auto-status");
      if (summary && !latestPolicy) summary.textContent = `Automatik-Regeln nicht abrufbar: ${error.message}`;
    }
  }

  function install() {
    ensureStyles();
    installApiBridge();
    if (!(injectUi() && patchApplyAutomation())) { window.setTimeout(install, 40); return; }
    void refreshPolicy();
    window.setInterval(() => {
      const settings = byId("tab-einstellungen");
      if (!document.hidden && settings?.classList.contains("active")) void refreshPolicy();
    }, REFRESH_MS);
  }

  install();
})();
