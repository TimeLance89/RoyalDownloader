import { createProviderSettings } from "../features/settings/providers.js";
import { syncAnimeNavigationVisibility } from "../shell/presentation.js";
import { syncAniworldNavigationVisibility } from "../shell/presentation.js";
import { sharedPresentation } from "../shell/presentation.js";
import { updateDeploymentModeHints as deploymentHints } from "../features/settings/deployment.js";
import { selectedDeploymentMode as deploymentMode } from "../features/settings/deployment.js";
import { createSettings } from "../features/settings/index.js";
import { fpShowList } from "../shell/actions/movies.js";
import { refreshWatchlist } from "../shell/actions/library.js";
import { createDirectoryPicker } from "../features/settings/directory.js";
import { createUpdater } from "../features/settings/updater.js";
import { createAccountSettings } from "../features/settings/account.js";
import { logout } from "../core/session.js";
import { createCalendar } from "../features/calendar/index.js";
import { loadSeries } from "../shell/actions/series.js";
import { createAutomation } from "../features/automation/index.js";
import { createStorage } from "../features/storage/index.js";
import { createModuleSettings } from "../features/settings/modules.js";

export function composeSettings({ i18n, movieState, seriesState, console, intelligence, subscriptions }) {
return {
providers: createProviderSettings(document.getElementById("settings-sources"), document.getElementById("setup-wizard"), {
      onChange() { syncAnimeNavigationVisibility(); syncAniworldNavigationVisibility(); },
      onApply() { sharedPresentation.anime.invalidate(); },
      onSetupStatus: (message, error) => sharedPresentation.setup.status(message, error),
    }),
deploymentHints: (context, mode) => deploymentHints(document.getElementById(context === "setup" ? "setup-wizard" : "tab-einstellungen"), context, mode),
deploymentMode: name => deploymentMode(document.getElementById(name === "setup-deployment-mode" ? "setup-wizard" : "tab-einstellungen"), name),
settings: createSettings(document.getElementById("tab-einstellungen"), {
      getFeatures: () => sharedPresentation, language: () => i18n.language, locale: () => i18n.locale(),
      changeLanguage: language => i18n.changeLanguage(language, { userInitiated: true, persist: true }),
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
    await sharedPresentation.genres.refresh().catch((error) => {
      console.error("Genres konnten nach dem Quellenwechsel nicht geladen werden:", error);
    });
    if (signal.aborted) return;
    fpShowList("new").catch((error) => {
      document.getElementById("fp-status").textContent = `Fehler: ${error.message}`;
    });
        if (sharedPresentation.subscriptions.get().loaded) void refreshWatchlist();
      },
    }),
directory: createDirectoryPicker(document.getElementById("dir-modal")),
updater: createUpdater(document.getElementById("updater-card")),
intelligence,
account: createAccountSettings(document.getElementById("settings-account"), {
      getUser: () => sharedPresentation.auth.get().user, logout,
      onSaved(result, username) {
        const previous = sharedPresentation.auth.get();
        sharedPresentation.auth.accept({ ...previous, user: result.user || previous.user, configured: true, authenticated: true, username: result.user?.username || username });
      },
    }),
calendar: createCalendar(document.getElementById("tab-kalender"), {
      subscriptions, getUserId: () => String(sharedPresentation.auth.get().user?.id || ""), locale: () => i18n.locale(),
      loadSeries: entry => loadSeries(entry),
    }),
automation: createAutomation(document.getElementById("tab-einstellungen")),
storage: createStorage(document.getElementById("tab-einstellungen")),
modules: createModuleSettings(document.getElementById("tab-einstellungen"))
};
}
