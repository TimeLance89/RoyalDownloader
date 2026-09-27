export function createCollectionActions({
  getMovieCollections,
}) {
  function homeCollectionEntry(item) { return { kind: "collection", item }; }
  function openMovieCollection(...args) { return getMovieCollections().open(...args); }
  function createMovieCollectionSearchCard(...args) { return getMovieCollections().createCard(...args); }
  return { homeCollectionEntry, openMovieCollection, createMovieCollectionSearchCard };
}
