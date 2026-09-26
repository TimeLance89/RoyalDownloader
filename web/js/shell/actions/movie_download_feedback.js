import { sharedPresentation } from "../presentation.js";
export function renderFpDownloadFeedback(...args) { return sharedPresentation.movieDownloads.renderFeedback(...args); }
export function setFpDownloadFeedback(...args) { return sharedPresentation.movieDownloads.feedback(...args); }
export function setFpJellyfinDownloadPending(...args) { return sharedPresentation.movieDownloads.pendingFeedback(...args); }
export function applyFpQueueAddResponse(...args) { return sharedPresentation.movieDownloads.accept(...args); }
export function applyFpDownloadJobResult(...args) { return sharedPresentation.movieDownloads.job(...args); }
