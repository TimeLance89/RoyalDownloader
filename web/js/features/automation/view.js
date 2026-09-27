export function createAutomationView(root) {
  const NIGHT_START = 0;
  const NIGHT_END = 6;
  let latestPolicy = null;

  function byId(id) { return root.querySelector(`#${id}`); }
  function numberValue(id, fallback = 0) {
    const value = Number(byId(id)?.value);
    return Number.isFinite(value) ? value : fallback;
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
    return root.querySelector(`input[name="${name}"]:checked`)?.value || fallback;
  }
  function setMode(name, value) {
    const target = root.querySelector(`input[name="${name}"][value="${value}"]`);
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

  function syncDisabled() {
      const jellyfinEnabled = !!byId("jellyfin-throttle-enabled")?.checked;
      if (byId("jellyfin-streaming-bandwidth-mbps")) byId("jellyfin-streaming-bandwidth-mbps").disabled = !jellyfinEnabled;
      const movieNight = !!byId("movie-upgrades-night-only")?.checked;
      for (const id of ["movie-upgrade-window-start", "movie-upgrade-window-end"]) if (byId(id)) byId(id).disabled = !movieNight;
  }

  function bind(scope) {
    const normalizeClock = (event) => {
      const input = event.currentTarget;
      const hour = timeHour(input.id, 0);
      input.value = hourTime(hour);
      syncScheduleControls();
    };
    root.querySelectorAll('.smart-time-window input[type="time"]').forEach((input) => {
      scope.listen(input, "change", normalizeClock);
    });
    root.querySelectorAll('input[name="weekday-mode"], input[name="weekend-mode"]').forEach((input) => {
      scope.listen(input, "change", syncScheduleControls);
    });

    scope.listen(byId("jellyfin-throttle-enabled"), "change", syncDisabled);
    scope.listen(byId("movie-upgrades-night-only"), "change", syncDisabled);
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
    const cell = root.querySelector(`[data-policy-state="${name}"]`);
    if (!cell) return;
    cell.dataset.state = state;
    cell.querySelector("strong").textContent = strong;
    cell.querySelector("small").textContent = detail;
  }

  function renderPolicy(policy) {
    if (!policy) return;
    latestPolicy = policy;
    byId("auto-download").checked = !!policy.auto_download;
    byId("check-interval").value = policy.check_interval_min ?? 30;
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

  return { bind, sync() { syncScheduleControls(); syncDisabled(); }, render: renderPolicy, build: buildPolicy, get ready() { return latestPolicy !== null; } };
}
