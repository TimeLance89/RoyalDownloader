import { createSeriesState } from "../features/discovery/series-state.js";
import { createMovieState } from "../features/discovery/movie-state.js";
import { createCollectionActions } from "../features/collections/actions.js";
import { createAniworldActions } from "../features/discovery/aniworld-actions.js";
import { createAnimeActions } from "../features/discovery/anime-actions.js";
import { createSeriesActions } from "../features/discovery/series-actions.js";
import { createMovieActions } from "../features/discovery/movie-actions.js";
import { WATCH_MODE_DEFAULT } from "../shared/constants/watch-policy.js";
import { WATCH_MODE_LABELS } from "../shared/constants/watch-policy.js";
import { createDetailDiscovery } from "../features/media-details/discovery.js";

import { createMoviePresentation } from "../features/discovery/movie-presentation.js";

import { createSeriesStatus } from "../features/media-details/series-status.js";
import { createResultCards } from "../shared/components/result-card.js";

import { createSeriesPresentation } from "../features/discovery/series-presentation.js";

import { createSeriesEpisodes } from "../features/media-details/series-episodes.js";

import { createMovieCollections } from "../features/collections/index.js";
import { createPeople } from "../features/people/index.js";

import { createAniworld } from "../features/discovery/aniworld.js";

import { createAnime } from "../features/discovery/anime.js";

import { createSeriesChecks } from "../features/media-details/series-checks.js";

import { createSeriesDetailsLoader } from "../features/media-details/series-loader.js";

import { createMovieDetailsLoader } from "../features/media-details/movie-loader.js";

import { createMovieFilters } from "../features/discovery/movie-filters.js";

import { createSeriesBrowse } from "../features/discovery/series-browse.js";

import { createMovieBrowse } from "../features/discovery/movie-browse.js";

import { createCatalogIdentity } from "../features/discovery/catalog-identity.js";
import { createCatalogSeed } from "../features/discovery/catalog-seed.js";

import { createCatalogMetadata } from "../features/discovery/catalog-metadata.js";

import { createPosterPreloader } from "../features/discovery/poster-preload.js";
import { createCatalogRefresh } from "../features/discovery/catalog-refresh.js";
import { createMediaLanguage } from "../features/media-details/language.js";
import { createTrailers } from "../features/trailers/index.js";
import { createGenres } from "../features/discovery/genres.js";
import { createInfiniteScroll } from "../shared/components/infinite-scroll.js";

import { createCatalogArtwork } from "../features/discovery/artwork.js";

import { createMovieHero } from "../features/discovery/movie-hero.js";

export function composeDiscovery({ movieState, seriesState, artworkUrls, i18n, state, getCore, getIntegrations, getDownloads, getSubscriptions, getHome, getSettings }) {
  const services = {
  movieState,
  seriesState,
  people: createPeople(document.getElementById("tab-personen"), {
    coverUrl: url => artworkUrls.coverUrl(url),
    openMovie: (...args) => services.movieActions.selectFpRow(...args),
    openSeries: (...args) => services.seriesActions.loadSeries(...args),
    openFilms: (...args) => services.movieCollections.openFilms(...args),
  }),
  movieDiscovery: createDetailDiscovery(document.getElementById("fp-detail-modal"), {
        openPerson: id => { getCore().actions.switchTab("personen"); void services.people.open(id); },
        kind: "movie", coverUrl: url => artworkUrls.coverUrl(url), selectFpRow: (...args) => services.movieActions.selectFpRow(...args), loadSeries: (...args) => services.seriesActions.loadSeries(...args), fpTrailerYoutubeKey: (...args) => services.movieActions.fpTrailerYoutubeKey(...args), openFpTrailerModal: (...args) => services.movieActions.openFpTrailerModal(...args),
      }),
  seriesDiscovery: createDetailDiscovery(document.getElementById("series-detail-modal"), {
        openPerson: id => { getCore().actions.switchTab("personen"); void services.people.open(id); },
        kind: "series", coverUrl: url => artworkUrls.coverUrl(url), selectFpRow: (...args) => services.movieActions.selectFpRow(...args), loadSeries: (...args) => services.seriesActions.loadSeries(...args), fpTrailerYoutubeKey: (...args) => services.movieActions.fpTrailerYoutubeKey(...args), openFpTrailerModal: (...args) => services.movieActions.openFpTrailerModal(...args),
      }),
  moviePresentation: createMoviePresentation(document.getElementById("tab-filme"), document.getElementById("fp-detail-modal"), {
        locale: () => i18n.locale(), movieState, getQueuedSlugs: () => state.queuedSlugs, coverUrl: url => artworkUrls.coverUrl(url),
        subscriptionFor: (...args) => getSubscriptions().movieSubscriptionFor(...args),
        openSubscription: (...args) => getSubscriptions().movieSubscriptionRules.open(...args),
        activateResultCard: (...args) => services.movieActions.activateResultCard(...args), applyFpSmartFilters: (...args) => services.movieActions.applyFpSmartFilters(...args), configureFpDetailAction: (...args) => services.movieActions.configureFpDetailAction(...args), configureFpTrailer: (...args) => services.movieActions.configureFpTrailer(...args), createResultCardVisual: (...args) => services.movieActions.createResultCardVisual(...args), dedupeCatalogMedia: (...args) => getSubscriptions().actions.dedupeCatalogMedia(...args), discardObservedResultPosters: (...args) => services.movieActions.discardObservedResultPosters(...args), fpMetadataPreloadItems: (...args) => services.movieActions.fpMetadataPreloadItems(...args), fpSmartFilteredResults: (...args) => services.movieActions.fpSmartFilteredResults(...args), fpSmartFilters: (...args) => services.movieActions.fpSmartFilters(...args), homeMovieBySlug: (...args) => getHome().actions.homeMovieBySlug(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args), mergeFpMetadata: (...args) => services.movieActions.mergeFpMetadata(...args), preloadTmdbMetadata: (...args) => services.movieActions.preloadTmdbMetadata(...args), refreshFpJellyfinStatus: (...args) => services.movieActions.refreshFpJellyfinStatus(...args), refreshMovieFeatureCandidates: (...args) => getHome().actions.refreshMovieFeatureCandidates(...args), renderFpAbout: (...args) => services.movieActions.renderFpAbout(...args), renderFpExtras: (...args) => services.movieActions.renderFpExtras(...args), renderFpSimilarTitles: (...args) => services.movieActions.renderFpSimilarTitles(...args), scheduleFpCatalogRefresh: (...args) => services.movieActions.scheduleFpCatalogRefresh(...args), selectFpRow: (...args) => services.movieActions.selectFpRow(...args), setCatalogJellyfinBadge: (...args) => getHome().actions.setCatalogJellyfinBadge(...args), syncResultCardPoster: (...args) => services.movieActions.syncResultCardPoster(...args), toggleFpPick: (...args) => services.movieActions.toggleFpPick(...args), updateTasteFeedbackButtons: (...args) => getHome().actions.updateTasteFeedbackButtons(...args),
      }),
  seriesStatus: createSeriesStatus(document.getElementById("series-status"), document.getElementById("series-jellyfin-status")),
  resultCards: createResultCards(document, {
        coverCandidates: url => artworkUrls.coverThumbnailCandidates(url), mediaCardInitials: (...args) => services.movieActions.mediaCardInitials(...args), scheduleResultPoster: (...args) => services.movieActions.scheduleResultPoster(...args),
        discardPoster: image => getCore().cardArtwork.discard(image), setFpPosterJellyfinBadge: (...args) => services.movieActions.setFpPosterJellyfinBadge(...args),
        markLanguage: (node, media) => services.mediaLanguage.mark(node, media),
      }),
  seriesPresentation: createSeriesPresentation(document.getElementById("tab-serien"), document.getElementById("series-detail-modal"), {
        watchModeLabel: mode => WATCH_MODE_LABELS[mode] || WATCH_MODE_LABELS[WATCH_MODE_DEFAULT],
        seriesState, getHomeData: () => getHome().homeData.get(), coverUrl: url => artworkUrls.coverUrl(url),
        activateResultCard: (...args) => services.movieActions.activateResultCard(...args), configureSeriesTrailer: (...args) => services.seriesActions.configureSeriesTrailer(...args), createResultCardVisual: (...args) => services.movieActions.createResultCardVisual(...args), dedupeCatalogMedia: (...args) => getSubscriptions().actions.dedupeCatalogMedia(...args), discardObservedResultPosters: (...args) => services.movieActions.discardObservedResultPosters(...args), homeSeriesEntry: (...args) => getHome().actions.homeSeriesEntry(...args), hydrateHomeSeriesArtwork: (...args) => getHome().actions.hydrateHomeSeriesArtwork(...args), isEpisodeEligible: (...args) => services.seriesActions.isEpisodeEligible(...args), loadSeries: (...args) => services.seriesActions.loadSeries(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args), mergeCatalogItems: (...args) => services.movieActions.mergeCatalogItems(...args), mergeCatalogSources: (...args) => services.movieActions.mergeCatalogSources(...args), openMediaModal: (...args) => getCore().actions.openMediaModal(...args), recheckSeriesInfinite: (...args) => getCore().actions.recheckSeriesInfinite(...args), refreshCatalogJellyfinStatus: (...args) => getHome().actions.refreshCatalogJellyfinStatus(...args), renderSeriesDetailDiscovery: (...args) => services.seriesActions.renderSeriesDetailDiscovery(...args), renderSeriesTiles: (...args) => services.seriesActions.renderSeriesTiles(...args), setFpJellyfinBadge: (...args) => services.movieActions.setFpJellyfinBadge(...args), setFpPosterJellyfinBadge: (...args) => services.movieActions.setFpPosterJellyfinBadge(...args), syncResultCardPoster: (...args) => services.movieActions.syncResultCardPoster(...args), syncSeriesQueueFlags: (...args) => services.seriesActions.syncSeriesQueueFlags(...args), updateSeriesJellyfinBadge: (...args) => services.movieActions.updateSeriesJellyfinBadge(...args), updateSeriesStatus: (...args) => services.movieActions.updateSeriesStatus(...args), updateTasteFeedbackButtons: (...args) => getHome().actions.updateTasteFeedbackButtons(...args), verifyHuhuEpisodeLanguages: (...args) => services.seriesActions.verifyHuhuEpisodeLanguages(...args),
      }),
  seriesEpisodes: createSeriesEpisodes(document.getElementById("series-detail-modal"), {
        isQueueLoaded: () => state.queue.loaded, status: document.getElementById("series-status"), seriesState, getQueuedSlugs: () => state.queuedSlugs,
        getEnabledLanguages: () => getSettings().providers.get()?.contentLanguages,
        verifyHuhuEpisodeLanguages: (...args) => services.seriesActions.verifyHuhuEpisodeLanguages(...args), trackDiscoveryPreference: (...args) => getHome().actions.trackDiscoveryPreference(...args), refreshQueueUiAfterChange: (...args) => getCore().actions.refreshQueueUiAfterChange(...args),
      }),
  movieCollections: createMovieCollections(document.getElementById("movie-collection-modal"), {
        getMovieCache: () => movieState.moviesCache, getMetadataCache: () => movieState.metadataCache,
        getQueuedSlugs: () => state.queuedSlugs, coverCandidates: url => artworkUrls.coverCandidates(url), coverUrl: url => artworkUrls.coverUrl(url),
        mediaCardInitials: (...args) => services.movieActions.mediaCardInitials(...args), openMediaModal: (...args) => getCore().actions.openMediaModal(...args), selectFpRow: (...args) => services.movieActions.selectFpRow(...args), applyMovieJellyfinStatus: (...args) => getHome().actions.applyMovieJellyfinStatus(...args), refreshQueueUiAfterChange: (...args) => getCore().actions.refreshQueueUiAfterChange(...args),
      }),
  aniworld: createAniworld(document.getElementById("tab-aniworld"), document.getElementById("aniworld-detail-modal"), {
        getQueuedSlugs: () => state.queuedSlugs, coverUrl: value => artworkUrls.coverUrl(value),
        mediaCardInitials: (...args) => services.movieActions.mediaCardInitials(...args), openMediaModal: (...args) => getCore().actions.openMediaModal(...args), recheckAniworldInfinite: (...args) => getCore().actions.recheckAniworldInfinite(...args), refreshQueueUiAfterChange: (...args) => getCore().actions.refreshQueueUiAfterChange(...args),
      }),
  anime: createAnime(document.getElementById("tab-anime"), document.getElementById("anime-detail-modal"), {
        getQueuedSlugs: () => state.queuedSlugs, coverUrl: value => artworkUrls.coverUrl(value),
        mediaCardInitials: (...args) => services.movieActions.mediaCardInitials(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args), jellyfinStatusText: (...args) => getHome().actions.jellyfinStatusText(...args),
        refreshCatalogJellyfinStatus: (...args) => getHome().actions.refreshCatalogJellyfinStatus(...args), homeAnimeEntry: (...args) => getHome().actions.homeAnimeEntry(...args),
        openMediaModal: (...args) => getCore().actions.openMediaModal(...args), trackDiscoveryPreference: (...args) => getHome().actions.trackDiscoveryPreference(...args), refreshQueueUiAfterChange: (...args) => getCore().actions.refreshQueueUiAfterChange(...args),
      }),
  seriesChecks: createSeriesChecks(document.getElementById("series-status"), {
        seriesState, isVisible: () => !document.getElementById("series-detail-modal").hidden,
        firstEpisodeSlug: (...args) => services.seriesActions.firstEpisodeSlug(...args), pruneSeriesEpisodeSelection: (...args) => services.seriesActions.pruneSeriesEpisodeSelection(...args), refreshSeriesTileStates: (...args) => services.seriesActions.refreshSeriesTileStates(...args),
        updateSeriesStatus: (...args) => services.movieActions.updateSeriesStatus(...args), syncSeriesQueueFlags: (...args) => services.seriesActions.syncSeriesQueueFlags(...args), seriesStructureFingerprint: (...args) => services.seriesActions.seriesStructureFingerprint(...args), mergeSeriesDetailPayload: (...args) => services.seriesActions.mergeSeriesDetailPayload(...args),
        updateSeriesOverview: (...args) => services.seriesActions.updateSeriesOverview(...args), updateWatchBtn: (...args) => services.seriesActions.updateWatchBtn(...args), renderSeriesTiles: (...args) => services.seriesActions.renderSeriesTiles(...args),
      }),
  seriesDetailsLoader: createSeriesDetailsLoader(document.getElementById("series-detail-modal"), document.getElementById("series-status"), {
        verifyHuhuEpisodeLanguages: (...args) => services.seriesActions.verifyHuhuEpisodeLanguages(...args),
        updateSeriesOverview: (...args) => services.seriesActions.updateSeriesOverview(...args),
        updateSeriesJellyfinBadge: (...args) => services.movieActions.updateSeriesJellyfinBadge(...args),
        seriesState, trackDiscoveryPreference: (...args) => getHome().actions.trackDiscoveryPreference(...args), updateSeriesResultSelection: (...args) => services.seriesActions.updateSeriesResultSelection(...args), showSeriesLoading: (...args) => services.seriesActions.showSeriesLoading(...args),
        openMediaModal: (...args) => getCore().actions.openMediaModal(...args), findSeriesResultCard: (...args) => services.seriesActions.findSeriesResultCard(...args), showSeriesDetail: (...args) => services.seriesActions.showSeriesDetail(...args), updateSeriesStatus: (...args) => services.movieActions.updateSeriesStatus(...args),
        refreshSeriesJellyfinStatus: (...args) => services.movieActions.refreshSeriesJellyfinStatus(...args), switchTab: (...args) => getCore().actions.switchTab(...args), firstEpisodeSlug: (...args) => services.seriesActions.firstEpisodeSlug(...args), seriesEpisodes: (...args) => services.seriesActions.seriesEpisodes(...args), isEpisodeSelectable: (...args) => services.seriesActions.isEpisodeSelectable(...args),
        renderSeriesTiles: (...args) => services.seriesActions.renderSeriesTiles(...args), syncWatchlistSnapshot: (...args) => getCore().actions.syncWatchlistSnapshot(...args),
      }),
  movieDetailsLoader: createMovieDetailsLoader({
        movieState, updateFpResultSelection: (...args) => services.movieActions.updateFpResultSelection(...args), homeMovieBySlug: (...args) => getHome().actions.homeMovieBySlug(...args), trackDiscoveryPreference: (...args) => getHome().actions.trackDiscoveryPreference(...args), showFpDetail: (...args) => services.movieActions.showFpDetail(...args),
        metadataPreviewMovie: (...args) => services.movieActions.metadataPreviewMovie(...args), basicMovieMetadata: (...args) => services.movieActions.basicMovieMetadata(...args), setFpDetailAvailability: (...args) => services.movieActions.setFpDetailAvailability(...args), openMediaModal: (...args) => getCore().actions.openMediaModal(...args),
        findFpResultCard: (...args) => services.movieActions.findFpResultCard(...args), updateFpResultCard: (...args) => services.movieActions.updateFpResultCard(...args), refreshMovieFeatureCandidates: (...args) => getHome().actions.refreshMovieFeatureCandidates(...args), refreshFpJellyfinStatus: (...args) => services.movieActions.refreshFpJellyfinStatus(...args),
      }),
  movieFilters: createMovieFilters(document.getElementById("tab-filme"), {
        movieState, getQueuedSlugs: () => state.queuedSlugs, fpResultMedia: (...args) => services.movieActions.fpResultMedia(...args), fpResultYear: (...args) => services.movieActions.fpResultYear(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args), mediaContentLanguages: (...args) => services.movieActions.mediaContentLanguages(...args),
        fpStatusMessage: (...args) => services.movieActions.fpStatusMessage(...args), fpGenreChange: (...args) => services.movieActions.fpGenreChange(...args),
      }),
  seriesBrowse: createSeriesBrowse(document.getElementById("tab-serien"), {
        seriesState, getActiveTab: () => state.tab, syncSearchClearButtons: (...args) => getHome().actions.syncSearchClearButtons(...args), closeSearchSuggestions: (...args) => getHome().actions.closeSearchSuggestions(...args), rememberSearch: (...args) => getHome().actions.rememberSearch(...args),
        applySeriesResults: (...args) => services.seriesActions.applySeriesResults(...args), renderSeriesTiles: (...args) => services.seriesActions.renderSeriesTiles(...args),
        updateSeriesInfiniteState: (...args) => services.seriesActions.updateSeriesInfiniteState(...args), showSeriesDetail: (...args) => services.seriesActions.showSeriesDetail(...args), firstEpisodeSlug: (...args) => services.seriesActions.firstEpisodeSlug(...args), updateSeriesStatus: (...args) => services.movieActions.updateSeriesStatus(...args),
        refreshSeriesJellyfinStatus: (...args) => services.movieActions.refreshSeriesJellyfinStatus(...args), recheckSeriesInfinite: (...args) => getCore().actions.recheckSeriesInfinite(...args), preloadSeriesPosterImages: (...args) => services.movieActions.preloadSeriesPosterImages(...args),
        syncSeriesCatalogFromHome: (...args) => services.movieActions.syncSeriesCatalogFromHome(...args), renderSeriesResults: (...args) => services.seriesActions.renderSeriesResults(...args), refreshSeriesCatalogInBackground: (...args) => services.movieActions.refreshSeriesCatalogInBackground(...args),
      }),
  movieBrowse: createMovieBrowse(document.getElementById("tab-filme"), {
        movieState, getActiveTab: () => state.tab, syncSearchClearButtons: (...args) => getHome().actions.syncSearchClearButtons(...args), closeSearchSuggestions: (...args) => getHome().actions.closeSearchSuggestions(...args), rememberSearch: (...args) => getHome().actions.rememberSearch(...args),
        applyFpResults: (...args) => services.movieActions.applyFpResults(...args), setActiveGenreFilter: (...args) => services.movieActions.setActiveGenreFilter(...args),
        renderFpResults: (...args) => services.movieActions.renderFpResults(...args), updateFpInfiniteState: (...args) => services.movieActions.updateFpInfiniteState(...args), refreshMovieFeatureCandidates: (...args) => getHome().actions.refreshMovieFeatureCandidates(...args),
        syncFpCatalogFromHome: (...args) => services.movieActions.syncFpCatalogFromHome(...args), refreshFpCatalogInBackground: (...args) => services.movieActions.refreshFpCatalogInBackground(...args),
        getGenres: () => services.genres.get(), applyFpSmartFilters: (...args) => services.movieActions.applyFpSmartFilters(...args), resetFpSmartFilters: (...args) => services.movieActions.resetFpSmartFilters(...args),
        setFilter: (key, value) => services.movieFilters.set(key, value),
        cancelMetadata: () => services.catalogMetadata.unmount(),
      }),
  catalogIdentity: createCatalogIdentity({ getMetadata: slug => movieState.metadataCache[slug] }),
  catalogSeed: createCatalogSeed({
        movieState, seriesState, getActiveTab: () => state.tab, getHomeData: () => getHome().homeData.get(),
        mergeFpMetadata: (...args) => services.movieActions.mergeFpMetadata(...args), fpMetadataPreloadItems: (...args) => services.movieActions.fpMetadataPreloadItems(...args), preloadTmdbMetadata: (...args) => services.movieActions.preloadTmdbMetadata(...args),
        renderFpResults: (...args) => services.movieActions.renderFpResults(...args), refreshMovieFeatureCandidates: (...args) => getHome().actions.refreshMovieFeatureCandidates(...args),
        updateFpInfiniteState: (...args) => services.movieActions.updateFpInfiniteState(...args), recheckFpInfinite: (...args) => getCore().actions.recheckFpInfinite(...args),
        renderSeriesResults: (...args) => services.seriesActions.renderSeriesResults(...args), renderSeriesCatalogHero: (...args) => services.seriesActions.renderSeriesCatalogHero(...args),
        updateSeriesInfiniteState: (...args) => services.seriesActions.updateSeriesInfiniteState(...args), recheckSeriesInfinite: (...args) => getCore().actions.recheckSeriesInfinite(...args),
      }),
  catalogMetadata: createCatalogMetadata({
        movieState, updateFpResultCard: slug => services.movieActions.updateFpResultCard(slug),
        refreshFpJellyfinStatus: items => services.movieActions.refreshFpJellyfinStatus(items),
        refreshMovieFeatureCandidates: () => getHome().actions.refreshMovieFeatureCandidates(),
        showFpDetail: (...args) => services.movieActions.showFpDetail(...args), metadataPreviewMovie: (...args) => services.movieActions.metadataPreviewMovie(...args),
        reconcileMovieCatalogDuplicates: () => getSubscriptions().actions.reconcileMovieCatalogDuplicates(),
      }),
  posterPreloader: createPosterPreloader({ candidates: value => artworkUrls.coverThumbnailCandidates(value) }),
  catalogRefresh: createCatalogRefresh({
        movieState, seriesState, applyFpResults: (...args) => services.movieActions.applyFpResults(...args),
        applySeriesResults: (...args) => services.seriesActions.applySeriesResults(...args),
        mergeCatalogItems: (...args) => services.movieActions.mergeCatalogItems(...args),
        preloadSeriesPosterImages: (...args) => services.movieActions.preloadSeriesPosterImages(...args),
      }),
  mediaLanguage: createMediaLanguage(document, { getProviders: () => getSettings().providers.get() }),
  trailers: createTrailers(document),
  genres: createGenres(document.getElementById("tab-filme"), {
        getActive: () => movieState.activeGenre,
        select(value) { movieState.activeGenre = value; services.movieActions.setActiveGenreFilter(value); },
        onChange: () => services.movieActions.applyFpSmartFilters(),
      }),
  infinite: {
        movies: createInfiniteScroll(document.getElementById("tab-filme"), {
          sentinel: document.getElementById("fp-infinite"), retryButton: document.getElementById("fp-infinite-retry"),
          loadNext: () => services.movieActions.loadNextFpPage(), retry() {
            if (movieState.loadingMore || !movieState.category) return;
            if (movieState.lastPageFull) services.movieActions.loadNextFpPage();
            else if (movieState.category === "genre") services.movieActions.fpGenreChange(movieState.activeGenre);
            else services.movieActions.fpShowList(movieState.category);
          },
        }),
        series: createInfiniteScroll(document.getElementById("tab-serien"), {
          sentinel: document.getElementById("series-infinite"), retryButton: document.getElementById("series-infinite-retry"),
          loadNext: () => services.seriesActions.loadNextSeriesPage(), retry() {
            const mode = seriesState.browseMode;
            if (seriesState.loadingBrowse || !mode || mode === "search") return;
            if (seriesState.lastPageFull) services.seriesActions.loadNextSeriesPage({ retry: true }); else services.seriesActions.seriesBrowse(mode, 1);
          },
        }),
        aniworld: createInfiniteScroll(document.getElementById("tab-aniworld"), {
          sentinel: document.getElementById("aniworld-infinite"), loadNext: () => services.aniworldActions.loadNextAniworldPage(),
        }),
      },
  artwork: createCatalogArtwork({
        getMovieMetadata: () => movieState.metadataCache,
        renderHome: () => getHome().actions.renderHome(), saveHomeCache: () => getHome().actions.saveHomeCache(),
        onSeriesHydrated: () => getSubscriptions().actions.reconcileSeriesCatalogDuplicates(),
      }),
  movieHero: createMovieHero(document.getElementById("movie-feature"), {
        getCatalog: () => movieState, getProviderLabels: () => getSettings().providers.get().labels,
        coverUrl: url => artworkUrls.coverUrl(url), locale: () => i18n.locale(),
        openMovie: slug => services.movieActions.selectFpRow(slug), onUpdateHome: () => getHome().actions.renderHomeHero(),
      })
  };
  services.movieActions = createMovieActions({
    getMovieFilters: () => services.movieFilters,
    getCatalogRefresh: () => services.catalogRefresh,
    getCardArtwork: () => getCore().cardArtwork,
    getCatalogMetadata: () => services.catalogMetadata,
    getPosterPreloader: () => services.posterPreloader,
    getCatalogSeed: () => services.catalogSeed,
    getMovieStatus: () => getIntegrations().movieStatus,
    getSeriesStatus: () => services.seriesStatus,
    getSeriesChecks: () => services.seriesChecks,
    getCleanMediaCardInitials: () => getCore().cleanMediaCardInitials,
    getResultCards: () => services.resultCards,
    getMovieBrowse: () => services.movieBrowse,
    getMovieDownloads: () => getDownloads().movieDownloads,
    getMovieDetailsLoader: () => services.movieDetailsLoader,
    getTrailers: () => services.trailers,
    getMediaLanguage: () => services.mediaLanguage,
    getMoviePresentation: () => services.moviePresentation,
    getMovieDiscovery: () => services.movieDiscovery,
  });
  services.seriesActions = createSeriesActions({
    getSeriesEpisodes: () => services.seriesEpisodes,
    getSeriesChecks: () => services.seriesChecks,
    getSeriesBrowse: () => services.seriesBrowse,
    getSeriesDetailsLoader: () => services.seriesDetailsLoader,
    getTrailers: () => services.trailers,
    getSeriesPresentation: () => services.seriesPresentation,
    getSeriesDiscovery: () => services.seriesDiscovery,
  });
  services.animeActions = createAnimeActions({
    getAnime: () => services.anime,
    getSubscriptions: () => getSubscriptions().subscriptions,
    getSubscriptionRules: () => getSubscriptions().subscriptionRules,
  });
  services.aniworldActions = createAniworldActions({
    getAniworld: () => services.aniworld,
  });
  services.collectionActions = createCollectionActions({
    getMovieCollections: () => services.movieCollections,
  });
  return services;
}

export function prepareDiscovery() {
  const movieState = createMovieState(), seriesState = createSeriesState();
  return { movieState, seriesState };
}
