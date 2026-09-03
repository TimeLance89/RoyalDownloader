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
  const status = state.home.jellyfinStatusByKey.get(homeEntryKey(entry))
    || mediaJellyfinStatus(media);
  const badge = card.querySelector(".catalog-jellyfin-badge");
  if (badge) setCatalogJellyfinBadge(badge, status);
  const title = card.querySelector(".home-card-overlay > strong");
  if (title) title.textContent = media.title || "";
  const meta = card.querySelector(".home-card-overlay > span:last-child");
  if (meta) {
    meta.textContent = [media.year || "", media.rating ? `★ ${media.rating}` : ""]
      .filter(Boolean).join(" · ") || (entry.kind === "movie" ? "Film" : "Serie");
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

function reconcileHomeRail(track, specs) {
  const logicalCount = specs.length;
  const renderedSpecs = logicalCount > 1
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
  prepareHomeRailLoop(track, logicalCount);
  updateHomeRailNavigation(track);
}
