function homeCollectionEntry(item) { return { kind: "collection", item }; }
function openMovieCollection(...args) { return sharedPresentation.movieCollections.open(...args); }
function createMovieCollectionSearchCard(...args) { return sharedPresentation.movieCollections.createCard(...args); }
