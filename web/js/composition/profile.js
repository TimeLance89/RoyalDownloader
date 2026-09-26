import { createTasteProfile } from "../features/profile/taste.js";
import { sharedPresentation } from "../shell/presentation.js";
import { currentTasteTarget } from "../shell/actions/home.js";
import { renderTasteProfileSummary } from "../shell/actions/home.js";
import { state } from "../shell/presentation.js";
import { renderHome } from "../shell/actions/home.js";
import { homeMovieEntry } from "../shell/actions/home.js";
import { homeSeriesEntry } from "../shell/actions/home.js";
import { homeEntryMedia } from "../shell/actions/home.js";
import { homeEntryKey } from "../shell/actions/home.js";
import { appStore } from "../core/store.js";
import { createProfile } from "../features/profile/index.js";
import { switchTab } from "../shell/presentation.js";
import { userRoleLabel } from "../features/profile/identity.js";

export function composeProfile({ household, userMenu }) {
return {
tasteProfile: createTasteProfile(document, {
      getUser: () => sharedPresentation.auth.get().user, currentTasteTarget, renderTasteProfileSummary,
      shouldRenderHome: () => state.tab === "home" && !sharedPresentation.homeData.get().refreshing && !sharedPresentation.homePresenter.get().rendered,
      renderHome, homeMovieEntry, homeSeriesEntry, homeEntryMedia, homeEntryKey,
      onReset(user) { sharedPresentation.auth.acceptUser(user); sharedPresentation.tasteOnboarding.show(user); },
    }),
household,
userMenu,
setUser: user => appStore.set({ user }),
profile: createProfile(document.getElementById("tab-profil"), {
      switchTab: name => switchTab(name), userRoleLabel,
      applyUser(user) { sharedPresentation.auth.acceptUser(user); },
      showHousehold: () => household.open(), closeHousehold: () => household.close(),
      reopenTasteOnboarding(user) { sharedPresentation.auth.acceptUser(user); sharedPresentation.tasteOnboarding.show(user); },
      openSecurity() { switchTab("einstellungen"); document.getElementById("settings-account")?.scrollIntoView({ behavior: "smooth", block: "start" }); },
    })
};
}
