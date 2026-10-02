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
  let resizeObserver, visibilityObserver, nearSections = new WeakSet();
  const pendingSizes = new Map();
  let resizeFrame = null;
  const pendingPosters = new Set(), metadata = new WeakMap();
  let posterFrame = null;
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
    if (title && title.textContent !== (media.title || "")) title.textContent = media.title || "";
    const meta = card.querySelector(".home-card-overlay > span:last-child");
    const metaKey = JSON.stringify([media.year, media.rating, entry.kind]);
    if (meta && metadata.get(meta) !== metaKey) {
      setMediaCardMeta(meta, media, entry.kind); metadata.set(meta, metaKey);
    }
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
    // Updates and orientation changes get one real measurement. ResizeObserver
    // re-enables offscreen skipping with the new, exact content-box height.
    const section = track.closest?.('.home-rail');
    if (section?.style.contentVisibility === 'auto') section.style.contentVisibility = 'visible';
    const oldPosition = track.scrollLeft;
    const oldStride = Number(track.dataset?.homeLoopStride || 0);
    const oldLeading = Number(track.dataset?.homeLoopLeading || 0);
    const oldCount = Number(track.dataset?.homeLoopCount || 0);
    let actualStride = 0, visibleFraction = 0, visibleKey = "";
    if (previous?.width === 0 && track.getBoundingClientRect) {
      const trackLeft = track.getBoundingClientRect().left;
      const oldCards = [...track.children];
      const visibleIndex = oldCards.findIndex(card => card.getBoundingClientRect().right > trackLeft + 2);
      const visibleCard = oldCards[visibleIndex];
      const followingCard = oldCards[visibleIndex + 1];
      const visibleRect = visibleCard?.getBoundingClientRect();
      actualStride = followingCard && visibleRect
        ? followingCard.getBoundingClientRect().left - visibleRect.left : 0;
      visibleFraction = actualStride > 0 ? (trackLeft - visibleRect.left) / actualStride : 0;
      visibleKey = visibleCard?.dataset.key || "";
    }
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
    const measuredStride = originals.length > 1
      ? (originals.at(-1).offsetLeft - originals[0].offsetLeft) / (originals.length - 1) : 0;
    const width = track.clientWidth;
    const stride = width > 0 ? measuredStride : oldStride;
    const buffer = loop && logicalCount > 1 ? (width > 0 ? carouselBuffer(logicalCount, width, stride) : oldLeading) : 0;
    for (let i = -buffer; i < 0; i++) nodes.push(node(specs[((i % logicalCount) + logicalCount) % logicalCount], 0, i));
    nodes.push(...originals);
    for (let i = 0; i < buffer; i++) nodes.push(node(specs[i % logicalCount], 2, i));
    const keep = new Set(nodes);
    for (const card of [...track.children]) if (!keep.has(card)) card.remove();
    nodes.forEach((card, index) => { if (track.children[index] !== card) track.insertBefore(card, track.children[index] || null); });
    const geometryChanged = oldStride !== stride || oldLeading !== buffer;
    const previousPosition = previous?.width === 0 ? carousel.homeRailStoredScroll(track, oldPosition) : oldPosition;
    let position = width > 0 && (geometryChanged || previous?.width === 0) && oldStride > 0 && oldCount === logicalCount
      ? (buffer + carouselPhase(previousPosition, oldLeading, oldStride, oldCount)) * stride
      : undefined;
    // An orientation or hidden-tab transition can resize cards before the
    // stored stride is refreshed. In that case map the visible card itself,
    // rather than treating stale pixel geometry as a logical catalog index.
    if (position !== undefined && previous?.width === 0 && actualStride > 0 && Math.abs(actualStride - oldStride) > 1 && visibleKey) {
      const index = originals.findIndex(card => card.dataset.key === visibleKey);
      if (index >= 0 && visibleFraction >= -0.1 && visibleFraction <= 1.1) {
        position = (buffer + index + visibleFraction) * stride;
      }
    }
    if (width > 0) {
      prepareHomeRailLoop(track, buffer ? logicalCount : 0, { stride, leading: buffer, position });
      carousel.rememberHomeRailScroll(track, { force: geometryChanged });
    }
    const hasCards = Boolean(originals[0]?.classList?.contains?.('home-card'));
    rails.set(track, { specs, loop, width, hasCards });
    // Re-observe so unchanged-height data refreshes also re-enable auto skipping.
    if (section) {
      resizeObserver?.unobserve(section);
      if (hasCards) { resizeObserver?.observe(section); visibilityObserver?.observe(section); }
      else {
        visibilityObserver?.unobserve(section); pendingSizes.delete(section);
        nearSections.delete(section); section.style.containIntrinsicBlockSize = '';
      }
    }
    updateHomeRailNavigation(track);
    primeHomeRailPosters(track);
  }

  function posterReads(track) {
      const jobs = [];
      const bounds = track.getBoundingClientRect();
      const viewportWidth = document.documentElement?.clientWidth || window.innerWidth || 0;
      const viewportHeight = document.documentElement?.clientHeight || window.innerHeight || 0;
      const verticallyNear = bounds.bottom >= -320 && bounds.top <= viewportHeight + 640;
      if (!verticallyNear) return jobs;
      [...track.children].forEach((card) => {
        const image = card.querySelector?.(".home-card-art img");
        if (!image || (artwork.needsStart && !artwork.needsStart(image))) return;
        const rect = card.getBoundingClientRect();
        const nearViewport = rect.right >= bounds.left - 240 && rect.left <= bounds.right + 420;
        if (!nearViewport) return;
        const visible = rect.right > 0 && rect.left < viewportWidth
          && rect.bottom > 0 && rect.top < viewportHeight;
        jobs.push({ image, visible });
      });
      return jobs;
  }

  function hydratePosters() {
    posterFrame = null;
    // Collect geometry for ALL pending rails before any class/src/priority write.
    const jobs = [...pendingPosters].flatMap(posterReads);
    pendingPosters.clear();
    for (const { image, visible } of jobs) startHomeCardArtwork(image, visible ? "high" : "auto");
  }

  function queuePosters(track) {
    pendingPosters.add(track);
    if (!scope?.active) { hydratePosters(); return; }
    if (!posterFrame) posterFrame = scope.frame(hydratePosters);
  }

  function primeHomeRailPosters(track) {
    if (!track?.getBoundingClientRect || !track.addEventListener) return;
    queuePosters(track);
    if (!scope?.active) return;
    if (bound.has(track)) return;
    bound.add(track);
    scope.listen(track, "scroll", () => queuePosters(track), { passive: true });
  }

return {
  signature: homeRailCardSignature, sync: syncHomeCardContent, reconcile: reconcileHomeRail,
  mount() {
    if (scope?.active) return;
    scope = createScope();
    if (window.IntersectionObserver) {
      visibilityObserver = new window.IntersectionObserver(entries => {
        for (const { target, isIntersecting } of entries) {
          if (isIntersecting) nearSections.add(target); else nearSections.delete(target);
          if (target.style.containIntrinsicBlockSize) target.style.contentVisibility = isIntersecting ? 'visible' : 'auto';
        }
      }, { rootMargin: '900px 0px' });
      scope.observe(visibilityObserver);
    }
    if (window.ResizeObserver) {
      resizeObserver = new window.ResizeObserver(entries => {
        for (const { target, contentRect } of entries) pendingSizes.set(target, contentRect.height);
        if (resizeFrame) return;
        // Do not resize an observed box during ResizeObserver delivery (WebKit
        // reports an undelivered-notifications loop). Read all widths first.
        resizeFrame = scope.frame(() => {
          resizeFrame = null;
          const sizes = [...pendingSizes].map(([target, height]) => {
            const track = target.querySelector('.home-track');
            return { target, height, track, rail: rails.get(track), width: track?.clientWidth || 0 };
          });
          pendingSizes.clear();
          for (const { target, height, track, rail, width } of sizes) {
            if (rail && width > 0 && width !== rail.width) reconcileHomeRail(track, rail.specs, { loop: rail.loop });
            if (rail && height > 0) {
              target.style.containIntrinsicBlockSize = `${height}px`;
              target.style.contentVisibility = visibilityObserver && !nearSections.has(target) ? 'auto' : 'visible';
            }
          }
        });
      });
      scope.observe(resizeObserver);
      for (const [track, rail] of rails) {
        const section = track.closest('.home-rail');
        if (section && rail.hasCards) { resizeObserver.observe(section); visibilityObserver?.observe(section); }
      }
    }
    for (const track of root.querySelectorAll(".home-track")) primeHomeRailPosters(track);
  },
  unmount() { scope?.dispose(); scope = null; resizeObserver = null; visibilityObserver = null; resizeFrame = null; posterFrame = null; pendingSizes.clear(); pendingPosters.clear(); nearSections = new WeakSet(); bound = new WeakSet(); },
};
}
