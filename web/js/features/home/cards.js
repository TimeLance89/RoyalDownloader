export function createHomeCards({
  getMovieMetadata, getJellyfinStatus, renderMediaCard, coverCandidates,
  mediaCardInitials, setHomeCardArtworkCandidates, setHomeCardMeta, mediaJellyfinStatus, homeEntryKey,
  openDailyTop, registerDock, markLanguage, enhanceTaste, enhanceHero, enhanceDailyTop,
  createCollectionCard, openMovieCollection, homeMovieBySlug, selectFpRow,
  homeAnimeById, openAnimeDetail, homeSeriesBySlug, loadSeries,
}) {
  function openHomeEntry(kind, key) {
      if (kind === "collection") {
        openMovieCollection(key);
        return;
      }
      if (kind === "movie") {
        const movie = homeMovieBySlug(key);
        if (movie) selectFpRow(movie.slug, movie);
        return;
      }
      if (kind === "anime") {
        const anime = homeAnimeById(key);
        if (anime) openAnimeDetail(anime);
        return;
      }
      const series = homeSeriesBySlug(key);
      if (series) loadSeries(series);
    }

  function createHomeCard(entry, rank = 0, eager = false, variant = "", { wallpaperOnly = false } = {}) {
    if (entry?.kind === "collection") return createCollectionCard(entry.item, eager);
    const { kind, item } = entry;
    const metadata = kind === "movie" ? (getMovieMetadata()[item.slug] || {}) : {};
    const media = { ...item, ...metadata };
    if (wallpaperOnly) media.cover_url = "";
    const cachedJellyfinStatus = getJellyfinStatus(homeEntryKey(entry));
    if (cachedJellyfinStatus) {
      media.jellyfin_status = cachedJellyfinStatus;
      if (cachedJellyfinStatus === "owned" || cachedJellyfinStatus === "missing") {
        media.in_jellyfin = cachedJellyfinStatus === "owned";
      }
    }
    const key = kind === "movie" ? item.slug : kind === "anime" ? item.id : item.base_slug;
    const card = renderMediaCard({
      media, kind, key, rank, eager, variant, jellyfinState: mediaJellyfinStatus(media),
      coverCandidates: url => coverCandidates(url), initials: mediaCardInitials,
      setArtwork: setHomeCardArtworkCandidates, setMeta: setHomeCardMeta,
      onOpen: () => { if (!openDailyTop(entry)) openHomeEntry(kind, key); },
      decorate(card) { registerDock(card, entry); },
    });
    markLanguage(card.querySelector(".home-card-type"), media);
    enhanceTaste(card, entry);
    enhanceHero(card, entry);
    return enhanceDailyTop(card, entry, rank);
  }

  return { create: createHomeCard, open: openHomeEntry };
}
