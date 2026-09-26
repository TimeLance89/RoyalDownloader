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

    return true;
  }
