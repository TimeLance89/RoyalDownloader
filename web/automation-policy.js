/* Royal Smart Automation: advanced unattended NAS policy UI. */
(() => {
  "use strict";

  if (window.__royalSmartAutomationInstalled) return;
  window.__royalSmartAutomationInstalled = true;

  const POLICY_URL = "/api/automation/policy";
  const REFRESH_MS = 15_000;
  const NIGHT_START = 0;
  const NIGHT_END = 6;
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
  function timeHour(id, fallback = null) {
    const raw = String(byId(id)?.value ?? "").trim();
    const match = raw.match(/^(\d{2}):(\d{2})$/);
    if (!match) return fallback;
    const hour = Number(match[1]);
    return Number.isInteger(hour) && hour >= 0 && hour <= 23 ? hour : fallback;
  }
  function hourTime(value, fallback = "00:00") {
    const hour = Number(value);
    if (!Number.isInteger(hour) || hour < 0 || hour > 23) return fallback;
    return `${String(hour).padStart(2, "0")}:00`;
  }
  function hourText(value) {
    return value == null ? "—" : `${String(value).padStart(2, "0")}:00`;
  }
  function windowText(start, end) {
    if (start == null || end == null || Number(start) === Number(end)) return "jederzeit";
    return `${hourText(start)}–${hourText(end)}`;
  }
  function sameWindow(aStart, aEnd, bStart, bEnd) {
    return (aStart ?? null) === (bStart ?? null) && (aEnd ?? null) === (bEnd ?? null);
  }
  function selectedMode(name, fallback) {
    return document.querySelector(`input[name="${name}"]:checked`)?.value || fallback;
  }
  function setMode(name, value) {
    const target = document.querySelector(`input[name="${name}"][value="${value}"]`);
    if (target) target.checked = true;
  }
  function weekdayModeFor(policy) {
    const start = policy.weekday_window_start ?? policy.dl_window_start ?? null;
    const end = policy.weekday_window_end ?? policy.dl_window_end ?? null;
    if (start == null || end == null || Number(start) === Number(end)) return "anytime";
    if (Number(start) === NIGHT_START && Number(end) === NIGHT_END) return "night";
    return "custom";
  }
  function weekendModeFor(policy) {
    const weekdayStart = policy.weekday_window_start ?? policy.dl_window_start ?? null;
    const weekdayEnd = policy.weekday_window_end ?? policy.dl_window_end ?? null;
    const start = policy.weekend_window_start ?? null;
    const end = policy.weekend_window_end ?? null;
    if (start == null || end == null || Number(start) === Number(end)) return "anytime";
    if (sameWindow(start, end, weekdayStart, weekdayEnd)) return "same";
    return "custom";
  }

  function ensureStyles() {
    if (document.querySelector("link[data-smart-automation-style]")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/styles/automation-policy.css?v=royal-20260821-1";
    link.dataset.smartAutomationStyle = "true";
    document.head.appendChild(link);
  }

  function scheduleChoice(name, value, label, description) {
    return `<label class="smart-schedule-choice"><input type="radio" name="${name}" value="${value}"><span><strong>${label}</strong><small>${description}</small></span></label>`;
  }

  function injectUi() {
    if (byId("smart-automation-policy")) return true;
    const autoToggle = byId("auto-download");
    const card = autoToggle?.closest(".settings-card");
    const weekdayRow = byId("dl-window-start")?.closest(".path-input-row");
    if (!card || !weekdayRow) return false;

    // Keep the original numeric fields as the legacy save contract, but remove
    // them from the visible UI. The friendly schedule controls below keep them
    // synchronized so older settings code and clients remain compatible.
    weekdayRow.classList.add("smart-automation-legacy-window");
    weekdayRow.setAttribute("aria-hidden", "true");

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
          <header><span class="smart-policy-icon" aria-hidden="true">◷</span><div><strong id="smart-schedule-title">Wochenplan</strong><small>Wähle in Alltagssprache, wann Royal neue automatische Downloads starten darf.</small></div></header>

          <div class="smart-schedule-group" role="group" aria-labelledby="weekday-schedule-label">
            <div class="smart-schedule-label"><strong id="weekday-schedule-label">Mo–Fr</strong><small>Arbeitswoche</small></div>
            <div class="smart-schedule-options">
              ${scheduleChoice("weekday-mode", "anytime", "Jederzeit", "Keine Zeitbeschränkung")}
              ${scheduleChoice("weekday-mode", "night", "Nur nachts", "00:00 bis 06:00")}
              ${scheduleChoice("weekday-mode", "custom", "Eigene Zeiten", "Zeitfenster selbst wählen")}
            </div>
            <div id="weekday-custom-window" class="smart-time-window" hidden>
              <label><span>Von</span><input id="weekday-custom-start" type="time" step="3600" value="00:00"></label>
              <span class="smart-time-arrow" aria-hidden="true">→</span>
              <label><span>Bis</span><input id="weekday-custom-end" type="time" step="3600" value="06:00"></label>
            </div>
          </div>

          <div class="smart-schedule-group" role="group" aria-labelledby="weekend-schedule-label">
            <div class="smart-schedule-label"><strong id="weekend-schedule-label">Wochenende</strong><small>Samstag & Sonntag</small></div>
            <div class="smart-schedule-options">
              ${scheduleChoice("weekend-mode", "anytime", "Jederzeit", "Am Wochenende immer erlauben")}
              ${scheduleChoice("weekend-mode", "same", "Wie Mo–Fr", "Arbeitswochen-Zeitplan übernehmen")}
              ${scheduleChoice("weekend-mode", "custom", "Eigene Zeiten", "Separates Wochenendfenster")}
            </div>
            <div id="weekend-custom-window" class="smart-time-window" hidden>
              <label><span>Von</span><input id="weekend-custom-start" type="time" step="3600" value="00:00"></label>
              <span class="smart-time-arrow" aria-hidden="true">→</span>
              <label><span>Bis</span><input id="weekend-custom-end" type="time" step="3600" value="06:00"></label>
            </div>
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
          <div class="smart-time-window smart-movie-time-window"><label><span>Von</span><input id="movie-upgrade-window-start" type="time" step="3600" value="00:00"></label><span class="smart-time-arrow" aria-hidden="true">→</span><label><span>Bis</span><input id="movie-upgrade-window-end" type="time" step="3600" value="06:00"></label></div>
        </section>

        <div class="smart-policy-dashboard" aria-live="polite">
          <div data-policy-state="schedule"><span>Zeitplan</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="performance"><span>Leistung</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="storage"><span>Speicher</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="jellyfin"><span>Jellyfin</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="movies"><span>Film-Upgrades</span><strong>—</strong><small>—</small></div>
        </div>
      </div>`);

    const normalizeClock = (event) => {
      const input = event.currentTarget;
      const hour = timeHour(input.id, 0);
      input.value = hourTime(hour);
      syncScheduleControls();
    };
    document.querySelectorAll('.smart-time-window input[type="time"]').forEach((input) => {
      input.addEventListener("change", normalizeClock);
    });
    document.querySelectorAll('input[name="weekday-mode"], input[name="weekend-mode"]').forEach((input) => {
      input.addEventListener("change", syncScheduleControls);
    });

    const syncDisabled = () => {
      const jellyfinEnabled = !!byId("jellyfin-throttle-enabled")?.checked;
      if (byId("jellyfin-streaming-bandwidth-mbps")) byId("jellyfin-streaming-bandwidth-mbps").disabled = !jellyfinEnabled;
      const movieNight = !!byId("movie-upgrades-night-only")?.checked;
      for (const id of ["movie-upgrade-window-start", "movie-upgrade-window-end"]) if (byId(id)) byId(id).disabled = !movieNight;
    };
    byId("jellyfin-throttle-enabled")?.addEventListener("change", syncDisabled);
    byId("movie-upgrades-night-only")?.addEventListener("change", syncDisabled);
    syncScheduleControls();
    syncDisabled();
    return true;
  }

  function weekdayWindowFromUi() {
    const mode = selectedMode("weekday-mode", "anytime");
    if (mode === "anytime") return [null, null];
    if (mode === "night") return [NIGHT_START, NIGHT_END];
    return [timeHour("weekday-custom-start", NIGHT_START), timeHour("weekday-custom-end", NIGHT_END)];
  }

  function weekendWindowFromUi(weekdayStart, weekdayEnd) {
    const mode = selectedMode("weekend-mode", "anytime");
    if (mode === "anytime") return [null, null];
    if (mode === "same") return [weekdayStart, weekdayEnd];
    return [timeHour("weekend-custom-start", NIGHT_START), timeHour("weekend-custom-end", NIGHT_END)];
  }

  function syncScheduleControls() {
    const weekdayMode = selectedMode("weekday-mode", "anytime");
    const weekendMode = selectedMode("weekend-mode", "anytime");
    if (byId("weekday-custom-window")) byId("weekday-custom-window").hidden = weekdayMode !== "custom";
    if (byId("weekend-custom-window")) byId("weekend-custom-window").hidden = weekendMode !== "custom";
    const [weekdayStart, weekdayEnd] = weekdayWindowFromUi();
    const legacyStart = byId("dl-window-start");
    const legacyEnd = byId("dl-window-end");
    if (legacyStart) legacyStart.value = weekdayStart == null ? "" : String(weekdayStart);
    if (legacyEnd) legacyEnd.value = weekdayEnd == null ? "" : String(weekdayEnd);
  }

  function buildPolicy(legacy = {}) {
    const saved = latestPolicy || {};
    const [weekdayStart, weekdayEnd] = byId("smart-automation-policy")
      ? weekdayWindowFromUi()
      : [legacy.dl_window_start ?? saved.weekday_window_start ?? null, legacy.dl_window_end ?? saved.weekday_window_end ?? null];
    const [weekendStart, weekendEnd] = byId("smart-automation-policy")
      ? weekendWindowFromUi(weekdayStart, weekdayEnd)
      : [saved.weekend_window_start ?? weekdayStart, saved.weekend_window_end ?? weekdayEnd];
    return {
      auto_download: !!legacy.auto_download,
      check_interval_min: Math.max(5, Number(legacy.check_interval_min) || 30),
      weekday_window_start: weekdayStart,
      weekday_window_end: weekdayEnd,
      weekend_window_start: weekendStart,
      weekend_window_end: weekendEnd,
      max_parallel_downloads: Math.max(1, Math.min(4, Math.trunc(numberValue("max-parallel-downloads", saved.max_parallel_downloads ?? 2)) || 2)),
      max_bandwidth_mbps: Math.max(0, numberValue("max-bandwidth-mbps", saved.max_bandwidth_mbps ?? 0)),
      min_free_space_gb: Math.max(0, numberValue("min-free-space-gb", saved.min_free_space_gb ?? 0)),
      jellyfin_throttle_enabled: latestPolicy ? !!byId("jellyfin-throttle-enabled")?.checked : !!saved.jellyfin_throttle_enabled,
      jellyfin_streaming_bandwidth_mbps: Math.max(0.1, numberValue("jellyfin-streaming-bandwidth-mbps", saved.jellyfin_streaming_bandwidth_mbps ?? 5)),
      movie_upgrades_night_only: latestPolicy ? !!byId("movie-upgrades-night-only")?.checked : !!saved.movie_upgrades_night_only,
      movie_upgrade_window_start: latestPolicy ? timeHour("movie-upgrade-window-start", saved.movie_upgrade_window_start ?? NIGHT_START) : (saved.movie_upgrade_window_start ?? NIGHT_START),
      movie_upgrade_window_end: latestPolicy ? timeHour("movie-upgrade-window-end", saved.movie_upgrade_window_end ?? NIGHT_END) : (saved.movie_upgrade_window_end ?? NIGHT_END),
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
    const weekdayStart = policy.weekday_window_start ?? policy.dl_window_start ?? null;
    const weekdayEnd = policy.weekday_window_end ?? policy.dl_window_end ?? null;
    const weekendStart = policy.weekend_window_start ?? null;
    const weekendEnd = policy.weekend_window_end ?? null;

    setMode("weekday-mode", weekdayModeFor(policy));
    setField("weekday-custom-start", hourTime(weekdayStart ?? NIGHT_START));
    setField("weekday-custom-end", hourTime(weekdayEnd ?? NIGHT_END));
    setMode("weekend-mode", weekendModeFor(policy));
    setField("weekend-custom-start", hourTime(weekendStart ?? NIGHT_START));
    setField("weekend-custom-end", hourTime(weekendEnd ?? NIGHT_END));
    syncScheduleControls();

    setField("max-parallel-downloads", policy.max_parallel_downloads ?? 2);
    setField("max-bandwidth-mbps", policy.max_bandwidth_mbps ?? 0);
    setField("min-free-space-gb", policy.min_free_space_gb ?? 0);
    byId("jellyfin-throttle-enabled").checked = !!policy.jellyfin_throttle_enabled;
    setField("jellyfin-streaming-bandwidth-mbps", policy.jellyfin_streaming_bandwidth_mbps ?? 5);
    byId("movie-upgrades-night-only").checked = !!policy.movie_upgrades_night_only;
    setField("movie-upgrade-window-start", hourTime(policy.movie_upgrade_window_start ?? NIGHT_START));
    setField("movie-upgrade-window-end", hourTime(policy.movie_upgrade_window_end ?? NIGHT_END));

    const state = policy.policy_state || {};
    const weekday = windowText(weekdayStart, weekdayEnd);
    const weekend = windowText(weekendStart, weekendEnd);
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

  function settingsHaveUnsavedChanges() {
    return byId("settings-saved-status")?.textContent?.trim() === "Ungespeicherte Änderungen.";
  }

  async function refreshPolicy() {
    if (typeof api === "undefined" || !injectUi() || settingsHaveUnsavedChanges()) return;
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
