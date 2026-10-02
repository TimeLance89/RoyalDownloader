import { api as http } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { createViewState } from "../../shared/components/view-state.js";
import { queueWaitCopy } from "./wait-state.js";

export function createQueueView(root, {
  state, invalidate, showPersistenceWarning, renderSerienstreamHealth,
  syncSeriesQueueFlags, syncAnimeQueueFlags, syncAniworldQueueFlags,
  syncFpQueueIndicators, setDownloadState, setMobileCount, refresh,
}) {
  let scope, rows, historyRows;
  const find = id => root.querySelector(`#${CSS.escape(id)}`);
  const post = (path, body) => http.post(path, body, { signal: scope.signal });
  const api = {
    queueHistory: () => http.get("/api/queue/history", { signal: scope.signal }),
    queueJobMove: (id, direction) => post(`/api/queue/jobs/${encodeURIComponent(id)}/move`, { direction }),
    queueJobResume: id => post(`/api/queue/jobs/${encodeURIComponent(id)}/resume`),
    queueJobCancel: id => post(`/api/queue/jobs/${encodeURIComponent(id)}/cancel`),
    queueJobRetry: id => post(`/api/queue/jobs/${encodeURIComponent(id)}/retry`),
    queueRemove: slug => post("/api/queue/remove", { slug }),
  };
  const errorHost = document.createElement("div");
  errorHost.className = "queue-error";
  root.querySelector("#queue-list").before(errorHost);
  function showError(error) {
    if (!scope?.active) return;
    const host = state.queue.loaded ? errorHost : find("queue-list");
    host.replaceChildren(createViewState({ state: "error", title: error.message, retry: refresh }));
  }
function renderQueue(payload) {
  if (!scope?.active) return;
  rows?.dispose(); rows = createScope();
  invalidate();
  errorHost.replaceChildren();
  state.queue = { ...payload, loaded: true };
  showPersistenceWarning("Downloadplan", payload.persistence);
  renderSerienstreamHealth(payload.providers?.serienstream || {});
  state.queuedSlugs = new Set();
  for (const group of payload.groups) for (const item of group.items) state.queuedSlugs.add(item.slug);
  syncSeriesQueueFlags();
  syncAnimeQueueFlags();
  syncAniworldQueueFlags();

  const count = Number(payload.count) || 0;
  find("queue-count").textContent = `${count} ${count === 1 ? "Eintrag" : "Einträge"}`;
  setMobileCount(count);
  root.classList.toggle("has-items", count > 0);
  const list = find("queue-list");
  list.innerHTML = "";
  if (!payload.groups.length) {
    list.replaceChildren(createViewState({ state: "empty", className: "queue-empty",
      title: "Der Downloadplan ist leer", detail: "Filme oder Episoden erscheinen hier, sobald du sie hinzufügst.",
    }));
  }

  let queuePosition = 0;
  for (const group of payload.groups) {
    const heading = document.createElement("div");
    heading.className = "queue-group";
    heading.translate = false;
    heading.textContent = `${group.name}  (${group.items.length})`;
    list.appendChild(heading);
    for (const item of group.items) {
      queuePosition += 1;
      const row = document.createElement("div");
      row.className = "queue-item" + (item.done ? " done" : "");
      row.dataset.jobId = item.job_id || "";
      const position = document.createElement("span");
      position.className = "queue-position";
      position.textContent = String(queuePosition).padStart(2, "0");
      const content = document.createElement("span");
      content.className = "queue-item-content";
      const title = document.createElement("strong");
      title.className = "queue-item-title";
      title.translate = false;
      title.textContent = item.title;
      const route = document.createElement("span");
      route.className = "queue-item-route";
      route.translate = false;
      const language = String(item.content_language || "").toUpperCase();
      route.textContent = [language, item.provider, item.hoster || item.hoster_label].filter(Boolean).join(" · ");
      const metrics = document.createElement("span");
      metrics.className = "queue-item-metrics";
      metrics.textContent = queueJobMetrics(item);
      const progress = document.createElement("span");
      progress.className = "queue-item-progress";
      const progressFill = document.createElement("i");
      progressFill.style.width = `${Math.max(0, Math.min(100, Number(item.progress) || 0))}%`;
      progress.appendChild(progressFill);
      content.append(title, route, metrics, progress);

      const status = document.createElement("span");
      status.className = "queue-item-status";
      const statusLabels = {
        queued: "Wartet", preparing: "Prüft Quelle", waiting_provider: "Wartet",
        downloading: "Lädt", paused: "Pausiert", cancelling: "Wird abgebrochen",
      };
      status.textContent = statusLabels[item.job_status] || statusLabels[item.status] || "Wartet";
      const actions = document.createElement("span");
      actions.className = "queue-item-actions";
      const addAction = (text, label, handler) => {
        const button = document.createElement("button");
        button.className = "queue-action-btn";
        button.type = "button";
        button.textContent = text;
        button.setAttribute("aria-label", label);
        rows.listen(button, "click", async () => {
          const current = scope;
          button.disabled = true;
          try {
            const response = await handler();
            if (!current?.active) return;
            if (response.queue) renderQueue(response.queue);
            const history = await api.queueHistory();
            if (current?.active) renderQueueHistory(history.jobs || []);
          } catch (error) {
            if (current?.active && !isAbortError(error)) showError(error);
            button.disabled = false;
          }
        });
        actions.appendChild(button);
      };
      if (item.job_id && !["downloading", "cancelling"].includes(item.job_status)) {
        addAction("↑", `${item.title} nach oben`, () => api.queueJobMove(item.job_id, "up"));
        addAction("↓", `${item.title} nach unten`, () => api.queueJobMove(item.job_id, "down"));
      }
      if (item.job_id && item.job_status === "waiting_provider") {
        addAction("▶", `${item.title} fortsetzen`, () => api.queueJobResume(item.job_id));
      }
      if (item.job_status !== "cancelling") {
        addAction("✕", `${item.title} abbrechen`, () => (
          item.job_id ? api.queueJobCancel(item.job_id) : api.queueRemove(item.slug)
        ));
      }
      row.append(position, content, status, actions);
      list.appendChild(row);
    }
  }
  syncFpQueueIndicators();

  const activity = payload.activity || {};
  const activeDownloads = Math.max(0, Number(activity.active_downloads) || 0);
  const activePreparations = Math.max(0, Number(activity.active_preparations) || 0);
  const pendingPreparations = Math.max(0, Number(activity.pending_preparations) || 0);
  const pendingDownloads = Math.max(0, Number(activity.pending_downloads) || 0);
  const downloadStage = find("download-stage");
  const hasLiveProgress = downloadStage?.dataset.state === "active"
    && find("dl-state-title")?.textContent !== "Bereit";
  if (activeDownloads && !hasLiveProgress) {
    setDownloadState("active", activeDownloads === 1 ? "Download läuft" : `${activeDownloads} Downloads laufen`,
      pendingDownloads ? `${pendingDownloads} weiterer Download ist bereit` : "Stream geladen · Download aktiv",
      state.download.percent);
  } else if (!activeDownloads && activePreparations) {
    const paused = ["cooldown", "probing", "blocked"].includes(payload.providers?.serienstream?.state);
    setDownloadState("active", paused ? "Ersatzquelle wird gesucht" : "Quelle wird geprüft",
      `${activePreparations} aktiv · ${pendingPreparations} Folgen vorgemerkt`, state.download.percent);
  } else if (!activeDownloads && !activePreparations && pendingPreparations) {
    setDownloadState("active", "Fallback-Warteschlange läuft",
      `${pendingPreparations} Folgen werden nacheinander geprüft`, state.download.percent);
  }
}

function formatQueueBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (!bytes) return "";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${Math.round(bytes / 1024)} KiB`;
}

function queueJobMetrics(job) {
  const parts = [];
  const waitCopy = queueWaitCopy(job);
  if (waitCopy) parts.push(waitCopy);
  const downloaded = formatQueueBytes(job.downloaded_bytes);
  const total = formatQueueBytes(job.total_bytes);
  if (downloaded) parts.push(total ? `${downloaded} / ${total}` : downloaded);
  const speed = formatQueueBytes(job.speed_bps);
  if (speed) parts.push(`${speed}/s`);
  const eta = Number(job.eta_seconds);
  if (Number.isFinite(eta) && eta > 0) parts.push(`ETA ${Math.ceil(eta / 60)} Min.`);
  return parts.join(" · ");
}

function updateQueueJobProgress(jobId, job) {
  const row = [...root.querySelectorAll(".queue-item")]
    .find((item) => item.dataset.jobId === String(jobId));
  if (!row) return;
  const fill = row.querySelector(".queue-item-progress i");
  if (fill) fill.style.width = `${Math.max(0, Math.min(100, Number(job.progress ?? job.pct) || 0))}%`;
  const metrics = row.querySelector(".queue-item-metrics");
  if (metrics) metrics.textContent = queueJobMetrics(job);
  const status = row.querySelector(".queue-item-status");
  if (status) status.textContent = "Lädt";
}

function renderQueueHistory(jobs) {
  if (!scope?.active) return;
  historyRows?.dispose(); historyRows = createScope();
  const list = find("queue-history-list");
  const count = find("queue-history-count");
  if (!list || !count) return;
  count.textContent = String(jobs.length);
  list.innerHTML = "";
  if (!jobs.length) {
    list.innerHTML = '<div class="queue-empty">Noch keine abgeschlossenen Downloads.</div>';
    return;
  }
  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = `queue-history-item status-${job.status}`;
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = job.title || job.slug;
    const detail = document.createElement("small");
    const statusLabel = { completed: "Abgeschlossen", failed: "Fehlgeschlagen", cancelled: "Abgebrochen" }[job.status] || job.status;
    detail.textContent = [statusLabel, job.error, job.final_path].filter(Boolean).join(" · ");
    copy.append(title, detail);
    row.appendChild(copy);
    if (["failed", "cancelled"].includes(job.status)) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "queue-action-btn queue-retry-btn";
      retry.textContent = "Retry";
      historyRows.listen(retry, "click", async () => {
        const current = scope;
        retry.disabled = true;
        try {
          const response = await api.queueJobRetry(job.job_id);
          if (!current?.active) return;
          renderQueue(response.queue);
          const history = await api.queueHistory();
          if (current?.active) renderQueueHistory(history.jobs || []);
        } catch (error) {
          if (current?.active && !isAbortError(error)) showError(error);
          retry.disabled = false;
        }
      });
      row.appendChild(retry);
    }
    list.appendChild(row);
  }
}

  return {
    get signal() { return scope?.signal; },
    get active() { return !!scope?.active; },
    refresh,
    mount() {
      if (scope) return;
      scope = createScope();
      if (!state.queue.loaded) find("queue-list").replaceChildren(createViewState({
        state: "loading", className: "queue-empty", title: "Downloadplan wird geladen …",
      }));
    },
    render: renderQueue,
    renderHistory: renderQueueHistory,
    updateProgress: updateQueueJobProgress,
    showError,
    unmount() {
      scope?.dispose(); rows?.dispose(); historyRows?.dispose();
      scope = rows = historyRows = null;
    },
  };
}
