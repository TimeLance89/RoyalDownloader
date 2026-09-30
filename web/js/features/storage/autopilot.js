import { createScope } from "../../core/lifecycle.js";
import { createStorageApi } from "./api.js";
import { installAutopilotUi } from "./autopilot-layout.js";
import { escapeHtml as html } from "../../shared/utils/escape-html.js";
import { formatBytes } from "../../shared/formatters/bytes.js";
import { isAbortError } from "../../core/errors.js";

const roles = { primary: "Primärspeicher", overflow: "Ausweichspeicher", archive: "Archiv", monitor: "Nur überwachen" };
const media = { movies: "Filme", series: "Serien", anime: "Anime" };
const fields = ["window_start", "window_end", "window_enabled", "interval_hours", "cooldown_hours", "max_moves", "max_move_gib", "unknown_download_gib", "archive_age_days", "allow_series_split"];
const flags = new Set(["window_enabled", "allow_series_split"]);
const pressureLabels = { normal: "Alles in Ordnung", warning: "Speicher wird knapp", critical: "Speicherreserve gefährdet", emergency: "Kein sicherer Speicher verfügbar", offline: "Ein Speicherort ist offline" };

export function createStorageAutopilot(root) {
  installAutopilotUi(root);
  const find = id => root.querySelector(`#${id}`);
  let scope, value, pending, dirty = false, busy = false, lastRefresh = 0, renderedVolumes = "", renderedRecommendations = "";
  const status = copy => { find("storage-autopilot-status").textContent = copy; };
  function render() {
    if (!value?.policy || !Array.isArray(value.roots)) throw new Error("Speicherinformationen unvollständig");
    const section = find("storage-autopilot");
    section.dataset.pressure = value.storage_error ? "critical" : value.pressure;
    find("storage-autopilot-health").textContent = value.storage_error ? "Autopilot-Daten prüfen" : pressureLabels[value.pressure] || "Verfügbarkeit wird geprüft";
    const recommendations = (value.recommendations || []).filter(item => item.state === "available");
    find("storage-autopilot-capacity").textContent = `${value.summary?.volume_count || 0} erreichbare Volumes · ${formatBytes(value.summary?.free_bytes || 0)} frei · ${formatBytes(value.summary?.total_bytes || 0)} gesamt`;
    find("storage-placement-advice").innerHTML = (value.placement_advice || []).map(item => {
      const target = value.roots.find(root => root.key === item.destination_root);
      return `<article class="storage-recommendation"><strong>${html(item.name)}</strong><p>Für diesen geplanten Download eignet sich ${html(target?.label || item.destination_root)} besser (${formatBytes(item.size_bytes)} eingeplant).</p><ul>${item.reasons.map(reason => `<li>${html(reason)}</li>`).join("")}</ul><small>Beraten verändert das Downloadziel nicht. Für automatische Platzierung wähle Automatisch.</small></article>`;
    }).join("");
    find("storage-autopilot-impact").textContent = value.storage_error ? "Automatische Aktionen sind gesperrt. Deine vorhandenen Dateien bleiben erhalten." : value.pressure === "normal" ? "Keine Einschränkungen erkannt. Royal hält die Sicherheitsreserve im Blick." : recommendations.length ? `Royal hat ${recommendations.length} sichere Vorschläge zur Entlastung. Dateien werden vor jeder Aktion erneut geprüft.` : "Prüfe freie Kapazität und erreichbare Medien-Volumes. Royal mountet keine Laufwerke selbst.";
    if (!dirty) {
      for (const radio of root.querySelectorAll('[name="storage-autonomy"]')) radio.checked = radio.value === value.policy.mode;
      for (const field of fields) {
        const control = root.querySelector(`#storage-autopilot-form [name="${field}"]`);
        if (flags.has(field)) control.checked = Boolean(value.policy[field]);
        else control.value = value.policy[field];
      }
    }
    find("storage-auto-delete").checked = Boolean(value.policy.auto_delete);
    const volumes = JSON.stringify(value.roots.map(item => [item.key, item.label, item.available, item.policy, item.last_seen_at]));
    if (volumes !== renderedVolumes && !find("storage-volume-policy-list").contains(root.ownerDocument.activeElement)) {
      find("storage-volume-policy-list").innerHTML = value.roots.map(volumeForm).join("");
      renderedVolumes = volumes;
    }
    const proposalSnapshot = JSON.stringify(recommendations);
    if (proposalSnapshot !== renderedRecommendations) {
      find("storage-recommendations").innerHTML = recommendations.length ? recommendations.map(item => {
        const target = value.roots.find(root => root.key === item.destination_root);
        return `<article class="storage-recommendation"><strong>${html(item.name)}</strong><p>${html(item.reason)}. ${formatBytes(item.size_bytes)} nach ${html(target?.label || item.destination_root)}.</p><p>Quelle: ${item.before_percent} % → ${item.after_percent} % · Ziel danach: ${item.expected_target_percent} %</p><ul>${item.reasons.map(reason => `<li>${html(reason)}</li>`).join("")}</ul><button class="btn btn-primary btn-sm" type="button" data-autopilot-action="apply" data-id="${html(item.id)}">Jetzt verschieben</button><button class="btn btn-ghost btn-sm" type="button" data-autopilot-action="dismiss" data-id="${html(item.id)}">Ignorieren</button></article>`;
      }).join("") : "Keine sichere Verschiebung empfohlen. Eine bewusste Speicheranalyse aktualisiert das Inventar.";
      renderedRecommendations = proposalSnapshot;
    }
    const actions = { placement: "Downloadziel gewählt", download_completed: "Download abgeschlossen", move_planned: "Verschiebung geplant", move_finished: "Verschiebung beendet", policy_changed: "Autopilot-Regeln gespeichert", volume_policy_changed: "Volume-Regeln gespeichert", recommendation_dismissed: "Empfehlung ignoriert", artifacts_cleaned: "Royal-Downloadreste bereinigt" };
    find("storage-autopilot-activity-list").innerHTML = (value.activity || []).slice(0, 30).map(item => `<li><time>${html(new Date(item.timestamp * 1000).toLocaleString("de-DE"))}</time><strong>${html(actions[item.action] || "Speicheraktion")}</strong>${item.destination ? `<span>${html(item.destination)}</span>` : ""}${item.reason ? `<small>${html(item.reason)}</small>` : ""}</li>`).join("") || "Noch keine automatischen Speicheraktionen.";
    find("storage-autopilot-schedule").textContent = `Planungsintervall: ${value.policy.interval_hours} Std. · Zeitfenster: ${value.policy.window_enabled ? `${value.policy.window_start}–${value.policy.window_end}` : "jederzeit"}. Aktive Verschiebungen: ${value.active_moves}.`;
  }
  function volumeForm(volume) {
    const policy = volume.policy;
    const customLocation = Boolean(volume.location_id);
    const mediaControl = customLocation
      ? `<div class="storage-policy-media-readonly"><span>Erlaubte Inhalte</span><strong>${policy.media_types.map((kind) => media[kind]).filter(Boolean).join(" · ")}</strong><small>Änderbar oben bei „Zusätzliche Speicherorte“.</small></div>${policy.media_types.map((kind) => `<input type="hidden" name="media_types" value="${html(kind)}">`).join("")}`
      : `<fieldset><legend>Medienarten</legend>${Object.entries(media).map(([key, label]) => `<label><input type="checkbox" name="media_types" value="${key}" ${policy.media_types.includes(key) ? "checked" : ""}>${label}</label>`).join("")}</fieldset>`;
    return `<form class="storage-volume-policy" data-volume-root="${html(volume.key)}"><h4>${html(volume.label)}</h4><p>${volume.available ? "Volume verfügbar" : "Offline – Royal führt keine Aktionen aus"}${volume.last_seen_at ? ` · Letzter Kontakt: ${html(new Date(volume.last_seen_at * 1000).toLocaleString("de-DE"))}` : ""}</p><div class="storage-policy-grid">
      <label><span>Rolle</span><select name="role">${Object.entries(roles).map(([key, label]) => `<option value="${key}" ${policy.role === key ? "selected" : ""}>${label}</option>`).join("")}</select></label>
      ${mediaControl}
      ${["target_percent", "warning_percent", "critical_percent", "reserve_gib"].map((key, index) => `<label><span>${["Zielauslastung (%)", "Warnschwelle (%)", "Kritische Schwelle (%)", "Mindestreserve (GiB)"][index]}</span><input type="number" name="${key}" min="1" max="${key === "reserve_gib" ? 4096 : 99}" value="${policy[key]}" required></label>`).join("")}
      <label><input type="checkbox" name="allow_moves_in" ${policy.allow_moves_in ? "checked" : ""}>Automatisch hierhin verschieben</label><label><input type="checkbox" name="allow_moves_out" ${policy.allow_moves_out ? "checked" : ""}>Automatisch von hier weg verschieben</label></div>
      <button class="btn btn-ghost btn-sm" type="submit">Erweiterte Regeln speichern</button>${!volume.available ? `<button class="btn btn-ghost btn-sm" type="button" data-autopilot-action="mount" data-root="${html(volume.key)}">Mount erneut prüfen und bestätigen</button>` : ""}</form>`;
  }
  async function refresh(force = false, afterMutation = false) {
    if (!scope?.active) return;
    const current = scope;
    if (pending) { await pending; if (!afterMutation || !current.active) return; }
    if (!force && Date.now() - lastRefresh < 15000) return;
    const request = (async () => { try {
      const result = await createStorageApi(current).get("/api/storage/autopilot");
      if (!current.active) return;
      value = result; render(); lastRefresh = Date.now();
    } catch (error) { if (current.active && !isAbortError(error)) status("Speicher-Autopilot ist vorübergehend nicht erreichbar. Bitte erneut versuchen."); }
    finally { if (current.active) pending = null; } })();
    pending = request;
    await request;
  }
  async function run(operation) {
    if (!scope?.active || busy) return;
    const current = scope; busy = true;
    find("storage-autopilot").setAttribute("aria-busy", "true");
    try { const message = await operation(createStorageApi(current)); if (current.active) { dirty = false; status(typeof message === "string" ? message : "Speicherregeln übernommen."); await refresh(true, true); } }
    catch (error) { if (current.active && !isAbortError(error)) status("Aktion nicht übernommen. Prüfe Speicherverfügbarkeit und freigegebene Regeln."); }
    finally { if (current.active) { busy = false; find("storage-autopilot").setAttribute("aria-busy", "false"); } }
  }
  function save(event) {
    const form = event.target.closest("form");
    if (!form || !find("storage-autopilot").contains(form)) return;
    event.preventDefault();
    const data = new FormData(form);
    if (form.id === "storage-autopilot-form") {
      const policy = { mode: data.get("storage-autonomy") };
      for (const field of fields) policy[field] = flags.has(field) ? data.has(field) : field.startsWith("window_") ? data.get(field) : Number(data.get(field));
      void run(api => api.put("/api/storage/autopilot", { policy }));
    } else if (form.dataset.volumeRoot) {
      const policy = { role: data.get("role"), media_types: data.getAll("media_types"), allow_moves_in: data.has("allow_moves_in"), allow_moves_out: data.has("allow_moves_out") };
      for (const key of ["target_percent", "warning_percent", "critical_percent", "reserve_gib"]) policy[key] = Number(data.get(key));
      void run(api => api.put("/api/storage/autopilot/volume", { root: form.dataset.volumeRoot, policy }));
    }
  }
  function action(event) {
    const button = event.target.closest("[data-autopilot-action]");
    if (!button) return;
    const name = button.dataset.autopilotAction;
    if (name === "cancel-delete") { find("storage-cleanup-preview").hidden = true; return; }
    if (name === "apply" && !window.confirm("Diesen Inhalt sicher auf das vorgeschlagene Volume verschieben? Die Quelle wird erst nach vollständiger Zielprüfung entfernt.")) return;
    if (name === "mount" && !window.confirm("Ist der richtige Datenträger unter diesem Mount eingebunden? Seine aktuelle Identität wird bestätigt.")) return;
    void run(async api => {
      if (["apply", "dismiss"].includes(name)) {
        await api.post(`/api/storage/recommendations/${encodeURIComponent(button.dataset.id)}/${name}`, { confirm: true });
        return name === "apply" ? "Sichere Verschiebung wurde geplant." : "Empfehlung während der Ruhezeit ausgeblendet.";
      }
      else if (name === "recommend") await api.get("/api/storage/recommendations");
      else if (name === "mount") await api.put("/api/storage/autopilot/volume", { root: button.dataset.root, policy: {}, confirm_mount: true });
      else if (name === "confirm-delete") { await api.put("/api/storage/autopilot", { policy: { auto_delete: true, delete_categories: ["royal_partials"] }, delete_confirmed: true }); find("storage-cleanup-preview").hidden = true; }
      else if (name === "optimize") { const result = await api.post("/api/storage/optimize", {}); return result.started ? "Sichere Verschiebung wurde geplant." : result.reason || "Keine sichere automatische Aktion nötig."; }
    });
  }
  async function deletePermission() {
    if (!scope?.active || busy) return;
    if (!find("storage-auto-delete").checked) { void run(api => api.put("/api/storage/autopilot", { policy: { auto_delete: false } })); return; }
    find("storage-auto-delete").checked = false;
    const current = scope;
    try {
      const preview = await createStorageApi(current).get("/api/storage/cleanup/preview");
      if (!current.active) return;
      find("storage-cleanup-preview-copy").textContent = `${preview.description} Aktuell ${preview.candidates.length} geeignete Restverzeichnisse (${formatBytes(preview.size_bytes)}). Die Freigabe gilt auch für künftig entsprechend erkannte Reste.`;
      find("storage-cleanup-preview").hidden = false;
    } catch (error) { if (current.active && !isAbortError(error)) status("Bereinigungsvorschau nicht verfügbar. Löschfreigabe bleibt unverändert."); }
  }
  return {
    mount() {
      if (scope?.active) return;
      scope = createScope(); lastRefresh = 0;
      scope.listen(find("storage-autopilot"), "submit", save);
      scope.listen(find("storage-autopilot"), "input", event => { if (event.target.id !== "storage-auto-delete") dirty = true; });
      scope.listen(find("storage-autopilot"), "click", action);
      scope.listen(find("storage-auto-delete"), "change", deletePermission);
      void refresh(true);
    }, refresh, snapshot: () => value,
    unmount() { scope?.dispose(); scope = null; pending = false; busy = false; dirty = false; },
  };
}
