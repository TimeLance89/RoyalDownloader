import { createMovieStatus } from "../features/integrations/movie-status.js";

import { createJellyfinResume } from "../features/integrations/resume.js";

import { createCatalogJellyfin } from "../features/integrations/catalog-jellyfin.js";

import { createJellyfinSettings } from "../features/integrations/jellyfin.js";
import { createJellyfinUserPicker } from "../features/integrations/jellyfin-users.js";

import { createIntegrationSettings } from "../features/integrations/settings.js";

export function composeIntegrations({ movieState, getHome, getDiscovery, getSettings }) {
  const services = {
  movieStatus: createMovieStatus({ movieState, refreshCatalogJellyfinStatus: (...args) => getHome().actions.refreshCatalogJellyfinStatus(...args), homeMovieEntry: (...args) => getHome().actions.homeMovieEntry(...args),
        homeMovieBySlug: (...args) => getHome().actions.homeMovieBySlug(...args), updateFpJellyfinBadges: (...args) => getDiscovery().movieActions.updateFpJellyfinBadges(...args), setFpDetailJellyfinStatus: (...args) => getDiscovery().movieActions.setFpDetailJellyfinStatus(...args) }),
  jellyfinResume: createJellyfinResume({
        refreshAllCatalogJellyfinStatuses: () => getHome().actions.refreshAllCatalogJellyfinStatuses(),
        refreshFpJellyfinStatus: () => getDiscovery().movieActions.refreshFpJellyfinStatus(),
        refreshSeriesJellyfinStatus: force => getDiscovery().movieActions.refreshSeriesJellyfinStatus(force),
      }),
  catalogJellyfin: createCatalogJellyfin({
        uniqueHomeEntries: (...args) => getHome().actions.uniqueHomeEntries(...args), homeEntryKey: (...args) => getHome().actions.homeEntryKey(...args), getMovieMetadata: () => movieState.metadataCache,
        getMovieInstances: slug => [
          ...movieState.results.filter(item => item.slug === slug), ...getHome().actions.homeMovieInstances(slug),
          movieState.metadataCache[slug], movieState.moviesCache[slug],
        ],
      }),
  jellyfin: createJellyfinSettings(document.getElementById("jellyfin-url").closest(".settings-group")),
  setupJellyfin: createJellyfinUserPicker(document.getElementById("setup-wizard"), {
        urlId: "setup-jellyfin-url", keyId: "setup-jellyfin-key", selectId: "setup-jellyfin-user",
        buttonId: "setup-jellyfin-users-load", onError: message => getSettings().setup.status(message, true),
      }),
  integrations: createIntegrationSettings(document.getElementById("settings-media"))
  };

  return services;
}
