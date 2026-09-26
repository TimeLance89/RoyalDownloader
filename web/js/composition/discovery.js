import { createDetailDiscovery } from "../features/media-details/discovery.js";
import { selectFpRow } from "../shell/actions/movies.js";
import { loadSeries } from "../shell/actions/series.js";
import { fpTrailerYoutubeKey } from "../shell/actions/movies.js";
import { openFpTrailerModal } from "../shell/actions/movies.js";
import { createMoviePresentation } from "../features/discovery/movie-presentation.js";
import { state } from "../shell/presentation.js";
import { sharedPresentation } from "../shell/presentation.js";
import { activateResultCard } from "../shell/actions/movies.js";
import { applyFpSmartFilters } from "../shell/actions/movies.js";
import { configureFpDetailAction } from "../shell/actions/movies.js";
import { configureFpTrailer } from "../shell/actions/movies.js";
import { createResultCardVisual } from "../shell/actions/movies.js";
import { dedupeCatalogMedia } from "../shell/actions/library.js";
import { discardObservedResultPosters } from "../shell/actions/movies.js";
import { fpMetadataPreloadItems } from "../shell/actions/movies.js";
import { fpSmartFilteredResults } from "../shell/actions/movies.js";
import { fpSmartFilters } from "../shell/actions/movies.js";
import { homeMovieBySlug } from "../shell/actions/home.js";
import { mediaJellyfinStatus } from "../shell/actions/home.js";
import { mergeFpMetadata } from "../shell/actions/movies.js";
import { preloadTmdbMetadata } from "../shell/actions/movies.js";
import { refreshFpJellyfinStatus } from "../shell/actions/movies.js";
import { refreshMovieFeatureCandidates } from "../shell/actions/home.js";
import { renderFpAbout } from "../shell/actions/movies.js";
import { renderFpExtras } from "../shell/actions/movies.js";
import { renderFpSimilarTitles } from "../shell/actions/movies.js";
import { scheduleFpCatalogRefresh } from "../shell/actions/movies.js";
import { setCatalogJellyfinBadge } from "../shell/actions/home.js";
import { syncResultCardPoster } from "../shell/actions/movies.js";
import { toggleFpPick } from "../shell/actions/movies.js";
import { updateTasteFeedbackButtons } from "../shell/actions/home.js";
import { createSeriesStatus } from "../features/media-details/series-status.js";
import { createResultCards } from "../shared/components/result-card.js";
import { mediaCardInitials } from "../shell/actions/movies.js";
import { scheduleResultPoster } from "../shell/actions/movies.js";
import { setFpPosterJellyfinBadge } from "../shell/actions/movies.js";
import { createSeriesPresentation } from "../features/discovery/series-presentation.js";
import { WATCH_MODE_LABELS } from "../shell/presentation.js";
import { WATCH_MODE_DEFAULT } from "../shell/presentation.js";
import { configureSeriesTrailer } from "../shell/actions/series.js";
import { homeSeriesEntry } from "../shell/actions/home.js";
import { hydrateHomeSeriesArtwork } from "../shell/actions/home.js";
import { isEpisodeEligible } from "../shell/actions/series.js";
import { mergeCatalogItems } from "../shell/actions/movies.js";
import { mergeCatalogSources } from "../shell/actions/movies.js";
import { openMediaModal } from "../shell/presentation.js";
import { recheckSeriesInfinite } from "../shell/presentation.js";
import { refreshCatalogJellyfinStatus } from "../shell/actions/home.js";
import { renderSeriesDetailDiscovery } from "../shell/actions/series.js";
import { renderSeriesTiles } from "../shell/actions/series.js";
import { setFpJellyfinBadge } from "../shell/actions/movies.js";
import { syncSeriesQueueFlags } from "../shell/actions/series.js";
import { updateSeriesJellyfinBadge } from "../shell/actions/movies.js";
import { updateSeriesStatus } from "../shell/actions/movies.js";
import { verifyHuhuEpisodeLanguages } from "../shell/actions/series.js";
import { createSeriesEpisodes } from "../features/media-details/series-episodes.js";
import { trackDiscoveryPreference } from "../shell/actions/home.js";
import { refreshQueueUiAfterChange } from "../shell/presentation.js";
import { createMovieCollections } from "../features/collections/index.js";
import { applyMovieJellyfinStatus } from "../shell/actions/home.js";
import { createAniworld } from "../features/discovery/aniworld.js";
import { recheckAniworldInfinite } from "../shell/presentation.js";
import { createAnime } from "../features/discovery/anime.js";
import { jellyfinStatusText } from "../shell/actions/home.js";
import { homeAnimeEntry } from "../shell/actions/home.js";
import { createSeriesChecks } from "../features/media-details/series-checks.js";
import { firstEpisodeSlug } from "../shell/actions/series.js";
import { pruneSeriesEpisodeSelection } from "../shell/actions/series.js";
import { refreshSeriesTileStates } from "../shell/actions/series.js";
import { seriesStructureFingerprint } from "../shell/actions/series.js";
import { mergeSeriesDetailPayload } from "../shell/actions/series.js";
import { updateSeriesOverview } from "../shell/actions/series.js";
import { updateWatchBtn } from "../shell/actions/series.js";
import { createSeriesDetailsLoader } from "../features/media-details/series-loader.js";
import { updateSeriesResultSelection } from "../shell/actions/series.js";
import { showSeriesLoading } from "../shell/actions/series.js";
import { findSeriesResultCard } from "../shell/actions/series.js";
import { showSeriesDetail } from "../shell/actions/series.js";
import { refreshSeriesJellyfinStatus } from "../shell/actions/movies.js";
import { switchTab } from "../shell/presentation.js";
import { seriesEpisodes } from "../shell/actions/series.js";
import { isEpisodeSelectable } from "../shell/actions/series.js";
import { syncWatchlistSnapshot } from "../shell/presentation.js";
import { createMovieDetailsLoader } from "../features/media-details/movie-loader.js";
import { updateFpResultSelection } from "../shell/actions/movies.js";
import { showFpDetail } from "../shell/actions/movies.js";
import { metadataPreviewMovie } from "../shell/actions/movies.js";
import { basicMovieMetadata } from "../shell/actions/movies.js";
import { setFpDetailAvailability } from "../shell/actions/movies.js";
import { findFpResultCard } from "../shell/actions/movies.js";
import { updateFpResultCard } from "../shell/actions/movies.js";
import { createMovieFilters } from "../features/discovery/movie-filters.js";
import { fpResultMedia } from "../shell/actions/movies.js";
import { fpResultYear } from "../shell/actions/movies.js";
import { mediaContentLanguages } from "../shell/actions/movies.js";
import { fpStatusMessage } from "../shell/actions/movies.js";
import { fpGenreChange } from "../shell/actions/movies.js";
import { createSeriesBrowse } from "../features/discovery/series-browse.js";
import { syncSearchClearButtons } from "../shell/actions/home.js";
import { closeSearchSuggestions } from "../shell/actions/home.js";
import { rememberSearch } from "../shell/actions/home.js";
import { applySeriesResults } from "../shell/actions/series.js";
import { updateSeriesInfiniteState } from "../shell/actions/series.js";
import { preloadSeriesPosterImages } from "../shell/actions/movies.js";
import { syncSeriesCatalogFromHome } from "../shell/actions/movies.js";
import { renderSeriesResults } from "../shell/actions/series.js";
import { refreshSeriesCatalogInBackground } from "../shell/actions/movies.js";
import { createMovieBrowse } from "../features/discovery/movie-browse.js";
import { applyFpResults } from "../shell/actions/movies.js";
import { setActiveGenreFilter } from "../shell/actions/movies.js";
import { renderFpResults } from "../shell/actions/movies.js";
import { updateFpInfiniteState } from "../shell/actions/movies.js";
import { syncFpCatalogFromHome } from "../shell/actions/movies.js";
import { refreshFpCatalogInBackground } from "../shell/actions/movies.js";
import { resetFpSmartFilters } from "../shell/actions/movies.js";
import { createCatalogIdentity } from "../features/discovery/catalog-identity.js";
import { createCatalogSeed } from "../features/discovery/catalog-seed.js";
import { recheckFpInfinite } from "../shell/presentation.js";
import { renderSeriesCatalogHero } from "../shell/actions/series.js";
import { createCatalogMetadata } from "../features/discovery/catalog-metadata.js";
import { reconcileMovieCatalogDuplicates } from "../shell/actions/library.js";
import { createPosterPreloader } from "../features/discovery/poster-preload.js";
import { createCatalogRefresh } from "../features/discovery/catalog-refresh.js";
import { createMediaLanguage } from "../features/media-details/language.js";
import { createTrailers } from "../features/trailers/index.js";
import { createGenres } from "../features/discovery/genres.js";
import { createInfiniteScroll } from "../shared/components/infinite-scroll.js";
import { loadNextFpPage } from "../shell/actions/movies.js";
import { fpShowList } from "../shell/actions/movies.js";
import { loadNextSeriesPage } from "../shell/actions/series.js";
import { seriesBrowse } from "../shell/actions/series.js";
import { loadNextAniworldPage } from "../shell/actions/aniworld.js";
import { createCatalogArtwork } from "../features/discovery/artwork.js";
import { renderHome } from "../shell/actions/home.js";
import { saveHomeCache } from "../shell/actions/home.js";
import { reconcileSeriesCatalogDuplicates } from "../shell/actions/library.js";
import { createMovieHero } from "../features/discovery/movie-hero.js";
import { renderHomeHero } from "../shell/actions/home.js";

export function composeDiscovery({ movieState, seriesState, artworkUrls, i18n }) {
return {
movieState,
seriesState,
movieDiscovery: createDetailDiscovery(document.getElementById("fp-detail-modal"), {
      kind: "movie", coverUrl: url => artworkUrls.coverUrl(url), selectFpRow, loadSeries, fpTrailerYoutubeKey, openFpTrailerModal,
    }),
seriesDiscovery: createDetailDiscovery(document.getElementById("series-detail-modal"), {
      kind: "series", coverUrl: url => artworkUrls.coverUrl(url), selectFpRow, loadSeries, fpTrailerYoutubeKey, openFpTrailerModal,
    }),
moviePresentation: createMoviePresentation(document.getElementById("tab-filme"), document.getElementById("fp-detail-modal"), {
      locale: () => i18n.locale(), movieState, getQueuedSlugs: () => state.queuedSlugs, coverUrl: url => artworkUrls.coverUrl(url),
      subscriptionFor: (...args) => sharedPresentation.movieSubscriptionFor(...args),
      openSubscription: (...args) => sharedPresentation.movieSubscriptionRules.open(...args),
      activateResultCard, applyFpSmartFilters, configureFpDetailAction, configureFpTrailer, createResultCardVisual, dedupeCatalogMedia, discardObservedResultPosters, fpMetadataPreloadItems, fpSmartFilteredResults, fpSmartFilters, homeMovieBySlug, mediaJellyfinStatus, mergeFpMetadata, preloadTmdbMetadata, refreshFpJellyfinStatus, refreshMovieFeatureCandidates, renderFpAbout, renderFpExtras, renderFpSimilarTitles, scheduleFpCatalogRefresh, selectFpRow, setCatalogJellyfinBadge, syncResultCardPoster, toggleFpPick, updateTasteFeedbackButtons,
    }),
seriesStatus: createSeriesStatus(document.getElementById("series-status"), document.getElementById("series-jellyfin-status")),
resultCards: createResultCards(document, {
      coverCandidates: url => artworkUrls.coverThumbnailCandidates(url), mediaCardInitials, scheduleResultPoster,
      discardPoster: image => sharedPresentation.cardArtwork.discard(image), setFpPosterJellyfinBadge,
      markLanguage: (node, media) => sharedPresentation.mediaLanguage.mark(node, media),
    }),
seriesPresentation: createSeriesPresentation(document.getElementById("tab-serien"), document.getElementById("series-detail-modal"), {
      watchModeLabel: mode => WATCH_MODE_LABELS[mode] || WATCH_MODE_LABELS[WATCH_MODE_DEFAULT],
      seriesState, getHomeData: () => sharedPresentation.homeData.get(), coverUrl: url => artworkUrls.coverUrl(url),
      activateResultCard, configureSeriesTrailer, createResultCardVisual, dedupeCatalogMedia, discardObservedResultPosters, homeSeriesEntry, hydrateHomeSeriesArtwork, isEpisodeEligible, loadSeries, mediaJellyfinStatus, mergeCatalogItems, mergeCatalogSources, openMediaModal, recheckSeriesInfinite, refreshCatalogJellyfinStatus, renderSeriesDetailDiscovery, renderSeriesTiles, setFpJellyfinBadge, setFpPosterJellyfinBadge, syncResultCardPoster, syncSeriesQueueFlags, updateSeriesJellyfinBadge, updateSeriesStatus, updateTasteFeedbackButtons, verifyHuhuEpisodeLanguages,
    }),
seriesEpisodes: createSeriesEpisodes(document.getElementById("series-detail-modal"), {
      isQueueLoaded: () => state.queue.loaded, status: document.getElementById("series-status"), seriesState, getQueuedSlugs: () => state.queuedSlugs,
      getEnabledLanguages: () => sharedPresentation.providers.get()?.contentLanguages,
      verifyHuhuEpisodeLanguages, trackDiscoveryPreference, refreshQueueUiAfterChange,
    }),
movieCollections: createMovieCollections(document.getElementById("movie-collection-modal"), {
      getMovieCache: () => movieState.moviesCache, getMetadataCache: () => movieState.metadataCache,
      getQueuedSlugs: () => state.queuedSlugs, coverCandidates: url => artworkUrls.coverCandidates(url), coverUrl: url => artworkUrls.coverUrl(url),
      mediaCardInitials, openMediaModal, selectFpRow, applyMovieJellyfinStatus, refreshQueueUiAfterChange,
    }),
aniworld: createAniworld(document.getElementById("tab-aniworld"), document.getElementById("aniworld-detail-modal"), {
      getQueuedSlugs: () => state.queuedSlugs, coverUrl: value => artworkUrls.coverUrl(value),
      mediaCardInitials, openMediaModal, recheckAniworldInfinite, refreshQueueUiAfterChange,
    }),
anime: createAnime(document.getElementById("tab-anime"), document.getElementById("anime-detail-modal"), {
      getQueuedSlugs: () => state.queuedSlugs, coverUrl: value => artworkUrls.coverUrl(value),
      mediaCardInitials, mediaJellyfinStatus, jellyfinStatusText,
      refreshCatalogJellyfinStatus: (...args) => refreshCatalogJellyfinStatus(...args), homeAnimeEntry,
      openMediaModal, trackDiscoveryPreference, refreshQueueUiAfterChange,
    }),
seriesChecks: createSeriesChecks(document.getElementById("series-status"), {
      seriesState, isVisible: () => !document.getElementById("series-detail-modal").hidden,
      firstEpisodeSlug, pruneSeriesEpisodeSelection, refreshSeriesTileStates,
      updateSeriesStatus, syncSeriesQueueFlags, seriesStructureFingerprint, mergeSeriesDetailPayload,
      updateSeriesOverview, updateWatchBtn, renderSeriesTiles,
    }),
seriesDetailsLoader: createSeriesDetailsLoader(document.getElementById("series-detail-modal"), document.getElementById("series-status"), {
      seriesState, trackDiscoveryPreference, updateSeriesResultSelection, showSeriesLoading,
      openMediaModal, findSeriesResultCard, showSeriesDetail, updateSeriesStatus,
      refreshSeriesJellyfinStatus, switchTab, firstEpisodeSlug, seriesEpisodes, isEpisodeSelectable,
      renderSeriesTiles, syncWatchlistSnapshot,
    }),
movieDetailsLoader: createMovieDetailsLoader({
      movieState, updateFpResultSelection, homeMovieBySlug, trackDiscoveryPreference, showFpDetail,
      metadataPreviewMovie, basicMovieMetadata, setFpDetailAvailability, openMediaModal,
      findFpResultCard, updateFpResultCard, refreshMovieFeatureCandidates, refreshFpJellyfinStatus,
    }),
movieFilters: createMovieFilters(document.getElementById("tab-filme"), {
      movieState, getQueuedSlugs: () => state.queuedSlugs, fpResultMedia, fpResultYear, mediaJellyfinStatus, mediaContentLanguages,
      fpStatusMessage, fpGenreChange,
    }),
seriesBrowse: createSeriesBrowse(document.getElementById("tab-serien"), {
      seriesState, getActiveTab: () => state.tab, syncSearchClearButtons, closeSearchSuggestions, rememberSearch,
      applySeriesResults: (...args) => applySeriesResults(...args), renderSeriesTiles,
      updateSeriesInfiniteState, showSeriesDetail, firstEpisodeSlug, updateSeriesStatus,
      refreshSeriesJellyfinStatus, recheckSeriesInfinite, preloadSeriesPosterImages,
      syncSeriesCatalogFromHome, renderSeriesResults, refreshSeriesCatalogInBackground,
    }),
movieBrowse: createMovieBrowse(document.getElementById("tab-filme"), {
      movieState, getActiveTab: () => state.tab, syncSearchClearButtons, closeSearchSuggestions, rememberSearch,
      applyFpResults: (...args) => applyFpResults(...args), setActiveGenreFilter,
      renderFpResults, updateFpInfiniteState, refreshMovieFeatureCandidates,
      syncFpCatalogFromHome, refreshFpCatalogInBackground,
      getGenres: () => sharedPresentation.genres.get(), applyFpSmartFilters, resetFpSmartFilters,
      setFilter: (key, value) => sharedPresentation.movieFilters.set(key, value),
      cancelMetadata: () => sharedPresentation.catalogMetadata.unmount(),
    }),
catalogIdentity: createCatalogIdentity({ getMetadata: slug => movieState.metadataCache[slug] }),
catalogSeed: createCatalogSeed({
      movieState, seriesState, getActiveTab: () => state.tab, getHomeData: () => sharedPresentation.homeData.get(),
      mergeFpMetadata, fpMetadataPreloadItems, preloadTmdbMetadata,
      renderFpResults: (...args) => renderFpResults(...args), refreshMovieFeatureCandidates,
      updateFpInfiniteState, recheckFpInfinite,
      renderSeriesResults: (...args) => renderSeriesResults(...args), renderSeriesCatalogHero,
      updateSeriesInfiniteState, recheckSeriesInfinite,
    }),
catalogMetadata: createCatalogMetadata({
      movieState, updateFpResultCard: slug => updateFpResultCard(slug),
      refreshFpJellyfinStatus: items => refreshFpJellyfinStatus(items),
      refreshMovieFeatureCandidates: () => refreshMovieFeatureCandidates(),
      showFpDetail: (...args) => showFpDetail(...args), metadataPreviewMovie,
      reconcileMovieCatalogDuplicates: () => reconcileMovieCatalogDuplicates(),
    }),
posterPreloader: createPosterPreloader({ candidates: value => artworkUrls.coverThumbnailCandidates(value) }),
catalogRefresh: createCatalogRefresh({
      movieState, seriesState, applyFpResults: (...args) => applyFpResults(...args),
      applySeriesResults: (...args) => applySeriesResults(...args),
      mergeCatalogItems: (...args) => mergeCatalogItems(...args),
      preloadSeriesPosterImages: (...args) => preloadSeriesPosterImages(...args),
    }),
mediaLanguage: createMediaLanguage(document, { getProviders: () => sharedPresentation.providers.get() }),
trailers: createTrailers(document),
genres: createGenres(document.getElementById("tab-filme"), {
      getActive: () => movieState.activeGenre,
      select(value) { movieState.activeGenre = value; setActiveGenreFilter(value); },
      onChange: () => applyFpSmartFilters(),
    }),
infinite: {
      movies: createInfiniteScroll(document.getElementById("tab-filme"), {
        sentinel: document.getElementById("fp-infinite"), retryButton: document.getElementById("fp-infinite-retry"),
        loadNext: () => loadNextFpPage(), retry() {
          if (movieState.loadingMore || !movieState.category) return;
          if (movieState.lastPageFull) loadNextFpPage();
          else if (movieState.category === "genre") fpGenreChange(movieState.activeGenre);
          else fpShowList(movieState.category);
        },
      }),
      series: createInfiniteScroll(document.getElementById("tab-serien"), {
        sentinel: document.getElementById("series-infinite"), retryButton: document.getElementById("series-infinite-retry"),
        loadNext: () => loadNextSeriesPage(), retry() {
          const mode = seriesState.browseMode;
          if (seriesState.loadingBrowse || !mode || mode === "search") return;
          if (seriesState.lastPageFull) loadNextSeriesPage(); else seriesBrowse(mode, 1);
        },
      }),
      aniworld: createInfiniteScroll(document.getElementById("tab-aniworld"), {
        sentinel: document.getElementById("aniworld-infinite"), loadNext: () => loadNextAniworldPage(),
      }),
    },
artwork: createCatalogArtwork({
      getMovieMetadata: () => movieState.metadataCache,
      renderHome: () => renderHome(), saveHomeCache: () => saveHomeCache(),
      onSeriesHydrated: () => reconcileSeriesCatalogDuplicates(),
    }),
movieHero: createMovieHero(document.getElementById("movie-feature"), {
      getCatalog: () => movieState, getProviderLabels: () => sharedPresentation.providers.get().labels,
      coverUrl: url => artworkUrls.coverUrl(url), locale: () => i18n.locale(),
      openMovie: slug => selectFpRow(slug), onUpdateHome: () => renderHomeHero(),
    })
};
}
