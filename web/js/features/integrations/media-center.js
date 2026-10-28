import { createScope } from "../../core/lifecycle.js";
import { escapeHtml as esc } from "../../shared/utils/escape-html.js";
import { api } from "../../core/api.js";
import { setMediaCenter } from "../../shared/media-center.js";

const services = {
  jellyfin: { name: "Jellyfin", mark: "JF", port: "8096", credential: "API-Schlüssel", hint: "Jellyfin → Dashboard → Erweitert → API-Schlüssel" },
  plex: { name: "Plex", mark: "P", port: "32400", credential: "Plex-Token", hint: "Den X-Plex-Token deines Plex Media Servers verwenden." },
};
const mark = kind => `<span class="mc-mark is-${kind}" aria-hidden="true">${services[kind].mark}</span>`;

/** Draft credentials are private until a successful server-validated commit. */
export function createMediaCenterSettings(host, { client = api, onActivated = async () => {} } = {}) {
  if (!host) return { initialize: async () => {}, update() {}, unavailable() {}, mount() {}, unmount() {} };
  let config = null, failed = false, scope, dialog, trigger, target = "plex", step = 0, draft, completed = false, busy = false, operation, completionNote = "";
  const active = () => config?.url && config?.has_api_key ? config.provider || "jellyfin" : null;
  const by = name => dialog.querySelector(`[data-mc="${name}"]`);
  function render() {
    const current = active();
    const alternative = current === "plex" ? "jellyfin" : "plex";
    host.innerHTML = `<div class="mc-heading"><div><h3>Dein Mediencenter</h3><p>Royal findet, was in deiner Bibliothek schon da ist.</p></div></div>
      ${config === null ? `<p class="mc-note" role="status">${failed ? "Die bestehende Verbindung konnte nicht geladen werden. Öffne die Einstellungen erneut." : "Bestehende Verbindung wird geladen …"}</p>` : current ? `
      <div class="mc-connected">${mark(current)}<div class="mc-connected-copy"><div class="mc-name"><strong>${services[current].name}</strong><span class="mc-status">Eingerichtet</span></div><p>${esc(config.url)}</p><small>${config.user_name ? `Automatik-Profil: ${esc(config.user_name)}` : "Persönliche Profile werden im Haushalt zugeordnet."}</small></div><button type="button" class="btn btn-ghost btn-sm" data-mc-open="${current}" data-mc-edit>Verwalten</button></div>
      <div class="mc-capabilities"><span>✓ Bibliotheksabgleich</span><span>✓ Gesehen-Status</span><span>✓ Automatischer Scan</span></div>
      <div class="mc-alternative">${mark(alternative)}<div><strong>Lieber ${services[alternative].name}?</strong><p>Wechsel mit geführter Einrichtung vorbereiten.</p></div><button type="button" class="btn btn-ghost" data-mc-open="${alternative}">Zu ${services[alternative].name} wechseln</button></div>
      <p class="mc-note">Deine bestehende ${services[current].name}-Verbindung wurde erkannt. Eine erneute Einrichtung ist nicht nötig.${current === "plex" ? " Automatische Löschregeln sind für Plex gesperrt." : ""}</p>` : `
      <p class="mc-intro">Wähle deinen Server. Wir führen dich durch die Einrichtung.</p>
      <div class="mc-choices">${Object.keys(services).map(kind => `<button class="mc-choice" type="button" data-mc-open="${kind}">${mark(kind)}<strong>${services[kind].name}</strong><span>${kind === "plex" ? "Dein Plex Media Server" : "Dein eigener Jellyfin-Server"}</span><b>Einrichten <span aria-hidden="true">↗</span></b></button>`).join("")}</div>
      <p class="mc-note">Optional: Du kannst Royal auch ohne Mediencenter nutzen.</p>`}
      ${completed ? `<p class="mc-completed" role="status">✓ Mediencenter gespeichert. ${esc(completionNote || "Der Bibliotheksabgleich wird aktualisiert.")}</p>` : ""}`;
    const legacy = host.closest(".settings-group")?.querySelector(".media-center-existing");
    if (legacy) legacy.hidden = current === "plex";
  }
  function content() {
    const service = services[target], current = active();
    const headings = [current === target ? `${service.name} verwalten.` : current ? `Von ${services[current].name} zu ${service.name}.` : `Dein Zuhause für Filme und Serien.`, `Verbinde deinen ${service.name}-Server.`, "Was gehört in deine Bibliothek?", current === target ? "Auswahl speichern?" : "Alles bereit für den Wechsel?"];
    const descriptions = [current ? "Richte die Alternative in Ruhe ein. Deine aktuelle Verbindung bleibt bis zum bestätigten Wechsel aktiv." : "Einmal einrichten. Vorhandene Titel erkennen und deine Bibliothek im Blick behalten.", "Serveradresse und Zugang gehören zum Server. Dein Profil wählen wir im nächsten Schritt.", "Wähle die Bibliotheken und das Profil für den Abgleich mit Royal.", "Prüfe deine Auswahl, bevor du dein Mediencenter umstellst."];
    dialog.dataset.provider = target;
    dialog.dataset.step = String(step);
    by("title").textContent = headings[step];
    by("intro").textContent = descriptions[step];
    by("steps").innerHTML = ["Mediencenter", "Verbindung", "Bibliothek", "Abschluss"].map((label, i) => `<li class="${i === step ? "is-current" : i < step ? "is-done" : ""}" ${i === step ? 'aria-current="step"' : ""}><span>${i < step ? "✓" : i + 1}</span>${label}</li>`).join("");
    by("back").hidden = step === 0;
    by("next").textContent = ["Einrichtung starten", "Verbindung prüfen", "Auswahl prüfen", current && current !== target ? `Zu ${service.name} wechseln` : `${service.name} speichern`][step];
    by("error").textContent = "";
    if (step === 0) by("body").innerHTML = `<div class="mc-transfer">${current ? `<div>${mark(current)}<strong>${services[current].name}</strong><span>Aktuell eingerichtet</span></div><span class="mc-transfer-arrow" aria-hidden="true">→</span>` : ""}<div>${mark(target)}<strong>${service.name}</strong><span>${current ? "Dein neues Mediencenter" : "Dein gewähltes Mediencenter"}</span></div></div>
      <div class="mc-benefits"><div><span aria-hidden="true">◫</span><strong>Bibliothek erkennen</strong><p>Vorhandene Filme, Serien und Folgen beim Stöbern sehen.</p></div><div><span aria-hidden="true">▷</span><strong>Fortschritt zuordnen</strong><p>Dein Profil für persönliche Gesehen-Informationen wählen.</p></div><div><span aria-hidden="true">↻</span><strong>Bibliothek aktualisieren</strong><p>Neue Downloads an dein Mediencenter übergeben.</p></div></div>
      <div class="mc-assurance"><span aria-hidden="true">✓</span><p>${current ? "Deine Downloads, Abos und Mediendateien bleiben erhalten. Persönliche Serverprofile werden beim Wechsel neu zugeordnet." : "Du kannst die Einrichtung jederzeit abbrechen und später fortsetzen."}</p></div>`;
    if (step === 1) by("body").innerHTML = `<div class="mc-server-title">${mark(target)}<div><strong>${service.name} Media Server</strong><span>Direkte Serververbindung</span></div></div>
      <label class="mc-field" for="mc-url">Serveradresse<input id="mc-url" type="url" autocomplete="off" value="${esc(draft.url)}" placeholder="http://medienserver.local:${service.port}" aria-describedby="mc-url-help"><small id="mc-url-help">Adresse, unter der dein Royal-Server das Mediencenter erreicht.</small></label>
      <label class="mc-field" for="mc-token">${service.credential}<input id="mc-token" type="password" autocomplete="new-password" value="${esc(draft.token)}" placeholder="${service.credential}" aria-describedby="mc-token-help"><small id="mc-token-help">${service.hint}</small></label>
      <div class="mc-assurance"><span aria-hidden="true">◈</span><p>Der Zugang wird nur an deinen Royal-Server gesendet. Ein leerer Schlüssel behält beim gleichen, bereits gespeicherten Server den bisherigen Zugang bei.</p></div>`;
    if (step === 2) by("body").innerHTML = `<div class="mc-example-server">${mark(target)}<div><strong>${esc(draft.probe.server_name)}</strong><small>Server und Zugang erfolgreich geprüft</small></div><span class="mc-status">Erreichbar</span></div>
      ${target === "plex" ? `<fieldset class="mc-libraries"><legend>Bibliotheken abgleichen</legend>${draft.probe.libraries.map(library => `<label><input type="checkbox" name="mc-library" value="${esc(library.id)}" ${draft.libraries.includes(library.id) ? "checked" : ""}><span><strong>${esc(library.name)}</strong><small>${library.type === "movie" ? "Filme" : "Serien & Episoden"}</small></span></label>`).join("") || '<p class="mc-note">Noch keine Film- oder Serienbibliothek vorhanden. Lege sie zuerst in Plex an und prüfe die Verbindung anschließend erneut.</p>'}</fieldset>` : '<p class="mc-note">Alle verfügbaren Jellyfin-Bibliotheken werden abgeglichen.</p>'}
      <label class="mc-field" for="mc-profile">Profil für den Gesehen-Status<select id="mc-profile"><option value="">Später zuordnen</option>${draft.probe.users.map(user => `<option value="${esc(user.id)}" ${draft.profile === user.id ? "selected" : ""}>${esc(user.name)}</option>`).join("")}</select><small>${esc(draft.probe.profile_hint)}</small></label>`;
    if (step === 3) by("body").innerHTML = `<div class="mc-review"><div>${mark(target)}<strong>${service.name}</strong><span>Neue Auswahl</span></div><dl><div><dt>Server</dt><dd>${esc(draft.url)}</dd></div><div><dt>Bibliotheken</dt><dd>${target === "plex" ? draft.probe.libraries.filter(library => draft.libraries.includes(library.id)).map(library => esc(library.name)).join(", ") : "Alle verfügbaren Bibliotheken"}</dd></div><div><dt>Gesehen-Status</dt><dd>${esc(draft.probe.users.find(user => user.id === draft.profile)?.name || "Später zuordnen")}</dd></div></dl></div>
      <div class="mc-assurance"><span aria-hidden="true">✓</span><p>Downloads, Abos und Dateien bleiben erhalten. ${target === "plex" ? "Automatische Löschregeln bleiben für Plex gesperrt." : "Die Standard-Löschregel wird auf Behalten gesetzt."} Persönliche Profile werden im Haushalt zugeordnet.</p></div><p class="mc-review-note">Royal prüft die Verbindung beim Speichern erneut. Bei einem Fehler bleibt dein bisheriges Mediencenter aktiv.</p>`;
    if (step > 0) { by("body").focus(); by("body").scrollTop = 0; }
  }
  function close() { if (!busy || step !== 3) { operation?.abort(); dialog?.close(); } }
  function open(kind, button) {
    if (config === null) return;
    operation?.abort(); busy = false;
    for (const name of ["next", "back", "cancel", "close"]) by(name).disabled = false;
    target = kind; step = kind === active() ? 1 : 0; trigger = button;
    const stored = kind === active() ? config : config.connections?.[kind] || {};
    draft = { url: stored.url || "", token: "", libraries: [...stored.libraries || []], profile: stored.user_id || "", probe: null, generation: config.generation || 0 };
    content(); dialog.showModal(); by("next").focus();
  }
  function remember() {
    if (step === 1) { draft.url = by("body").querySelector("#mc-url").value.trim(); draft.token = by("body").querySelector("#mc-token").value; }
    if (step === 2) {
      draft.libraries = [...dialog.querySelectorAll('[name="mc-library"]:checked')].map(input => input.value);
      draft.profile = dialog.querySelector("#mc-profile").value;
    }
  }
  return {
    get: () => config,
    async initialize() {
      const current = scope;
      try {
        const value = await client.get("/api/media-center/config", { signal: current?.signal });
        if (current && !current.active) return;
        config = value; failed = false; setMediaCenter(value.provider || "jellyfin"); render();
      } catch (error) { if (!current || current.active) { failed = true; render(); } throw error; }
    },
    update(value) { config = value; failed = false; render(); },
    unavailable() { failed = true; render(); },
    mount() {
      if (scope) return;
      scope = createScope();
      dialog = host.ownerDocument.createElement("dialog");
      dialog.className = "mc-dialog";
      dialog.setAttribute("aria-labelledby", "mc-dialog-title");
      dialog.setAttribute("aria-describedby", "mc-dialog-intro");
      dialog.innerHTML = `<div class="mc-dialog-shell"><div class="mc-dialog-top"><span>Royal × Mediencenter</span><button type="button" data-mc="close" aria-label="Einrichtung schließen">×</button></div><header><h2 id="mc-dialog-title" data-mc="title"></h2><p id="mc-dialog-intro" data-mc="intro"></p></header><ol class="mc-steps" data-mc="steps" aria-label="Einrichtungsschritte"></ol><div class="mc-dialog-body" data-mc="body" tabindex="-1"></div><p class="mc-error" data-mc="error" role="alert"></p><footer><button type="button" class="btn btn-ghost" data-mc="cancel">Abbrechen</button><div><button type="button" class="btn btn-ghost" data-mc="back">Zurück</button><button type="button" class="btn mc-primary" data-mc="next">Weiter</button></div></footer></div>`;
      host.ownerDocument.body.append(dialog);
      scope.listen(host, "click", event => { const button = event.target.closest("[data-mc-open]"); if (button) open(button.dataset.mcOpen, button); });
      scope.listen(by("close"), "click", close); scope.listen(by("cancel"), "click", close);
      scope.listen(dialog, "cancel", event => { if (busy && step === 3) event.preventDefault(); else operation?.abort(); });
      scope.listen(dialog, "close", () => { if (dialog.open) return; operation?.abort(); draft = null; by("body").innerHTML = ""; if (trigger?.isConnected) trigger.focus(); });
      scope.listen(by("back"), "click", () => { remember(); step--; content(); });
      scope.listen(by("next"), "click", async () => {
        if (busy) return;
        remember();
        if (step === 1) {
          try { const url = new URL(draft.url); if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error(); }
          catch { by("error").textContent = "Gib eine gültige Serveradresse mit http:// oder https:// ohne Zugangsdaten ein."; dialog.querySelector("#mc-url").focus(); return; }
        }
        if (step === 2 && target === "plex" && !draft.libraries.length) { by("error").textContent = "Wähle mindestens eine Bibliothek für den Abgleich."; return; }
        if (step === 1 || step === 3) {
          busy = true; operation = new AbortController();
          const current = scope, currentDialog = dialog, currentDraft = draft;
          by("next").disabled = true; by("back").disabled = true;
          by("next").textContent = step === 1 ? "Prüfe Verbindung …" : "Speichere …";
          if (step === 3) { by("cancel").disabled = true; by("close").disabled = true; }
          try {
            const value = await client.post(`/api/media-center/${step === 1 ? "probe" : "activate"}`, {
              provider: target, url: draft.url, api_key: draft.token,
              libraries: draft.libraries, user_id: draft.profile, server_id: step === 3 ? draft.probe.server_id : "",
              expected_generation: draft.generation,
            }, { signal: operation.signal });
            if (!current.active || !currentDialog.open || draft !== currentDraft) return;
            if (step === 3) {
              config = value; completed = true; completionNote = (value.warnings || []).join(" "); setMediaCenter(value.provider); busy = false;
              dialog.close(); render();
              host.querySelector("[data-mc-edit]")?.focus();
              host.ownerDocument.dispatchEvent(new CustomEvent("royal:media-center-changed", { detail: value }));
              void onActivated().catch(error => { if (current.active) { failed = true; render(); console.warn("Mediencenter wurde gespeichert; Ansicht konnte nicht aktualisiert werden:", error); } });
              return;
            }
            draft.probe = value;
            draft.libraries = value.libraries.filter(library => draft.libraries.includes(library.id)).map(library => library.id);
            if (!draft.libraries.length) draft.libraries = value.libraries.map(library => library.id);
            if (!value.users.some(user => user.id === draft.profile)) draft.profile = value.users[0]?.id || "";
          } catch (error) {
            if (current.active && currentDialog.open && draft === currentDraft && error.name !== "AbortError") by("error").textContent = error.message;
            return;
          } finally {
            if (!draft || draft === currentDraft) busy = false;
            if (current.active && dialog && draft === currentDraft) {
              by("next").disabled = false; by("back").disabled = false; by("cancel").disabled = false; by("close").disabled = false;
              by("next").textContent = step === 1 ? "Verbindung prüfen" : "Erneut speichern";
            }
          }
        }
        step++; content();
      });
      render();
    },
    unmount() { operation?.abort(); scope?.dispose(); scope = null; dialog?.close(); dialog?.remove(); dialog = null; draft = null; busy = false; },
  };
}
