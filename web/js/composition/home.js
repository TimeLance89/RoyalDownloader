import { createHomeCards } from "../features/home/cards.js";
import { sharedPresentation } from "../shell/presentation.js";
import { renderMediaCard } from "../shared/components/media-card.js";
import { mediaCardInitials } from "../shell/actions/movies.js";
import { setHomeCardArtworkCandidates } from "../shell/actions/home.js";
import { setHomeCardMeta } from "../shell/actions/home.js";
import { mediaJellyfinStatus } from "../shell/actions/home.js";
import { homeEntryKey } from "../shell/actions/home.js";
import { createMovieCollectionSearchCard } from "../shell/actions/movie-collections.js";
import { openMovieCollection } from "../shell/actions/movie-collections.js";
import { homeMovieBySlug } from "../shell/actions/home.js";
import { selectFpRow } from "../shell/actions/movies.js";
import { homeAnimeById } from "../shell/actions/home.js";
import { openAnimeDetail } from "../shell/actions/anime.js";
import { homeSeriesBySlug } from "../shell/actions/home.js";
import { loadSeries } from "../shell/actions/series.js";
import { createHomeLanes } from "../features/home/lanes.js";
import { allowedHomeEntries } from "../shell/actions/home.js";
import { uniqueHomeEntries } from "../shell/actions/home.js";
import { homeMovieEntry } from "../shell/actions/home.js";
import { homeSeriesEntry } from "../shell/actions/home.js";
import { interleaveHomeEntries } from "../shell/actions/home.js";
import { loadDiscoveryProfile } from "../shell/actions/home.js";
import { stableDailyOrder } from "../shell/actions/home.js";
import { homeEntryMedia } from "../shell/actions/home.js";
import { homeTopEntries } from "../shell/actions/home.js";
import { stableDiscoveryHash } from "../shell/actions/home.js";
import { localDateKey } from "../shell/actions/home.js";
import { homeHeroCandidates } from "../shell/actions/home.js";
import { homePersonalizedEntries } from "../shell/actions/home.js";
import { currentHomeLayout } from "../shell/actions/home.js";
import { createHomePresenter } from "../features/home/presenter.js";
import { rememberAllHomeRailScroll } from "../shell/actions/home.js";
import { favoriteDiscoveryGenre } from "../shell/actions/home.js";
import { applyHomeLayout } from "../shell/actions/home.js";
import { renderHomeHero } from "../shell/actions/home.js";
import { homeDiscoveryLanes } from "../shell/actions/home.js";
import { homeRailDefinition } from "../shell/actions/home.js";
import { renderHomeRail } from "../shell/actions/home.js";
import { scheduleHomeHeroRotation } from "../shell/actions/home.js";
import { homeAllEntries } from "../shell/actions/home.js";
import { createHomeCatalog } from "../features/home/catalog.js";
import { createTasteRanking } from "../features/home/taste-ranking.js";
import { tasteMetadata } from "../shell/actions/home.js";
import { applyServerTasteProfile } from "../shell/actions/home.js";
import { renderHome } from "../shell/actions/home.js";
import { createHeroSelection } from "../features/home/hero-selection.js";
import { createDailyTop } from "../features/home/daily-top.js";
import { closeGlobalSearch } from "../shell/actions/home.js";
import { createHomeData } from "../features/home/data.js";
import { homeArtworkEntriesInLayout } from "../shell/actions/home.js";
import { syncFpCatalogFromHome } from "../shell/actions/movies.js";
import { syncSeriesCatalogFromHome } from "../shell/actions/movies.js";
import { refreshCatalogJellyfinStatus } from "../shell/actions/home.js";
import { createCarousel } from "../shared/components/carousel.js";

export function composeHome({ discoveryPolicy, movieState, artworkUrls, recommendations }) {
return {
discoveryPolicy,
homeCards: createHomeCards({
      getMovieMetadata: () => movieState.metadataCache,
      getJellyfinStatus: key => sharedPresentation.catalogJellyfin.getStatus(key),
      renderMediaCard, coverCandidates: url => artworkUrls.coverCandidates(url),
      mediaCardInitials, setHomeCardArtworkCandidates, setHomeCardMeta, mediaJellyfinStatus, homeEntryKey,
      openDailyTop: entry => sharedPresentation.dailyTop.open(entry),
      registerDock: (card, entry) => sharedPresentation.cardDock.register(card, entry),
      markLanguage: (node, media) => sharedPresentation.mediaLanguage.mark(node, media),
      enhanceTaste: (card, entry) => sharedPresentation.tasteRanking.enhance(card, entry),
      enhanceHero: (card, entry) => sharedPresentation.heroSelection.enhance(card, entry),
      enhanceDailyTop: (card, entry, rank) => sharedPresentation.dailyTop.enhance(card, entry, rank),
      createCollectionCard: createMovieCollectionSearchCard, openMovieCollection, homeMovieBySlug, selectFpRow,
      homeAnimeById, openAnimeDetail, homeSeriesBySlug, loadSeries,
    }),
homeLanes: createHomeLanes(document.getElementById("tab-home"), {
      allowedHomeEntries, uniqueHomeEntries, homeMovieEntry, homeSeriesEntry, interleaveHomeEntries,
      loadDiscoveryProfile, stableDailyOrder, homeEntryMedia, homeEntryKey, homeTopEntries,
      stableDiscoveryHash, localDateKey, homeHeroCandidates, homePersonalizedEntries, currentHomeLayout,
      mediaJellyfinStatus, getJellyfinStatus: key => sharedPresentation.catalogJellyfin.getStatus(key),
      getData: () => sharedPresentation.homeData.get(),
    }),
homePresenter: createHomePresenter(document.getElementById("tab-home"), {
      getData: () => sharedPresentation.homeData.get(), rememberAllHomeRailScroll, localDateKey,
      loadDiscoveryProfile, favoriteDiscoveryGenre, applyHomeLayout, currentHomeLayout, renderHomeHero,
      homeDiscoveryLanes, homeRailDefinition, renderHomeRail, scheduleHomeHeroRotation, homeAllEntries,
      beforeShuffle: () => sharedPresentation.tasteRanking.beforeShuffle(),
      animateShuffle: () => sharedPresentation.tasteRanking.animateShuffle(), resetHero: () => sharedPresentation.hero.reset(),
    }),
homeCatalog: createHomeCatalog({
      getData: () => sharedPresentation.homeData.get(),
      getHomeSearchResults: () => sharedPresentation.homeSearch.get().results,
      getSearchResults: () => sharedPresentation.search.get().results,
      getAnimeResults: () => sharedPresentation.anime.get().results,
      getMovieMetadata: () => movieState.metadataCache, getShuffle: () => sharedPresentation.homePresenter.get().discoveryShuffle,
    }),
tasteRanking: createTasteRanking(document.getElementById("tab-home"), document.getElementById("taste-profile-summary"), {
      homeEntryMedia: entry => homeEntryMedia(entry), homeEntryKey, tasteMetadata,
      loadDiscoveryProfile: () => loadDiscoveryProfile(), homeAllEntries: () => homeAllEntries(),
      discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry),
      discoveryV2ExposurePenalty: (...args) => discoveryPolicy.discoveryV2ExposurePenalty(...args),
      discoveryV2SelectDiverse: (...args) => discoveryPolicy.discoveryV2SelectDiverse(...args),
      getShuffle: () => sharedPresentation.homePresenter.get().discoveryShuffle,
      applyServerTasteProfile: profile => applyServerTasteProfile(profile), renderHome: () => renderHome(),
    }),
heroSelection: createHeroSelection({
      discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry), homeEntryKey, homeEntryMedia: entry => homeEntryMedia(entry), tasteMetadata,
      discoveryV2ExposurePenalty: (...args) => discoveryPolicy.discoveryV2ExposurePenalty(...args), getHomeData: () => sharedPresentation.homeData.get(),
      homeMovieEntry, homeSeriesEntry, mediaJellyfinStatus, loadDiscoveryProfile: () => loadDiscoveryProfile(), homeAllEntries: () => homeAllEntries(),
    }),
dailyTop: createDailyTop(document.getElementById("tab-home"), {
      fallbackEntries: discoveryPolicy.discoveryV2TopEntries, localDateKey, homeEntryKey,
      discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry), loadDiscoveryProfile: () => loadDiscoveryProfile(),
      selectFpRow: (...args) => selectFpRow(...args), closeGlobalSearch: () => closeGlobalSearch(),
      loadSeries: item => loadSeries(item), renderHome: () => renderHome(),
    }),
recommendations,
homeData: createHomeData({
      getMovieMetadata: () => movieState.metadataCache, isRendered: () => sharedPresentation.homePresenter.get().rendered,
      homeAllEntries: () => homeAllEntries(), homeArtworkEntriesInLayout: () => homeArtworkEntriesInLayout(),
      renderHome: options => renderHome(options),
      syncFpCatalogFromHome: options => syncFpCatalogFromHome(options),
      syncSeriesCatalogFromHome: options => syncSeriesCatalogFromHome(options),
      hydrateHomeMovieArtwork: (...args) => sharedPresentation.artwork.movies(...args),
      hydrateHomeSeriesArtwork: (...args) => sharedPresentation.artwork.series(...args),
      refreshCatalogJellyfinStatus: (...args) => refreshCatalogJellyfinStatus(...args),
      discoveryV2MergeItems: (...args) => discoveryPolicy.discoveryV2MergeItems(...args),
      homeMovieEntry: item => homeMovieEntry(item), homeSeriesEntry: item => homeSeriesEntry(item),
      onLoaded: () => { void recommendations.refresh(); },
    }),
carousel: createCarousel(document.getElementById("tab-home"))
};
}
