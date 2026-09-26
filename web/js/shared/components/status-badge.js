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
  return labels[status] || labels.checking;
}

export function setCatalogJellyfinBadge(badge, status) {
  const normalized = labels[status] ? status : "checking";
  badge.className = `catalog-jellyfin-badge is-${normalized}`;
  badge.textContent = normalized === "owned" ? "✓ JF" : normalized === "missing" ? "– JF" : "JF ?";
  badge.title = labels[normalized];
  badge.setAttribute("aria-label", labels[normalized]);
}
