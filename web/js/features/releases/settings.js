import { createScope, delay } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";

export function createReleaseSettings({ request, t, regionNames, onData }) {
  let scope, config, onClick;
  let settings;
  function install(grid) {
    if(!grid)return;
    settings=document.createElement("div"); settings.id="release-settings";settings.className="settings-group settings-card";
    settings.innerHTML=`<h3>${t("Film- & Serien-Releases", "Movie & series releases")}</h3><p>${t("Kostenloser Direktzugang von Movie of the Night. Wähle beim Anbieter den Free-Tarif ohne Zahlungsdaten.", "Free direct access from Movie of the Night. Choose the provider’s Free plan without payment details.")}</p>
      <a href="https://developers.movieofthenight.com/" target="_blank" rel="noopener noreferrer">${t("Kostenlosen API-Key erstellen", "Get a free API key")}</a>
      <label for="releases-key">API-Key</label><input id="releases-key" type="password" autocomplete="off" placeholder="${t("API-Key eingeben", "Enter API key")}">
      <label for="releases-region">${t("Release-Region", "Release region")}</label><select id="releases-region">${Object.entries(regionNames).map(([id,name])=>`<option value="${id}">${name}</option>`).join("")}</select>
      <div class="release-settings-actions"><button type="button" id="releases-save" class="btn btn-primary">${t("Speichern & Verbindung prüfen", "Save & test connection")}</button><button type="button" id="releases-remove" class="btn btn-ghost">${t("Key entfernen", "Remove key")}</button></div>
      <p id="releases-config-status" role="status"></p><small>${t("Täglicher Abgleich. Maximal 900 Abrufe in 31 Tagen. Kein kostenpflichtiger Fallback.", "Daily sync. Up to 900 requests in 31 days. No paid fallback.")}</small>`;
    grid.append(settings);
    const status=settings.querySelector("#releases-config-status");
    config = async function(current = scope) {
      try {
        const cfg = await request("/api/releases/config", { signal: current.signal });
        if (!current.active) return;
        settings.querySelector("#releases-region").value = cfg.region;
        settings.querySelector("#releases-key").placeholder = cfg.has_api_key
          ? t("Gespeichert — leer lassen zum Beibehalten", "Saved — leave blank to keep") : "API-Key";
      } catch (error) {
        if (current.active && !isAbortError(error)) {
          status.textContent = t("Einstellungen konnten nicht geladen werden.", "Unable to load settings.");
        }
      }
    };
    onClick = async event=>{
      const current = scope;
      const scopedRequest = (path, options = {}) => request(path, { ...options, signal: current.signal });
      if(!["releases-save","releases-remove"].includes(event.target.id))return;
      const button=event.target;button.disabled=true;
      try {
        await scopedRequest("/api/releases/config", {method:"POST", body:{
          api_key:settings.querySelector("#releases-key").value,
          region:settings.querySelector("#releases-region").value,
          remove_key:button.id === "releases-remove"
        }});
        if (!current.active) return;
        settings.querySelector("#releases-key").value="";
        await config(current);
        if (!current.active) return;
        let result=await scopedRequest("/api/releases/test", {method:"POST"});
        if (!current.active) return;
        const deadline=Date.now()+180000;
        status.textContent=t("Gespeichert. Verbindung wird geprüft …", "Saved. Testing connection …");
        while(result.loading && Date.now()<deadline) {
          await delay(3000, current.signal);
          result=await scopedRequest("/api/releases");
        }
        if (!current.active) return;
        status.textContent=!result.configured ? t("API-Key entfernt.", "API key removed.")
          : result.loading ? t("Abgleich dauert länger. Ergebnis später unter Releases prüfen.", "Sync is taking longer. Check Releases later.")
          : result.error ? t("Verbindung fehlgeschlagen. API-Key und Gratis-Kontingent prüfen. Erneuter Test nach fünf Minuten möglich.", "Connection failed. Check your API key and free quota. Retry after five minutes.")
          : t("Verbindung bestätigt. Termine gespeichert. Täglicher Abgleich aktiv.", "Connection confirmed. Dates saved. Daily sync enabled.");
        if (current.active) onData(result);
      } catch(error) {
        if (!current.active || isAbortError(error)) return;
        status.textContent=t("Speichern oder Verbindungsprüfung fehlgeschlagen.", "Saving or testing the connection failed.");
      } finally { if (current.active) button.disabled = false; }
    };
  }
  return {
    mount(root) {
      if (scope) return;
      scope = createScope();
      if (!settings) install(root.querySelector(".settings-service-grid"));
      if (!settings) return;
      scope.listen(settings, "click", onClick);
      void config();
    },
    refresh() { return scope && config?.(); },
    unmount() {
      scope?.dispose(); scope = null;
      settings?.querySelectorAll("button").forEach(button => { button.disabled = false; });
    },
  };
}
