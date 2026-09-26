import { createHomeSearch } from "../features/search/home.js";
import { createSearchSupport } from "../features/search/support.js";

import { createSearch } from "../features/search/index.js";

export function composeSearch({ personalStorageKey, getDiscovery, getProfile, getHome }) {
  const services = {
  searchSupport: createSearchSupport(document, {
        personalStorageKey, getGenres: () => getDiscovery().genres.get(),
        recordTasteEvent: event => getProfile().tasteProfile.event(event),
      }),
  search: createSearch(document.getElementById("global-search-page"), document.getElementById("global-search-shell"), {
        createHomeCard: (...args) => getHome().actions.createHomeCard(...args), mediaJellyfinStatus: (...args) => getHome().actions.mediaJellyfinStatus(...args),
        rememberSearch: (...args) => getHome().actions.rememberSearch(...args),
        uniqueHomeContentEntries: entries => getHome().actions.uniqueHomeContentEntries(entries), uniqueHomeEntries: (...args) => getHome().actions.uniqueHomeEntries(...args),
        homeCollectionEntry: (...args) => getDiscovery().collectionActions.homeCollectionEntry(...args), homeMovieEntry: (...args) => getHome().actions.homeMovieEntry(...args), homeSeriesEntry: (...args) => getHome().actions.homeSeriesEntry(...args), homeAnimeEntry: (...args) => getHome().actions.homeAnimeEntry(...args),
        hydrateHomeMovieArtwork: (...args) => getDiscovery().artwork.movies(...args),
        hydrateHomeSeriesArtwork: (...args) => getDiscovery().artwork.series(...args),
        refreshCatalogJellyfinStatus: (...args) => getHome().actions.refreshCatalogJellyfinStatus(...args),
        mediaDetailModalOpen: () => [...document.querySelectorAll(".media-modal")].some(modal =>
          !modal.hidden && !modal.classList.contains("hidden") && modal.getAttribute("aria-hidden") !== "true"),
      })
  };

  return services;
}

export function initializeSearch({ getSearch, getHome, getDiscovery }) {
  getSearch().homeSearch = createHomeSearch(document.getElementById("tab-home"), {
      rememberSearch: (...args) => getHome().actions.rememberSearch(...args), homeMovieEntry: (...args) => getHome().actions.homeMovieEntry(...args), homeSeriesEntry: (...args) => getHome().actions.homeSeriesEntry(...args),
      interleaveHomeEntries: (...args) => getHome().actions.interleaveHomeEntries(...args), uniqueHomeEntries: (...args) => getHome().actions.uniqueHomeEntries(...args), createHomeCard: (...args) => getHome().actions.createHomeCard(...args),
      artwork: getDiscovery().artwork, refreshJellyfin: (...args) => getHome().actions.refreshCatalogJellyfinStatus(...args),
    });
}
