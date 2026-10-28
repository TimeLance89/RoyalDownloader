import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { applyUserAvatar, profileAvatarUrl } from "../profile/identity.js";

const presets = ["avatar-red", "avatar-blue", "avatar-gold", "avatar-green", "avatar-purple", "avatar-cyan", "avatar-orange", "avatar-slate"];

export function createAccountOverview(root, { client = api, getUser, onUser, onPanelChange, confirm }) {
  const document = root.ownerDocument, find = id => root.querySelector(`#${id}`);
  let scope, owner = "", sessions = [], selectedAvatar = "", panel = "security", pending;
  const valid = current => current?.active && owner && owner === String(getUser()?.id || "");
  const options = current => ({ signal: current.signal, headers: { "X-Royal-Profile": owner } });
  function identity() {
    const user = getUser();
    find("account-display-name").textContent = user?.display_name || user?.username || "Dein Konto";
    find("account-login-summary").textContent = user?.username ? `Login: ${user.username}` : "Konto wird eingerichtet";
    find("account-login-value").textContent = user?.username || "Noch nicht eingerichtet";
    find("account-role-label").textContent = user?.role === "admin" ? "Administrator" : user ? "Mitglied" : "";
    applyUserAvatar(find("account-identity-avatar"), user);
    root.querySelector('[data-account-tab="household"]').hidden = user?.role !== "admin";
    find("account-profile-edit").hidden = !user;
    if (panel === "household" && user?.role !== "admin") activate("security");
  }
  function activate(name) {
    if (name === "household" && getUser()?.role !== "admin") return;
    if (panel !== name) onPanelChange();
    panel = name;
    root.querySelectorAll("[data-account-panel]").forEach(node => { node.hidden = node.dataset.accountPanel !== name; });
    root.querySelectorAll("[data-account-tab]").forEach(node => {
      if (node.dataset.accountTab === name) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
    if (name === "devices") void refreshSessions();
  }
  function deviceName(row) {
    const label = String(row.label || "");
    if (!label.includes("Mozilla") && label) return label;
    const browser = /Edg\//.test(label) ? "Edge" : /Firefox\//.test(label) ? "Firefox" : /Chrome\//.test(label) ? "Chrome" : /Safari\//.test(label) ? "Safari" : "Browser";
    const system = /Android/.test(label) ? "Android" : /iPhone|iPad/.test(label) ? "iOS" : /Windows/.test(label) ? "Windows" : /Macintosh|Mac OS/.test(label) ? "macOS" : /Linux/.test(label) ? "Linux" : "";
    return row.kind === "mobile" && !label ? "Royal-App" : [browser, system].filter(Boolean).join(" · ");
  }
  function paintSessions() {
    const total = sessions.length;
    find("account-device-count").textContent = String(total);
    find("account-sessions-count").textContent = `${total} aktive ${total === 1 ? "Sitzung" : "Sitzungen"}`;
    find("account-devices-summary").textContent = `${total} ${total === 1 ? "Anmeldung" : "Anmeldungen"} · Geräte einzeln prüfen und abmelden`;
    find("account-revoke").disabled = !sessions.some(row => !row.current);
    const list = find("account-device-list"); list.replaceChildren();
    for (const row of sessions) {
      const item = document.createElement("article"); item.className = "account-device-row";
      const glyph = document.createElement("span"); glyph.className = "account-device-glyph"; glyph.textContent = row.kind === "mobile" ? "▯" : "▱"; glyph.setAttribute("aria-hidden", "true");
      const copy = document.createElement("div"); copy.className = "account-device-copy";
      const title = document.createElement("strong"); title.textContent = deviceName(row);
      const meta = document.createElement("span");
      const when = Number(row.last_seen_at) * 1000;
      meta.textContent = `${row.kind === "mobile" ? "App" : "Web-Anmeldung"} · ${when && Date.now() - when < 120_000 ? "Gerade aktiv" : when ? "Zuletzt aktiv: " + new Date(when).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "Zeitpunkt nicht verfügbar"}`;
      copy.append(title, meta);
      if (row.current) {
        const current = document.createElement("span"); current.className = "account-current-session"; current.textContent = "Diese Sitzung"; item.append(glyph, copy, current);
      } else {
        const button = document.createElement("button"); button.type = "button"; button.className = "btn btn-ghost btn-sm"; button.textContent = "Abmelden"; button.setAttribute("aria-label", `${deviceName(row)} abmelden`);
        button.addEventListener("click", () => { void revoke(row, button); }); item.append(glyph, copy, button);
      }
      list.append(item);
    }
    if (!total) list.textContent = "Keine gespeicherten Sitzungen für dieses Konto gefunden.";
  }
  async function refreshSessions() {
    const current = scope;
    if (!valid(current)) return;
    if (pending) return pending;
    const request = (async () => {
      try {
        const data = await client.get("/api/me/sessions", options(current));
        if (!valid(current)) return;
        if (!Array.isArray(data.sessions)) throw new Error("Sitzungsliste ist nicht verfügbar.");
        sessions = data.sessions; paintSessions();
      } catch (error) {
        if (!valid(current) || error.name === "AbortError") return;
        find("account-device-count").textContent = "—";
        find("account-devices-summary").textContent = "Sitzungen konnten nicht geladen werden";
        find("account-sessions-count").textContent = "Aktualisierung fehlgeschlagen";
        find("account-revoke-status").textContent = error.message;
      }
    })().finally(() => { if (pending === request) pending = null; });
    pending = request; return request;
  }
  async function revoke(row, button) {
    const current = scope;
    if (!valid(current) || !confirm(`„${deviceName(row)}“ von deinem Konto abmelden?`)) return;
    button.disabled = true;
    try {
      const data = await client.delete(`/api/me/sessions/${encodeURIComponent(row.id)}`, options(current));
      if (!valid(current)) return;
      sessions = data.sessions; paintSessions(); find("account-revoke-status").textContent = "Sitzung beendet.";
    } catch (error) { if (valid(current)) { find("account-revoke-status").textContent = error.message; button.disabled = false; } }
  }
  async function revokeOthers() {
    const current = scope;
    if (!valid(current) || !confirm("Alle anderen Web- und App-Anmeldungen deines Kontos beenden? Diese Sitzung bleibt geöffnet.")) return;
    find("account-revoke").disabled = true;
    try {
      const data = await client.post("/api/me/sessions/revoke-others", {}, options(current));
      if (!valid(current)) return;
      sessions = data.sessions; paintSessions(); find("account-revoke-status").textContent = `${data.revoked} andere Sitzung(en) beendet.`;
    } catch (error) { if (valid(current)) { find("account-revoke-status").textContent = error.message; paintSessions(); } }
  }
  function avatars(custom = []) {
    const grid = find("account-profile-avatars"); grid.replaceChildren();
    const rows = [{ id: "", name: "Initialen" }, ...presets.map((id, i) => ({ id, name: `Royal-Profilbild ${i + 1}`, url: profileAvatarUrl({ avatar_id: id }) })), ...custom];
    for (const avatar of rows) {
      const button = document.createElement("button"); button.type = "button"; button.setAttribute("aria-label", avatar.name || "Eigenes Profilbild"); button.setAttribute("aria-pressed", String(selectedAvatar === avatar.id)); button.className = "account-profile-choice";
      if (avatar.url) { const img = document.createElement("img"); img.src = avatar.url; img.alt = ""; button.append(img); }
      else button.textContent = String(getUser()?.display_name || "R").slice(0, 1);
      button.addEventListener("click", () => { selectedAvatar = avatar.id; grid.querySelectorAll("button").forEach(node => node.setAttribute("aria-pressed", String(node === button))); }); grid.append(button);
    }
  }
  async function openProfile() {
    const current = scope;
    if (!valid(current)) return;
    find("account-profile-name").value = getUser().display_name || getUser().username;
    selectedAvatar = getUser().avatar_id || ""; find("account-profile-editor").hidden = false; avatars();
    find("account-profile-name").focus();
    try {
      const data = await client.get("/api/profile-avatars", options(current));
      if (valid(current) && !find("account-profile-editor").hidden) avatars(Array.isArray(data.avatars) ? data.avatars : []);
    } catch { /* Preset avatars remain available. */ }
  }
  async function saveProfile() {
    const current = scope;
    if (!valid(current)) return;
    const status = find("account-profile-status"), button = find("account-profile-save");
    const displayName = find("account-profile-name").value.trim();
    if (!displayName) { status.textContent = "Ein Profilname fehlt."; return; }
    button.disabled = true;
    try {
      const data = await client.post(`/api/me/household/${encodeURIComponent(owner)}/profile`, { display_name: displayName, avatar_id: selectedAvatar }, options(current));
      if (!valid(current)) return;
      onUser(data.user); identity(); status.textContent = "Profil gespeichert.";
    } catch (error) { if (valid(current)) status.textContent = error.message; }
    finally { if (valid(current)) button.disabled = false; }
  }
  return {
    render: identity, refreshSessions,
    mount() {
      if (scope) return; find("account-revoke").disabled = true; scope = createScope(); owner = String(getUser()?.id || ""); identity(); activate("security");
      for (const button of root.querySelectorAll("[data-account-tab], [data-account-open]")) scope.listen(button, "click", () => activate(button.dataset.accountTab || button.dataset.accountOpen));
      scope.listen(find("account-profile-edit"), "click", () => { void openProfile(); });
      scope.listen(find("account-profile-save"), "click", () => { void saveProfile(); });
      scope.listen(find("account-profile-cancel"), "click", () => { find("account-profile-editor").hidden = true; });
      scope.listen(find("account-revoke"), "click", () => { void revokeOthers(); });
      void refreshSessions();
    },
    unmount() { scope?.dispose(); scope = null; owner = ""; sessions = []; pending = null; find("account-profile-editor").hidden = true; find("account-device-list").replaceChildren(); },
  };
}
