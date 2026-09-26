function renderFpDownloadFeedback(...args) { return sharedPresentation.movieDownloads.renderFeedback(...args); }
function setFpDownloadFeedback(...args) { return sharedPresentation.movieDownloads.feedback(...args); }
function setFpJellyfinDownloadPending(...args) { return sharedPresentation.movieDownloads.pendingFeedback(...args); }
function applyFpQueueAddResponse(...args) { return sharedPresentation.movieDownloads.accept(...args); }
function applyFpDownloadJobResult(...args) { return sharedPresentation.movieDownloads.job(...args); }
