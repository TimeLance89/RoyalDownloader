import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { escapeHtml } from "../../shared/utils/escape-html.js";
import { websocket } from "../../core/websocket.js";

const labels = { offline: "Nicht erreichbar", repairing: "Reparatur läuft", changed: "Verändert", healthy: "Gesund", degraded: "Eingeschränkt", broken: "Defekt", blocked: "Verifikation erforderlich", unknown: "Noch nicht geprüft", needs_attention: "Manuelle Prüfung nötig", repair_available: "Reparatur verfügbar", cooldown: "Cooldown", probing: "Prüfung läuft" };
const steps = { reachability: "Erreichbarkeit", embed: "Embed", redirect: "Weiterleitung", player: "Player", resolver: "Resolver", media_result: "Medienquelle", connectivity: "Erreichbarkeit", catalog: "Katalog", search: "Suche", detail: "Details", metadata: "Metadaten", hoster_structure: "Hosterstruktur", source_structure: "Quellstruktur", episode_detail: "Episodendetails" };
const reasons = { browser_fallback_required: "HTTP-Pfad nicht bestätigt · Browser-Fallback nicht aktiv geprüft", runtime_validation_required: "HTTP-Probe unvollständig · Produktionspfad benötigt Runtime-Evidenz", metadata_changed: "Metadaten verändert", invalid_reference: "Ungültige Medienreferenzen", response_too_large: "Antwort überschreitet Prüfbudget", http_error: "HTTP-Fehler", internal_probe_error: "Interner Prüffehler", ok: "Bestanden", empty_extraction: "Keine Ergebnisse erkannt", removed: "Referenztitel entfernt", identity_mismatch: "Identität nicht bestätigt", missing_hosters: "Keine Hoster erkannt", missing_links: "Keine Quellen erkannt", verification_required: "Benutzer-Verifikation erforderlich", rate_limit: "Rate-Limit", network_error: "Netzwerkfehler", temporary_http: "Temporärer HTTP-Fehler", budget_exhausted: "Prüfbudget erreicht", full_probe_required: "Nur im vollständigen Test", links_only: "Linkstruktur geprüft; kein Download", parser_error: "Parserfehler" };
const date = value => value ? new Date(value * 1000).toLocaleString() : "—";

export function createProviderMonitor(root, { client = api, events = websocket } = {}) {
  let scope, pending, value, dirty = false, tab = "providers";
  const status = () => root.querySelector('[data-monitor="status"]');
  function render() {
    if (!value) return;
    if (!dirty) {
      root.querySelector('[name="monitor-enabled"]').checked = value.config.enabled;
      root.querySelector('[name="monitor-auto-repair"]').checked = value.config.auto_repair;
      root.querySelector('[name="monitor-notify"]').checked = value.config.notify_changes;
      root.querySelector('[name="monitor-interval"]').value = value.config.interval_hours;
      root.querySelector('[name="monitor-intensity"]').value = value.config.intensity;
    }
    root.querySelector('[data-monitor="summary"]').textContent = `${value.providers.filter(p => p.enabled).length} aktive Quellen · ${Object.entries(value.summary).filter(([, count]) => count).map(([state, count]) => `${count} ${labels[state] || state}`).join(" · ")} · Hoster: ${Object.entries(value.hoster_summary || {}).filter(([, count]) => count).map(([state, count]) => `${count} ${labels[state] || state}`).join(" · ") || "Noch keine Diagnose"} · Letzte Komplettprüfung: ${date(value.last_complete_check_at)} · Nächste Prüfung: ${value.config.enabled ? date(value.next_check_at) : "Pausiert"}`;
    const list = root.querySelector('[data-monitor="providers"]');
    const opened = new Set([...list.querySelectorAll("details[open]")].map(node => node.dataset.panel || node.dataset.provider));
    list.innerHTML = value.providers.map(provider => {
      const esc = escapeHtml, id = esc(provider.provider);
      const repair = provider.repairs.find(item => item.id === provider.active_repair);
      return `<details data-provider="${id}" ${opened.has(provider.provider) ? "open" : ""}>
        <summary><strong>${esc(provider.label)}</strong> · ${provider.enabled ? labels[provider.diagnosis] || esc(provider.diagnosis) : "Pausiert"}${provider.running ? " · Prüfung läuft" : ""}${repair ? " · Reparatur aktiv" : ""}</summary>
        <p class="dim">${esc(provider.domain)} · ${esc(provider.contract.media_types.join(", "))} · Runtime: ${esc(labels[provider.runtime.state] || provider.runtime.state)}<br>Priorität: ${Object.entries(provider.priority || {}).map(([media, rank]) => `${esc(media)} ${rank}`).join(" · ") || "—"}<br>Letzter Prüfungsfehler: ${esc(reasons[provider.last_error] || provider.last_error || "—")}</p>
        <p>Letzte Prüfung: ${date(provider.last_check_at)} · Nächste Prüfung: ${provider.enabled && value.config.enabled ? date(provider.next_check_at) : "Automatisch pausiert"}<br>Letzter Erfolg: ${date(provider.last_success_at)}<br>Fehlerquote der Prüfungen (24 h): ${provider.error_rate_24h === null ? "—" : `${Math.round(provider.error_rate_24h * 100)} %`} · Durchschnittliche Prüfdauer: ${provider.average_duration_ms ?? "—"} ms</p>
        <div class="table-scroll"><table><thead><tr><th>Test</th><th>Ergebnis</th><th>Zeit</th></tr></thead><tbody>${provider.steps.map(step => `<tr><td>${esc(steps[step.name] || step.name)}${step.sample && !["movies", "series", "anime"].includes(step.sample) ? ` · ${esc(step.sample.slice(0, 6))}` : ""}</td><td>${step.ok === null ? "—" : step.ok ? "✓" : "✕"} ${esc(reasons[step.code] || step.code)}${step.http_status ? ` (HTTP ${step.http_status})` : ""}</td><td>${step.duration_ms} ms</td></tr>`).join("")}</tbody></table></div>
        ${provider.changed ? '<p>Strukturänderung erkannt. Details stehen im Prüfverlauf.</p>' : ""}
        <p>${provider.hosters.map(hoster => `${esc(hoster.name)}: ${esc(labels[hoster.state] || hoster.state)}`).join(" · ")}</p>
        <button type="button" class="btn-ghost" data-action="probe" data-provider="${id}" ${provider.running ? "disabled" : ""}>Jetzt prüfen</button>
        <button type="button" class="btn-ghost" data-action="full" data-provider="${id}" ${provider.running ? "disabled" : ""}>Vollständigen Test starten</button>
        <details data-panel="${id}-repairs" ${opened.has(`${provider.provider}-repairs`) ? "open" : ""}><summary>Reparaturen (${provider.repairs.length})</summary>${provider.repairs.map(item => `<article><p>Repair ${esc(item.id.slice(0, 8))} · ${esc(item.state)} · Sicherheit: ${esc(item.confidence)}<br>Validierung: ${item.validation.validated_detail_pages}/${item.validation.known_detail_pages} unabhängige bekannte Titel</p><div class="table-scroll"><pre>${esc(JSON.stringify({ vorher: item.previous_profile, nachher: item.profile }, null, 2))}</pre></div>${item.id === provider.active_repair ? `<button type="button" class="btn-ghost" data-action="rollback" data-provider="${id}" data-repair="${esc(item.id)}">Reparatur zurücksetzen</button>` : item.state === "available" && item.confidence === "high" ? `<button type="button" class="btn-ghost" data-action="activate" data-provider="${id}" data-repair="${esc(item.id)}">Erneut validieren und aktivieren</button>` : ""}</article>`).join("")}</details>
        <details data-panel="${id}-history" ${opened.has(`${provider.provider}-history`) ? "open" : ""}><summary>Verlauf (${provider.history.length})</summary><ul>${provider.history.slice().reverse().map(event => `<li>${date(event.timestamp)} · ${esc(event.event)} · ${esc(labels[event.diagnosis] || event.reason || "")}${event.changed ? " · Strukturänderung" : ""}${event.isolated ? " · temporär isoliert" : ""}</li>`).join("")}</ul></details>
      </details>`;
    }).join("");
  }
  function renderHosters() {
    const list = root.querySelector('[data-monitor="hosters"]');
    if (!list) return;
    const opened = new Set([...list.querySelectorAll("details[open]")].map(node => node.dataset.panel));
    const esc = escapeHtml;
    list.innerHTML = (value.hosters || []).map(hoster => {
      const id = esc(hoster.hoster), panel = `hoster-${hoster.hoster}`;
      const metric = hoster.metrics_24h;
      return `<details data-panel="${esc(panel)}" ${opened.has(panel) ? "open" : ""}><summary><strong>${esc(hoster.label)}</strong> · ${esc(labels[hoster.diagnosis] || hoster.diagnosis)}${hoster.active_repair ? " · Reparatur aktiv" : ""}</summary>
        <p>Domains: ${hoster.domains.map(esc).join(", ") || "Noch keine beobachtet"}<br>Resolver: ${esc(hoster.contract.resolver)}${hoster.contract.browser_fallback ? " · Browser-Fallback vorhanden (nicht aktiv geprüft)" : hoster.contract.probe_mode === "runtime_only" ? " · Produktionspfad nicht vollständig aktiv geprüft" : ""}<br>Provider: ${hoster.providers.map(esc).join(", ") || "—"}<br>Fähigkeiten: ${hoster.contract.capabilities.map(esc).join(", ")}</p>
        <p>24 h: ${metric.attempts} Versuche · Erfolg ${metric.success_rate === null ? "—" : `${Math.round(metric.success_rate * 100)} %`} · Median ${metric.median_resolve_ms ?? "—"} ms<br>7 Tage: ${hoster.metrics_7d.attempts} Versuche · Erfolg ${hoster.metrics_7d.success_rate === null ? "—" : `${Math.round(hoster.metrics_7d.success_rate * 100)} %`}<br>Letzter Erfolg: ${date(hoster.last_success_at)} · Letzter Fehler: ${date(hoster.last_failure_at)}<br>Letzte Prüfung: ${date(hoster.last_check_at)} · Nächste Prüfung: ${date(hoster.next_check_at)}</p>
        <div class="table-scroll"><table><thead><tr><th>Test</th><th>Ergebnis</th><th>Zeit</th></tr></thead><tbody>${hoster.steps.map(step => `<tr><td>${esc(steps[step.name] || step.name)}</td><td>${["browser_fallback_required", "runtime_validation_required"].includes(step.code) ? "⚠" : step.ok === null ? "—" : step.ok ? "✓" : "✕"} ${esc(reasons[step.code] || step.code)}</td><td>${step.duration_ms ? `${step.duration_ms} ms` : "—"}</td></tr>`).join("")}</tbody></table></div>
        <button type="button" class="btn-ghost" data-kind="hoster" data-provider="${id}" data-action="probe" ${hoster.running ? "disabled" : ""}>Jetzt prüfen</button><button type="button" class="btn-ghost" data-kind="hoster" data-provider="${id}" data-action="full" ${hoster.running ? "disabled" : ""}>Vollständigen Test starten</button>
        <details data-panel="${esc(panel)}-repairs" ${opened.has(`${panel}-repairs`) ? "open" : ""}><summary>Reparaturen (${hoster.repairs.length})</summary>${hoster.repairs.map(item => `<article><p>Repair ${esc(item.id.slice(0, 8))} · ${esc(item.state)} · ${esc(item.confidence)} · Shadow ${item.validation.validated_detail_pages}/${item.validation.known_detail_pages}</p><div class="table-scroll"><pre>${esc(JSON.stringify({ vorher: item.previous_profile, nachher: item.profile }, null, 2))}</pre></div><button type="button" class="btn-ghost" data-kind="hoster" data-provider="${id}" data-repair="${esc(item.id)}" data-action="${hoster.active_repair === item.id ? "rollback" : "activate"}">${hoster.active_repair === item.id ? "Reparatur zurücksetzen" : "Erneut validieren und aktivieren"}</button></article>`).join("")}</details>
        <details data-panel="${esc(panel)}-history" ${opened.has(`${panel}-history`) ? "open" : ""}><summary>Verlauf</summary><ul>${hoster.history.slice().reverse().map(event => `<li>${date(event.timestamp)} · ${esc(event.event)} · ${esc(event.reason || event.diagnosis || "")}</li>`).join("")}</ul></details></details>`;
    }).join("");
    const history = root.querySelector('[data-monitor="history"]');
    if (history) history.innerHTML = [...value.providers, ...(value.hosters || [])].map(source => `<details><summary>${esc(source.label)} · ${source.repairs.length} Reparaturen</summary><ul>${source.history.slice().reverse().map(event => `<li>${date(event.timestamp)} · ${esc(event.event)} · ${esc(event.reason || event.diagnosis || "")}</li>`).join("")}</ul></details>`).join("");
    for (const name of ["providers", "hosters", "history"]) root.querySelector(`[data-monitor="${name}"]`).hidden = name !== tab;
    for (const button of root.querySelectorAll('[data-action="tab"]')) button.setAttribute("aria-pressed", String(button.dataset.tab === tab));
  }
  async function refresh() {
    if (!scope?.active || pending) return;
    const current = scope;
    pending = true;
    try {
      const result = await client.get("/api/providers/diagnostics", { signal: current.signal });
      if (!current.active) return;
      if (!result?.config || !Array.isArray(result.providers)) throw new Error("Provider-Diagnosen sind derzeit nicht verfügbar.");
      value = result; render(); renderHosters(); status().textContent = "";
    } catch (error) {
      if (current.active) status().textContent = error.status === 403 ? "Provider-Überwachung ist nur für Administratoren verfügbar." : error.message;
    } finally { if (current.active) pending = false; }
  }
  async function action(event) {
    const button = event.target.closest("button[data-action]");
    if (!button || !scope?.active) return;
    const current = scope;
    const { action: name, provider, repair, kind } = button.dataset;
    if (name === "tab") { tab = button.dataset.tab; renderHosters(); return; }
    const sourcePath = kind === "hoster" ? "hosters" : "providers";
    if (["rollback", "activate"].includes(name)) {
      const confirmation = root.querySelector('[data-monitor="confirmation"]');
      confirmation.hidden = false;
      confirmation.querySelector("p").textContent = name === "rollback" ? "Aktive Reparatur zurücksetzen und das vorherige Profil wiederherstellen?" : "Reparatur erneut vollständig validieren und bei Erfolg aktivieren?";
      const confirm = confirmation.querySelector('[data-action="confirm"]');
      Object.assign(confirm.dataset, { operation: name, provider, repair, kind: kind || "provider" });
      confirm.focus(); return;
    }
    if (name === "cancel") { root.querySelector('[data-monitor="confirmation"]').hidden = true; return; }
    button.disabled = true;
    try {
      if (name === "save") {
        await client.put("/api/providers/monitor/config", {
          enabled: root.querySelector('[name="monitor-enabled"]').checked,
          auto_repair: root.querySelector('[name="monitor-auto-repair"]').checked,
          notify_changes: root.querySelector('[name="monitor-notify"]').checked,
          interval_hours: Number(root.querySelector('[name="monitor-interval"]').value),
          intensity: root.querySelector('[name="monitor-intensity"]').value,
        }, { signal: current.signal });
        dirty = false;
      } else if (name === "all") {
        await client.post("/api/providers/probe-all", { intensity: root.querySelector('[name="monitor-intensity"]').value }, { signal: current.signal });
      } else if (name === "confirm") {
        await client.post(`/api/${sourcePath}/${encodeURIComponent(provider)}/repairs/${encodeURIComponent(repair)}/${button.dataset.operation}`, { confirmed: true }, { signal: current.signal });
        if (current.active) root.querySelector('[data-monitor="confirmation"]').hidden = true;
      } else {
        await client.post(`/api/${sourcePath}/${encodeURIComponent(provider)}/probe`, { intensity: name === "full" ? "full" : "standard" }, { signal: current.signal });
      }
      if (current.active) { status().textContent = "Übernommen. Prüfungen werden mit begrenztem Budget ausgeführt."; await refresh(); }
    } catch (error) { if (current.active) status().textContent = error.message; }
    finally { if (current.active) button.disabled = false; }
  }
  return {
    mount() {
      if (!root || scope) return;
      scope = createScope(); pending = false;
      scope.listen(root, "click", event => { void action(event); });
      scope.listen(root, "input", () => { dirty = true; });
      scope.interval(() => { if (!root.ownerDocument.hidden) void refresh(); }, 15000);
      scope.add(events.subscribe("provider_diagnostics", event => {
        if (!value?.config.notify_changes) return;
        root.querySelector('[data-monitor="notice"]').textContent = `${event.provider}: ${labels[event.diagnosis] || event.diagnosis}`;
        void refresh();
      }));
      void refresh();
    }, refresh,
    unmount() { scope?.dispose(); scope = null; pending = false; },
  };
}
