import { sharedPresentation } from "../presentation.js";
export function homeCollectionEntry(item) { return { kind: "collection", item }; }
export function openMovieCollection(...args) { return sharedPresentation.movieCollections.open(...args); }
export function createMovieCollectionSearchCard(...args) { return sharedPresentation.movieCollections.createCard(...args); }
