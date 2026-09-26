import { createScope } from "../../core/lifecycle.js";
import { setMediaCardMeta } from "../../shared/components/media-card.js";
import { jellyfinStatusText, setCatalogJellyfinBadge } from "../../shared/components/status-badge.js";

export function createRailRenderer(root, {
  artwork, carousel, homeEntryMedia, homeEntryKey, getJellyfinStatus, mediaJellyfinStatus,
}) {
  const document = root.ownerDocument, window = document.defaultView;
  const startHomeCardArtwork = artwork.start;
  const setHomeRailCycleAccessibility = (...args) => carousel.setHomeRailCycleAccessibility(...args);
  const prepareHomeRailLoop = (...args) => carousel.prepareHomeRailLoop(...args);
  const updateHomeRailNavigation = (...args) => carousel.updateHomeRailNavigation(...args);
  let scope = null, bound = new WeakSet();
  function homeRailCardSignature(entry, rank = 0, variant = "") {
    const media = homeEntryMedia(entry);
    const artwork = rank
      ? (media.cover_url || media.backdrop_url || "")
      : (media.backdrop_url || media.cover_url || "");
    return JSON.stringify([
      homeEntryKey(entry), rank, variant, artwork,
    ]);
  }

  function syncHomeCardContent(card, entry, rank = 0) {
    if (!card) return;
    const media = homeEntryMedia(entry);
    const status = getJellyfinStatus(homeEntryKey(entry))
      || mediaJellyfinStatus(media);
    const badge = card.querySelector(".catalog-jellyfin-badge");
    if (badge) setCatalogJellyfinBadge(badge, status);
    const title = card.querySelector(".home-card-overlay > strong");
    if (title) title.textContent = media.title || "";
    const meta = card.querySelector(".home-card-overlay > span:last-child");
    if (meta) setMediaCardMeta(meta, media, entry.kind);
    const action = card.querySelector(".home-card-primary-action");
    if (action) {
      const kindLabel = entry.kind === "movie" ? "Film" : entry.kind === "anime" ? "Anime" : "Serie";
      action.setAttribute(
        "aria-label",
        `${rank ? `Platz ${rank}: ` : ""}${media.title}, ${kindLabel}, ${jellyfinStatusText(status)}`,
      );
    }
  }

  function reconcileHomeRail(track, specs, { loop = true } = {}) {
    const logicalCount = specs.length;
    const renderedSpecs = loop && logicalCount > 1
      ? [0, 1, 2].flatMap((cycle) => specs.map((spec) => ({ ...spec, cycle })))
      : specs.map((spec) => ({ ...spec, cycle: 1 }));
    renderedSpecs.forEach((spec, index) => {
      const current = track.children[index];
      const signature = `loop:${spec.cycle}:${spec.signature}`;
      if (current?.dataset?.renderSignature === signature) {
        spec.update?.(current);
        setHomeRailCycleAccessibility(current, spec.cycle);
        return;
      }
      const replacement = spec.create(spec.cycle);
      replacement.dataset.renderSignature = signature;
      spec.update?.(replacement);
      setHomeRailCycleAccessibility(replacement, spec.cycle);
      if (current) current.replaceWith(replacement);
      else track.appendChild(replacement);
    });
    while (track.children.length > renderedSpecs.length) track.lastElementChild.remove();
    prepareHomeRailLoop(track, loop ? logicalCount : 0);
    updateHomeRailNavigation(track);
    primeHomeRailPosters(track);
  }

  function primeHomeRailPosters(track) {
    if (!track?.getBoundingClientRect || !track.addEventListener) return;
    const hydrate = () => {
      const bounds = track.getBoundingClientRect();
      const viewportWidth = document.documentElement?.clientWidth || window.innerWidth || 0;
      const viewportHeight = document.documentElement?.clientHeight || window.innerHeight || 0;
      const verticallyNear = bounds.bottom >= -320 && bounds.top <= viewportHeight + 640;
      if (!verticallyNear) return;
      [...track.children].forEach((card) => {
        const image = card.querySelector?.(".home-card-art img");
        if (!image) return;
        const rect = card.getBoundingClientRect();
        const nearViewport = rect.right >= bounds.left - 240 && rect.left <= bounds.right + 420;
        if (!nearViewport) return;
        const visible = rect.right > 0 && rect.left < viewportWidth
          && rect.bottom > 0 && rect.top < viewportHeight;
        startHomeCardArtwork(image, visible ? "high" : "auto");
      });
    };
    hydrate();
    if (!scope?.active) return;
    scope.frame(hydrate);
    if (bound.has(track)) return;
    bound.add(track);
    let frame = 0;
    scope.listen(track, "scroll", () => {
      if (frame) return;
      frame = scope.frame(() => { frame = 0; hydrate(); });
    }, { passive: true });
  }

return {
  signature: homeRailCardSignature, sync: syncHomeCardContent, reconcile: reconcileHomeRail,
  mount() {
    if (scope?.active) return;
    scope = createScope();
    for (const track of root.querySelectorAll(".home-track")) primeHomeRailPosters(track);
  },
  unmount() { scope?.dispose(); scope = null; bound = new WeakSet(); },
};
}
