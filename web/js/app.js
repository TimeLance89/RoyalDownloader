import { appStore } from "./core/store.js";
import { createScope } from "./core/lifecycle.js";
import { createNavigation } from "./core/navigation.js";
import { createLiveUpdates } from "./features/downloads/index.js";
import { createReleases } from "./features/releases/index.js";

/** Explicit seam to classic presenters while features migrate independently. */
export function createApplication({
  live, releases: releaseActions, home, user, queueView, modules, profile, movieHero,
  localization, shell, movieDiscovery, seriesDiscovery, moviePresentation, movieStatus, resultCards, seriesPresentation, seriesEpisodes, movieDownloads, movieCollections, tasteProfile, aniworld, anime, seriesChecks, seriesDetailsLoader, movieDetailsLoader, seriesBrowse, movieBrowse, catalogMetadata, posterPreloader, catalogRefresh, mediaLanguage, mood, cardArtwork, trailers, jellyfinResume, catalogJellyfin, tasteOnboarding, startup, genres, infinite, setup, settings, jellyfin, setupJellyfin, providers, integrations, settingsNavigation, directory, updater, search, account, intelligence, homeData, artwork, calendar, storage, automation, notifications, subscriptions, library, subscriptionRules,
  onSubscriptions, movieSubscriptions, movieSubscriptionView, movieSubscriptionRules, onMovieSubscriptions,
}) {
  let sessionActive = true;
  const scope = createScope();
  const navigation = createNavigation();
  scope.add(subscriptions.subscribe(onSubscriptions));
  scope.add(movieSubscriptions.subscribe(onMovieSubscriptions));
  subscriptions.mount();
  movieSubscriptions.mount();
  notifications.mount();
  search.mount();
  jellyfinResume.mount();
  localization.mount(); shell.mount(); movieDiscovery.mount(); seriesDiscovery.mount(); moviePresentation.mountDetail(); movieStatus.mount(); seriesEpisodes.mount(); movieDownloads.mount(); movieCollections.mount(); tasteProfile.mount(); mediaLanguage.mount(); mood.mount(); trailers.mount(); cardArtwork.mount();
  const downloads = createLiveUpdates(live);
  const releases = createReleases(releaseActions);
  function stopViews() {
    localization.unmount(); shell.unmount(); movieDiscovery.unmount(); seriesDiscovery.unmount(); moviePresentation.unmountDetail(); movieStatus.unmount(); seriesEpisodes.unmount(); movieDownloads.unmount(); movieCollections.unmount(); tasteProfile.unmount(); aniworld.dispose(); anime.dispose(); seriesChecks.unmount(); seriesDetailsLoader.unmount(); movieDetailsLoader.unmount(); catalogMetadata.unmount(); posterPreloader.unmount(); mediaLanguage.unmount(); mood.unmount(); cardArtwork.unmount(); trailers.unmount(); jellyfinResume.unmount(); catalogJellyfin.unmount(); tasteOnboarding.unmount(); startup.unmount(); genres.unmount(); setup.unmount(); settings.dispose(); jellyfin.dispose(); setupJellyfin.unmount(); providers.unmount(); directory.unmount(); search.unmount();
    homeData.unmount(); artwork.unmount(); intelligence.unmount(); account.unmount();
    subscriptionRules.unmount(); movieSubscriptionRules.unmount();
    navigation.dispose(); calendar.unmount(); automation.unmount(); notifications.unmount();
    subscriptions.unmount(); movieSubscriptions.unmount();
    downloads.unmount(); queueView.unmount();
  }
  navigation.register("kalender", calendar, document.getElementById("tab-kalender"));
  navigation.register("bibliothek", library, document.getElementById("tab-bibliothek"));
  navigation.register("filme", {
    mount(root) { resultCards.mount("movie", root); moviePresentation.mount(); movieBrowse.mount(); catalogMetadata.resume(); catalogRefresh.movies.mount(); infinite.movies.mount(); movieHero.mount(root); movieSubscriptionView.mount(); },
    refresh() { infinite.movies.refresh(); movieHero.refresh(); movieSubscriptionView.refresh(); },
    unmount() { moviePresentation.unmount(); movieStatus.cancel(); resultCards.unmount("movie"); movieBrowse.unmount(); catalogRefresh.movies.unmount(); infinite.movies.unmount(); movieHero.unmount(); movieSubscriptionView.unmount(); },
  }, document.getElementById("tab-filme"));
  navigation.register("serien", {
    mount(root) { resultCards.mount("series", root); seriesPresentation.mount(); seriesBrowse.mount(); catalogRefresh.series.mount(); infinite.series.mount(); },
    refresh() { infinite.series.refresh(); },
    unmount() { resultCards.unmount("series"); seriesPresentation.unmount(); seriesBrowse.unmount(); posterPreloader.unmount(); catalogRefresh.series.unmount(); infinite.series.unmount(); },
  }, document.getElementById("tab-serien"));
  navigation.register("anime", anime, document.getElementById("tab-anime"));
  navigation.register("aniworld", {
    mount() { aniworld.mount(); infinite.aniworld.mount(); },
    refresh() { infinite.aniworld.refresh(); },
    unmount() { aniworld.unmount(); infinite.aniworld.unmount(); },
  }, document.getElementById("tab-aniworld"));
  navigation.register("profil", profile, document.getElementById("tab-profil"));
  navigation.register("releases", releases, document.getElementById("tab-releases"));
  navigation.register("einstellungen", {
    mount(root) { settings.mount(); jellyfin.mount(); settingsNavigation.mount(); providers.settings.mount(); integrations.mount(); releases.settings.mount(root); modules.mount(); storage.mount(); automation.mount(); intelligence.mount(); account.mount(); updater.mount(); },
    refresh() { providers.settings.refresh(); void integrations.refresh(); releases.settings.refresh(); modules.refresh(); storage.refresh(); automation.refresh(); intelligence.refresh(); void account.refresh(); void updater.refresh(); },
    unmount() { settings.unmount(); jellyfin.unmount(); directory.unmount(); settingsNavigation.unmount(); providers.settings.unmount(); integrations.unmount(); releases.settings.unmount(); modules.unmount(); storage.unmount(); automation.unmount(); intelligence.unmount(); account.unmount(); updater.unmount(); },
  }, document.getElementById("tab-einstellungen"));
  navigation.register("home", home, document.getElementById("tab-home"));
  scope.listen(document, "royal:navigate", ({ detail }) => {
    seriesChecks.unmount(); seriesDetailsLoader.unmount();
    if (detail.name !== appStore.get().navigation) catalogMetadata.unmount();
    notifications.close();
    subscriptionRules.unmount(); movieSubscriptionRules.unmount();
    appStore.set({ navigation: detail.name });
    navigation.activate(detail.name, detail);
  });
  scope.listen(document, "royal:session-expired", () => {
    sessionActive = false; tasteOnboarding.close();
    stopViews();
    appStore.set({ user: null });
  });
  scope.listen(window, "pagehide", stopViews);
  scope.listen(window, "pageshow", event => {
    if (!event.persisted || !sessionActive) return;
    localization.mount(); shell.mount(); movieDiscovery.mount(); seriesDiscovery.mount(); moviePresentation.mountDetail(); movieStatus.mount(); seriesEpisodes.mount(); movieDownloads.mount(); movieCollections.mount(); tasteProfile.mount(); aniworld.resume(); anime.resume(); mediaLanguage.mount(); mood.mount(); trailers.mount(); cardArtwork.mount(); catalogJellyfin.mount(); startup.mount(); genres.mount(); settings.resume(); jellyfin.resume(); providers.mount();
    if (setup.required) setup.mount();
    homeData.mount(); artwork.mount(); tasteOnboarding.mount();
    subscriptions.mount();
    movieSubscriptions.mount();
    notifications.mount();
    search.mount();
    navigation.activate(appStore.get().navigation);
    queueView.mount();
    downloads.mount(); jellyfinResume.mount({ resumed: true });
  });
  const language = new MutationObserver(() => appStore.set({ language: document.documentElement.lang || "de" }));
  language.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  scope.observe(language);
  appStore.set({ user, language: document.documentElement.lang || "de" });
  navigation.activate("home");
  return {
    downloads,
    dispose() { stopViews(); scope.dispose(); },
  };
}
