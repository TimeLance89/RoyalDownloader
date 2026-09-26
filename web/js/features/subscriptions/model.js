export function watchlistNeedsAttention(entry) {
  return Boolean(
    entry.new_count || entry.cleanup_last_error
    || entry.status === "blocked" || entry.status === "failed",
  );
}

export function libraryVisibleItems(items, ui) {
  const query = String(ui.query || "").trim().toLocaleLowerCase("de-DE");
  const filtered = items.filter((entry) => {
    if (query && !String(entry.title || "").toLocaleLowerCase("de-DE").includes(query)) return false;
    if (ui.filter === "attention") return watchlistNeedsAttention(entry);
    if (ui.filter === "current") return entry.status === "current";
    if (ui.filter === "queued") return entry.status === "queued" || Number(entry.queued_count) > 0;
    return true;
  });
  return filtered.sort((left, right) => {
    if (ui.sort === "title") return String(left.title).localeCompare(String(right.title), "de");
    if (ui.sort === "recent") return Number(right.last_checked || 0) - Number(left.last_checked || 0);
    return Number(watchlistNeedsAttention(right)) - Number(watchlistNeedsAttention(left))
      || Number(right.new_count || 0) - Number(left.new_count || 0)
      || String(left.title).localeCompare(String(right.title), "de");
  });
}

export function libraryCheckedLabel(entry) {
  const timestamp = Number(entry?.last_checked || 0);
  if (!timestamp) return "Noch nicht geprüft";
  const elapsed = Math.max(0, Date.now() - timestamp * 1000);
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "Gerade geprüft";
  if (minutes < 60) return `Vor ${minutes} Min. geprüft`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Vor ${hours} Std. geprüft`;
  const days = Math.floor(hours / 24);
  return `Vor ${days} ${days === 1 ? "Tag" : "Tagen"} geprüft`;
}
