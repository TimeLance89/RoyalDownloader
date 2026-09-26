import { sharedPresentation } from "../presentation.js";
/* Active household identity, profile hub, and personal browser-state boundary. */
export let activeUserId = "";

export function personalStorageKey(base, userId = sharedPresentation.auth.get().user?.id) {
  const id = String(userId || "");
  return id && id !== "admin-legacy" ? `${base}:${id}` : base;
}

export function invalidatePersonalUiState(user = sharedPresentation.auth.get().user) {
  const nextId = String(user?.id || "");
  if (!activeUserId || activeUserId === nextId) { activeUserId = nextId; return; }
  sharedPresentation.recommendations.invalidate();
  sharedPresentation.homePresenter.invalidate();
  activeUserId = nextId;
}

export function initUserProfile() {
  invalidatePersonalUiState(sharedPresentation.auth.get().user);
  sharedPresentation.setUser(sharedPresentation.auth.get().user);
  sharedPresentation.household.mount();
  sharedPresentation.userMenu.mount();
}
