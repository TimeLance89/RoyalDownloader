export function createSeriesActions({
  getSeriesEpisodes,
  getSeriesChecks,
  getSeriesBrowse,
  getSeriesDetailsLoader,
  getTrailers,
  getSeriesPresentation,
  getSeriesDiscovery,
}) {
  function firstEpisodeSlug(...args) { return getSeriesEpisodes().firstEpisodeSlug(...args); }
  function seriesEpisodes(...args) { return getSeriesEpisodes().seriesEpisodes(...args); }
  function isEpisodeQueued(...args) { return getSeriesEpisodes().isEpisodeQueued(...args); }
  function episodeHasEnabledStreamLanguage(...args) { return getSeriesEpisodes().episodeHasEnabledStreamLanguage(...args); }
  function episodeLanguageLockLabel(...args) { return getSeriesEpisodes().episodeLanguageLockLabel(...args); }
  function isEpisodeEligible(...args) { return getSeriesEpisodes().isEpisodeEligible(...args); }
  function isEpisodeSelectable(...args) { return getSeriesEpisodes().isEpisodeSelectable(...args); }
  function isEpisodeActionable(...args) { return getSeriesEpisodes().isEpisodeActionable(...args); }
  function syncSeriesQueueFlags(...args) { return getSeriesEpisodes().syncSeriesQueueFlags(...args); }
  function pruneSeriesEpisodeSelection(...args) { return getSeriesEpisodes().pruneSeriesEpisodeSelection(...args); }
  function findCurrentEpisode(...args) { return getSeriesEpisodes().findCurrentEpisode(...args); }
  function tileClass(...args) { return getSeriesEpisodes().tileClass(...args); }
  function episodeReleaseText(...args) { return getSeriesEpisodes().episodeReleaseText(...args); }
  function seriesAvailabilityNotice(...args) { return getSeriesEpisodes().seriesAvailabilityNotice(...args); }
  function syncSeriesAvailabilityNotice(...args) { return getSeriesEpisodes().syncSeriesAvailabilityNotice(...args); }
  function applySeriesEpisodeTileState(...args) { return getSeriesEpisodes().applySeriesEpisodeTileState(...args); }
  function refreshSeriesTileStates(...args) { return getSeriesEpisodes().refreshSeriesTileStates(...args); }
  function renderSeriesTiles(...args) { return getSeriesEpisodes().renderSeriesTiles(...args); }
  function toggleEpisodeTile(...args) { return getSeriesEpisodes().toggleEpisodeTile(...args); }
  function toggleSeasonTiles(...args) { return getSeriesEpisodes().toggleSeasonTiles(...args); }
  function selectAllSeriesEpisodes(...args) { return getSeriesEpisodes().selectAllSeriesEpisodes(...args); }
  function markSeriesSlugDownloaded(...args) { return getSeriesEpisodes().markSeriesSlugDownloaded(...args); }
  function seriesAddSelected(...args) { return getSeriesEpisodes().seriesAddSelected(...args); }
  function verifyHuhuEpisodeLanguages(...args) { return getSeriesChecks().verifyLanguages(...args); }
  function clearSeriesSearchContext(...args) { return getSeriesBrowse().clear(...args); }
  function rememberSeriesSearchContext(...args) { return getSeriesBrowse().remember(...args); }
  function restoreSeriesSearchContext(...args) { return getSeriesBrowse().restore(...args); }
  function seriesSearch(...args) { return getSeriesBrowse().search(...args); }
  function seriesBrowse(...args) { return getSeriesBrowse().browse(...args); }
  function ensureSeriesResults(...args) { return getSeriesBrowse().ensure(...args); }
  function loadNextSeriesPage(...args) { return getSeriesBrowse().next(...args); }
  function mergeSeriesDetailPayload(...args) { return getSeriesDetailsLoader().merge(...args); }
  function loadSeries(...args) { return getSeriesDetailsLoader().open(...args); }
  function stopSeriesDetailHeroTrailer() { return getTrailers().series.stop(); }
  function scheduleSeriesDetailHeroTrailer(series) { return getTrailers().series.schedule(series); }
  function configureSeriesTrailer(series) { return getTrailers().series.configure(series); }
  function updateSeriesInfiniteState(...args) { return getSeriesPresentation().updateSeriesInfiniteState(...args); }
  function updateSeriesFeatureArtwork(...args) { return getSeriesPresentation().updateSeriesFeatureArtwork(...args); }
  function renderSeriesCatalogHero(...args) { return getSeriesPresentation().renderSeriesCatalogHero(...args); }
  function seriesCardSeasonSummary(...args) { return getSeriesPresentation().seriesCardSeasonSummary(...args); }
  function createSeriesResultRow(...args) { return getSeriesPresentation().createSeriesResultRow(...args); }
  function renderSeriesResults(...args) { return getSeriesPresentation().renderSeriesResults(...args); }
  function findSeriesResultCard(...args) { return getSeriesPresentation().findSeriesResultCard(...args); }
  function updateSeriesResultCard(...args) { return getSeriesPresentation().updateSeriesResultCard(...args); }
  function updateSeriesResultSelection(...args) { return getSeriesPresentation().updateSeriesResultSelection(...args); }
  function applySeriesResults(...args) { return getSeriesPresentation().applySeriesResults(...args); }
  function seriesStructureFingerprint(...args) { return getSeriesPresentation().seriesStructureFingerprint(...args); }
  function showSeriesLoading(...args) { return getSeriesPresentation().showSeriesLoading(...args); }
  function renderSeriesDetailMeta(...args) { return getSeriesPresentation().renderSeriesDetailMeta(...args); }
  function updateWatchBtn(...args) { return getSeriesPresentation().updateWatchBtn(...args); }
  function setSeriesDetailArtwork(...args) { return getSeriesPresentation().setSeriesDetailArtwork(...args); }
  function updateSeriesOverview(...args) { return getSeriesPresentation().updateSeriesOverview(...args); }
  function showSeriesDetail(...args) { return getSeriesPresentation().showSeriesDetail(...args); }
  function renderSeriesDetailDiscovery(...args) { return getSeriesDiscovery().render(...args); }
  return { firstEpisodeSlug, seriesEpisodes, isEpisodeQueued, episodeHasEnabledStreamLanguage, episodeLanguageLockLabel, isEpisodeEligible, isEpisodeSelectable, isEpisodeActionable, syncSeriesQueueFlags, pruneSeriesEpisodeSelection, findCurrentEpisode, tileClass, episodeReleaseText, seriesAvailabilityNotice, syncSeriesAvailabilityNotice, applySeriesEpisodeTileState, refreshSeriesTileStates, renderSeriesTiles, toggleEpisodeTile, toggleSeasonTiles, selectAllSeriesEpisodes, markSeriesSlugDownloaded, seriesAddSelected, verifyHuhuEpisodeLanguages, clearSeriesSearchContext, rememberSeriesSearchContext, restoreSeriesSearchContext, seriesSearch, seriesBrowse, ensureSeriesResults, loadNextSeriesPage, mergeSeriesDetailPayload, loadSeries, stopSeriesDetailHeroTrailer, scheduleSeriesDetailHeroTrailer, configureSeriesTrailer, updateSeriesInfiniteState, updateSeriesFeatureArtwork, renderSeriesCatalogHero, seriesCardSeasonSummary, createSeriesResultRow, renderSeriesResults, findSeriesResultCard, updateSeriesResultCard, updateSeriesResultSelection, applySeriesResults, seriesStructureFingerprint, showSeriesLoading, renderSeriesDetailMeta, updateWatchBtn, setSeriesDetailArtwork, updateSeriesOverview, showSeriesDetail, renderSeriesDetailDiscovery };
}
