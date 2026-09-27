export function createSeriesStatus(statusElement, badgeElement) {
  function updateSeriesStatus(series) {
    if (!series) return;
    updateSeriesJellyfinBadge(series);
    const status = statusElement;
    if (series.availability_error) {
      status.textContent = `${series.episode_count} Episoden · Verfügbarkeitsprüfung fehlgeschlagen`;
      return;
    }
    if (series.availability_pending) {
      status.textContent = `${series.episode_count} Episoden · Verfügbarkeit wird geprüft …`;
      return;
    }
    if (series.jellyfin_available === false) {
      status.textContent = `${series.episode_count} Episoden · Jellyfin-Abgleich nicht verfügbar`;
      return;
    }
    if (series.jellyfin_configured) {
      const jellyfinCount = (series.seasons || []).reduce(
        (sum, season) => sum + season.episodes.filter((episode) => episode.in_jellyfin).length,
        0,
      );
      status.textContent = `${series.episode_count} Episoden · ${jellyfinCount} in Jellyfin`;
      return;
    }
    status.textContent = `${series.episode_count} Episoden`;
  }

  function updateSeriesJellyfinBadge(series, checking = false) {
    const badge = badgeElement;
    if (!badge) return;
    const label = badge.querySelector("strong");
    badge.className = "series-jellyfin-status";
    if (checking || series?.jellyfin_pending) {
      badge.classList.add("is-checking");
      label.textContent = "Jellyfin wird geprüft";
      return;
    }
    if (series?.jellyfin_stale) {
      const episodes = (series.seasons || []).flatMap((season) => season.episodes || []);
      const jellyfinCount = episodes.filter((episode) => episode.in_jellyfin).length;
      badge.classList.add("is-unavailable");
      label.textContent = `${jellyfinCount} Episoden · letzter Jellyfin-Stand`;
      return;
    }
    if (series?.availability_error || series?.jellyfin_available === false) {
      badge.classList.add("is-unavailable");
      label.textContent = "Jellyfin-Abgleich nicht verfügbar";
      return;
    }
    if (!series?.jellyfin_configured) {
      badge.classList.add("is-disconnected");
      label.textContent = "Jellyfin nicht verbunden";
      return;
    }
    const episodes = (series.seasons || []).flatMap((season) => season.episodes || []);
    const jellyfinCount = episodes.filter((episode) => episode.in_jellyfin).length;
    badge.classList.add(jellyfinCount ? "is-owned" : "is-missing");
    label.textContent = jellyfinCount === episodes.length && episodes.length
      ? "Vollständig in Jellyfin"
      : jellyfinCount
        ? `${jellyfinCount} Episoden in Jellyfin`
        : "Nicht in Jellyfin";
  }

  return { update: updateSeriesStatus, badge: updateSeriesJellyfinBadge };
}
