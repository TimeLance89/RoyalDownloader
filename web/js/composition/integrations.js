import { createMovieStatus } from "../features/integrations/movie-status.js";
import { refreshCatalogJellyfinStatus } from "../shell/actions/home.js";
import { homeMovieEntry } from "../shell/actions/home.js";
import { homeMovieBySlug } from "../shell/actions/home.js";
import { updateFpJellyfinBadges } from "../shell/actions/movies.js";
import { setFpDetailJellyfinStatus } from "../shell/actions/movies.js";
import { createJellyfinResume } from "../features/integrations/resume.js";
import { refreshAllCatalogJellyfinStatuses } from "../shell/actions/home.js";
import { refreshFpJellyfinStatus } from "../shell/actions/movies.js";
import { refreshSeriesJellyfinStatus } from "../shell/actions/movies.js";
import { createCatalogJellyfin } from "../features/integrations/catalog-jellyfin.js";
import { uniqueHomeEntries } from "../shell/actions/home.js";
import { homeEntryKey } from "../shell/actions/home.js";
import { homeMovieInstances } from "../shell/actions/home.js";
import { createJellyfinSettings } from "../features/integrations/jellyfin.js";
import { createJellyfinUserPicker } from "../features/integrations/jellyfin-users.js";
import { sharedPresentation } from "../shell/presentation.js";
import { createIntegrationSettings } from "../features/integrations/settings.js";

export function composeIntegrations({ movieState }) {
return {
movieStatus: createMovieStatus({ movieState, refreshCatalogJellyfinStatus, homeMovieEntry,
      homeMovieBySlug, updateFpJellyfinBadges, setFpDetailJellyfinStatus }),
jellyfinResume: createJellyfinResume({
      refreshAllCatalogJellyfinStatuses: () => refreshAllCatalogJellyfinStatuses(),
      refreshFpJellyfinStatus: () => refreshFpJellyfinStatus(),
      refreshSeriesJellyfinStatus: force => refreshSeriesJellyfinStatus(force),
    }),
catalogJellyfin: createCatalogJellyfin({
      uniqueHomeEntries, homeEntryKey, getMovieMetadata: () => movieState.metadataCache,
      getMovieInstances: slug => [
        ...movieState.results.filter(item => item.slug === slug), ...homeMovieInstances(slug),
        movieState.metadataCache[slug], movieState.moviesCache[slug],
      ],
    }),
jellyfin: createJellyfinSettings(document.getElementById("jellyfin-url").closest(".settings-group")),
setupJellyfin: createJellyfinUserPicker(document.getElementById("setup-wizard"), {
      urlId: "setup-jellyfin-url", keyId: "setup-jellyfin-key", selectId: "setup-jellyfin-user",
      buttonId: "setup-jellyfin-users-load", onError: message => sharedPresentation.setup.status(message, true),
    }),
integrations: createIntegrationSettings(document.getElementById("settings-media"))
};
}
