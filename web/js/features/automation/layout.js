  function scheduleChoice(name, value, label, description) {
    return `<label class="smart-schedule-choice"><input type="radio" name="${name}" value="${value}"><span><strong>${label}</strong><small>${description}</small></span></label>`;
  }

export function installAutomationUi(root) {
    const byId = id => root.querySelector(`#${id}`);
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
        <nav class="automation-tabs" aria-label="Automatikbereiche">
          <button type="button" data-automation-tab="schedule" aria-current="page">Wochenplan</button>
          <button type="button" data-automation-tab="limits">Leistung &amp; Schutz</button>
          <button type="button" data-automation-tab="status">Status</button>
        </nav>
        <div data-automation-panel="schedule">
        <section class="smart-policy-block" aria-labelledby="smart-schedule-title">
          <header><span class="smart-policy-icon" aria-hidden="true">◷</span><div><strong id="smart-schedule-title">Wochenplan</strong><small>Wann dürfen neue Folgen automatisch starten?</small></div></header>

          <div id="automation-interval-slot" class="automation-interval"><div><strong>Nach neuen Folgen suchen</strong><small>Prüfintervall für abonnierte Serien</small></div></div>
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

        </div>
        <div data-automation-panel="limits" class="automation-limits" hidden>
        <section class="smart-policy-block" aria-labelledby="smart-performance-title">
          <header><span class="smart-policy-icon" aria-hidden="true">⇅</span><div><strong id="smart-performance-title">Leistung</strong><small>Download-Anzahl und gemeinsames Bandbreitenbudget.</small></div></header>
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

        </div>
        <div data-automation-panel="schedule">
        <details class="smart-policy-block automation-movie-block">
          <summary><strong id="smart-movie-title">Film-Upgrades</strong><span>Eigenes Zeitfenster für bessere Filmversionen</span></summary>
          <label class="smart-policy-toggle"><input id="movie-upgrades-night-only" type="checkbox"><span><strong>Automatische Film-Upgrades nur nachts</strong><small>Manuelle Abo-Prüfungen bleiben jederzeit möglich.</small></span></label>
          <div class="smart-time-window smart-movie-time-window"><label><span>Von</span><input id="movie-upgrade-window-start" type="time" step="3600" value="00:00"></label><span class="smart-time-arrow" aria-hidden="true">→</span><label><span>Bis</span><input id="movie-upgrade-window-end" type="time" step="3600" value="06:00"></label></div>
        </details>

        </div>
        <section data-automation-panel="status" class="automation-runtime" hidden aria-labelledby="automation-runtime-title">
        <header><h3 id="automation-runtime-title">Aktuell wirksame Regeln</h3><p>Diese Übersicht zeigt den zuletzt abgerufenen Serverstand. Ungespeicherte Änderungen gelten hier noch nicht.</p><button type="button" id="automation-refresh" class="btn btn-ghost btn-sm">Status aktualisieren</button></header>
        <div class="smart-policy-dashboard" aria-live="polite">
          <div data-policy-state="schedule"><span>Zeitplan</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="performance"><span>Leistung</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="storage"><span>Speicher</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="jellyfin"><span>Jellyfin</span><strong>—</strong><small>—</small></div>
          <div data-policy-state="movies"><span>Film-Upgrades</span><strong>—</strong><small>—</small></div>
        </div>
        <p class="automation-runtime-note">Die Uhrzeiten richten sich nach der lokalen Zeit des Royal-Servers. Ein geschlossenes Zeitfenster verhindert neue automatische Starts.</p>
        </section>
        <footer class="automation-actions"><p id="automation-save-status" role="status" aria-live="polite">Regeln werden geladen …</p><button id="automation-save" type="button" class="btn btn-accent" disabled>Automatik speichern</button></footer>
      </div>`);
    byId("automation-interval-slot").append(byId("check-interval").closest(".auto-fields"));
    const toolbar = root.ownerDocument.createElement("div"); toolbar.className = "automation-toolbar";
    const tabs = card.querySelector(".automation-tabs"); tabs.before(toolbar);
    toolbar.append(tabs, card.querySelector(".automation-actions"));

    return true;
  }
