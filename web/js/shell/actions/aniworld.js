import { sharedPresentation } from "../presentation.js";
export function aniworldBrowse(...args) { return sharedPresentation.aniworld.browse(...args); }
export function loadNextAniworldPage(...args) { return sharedPresentation.aniworld.next(...args); }
export function openAniworldDetail(...args) { return sharedPresentation.aniworld.open(...args); }
export function loadAniworldDetail(...args) { return sharedPresentation.aniworld.loadDetail(...args); }
export function renderAniworldResults(...args) { return sharedPresentation.aniworld.renderResults(...args); }
export function renderAniworldDetail(...args) { return sharedPresentation.aniworld.renderDetail(...args); }
export function renderAniworldEpisodes(...args) { return sharedPresentation.aniworld.renderEpisodes(...args); }
export function syncAniworldQueueFlags(...args) { return sharedPresentation.aniworld.syncQueue(...args); }
export function markAniworldSlugDownloaded(...args) { return sharedPresentation.aniworld.markDownloaded(...args); }
export function aniworldAddSelected(...args) { return sharedPresentation.aniworld.addSelected(...args); }
export function aniworldVisibleEpisodes(...args) { return sharedPresentation.aniworld.visibleEpisodes(...args); }
export function aniworldSelectableEpisodes(...args) { return sharedPresentation.aniworld.selectableEpisodes(...args); }
export function updateAniworldInfiniteState(...args) { return sharedPresentation.aniworld.updateInfinite(...args); }
