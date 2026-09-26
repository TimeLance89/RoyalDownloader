import { createSearchSupport } from "../features/search/support.js";
import { sharedPresentation } from "../shell/presentation.js";
import { createSearch } from "../features/search/index.js";
import { createHomeCard } from "../shell/actions/home.js";
import { mediaJellyfinStatus } from "../shell/actions/home.js";
import { rememberSearch } from "../shell/actions/home.js";
import { uniqueHomeContentEntries } from "../shell/actions/home.js";
import { uniqueHomeEntries } from "../shell/actions/home.js";
import { homeCollectionEntry } from "../shell/actions/movie-collections.js";
import { homeMovieEntry } from "../shell/actions/home.js";
import { homeSeriesEntry } from "../shell/actions/home.js";
import { homeAnimeEntry } from "../shell/actions/home.js";
import { refreshCatalogJellyfinStatus } from "../shell/actions/home.js";

export function composeSearch({ personalStorageKey }) {
return {
searchSupport: createSearchSupport(document, {
      personalStorageKey, getGenres: () => sharedPresentation.genres.get(),
      recordTasteEvent: event => sharedPresentation.tasteProfile.event(event),
    }),
search: createSearch(document.getElementById("global-search-page"), document.getElementById("global-search-shell"), {
      createHomeCard: (...args) => createHomeCard(...args), mediaJellyfinStatus,
      rememberSearch: (...args) => rememberSearch(...args),
      uniqueHomeContentEntries: entries => uniqueHomeContentEntries(entries), uniqueHomeEntries,
      homeCollectionEntry, homeMovieEntry, homeSeriesEntry, homeAnimeEntry,
      hydrateHomeMovieArtwork: (...args) => sharedPresentation.artwork.movies(...args),
      hydrateHomeSeriesArtwork: (...args) => sharedPresentation.artwork.series(...args),
      refreshCatalogJellyfinStatus: (...args) => refreshCatalogJellyfinStatus(...args),
      mediaDetailModalOpen: () => [...document.querySelectorAll(".media-modal")].some(modal =>
        !modal.hidden && !modal.classList.contains("hidden") && modal.getAttribute("aria-hidden") !== "true"),
    })
};
}
