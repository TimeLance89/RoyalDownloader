function homeRailCardSignature(entry, rank = 0, variant = "") {
  const media = homeEntryMedia(entry);
  const artwork = rank
    ? (media.cover_url || media.backdrop_url || "")
    : (media.backdrop_url || media.cover_url || "");
  return JSON.stringify([
    homeEntryKey(entry), rank, variant, artwork,
  ]);
}

function setHomeCardMeta(meta, media, kind) {
  meta.replaceChildren();
  if (media.year) {
    const year = document.createElement("span");
    year.className = "home-card-year";
    year.textContent = media.year;
    meta.appendChild(year);
  }
  if (media.rating) {
    const rating = document.createElement("span");
    rating.className = "home-card-rating";
    const star = document.createElement("span");
    star.className = "home-card-star";
    star.textContent = "★";
    star.setAttribute("aria-hidden", "true");
    rating.append(star, document.createTextNode(String(media.rating)));
    rating.setAttribute("aria-label", `Bewertung ${media.rating}`);
    meta.appendChild(rating);
  }
  if (!meta.childNodes.length) meta.textContent = kind === "movie" ? "Film" : "Serie";
}

function syncHomeCardContent(card, entry, rank = 0) {
  if (!card) return;
  const media = homeEntryMedia(entry);
  const status = state.home.jellyfinStatusByKey.get(homeEntryKey(entry))
    || mediaJellyfinStatus(media);
  const badge = card.querySelector(".catalog-jellyfin-badge");
  if (badge) setCatalogJellyfinBadge(badge, status);
  const title = card.querySelector(".home-card-overlay > strong");
  if (title) title.textContent = media.title || "";
  const meta = card.querySelector(".home-card-overlay > span:last-child");
  if (meta) setHomeCardMeta(meta, media, entry.kind);
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
    [...track.children].forEach((card, index) => {
      const image = card.querySelector?.(".home-card-art img");
      if (!image) return;
      const rect = card.getBoundingClientRect();
      const nearViewport = rect.right >= bounds.left - 240 && rect.left <= bounds.right + 420;
      if (index < 7 || nearViewport) {
        image.loading = "eager";
        image.fetchPriority = index < 5 ? "high" : "auto";
      }
    });
  };
  hydrate();
  if (track.dataset.posterHydrationBound) return;
  track.dataset.posterHydrationBound = "true";
  let frame = 0;
  track.addEventListener("scroll", () => {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; hydrate(); });
  }, { passive: true });
}
