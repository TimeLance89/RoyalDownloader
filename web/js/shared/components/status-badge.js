import { mediaCenterName, mediaCenterMark } from "../media-center.js";
const labels = {
    owned: "✓ In Jellyfin",
    missing: "Fehlt in Jellyfin",
    checking: "Jellyfin wird geprüft",
    unavailable: "Jellyfin nicht erreichbar",
    blocked: "Jellyfin-Statusanfrage blockiert",
    unconfigured: "Jellyfin nicht verbunden",
    ambiguous: "Jellyfin-Zuordnung unklar",
  };


export function jellyfinStatusText(status) {
  return (labels[status] || labels.checking).replaceAll("Jellyfin", mediaCenterName());
}

export function setCatalogJellyfinBadge(badge, status) {
  const normalized = labels[status] ? status : "checking";
  badge.className = `catalog-jellyfin-badge is-${normalized}`;
  badge.textContent = normalized === "owned" ? `✓ ${mediaCenterMark()}` : normalized === "missing" ? `– ${mediaCenterMark()}` : `${mediaCenterMark()} ?`;
  badge.title = jellyfinStatusText(normalized);
  badge.setAttribute("aria-label", jellyfinStatusText(normalized));
}
