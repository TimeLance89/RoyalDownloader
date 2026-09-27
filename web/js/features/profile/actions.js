export function createProfileActions({ getUser, invalidateRecommendations, invalidateHome, setUser, household, userMenu }) {
/* Active household identity, profile hub, and personal browser-state boundary. */
let activeUserId = "";

function personalStorageKey(base, userId = getUser()?.id) {
  const id = String(userId || "");
  return id && id !== "admin-legacy" ? `${base}:${id}` : base;
}

function invalidatePersonalUiState(user = getUser()) {
  const nextId = String(user?.id || "");
  if (!activeUserId || activeUserId === nextId) { activeUserId = nextId; return; }
  invalidateRecommendations();
  invalidateHome();
  activeUserId = nextId;
}

function initUserProfile() {
  invalidatePersonalUiState(getUser());
  setUser(getUser());
  household.mount();
  userMenu.mount();
}

return { personalStorageKey, invalidatePersonalUiState, initUserProfile };
}
