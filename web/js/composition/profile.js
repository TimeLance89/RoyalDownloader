import { createTasteOnboarding } from "../features/profile/taste-onboarding.js";
import { createAuthentication } from "../features/auth/index.js";
import { createProfileActions } from "../features/profile/actions.js";
import { logout } from "../core/session.js";
import { createUserMenu } from "../features/profile/menu.js";
import { userInitials } from "../features/profile/identity.js";
import { createHousehold } from "../features/profile/household.js";
import { createTasteProfile } from "../features/profile/taste.js";

import { appStore } from "../core/store.js";
import { createProfile } from "../features/profile/index.js";

import { userRoleLabel } from "../features/profile/identity.js";

export function composeProfile({ household, userMenu, state, getHome, getCore }) {
  const services = {
  tasteProfile: createTasteProfile(document, {
        getUser: () => services.auth.get().user, currentTasteTarget: (...args) => getHome().actions.currentTasteTarget(...args), renderTasteProfileSummary: (...args) => getHome().actions.renderTasteProfileSummary(...args),
        shouldRenderHome: () => state.tab === "home" && !getHome().homeData.get().refreshing && !getHome().homePresenter.get().rendered,
        renderHome: (...args) => getHome().actions.renderHome(...args), homeMovieEntry: (...args) => getHome().actions.homeMovieEntry(...args), homeSeriesEntry: (...args) => getHome().actions.homeSeriesEntry(...args), homeEntryMedia: (...args) => getHome().actions.homeEntryMedia(...args), homeEntryKey: (...args) => getHome().actions.homeEntryKey(...args),
        onReset(user) { services.auth.acceptUser(user); services.tasteOnboarding.show(user); },
      }),
  household,
  userMenu,
  setUser: user => appStore.set({ user }),
  profile: createProfile(document.getElementById("tab-profil"), {
        switchTab: name => getCore().actions.switchTab(name), userRoleLabel,
        applyUser(user) { services.auth.acceptUser(user); },
        showHousehold: () => household.open(), closeHousehold: () => household.close(),
        reopenTasteOnboarding(user) { services.auth.acceptUser(user); services.tasteOnboarding.show(user); },
        openSecurity() { getCore().actions.switchTab("einstellungen"); document.getElementById("settings-account")?.scrollIntoView({ behavior: "smooth", block: "start" }); },
      })
  };

  return services;
}

export function prepareProfile({ getCore, getProfile, getHome }) {
  const household = createHousehold(document.getElementById("household-panel"), { userInitials, userRoleLabel });
  const userMenu = createUserMenu(document.getElementById("user-menu"), {
      logout, navigate: name => getCore().actions.switchTab(name),
      openHousehold: () => household.open(),
      openSecurity() { getCore().actions.switchTab("einstellungen"); document.getElementById("settings-account")?.scrollIntoView({ behavior: "smooth" }); },
    });
  window.addEventListener("pagehide", () => { household.unmount(); userMenu.unmount(); });
  window.addEventListener("pageshow", event => { if (event.persisted && appStore.get().user) { household.mount(); userMenu.mount(); } });
  document.addEventListener("royal:session-expired", () => { household.unmount(); userMenu.unmount(); });
  const profileActions = createProfileActions({
      getUser: () => getProfile().auth.get().user,
      invalidateRecommendations: () => getHome().recommendations.invalidate(),
      invalidateHome: () => getHome().homePresenter.invalidate(),
      setUser: user => appStore.set({ user }), household, userMenu,
    });
  const { personalStorageKey } = profileActions;
  return { household, userMenu, profileActions, personalStorageKey };
}

export function initializeProfile({ getProfile, getSettings, getCore, getHome, profileActions }) {
  getProfile().auth = createAuthentication(document.getElementById("login-screen"), {
      isSetupRequired: () => Boolean(getSettings().setup?.required),
      onChange: status => appStore.set({ user: status.user || null }),
      onVisibility: visible => document.body.classList.toggle("login-open", visible),
      onExpired: () => document.dispatchEvent(new Event("royal:session-expired")),
      finishLoading: () => getCore().startupCurtain.finish(),
    });
  window.addEventListener("pagehide", () => getProfile().auth.unmount());
  window.addEventListener("pageshow", event => { if (event.persisted) getProfile().auth.mount(); });
  getProfile().tasteOnboarding = createTasteOnboarding(document.getElementById("taste-onboarding"), {
      getUser: () => getProfile().auth.get().user, acceptUser: user => getProfile().auth.acceptUser(user),
      homeData: getHome().homeData, homeAllEntries: () => getHome().actions.homeAllEntries(),
      homeEntryMedia: entry => getHome().actions.homeEntryMedia(entry), homeEntryKey: entry => getHome().actions.homeEntryKey(entry),
      tasteMetadata: (...args) => getHome().actions.tasteMetadata(...args),
      onVisibility: visible => document.body.classList.toggle("taste-onboarding-open", visible),
      onSaved(profile) {
        getHome().actions.applyServerTasteProfile(profile); getHome().recommendations.invalidate();
        getHome().actions.renderHome({ force: true }); void getHome().recommendations.refresh(true);
      },
    });
  getProfile().identityActions = profileActions;
}
