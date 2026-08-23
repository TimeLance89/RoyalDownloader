function homeRailCardSignature(entry, rank = 0, variant = "") {
  const media = homeEntryMedia(entry);
  return JSON.stringify([
    homeEntryKey(entry), rank, variant, media.title || "", media.year || "",
    media.rating || "", media.cover_url || "", media.backdrop_url || "",
    mediaJellyfinStatus({
      ...media,
      jellyfin_status: state.home.jellyfinStatusByKey.get(homeEntryKey(entry))
        || media.jellyfin_status,
    }),
  ]);
}

function reconcileHomeRail(track, specs) {
  specs.forEach((spec, index) => {
    const current = track.children[index];
    if (current?.dataset?.renderSignature === spec.signature) return;
    const replacement = spec.create();
    replacement.dataset.renderSignature = spec.signature;
    if (current) current.replaceWith(replacement);
    else track.appendChild(replacement);
  });
  while (track.children.length > specs.length) track.lastElementChild.remove();
  updateHomeRailNavigation(track);
}
