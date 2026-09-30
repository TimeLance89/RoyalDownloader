import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";

export function createHousehold(root, { userInitials, userRoleLabel }) {
  let scope;
  let opened;
  let householdState = null;
  let pendingHouseholdUser = null;
  let pendingHouseholdAction = "";
  let managedHouseholdUser = null;
  const find = id => root.querySelector(`#${id}`);

  function hideAuxiliaryPanels() {
    find("household-unlock").hidden = true;
    find("household-manage").hidden = true;
    find("household-password").value = "";
    find("household-status").textContent = "";
    find("household-status").classList.remove("error");
  }

  function profileCard(user, current) {
    const wrapper = document.createElement("div");
    wrapper.className = "household-profile";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "household-user";
    button.dataset.userId = user.id;
    button.style.setProperty(
      "--profile-hue",
      String([...String(user.id)].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 330),
    );

    const avatar = document.createElement("i");
    avatar.textContent = userInitials(user);
    const details = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = user.display_name;
    const role = document.createElement("small");
    role.textContent = userRoleLabel(user);
    details.append(name, role);
    button.append(avatar, details);

    if (user.id === householdState?.current_user_id) {
      button.classList.add("is-current");
      button.setAttribute("aria-current", "true");
      const active = document.createElement("em");
      active.textContent = "Aktiv";
      button.append(active);
    } else {
      current.listen(button, "click", () => selectHouseholdUser(user));
    }

    const settings = document.createElement("button");
    settings.type = "button";
    settings.className = "household-user-settings";
    settings.dataset.userId = user.id;
    settings.setAttribute("aria-label", `${user.display_name} verwalten`);
    settings.title = `${user.display_name} verwalten`;
    settings.innerHTML = '<span aria-hidden="true">⚙</span><small>Profil</small>';
    current.listen(settings, "click", () => manageHouseholdUser(user));

    wrapper.append(button, settings);
    return wrapper;
  }

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
    try {
      household = await api.get("/api/me/household", { signal: current.signal });
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      target.textContent = `Profile konnten nicht geladen werden: ${error.message}`;
      return;
    }
    if (!current.active) return;
    householdState = household;
    panel.dataset.unlocked = String(Boolean(household.unlocked));
    target.replaceChildren(...household.users.map(user => profileCard(user, current)));
    hideAuxiliaryPanels();
    current.timeout(() => target.querySelector(".household-user")?.focus(), 0);
  }

  function closeHousehold() {
    opened?.dispose();
    opened = null;
    householdState = null;
    pendingHouseholdUser = null;
    pendingHouseholdAction = "";
    managedHouseholdUser = null;
    root.hidden = true;
    hideAuxiliaryPanels();
    document.body.classList.remove("household-open");
  }

  function showUnlock(user, action) {
    pendingHouseholdUser = user;
    pendingHouseholdAction = action;
    find("household-manage").hidden = true;
    find("household-unlock-title").textContent = action === "manage"
      ? `${user.display_name} verwalten`
      : `Zu ${user.display_name} wechseln`;
    find("household-unlock-copy").textContent = action === "manage"
      ? "Einmal Passwort eingeben. Danach kannst du die Profile in dieser Sitzung verwalten."
      : "Einmal Passwort eingeben. Danach wechselst du in dieser Sitzung direkt.";
    find("household-unlock").hidden = false;
    find("household-password").focus();
  }

  async function switchHouseholdUser(user, password = "") {
    const current = opened;
    if (!current?.active) return;
    const status = find("household-status");
    status.classList.remove("error");
    status.textContent = `Wechsel zu ${user.display_name} …`;
    try {
      await api.post(
        "/api/me/household/switch",
        { user_id: user.id, password },
        { signal: current.signal },
      );
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
    showUnlock(user, "switch");
  }

  async function unlockHousehold(password) {
    const current = opened;
    if (!current?.active) return false;
    const status = find("household-status");
    status.classList.remove("error");
    status.textContent = "Profilverwaltung wird freigegeben …";
    try {
      await api.post("/api/me/household/unlock", { password }, { signal: current.signal });
      if (!current.active) return false;
      root.dataset.unlocked = "true";
      if (householdState) householdState.unlocked = true;
      find("household-unlock").hidden = true;
      status.textContent = "";
      return true;
    } catch (error) {
      if (!current.active || isAbortError(error)) return false;
      status.textContent = error.message;
      status.classList.add("error");
      find("household-password").select();
      return false;
    }
  }

  async function manageHouseholdUser(user) {
    const current = opened;
    if (!current?.active) return;
    const isCurrent = user.id === householdState?.current_user_id;
    if (!isCurrent && root.dataset.unlocked !== "true") {
      showUnlock(user, "manage");
      return;
    }
    managedHouseholdUser = user;
    pendingHouseholdUser = null;
    pendingHouseholdAction = "";
    find("household-unlock").hidden = true;
    const form = find("household-manage");
    const select = find("household-jellyfin-user");
    const status = find("household-manage-status");
    find("household-manage-title").textContent = `${user.display_name} verwalten`;
    select.disabled = true;
    find("household-manage-save").disabled = true;
    status.textContent = "Jellyfin-Profile werden geladen …";
    form.hidden = false;

    try {
      const config = await api.get(
        `/api/me/household/${encodeURIComponent(user.id)}/jellyfin-profile`,
        { signal: current.signal },
      );
      if (!current.active || managedHouseholdUser?.id !== user.id) return;
      const users = Array.isArray(config.users) ? config.users : [];
      const options = [
        Object.assign(document.createElement("option"), {
          value: "",
          textContent: "Nicht mit Jellyfin verknüpfen",
        }),
      ];
      users.forEach(jellyfinUser => {
        const option = document.createElement("option");
        option.value = jellyfinUser.id || "";
        option.textContent = jellyfinUser.name || jellyfinUser.id || "Jellyfin";
        options.push(option);
      });
      select.replaceChildren(...options);
      if (config.user_id && !users.some(jellyfinUser => jellyfinUser.id === config.user_id)) {
        const stale = document.createElement("option");
        stale.value = config.user_id;
        stale.textContent = config.user_name || "Bisher verknüpfter Jellyfin-Benutzer";
        select.append(stale);
      }
      select.value = config.user_id || "";
      select.disabled = !config.configured || config.available === false;
      find("household-manage-save").disabled = select.disabled;
      status.textContent = !config.configured
        ? "Jellyfin zuerst unter Einstellungen → Dienste einrichten."
        : config.available === false
          ? "Jellyfin-Benutzer sind gerade nicht erreichbar."
          : config.user_id
            ? `Verknüpft mit ${config.user_name || "Jellyfin"}.`
            : "Noch kein Jellyfin-Profil verknüpft.";
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      status.textContent = error.message;
      status.classList.add("error");
    }
  }

  async function saveManagedProfile() {
    const current = opened;
    const user = managedHouseholdUser;
    if (!current?.active || !user) return;
    const select = find("household-jellyfin-user");
    const status = find("household-manage-status");
    const save = find("household-manage-save");
    save.disabled = true;
    status.classList.remove("error");
    status.textContent = "Jellyfin-Verknüpfung wird gespeichert …";
    try {
      const config = await api.post(
        `/api/me/household/${encodeURIComponent(user.id)}/jellyfin-profile`,
        { user_id: select.value },
        { signal: current.signal },
      );
      if (!current.active || managedHouseholdUser?.id !== user.id) return;
      status.textContent = config.user_id
        ? `✓ ${user.display_name} ist mit ${config.user_name || "Jellyfin"} verknüpft.`
        : `Jellyfin-Verknüpfung für ${user.display_name} entfernt.`;
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      status.textContent = error.message;
      status.classList.add("error");
    } finally {
      if (current.active && managedHouseholdUser?.id === user.id) {
        save.disabled = select.disabled;
      }
    }
  }

  function closeManagedProfile() {
    managedHouseholdUser = null;
    const form = find("household-manage");
    form.hidden = true;
    find("household-manage-status").textContent = "";
    find("household-manage-status").classList.remove("error");
  }

  return {
    open: showHousehold,
    close: closeHousehold,
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.listen(find("household-close"), "click", closeHousehold);
      scope.listen(find("household-unlock"), "submit", async event => {
        event.preventDefault();
        if (!pendingHouseholdUser) return;
        if (pendingHouseholdAction === "manage") {
          const user = pendingHouseholdUser;
          if (await unlockHousehold(find("household-password").value)) {
            await manageHouseholdUser(user);
          }
          return;
        }
        void switchHouseholdUser(pendingHouseholdUser, find("household-password").value);
      });
      scope.listen(find("household-manage"), "submit", event => {
        event.preventDefault();
        void saveManagedProfile();
      });
      scope.listen(find("household-manage-cancel"), "click", closeManagedProfile);
      scope.listen(document, "keydown", event => {
        if (event.key === "Escape" && !root.hidden) {
          if (!find("household-manage").hidden) closeManagedProfile();
          else closeHousehold();
        }
      });
    },
    unmount() {
      closeHousehold();
      scope?.dispose();
      scope = null;
    },
  };
}
