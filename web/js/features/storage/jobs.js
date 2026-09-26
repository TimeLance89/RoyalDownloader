import { escapeHtml as html } from "../../shared/utils/escape-html.js";
import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { formatBytes } from "../../shared/formatters/bytes.js";

export function createStorageJobs(root, { onCompleted }) {
  let scope;
  let pending;
  let revision = 0;
  const find = id => root.querySelector(`#${id}`);

  const POLL_MS = 2500;
  const HISTORY_VISIBLE = 5;
  let activeJobs = [];
  let history = [];
  let previousActiveIds = null;

  function injectPanel() {
    if (find("storage-move-job-list")) return true;
    const volumeGrid = find("storage-volume-grid");
    if (!volumeGrid) return false;
    volumeGrid.insertAdjacentHTML("afterend", `
      <section class="storage-move-jobs-card" aria-labelledby="storage-move-jobs-title">
        <header class="storage-move-jobs-head">
          <div><span>DATEIAKTIONEN</span><h3 id="storage-move-jobs-title">Verschiebe-Jobs</h3><p>Transfers laufen im Hintergrund weiter. Derselbe Inhalt bleibt bis zum Abschluss für Verschieben und Löschen gesperrt.</p></div>
          <strong id="storage-move-job-count">Keine aktiven Jobs</strong>
        </header>
        <div id="storage-move-job-list" class="storage-move-job-list" aria-live="polite">
          <div class="storage-move-job-empty"><strong>Bereit.</strong> Gestartete Verschiebevorgänge erscheinen hier.</div>
        </div>
      </section>`);
    return true;
  }

  function jobStateLabel(job) {
    if (job.status === "queued") return ["Wartet", "Wird gestartet, sobald der vorherige Transfer abgeschlossen ist."];
    if (job.status === "running") return ["Läuft im Hintergrund", "Royal überträgt den Inhalt sicher auf das Ziel-Volume."];
    if (job.status === "completed") return ["Abgeschlossen", "Quelle entfernt · Ziel vollständig bestätigt."];
    return ["Fehlgeschlagen", job.error || "Der Verschiebevorgang konnte nicht abgeschlossen werden."];
  }

  function jobRow(job, isHistory = false) {
    const [label, detail] = jobStateLabel(job);
    const active = job.status === "queued" || job.status === "running";
    const statusClass = active ? "is-active" : job.status === "completed" ? "is-completed" : "is-failed";
    const source = job.source_label || job.source_root || "Quelle";
    const target = job.destination_label || job.destination_root || "Ziel";
    return `
      <article class="storage-move-job ${statusClass} ${isHistory ? "is-history" : ""}" data-move-job-id="${html(job.job_id)}">
        <div class="storage-move-job-copy"><span>${job.source_kind === "series" ? "SERIE" : "FILM"} · ${html(source)} → ${html(target)}</span><strong>${html(job.source_name || "Inhalt")}</strong><small title="${html(job.destination_path || "")}">${html(job.destination_path || target)}</small></div>
        <div class="storage-move-job-state"><strong>${html(label)}</strong><div class="storage-move-job-bar" aria-hidden="true"><i></i></div><small>${html(detail)}</small></div>
        <div class="storage-move-job-size"><strong>${formatBytes(job.size_bytes)}</strong><small>${isHistory ? "Verlauf" : "Job aktiv"}</small></div>
      </article>`;
  }

  function renderJobs() {
    if (!injectPanel()) return;
    const list = find("storage-move-job-list");
    const count = find("storage-move-job-count");
    if (!list || !count) return;
    count.textContent = activeJobs.length
      ? `${activeJobs.length} ${activeJobs.length === 1 ? "Job aktiv" : "Jobs aktiv"}`
      : "Keine aktiven Jobs";
    const visibleHistory = history.slice(0, HISTORY_VISIBLE);
    list.innerHTML = [...activeJobs.map((job) => jobRow(job)), ...visibleHistory.map((job) => jobRow(job, true))].join("")
      || '<div class="storage-move-job-empty"><strong>Bereit.</strong> Gestartete Verschiebevorgänge erscheinen hier.</div>';
    syncMoveLocks();
  }

  function firstPathPart(value) {
    return String(value || "").replaceAll("\\", "/").split("/").filter(Boolean)[0] || "";
  }

  function matchingActiveJob(button) {
    const root = String(button?.dataset?.root || "");
    const relative = String(button?.dataset?.relativePath || "");
    const top = firstPathPart(relative);
    return activeJobs.find((job) => (
      String(job.source_root || "") === root
      && (String(job.source_name || "") === top || String(job.candidate_path || "") === relative)
    ));
  }

  function setButtonJobLock(button, job) {
    if (!button) return;
    if (job) {
      if (!button.dataset.moveJobOriginalLabel) button.dataset.moveJobOriginalLabel = button.textContent;
      button.dataset.moveJobLocked = job.job_id || "active";
      button.disabled = true;
      button.title = `${job.source_name || "Inhalt"} wird bereits verschoben.`;
      if (button.matches("[data-storage-move]")) button.textContent = job.status === "queued" ? "Verschieben wartet" : "Wird verschoben";
      return;
    }
    if (!button.dataset.moveJobLocked) return;
    delete button.dataset.moveJobLocked;
    button.disabled = false;
    button.title = "";
    if (button.dataset.moveJobOriginalLabel) {
      button.textContent = button.dataset.moveJobOriginalLabel;
      delete button.dataset.moveJobOriginalLabel;
    }
  }

  function syncMoveLocks() {
    root.querySelectorAll("[data-storage-move]").forEach((button) => setButtonJobLock(button, matchingActiveJob(button)));
    root.querySelectorAll("[data-storage-cleanup]").forEach((button) => setButtonJobLock(button, matchingActiveJob(button)));
  }

  function setBackgroundStatus() {
    if (!activeJobs.length) return;
    const status = find("storage-cleanup-status");
    if (!status) return;
    const running = activeJobs.find((job) => job.status === "running") || activeJobs[0];
    const suffix = activeJobs.length > 1 ? ` · ${activeJobs.length} Verschiebe-Jobs aktiv` : "";
    status.textContent = `${running.source_name || "Inhalt"} wird im Hintergrund nach ${running.destination_label || "dem Ziel-Volume"} verschoben${suffix}.`;
  }

  function handleTransitions(nextJobs, nextHistory) {
    const nextIds = new Set(nextJobs.map((job) => job.job_id));
    if (previousActiveIds) {
      const finishedIds = [...previousActiveIds].filter((id) => !nextIds.has(id));
      if (finishedIds.length) {
        const finished = nextHistory.find((job) => finishedIds.includes(job.job_id));
        const status = find("storage-cleanup-status");
        if (finished && status) {
          status.textContent = finished.status === "completed"
            ? `${finished.source_name || "Inhalt"} erfolgreich nach ${finished.destination_label || "dem Ziel"} verschoben · ${formatBytes(finished.moved_bytes || finished.size_bytes)}.`
            : `Verschieben fehlgeschlagen · ${finished.error || "Unbekannter Fehler"}`;
        }
        onCompleted();
      }
    }
    previousActiveIds = nextIds;
  }

  function refreshJobs() {
    const current = scope;
    if (!current?.active || !injectPanel()) return Promise.resolve();
    if (pending) return pending;
    const request = load(current).finally(() => { if (pending === request) pending = null; });
    pending = request;
    return request;
  }
  async function load(current) {
    const requestRevision = revision;
    try {
      const payload = await api.get("/api/storage/move/jobs", { signal: current.signal });
      if (!current.active || revision !== requestRevision) return;
      const nextJobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
      const nextHistory = Array.isArray(payload?.history) ? payload.history : [];
      handleTransitions(nextJobs, nextHistory);
      activeJobs = nextJobs;
      history = nextHistory;
      renderJobs();
      setBackgroundStatus();
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      const count = find("storage-move-job-count");
      if (count) count.textContent = "Jobstatus nicht erreichbar";
    }
  }

  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      injectPanel(); syncMoveLocks();
      void refreshJobs();
      scope.interval(() => { if (!document.hidden) void refreshJobs(); }, POLL_MS);
      scope.listen(document, "visibilitychange", () => { if (!document.hidden) void refreshJobs(); });
    },
    refresh: refreshJobs,
    syncLocks: syncMoveLocks,
    accept(incoming) {
      if (!scope?.active || !incoming) return;
      revision++;
      activeJobs = [incoming, ...activeJobs.filter(job => job.job_id !== incoming.job_id)];
      previousActiveIds = new Set(activeJobs.map(job => job.job_id));
      renderJobs(); setBackgroundStatus();
    },
    unmount() { scope?.dispose(); scope = null; pending = null; },
  };
}
