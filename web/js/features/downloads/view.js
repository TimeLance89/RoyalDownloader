import { api as http } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { createViewState } from "../../shared/components/view-state.js";
import { createQueueWallpaper, queueEpisode, queueFocus, queueStatus, queuePercent } from "./presentation.js";
import { queueWaitCopy } from "./wait-state.js";

export function createQueueView(root, {
  state, invalidate, showPersistenceWarning, renderSerienstreamHealth,
  syncSeriesQueueFlags, syncAnimeQueueFlags, syncAniworldQueueFlags,
  syncFpQueueIndicators, setDownloadState, setMobileCount, refresh, getArtwork = () => [],
}) {
  let scope, historyRows, historyJobs = [], historyKey = "", currentJobId = "";
  const rowCache = new Map(), groupCache = new Map();
  const wallpaper = createQueueWallpaper(root, getArtwork);
  const historyPanel = root.querySelector(".queue-history-panel");
  function updateFocus() {
    const groups = state.queue.groups || [];
    const live = rowCache.get(currentJobId)?.row.dataset.status === "downloading"
      ? groups.flatMap(group => group.items).find(item => item.job_id === currentJobId) : null;
    const item = live || queueFocus(groups, currentJobId);
    find("download-current").textContent = item?.title || "";
    wallpaper.update(item);
  }
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
  const desired = [], retained = new Set(), retainedGroups = new Set();
  if (!payload.groups.length) {
    list.replaceChildren(createViewState({ state: "empty", className: "queue-empty",
      title: "Der Downloadplan ist leer", detail: "Filme oder Episoden erscheinen hier, sobald du sie hinzufügst.",
    }));
  }

  let queuePosition = 0;
  for (const [groupIndex, group] of payload.groups.entries()) {
    const groupKey = `${groupIndex}:${group.name}`;
    retainedGroups.add(groupKey);
    const heading = groupCache.get(groupKey) || document.createElement("div");
    groupCache.set(groupKey, heading);
    heading.className = "queue-group";
    heading.translate = false;
    heading.textContent = `${group.name}  (${group.items.length})`;
    desired.push(heading);
    for (const item of group.items) {
      queuePosition += 1;
      const key = item.job_id || item.slug;
      retained.add(key);
      const signature = JSON.stringify([item.title, item.slug, item.done, item.job_status, item.status,
        item.content_language, item.provider, item.hoster, item.hoster_label]);
      const cached = rowCache.get(key);
      if (cached?.signature === signature) {
        cached.row.querySelector(".queue-position").textContent = String(queuePosition).padStart(2, "0");
        paintProgress(cached.row, item);
        desired.push(cached.row);
        continue;
      }
      cached?.scope.dispose();
      const rows = createScope();
      const row = document.createElement("div");
      rowCache.set(key, { row, signature, scope: rows });
      row.className = "queue-item" + (queueStatus(item) === "completed" ? " done" : "");
      row.dataset.jobId = item.job_id || "";
      row.dataset.status = queueStatus(item);
      const position = document.createElement("span");
      position.className = "queue-position";
      const episode = queueEpisode(item.slug);
      if (episode) {
        position.dataset.episode = `E${String(episode.episode).padStart(2, "0")}`;
        position.setAttribute("aria-label", `Staffel ${episode.season}, Episode ${episode.episode}`);
      }
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
      const titleEpisode = String(item.title || "").match(/\bS(\d{1,2})E(\d{1,3})\b/i);
      const hasEpisodeTitle = episode && titleEpisode
        && Number(titleEpisode[1]) === episode.season && Number(titleEpisode[2]) === episode.episode;
      const episodeCopy = document.createElement("span");
      episodeCopy.className = "queue-mobile-copy queue-item-episode";
      episodeCopy.textContent = episode && !hasEpisodeTitle ? `Staffel ${episode.season} · Episode ${episode.episode}` : "";
      content.append(title, episodeCopy, route, metrics, progress);

      const status = document.createElement("span");
      status.className = "queue-item-status";
      const statusLabels = {
        queued: "Wartet", preparing: "Prüft Quelle", waiting_provider: "Wartet",
        completed: "Abgeschlossen", failed: "Fehlgeschlagen", cancelled: "Abgebrochen",
        downloading: "Lädt", paused: "Pausiert", cancelling: "Wird abgebrochen",
      };
      status.textContent = statusLabels[queueStatus(item)] || "Wartet";
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
          } finally {
            if (current?.active) button.disabled = false;
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
      row.style.setProperty("--queue-actions-width", `${actions.children.length * 44 + Math.max(0, actions.children.length - 1) * 4 + 8}px`);
      row.append(position, content, status, actions);
      paintProgress(row, item);
      desired.push(row);
    }
  }
  for (const key of groupCache.keys()) if (!retainedGroups.has(key)) groupCache.delete(key);
  for (const [key, cached] of rowCache) {
    if (!retained.has(key)) { cached.scope.dispose(); rowCache.delete(key); }
  }
  if (payload.groups.length) {
    // Reuse nodes and their focus; unchanged progress snapshots never replace the list.
    desired.forEach((node, index) => { if (list.children[index] !== node) list.insertBefore(node, list.children[index] || null); });
    while (list.children.length > desired.length) list.lastElementChild.remove();
  }
  syncFpQueueIndicators();
  const queueItems = payload.groups.flatMap(group => group.items);
  const active = queueItems.filter(item => ["downloading", "preparing", "cancelling"].includes(queueStatus(item))).length;
  const pending = queueItems.filter(item => ["queued", "waiting", "waiting_provider", "paused"].includes(queueStatus(item))).length;
  find("queue-summary").textContent = `${active} aktiv · ${pending} vorgemerkt`;
  if (!queueItems.some(item => item.job_id === currentJobId && ["downloading", "preparing", "cancelling"].includes(queueStatus(item)))) currentJobId = "";
  updateFocus();

  const activity = payload.activity || {};
  const activeDownloads = Math.max(0, Number(activity.active_downloads) || 0);
  const activePreparations = Math.max(0, Number(activity.active_preparations) || 0);
  const pendingPreparations = Math.max(0, Number(activity.pending_preparations) || 0);
  const pendingDownloads = Math.max(0, Number(activity.pending_downloads) || 0);
  const downloadStage = find("download-stage");
  const hasLiveProgress = downloadStage?.dataset.state === "active"
    && downloadStage.dataset.progress === "known"
    && find("dl-state-title")?.textContent !== "Bereit";
  const focusedDownload = queueFocus(payload.groups, currentJobId);
  const snapshotPercent = focusedDownload && (Number(focusedDownload.total_bytes) > 0 || Number(focusedDownload.progress) > 0)
    ? queuePercent(focusedDownload.progress) : null;
  if (activeDownloads && !hasLiveProgress) {
    setDownloadState("active", activeDownloads === 1 ? "Download läuft" : `${activeDownloads} Downloads laufen`,
      pendingDownloads ? `${pendingDownloads} weiterer Download ist bereit` : "Stream geladen · Download aktiv",
      snapshotPercent);
  } else if (!activeDownloads && activePreparations) {
    const paused = ["cooldown", "probing", "blocked"].includes(payload.providers?.serienstream?.state);
    setDownloadState("active", paused ? "Ersatzquelle wird gesucht" : "Quelle wird geprüft",
      `${activePreparations} aktiv · ${pendingPreparations} Folgen vorgemerkt`, null);
  } else if (!activeDownloads && !activePreparations && pendingPreparations) {
    setDownloadState("active", "Fallback-Warteschlange läuft",
      `${pendingPreparations} Folgen werden nacheinander geprüft`, null);
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

function paintProgress(row, job) {
  const percent = queuePercent(job.progress ?? job.pct);
  const known = percent !== null && ["downloading", "completed"].includes(queueStatus(job));
  const progress = row.querySelector(".queue-item-progress");
  progress.dataset.known = String(known);
  progress.querySelector("i").style.width = `${percent || 0}%`;
  progress.setAttribute("role", "progressbar");
  progress.setAttribute("aria-label", "Downloadfortschritt");
  progress.setAttribute("aria-valuemin", "0"); progress.setAttribute("aria-valuemax", "100");
  if (known) progress.setAttribute("aria-valuenow", String(Math.round(percent)));
  else progress.removeAttribute("aria-valuenow");
  row.querySelector(".queue-item-metrics").textContent = queueJobMetrics(job);
}
function updateQueueJobProgress(jobId, job) {
  const row = rowCache.get(String(jobId))?.row;
  if (!row) return;
  paintProgress(row, { ...job, job_status: "downloading" });
  // A verified progress event may arrive ahead of the next authoritative snapshot.
  if (row.dataset.status !== "downloading") rowCache.get(String(jobId)).signature = "";
  row.dataset.status = "downloading";
  row.querySelector(".queue-item-status").textContent = "Lädt";
  currentJobId = String(jobId);
  const item = state.queue.groups.flatMap(group => group.items).find(item => item.job_id === currentJobId);
  if (item) { find("download-current").textContent = item.title; wallpaper.update(item); }
}

function renderQueueHistory(jobs) {
  if (!scope?.active) return;
  historyJobs = jobs;
  find("queue-history-count").textContent = String(jobs.length);
  if (!historyPanel.open) return;
  const signature = JSON.stringify(jobs);
  if (signature === historyKey) return;
  historyKey = signature;
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
        } finally {
          if (current?.active) retry.disabled = false;
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
      scope.listen(document, "keydown", event => {
        if (event.key !== "Tab" || !document.body.classList.contains("queue-open") || !matchMedia("(max-width: 820px)").matches) return;
        const targets = [...root.querySelectorAll("button:not(:disabled), summary")].filter(node => node.getClientRects().length && !node.closest("[inert]"));
        const first = targets[0], last = targets.at(-1);
        if (!first) return;
        if (event.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
      });
      scope.listen(historyPanel, "toggle", () => { if (historyPanel.open) renderQueueHistory(historyJobs); });
      // Recheck late catalog hydration only while visible; this never requests metadata.
      const observer = new MutationObserver(() => updateFocus());
      observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
      scope.observe(observer);
      scope.interval(() => { if (document.body.classList.contains("queue-open")) updateFocus(); }, 4000);
      if (!state.queue.loaded) find("queue-list").replaceChildren(createViewState({
        state: "loading", className: "queue-empty", title: "Downloadplan wird geladen …",
      }));
    },
    render: renderQueue,
    renderHistory: renderQueueHistory,
    updateProgress: updateQueueJobProgress,
    showError,
    unmount() {
      scope?.dispose(); historyRows?.dispose(); wallpaper.dispose();
      for (const cached of rowCache.values()) cached.scope.dispose();
      rowCache.clear(); groupCache.clear(); historyJobs = []; historyKey = ""; currentJobId = "";
      scope = historyRows = null;
    },
  };
}
