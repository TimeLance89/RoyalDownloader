import { createHomeRows } from "../features/home/rows.js";
import { createHomeLayout } from "../features/home/layout.js";
import { createRailRenderer } from "../features/home/rail-renderer.js";
import { createCardDock } from "../features/home/card-dock.js";
import { createMood } from "../features/mood/index.js";
import { createHero } from "../features/home/hero.js";
import { createDiscoveryPolicy } from "../features/home/discovery-policy.js";
import { createRecommendations } from "../features/home/recommendations.js";
import { createHomeActions } from "../features/home/actions.js";
import { createHomeCards } from "../features/home/cards.js";

import { renderMediaCard } from "../shared/components/media-card.js";

import { createHomeLanes } from "../features/home/lanes.js";

import { createHomePresenter } from "../features/home/presenter.js";

import { createHomeCatalog } from "../features/home/catalog.js";
import { createTasteRanking } from "../features/home/taste-ranking.js";

import { createHeroSelection } from "../features/home/hero-selection.js";
import { createDailyTop } from "../features/home/daily-top.js";

import { createHomeData } from "../features/home/data.js";

import { createCarousel } from "../shared/components/carousel.js";

export function composeHome({ discoveryPolicy, movieState, artworkUrls, recommendations, getDiscovery, getIntegrations, getCore, getSearch, getProfile }) {
  const services = {
  discoveryPolicy,
  homeCards: createHomeCards({
        getMovieMetadata: () => movieState.metadataCache,
        getJellyfinStatus: key => getIntegrations().catalogJellyfin.getStatus(key),
        renderMediaCard, coverCandidates: url => artworkUrls.coverCandidates(url),
        mediaCardInitials: (...args) => getDiscovery().movieActions.mediaCardInitials(...args), setHomeCardArtworkCandidates: (...args) => services.actions.setHomeCardArtworkCandidates(...args), setHomeCardMeta: (...args) => services.actions.setHomeCardMeta(...args), mediaJellyfinStatus: (...args) => services.actions.mediaJellyfinStatus(...args), homeEntryKey: (...args) => services.actions.homeEntryKey(...args),
        openDailyTop: entry => services.dailyTop.open(entry),
        registerDock: (card, entry) => services.cardDock.register(card, entry),
        markLanguage: (node, media) => getDiscovery().mediaLanguage.mark(node, media),
        enhanceTaste: (card, entry) => services.tasteRanking.enhance(card, entry),
        enhanceHero: (card, entry) => services.heroSelection.enhance(card, entry),
        enhanceDailyTop: (card, entry, rank) => services.dailyTop.enhance(card, entry, rank),
        createCollectionCard: ((...args) => getDiscovery().collectionActions.createMovieCollectionSearchCard(...args)), openMovieCollection: (...args) => getDiscovery().collectionActions.openMovieCollection(...args), homeMovieBySlug: (...args) => services.actions.homeMovieBySlug(...args), selectFpRow: (...args) => getDiscovery().movieActions.selectFpRow(...args),
        homeAnimeById: (...args) => services.actions.homeAnimeById(...args), openAnimeDetail: (...args) => getDiscovery().animeActions.openAnimeDetail(...args), homeSeriesBySlug: (...args) => services.actions.homeSeriesBySlug(...args), loadSeries: (...args) => getDiscovery().seriesActions.loadSeries(...args),
      }),
  homeLanes: createHomeLanes(document.getElementById("tab-home"), {
        allowedHomeEntries: (...args) => services.actions.allowedHomeEntries(...args), uniqueHomeEntries: (...args) => services.actions.uniqueHomeEntries(...args), homeMovieEntry: (...args) => services.actions.homeMovieEntry(...args), homeSeriesEntry: (...args) => services.actions.homeSeriesEntry(...args), interleaveHomeEntries: (...args) => services.actions.interleaveHomeEntries(...args),
        loadDiscoveryProfile: (...args) => services.actions.loadDiscoveryProfile(...args), stableDailyOrder: (...args) => services.actions.stableDailyOrder(...args), homeEntryMedia: (...args) => services.actions.homeEntryMedia(...args), homeEntryKey: (...args) => services.actions.homeEntryKey(...args), homeTopEntries: (...args) => services.actions.homeTopEntries(...args),
        stableDiscoveryHash: (...args) => services.actions.stableDiscoveryHash(...args), localDateKey: (...args) => services.actions.localDateKey(...args), homeHeroCandidates: (...args) => services.actions.homeHeroCandidates(...args), homePersonalizedEntries: (...args) => services.actions.homePersonalizedEntries(...args), currentHomeLayout: (...args) => services.actions.currentHomeLayout(...args),
        mediaJellyfinStatus: (...args) => services.actions.mediaJellyfinStatus(...args), getJellyfinStatus: key => getIntegrations().catalogJellyfin.getStatus(key),
        getData: () => services.homeData.get(),
      }),
  homePresenter: createHomePresenter(document.getElementById("tab-home"), {
        getData: () => services.homeData.get(), rememberAllHomeRailScroll: (...args) => services.actions.rememberAllHomeRailScroll(...args), localDateKey: (...args) => services.actions.localDateKey(...args),
        loadDiscoveryProfile: (...args) => services.actions.loadDiscoveryProfile(...args), favoriteDiscoveryGenre: (...args) => services.actions.favoriteDiscoveryGenre(...args), applyHomeLayout: (...args) => services.actions.applyHomeLayout(...args), currentHomeLayout: (...args) => services.actions.currentHomeLayout(...args), renderHomeHero: (...args) => services.actions.renderHomeHero(...args),
        homeDiscoveryLanes: (...args) => services.actions.homeDiscoveryLanes(...args), homeRailDefinition: (...args) => services.actions.homeRailDefinition(...args), renderHomeRail: (...args) => services.actions.renderHomeRail(...args), scheduleHomeHeroRotation: (...args) => services.actions.scheduleHomeHeroRotation(...args), homeAllEntries: (...args) => services.actions.homeAllEntries(...args),
        beforeShuffle: () => services.tasteRanking.beforeShuffle(),
        animateShuffle: () => services.tasteRanking.animateShuffle(), resetHero: () => services.hero.reset(),
      }),
  homeCatalog: createHomeCatalog({
        getData: () => services.homeData.get(),
        getHomeSearchResults: () => getSearch().homeSearch.get().results,
        getSearchResults: () => getSearch().search.get().results,
        getAnimeResults: () => getDiscovery().anime.get().results,
        getMovieMetadata: () => movieState.metadataCache, getShuffle: () => services.homePresenter.get().discoveryShuffle,
      }),
  tasteRanking: createTasteRanking(document.getElementById("tab-home"), document.getElementById("taste-profile-summary"), {
        homeEntryMedia: entry => services.actions.homeEntryMedia(entry), homeEntryKey: (...args) => services.actions.homeEntryKey(...args), tasteMetadata: (...args) => services.actions.tasteMetadata(...args),
        loadDiscoveryProfile: () => services.actions.loadDiscoveryProfile(), homeAllEntries: () => services.actions.homeAllEntries(),
        discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry),
        discoveryV2ExposurePenalty: (...args) => discoveryPolicy.discoveryV2ExposurePenalty(...args),
        discoveryV2SelectDiverse: (...args) => discoveryPolicy.discoveryV2SelectDiverse(...args),
        getShuffle: () => services.homePresenter.get().discoveryShuffle,
        applyServerTasteProfile: profile => services.actions.applyServerTasteProfile(profile), renderHome: () => services.actions.renderHome(),
      }),
  heroSelection: createHeroSelection({
        discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry), homeEntryKey: (...args) => services.actions.homeEntryKey(...args), homeEntryMedia: entry => services.actions.homeEntryMedia(entry), tasteMetadata: (...args) => services.actions.tasteMetadata(...args),
        discoveryV2ExposurePenalty: (...args) => discoveryPolicy.discoveryV2ExposurePenalty(...args), getHomeData: () => services.homeData.get(),
        homeMovieEntry: (...args) => services.actions.homeMovieEntry(...args), homeSeriesEntry: (...args) => services.actions.homeSeriesEntry(...args), mediaJellyfinStatus: (...args) => services.actions.mediaJellyfinStatus(...args), loadDiscoveryProfile: () => services.actions.loadDiscoveryProfile(), homeAllEntries: () => services.actions.homeAllEntries(),
      }),
  dailyTop: createDailyTop(document.getElementById("tab-home"), {
        fallbackEntries: discoveryPolicy.discoveryV2TopEntries, localDateKey: (...args) => services.actions.localDateKey(...args), homeEntryKey: (...args) => services.actions.homeEntryKey(...args),
        discoveryV2LogicalKey: entry => discoveryPolicy.discoveryV2LogicalKey(entry), loadDiscoveryProfile: () => services.actions.loadDiscoveryProfile(),
        selectFpRow: (...args) => getDiscovery().movieActions.selectFpRow(...args), closeGlobalSearch: () => services.actions.closeGlobalSearch(),
        loadSeries: item => getDiscovery().seriesActions.loadSeries(item), renderHome: () => services.actions.renderHome(),
      }),
  recommendations,
  homeData: createHomeData({
        getMovieMetadata: () => movieState.metadataCache, isRendered: () => services.homePresenter.get().rendered,
        homeAllEntries: () => services.actions.homeAllEntries(), homeArtworkEntriesInLayout: () => services.actions.homeArtworkEntriesInLayout(),
        renderHome: options => services.actions.renderHome(options),
        syncFpCatalogFromHome: options => getDiscovery().movieActions.syncFpCatalogFromHome(options),
        syncSeriesCatalogFromHome: options => getDiscovery().movieActions.syncSeriesCatalogFromHome(options),
        hydrateHomeMovieArtwork: (...args) => getDiscovery().artwork.movies(...args),
        hydrateHomeSeriesArtwork: (...args) => getDiscovery().artwork.series(...args),
        refreshCatalogJellyfinStatus: (...args) => services.actions.refreshCatalogJellyfinStatus(...args),
        discoveryV2MergeItems: (...args) => discoveryPolicy.discoveryV2MergeItems(...args),
        homeMovieEntry: item => services.actions.homeMovieEntry(item), homeSeriesEntry: item => services.actions.homeSeriesEntry(item),
        onLoaded: () => { void recommendations.refresh(); },
      }),
  carousel: createCarousel(document.getElementById("tab-home"))
  };
  services.actions = createHomeActions({
    renderSeriesResults: (...args) => getDiscovery().seriesActions.renderSeriesResults(...args),
    renderAnimeResults: (...args) => getDiscovery().animeActions.renderAnimeResults(...args),
    getMovieHero: () => getDiscovery().movieHero,
    getHomeCatalog: () => services.homeCatalog,
    getCatalogJellyfin: () => getIntegrations().catalogJellyfin,
    getJellyfinStatusText: () => getCore().jellyfinStatusText,
    getSetCatalogJellyfinBadge: () => getCore().setCatalogJellyfinBadge,
    getSeriesState: () => getDiscovery().seriesState,
    getAnime: () => getDiscovery().anime,
    getSearch: () => getSearch().search,
    getTasteProfile: () => getProfile().tasteProfile,
    getMovieState: () => getDiscovery().movieState,
    getTasteRanking: () => services.tasteRanking,
    getHomeLanes: () => services.homeLanes,
    getDailyTop: () => services.dailyTop,
    getHomePresenter: () => services.homePresenter,
    getHeroSelection: () => services.heroSelection,
    getHero: () => services.hero,
    getHomeCards: () => services.homeCards,
    getRows: () => services.rows,
    getHomeData: () => services.homeData,
    getSearchSupport: () => getSearch().searchSupport,
    getArtwork: () => getDiscovery().artwork,
    getCarousel: () => services.carousel,
    getHomeLayout: () => services.homeLayout,
    getRailRenderer: () => services.railRenderer,
    getCardArtwork: () => getCore().cardArtwork,
    getSetMediaCardMeta: () => getCore().setMediaCardMeta,
  });
  return services;
}

export function prepareHome({ intelligence, getHome, personalStorageKey, getDiscovery }) {
  const recommendations = createRecommendations(document.getElementById("home-ai-rail"), {
      getConfig: intelligence.get, homeAllEntries: () => getHome().actions.homeAllEntries(),
      homeEntryKey: entry => getHome().actions.homeEntryKey(entry), homeEntryMedia: entry => getHome().actions.homeEntryMedia(entry),
      mediaJellyfinStatus: entry => getHome().actions.mediaJellyfinStatus(entry), createHomeCard: (...args) => getHome().actions.createHomeCard(...args),
      syncHomeCardContent: (...args) => getHome().actions.syncHomeCardContent(...args),
      reconcileHomeRail: (...args) => getHome().actions.reconcileHomeRail(...args), updateHomeRailNavigation: (...args) => getHome().actions.updateHomeRailNavigation(...args),
    });
  const discoveryPolicy = createDiscoveryPolicy({
      personalStorageKey, homeEntryMedia: (...args) => getHome().actions.homeEntryMedia(...args), homeEntryKey: (...args) => getHome().actions.homeEntryKey(...args), localDateKey: (...args) => getHome().actions.localDateKey(...args),
      getShuffle: () => getHome().homePresenter.get().discoveryShuffle, stableDiscoveryHash: (...args) => getHome().actions.stableDiscoveryHash(...args), mediaContentLanguages: (...args) => getDiscovery().movieActions.mediaContentLanguages(...args),
      getHomeData: () => getHome().homeData.get(), homeMovieEntry: (...args) => getHome().actions.homeMovieEntry(...args), homeSeriesEntry: (...args) => getHome().actions.homeSeriesEntry(...args),
      allowedHomeEntries: entries => getHome().actions.allowedHomeEntries(entries), uniqueHomeEntries: (...args) => getHome().actions.uniqueHomeEntries(...args), normalizeUiContentLanguage: (...args) => getDiscovery().movieActions.normalizeUiContentLanguage(...args),
    });
  return { recommendations, discoveryPolicy };
}

export function initializeHome({ getHome, artworkUrls, discoveryPolicy, getCore, state, getDiscovery, movieState, getIntegrations }) {
  getHome().hero = createHero(document.getElementById("tab-home"), {
      homeHeroCandidates: () => getHome().actions.homeHeroCandidates(), coverUrl: url => artworkUrls.coverUrl(url),
      onRendered: entry => discoveryPolicy.recordDiscoveryExposureV2("hero", [entry]),
      onRender: () => getHome().actions.renderHomeHero(), openEntry: (kind, key) => getHome().actions.openHomeEntry(kind, key),
      openLibrary: () => getCore().actions.switchTab("bibliothek"),
    });
  getHome().mood = createMood(document.getElementById("mood-modal"), {
      model: { homeEntryMedia: (...args) => getHome().actions.homeEntryMedia(...args), homeEntryKey: (...args) => getHome().actions.homeEntryKey(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args), loadDiscoveryProfile: (...args) => getHome().actions.loadDiscoveryProfile(...args), stableDiscoveryHash: (...args) => getHome().actions.stableDiscoveryHash(...args), localDateKey: (...args) => getHome().actions.localDateKey(...args),
        allowedHomeEntries: entries => getHome().actions.allowedHomeEntries(entries), homeAllEntries: (...args) => getHome().actions.homeAllEntries(...args), uniqueHomeContentEntries: (...args) => getHome().actions.uniqueHomeContentEntries(...args), uniqueHomeEntries: (...args) => getHome().actions.uniqueHomeEntries(...args) },
      homeEntryMedia: (...args) => getHome().actions.homeEntryMedia(...args), homeEntryKey: (...args) => getHome().actions.homeEntryKey(...args), homeAllEntries: (...args) => getHome().actions.homeAllEntries(...args), coverCandidates: url => artworkUrls.coverCandidates(url),
      hydrateHomeMovieArtwork: (...args) => getHome().actions.hydrateHomeMovieArtwork(...args), hydrateHomeSeriesArtwork: (...args) => getHome().actions.hydrateHomeSeriesArtwork(...args), openHomeEntry: (...args) => getHome().actions.openHomeEntry(...args), stopHomeHeroRotation: (...args) => getHome().actions.stopHomeHeroRotation(...args), scheduleHomeHeroRotation: (...args) => getHome().actions.scheduleHomeHeroRotation(...args),
      isHome: () => state.tab === "home",
    });
  getHome().cardDock = createCardDock(document.getElementById("tab-home"), {
      trailers: getDiscovery().trailers, homeEntryMedia: (...args) => getHome().actions.homeEntryMedia(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args), mediaCardInitials: (...args) => getDiscovery().movieActions.mediaCardInitials(...args),
      openHomeEntry: (...args) => getHome().actions.openHomeEntry(...args), toggleFpPick: (...args) => getDiscovery().movieActions.toggleFpPick(...args), getMovie: slug => movieState.moviesCache[slug],
      acceptMetadata(slug, movie) { movieState.metadataCache[slug] = { ...movieState.metadataCache[slug], ...movie }; },
      isQueued: slug => state.queuedSlugs.has(slug), normalizeHomeRailLoop: (...args) => getHome().actions.normalizeHomeRailLoop(...args),
    });
  getHome().railRenderer = createRailRenderer(document.getElementById("tab-home"), {
      artwork: getCore().cardArtwork, carousel: getHome().carousel,
      homeEntryMedia: (...args) => getHome().actions.homeEntryMedia(...args), homeEntryKey: (...args) => getHome().actions.homeEntryKey(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args), getJellyfinStatus: key => getIntegrations().catalogJellyfin.getStatus(key),
    });
  getHome().homeLayout = createHomeLayout(document.getElementById("tab-home"), document.getElementById("home-layout-modal"), {
      carousel: getHome().carousel, render: () => getHome().actions.renderHome(), stopRotation: () => getHome().actions.stopHomeHeroRotation(),
    });
  getHome().rows = createHomeRows(document.getElementById("tab-home"), {
      isLoading: () => getHome().homeData.get().loading,
      onRendered(trackId, entries, options) {
        const lane = { "home-movies-track": "personal", "home-explore-track": "explore", "home-series-track": "series",
          "home-top-track": "top", "home-genre-track": "genre", "home-gems-track": "gems" }[trackId];
        if (lane) discoveryPolicy.recordDiscoveryExposureV2(lane, entries.slice(0, options.layout === "spotlight" ? 7 : options.ranked ? 10 : 16));
      },
      reconcileHomeRail: (...args) => getHome().actions.reconcileHomeRail(...args), homeRailCardSignature: (...args) => getHome().actions.homeRailCardSignature(...args),
      createHomeCard: (...args) => getHome().actions.createHomeCard(...args), syncHomeCardContent: (...args) => getHome().actions.syncHomeCardContent(...args),
    });
}
