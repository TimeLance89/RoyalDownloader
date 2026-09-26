export function movieSubscriptionFor(items, slug, movie) {
  const tmdbId = String(movie?.tmdb_id || "").trim();
  if (tmdbId) {
    return items.find(
      (entry) => String(entry.tmdb_id || "") === tmdbId,
    ) || null;
  }
  return items.find(
    (entry) => entry.source_slug === slug,
  ) || null;
}

export function movieSubscriptionStatus(entry) {
  if (entry.status === "watched_deleted") return "Gesehen · gelöscht";
  if (entry.cleanup_last_error) return entry.cleanup_last_error;
  if (entry.status === "queued") return `Upgrade ${entry.upgrade_available_quality || ""} in Queue`.trim();
  if (entry.status === "failed") return entry.last_error || "Prüfung fehlgeschlagen";
  if (entry.status === "upgrade") return `${entry.upgrade_available_quality || "Besser"} verfügbar`;
  const current = entry.current_quality || (
    entry.current_quality_rank ? `${entry.current_quality_rank}p` : "Noch keine Fassung"
  );
  return `${current} · Ziel ${entry.target_quality_label || "Beste Qualität"}`;
}
