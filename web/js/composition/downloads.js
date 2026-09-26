import { createDownloadActions } from "../features/downloads/actions.js";
import { createQueueSync } from "../features/downloads/sync.js";

import { createMovieDownloads } from "../features/downloads/movies.js";

export function composeDownloads({ movieState, state, getCore, getDiscovery, getHome }) {
  const services = {
  queueSync: createQueueSync({ getView: () => services.queueView, downloadState: state.download,
        setDownloadState: (...args) => getCore().actions.setDownloadState(...args), refreshFpQueuePresentation: (...args) => getCore().actions.refreshFpQueuePresentation(...args), renderSeriesTiles: (...args) => getDiscovery().seriesActions.renderSeriesTiles(...args) }),
  movieDownloads: createMovieDownloads(document.getElementById("fp-detail-modal"), {
        movieState, getQueuedSlugs: () => state.queuedSlugs, homeMovieBySlug: (...args) => getHome().actions.homeMovieBySlug(...args), updateFpResultCard: (...args) => getDiscovery().movieActions.updateFpResultCard(...args), showFpDetail: (...args) => getDiscovery().movieActions.showFpDetail(...args),
        setDownloadState: (...args) => getCore().actions.setDownloadState(...args), refreshQueueUiAfterChange: (...args) => getCore().actions.refreshQueueUiAfterChange(...args), refreshFpQueuePresentation: (...args) => getCore().actions.refreshFpQueuePresentation(...args), trackDiscoveryPreference: (...args) => getHome().actions.trackDiscoveryPreference(...args),
        metadataPreviewMovie: (...args) => getDiscovery().movieActions.metadataPreviewMovie(...args), basicMovieMetadata: (...args) => getDiscovery().movieActions.basicMovieMetadata(...args), fpDetailJellyfinValue: (...args) => getDiscovery().movieActions.fpDetailJellyfinValue(...args),
        needsLanguageChoice: movie => getDiscovery().mediaLanguage.needsChoice(movie),
        chooseLanguage: (movie, button) => getDiscovery().mediaLanguage.choose(movie, button),
      })
  };
  services.actions = createDownloadActions({
    getMovieDownloads: () => services.movieDownloads,
  });
  return services;
}
