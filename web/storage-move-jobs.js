(() => {
  if (window.__royalStorageMoveJobsInstalled) return;
  window.__royalStorageMoveJobsInstalled = true;

  const POLL_MS = 2500;
  const HISTORY_VISIBLE = 5;
  let activeJobs = [];
  let history = [];
  let previousActiveIds = null;
  let pollTimer = null;

  const html = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);

  function formatBytes(value) {
    const bytes = Math.max(0, Number(value) || 0);
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB", "PB"];
    const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    const amount = bytes / (1024 ** index);
    return `${amount.toLocaleString("de-DE", { maximumFractionDigits: index >= 3 ? 2 : 1 })} ${units[index]}`;
  }

  function ensureStyles() {
    if (document.querySelector("style[data-royal-storage-move-jobs-style]")) return;
    const style = document.createElement("style");
    style.dataset.royalStorageMoveJobsStyle = "true";
    style.textContent = `
      .storage-move-jobs-card{margin-top:18px;border:1px solid color-mix(in srgb,currentColor 10%,transparent);border-radius:18px;background:color-mix(in srgb,var(--panel,#17191f) 97%,white 3%);overflow:hidden}
      .storage-move-jobs-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:18px 20px;border-bottom:1px solid color-mix(in srgb,currentColor 8%,transparent)}
      .storage-move-jobs-head span{font-size:.66rem;letter-spacing:.13em;font-weight:800;color:var(--storage-accent)}.storage-move-jobs-head h3{margin:4px 0 3px;font-size:1rem}.storage-move-jobs-head p{margin:0;color:var(--muted,#9ca4af);font-size:.77rem}.storage-move-jobs-head>strong{white-space:nowrap;font-size:.74rem;padding:6px 9px;border-radius:999px;background:color-mix(in srgb,var(--storage-accent) 10%,transparent);color:var(--storage-accent)}
      .storage-move-job-list{display:grid}.storage-move-job{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(150px,.8fr) auto;gap:16px;align-items:center;padding:15px 20px;border-bottom:1px solid color-mix(in srgb,currentColor 7%,transparent)}.storage-move-job:last-child{border-bottom:0}.storage-move-job.is-history{opacity:.78}
      .storage-move-job-copy{min-width:0;display:grid;gap:4px}.storage-move-job-copy>span{font-size:.64rem;letter-spacing:.09em;font-weight:800;color:var(--muted,#9ca4af)}.storage-move-job-copy strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.storage-move-job-copy small{color:var(--muted,#9ca4af);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .storage-move-job-state{display:grid;gap:7px}.storage-move-job-state strong{font-size:.75rem}.storage-move-job-state small{color:var(--muted,#9ca4af);font-size:.7rem}.storage-move-job-bar{height:5px;border-radius:999px;overflow:hidden;background:color-mix(in srgb,currentColor 10%,transparent)}.storage-move-job-bar i{display:block;height:100%;border-radius:inherit;background:var(--storage-accent);width:100%;transform-origin:left}.storage-move-job.is-active .storage-move-job-bar i{width:38%;animation:royalStorageMoveJob 1.15s ease-in-out infinite}.storage-move-job.is-completed .storage-move-job-bar i{width:100%}.storage-move-job.is-failed .storage-move-job-bar i{width:100%;opacity:.35}
      .storage-move-job-size{text-align:right;display:grid;gap:3px}.storage-move-job-size strong{font-size:.82rem}.storage-move-job-size small{font-size:.68rem;color:var(--muted,#9ca4af)}
      .storage-move-job-empty{padding:17px 20px;color:var(--muted,#9ca4af);font-size:.78rem}.storage-move-job-empty strong{color:inherit;margin-right:6px}
      .storage-move-button[data-move-job-locked],.storage-cleanup-button[data-move-job-locked]{opacity:.52;cursor:not-allowed!important}
      @keyframes royalStorageMoveJob{0%{transform:translateX(-110%)}50%{transform:translateX(90%)}100%{transform:translateX(280%)}}
      @media(max-width:760px){.storage-move-jobs-head{display:grid}.storage-move-jobs-head>strong{justify-self:start}.storage-move-job{grid-template-columns:1fr auto}.storage-move-job-state{grid-column:1/-1;grid-row:2}.storage-move-job-size{grid-column:2;grid-row:1}}
    `;
    document.head.appendChild(style);
  }

  function injectPanel() {
    if (document.getElementById("storage-move-job-list")) return true;
    const volumeGrid = document.getElementById("storage-volume-grid");
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
    const list = document.getElementById("storage-move-job-list");
    const count = document.getElementById("storage-move-job-count");
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
    document.querySelectorAll("[data-storage-move]").forEach((button) => setButtonJobLock(button, matchingActiveJob(button)));
    document.querySelectorAll("[data-storage-cleanup]").forEach((button) => setButtonJobLock(button, matchingActiveJob(button)));
  }

  function setBackgroundStatus() {
    if (!activeJobs.length) return;
    const status = document.getElementById("storage-cleanup-status");
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
        const status = document.getElementById("storage-cleanup-status");
        if (finished && status) {
          status.textContent = finished.status === "completed"
            ? `${finished.source_name || "Inhalt"} erfolgreich nach ${finished.destination_label || "dem Ziel"} verschoben · ${formatBytes(finished.moved_bytes || finished.size_bytes)}.`
            : `Verschieben fehlgeschlagen · ${finished.error || "Unbekannter Fehler"}`;
        }
        document.getElementById("storage-refresh")?.click();
        window.setTimeout(() => {
          const section = document.getElementById("settings-storage");
          if (section?.classList.contains("is-active")) document.getElementById("storage-scan")?.click();
        }, 250);
      }
    }
    previousActiveIds = nextIds;
  }

  async function refreshJobs() {
    if (!injectPanel()) return;
    try {
      const payload = await api.get("/api/storage/move/jobs");
      const nextJobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
      const nextHistory = Array.isArray(payload?.history) ? payload.history : [];
      handleTransitions(nextJobs, nextHistory);
      activeJobs = nextJobs;
      history = nextHistory;
      renderJobs();
      setBackgroundStatus();
    } catch (error) {
      const count = document.getElementById("storage-move-job-count");
      if (count) count.textContent = "Jobstatus nicht erreichbar";
    }
  }

  function hookMoveSubmission() {
    if (api.__royalStorageMoveJobsHooked) return;
    api.__royalStorageMoveJobsHooked = true;
    const originalPost = api.post.bind(api);
    api.post = async function royalStorageMoveJobPost(url, body) {
      try {
        const result = await originalPost(url, body);
        if (url === "/api/storage/move" && result?.job) {
          const incoming = result.job;
          activeJobs = [incoming, ...activeJobs.filter((job) => job.job_id !== incoming.job_id)];
          previousActiveIds = new Set(activeJobs.map((job) => job.job_id));
          renderJobs();
          window.setTimeout(setBackgroundStatus, 0);
          window.setTimeout(setBackgroundStatus, 150);
        }
        return result;
      } catch (error) {
        if (url === "/api/storage/move") void refreshJobs();
        throw error;
      }
    };
  }

  function install() {
    ensureStyles();
    injectPanel();
    hookMoveSubmission();
    void refreshJobs();
    pollTimer = window.setInterval(() => {
      if (!document.hidden) void refreshJobs();
    }, POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) void refreshJobs();
    });
    const scanList = document.getElementById("storage-large-content-list");
    if (scanList) {
      new MutationObserver(syncMoveLocks).observe(scanList, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, { once: true });
  else install();
})();
