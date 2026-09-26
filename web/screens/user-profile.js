/* Active household identity, profile hub, and personal browser-state boundary. */
let activeUserId = "";

function personalStorageKey(base, userId = sharedPresentation.auth.get().user?.id) {
  const id = String(userId || "");
  return id && id !== "admin-legacy" ? `${base}:${id}` : base;
}

function invalidatePersonalUiState(user = sharedPresentation.auth.get().user) {
  const nextId = String(user?.id || "");
  if (!activeUserId || activeUserId === nextId) { activeUserId = nextId; return; }
  sharedPresentation.recommendations.invalidate();
  sharedPresentation.homePresenter.invalidate();
  activeUserId = nextId;
}

function initUserProfile() {
  invalidatePersonalUiState(sharedPresentation.auth.get().user);
  sharedPresentation.setUser(sharedPresentation.auth.get().user);
  sharedPresentation.household.mount();
  sharedPresentation.userMenu.mount();
}
