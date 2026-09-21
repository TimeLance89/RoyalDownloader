/* Active household identity, profile hub, and personal browser-state boundary. */
let activeUserId = "";

function personalStorageKey(base, userId = authStatus?.user?.id) {
  const id = String(userId || "");
  return id && id !== "admin-legacy" ? `${base}:${id}` : base;
}

function userInitials(user = authStatus?.user) {
  return String(user?.display_name || user?.username || "R").trim().slice(0, 1).toLocaleUpperCase("de-DE") || "R";
}

function userRoleLabel(user = authStatus?.user) {
  return user?.role === "admin" ? "Administrator" : "Mitglied";
}

function applyActiveUser(user = authStatus?.user) {
  if (!user) return;
  const name = user.display_name || user.username;
  const initial = userInitials(user);
  ["user-menu-name", "user-menu-popover-name", "profile-title"].forEach((id) => {
    const element = document.getElementById(id); if (element) element.textContent = name;
  });
  ["user-menu-role", "user-menu-popover-role"].forEach((id) => {
    const element = document.getElementById(id); if (element) element.textContent = userRoleLabel(user);
  });
  ["user-menu-avatar", "profile-avatar"].forEach((id) => {
    const element = document.getElementById(id); if (element) element.textContent = initial;
  });
  document.getElementById("user-menu-admin")?.toggleAttribute("hidden", user.role !== "admin");
}

function invalidatePersonalUiState(user = authStatus?.user) {
  const nextId = String(user?.id || "");
  if (!activeUserId || activeUserId === nextId) { activeUserId = nextId; return; }
  api._inflightGets.clear();
  state.ai.recommendations = [];
  state.ai.lastFingerprint = "";
  state.home.rendered = false;
  activeUserId = nextId;
}

function tasteConfidenceCopy(value, interactions) {
  if (interactions < 5 || value < .2) return "Wir lernen dich noch kennen.";
  if (value < .55) return "Dein Geschmacksprofil nimmt Form an.";
  return "Dein Geschmacksprofil ist gut etabliert.";
}

function renderProfileSummary(summary) {
  const taste = summary.taste || {};
  const confidence = Math.max(0, Math.min(1, Number(taste.confidence || 0)));
  document.getElementById("profile-confidence").textContent = tasteConfidenceCopy(confidence, Number(taste.interactions || 0));
  document.getElementById("profile-confidence-bar").style.width = `${Math.max(8, confidence * 100)}%`;
  document.getElementById("profile-interactions").textContent = String(taste.interactions || 0);
  document.getElementById("profile-download-count").textContent = String(summary.downloads_requested || 0);
  const genres = Object.entries(taste.genres || {}).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 5);
  const maximum = Math.max(1, ...genres.map(([, score]) => Math.abs(Number(score) || 0)));
  document.getElementById("profile-genres").replaceChildren(...(genres.length ? genres.map(([name, score]) => {
    const row = document.createElement("div");
    const label = document.createElement("span"); label.textContent = name;
    const meter = document.createElement("i");
    const fill = document.createElement("b");
    fill.style.width = `${Math.max(8, Math.abs(Number(score)) / maximum * 100)}%`;
    meter.append(fill); row.append(label, meter);
    return row;
  }) : [Object.assign(document.createElement("p"), { textContent: "Noch keine ausreichenden Signale." })]));
  const recent = summary.recent_downloads || [];
  document.getElementById("profile-recent-downloads").replaceChildren(...(recent.length ? recent.map((download) => {
    const card = document.createElement("div"); card.className = "profile-download"; card.textContent = download.title; card.title = download.status; return card;
  }) : [Object.assign(document.createElement("p"), { textContent: "Du hast noch keine Downloads angefordert." })]));
  const created = summary.user?.created_at ? new Date(summary.user.created_at * 1000).toLocaleDateString("de-DE", { month: "long", year: "numeric" }) : "";
  document.getElementById("profile-member-since").textContent = created ? `Mitglied seit ${created}` : userRoleLabel(summary.user);
}

async function refreshUserProfile() {
  const summary = await api.meProfileSummary();
  authStatus.user = summary.user;
  applyActiveUser(summary.user);
  renderProfileSummary(summary);
}

async function showHousehold() {
  const panel = document.getElementById("household-panel");
  const target = document.getElementById("household-users");
  const household = await api.meHousehold();
  target.replaceChildren(...household.users.map((user) => {
    const button = document.createElement("button"); button.type = "button"; button.className = "household-user";
    const avatar = document.createElement("i"); avatar.textContent = userInitials(user);
    const details = document.createElement("span");
    const name = document.createElement("strong"); name.textContent = user.display_name;
    const role = document.createElement("small"); role.textContent = userRoleLabel(user);
    details.append(name, role); button.append(avatar, details);
    if (user.id !== household.current_user_id) button.addEventListener("click", () => logoutAccount());
    return button;
  }));
  panel.hidden = false;
}

function closeUserMenu() {
  const menu = document.getElementById("user-menu");
  document.getElementById("user-menu-popover").hidden = true;
  document.getElementById("user-menu-trigger").setAttribute("aria-expanded", "false");
  menu?.classList.remove("is-open");
}

function initUserProfile() {
  invalidatePersonalUiState(authStatus.user);
  applyActiveUser(authStatus.user);
  const trigger = document.getElementById("user-menu-trigger");
  trigger.addEventListener("click", () => {
    const popover = document.getElementById("user-menu-popover"); const open = popover.hidden;
    popover.hidden = !open; trigger.setAttribute("aria-expanded", String(open)); document.getElementById("user-menu").classList.toggle("is-open", open);
  });
  document.addEventListener("click", (event) => { if (!event.target.closest("#user-menu")) closeUserMenu(); });
  document.getElementById("user-menu-popover").addEventListener("click", async (event) => {
    const action = event.target.closest("[data-user-action]")?.dataset.userAction; if (!action) return; closeUserMenu();
    if (action === "logout" || action === "users") { if (action === "users") switchTab("einstellungen"); else logoutAccount(); return; }
    if (action === "profile" || action === "downloads") { switchTab("profil"); await refreshUserProfile(); if (action === "downloads") document.querySelector(".profile-downloads")?.scrollIntoView({ behavior: "smooth" }); return; }
    if (action === "taste") { switchTab("profil"); await refreshUserProfile(); document.querySelector(".profile-taste")?.scrollIntoView({ behavior: "smooth" }); return; }
    if (action === "security") { switchTab("einstellungen"); document.getElementById("settings-account")?.scrollIntoView({ behavior: "smooth" }); return; }
    if (action === "household") { switchTab("profil"); await refreshUserProfile(); await showHousehold(); }
  });
  document.getElementById("profile-edit-taste").addEventListener("click", async () => {
    if (!window.confirm("Geschmack vollständig neu aufbauen? Bisherige persönliche Signale werden gelöscht.")) return;
    const response = await api.tasteReset(); reopenTasteOnboarding(response.user);
  });
  document.getElementById("profile-security").addEventListener("click", () => switchTab("einstellungen"));
}

window.initUserProfile = initUserProfile;
window.refreshUserProfile = refreshUserProfile;
