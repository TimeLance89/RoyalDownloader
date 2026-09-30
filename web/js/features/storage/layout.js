export function installStorageUi(root) {
  const find = id => root.querySelector(`#${id}`);
    if (find("settings-storage")) return;
    const nav = root.querySelector(".settings-directory-nav");
    const generalLink = nav?.querySelector('[data-settings-target="settings-general"]');
    generalLink?.insertAdjacentHTML("afterend", `
      <a href="#settings-storage" data-settings-target="settings-storage">
        <span aria-hidden="true">▰</span><strong>Speicher</strong><small>Live-Belegung &amp; Bereinigung</small>
      </a>`);

    const launchGrid = root.querySelector(".settings-launch-grid");
    const generalLaunch = launchGrid?.querySelector('[data-settings-open="settings-general"]');
    generalLaunch?.insertAdjacentHTML("afterend", `
      <button class="settings-launch-card is-storage" type="button" data-settings-open="settings-storage">
        <span class="settings-launch-symbol" aria-hidden="true">▰</span>
        <span class="settings-launch-copy"><small>SPEICHER</small><strong>Live-Belegung &amp; Bereinigung</strong><em>Mehrere Volumes, Kapazität und sichere Freigabe</em></span>
        <i aria-hidden="true">→</i>
      </button>`);

    const general = find("settings-general");
    general?.insertAdjacentHTML("afterend", `
      <section id="settings-storage" class="settings-section royal-storage-section" data-settings-section aria-labelledby="settings-storage-title" aria-hidden="true" hidden>
        <header class="settings-section-heading">
          <span class="settings-section-mark is-storage" aria-hidden="true">▰</span>
          <div><span>SPEICHER</span><h2 id="settings-storage-title">Speicher verwalten &amp; Downloads verteilen</h2>
          <p>Sieh alle Datenträger, gib zusätzliche Download-Ziele frei und entscheide, wie selbstständig Royal freien Platz nutzen darf.</p></div>
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
            <div><span>SPEICHERZIELE</span><h3 id="storage-locations-title">Zusätzliche Speicherorte</h3><p>Hier legst du fest, welche eingebundenen Ordner Royal zusätzlich nutzen darf. Bei „Medien“ kannst du direkt auswählen, ob dort Filme, Serien oder Anime landen dürfen. „Nur überwachen“ zeigt nur die Belegung an.</p></div>
            <strong id="storage-location-count">0 zusätzlich</strong>
          </header>
          <form id="storage-location-form" class="storage-location-form">
            <label><span>Name</span><input id="storage-location-label" maxlength="80" autocomplete="off" placeholder="z. B. Externe Festplatte" required></label>
            <label class="is-path"><span>Pfad im Royal-Container</span><input id="storage-location-path" maxlength="2048" autocomplete="off" placeholder="z. B. /external-media" required></label>
            <label><span>Verwendung</span><select id="storage-location-mode"><option value="monitor">Nur anzeigen</option><option value="media">Für Downloads &amp; Medien nutzen</option></select></label>
            <fieldset id="storage-location-media-types" class="storage-location-media-types" hidden>
              <legend>Was darf hier gespeichert werden?</legend>
              <label><input type="checkbox" name="storage-location-media" value="movies" checked><span>Filme</span></label>
              <label><input type="checkbox" name="storage-location-media" value="series" checked><span>Serien</span></label>
              <label><input type="checkbox" name="storage-location-media" value="anime" checked><span>Anime</span></label>
              <small>Royal verteilt nur passende Inhalte in diesen Ordner. So landen Filme nicht versehentlich im Serien-Ordner.</small>
            </fieldset>
            <div class="storage-location-form-actions"><button id="storage-location-save" class="btn btn-primary btn-sm" type="submit">Speicherort hinzufügen</button><button id="storage-location-cancel" class="btn btn-ghost btn-sm" type="button" hidden>Abbrechen</button></div>
          </form>
          <div id="storage-location-list" class="storage-location-list"><div class="storage-empty-state"><strong>Noch kein zusätzlicher Speicherort</strong><span>Der Film- und Serien-Speicher wird trotzdem automatisch live gemessen.</span></div></div>
          <p class="storage-mount-hint"><span>i</span><span><strong>Für automatische Verteilung:</strong> Zusätzliche Medienziele werden für neue Downloads erst verwendet, wenn du beim Storage Autopilot „Automatisch verteilen“ oder „Automatisch + Archiv“ auswählst.</span></p>
          <p class="storage-mount-hint"><span>i</span><span><strong>Docker/NAS:</strong> Der Ordner muss zuerst als Bind-Mount im Royal-Container sichtbar sein. Danach trägst du hier den Container-Pfad ein, zum Beispiel <code>/movies_vol2</code>. Royal bindet Laufwerke nicht selbst ein.</span></p>
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

  }
