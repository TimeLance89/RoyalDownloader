import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";

export function createHousehold(root, { userInitials, userRoleLabel }) {
  let scope;
  let opened;
  const find = id => root.querySelector(`#${id}`);
  async function showHousehold() {
    const panel = root;
    const target = find("household-users");
    closeHousehold();
    const current = createScope();
    opened = current;
    panel.hidden = false;
    document.body.classList.add("household-open");
    target.textContent = "Profile werden geladen …";
    let household;
    try { household = await api.get("/api/me/household", { signal: current.signal }); }
    catch (error) {
      if (!current.active || isAbortError(error)) return;
      target.textContent = `Profile konnten nicht geladen werden: ${error.message}`;
      return;
    }
    if (!current.active) return;
    panel.dataset.unlocked = String(Boolean(household.unlocked));
    target.replaceChildren(...household.users.map((user) => {
      const button = document.createElement("button"); button.type = "button"; button.className = "household-user";
      button.dataset.userId = user.id;
      button.style.setProperty("--profile-hue", String([...String(user.id)].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 330));
      const avatar = document.createElement("i"); avatar.textContent = userInitials(user);
      const details = document.createElement("span");
      const name = document.createElement("strong"); name.textContent = user.display_name;
      const role = document.createElement("small"); role.textContent = userRoleLabel(user);
      details.append(name, role); button.append(avatar, details);
      if (user.id === household.current_user_id) {
        button.classList.add("is-current");
        button.setAttribute("aria-current", "true");
        const current = document.createElement("em"); current.textContent = "Aktiv"; button.append(current);
      } else {
        current.listen(button, "click", () => selectHouseholdUser(user));
      }
      return button;
    }));
    panel.hidden = false;
    document.body.classList.add("household-open");
    find("household-unlock").hidden = true;
    current.timeout(() => target.querySelector(".household-user")?.focus(), 0);
  }

  let pendingHouseholdUser = null;

  function closeHousehold() {
    opened?.dispose(); opened = null;
    pendingHouseholdUser = null;
    root.hidden = true;
    find("household-unlock").hidden = true;
    find("household-password").value = "";
    find("household-status").textContent = "";
    document.body.classList.remove("household-open");
  }

  async function switchHouseholdUser(user, password = "") {
    const current = opened;
    if (!current?.active) return;
    const status = find("household-status");
    status.classList.remove("error");
    status.textContent = `Wechsel zu ${user.display_name} …`;
    try {
      await api.post("/api/me/household/switch", { user_id: user.id, password }, { signal: current.signal });
      if (!current.active) return;
      location.reload();
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      status.textContent = error.message;
      status.classList.add("error");
      find("household-password").select();
    }
  }

  function selectHouseholdUser(user) {
    if (root.dataset.unlocked === "true") {
      void switchHouseholdUser(user);
      return;
    }
    pendingHouseholdUser = user;
    find("household-unlock-title").textContent = `Zu ${user.display_name} wechseln`;
    find("household-unlock").hidden = false;
    find("household-password").focus();
  }

  return {
    open: showHousehold, close: closeHousehold,
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.listen(find("household-close"), "click", closeHousehold);
      scope.listen(find("household-unlock"), "submit", event => {
        event.preventDefault();
        if (pendingHouseholdUser) void switchHouseholdUser(pendingHouseholdUser, find("household-password").value);
      });
      scope.listen(document, "keydown", event => {
        if (event.key === "Escape" && !root.hidden) closeHousehold();
      });
    },
    unmount() { closeHousehold(); scope?.dispose(); scope = null; },
  };
}
