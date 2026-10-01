export function createHomeRows(root, { isLoading, onRendered = () => {}, reconcileHomeRail, homeRailCardSignature, createHomeCard, syncHomeCardContent }) {
  return function renderHomeRail(trackId, entries, { ranked = false, layout = "rail", wallpaperOnly = false } = {}) {
  const track = root.querySelector(`#${CSS.escape(trackId)}`);
  if (!track) return;
  track.classList.toggle("is-spotlight-track", layout === "spotlight");
  if (!entries.length) {
    if (!isLoading()) {
      reconcileHomeRail(track, [{ signature: "empty", create: () => {
        const empty = document.createElement("span");
        empty.className = "home-rail-empty";
        empty.textContent = "Noch keine Titel aus den aktiven Quellen verfügbar.";
        return empty;
      } }], { loop: false });
      return;
    }
    reconcileHomeRail(track, Array.from({ length: 6 }, (_, index) => ({
      signature: `skeleton:${index}`,
      create: () => {
        const skeleton = document.createElement("span");
        skeleton.className = "home-card-skeleton";
        skeleton.setAttribute("aria-hidden", "true");
        return skeleton;
      },
    })), { loop: false });
    return;
  }
  const visibleEntries = layout === "spotlight" ? entries.slice(0, 7) : entries;
  reconcileHomeRail(track, visibleEntries.map((entry, index) => {
      const eagerCount = ranked ? 5 : 3;
      const variant = layout === "spotlight" && index === 0 ? "spotlight-lead" : "";
      const rank = ranked ? index + 1 : 0;
      return {
        signature: homeRailCardSignature(entry, rank, variant),
        create: (cycle = 0) => createHomeCard(entry, rank, cycle === 1 && index < eagerCount, variant, { wallpaperOnly }),
        update: (card) => syncHomeCardContent(card, entry, rank),
      };
  }), { loop: layout !== "spotlight" && !ranked });
  onRendered(trackId, entries, { ranked, layout, wallpaperOnly });
}
}
