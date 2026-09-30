const PROFILE_AVATAR_PATH = "/assets/profile-avatars/";

export function userInitials(user) {
  return String(user?.display_name || user?.username || "R").trim().slice(0, 1).toLocaleUpperCase("de-DE") || "R";
}

export function profileAvatarUrl(user) {
  const avatar = String(user?.avatar_id || "").trim();
  return avatar ? `${PROFILE_AVATAR_PATH}${avatar}.svg` : "";
}

export function applyUserAvatar(element, user) {
  if (!element) return;
  const url = profileAvatarUrl(user);
  element.classList.toggle("has-profile-avatar", Boolean(url));
  element.style.backgroundImage = url ? `url("${url}")` : "";
  element.textContent = url ? "" : userInitials(user);
}

export function userRoleLabel(user) {
  return user?.role === "admin" ? "Administrator" : "Mitglied";
}
