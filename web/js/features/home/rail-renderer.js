import { createScope } from "../../core/lifecycle.js";
import { setMediaCardMeta } from "../../shared/components/media-card.js";
import { jellyfinStatusText, setCatalogJellyfinBadge } from "../../shared/components/status-badge.js";
import { carouselBuffer, carouselPhase } from "../../shared/components/carousel-geometry.js";

export function createRailRenderer(root, {
  artwork, carousel, homeEntryMedia, homeEntryKey, getJellyfinStatus, mediaJellyfinStatus,
}) {
  const document = root.ownerDocument, window = document.defaultView;
  const startHomeCardArtwork = artwork.start;
  const setHomeRailCycleAccessibility = (...args) => carousel.setHomeRailCycleAccessibility(...args);
  const prepareHomeRailLoop = (...args) => carousel.prepareHomeRailLoop(...args);
  const updateHomeRailNavigation = (...args) => carousel.updateHomeRailNavigation(...args);
  let scope = null, bound = new WeakSet();
  const rails = new Map();
  let resizeObserver;
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
    const previous = rails.get(track);
    // Resize may arrive during an orientation gesture. Defer geometry changes
    // until native scrolling settles; preserve the latest catalog meanwhile.
    if (carousel.isInteracting?.(track)) {
      previous?.retry?.();
      const retry = scope?.timeout(() => reconcileHomeRail(track, specs, { loop }), 200);
      rails.set(track, { ...previous, specs, loop, retry });
      return;
    }
    const oldPosition = track.scrollLeft;
    const oldStride = Number(track.dataset?.homeLoopStride || 0);
    const oldLeading = Number(track.dataset?.homeLoopLeading || 0);
    const oldCount = Number(track.dataset?.homeLoopCount || 0);
    const existing = new Map([...track.children].map(card => [card.dataset.renderSignature, card]));
    const nodes = [];
    const node = (spec, cycle, slot = "") => {
      const signature = `loop:${cycle}:${slot}:${spec.signature}`;
      let card = existing.get(signature);
      if (!card) {
        card = spec.create(cycle);
        card.dataset.renderSignature = signature;
        setHomeRailCycleAccessibility(card, cycle);
      }
      spec.update?.(card);
      return card;
    };
    const originals = specs.map(spec => node(spec, 1));
    // Originals are retained by identity, including their focus and artwork.
    // On first render only, attach them to measure the actual responsive stride.
    if (!previous || !originals.every(card => card.parentElement === track)) {
      for (const card of originals) track.appendChild(card);
    }
    // Average across the entire original sequence: offsetLeft is integer-rounded,
    // but adjacent bounding rects include the shell's temporary entrance scale.
    // Spanning n-1 gaps bounds the cycle error to about one CSS pixel, without
    // multiplying either per-card rounding or a transient transform by n.
    const stride = originals.length > 1
      ? (originals.at(-1).offsetLeft - originals[0].offsetLeft) / (originals.length - 1) : 0;
    const width = track.clientWidth;
    const buffer = loop && logicalCount > 1 ? carouselBuffer(logicalCount, width, stride) : 0;
    for (let i = -buffer; i < 0; i++) nodes.push(node(specs[((i % logicalCount) + logicalCount) % logicalCount], 0, i));
    nodes.push(...originals);
    for (let i = 0; i < buffer; i++) nodes.push(node(specs[i % logicalCount], 2, i));
    const keep = new Set(nodes);
    for (const card of [...track.children]) if (!keep.has(card)) card.remove();
    nodes.forEach((card, index) => { if (track.children[index] !== card) track.insertBefore(card, track.children[index] || null); });
    const geometryChanged = oldStride !== stride || oldLeading !== buffer;
    const position = geometryChanged && oldStride > 0 && oldCount === logicalCount
      ? (buffer + carouselPhase(oldPosition, oldLeading, oldStride, oldCount)) * stride
      : undefined;
    prepareHomeRailLoop(track, buffer ? logicalCount : 0, { stride, leading: buffer, position });
    carousel.rememberHomeRailScroll(track, { force: geometryChanged });
    rails.set(track, { specs, loop, width });
    resizeObserver?.observe(track);
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
    if (window.ResizeObserver) {
      resizeObserver = new window.ResizeObserver(entries => {
        for (const { target } of entries) {
          const rail = rails.get(target);
          if (rail && target.clientWidth > 0 && target.clientWidth !== rail.width) reconcileHomeRail(target, rail.specs, { loop: rail.loop });
        }
      });
      scope.observe(resizeObserver);
      for (const track of rails.keys()) resizeObserver.observe(track);
    }
    for (const track of root.querySelectorAll(".home-track")) primeHomeRailPosters(track);
  },
  unmount() { scope?.dispose(); scope = null; resizeObserver = null; bound = new WeakSet(); },
};
}
