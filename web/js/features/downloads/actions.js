export function createDownloadActions({
  getMovieDownloads,
}) {
  function renderFpDownloadFeedback(...args) { return getMovieDownloads().renderFeedback(...args); }
  function setFpDownloadFeedback(...args) { return getMovieDownloads().feedback(...args); }
  function setFpJellyfinDownloadPending(...args) { return getMovieDownloads().pendingFeedback(...args); }
  function applyFpQueueAddResponse(...args) { return getMovieDownloads().accept(...args); }
  function applyFpDownloadJobResult(...args) { return getMovieDownloads().job(...args); }
  return { renderFpDownloadFeedback, setFpDownloadFeedback, setFpJellyfinDownloadPending, applyFpQueueAddResponse, applyFpDownloadJobResult };
}
