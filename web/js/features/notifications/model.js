export function notificationCount(value) {
  const count = Number(value);
  return Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0;
}

export function notificationHasIssue(entry) {
  return Boolean(
    entry.cleanup_last_error || entry.last_error
    || notificationCount(entry.failed_count) > 0
    || entry.status === "blocked" || entry.status === "failed"
  );
}

export function buildSubscriptionInbox(items, health = {}) {
  const entries = (Array.isArray(items) ? items : []).map((entry) => ({
    entry,
    // Alte Server kennen open_count noch nicht. new_count darf dann nicht um
    // queued/failed reduziert werden, weil diese Mengen überlappen konnten.
    openCount: notificationCount(entry.open_count ?? entry.new_count),
    queuedCount: notificationCount(entry.queued_count),
    waitingLanguageCount: notificationCount(entry.waiting_language_count),
    upcomingCount: notificationCount(entry.upcoming_count),
    waitingSourceCount: notificationCount(entry.waiting_release_count),
    downloadedCount: notificationCount(entry.downloaded_count),
    hasIssue: notificationHasIssue(entry),
  })).filter((item) => (
    item.openCount || item.queuedCount || item.waitingLanguageCount || item.upcomingCount
      || item.waitingSourceCount || item.downloadedCount || item.hasIssue
  ));
  const globalError = String(health?.error || "").trim();
  const counts = {
    all: entries.length + (globalError ? 1 : 0),
    new: entries.filter((item) => item.openCount > 0).length,
    queued: entries.filter((item) => item.queuedCount > 0).length,
    downloaded: entries.filter((item) => item.downloadedCount > 0).length,
    issue: entries.filter((item) => item.hasIssue).length + (globalError ? 1 : 0),
  };
  const totals = entries.reduce((sum, item) => ({
    open: sum.open + item.openCount,
    queued: sum.queued + item.queuedCount,
    waitingLanguage: sum.waitingLanguage + item.waitingLanguageCount,
    downloaded: sum.downloaded + item.downloadedCount,
  }), { open: 0, queued: 0, waitingLanguage: 0, downloaded: 0 });
  return { entries, counts, totals, globalError };
}

export function inboxEntriesForFilter(model, filter = "all") {
  return model.entries.filter((item) => {
    if (filter === "new") return item.openCount > 0;
    if (filter === "queued") return item.queuedCount > 0;
    if (filter === "downloaded") return item.downloadedCount > 0;
    if (filter === "issue") return item.hasIssue;
    return true;
  }).sort((left, right) => {
    if (filter === "downloaded") {
      const timestamp = (item) => Number(
        (item.entry.last_unread_downloaded_episode
          || item.entry.last_downloaded_episode)?.downloaded_at || 0
      );
      return timestamp(right) - timestamp(left)
        || String(left.entry.title || "").localeCompare(String(right.entry.title || ""), "de");
    }
    return Number(right.hasIssue) - Number(left.hasIssue)
      || right.openCount - left.openCount
      || right.queuedCount - left.queuedCount
      || String(left.entry.title || "").localeCompare(String(right.entry.title || ""), "de");
  });
}

export function downloadedEpisodeLabel(entry) {
  const episode = entry?.last_unread_downloaded_episode || entry?.last_downloaded_episode;
  if (!episode) return "";
  return `S${String(episode.season || 0).padStart(2, "0")}E${String(episode.episode || 0).padStart(2, "0")}`;
}

export function inboxIssueDetail(entry) {
  const parts = [];
  const failed = notificationCount(entry.failed_count);
  if (failed) parts.push(`${failed} ${failed === 1 ? "Download ist" : "Downloads sind"} fehlgeschlagen.`);
  if (entry.last_error) parts.push(String(entry.last_error));
  else if (entry.status === "blocked") parts.push("Die Quelle konnte nicht geprüft werden.");
  else if (entry.status === "failed" && !failed) parts.push("Ein Download ist fehlgeschlagen.");
  if (entry.cleanup_last_error) parts.push(`Bereinigung pausiert: ${entry.cleanup_last_error}`);
  return parts.join(" ");
}

export function inboxDownloadDetail(entry) {
  const episode = entry.last_unread_downloaded_episode || entry.last_downloaded_episode;
  const timestamp = Number(episode?.downloaded_at || 0);
  const when = timestamp ? new Date(timestamp * 1000).toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }) : "";
  return [`Zuletzt geladen: ${downloadedEpisodeLabel(entry) || "Folge"}`, when]
    .filter(Boolean).join(" · ");
}
