export function userInitials(user) {
  return String(user?.display_name || user?.username || "R").trim().slice(0, 1).toLocaleUpperCase("de-DE") || "R";
}

export function userRoleLabel(user) {
  return user?.role === "admin" ? "Administrator" : "Mitglied";
}
