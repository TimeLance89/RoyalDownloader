import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createAccountSettings(root, { client = api, getUser, onSaved, logout,
  confirm = message => window.confirm(message),
}) {
  const byId = id => root.querySelector(`#${id}`);
  let scope;
  let users = [];
  let profileAvatars = [];
  let pending = null;
  let cancelUsers = () => {};
  function setAccountStatus(message = "", error = false) {
    const el = byId("account-status");
    el.textContent = message;
    el.classList.toggle("error", !!error);
  }

  function applyAccountCfg(cfg) {
    const activeUser = getUser();
    const configured = !!cfg.configured;
    const card = byId("account-card");
    card.dataset.state = configured ? "configured" : "open";
    byId("account-warning").classList.toggle("hidden", configured);
    byId("account-username").value = activeUser?.username || cfg.username || "";
    byId("account-username").disabled = false;
    byId("account-username-save").hidden = !activeUser;
    // Ohne bestehendes Konto gibt es kein aktuelles Passwort zu bestätigen.
    byId("account-current-label").classList.toggle("hidden", !configured);
    byId("account-current-password").classList.toggle("hidden", !configured);
    byId("account-logout").classList.toggle("hidden", !configured);
    byId("account-state").textContent = activeUser
      ? `Angemeldet: Profil „${activeUser.display_name || activeUser.username}“ · Loginname „${activeUser.username}“ · ${activeUser.role === "admin" ? "Administrator" : "Mitglied"}. Profilname und Loginname sind bewusst getrennt.`
      : configured
      ? (cfg.source === "env"
        ? `Angemeldet als „${cfg.username}“ · Zugangsdaten stammen aus APP_USERNAME/APP_PASSWORD. Beim Speichern werden sie in die Einstellungen übernommen.`
        : `Angemeldet als „${cfg.username}“.`)
      : "Es ist kein Konto eingerichtet – die Oberfläche ist ungeschützt erreichbar.";
    byId("account-sessions-count").textContent =
      `${cfg.active_sessions ?? 0} aktive Sitzung(en)`;
    byId("account-save").textContent = activeUser || configured
      ? "Mein Passwort ändern"
      : "Konto anlegen";
  }

  function accountUserRow(user) {
    const row = root.ownerDocument.createElement("div");
    row.className = "account-actions";
    const state = !user.enabled ? "Deaktiviert" : user.setup_required ? "Einrichtung ausstehend" : "Aktiv";
    const identity = root.ownerDocument.createElement("span");
    identity.className = "account-user-identity";
    identity.textContent = `${user.display_name} · Login: ${user.username} · ${user.role === "admin" ? "Administrator" : "Mitglied"} · ${state}`;
    row.appendChild(identity);
    const action = (name, label, className = "") => {
      const button = root.ownerDocument.createElement("button");
      button.type = "button"; button.className = `btn btn-ghost btn-sm ${className}`.trim();
      button.textContent = label; button.dataset.userAction = name; button.dataset.userId = user.id;
      row.appendChild(button);
    };
    if (user.enabled) action("reset", "Passwort zurücksetzen");
    if (user.id !== getUser()?.id) action("delete", "Vollständig löschen", "account-user-delete");
    return row;
  }

  function profileAvatarRow(avatar) {
    const row = root.ownerDocument.createElement("div");
    row.className = "account-avatar-item";
    const image = root.ownerDocument.createElement("img");
    image.src = avatar.url || `/api/profile-avatars/${encodeURIComponent(avatar.id)}`;
    image.alt = "";
    image.loading = "lazy";
    const copy = root.ownerDocument.createElement("div");
    const name = root.ownerDocument.createElement("strong");
    name.textContent = avatar.name || "Eigenes Profilbild";
    const meta = root.ownerDocument.createElement("small");
    const assigned = users.filter(user => user.avatar_id === avatar.id);
    const uploaded = avatar.created_at
      ? `Hochgeladen am ${new Date(avatar.created_at * 1000).toLocaleDateString("de-DE")}`
      : "Eigenes Profilbild";
    meta.textContent = assigned.length
      ? `${uploaded} · Verwendet von: ${assigned.map(user => user.display_name || user.username).join(", ")}`
      : `${uploaded} · Nicht verwendet`;
    copy.append(name, meta);
    const remove = root.ownerDocument.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-ghost btn-sm account-avatar-delete";
    remove.dataset.avatarId = avatar.id;
    remove.setAttribute("aria-label", `Profilbild ${avatar.name || "Eigenes Profilbild"} löschen`);
    remove.textContent = "Profilbild löschen";
    row.append(image, copy, remove);
    return row;
  }

  async function refreshProfileAvatars() {
    const card = byId("account-avatar-card");
    if (!scope?.active || getUser()?.role !== "admin") {
      card.hidden = true;
      return;
    }
    const currentScope = scope;
    card.hidden = false;
    const grid = byId("account-avatar-library");
    grid.textContent = "Profilbilder werden geladen …";
    try {
      const result = await client.get("/api/profile-avatars", { signal: currentScope.signal });
      if (!currentScope.active) return;
      profileAvatars = Array.isArray(result.avatars) ? result.avatars : [];
      grid.replaceChildren(...(profileAvatars.length
        ? profileAvatars.map(profileAvatarRow)
        : [Object.assign(root.ownerDocument.createElement("p"), {
            className: "dim small-status",
            textContent: "Noch keine eigenen Profilbilder hochgeladen.",
          })]));
    } catch (error) {
      if (!currentScope.active) return;
      grid.textContent = `Profilbilder nicht abrufbar: ${error.message}`;
    }
  }

  function fileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error || new Error("Datei konnte nicht gelesen werden."));
      reader.onload = () => {
        const value = String(reader.result || "");
        resolve(value.includes(",") ? value.split(",", 2)[1] : value);
      };
      reader.readAsDataURL(file);
    });
  }

  async function uploadProfileAvatar() {
    if (!scope?.active || getUser()?.role !== "admin") return;
    const currentScope = scope;
    const input = byId("account-avatar-file");
    const button = byId("account-avatar-upload");
    const status = byId("account-avatar-status");
    const file = input.files?.[0];
    status.classList.remove("error");
    if (!file) {
      status.textContent = "Bitte zuerst ein Bild auswählen.";
      status.classList.add("error");
      return;
    }
    if (file.size > 4 * 1024 * 1024) {
      status.textContent = "Das Profilbild darf höchstens 4 MB groß sein.";
      status.classList.add("error");
      return;
    }
    button.disabled = true;
    status.textContent = "Profilbild wird hochgeladen …";
    try {
      const dataBase64 = await fileAsBase64(file);
      await client.post("/api/auth/profile-avatars", {
        filename: file.name,
        content_type: file.type,
        data_base64: dataBase64,
      }, { signal: currentScope.signal, timeoutMs: 45_000 });
      if (!currentScope.active) return;
      input.value = "";
      status.textContent = "✓ Profilbild hochgeladen. Es kann jetzt von allen Profilen ausgewählt werden.";
      await refreshProfileAvatars();
    } catch (error) {
      if (!currentScope.active) return;
      status.textContent = error.message;
      status.classList.add("error");
    } finally {
      if (currentScope.active) button.disabled = false;
    }
  }

  async function deleteProfileAvatar(event) {
    const button = event.target.closest("[data-avatar-id]");
    if (!scope?.active || getUser()?.role !== "admin" || !button || button.disabled) return;
    const avatar = profileAvatars.find(item => item.id === button.dataset.avatarId);
    if (!avatar) return;
    if (!confirm(`Profilbild „${avatar.name || "Eigenes Profilbild"}“ löschen? Profile, die es verwenden, wechseln zurück zu ihren Initialen.`)) return;
    const currentScope = scope;
    const status = byId("account-avatar-status");
    button.disabled = true;
    status.classList.remove("error");
    status.textContent = "Profilbild wird gelöscht …";
    try {
      const result = await client.delete(
        `/api/auth/profile-avatars/${encodeURIComponent(avatar.id)}`,
        { signal: currentScope.signal },
      );
      if (!currentScope.active) return;
      const cleared = Number(result.deleted?.cleared_profiles || 0);
      status.textContent = cleared
        ? `✓ Profilbild gelöscht. ${cleared} Profil(e) wurden auf Initialen zurückgesetzt.`
        : "✓ Profilbild gelöscht.";
      if (getUser()?.avatar_id === avatar.id) {
        const currentUser = await client.get("/api/me", { signal: currentScope.signal });
        if (currentScope.active) onSaved({ user: currentUser, configured: true }, currentUser.username);
      }
      if (currentScope.active) await refreshAccountUsers();
    } catch (error) {
      if (!currentScope.active) return;
      status.textContent = error.message;
      status.classList.add("error");
      button.disabled = false;
    }
  }

  async function changeUser(event) {
    const button = event.target.closest("[data-user-action]");
    const user = users.find(item => String(item.id) === button?.dataset.userId);
    if (!scope?.active || !button || !root.contains(button) || !user || button.disabled) return;
    const current = scope;
    const deleting = button.dataset.userAction === "delete";
    const name = user.display_name || user.username;
    if (deleting && !confirm(`Konto „${name}“ vollständig löschen? Sitzungen, Geschmack, Anfragen und persönliche Abos werden dauerhaft entfernt.`)) return;
    cancelUsers();
    const status = byId("account-users-status");
    button.disabled = true;
    status.classList.remove("error");
    status.textContent = deleting ? `„${name}“ wird vollständig gelöscht …` : "Passwort wird zurückgesetzt …";
    try {
      const path = `/api/auth/users/${encodeURIComponent(user.id)}`;
      if (deleting) await client.delete(path, { signal: current.signal });
      else await client.post(`${path}/reset-password`, {}, { signal: current.signal });
      if (!current.active) return;
      status.textContent = deleting ? `„${name}“ wurde vollständig gelöscht.` : "Passwort wurde zurückgesetzt.";
      await refreshAccountUsers();
    } catch (error) {
      if (!current.active) return;
      status.textContent = error.message; status.classList.add("error");
    } finally { if (current.active) button.disabled = false; }
  }

  async function refreshAccountUsers() {
    if (!scope?.active) return;
    cancelUsers();
    const currentScope = createScope();
    const release = scope.add(() => currentScope.dispose());
    cancelUsers = release;
    const card = byId("account-users-card");
    const list = byId("account-users-list");
    try {
      const result = await client.get("/api/auth/users", { signal: currentScope.signal });
      if (!currentScope.active) return;
      users = result.users || [];
      card.hidden = false;
      list.replaceChildren(...users.map(accountUserRow));
      void refreshProfileAvatars();
    } catch (error) {
      if (!currentScope.active) return;
      card.hidden = [401, 403].includes(error.status);
      if (!card.hidden) list.textContent = `Benutzer nicht abrufbar: ${error.message}`;
    } finally { release(); }
  }

  async function createAccountUser() {
    if (!scope?.active) return;
    const currentScope = scope;
    const button = byId("new-user-create");
    if (button.disabled) return;
    button.disabled = true;
    const status = byId("account-users-status");
    try {
      const displayName = byId("new-user-display-name").value.trim();
      const username = byId("new-user-username").value.trim();
      const role = byId("new-user-role").value;
      const result = await client.post("/api/auth/users", { display_name: displayName, username, role }, { signal: currentScope.signal });
      if (!currentScope.active) return;
      status.textContent = `${result.user.display_name} wurde angelegt und richtet beim ersten Login ein Passwort ein.`;
      byId("new-user-display-name").value = "";
      byId("new-user-username").value = "";
      await refreshAccountUsers();
    } catch (error) { if (!currentScope.active) return; status.textContent = error.message; status.classList.add("error"); } finally { if (currentScope.active) button.disabled = false; }
  }

  async function refreshAccountCard() {
    if (!scope?.active) return;
    const currentScope = scope;
    try {
      const config = await client.get("/api/auth/config", { signal: currentScope.signal });
      if (!currentScope.active) return;
      applyAccountCfg(config);
      void refreshAccountUsers();
      if (getUser()?.role !== "admin") byId("account-avatar-card").hidden = true;
    } catch (error) {
      if (!currentScope.active) return;
      byId("account-state").textContent =
        `Kontostatus nicht abrufbar: ${error.message}`;
    }
  }

  async function saveUsername() {
    if (!scope?.active || !getUser()) return;
    const currentScope = scope;
    const button = byId("account-username-save");
    if (button.disabled) return;
    const username = byId("account-username").value.trim();
    const currentPassword = byId("account-current-password").value;
    if (!username) {
      setAccountStatus("Der Loginname fehlt.", true);
      return;
    }
    if (username === getUser()?.username) {
      setAccountStatus("Der Loginname ist bereits aktuell.");
      return;
    }
    if (!currentPassword) {
      setAccountStatus("Gib zur Änderung dein aktuelles Passwort ein.", true);
      byId("account-current-password").focus();
      return;
    }
    button.disabled = true;
    setAccountStatus("Loginname wird geändert …");
    try {
      const result = await client.post(
        "/api/me/username",
        { username, current_password: currentPassword },
        { signal: currentScope.signal },
      );
      if (!currentScope.active) return;
      byId("account-current-password").value = "";
      onSaved(result, username);
      applyAccountCfg(result);
      setAccountStatus(`✓ Neuer Loginname: „${result.user?.username || username}“. Dein Profilname bleibt unverändert.`);
      void refreshAccountUsers();
    } catch (error) {
      if (!currentScope.active) return;
      setAccountStatus(error.message, true);
    } finally {
      if (currentScope.active) button.disabled = false;
    }
  }

  async function saveAccount() {
    if (!scope?.active) return;
    const currentScope = scope;
    const button = byId("account-save");
    if (button.disabled) return;
    const username = byId("account-username").value.trim();
    const password = byId("account-password").value;
    const repeat = byId("account-password-repeat").value;
    const current = byId("account-current-password").value;
    if (!getUser() && !username) {
      setAccountStatus("Der Loginname fehlt.", true);
      return;
    }
    if (!password) {
      setAccountStatus("Bitte ein neues Passwort eingeben.", true);
      return;
    }
    if (password !== repeat) {
      setAccountStatus("Die beiden Passwörter stimmen nicht überein.", true);
      return;
    }
    button.disabled = true;
    setAccountStatus("Wird gespeichert …");
    try {
      const result = getUser()
        ? await client.post("/api/me/password", { current_password: current, password, password_repeat: repeat }, { signal: currentScope.signal })
        : await client.post("/api/auth/config", { username, password, current_password: current }, { signal: currentScope.signal });
      if (!currentScope.active) return;
      byId("account-password").value = "";
      byId("account-password-repeat").value = "";
      byId("account-current-password").value = "";
      onSaved(result, username);
      applyAccountCfg(result);
      setAccountStatus("✓ Passwort geändert. Andere Sitzungen wurden beendet.");
    } catch (error) {
      if (!currentScope.active) return;
      setAccountStatus(error.message, true);
    } finally {
      if (currentScope.active) button.disabled = false;
    }
  }

  async function revokeOtherSessions() {
    if (!scope?.active) return;
    const currentScope = scope;
    const button = byId("account-revoke");
    if (button.disabled) return;
    button.disabled = true;
    const status = byId("account-revoke-status");
    status.classList.remove("error");
    status.textContent = "Sitzungen werden beendet …";
    try {
      const result = await client.post("/api/auth/sessions/revoke", {}, { signal: currentScope.signal });
      if (!currentScope.active) return;
      status.textContent = `✓ ${result.revoked} Sitzung(en) beendet.`;
      byId("account-sessions-count").textContent =
        `${result.active_sessions ?? 0} aktive Sitzung(en)`;
    } catch (error) {
      if (!currentScope.active) return;
      status.textContent = error.message;
      status.classList.add("error");
    } finally { if (currentScope.active) button.disabled = false; }
  }


  function refresh() {
    if (!scope) return Promise.resolve();
    if (pending) return pending;
    const request = refreshAccountCard().finally(() => { if (pending === request) pending = null; });
    pending = request;
    return request;
  }
  return {
    refresh,
    mount() {
      if (scope) return;
      scope = createScope();
      for (const id of ["account-save", "account-username-save", "new-user-create", "account-revoke", "account-avatar-upload"]) byId(id).disabled = false;
      scope.listen(byId("account-save"), "click", saveAccount);
      scope.listen(byId("account-username-save"), "click", saveUsername);
      scope.listen(byId("account-logout"), "click", logout);
      scope.listen(byId("account-revoke"), "click", revokeOtherSessions);
      scope.listen(byId("new-user-create"), "click", createAccountUser);
      scope.listen(byId("account-users-list"), "click", changeUser);
      scope.listen(byId("account-avatar-upload"), "click", uploadProfileAvatar);
      scope.listen(byId("account-avatar-library"), "click", deleteProfileAvatar);
      void refresh();
    },
    unmount() {
      scope?.dispose(); scope = null; pending = null; users = []; profileAvatars = [];
      for (const id of ["account-password", "account-password-repeat", "account-current-password"]) byId(id).value = "";
    },
  };
}
