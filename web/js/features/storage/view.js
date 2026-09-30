import { createViewState } from "../../shared/components/view-state.js";
import { formatBytes } from "../../shared/formatters/bytes.js";
import { escapeHtml as html } from "../../shared/utils/escape-html.js";

export function createStorageView(root) {
  const find = id => root.querySelector(`#${id}`);
  let autopilotRoots = [];
  function formatPercent(value) {
    return `${Math.max(0, Math.min(100, Number(value) || 0)).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;
  }

  function locationStatus(location, roots) {
    return roots.find((root) => root.location_id === location.id) || null;
  }

  function renderLocations(locations, roots) {
    const currentLocations = Array.isArray(locations) ? locations : [];
    const list = find("storage-location-list");
    const count = find("storage-location-count");
    if (!list || !count) return;
    count.textContent = `${currentLocations.length} zusätzlich`;
    if (!currentLocations.length) {
      list.innerHTML = '<div class="storage-empty-state"><strong>Noch kein zusätzlicher Speicherort</strong><span>Der Film- und Serien-Speicher wird trotzdem automatisch live gemessen.</span></div>';
      return;
    }
    list.innerHTML = currentLocations.map((location) => {
      const status = locationStatus(location, roots);
      const available = Boolean(status?.available);
      const state = available ? `${formatPercent(status.used_percent)} belegt · ${formatBytes(status.free_bytes)} frei` : "nicht erreichbar";
      const mediaLabels = { movies: "Filme", series: "Serien", anime: "Anime" };
      const allowed = (location.media_types || []).map((kind) => mediaLabels[kind]).filter(Boolean);
      const routing = location.mode === "media"
        ? `Ziel für: ${allowed.join(" · ") || "keine Medienart"}`
        : "Keine Downloads auf diesen Pfad";
      return `
        <article class="storage-location-row${available ? "" : " is-offline"}" data-location-id="${html(location.id)}">
          <div class="storage-location-icon" aria-hidden="true">▰</div>
          <div class="storage-location-copy"><span>${location.mode === "media" ? "DOWNLOAD-ZIEL" : "NUR ANZEIGE"}</span><strong>${html(location.label)}</strong><code title="${html(location.path)}">${html(location.path)}</code><small>${html(routing)} · ${html(state)}</small></div>
          <div class="storage-location-actions"><button type="button" class="btn btn-ghost btn-sm" data-location-edit="${html(location.id)}">Bearbeiten</button><button type="button" class="storage-location-remove" data-location-remove="${html(location.id)}">Entfernen</button></div>
        </article>`;
    }).join("");
  }

  function volumeCard(volume) {
    const members = Array.isArray(volume.members) ? volume.members : [];
    const tags = members.map((member) => `<span>${html(member.label)}${member.mode === "monitor" ? " · Monitor" : ""}</span>`).join("");
    const paths = (volume.paths || []).map((path) => html(path)).join(" · ");
    const modeText = volume.mode === "media" ? "Smart Scan und Medienaktionen aktiv" : "Nur Live-Monitoring · keine Medienaktionen";
    const policies = autopilotRoots.filter(root => root.volume_id === volume.id);
    const roles = { primary: "Primär", overflow: "Overflow", archive: "Archiv", monitor: "Nur überwachen" };
    const storagePolicy = policies.length ? `<p class="storage-volume-policy-summary">${[...new Set(policies.map(root => roles[root.policy.role]))].join(" · ")}<br>Ziel: unter ${Math.min(...policies.map(root => root.policy.target_percent))} % · Reserve: ${Math.max(...policies.map(root => root.policy.reserve_gib))} GiB<br>${[...new Set(policies.flatMap(root => root.policy.media_types))].map(kind => ({ movies: "Filme", series: "Serien", anime: "Anime" })[kind]).join(" · ")}</p>` : "";
    return `
      <article class="storage-volume-card">
        <header><div><small>PHYSISCHES VOLUME</small><span>${html(volume.label || "Speicher")}</span></div><strong>${formatPercent(volume.used_percent)}</strong></header>
        <code title="${paths}">${paths || "Eingebundenes Dateisystem"}</code>
        <div class="storage-volume-members">${tags}</div>
        <div class="storage-meter" style="--storage-used:${Number(volume.used_percent) || 0}%"><i></i></div>
        <div class="storage-volume-numbers"><span><small>Belegt</small><b>${formatBytes(volume.used_bytes)}</b></span><span><small>Frei</small><b>${formatBytes(volume.free_bytes)}</b></span><span><small>Gesamt</small><b>${formatBytes(volume.total_bytes)}</b></span></div>
        <p>${volume.measurement === "nas_mount" ? "NAS-Mount live" : "Lokales Dateisystem live"} · ${modeText}</p>
        ${storagePolicy}
      </article>`;
  }

  function unavailableRootCard(root) {
    return `
      <article class="storage-volume-card is-error"><header><div><small>${root.source === "custom" ? "SPEICHERORT" : "MEDIENPFAD"}</small><span>${html(root.label || root.key)}</span></div><strong>offline</strong></header><code>${html(root.path || "Nicht konfiguriert")}</code><p>${html(root.error || "Pfad konnte nicht gelesen werden. Prüfe den NAS-/Docker-Mount.")}</p></article>`;
  }

  function renderStatus(payload) {
    autopilotRoots = payload.autopilot?.roots || [];
    const live = find("storage-live-state");
    const summary = find("storage-summary");
    const grid = find("storage-volume-grid");
    if (!live || !summary || !grid) return;
    const roots = (payload.roots || []).map(root => {
      const managed = autopilotRoots.find(item => item.key === root.key);
      return managed && !managed.available ? { ...root, available: false, error: managed.error || root.error } : root;
    });
    renderLocations(payload.locations || [], roots);
    const total = payload.autopilot?.summary || payload.summary || {};
    const volumes = (payload.volumes || []).filter(volume => !autopilotRoots.length || autopilotRoots.some(root => root.available && root.volume_id === volume.id));
    const percent = Number(total.used_percent) || 0;
    summary.dataset.viewState = "ready";
    summary.classList.remove("is-unavailable");
    summary.querySelector(".storage-summary-ring").style.setProperty("--storage-used", `${percent}%`);
    summary.querySelector(".storage-summary-ring strong").textContent = formatPercent(percent);
    summary.querySelector(".storage-summary-copy h3").textContent = `${formatBytes(total.free_bytes)} frei über ${Number(total.volume_count) || 0} Volume${Number(total.volume_count) === 1 ? "" : "s"}`;
    summary.querySelector(".storage-summary-copy p").textContent = payload.deployment_mode === "nas"
      ? "Direkt von den eingebundenen NAS-Dateisystemen gemessen · identische Volumes werden nur einmal gezählt."
      : "Direkt auf den konfigurierten Dateisystemen gemessen · identische Volumes werden nur einmal gezählt.";
    const values = summary.querySelectorAll(".storage-summary-numbers strong");
    if (values[0]) values[0].textContent = formatBytes(total.used_bytes);
    if (values[1]) values[1].textContent = formatBytes(total.free_bytes);
    if (values[2]) values[2].textContent = formatBytes(total.total_bytes);
    live.textContent = `${volumes.length} physische${volumes.length === 1 ? "s" : ""} Volume${volumes.length === 1 ? "" : "s"} · ${new Date((payload.observed_at || Date.now() / 1000) * 1000).toLocaleTimeString("de-DE")}`;

    const unavailable = roots.filter((root) => root.configured !== false && !root.available);
    grid.innerHTML = [
      ...volumes.map(volumeCard),
      ...unavailable.map(unavailableRootCard),
    ].join("");
    grid.dataset.viewState = grid.children.length ? "ready" : "empty";
    if (!grid.children.length) grid.append(createViewState({ state: "empty", className: "storage-empty-state", title: "Keine Speicher-Volumes verfügbar", detail: "Füge einen Speicherort hinzu oder prüfe die konfigurierten Medienpfade." }));
  }

  function renderScan(payload) {
    const list = find("storage-large-content-list");
    const summary = find("storage-scan-summary");
    if (!list || !summary) return;
    const candidates = payload.candidates || [];
    summary.textContent = `${Number(payload.scanned_files) || 0} Dateien geprüft · ${candidates.length} Treffer${payload.truncated ? " · Scanlimit erreicht" : ""}`;
    if (!candidates.length) {
      list.innerHTML = '<div class="storage-empty-state"><strong>Keine auffälligen großen Inhalte gefunden</strong><span>Aktuell sticht kein sicherer Bereinigungs- oder Verschiebe-Treffer hervor.</span></div>';
      return;
    }
    list.innerHTML = candidates.map((candidate, index) => {
      const attrs = `data-root="${html(candidate.root)}" data-relative-path="${html(candidate.relative_path)}" data-token="${html(candidate.token)}" data-size="${Number(candidate.size_bytes) || 0}" data-expires-at="${Number(candidate.expires_at) || 0}" data-name="${html(candidate.name || candidate.relative_path)}"`;
      return `
      <article class="storage-content-candidate"><div class="storage-candidate-rank">${String(index + 1).padStart(2, "0")}</div>
      <div class="storage-candidate-copy"><span>${html(candidate.root_label)} · ${candidate.kind === "directory" ? "Ordner" : "Datei"}</span><strong title="${html(candidate.relative_path)}">${html(candidate.name || candidate.relative_path)}</strong><small>${html(candidate.reason)} · ${Number(candidate.file_count) || 0} Dateien</small></div>
      <div class="storage-candidate-size"><strong>${formatBytes(candidate.size_bytes)}</strong><small>${Number(candidate.media_file_count) || 0} Medien</small></div>
      <div class="storage-candidate-actions"><button class="storage-move-button" type="button" data-storage-move ${attrs}>Verschieben</button><button class="storage-cleanup-button" type="button" data-storage-cleanup ${attrs}>Löschen</button></div></article>`;
    }).join("");
  }

  return { status: renderStatus, scan: renderScan };
}
