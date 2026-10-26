import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { escapeHtml } from "../../shared/utils/escape-html.js";
import { websocket } from "../../core/websocket.js";

const labels = { offline: "Nicht erreichbar", repairing: "Reparatur läuft", changed: "Verändert", healthy: "Gesund", degraded: "Eingeschränkt", broken: "Defekt", blocked: "Verifikation erforderlich", unknown: "Noch nicht geprüft", needs_attention: "Nicht vollständig geprüft", repair_available: "Reparatur verfügbar", cooldown: "Cooldown", probing: "Prüfung läuft" };
const steps = { reachability: "Erreichbarkeit", embed: "Embed", redirect: "Weiterleitung", player: "Player", resolver: "Resolver", media_result: "Medienquelle", connectivity: "Erreichbarkeit", catalog: "Katalog", search: "Suche", detail: "Details", metadata: "Metadaten", hoster_structure: "Hosterstruktur", source_structure: "Quellstruktur", episode_detail: "Episodendetails" };
const reasons = { browser_fallback_required: "HTTP-Pfad nicht bestätigt · Browser-Fallback nicht aktiv geprüft", runtime_validation_required: "HTTP-Probe unvollständig · Produktionspfad benötigt Runtime-Evidenz", metadata_changed: "Metadaten verändert", invalid_reference: "Ungültige Medienreferenzen", response_too_large: "Antwort überschreitet Prüfbudget", http_error: "HTTP-Fehler", internal_probe_error: "Interner Prüffehler", ok: "Bestanden", empty_extraction: "Keine Ergebnisse erkannt", removed: "Referenztitel entfernt", identity_mismatch: "Identität nicht bestätigt", missing_hosters: "Keine Hoster erkannt", missing_links: "Keine Quellen erkannt", verification_required: "Benutzer-Verifikation erforderlich", rate_limit: "Rate-Limit", network_error: "Netzwerkfehler", temporary_http: "Temporärer HTTP-Fehler", budget_exhausted: "Prüfbudget erreicht", full_probe_required: "Nur im vollständigen Test", links_only: "Linkstruktur geprüft; kein Download", parser_error: "Parserfehler" };
const date = value => value ? new Date(value * 1000).toLocaleString() : "—";
const recentDate = value => {
  if (!value) return "Noch keine Prüfung";
  const minutes = Math.max(0, Math.floor((Date.now() / 1000 - value) / 60));
  return minutes < 1 ? "gerade eben" : minutes < 60 ? `vor ${minutes} Minuten` : minutes < 1440 ? `vor ${Math.floor(minutes / 60)} Stunden` : date(value);
};

export function createProviderMonitor(root, { client = api, events = websocket } = {}) {
  let scope, pending, value, dirty = false, tab = "providers", actionPending = false, refreshError = false;
  let revision = 0;
  const snapshots = new WeakMap();
  const detailCache = new Map(), detailPending = new Map();
  const detailKey = (kind, id, field) => `${kind}:${id}:${field}`;
  function applyCachedDetails() {
    const live = new Set();
    for (const kind of ["providers", "hosters"]) for (const source of value[kind] || []) {
      for (const field of ["history", "repairs"]) {
        const key = detailKey(kind, source.provider || source.hoster, field);
        live.add(key);
        const cached = detailCache.get(key);
        if (cached && cached.revision === source.revision) source[field] = cached.items;
        else detailCache.delete(key);
      }
    }
    for (const key of detailCache.keys()) if (!live.has(key)) detailCache.delete(key);
  }
  function prepareDetailPanels() {
    if (!value?.compact || !technical().open) return;
    for (const kind of ["providers", "hosters"]) for (const source of value[kind] || []) {
      const id = source.provider || source.hoster;
      for (const field of ["history", "repairs"]) {
        const panelId = `${kind === "hosters" ? "hoster-" : ""}${id}-${field}`;
        const panel = [...root.querySelectorAll("details[data-panel]")].find(node => node.dataset.panel === panelId);
        if (panel) Object.assign(panel.dataset, { detailKind: kind, detailSource: id, detailField: field });
      }
    }
    for (const panel of root.querySelectorAll("details[data-detail-source][open]")) void loadDetail(panel);
  }
  async function loadDetail(panel) {
    if (!value?.compact || !scope?.active) return;
    if (panel.closest("[hidden]") || !technical().open) return;
    for (let parent = panel.parentElement?.closest("details"); parent; parent = parent.parentElement?.closest("details")) {
      if (!parent.open) return;
    }
    const current = scope;
    const { detailKind: kind, detailSource: id, detailField: field } = panel.dataset;
    if (!["providers", "hosters"].includes(kind) || !["history", "repairs"].includes(field)) return;
    const source = value[kind].find(row => (row.provider || row.hoster) === id);
    if (!source) return;
    const key = detailKey(kind, id, field), version = source.revision;
    if (detailPending.has(key) || detailCache.get(key)?.revision === version) return;
    const task = {};
    detailPending.set(key, task);
    panel.querySelector("[data-detail-feedback]")?.remove();
    const feedback = root.ownerDocument.createElement("p");
    feedback.dataset.detailFeedback = ""; feedback.setAttribute("role", "status");
    feedback.textContent = "Details werden geladen …"; panel.append(feedback);
    try {
      const result = await client.get(`/api/${kind}/${encodeURIComponent(id)}/${field}`, { signal: current.signal });
      if (!current.active || value[kind].find(row => (row.provider || row.hoster) === id)?.revision !== version) return;
      if (!Array.isArray(result[field])) throw new Error("Invalid detail response");
      detailCache.set(key, { revision: version, items: result[field] });
      applyCachedDetails(); render(); renderHosters(); prepareDetailPanels();
    } catch {
      if (current.active) {
        feedback.textContent = "Details konnten nicht geladen werden. ";
        const retry = root.ownerDocument.createElement("button");
        retry.type = "button"; retry.dataset.action = "detail-retry"; retry.textContent = "Erneut laden";
        feedback.append(retry);
      }
    } finally {
      if (detailPending.get(key) === task) detailPending.delete(key);
    }
  }
  function updateList(node, data, markup) {
    const snapshot = JSON.stringify(data);
    if (snapshots.get(node) === snapshot) return;
    node.innerHTML = markup();
    snapshots.set(node, snapshot);
  }
  const status = () => root.querySelector('[data-monitor="status"]');
  const technical = () => root.querySelector('[data-monitor="technical"]');
  const text = (name, copy) => { const node = root.querySelector(`[data-monitor="${name}"]`); if (node.textContent !== copy) node.textContent = copy; };
  function renderService() {
    const service = value.service;
    const state = service?.service_health || "degraded";
    root.querySelector('[data-monitor="overview"]').dataset.state = state;
    text("health-title", state === "healthy" ? "Alles funktioniert" : state === "action_required" ? "Aktion erforderlich" : service?.user_impact === "reduced_redundancy" ? "Eingeschränkte Verfügbarkeit" : "Verfügbarkeit wird geprüft");
    text("health-copy", service?.active_sources === 0 ? "Aktiviere mindestens eine passende Quelle für deine Medien." : state === "healthy" ? "Royal nutzt bei Bedarf automatisch Alternativen." : state === "action_required" ? "Für einen eingerichteten Bereich fehlt eine verfügbare Quelle. Prüfe, ob du weitere passende Quellen aktivieren kannst." : service?.user_impact === "reduced_redundancy" ? "Royal verwendet verfügbare Alternativen. In einzelnen Bereichen stehen weniger Ausweichquellen bereit." : "Die Verfügbarkeit ist noch nicht vollständig bestätigt. Royal sammelt Prüfergebnisse und Ergebnisse der tatsächlichen Nutzung.");
    const coverage = { healthy: "✓ Verfügbar", degraded: "⚠ Weniger Ausweichquellen", action_required: "✕ Keine verfügbare Quelle", unconfirmed: "○ Noch nicht bestätigt", not_configured: "○ Nicht eingerichtet" };
    const coverageMarkup = Object.entries({ movies: "Filme", series: "Serien", anime: "Anime" }).map(([key, label]) => {
      const paths = (service?.paths || []).filter(path => path.media_type === key);
      const affected = paths.some(path => path.state !== "healthy");
      const detail = affected && paths.length > 1 ? paths.map(path => {
        const language = ({ de: "Deutsch", en: "Englisch" })[path.language] || path.language;
        const state = { healthy: "✓ Verfügbar", degraded: "⚠ Weniger Ausweichquellen", action_required: "✕ Nicht verfügbar", unconfirmed: "○ Noch nicht bestätigt" }[path.state] || "○ Noch nicht bestätigt";
        return `<span class="source-language-path">${escapeHtml(language)}: ${state}</span>`;
      }).join("") : "";
      const singleLanguage = affected && paths.length === 1 ? ` (${escapeHtml(({ de: "Deutsch", en: "Englisch" })[paths[0].language] || paths[0].language)})` : "";
      return `<li><strong>${label}</strong><span>${detail || `${coverage[service?.coverage?.[key]] || coverage.unconfirmed}${singleLanguage}`}</span></li>`;
    }).join("");
    const coverageNode = root.querySelector('[data-monitor="coverage"]');
    if (coverageNode.innerHTML !== coverageMarkup) coverageNode.innerHTML = coverageMarkup;
    text("counts", service ? `${service.active_sources} ${service.active_sources === 1 ? "Quelle" : "Quellen"} aktiv · ${service.available_video_services} Videoanbieter verfügbar` : "Noch keine Verfügbarkeitsdaten");
    text("impact", state === "healthy" ? "Downloads: Keine Einschränkungen erkannt." : state === "action_required" ? "Auswirkung auf Downloads: Mindestens ein eingerichteter Bereich ist derzeit nicht verfügbar." : service?.user_impact === "reduced_redundancy" ? "Auswirkung auf Downloads: Verfügbare Alternativen bleiben nutzbar." : "Auswirkung auf Downloads: Noch nicht zuverlässig bewertet.");
    text("required", `Aktion erforderlich: ${service?.action_required ? "Ja – betroffene Quellen prüfen." : "Nein"}`);
    text("last-check", `Letzte Prüfung: ${recentDate(service?.last_check_at)}`);
    const runtime = root.querySelector('[data-monitor="runtime-health"]');
    if (runtime) {
      const warnings = [];
      if (value.config.enabled && value.scheduler?.running === false) warnings.push("Die automatische Quellenprüfung läuft derzeit nicht.");
      else if (value.scheduler?.retrying) warnings.push("Bei der Quellenprüfung gab es einen Fehler. Royal versucht es erneut.");
      if (value.persistence?.write_failed) warnings.push("Prüfergebnisse konnten nicht gespeichert werden. Royal versucht es erneut.");
      if (value.hoster_inventory?.rejected) warnings.push("Das Hoster-Inventar ist belegt. Neue Videoanbieter konnten noch nicht aufgenommen werden.");
      runtime.textContent = warnings.join(" "); runtime.hidden = warnings.length === 0;
    }
    root.querySelector('[data-action="details"]').hidden = !service?.action_required;
  }
  function sourceImpact(kind, key) {
    const impact = value.service?.sources?.[kind]?.[key];
    const label = { none: "Keine", unconfirmed: "Noch nicht bestätigt", relevant: "Weniger Ausweichquellen", blocking: "Blockierend" };
    return `<p>Auswirkung auf Royal: ${label[impact?.impact] || "Noch nicht bewertet"}<br>Aktion erforderlich: ${impact?.action_required ? "Ja" : "Nein"}${impact?.availability === "available" ? "<br>Bestätigt verfügbar" : ""}</p>`;
  }
  function render() {
    if (!value) return;
    if (!dirty) {
      root.querySelector('[name="monitor-enabled"]').checked = value.config.enabled;
      root.querySelector('[name="monitor-auto-repair"]').checked = value.config.auto_repair;
      root.querySelector('[name="monitor-notify"]').checked = value.config.notify_changes;
      root.querySelector('[name="monitor-interval"]').value = value.config.interval_hours;
      root.querySelector('[name="monitor-intensity"]').value = value.config.intensity;
    }
    renderService();
    if (!technical().open) return;
    root.querySelector('[data-monitor="summary"]').textContent = `${value.providers.filter(p => p.enabled).length} aktive Quellen · ${Object.entries(value.summary).filter(([, count]) => count).map(([state, count]) => `${count} ${labels[state] || state}`).join(" · ")} · Hoster: ${Object.entries(value.hoster_summary || {}).filter(([, count]) => count).map(([state, count]) => `${count} ${labels[state] || state}`).join(" · ") || "Noch keine Diagnose"} · Letzte Komplettprüfung: ${date(value.last_complete_check_at)} · Nächste Prüfung: ${value.config.enabled ? date(value.next_check_at) : "Pausiert"}`;
    const list = root.querySelector('[data-monitor="providers"]');
    const opened = new Set([...list.querySelectorAll("details[open]")].map(node => node.dataset.panel || node.dataset.provider));
    updateList(list, [value.providers, value.config.enabled, value.service?.sources?.providers], () => value.providers.map(provider => {
      const esc = escapeHtml, id = esc(provider.provider);
      const repair = Boolean(provider.active_repair);
      return `<details data-provider="${id}" ${opened.has(provider.provider) ? "open" : ""}>
        <summary><strong>${esc(provider.label)}</strong> · ${provider.enabled ? labels[provider.diagnosis] || esc(provider.diagnosis) : "Pausiert"}${provider.running ? " · Prüfung läuft" : ""}${repair ? " · Reparatur aktiv" : ""}</summary>
        ${sourceImpact("providers", provider.provider)}
        <p class="dim">${esc(provider.domain)} · ${esc(provider.contract.media_types.join(", "))} · Runtime: ${esc(labels[provider.runtime.state] || provider.runtime.state)}<br>Priorität: ${Object.entries(provider.priority || {}).map(([media, rank]) => `${esc(media)} ${rank}`).join(" · ") || "—"}<br>Letzter Prüfungsfehler: ${esc(reasons[provider.last_error] || provider.last_error || "—")}</p>
        <p>Letzte Prüfung: ${date(provider.last_check_at)} · Nächste Prüfung: ${provider.enabled && value.config.enabled ? date(provider.next_check_at) : "Automatisch pausiert"}<br>Letzter Erfolg: ${date(provider.last_success_at)}<br>Fehlerquote der Prüfungen (24 h): ${provider.error_rate_24h === null ? "—" : `${Math.round(provider.error_rate_24h * 100)} %`} · Durchschnittliche Prüfdauer: ${provider.average_duration_ms ?? "—"} ms</p>
        <div class="table-scroll"><table><thead><tr><th>Test</th><th>Ergebnis</th><th>Zeit</th></tr></thead><tbody>${provider.steps.map(step => `<tr><td>${esc(steps[step.name] || step.name)}${step.sample && !["movies", "series", "anime"].includes(step.sample) ? ` · ${esc(step.sample.slice(0, 6))}` : ""}</td><td>${step.ok === null ? "—" : step.ok ? "✓" : "✕"} ${esc(reasons[step.code] || step.code)}${step.http_status ? ` (HTTP ${step.http_status})` : ""}</td><td>${step.duration_ms} ms</td></tr>`).join("")}</tbody></table></div>
        ${provider.changed ? '<p>Strukturänderung erkannt. Details stehen im Prüfverlauf.</p>' : ""}
        <p>${provider.hosters.map(hoster => `${esc(hoster.name)}: ${esc(labels[hoster.state] || hoster.state)}`).join(" · ")}</p>
        <button type="button" class="btn-ghost" data-action="probe" data-provider="${id}" ${provider.running ? "disabled" : ""}>Jetzt prüfen</button>
        <button type="button" class="btn-ghost" data-action="full" data-provider="${id}" ${provider.running ? "disabled" : ""}>Vollständigen Test starten</button>
        <details data-panel="${id}-repairs" ${opened.has(`${provider.provider}-repairs`) ? "open" : ""}><summary>Reparaturen (${provider.repairs_count ?? provider.repairs.length})</summary>${provider.repairs.map(item => `<article><p>Repair ${esc(item.id.slice(0, 8))} · ${esc(item.state)} · Sicherheit: ${esc(item.confidence)}<br>Validierung: ${item.validation.validated_detail_pages}/${item.validation.known_detail_pages} unabhängige bekannte Titel</p><div class="table-scroll"><pre>${esc(JSON.stringify({ vorher: item.previous_profile, nachher: item.profile }, null, 2))}</pre></div>${item.id === provider.active_repair ? `<button type="button" class="btn-ghost" data-action="rollback" data-provider="${id}" data-repair="${esc(item.id)}">Reparatur zurücksetzen</button>` : item.state === "available" && item.confidence === "high" ? `<button type="button" class="btn-ghost" data-action="activate" data-provider="${id}" data-repair="${esc(item.id)}">Erneut validieren und aktivieren</button>` : ""}</article>`).join("")}</details>
        <details data-panel="${id}-history" ${opened.has(`${provider.provider}-history`) ? "open" : ""}><summary>Verlauf (${provider.history_count ?? provider.history.length})</summary><ul>${provider.history.slice().reverse().map(event => `<li>${date(event.timestamp)} · ${esc(event.event)} · ${esc(labels[event.diagnosis] || event.reason || "")}${event.changed ? " · Strukturänderung" : ""}${event.isolated ? " · temporär isoliert" : ""}</li>`).join("")}</ul></details>
      </details>`;
    }).join(""));
  }
  function renderHosters() {
    const list = root.querySelector('[data-monitor="hosters"]');
    if (!list || !technical().open) return;
    const opened = new Set([...list.querySelectorAll("details[open]")].map(node => node.dataset.panel));
    const esc = escapeHtml;
    updateList(list, [value.hosters, value.service?.sources?.hosters], () => (value.hosters || []).map(hoster => {
      const id = esc(hoster.hoster), panel = `hoster-${hoster.hoster}`;
      const metric = hoster.metrics_24h;
      return `<details data-panel="${esc(panel)}" ${opened.has(panel) ? "open" : ""}><summary><strong>${esc(hoster.label)}</strong> · ${esc(labels[hoster.diagnosis] || hoster.diagnosis)}${hoster.active_repair ? " · Reparatur aktiv" : ""}</summary>
        ${sourceImpact("hosters", hoster.hoster)}
        <p>Letzte tatsächliche Nutzung: ${!hoster.metrics_24h.attempts ? "Noch keine aktuellen Ergebnisse" : (hoster.last_success_at || 0) > (hoster.last_failure_at || 0) ? "Erfolgreich" : "Nicht erfolgreich"}</p>
        <p>Domains: ${hoster.domains.map(esc).join(", ") || "Noch keine beobachtet"}<br>Resolver: ${esc(hoster.contract.resolver)}${hoster.contract.browser_fallback ? " · Browser-Fallback vorhanden (nicht aktiv geprüft)" : hoster.contract.probe_mode === "runtime_only" ? " · Produktionspfad nicht vollständig aktiv geprüft" : ""}<br>Provider: ${hoster.providers.map(esc).join(", ") || "—"}<br>Fähigkeiten: ${hoster.contract.capabilities.map(esc).join(", ")}</p>
        <p>24 h: ${metric.attempts} Versuche · Erfolg ${metric.success_rate === null ? "—" : `${Math.round(metric.success_rate * 100)} %`} · Median ${metric.median_resolve_ms ?? "—"} ms<br>7 Tage: ${hoster.metrics_7d.attempts} Versuche · Erfolg ${hoster.metrics_7d.success_rate === null ? "—" : `${Math.round(hoster.metrics_7d.success_rate * 100)} %`}<br>Letzter Erfolg: ${date(hoster.last_success_at)} · Letzter Fehler: ${date(hoster.last_failure_at)}<br>Letzte Prüfung: ${date(hoster.last_check_at)} · Nächste Prüfung: ${date(hoster.next_check_at)}</p>
        <div class="table-scroll"><table><thead><tr><th>Test</th><th>Ergebnis</th><th>Zeit</th></tr></thead><tbody>${hoster.steps.map(step => `<tr><td>${esc(steps[step.name] || step.name)}</td><td>${["browser_fallback_required", "runtime_validation_required"].includes(step.code) ? "⚠" : step.ok === null ? "—" : step.ok ? "✓" : "✕"} ${esc(reasons[step.code] || step.code)}</td><td>${step.duration_ms ? `${step.duration_ms} ms` : "—"}</td></tr>`).join("")}</tbody></table></div>
        <button type="button" class="btn-ghost" data-kind="hoster" data-provider="${id}" data-action="probe" ${hoster.running ? "disabled" : ""}>Jetzt prüfen</button><button type="button" class="btn-ghost" data-kind="hoster" data-provider="${id}" data-action="full" ${hoster.running ? "disabled" : ""}>Vollständigen Test starten</button>
        <details data-panel="${esc(panel)}-repairs" ${opened.has(`${panel}-repairs`) ? "open" : ""}><summary>Reparaturen (${hoster.repairs_count ?? hoster.repairs.length})</summary>${hoster.repairs.map(item => `<article><p>Repair ${esc(item.id.slice(0, 8))} · ${esc(item.state)} · ${esc(item.confidence)} · Shadow ${item.validation.validated_detail_pages}/${item.validation.known_detail_pages}</p><div class="table-scroll"><pre>${esc(JSON.stringify({ vorher: item.previous_profile, nachher: item.profile }, null, 2))}</pre></div><button type="button" class="btn-ghost" data-kind="hoster" data-provider="${id}" data-repair="${esc(item.id)}" data-action="${hoster.active_repair === item.id ? "rollback" : "activate"}">${hoster.active_repair === item.id ? "Reparatur zurücksetzen" : "Erneut validieren und aktivieren"}</button></article>`).join("")}</details>
        <details data-panel="${esc(panel)}-history" ${opened.has(`${panel}-history`) ? "open" : ""}><summary>Verlauf</summary><ul>${hoster.history.slice().reverse().map(event => `<li>${date(event.timestamp)} · ${esc(event.event)} · ${esc(event.reason || event.diagnosis || "")}</li>`).join("")}</ul></details></details>`;
    }).join(""));
    const history = root.querySelector('[data-monitor="history"]');
    const openedHistory = new Set([...(history?.querySelectorAll("details[open]") || [])].map(node => node.dataset.panel));
    if (history) updateList(history, [value.providers, value.hosters], () => [...value.providers, ...(value.hosters || [])].map(source => {
      const kind = source.provider ? "providers" : "hosters", id = source.provider || source.hoster, panel = `history-${kind}-${id}`;
      return `<details data-panel="${esc(panel)}" data-detail-kind="${kind}" data-detail-source="${esc(id)}" data-detail-field="history" ${openedHistory.has(panel) ? "open" : ""}><summary>${esc(source.label)} · ${source.repairs_count ?? source.repairs.length} Reparaturen</summary><ul>${source.history.slice().reverse().map(event => `<li>${date(event.timestamp)} · ${esc(event.event)} · ${esc(event.reason || event.diagnosis || "")}</li>`).join("")}</ul></details>`;
    }).join(""));
    for (const name of ["providers", "hosters", "history"]) root.querySelector(`[data-monitor="${name}"]`).hidden = name !== tab;
    for (const button of root.querySelectorAll('[data-action="tab"]')) button.setAttribute("aria-pressed", String(button.dataset.tab === tab));
  }
  async function refresh({ afterMutation = false } = {}) {
    if (!scope?.active) return;
    const current = scope;
    if (pending) {
      await pending;
      if (!afterMutation || !current.active) return;
    }
    const request = (async () => { try {
      const result = await client.get("/api/providers/diagnostics?summary=true", { signal: current.signal });
      if (!current.active) return;
      if (!result?.config || !Array.isArray(result.providers)) throw new Error("Provider-Diagnosen sind derzeit nicht verfügbar.");
      // Background polling must not remove feedback and move controls between
      // pointerdown and pointerup. A new action/mount owns status replacement.
      value = result; applyCachedDetails(); render(); renderHosters(); prepareDetailPanels();
      if (refreshError) { status().textContent = ""; refreshError = false; }
    } catch (error) {
      if (current.active) { refreshError = true; status().textContent = error.status === 403 ? "Die Quellenübersicht ist nur für Administratoren verfügbar." : "Die Quellenübersicht ist vorübergehend nicht erreichbar. Bitte später erneut versuchen."; }
    } finally { if (current.active) pending = null; } })();
    pending = request;
    await request;
  }
  async function action(event) {
    const button = event.target.closest("button[data-action]");
    if (!button || !scope?.active) return;
    const current = scope;
    const { action: name, provider, repair, kind } = button.dataset;
    if (name === "detail-retry") { await loadDetail(button.closest("details")); return; }
    if (name === "details") { technical().open = true; render(); renderHosters(); prepareDetailPanels(); technical().querySelector("summary").focus(); return; }
    if (name === "tab") { tab = button.dataset.tab; renderHosters(); prepareDetailPanels(); return; }
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
    if (actionPending) return;
    actionPending = true;
    root.setAttribute("aria-busy", "true");
    button.disabled = true;
    try {
      if (name === "save") {
        const atRevision = revision;
        await client.put("/api/providers/monitor/config", {
          enabled: root.querySelector('[name="monitor-enabled"]').checked,
          auto_repair: root.querySelector('[name="monitor-auto-repair"]').checked,
          notify_changes: root.querySelector('[name="monitor-notify"]').checked,
          interval_hours: Number(root.querySelector('[name="monitor-interval"]').value),
          intensity: root.querySelector('[name="monitor-intensity"]').value,
        }, { signal: current.signal });
        if (current.active && revision === atRevision) dirty = false;
      } else if (name === "all") {
        await client.post("/api/providers/probe-all", { intensity: root.querySelector('[name="monitor-intensity"]').value }, { signal: current.signal });
      } else if (name === "confirm") {
        await client.post(`/api/${sourcePath}/${encodeURIComponent(provider)}/repairs/${encodeURIComponent(repair)}/${button.dataset.operation}`, { confirmed: true }, { signal: current.signal });
        if (current.active) root.querySelector('[data-monitor="confirmation"]').hidden = true;
      } else {
        await client.post(`/api/${sourcePath}/${encodeURIComponent(provider)}/probe`, { intensity: name === "full" ? "full" : "standard" }, { signal: current.signal });
      }
      if (current.active) { refreshError = false; status().textContent = "Übernommen. Royal kümmert sich um die Prüfung."; await refresh({ afterMutation: true }); }
    } catch (error) { if (current.active) { refreshError = false; status().textContent = error.status === 429 ? "Eine Prüfung läuft bereits. Bitte kurz warten." : "Die Änderung konnte nicht übernommen werden. Bitte erneut versuchen."; } }
    finally { if (current.active) { button.disabled = false; actionPending = false; root.setAttribute("aria-busy", "false"); } }
  }
  return {
    mount() {
      if (!root || scope) return;
      scope = createScope(); pending = null; actionPending = false; refreshError = false;
      detailCache.clear(); detailPending.clear();
      if (!root.querySelector('[data-monitor="runtime-health"]')) {
        const warning = root.ownerDocument.createElement("p");
        warning.dataset.monitor = "runtime-health"; warning.setAttribute("role", "status"); warning.hidden = true;
        root.querySelector('[data-monitor="notice"]').after(warning);
      }
      root.setAttribute("aria-busy", "false"); status().textContent = "";
      scope.listen(root, "click", event => { void action(event); });
      const changed = () => { dirty = true; revision++; };
      scope.listen(root, "input", changed);
      scope.listen(root, "change", changed);
      scope.listen(technical(), "toggle", event => {
        // Nested disclosure events must not rebuild the control being opened.
        if (event.target !== technical()) return;
        if (value && technical().open) { render(); renderHosters(); prepareDetailPanels(); }
      });
      scope.listen(root, "toggle", event => {
        const panel = event.target;
        if (panel.matches?.("details[data-detail-source]") && panel.open) void loadDetail(panel);
      }, true);
      scope.interval(() => { if (!root.ownerDocument.hidden) void refresh(); }, 15000);
      scope.add(events.subscribe("provider_diagnostics", event => {
        if (!value?.config.notify_changes) return;
        const notices = { source_recovered: "Die betroffenen Bereiche sind wieder verfügbar.", source_unavailable: "Ein eingerichteter Bereich ist nicht verfügbar. Bitte Quellen prüfen.", source_redundancy_reduced: "In einem Bereich stehen weniger Ausweichquellen bereit. Royal verwendet Alternativen." };
        root.querySelector('[data-monitor="notice"]').textContent = notices[event.message_code] || "";
        void refresh();
      }));
      void refresh();
    }, refresh,
    unmount() { scope?.dispose(); scope = null; pending = null; actionPending = false; detailCache.clear(); detailPending.clear(); root.setAttribute("aria-busy", "false"); },
  };
}
