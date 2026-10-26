import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { createDialog } from "../../shared/components/dialog.js";

export function createOperationSettings(root, { getConfig, applyMode, client = api }) {
  const document = root.ownerDocument;
  const find = id => document.getElementById(id);
  const modal = find("installation-dialog");
  let scope, wizard, step = 1, target = "desktop", storage;
  const dialog = createDialog(modal, { initialFocus: () => find("installation-close"), onClose() { wizard = null; } });
  const name = mode => mode === "nas" ? "NAS / Server" : "Computer";
  const transfer = () => getConfig()?.runtime?.startup_managed !== false || find("installation-transfer").checked;
  function text(id, value) { const node = find(id); if (node) node.textContent = value; }
  function renderStorage(value) {
    if (value?.policy) storage = value;
    const mode = storage?.policy?.mode;
    const automatic = mode === "automatic" || mode === "full";
    const known = !storage?.storage_error && ["monitor", "advisor", "automatic", "full"].includes(mode);
    text("operation-policy-label", !known ? "Strategie nicht verfügbar" : automatic ? "Automatische Verteilung" : mode === "advisor" ? "Feste Ziele mit Vorschlägen" : "Feste Downloadziele");
    text("operation-destinations-title", !known ? "Deine Downloadziele" : automatic ? "Royal wählt den passenden Speicher." : "Du legst die Downloadziele fest.");
    text("operation-policy-description", !known ? "Speicher konnte nicht abgefragt werden. Öffne die Verteilungseinstellungen, um den aktuellen Stand zu prüfen." : automatic
      ? "Neue Downloads werden auf deine freigegebenen Speicher verteilt. Medientyp, Platzreserve und vorhandene Serienordner zählen mit."
      : "Filme und Serien landen in den unten festgelegten Ordnern. Weitere Speicherorte werden erst bei automatischer Verteilung verwendet.");
    text("operation-placement-choice", automatic ? "Royal prüft Platz & Freigaben" : "Deine Ordnerwahl");
    text("operation-placement-result", automatic ? "Geeigneter Speicher" : "Festes Downloadziel");
    text("operation-base-title", automatic ? "Basisordner" : "Deine Downloadordner");
    text("operation-base-explanation", automatic ? "Ausgangspunkt für die Ablage. Der tatsächliche Download darf auf einem anderen freigegebenen Speicher landen." : "Diese Ordner werden für neue Downloads verwendet. Anime folgt dem Serienordner.");
    text("operation-volume-count", storage?.summary ? `${storage.summary.volume_count || 0} physische Volumes` : "Stand nicht verfügbar");
    text("operation-storage-summary", !known ? "Ziele und Verteilung findest du gesammelt im Speicherbereich." : automatic
      ? `Automatische Verteilung aktiv. ${storage.summary?.volume_count || 0} Volumes werden überwacht. Ziele und Regeln verwaltest du an einem Ort.`
      : "Filme und Serien haben feste Ziele. Weitere Speicher und automatische Verteilung verwaltest du an einem Ort.");
  }
  function render() {
    const config = getConfig();
    if (!config) return;
    const runtime = config.runtime;
    const current = runtime?.mode || config.deployment_mode;
    text("operation-title", runtime ? runtime.container ? "Royal im Container" : current === "nas" ? "Royal als Netzwerkdienst" : "Royal als lokaler Dienst" : "Deine Royal-Installation");
    text("operation-description", !runtime ? "Das gespeicherte Startprofil allein bestätigt keine laufende Geräteumstellung." : runtime.startup_managed
      ? "Die Startumgebung wird außerhalb von Royal verwaltet. Für einen Gerätewechsel führt dich ein Assistent durch die Vorbereitung."
      : "Das Startprofil bestimmt Netzwerkzugriff und Browserstart. Änderungen werden erst beim nächsten Start wirksam.");
    text("operation-runtime-label", runtime ? `${runtime.container ? "Docker" : "Native Installation"} · ${runtime.platform}` : "Laufzeit nicht gemeldet");
    text("operation-network-label", runtime ? ["127.0.0.1", "localhost", "::1"].includes(runtime.bind_host) ? "Dienst an Loopback gebunden" : "Dienst im Netzwerk gebunden" : name(config.deployment_mode));
    text("deployment-mode-status", runtime && runtime.mode !== config.deployment_mode
      ? `Gespeichertes Startprofil: ${name(config.deployment_mode)}. Laufende Umgebung: ${name(runtime.mode)}.`
      : "Geführte Einrichtung für Startprofil und Gerätewechsel.");
    text("operation-profile", name(config.deployment_mode));
    text("operation-change", runtime?.startup_managed ? "Umzug vorbereiten" : "Installation ändern");
    text("operation-data-path", runtime?.data_path || "Nicht gemeldet");
    text("operation-address", document.defaultView?.location.host || "—");
    text("operation-movie-path", config.save_path || "Nicht konfiguriert");
    text("operation-series-path", config.series_path || config.save_path || "Nicht konfiguriert");
    renderStorage();
  }
  function paths() {
    const os = find("installation-os").value;
    const base = target === "nas" ? "/volume1/media/" : os === "windows" ? "C:\\Royal\\Medien\\" : os === "macos" ? "/Users/DEIN_NAME/Movies/Royal/" : "/home/DEIN_NAME/Medien/";
    find("installation-movie-path").value = base + "Filme";
    find("installation-series-path").value = base + "Serien";
  }
  function destinationStep() {
    const managed = getConfig()?.runtime?.startup_managed !== false;
    find("installation-transfer-choice").hidden = managed;
    if (managed) find("installation-transfer").checked = true;
    find("installation-target-paths").hidden = !transfer();
    find("installation-os").disabled = target === "nas";
    text("installation-host-note", transfer()
      ? "Diese Pfade gehören zum Zielgerät. Auf der laufenden Installation wird dabei nichts geändert."
      : "Nur das Startverhalten dieses Geräts wird angepasst. Speicherorte, Konten und Abos bleiben erhalten. Ein Neustart ist anschließend erforderlich.");
  }
  function review() {
    const runtime = getConfig()?.runtime;
    text("installation-review-route", `${name(runtime?.mode || getConfig()?.deployment_mode)} → ${name(target)}`);
    const body = find("installation-review-body"); body.replaceChildren();
    const items = transfer() ? [
      ["Bestehende Installation sichern", `Downloads vorher anhalten. Den vollständigen Royal-Datenordner sichern: ${runtime?.data_path || "Datenordner der Installation"}. Konten, Abos und der 2FA-Schlüssel gehören zusammen.`],
      ["Zielgerät einrichten", target === "nas" ? "Royal als Container einrichten und die Medienordner als Volumes einbinden. Der Plan enthält die gewählten Host-Pfade." : "Royal auf dem gewählten Computer installieren. Dort die neuen Film- und Serienordner anlegen."],
      ["Daten übernehmen & starten", "Den gesicherten Datenordner vollständig übernehmen und Dateirechte prüfen. Medien getrennt kopieren oder einbinden. Zielpfade anpassen, Royal starten und Anmeldung sowie Speicher prüfen. Erst danach die alte Instanz ablösen."],
    ] : [["Beim nächsten Start", target === "desktop" ? "Royal bindet an 127.0.0.1 und öffnet den lokalen Browser. Der bisherige Netzwerkzugriff endet nach dem Neustart." : "Royal bindet an 0.0.0.0 und startet ohne Browserfenster. Der Dienst kann im lokalen Netzwerk erreicht werden."], ["Bleibt erhalten", "Medienpfade, Konten, Abonnements und laufende Prozesse werden durch das Vormerken nicht verändert."]];
    const list = document.createElement("ol");
    for (const [heading, copy] of items) {
      const item = document.createElement("li"), strong = document.createElement("strong"), paragraph = document.createElement("p");
      strong.textContent = heading; paragraph.textContent = copy; item.append(strong, paragraph); list.append(item);
    }
    body.append(list);
    text("installation-result", transfer() ? "Der Assistent erstellt einen Umzugsplan. Er kopiert keine Dateien und stellt das NAS nicht automatisch auf einen Computer um." : "Royal wird hierdurch noch nicht neu gestartet.");
  }
  function show(next) {
    step = next; text("installation-error", "");
    modal.querySelectorAll("[data-installation-step]").forEach(node => { node.hidden = Number(node.dataset.installationStep) !== step; });
    text("installation-progress", `Schritt ${step} von 3`);
    text("installation-title", ["", "Wie soll Royal weiterlaufen?", "Den Wechsel vorbereiten", "So gelingt dein Wechsel"][step]);
    find("installation-back").hidden = step === 1;
    find("installation-next").hidden = step === 3;
    find("installation-download").hidden = step !== 3 || !transfer();
    find("installation-apply").hidden = step !== 3 || transfer();
    if (step === 2) destinationStep();
    if (step === 3) {
      review();
      const unchanged = !transfer() && target === getConfig()?.deployment_mode;
      find("installation-apply").disabled = unchanged;
      if (unchanged) text("installation-result", "Dieses Startprofil ist bereits eingerichtet. Für einen Gerätewechsel wähle den Umzug auf ein anderes Gerät.");
    }
  }
  function downloadPlan() {
    const runtime = getConfig()?.runtime;
    const plan = ["Royal – Umzugsplan", "", `Ziel: ${name(target)}`, `Zielsystem: ${target === "nas" ? "Docker / NAS" : find("installation-os").selectedOptions[0].textContent}`,
      `Bisheriger Datenordner: ${runtime?.data_path || "siehe Installation"}`, "", find("installation-review-body").textContent, "",
      "Startwerte auf dem Zielgerät (bestehende Konfiguration ergänzen, nicht blind ersetzen):", `ROYAL_DEPLOYMENT_MODE=${target}`, `HOST=${target === "nas" ? "0.0.0.0" : "127.0.0.1"}`, `OPEN_BROWSER=${target === "nas" ? "0" : "1"}`, `ROYAL_BIND_ADDRESS=${target === "nas" ? "0.0.0.0" : "127.0.0.1"}`,
      `${target === "nas" ? "MOVIES_HOST_DIR" : "DOWNLOAD_DIR"}=${find("installation-movie-path").value.trim()}`, `${target === "nas" ? "SERIES_HOST_DIR" : "SERIES_DIR"}=${find("installation-series-path").value.trim()}`,
      "", "Die Startwerte ersetzen kein Backup und keine Installation. Bei Docker müssen Portbindung und Volumes im Compose-Projekt passend gesetzt sein.", "Einstellungen auf dem Ziel übernehmen/anpassen und im Speicherbereich bestätigen. Zugangsdaten/2FA-Schlüssel werden in diesem Plan nicht exportiert."];
    const url = URL.createObjectURL(new Blob([plan.join("\n")], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "royal-umzugsplan.txt"; document.body.append(link); link.click(); link.remove();
    scope.timeout(() => URL.revokeObjectURL(url), 1000); scope.add(() => URL.revokeObjectURL(url));
    text("installation-result", "Umzugsplan heruntergeladen. Deine laufende Installation wurde nicht verändert.");
  }
  function open() {
    if (!getConfig()) return;
    wizard = dialog.open(); target = getConfig().deployment_mode === "nas" ? "desktop" : "nas";
    find("installation-transfer").checked = getConfig().runtime?.startup_managed !== false;
    modal.querySelectorAll("[data-installation-target]").forEach(button => { button.setAttribute("aria-pressed", String(button.dataset.installationTarget === target)); });
    paths(); show(1);
    wizard.listen(find("installation-close"), "click", () => dialog.close());
    wizard.listen(find("installation-back"), "click", () => show(step - 1));
    wizard.listen(find("installation-next"), "click", () => {
      if (step === 2 && transfer() && ["installation-movie-path", "installation-series-path"].some(id => !find(id).value.trim() || /[\r\n\0]/.test(find(id).value))) {
        text("installation-error", "Gültige Zielordner auf dem neuen Gerät angeben."); return;
      }
      show(step + 1);
    });
    for (const button of modal.querySelectorAll("[data-installation-target]")) wizard.listen(button, "click", () => {
      target = button.dataset.installationTarget; paths();
      modal.querySelectorAll("[data-installation-target]").forEach(node => { node.setAttribute("aria-pressed", String(node === button)); });
    });
    wizard.listen(find("installation-transfer"), "change", destinationStep);
    wizard.listen(find("installation-os"), "change", paths);
    wizard.listen(find("installation-download"), "click", downloadPlan);
    wizard.listen(find("installation-apply"), "click", async () => {
      const current = wizard; const button = find("installation-apply"); button.disabled = true;
      try {
        await applyMode(target, current.signal);
        if (!current.active) return;
        render(); text("installation-result", "Startprofil gespeichert. Beim nächsten manuellen Neustart wird die neue Konfiguration verwendet.");
      } catch (error) { if (current.active) text("installation-error", error.message); }
      finally { if (current.active) button.disabled = false; }
    });
    text("installation-change-note", getConfig().runtime?.startup_managed ? "Ein Container wird durch einen Modusschalter nicht zu einer lokalen Installation. Für den Wechsel bereitest du das Zielgerät vor." : "Du kannst das Startprofil dieses Geräts anpassen oder Royal auf ein anderes Gerät umziehen.");
  }
  return {
    render,
    mount() {
      if (scope) return; scope = createScope(); render();
      scope.listen(find("operation-change"), "click", open);
      scope.listen(root, "royal:storage-overview", event => renderStorage(event.detail));
      for (const button of root.querySelectorAll("[data-operation-policy-open]")) scope.listen(button, "click", () => {
        const policy = find("storage-autopilot"); policy?.scrollIntoView({ behavior: "smooth", block: "start" });
        policy?.querySelector('input[name="storage-autonomy"]:checked')?.focus({ preventScroll: true });
      });
      const current = scope;
      void client.get("/api/storage/autopilot", { signal: current.signal }).then(value => { if (current.active) renderStorage(value); }).catch(() => { if (current.active) renderStorage(); });
    },
    unmount() { dialog.unmount(); scope?.dispose(); scope = null; },
  };
}
