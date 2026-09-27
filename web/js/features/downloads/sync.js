import { api } from "../../core/api.js";

/** Server queue/history snapshots share the persistent queue view's session signal. */
export function createQueueSync({ getView, downloadState, setDownloadState, refreshFpQueuePresentation, renderSeriesTiles, client = api }) {
  let queueSnapshotGeneration = 0, historySequence = 0;
  async function syncQueueSnapshot(context = "Queue-Synchronisierung", shouldApply = null) {
    const queueView = getView();
    if (!queueView?.active) return false;
    const signal = queueView.signal;
    const snapshotGeneration = ++queueSnapshotGeneration;
    try {
      const [response, history] = await Promise.all([
        client.get("/api/queue", { signal }),
        client.get("/api/queue/history", { signal }),
      ]);
      if (snapshotGeneration !== queueSnapshotGeneration || (shouldApply && !shouldApply())) return false;
      if (signal.aborted || !queueView.active) return false;
      queueView.render(response.queue);
      queueView.renderHistory(history.jobs || []);
      return true;
    } catch (error) {
      if (signal.aborted || error?.name === "AbortError") return false;
      if (!shouldApply || shouldApply()) queueView?.showError(error);
      console.warn(`${context} fehlgeschlagen:`, error);
      return false;
    }
  }

  function refreshQueueUiAfterChange(resp) {
    const view = getView();
    if (!view?.active) return;
    const signal = view.signal;
    view.render(resp.queue);
    const sequence = ++historySequence;
    client.get("/api/queue/history", { signal })
      .then((history) => { if (!signal.aborted && sequence === historySequence) view.renderHistory(history.jobs || []); })
      .catch((error) => { if (!signal.aborted) console.warn("Downloadhistorie konnte nicht aktualisiert werden:", error); });
    if (resp.auto_started) {
      downloadState.completed = resp.done_jobs;
      downloadState.total = resp.total_jobs;
      const percent = resp.total_jobs ? (resp.done_jobs / resp.total_jobs) * 100 : 0;
      setDownloadState("active", "Automatischer Download", `${resp.done_jobs}/${resp.total_jobs} fertig`, percent);
    }
    refreshFpQueuePresentation();
    renderSeriesTiles();
  }
  return { refresh: syncQueueSnapshot, acceptMutation: refreshQueueUiAfterChange, invalidate() { queueSnapshotGeneration++; historySequence++; } };
}
