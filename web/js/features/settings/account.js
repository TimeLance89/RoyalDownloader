import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createAccountSettings(root, { client = api, getUser, onSaved, logout,
  confirm = message => window.confirm(message),
}) {
  const byId = id => root.querySelector(`#${id}`);
  let scope;
  let users = [];
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
    byId("account-username").disabled = !!activeUser;
    // Ohne bestehendes Konto gibt es kein aktuelles Passwort zu bestätigen.
    byId("account-current-label").classList.toggle("hidden", !configured);
    byId("account-current-password").classList.toggle("hidden", !configured);
    byId("account-logout").classList.toggle("hidden", !configured);
    byId("account-state").textContent = activeUser
      ? `Angemeldet als „${activeUser.display_name || activeUser.username}“ · ${activeUser.role === "admin" ? "Administrator" : "Mitglied"}. Hier änderst du ausschließlich dein eigenes Passwort.`
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
    identity.textContent = `${user.display_name} · ${user.role === "admin" ? "Administrator" : "Mitglied"} · ${state}`;
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
    } catch (error) {
      if (!currentScope.active) return;
      byId("account-state").textContent =
        `Kontostatus nicht abrufbar: ${error.message}`;
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
    if (!username) {
      setAccountStatus("Der Benutzername fehlt.", true);
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
      for (const id of ["account-save", "new-user-create", "account-revoke"]) byId(id).disabled = false;
      scope.listen(byId("account-save"), "click", saveAccount);
      scope.listen(byId("account-logout"), "click", logout);
      scope.listen(byId("account-revoke"), "click", revokeOtherSessions);
      scope.listen(byId("new-user-create"), "click", createAccountUser);
      scope.listen(byId("account-users-list"), "click", changeUser);
      void refresh();
    },
    unmount() {
      scope?.dispose(); scope = null; pending = null; users = [];
      for (const id of ["account-password", "account-password-repeat", "account-current-password"]) byId(id).value = "";
    },
  };
}
