let provider = "jellyfin";
export const mediaCenterName = () => provider === "plex" ? "Plex" : "Jellyfin";
export const mediaCenterMark = () => provider === "plex" ? "P" : "JF";
export const mediaCenterText = value => value.replaceAll("Jellyfin", mediaCenterName());
export const mediaCleanupSupported = () => provider !== "plex";
export function setMediaCenter(value) {
  provider = value === "plex" ? "plex" : "jellyfin";
  if (typeof document === "undefined") return;
  document.documentElement.dataset.mediaCenter = provider;
  document.querySelectorAll("[data-media-center-name]").forEach(node => { node.textContent = mediaCenterName(); });
  document.querySelectorAll(".detail-jellyfin-mark, .series-jellyfin-mark").forEach(node => { node.textContent = mediaCenterMark(); });
  const filter = document.getElementById("global-search-jellyfin");
  if (filter) filter.textContent = `✓ In ${mediaCenterName()}`;
}
