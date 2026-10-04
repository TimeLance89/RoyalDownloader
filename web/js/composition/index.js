import { mountApplication } from "./application.js";
import { initializeHome } from "./home.js";
import { initializeSettings } from "./settings.js";
import { initializeProfile } from "./profile.js";
import { initializeSearch } from "./search.js";
import { initializeCore } from "./core.js";

import { composeSubscriptions, prepareSubscriptions } from "./subscriptions.js";
import { composeHome, prepareHome } from "./home.js";
import { composeCore, prepareCore } from "./core.js";
import { composeDiscovery, prepareDiscovery } from "./discovery.js";
import { composeDownloads } from "./downloads.js";
import { composeIntegrations } from "./integrations.js";
import { composeSearch } from "./search.js";
import { composeProfile, prepareProfile } from "./profile.js";
import { composeSettings, prepareSettings } from "./settings.js";

export function preparePresentation() {
  let coreDomain, discoveryDomain, downloadsDomain, homeDomain, integrationsDomain;
  let profileDomain, searchDomain, settingsDomain, subscriptionsDomain;

  // Prepare state first; callbacks resolve named peers only after all domains exist.
  const { state, startupCurtain, artworkUrls, i18n, modal } = prepareCore({ getDiscovery: () => discoveryDomain, getDownloads: () => downloadsDomain, getIntegrations: () => integrationsDomain, getHome: () => homeDomain });
  const { movieState, seriesState } = prepareDiscovery();
  const { household, userMenu, profileActions, personalStorageKey } = prepareProfile({ getCore: () => coreDomain, getProfile: () => profileDomain, getHome: () => homeDomain });
  const { subscriptions, movieSubscriptions, movieSubscriptionRules } = prepareSubscriptions({ getCore: () => coreDomain, getIntegrations: () => integrationsDomain });
  const { intelligence } = prepareSettings({ getRecommendations: () => recommendations });
  const { recommendations, discoveryPolicy } = prepareHome({ intelligence, getHome: () => homeDomain, personalStorageKey, getDiscovery: () => discoveryDomain });

  coreDomain = composeCore({
    i18n,
    modal,
    state,
    getSettings: () => settingsDomain,
    getHome: () => homeDomain,
    getDiscovery: () => discoveryDomain,
    getSearch: () => searchDomain,
    getDownloads: () => downloadsDomain,
    getSubscriptions: () => subscriptionsDomain,
  });
  discoveryDomain = composeDiscovery({
    movieState,
    seriesState,
    artworkUrls,
    i18n,
    state,
    getCore: () => coreDomain,
    getIntegrations: () => integrationsDomain,
    getDownloads: () => downloadsDomain,
    getSubscriptions: () => subscriptionsDomain,
    getHome: () => homeDomain,
    getSettings: () => settingsDomain,
  });
  downloadsDomain = composeDownloads({
    movieState,
    state,
    getCore: () => coreDomain,
    getDiscovery: () => discoveryDomain,
    getHome: () => homeDomain,
  });
  homeDomain = composeHome({
    discoveryPolicy,
    movieState,
    artworkUrls,
    recommendations,
    getDiscovery: () => discoveryDomain,
    getIntegrations: () => integrationsDomain,
    getCore: () => coreDomain,
    getSearch: () => searchDomain,
    getProfile: () => profileDomain,
  });
  integrationsDomain = composeIntegrations({
    movieState,
    getHome: () => homeDomain,
    getDiscovery: () => discoveryDomain,
    getSettings: () => settingsDomain,
  });
  profileDomain = composeProfile({
    household,
    userMenu,
    state,
    getHome: () => homeDomain,
    getCore: () => coreDomain,
  });
  searchDomain = composeSearch({
    personalStorageKey,
    getDiscovery: () => discoveryDomain,
    getProfile: () => profileDomain,
    getHome: () => homeDomain,
  });
  settingsDomain = composeSettings({
    i18n,
    movieState,
    seriesState,
    intelligence,
    subscriptions,
    getCore: () => coreDomain,
    getDiscovery: () => discoveryDomain,
    getIntegrations: () => integrationsDomain,
    getSubscriptions: () => subscriptionsDomain,
    getProfile: () => profileDomain,
    getHome: () => homeDomain,
  });
  subscriptionsDomain = composeSubscriptions({
    movieSubscriptions,
    movieSubscriptionRules,
    subscriptions,
    seriesState,
    artworkUrls,
    getCore: () => coreDomain,
    getDiscovery: () => discoveryDomain,
    getHome: () => homeDomain,
    getIntegrations: () => integrationsDomain,
  });

  // Shell-owned navigation entries exist before the shell menu listeners bind.

  initializeCore({ getCore: () => coreDomain, startupCurtain, getHome: () => homeDomain, getDiscovery: () => discoveryDomain, getSubscriptions: () => subscriptionsDomain, state });
  initializeSearch({ getSearch: () => searchDomain, getHome: () => homeDomain, getDiscovery: () => discoveryDomain });
  initializeProfile({ getProfile: () => profileDomain, getSettings: () => settingsDomain, getCore: () => coreDomain, getHome: () => homeDomain, profileActions });
  initializeSettings({ getSettings: () => settingsDomain, getIntegrations: () => integrationsDomain, i18n, getCore: () => coreDomain });
  initializeHome({ getHome: () => homeDomain, artworkUrls, discoveryPolicy, getCore: () => coreDomain, state, getDiscovery: () => discoveryDomain, movieState, getIntegrations: () => integrationsDomain });
  return {
    core: coreDomain,
    discovery: discoveryDomain,
    downloads: downloadsDomain,
    home: homeDomain,
    integrations: integrationsDomain,
    profile: profileDomain,
    search: searchDomain,
    settings: settingsDomain,
    subscriptions: subscriptionsDomain,
    initUserProfile: profileActions.initUserProfile,
    mount: () => mountApplication({
      state, downloadsDomain, coreDomain, discoveryDomain, profileDomain,
      searchDomain, integrationsDomain, subscriptionsDomain, homeDomain, settingsDomain,
    }),
  };

}
