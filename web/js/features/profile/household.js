import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { appStore } from "../../core/store.js";
import { applyUserAvatar } from "./identity.js";

const PROFILE_AVATARS = [
  "avatar-red", "avatar-blue", "avatar-gold", "avatar-green",
  "avatar-purple", "avatar-cyan", "avatar-orange", "avatar-slate",
];

export function createHousehold(root, { userRoleLabel }) {
  let scope;
  let opened;
  let householdState = null;
  let pendingHouseholdUser = null;
  let pendingHouseholdAction = "";
  let managedHouseholdUser = null;
  let selectedAvatarId = "";
  let managedJellyfinWritable = false;
  let customProfileAvatars = [];
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
    applyUserAvatar(avatar, user);
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
      const [householdResult, avatarResult] = await Promise.all([
        api.get("/api/me/household", { signal: current.signal }),
        api.get("/api/profile-avatars", { signal: current.signal }).catch(() => ({ avatars: [] })),
      ]);
      household = householdResult;
      customProfileAvatars = Array.isArray(avatarResult.avatars) ? avatarResult.avatars : [];
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

  function renderAvatarChoices(user) {
    const currentAvatar = String(user.avatar_id || "");
    const customIds = new Set(customProfileAvatars.map(item => String(item.id || "")));
    selectedAvatarId = PROFILE_AVATARS.includes(currentAvatar) || customIds.has(currentAvatar)
      ? currentAvatar
      : "";
    const grid = find("household-avatar-grid");
    const choices = [];

    const initials = document.createElement("button");
    initials.type = "button";
    initials.className = "household-avatar-choice is-initials";
    initials.dataset.avatarId = "";
    initials.setAttribute("role", "radio");
    initials.setAttribute("aria-label", "Initialen verwenden");
    const initialsPreview = document.createElement("span");
    initialsPreview.textContent = String(user.display_name || "R").trim().slice(0, 1).toLocaleUpperCase("de-DE");
    initials.append(initialsPreview);
    choices.push(initials);

    PROFILE_AVATARS.forEach(avatarId => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "household-avatar-choice";
      button.dataset.avatarId = avatarId;
      button.setAttribute("role", "radio");
      button.setAttribute("aria-label", `Profilbild ${avatarId.replace("avatar-", "")}`);
      const image = document.createElement("img");
      image.src = `/assets/profile-avatars/${avatarId}.svg`;
      image.alt = "";
      image.loading = "lazy";
      button.append(image);
      choices.push(button);
    });

    customProfileAvatars.forEach(avatar => {
      const avatarId = String(avatar.id || "");
      if (!avatarId) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "household-avatar-choice is-custom";
      button.dataset.avatarId = avatarId;
      button.setAttribute("role", "radio");
      button.setAttribute("aria-label", avatar.name || "Eigenes Profilbild");
      const image = document.createElement("img");
      image.src = avatar.url || `/api/profile-avatars/${encodeURIComponent(avatarId)}`;
      image.alt = "";
      image.loading = "lazy";
      button.append(image);
      choices.push(button);
    });

    const choose = avatarId => {
      selectedAvatarId = avatarId;
      choices.forEach(button => {
        const active = button.dataset.avatarId === avatarId;
        button.classList.toggle("is-selected", active);
        button.setAttribute("aria-checked", String(active));
      });
    };
    choices.forEach(button => opened?.listen(button, "click", () => choose(button.dataset.avatarId || "")));
    grid.replaceChildren(...choices);
    choose(selectedAvatarId);
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
    managedJellyfinWritable = false;
    pendingHouseholdUser = null;
    pendingHouseholdAction = "";
    find("household-unlock").hidden = true;
    const form = find("household-manage");
    const select = find("household-jellyfin-user");
    const status = find("household-manage-status");
    find("household-manage-title").textContent = `${user.display_name} verwalten`;
    find("household-profile-name").value = user.display_name || "";
    renderAvatarChoices(user);
    select.disabled = true;
    find("household-manage-save").disabled = false;
    status.classList.remove("error");
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
      managedJellyfinWritable = Boolean(config.configured && config.available !== false);
      select.disabled = !managedJellyfinWritable;
      status.textContent = !config.configured
        ? "Jellyfin ist nicht eingerichtet. Name und Profilbild können trotzdem gespeichert werden."
        : config.available === false
          ? "Jellyfin-Benutzer sind gerade nicht erreichbar. Name und Profilbild bleiben bearbeitbar."
          : config.user_id
            ? `Verknüpft mit ${config.user_name || "Jellyfin"}.`
            : "Noch kein Jellyfin-Profil verknüpft.";
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      managedJellyfinWritable = false;
      select.disabled = true;
      status.textContent = `Jellyfin: ${error.message}. Name und Profilbild können trotzdem gespeichert werden.`;
    }
  }

  async function saveManagedProfile() {
    const current = opened;
    const user = managedHouseholdUser;
    if (!current?.active || !user) return;
    const select = find("household-jellyfin-user");
    const name = find("household-profile-name").value.trim();
    const status = find("household-manage-status");
    const save = find("household-manage-save");
    if (!name) {
      status.textContent = "Bitte einen Profilnamen eingeben.";
      status.classList.add("error");
      find("household-profile-name").focus();
      return;
    }
    save.disabled = true;
    status.classList.remove("error");
    status.textContent = "Profil wird gespeichert …";
    try {
      const profile = await api.post(
        `/api/me/household/${encodeURIComponent(user.id)}/profile`,
        { display_name: name, avatar_id: selectedAvatarId },
        { signal: current.signal },
      );
      if (!current.active || managedHouseholdUser?.id !== user.id) return;

      if (managedJellyfinWritable) {
        await api.post(
          `/api/me/household/${encodeURIComponent(user.id)}/jellyfin-profile`,
          { user_id: select.value },
          { signal: current.signal },
        );
      }
      if (!current.active) return;

      const saved = profile.user || { ...user, display_name: name, avatar_id: selectedAvatarId };
      Object.assign(user, saved);
      const linkedName = managedJellyfinWritable && select.value
        ? (select.selectedOptions[0]?.textContent || "Jellyfin")
        : "";
      status.textContent = linkedName
        ? `✓ ${saved.display_name || name} ist mit ${linkedName} verknüpft.`
        : `✓ Profil „${saved.display_name || name}“ gespeichert.`;

      if (user.id === householdState?.current_user_id) {
        appStore.set({ user: saved });
        const title = document.getElementById("profile-title");
        if (title) title.textContent = saved.display_name || saved.username || "Royal";
        applyUserAvatar(document.getElementById("profile-avatar"), saved);
      }

      const cards = find("household-users");
      if (cards && householdState) {
        cards.replaceChildren(...householdState.users.map(item => profileCard(item, current)));
      }
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      status.textContent = error.message;
      status.classList.add("error");
      save.disabled = false;
    }
  }

  function closeManagedProfile() {
    managedHouseholdUser = null;
    selectedAvatarId = "";
    managedJellyfinWritable = false;
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
