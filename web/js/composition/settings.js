import { api } from "../core/api.js";
import { createSetup } from "../features/setup/index.js";
import { createIntelligenceSettings } from "../features/settings/intelligence.js";
import { createSettingsActions } from "../features/settings/actions.js";
import { createProviderSettings } from "../features/settings/providers.js";

import { updateDeploymentModeHints as deploymentHints } from "../features/settings/deployment.js";
import { selectedDeploymentMode as deploymentMode } from "../features/settings/deployment.js";
import { createSettings } from "../features/settings/index.js";

import { createDirectoryPicker } from "../features/settings/directory.js";
import { createUpdater } from "../features/settings/updater.js";
import { createAccountSettings } from "../features/settings/account.js";
import { logout } from "../core/session.js";
import { createCalendar } from "../features/calendar/index.js";

import { createAutomation } from "../features/automation/index.js";
import { createStorage } from "../features/storage/index.js";
import { createModuleSettings } from "../features/settings/modules.js";

export function composeSettings({ i18n, movieState, seriesState, intelligence, subscriptions, getCore, getDiscovery, getIntegrations, getSubscriptions, getProfile, getHome }) {
  const services = {
  providers: createProviderSettings(document.getElementById("settings-sources"), document.getElementById("setup-wizard"), {
        onChange() { getCore().actions.syncAnimeNavigationVisibility(); getCore().actions.syncAniworldNavigationVisibility(); },
        onApply() { getDiscovery().anime.invalidate(); },
        onSetupStatus: (message, error) => services.setup.status(message, error),
        onLanguageSetup: options => { void services.settings.openLanguageSetup(options); },
      }),
  deploymentHints: (context, mode) => deploymentHints(document.getElementById(context === "setup" ? "setup-wizard" : "tab-einstellungen"), context, mode),
  deploymentMode: name => deploymentMode(document.getElementById(name === "setup-deployment-mode" ? "setup-wizard" : "tab-einstellungen"), name),
  settings: createSettings(document.getElementById("tab-einstellungen"), {
        getFeatures: () => ({ jellyfin: getIntegrations().jellyfin, intelligence, automation: services.automation, providers: services.providers, updater: services.updater, integrations: getIntegrations().integrations }), language: () => i18n.language, locale: () => i18n.locale(),
        changeLanguage: language => i18n.changeLanguage(language, { userInitiated: true, requireReady: true }),
        async onLanguageReady({ signal }) {
          movieState.results = []; movieState.moviesCache = {}; movieState.metadataCache = {}; movieState.sources = [];
          seriesState.results = []; seriesState.sources = []; seriesState.cache = {}; seriesState.browseMode = null; seriesState.page = 1;
          await getDiscovery().genres.refresh();
          if (signal.aborted) return;
          getHome().hero.reset();
          await getHome().homeData.reloadForLanguage({ signal });
          if (signal.aborted) return;
          await getSubscriptions().actions.refreshWatchlist();
        },
        async onSaved({ signal }) {
      movieState.results = [];
      movieState.moviesCache = {};
      movieState.metadataCache = {};
      movieState.sources = [];
      seriesState.results = [];
      seriesState.sources = [];
      seriesState.browseMode = null;
      seriesState.page = 1;
      seriesState.cache = {};
      await getDiscovery().genres.refresh().catch((error) => {
        console.error("Genres konnten nach dem Quellenwechsel nicht geladen werden:", error);
      });
      if (signal.aborted) return;
      getDiscovery().movieActions.fpShowList("new").catch((error) => {
        document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
      });
          if (getSubscriptions().subscriptions.get().loaded) void getSubscriptions().actions.refreshWatchlist();
        },
      }),
  directory: createDirectoryPicker(document.getElementById("dir-modal")),
  updater: createUpdater(document.getElementById("updater-card")),
  intelligence,
  account: createAccountSettings(document.getElementById("settings-account"), {
        getUser: () => getProfile().auth.get().user, logout,
        onSaved(result, username) {
          const previous = getProfile().auth.get();
          getProfile().auth.accept({ ...previous, user: result.user || previous.user, configured: true, authenticated: true, username: result.user?.username || username });
        },
      }),
  calendar: createCalendar(document.getElementById("tab-kalender"), {
        subscriptions, getUserId: () => String(getProfile().auth.get().user?.id || ""), locale: () => i18n.locale(),
        loadSeries: entry => getDiscovery().seriesActions.loadSeries(entry),
      }),
  automation: createAutomation(document.getElementById("tab-einstellungen")),
  storage: createStorage(document.getElementById("tab-einstellungen")),
  modules: createModuleSettings(document.getElementById("tab-einstellungen"))
  };
  services.actions = createSettingsActions({
    getDeploymentHints: () => services.deploymentHints,
    getDeploymentMode: () => services.deploymentMode,
    getProviders: () => services.providers,
    getSettings: () => services.settings,
  });
  return services;
}

export function prepareSettings({ getRecommendations }) {
  const intelligence = createIntelligenceSettings(document.querySelector(".ai-settings-card"), {
      onConfig: () => getRecommendations().configure(),
    });
  return { intelligence };
}

export function initializeSettings({ getSettings, getIntegrations, i18n, getCore, getHome, getProfile }) {
  getSettings().setup = createSetup(document.getElementById("setup-wizard"), {
      providers: getSettings().providers, jellyfin: getIntegrations().setupJellyfin,
      directory: getSettings().directory, i18n,
      onVisibility: visible => document.body.classList.toggle("setup-open", visible),
      async onComplete() {
        const session = await api.get("/api/auth/status");
        if (session.configured && !session.authenticated) throw new Error("Die neue Sitzung ist noch nicht bereit. Bitte erneut versuchen.");
        getProfile().auth.accept(session);
        await getSettings().settings.initialize();
        await getHome().homeData.reloadForLanguage();
        await i18n.changeLanguage(i18n.language, { requireReady: true, userInitiated: true });
        getCore().startup.start();
      },
      onError: error => console.error("Ersteinrichtung konnte nicht geprüft werden:", error),
    });
}
