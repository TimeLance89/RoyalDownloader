function homeRailCardSignature(entry, rank = 0, variant = "") {
  const media = homeEntryMedia(entry);
  const artwork = rank
    ? (media.cover_url || media.backdrop_url || "")
    : (media.backdrop_url || "");
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
  specs.forEach((spec, index) => {
    const current = track.children[index];
    if (current?.dataset?.renderSignature === spec.signature) {
      spec.update?.(current);
      return;
    }
    const replacement = spec.create();
    replacement.dataset.renderSignature = spec.signature;
    spec.update?.(replacement);
    if (current) current.replaceWith(replacement);
    else track.appendChild(replacement);
  });
  while (track.children.length > specs.length) track.lastElementChild.remove();
  updateHomeRailNavigation(track);
}
