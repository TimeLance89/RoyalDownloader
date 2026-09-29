export function installAutopilotUi(root) {
  if (root.querySelector("#storage-autopilot")) return;
  root.querySelector("#storage-summary").insertAdjacentHTML("beforebegin", `
    <section id="storage-autopilot" class="storage-autopilot" aria-labelledby="storage-autopilot-title">
      <header><h3 id="storage-autopilot-title">Royal Storage Autopilot</h3>
        <p id="storage-autopilot-health" role="status">Speicher wird geprüft …</p>
        <p id="storage-autopilot-impact">Royal behält deine Speicherorte im Blick.</p><p id="storage-autopilot-capacity" class="dim"></p></header>
      <form id="storage-autopilot-form">
        <fieldset class="storage-autonomy"><legend>Wie selbstständig darf Royal handeln?</legend>
          <label><input type="radio" name="storage-autonomy" value="monitor" checked><span><strong>Überwachen</strong><small>Kapazität anzeigen. Keine Zieländerung, Verschiebung oder Löschung.</small></span></label>
          <label><input type="radio" name="storage-autonomy" value="advisor"><span><strong>Beraten</strong><small>Konkrete Vorschläge. Du bestätigst jede Aktion.</small></span></label>
          <label><input type="radio" name="storage-autonomy" value="automatic"><span><strong>Automatisch</strong><small>Downloads sinnvoll platzieren und volle Volumes sicher entlasten.</small></span></label>
          <label><input type="radio" name="storage-autonomy" value="full"><span><strong>Vollautomatisch</strong><small>Zusätzlich ältere Inhalte auf freigegebene Archiv-Volumes verlagern.</small></span></label>
        </fieldset>
        <p>Keine Stufe erlaubt automatisch das Löschen von Medien.</p>
        <details id="storage-autopilot-advanced"><summary>Erweiterte Einstellungen</summary>
          <div class="storage-policy-grid">
            <label><span>Zeitfenster nutzen</span><input name="window_enabled" type="checkbox" checked></label>
            <label><span>Von</span><input name="window_start" type="time" value="02:00" required></label>
            <label><span>Bis</span><input name="window_end" type="time" value="07:00" required></label>
            <label><span>Planungsintervall (Std.)</span><input name="interval_hours" type="number" min="1" max="168" value="6" required></label>
            <label><span>Ruhezeit je Inhalt (Std.)</span><input name="cooldown_hours" type="number" min="24" max="8760" value="168" required></label>
            <label><span>Max. Verschiebungen pro Runde</span><input name="max_moves" type="number" min="1" max="5" value="1" required></label>
            <label><span>Datenbudget pro Runde (GiB)</span><input name="max_move_gib" type="number" min="1" max="4096" value="200" required></label>
            <label><span>Reserve für unbekannte Downloads (GiB)</span><input name="unknown_download_gib" type="number" min="1" max="1024" value="8" required></label>
            <label><span>Archivieren frühestens nach (Tagen)</span><input name="archive_age_days" type="number" min="30" max="3650" value="180" required></label>
            <label><span>Serien-Verteilung erlauben</span><input name="allow_series_split" type="checkbox"></label>
          </div>
          <p>Ein großer Verschiebejob gleichzeitig. Wiedergabe und Downloads haben Vorrang.</p>
        </details>
        <button class="btn btn-primary btn-sm" type="submit">Autopilot speichern</button>
      </form>
      <p id="storage-autopilot-status" class="dim" role="status"></p>
      <section aria-labelledby="storage-recommendations-title"><h4 id="storage-recommendations-title">Empfehlungen</h4><div id="storage-placement-advice"></div><div id="storage-recommendations">Keine Empfehlungen geladen.</div>
        <button class="btn btn-ghost btn-sm" type="button" data-autopilot-action="recommend">Empfehlungen aktualisieren</button>
      </section>
      <details id="storage-volume-policies"><summary>Volume-Rollen und Speicherziele</summary><div id="storage-volume-policy-list"></div></details>
      <details id="storage-cleanup-permission" class="storage-cleanup-permission"><summary>Automatische Bereinigung</summary>
        <p>Diese Freigabe ist unabhängig vom Autopilot-Modus. Medien und unbekannte Dateien werden niemals automatisch gelöscht.</p>
        <label><input id="storage-auto-delete" type="checkbox"> Automatisches Löschen eindeutig markierter Royal-Downloadreste erlauben</label>
        <div id="storage-cleanup-preview" hidden><p id="storage-cleanup-preview-copy"></p><button class="btn btn-ghost btn-sm" type="button" data-autopilot-action="confirm-delete">Bereinigung ausdrücklich aktivieren</button><button class="btn btn-ghost btn-sm" type="button" data-autopilot-action="cancel-delete">Abbrechen</button></div>
      </details>
      <details id="storage-autopilot-activity"><summary>Aktivitäten</summary><ol id="storage-autopilot-activity-list"></ol></details>
      <details><summary>Erweiterte Diagnose</summary><p id="storage-autopilot-schedule"></p><button class="btn btn-ghost btn-sm" type="button" data-autopilot-action="optimize">Jetzt Optimierung prüfen</button><p>Normalerweise arbeitet Royal automatisch innerhalb deiner Regeln.</p></details>
    </section>`);
}
