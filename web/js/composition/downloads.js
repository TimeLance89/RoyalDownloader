import { createQueueSync } from "../features/downloads/sync.js";
import { sharedPresentation } from "../shell/presentation.js";
import { state } from "../shell/presentation.js";
import { setDownloadState } from "../shell/presentation.js";
import { refreshFpQueuePresentation } from "../shell/presentation.js";
import { renderSeriesTiles } from "../shell/actions/series.js";
import { createMovieDownloads } from "../features/downloads/movies.js";
import { homeMovieBySlug } from "../shell/actions/home.js";
import { updateFpResultCard } from "../shell/actions/movies.js";
import { showFpDetail } from "../shell/actions/movies.js";
import { refreshQueueUiAfterChange } from "../shell/presentation.js";
import { trackDiscoveryPreference } from "../shell/actions/home.js";
import { metadataPreviewMovie } from "../shell/actions/movies.js";
import { basicMovieMetadata } from "../shell/actions/movies.js";
import { fpDetailJellyfinValue } from "../shell/actions/movies.js";

export function composeDownloads({ movieState }) {
return {
queueSync: createQueueSync({ getView: () => sharedPresentation.queueView, downloadState: state.download,
      setDownloadState, refreshFpQueuePresentation, renderSeriesTiles }),
movieDownloads: createMovieDownloads(document.getElementById("fp-detail-modal"), {
      movieState, getQueuedSlugs: () => state.queuedSlugs, homeMovieBySlug, updateFpResultCard, showFpDetail,
      setDownloadState, refreshQueueUiAfterChange, refreshFpQueuePresentation, trackDiscoveryPreference,
      metadataPreviewMovie, basicMovieMetadata, fpDetailJellyfinValue,
      needsLanguageChoice: movie => sharedPresentation.mediaLanguage.needsChoice(movie),
      chooseLanguage: (movie, button) => sharedPresentation.mediaLanguage.choose(movie, button),
    })
};
}
