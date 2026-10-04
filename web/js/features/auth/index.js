import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Server authentication snapshot and a separately scoped login form. */
export function createAuthentication(root, {
  client = api, isSetupRequired = () => false, onChange = () => {}, onVisibility = () => {},
  onExpired = () => {}, finishLoading = () => {}, reload = () => location.reload(),
}) {
  const byId = id => root.querySelector(`#${id}`);
  let snapshot = Object.freeze({ configured: false, authenticated: true, prompt_setup: false });
  let owner = createScope(), scope, resolveLogin, visible = false, busy = false;
  function accept(value) { snapshot = Object.freeze({ ...value }); onChange(snapshot); }
  function status(message = "", error = false) {
    byId("login-status").textContent = message; byId("login-status").classList.toggle("error", Boolean(error));
  }
  function clearSecrets() { for (const id of ["login-password", "first-login-password", "first-login-repeat"]) byId(id).value = ""; }
  function hide() {
    visible = false; onVisibility(false); root.classList.add("hidden"); clearSecrets(); status();
    scope?.dispose(); scope = null; busy = false;
  }
  function firstLogin(username) {
    byId("login-form").classList.add("hidden"); byId("first-login-form").classList.remove("hidden");
    byId("first-login-greeting").textContent = `Hallo ${username}. Lege für deinen Zugang ein Passwort fest.`;
    status(); byId("first-login-password").focus();
  }
  function authenticated(value) {
    accept(value); hide();
    if (resolveLogin) { const resolve = resolveLogin; resolveLogin = null; resolve(); }
    else reload();
  }
  async function submit(event) {
    event.preventDefault();
    if (!scope?.active || busy) return;
    const current = scope;
    const username = byId("login-username").value.trim(), password = byId("login-password").value;
    if (!username || !password) { status("Benutzername und Passwort werden benötigt.", true); return; }
    busy = true; byId("login-submit").disabled = true; status("Anmeldung läuft …");
    try {
      const value = await client.post("/api/auth/login", { username, password }, { signal: current.signal });
      if (current.active) authenticated(value);
    } catch (error) {
      if (!current.active) return;
      if (error.status === 409) firstLogin(username);
      else { status(error.message, true); byId("login-password").select(); }
    } finally { if (current.active) { busy = false; byId("login-submit").disabled = false; } }
  }
  async function submitFirst(event) {
    event.preventDefault();
    if (!scope?.active || busy) return;
    const current = scope;
    const username = byId("login-username").value.trim();
    const password = byId("first-login-password").value, repeat = byId("first-login-repeat").value;
    if (!password || password !== repeat) { status("Passwörter stimmen nicht überein.", true); return; }
    busy = true;
    try {
      const value = await client.post("/api/auth/first-login", { username, password, password_repeat: repeat }, { signal: current.signal });
      if (current.active) { accept(value); hide(); reload(); }
    } catch (error) { if (current.active) status(error.message, true); }
    finally { if (current.active) busy = false; }
  }
  function bind() {
    if (scope) return;
    scope = createScope(); busy = false; byId("login-submit").disabled = false;
    scope.listen(byId("login-form"), "submit", submit);
    scope.listen(byId("first-login-form"), "submit", submitFirst);
    scope.listen(byId("login-password-toggle"), "click", event => {
      const button = event.currentTarget, password = byId("login-password");
      const shown = password.type === "text"; password.type = shown ? "password" : "text";
      button.setAttribute("aria-pressed", String(!shown)); button.setAttribute("aria-label", shown ? "Passwort anzeigen" : "Passwort verbergen");
      password.focus();
    });
  }
  function show({ expired = false } = {}) {
    if (visible) return;
    visible = true; bind(); onVisibility(true); root.classList.remove("hidden");
    byId("login-form").classList.remove("hidden"); byId("first-login-form").classList.add("hidden");
    finishLoading(); status(expired ? "Die Sitzung ist abgelaufen. Bitte erneut anmelden." : "", expired);
    clearSecrets();
    scope.timeout(() => (byId("login-username").value.trim() ? byId("login-password") : byId("login-username")).focus(), 60);
  }
  function unauthorized() {
    if (visible || isSetupRequired() || !snapshot.configured) return;
    accept({ ...snapshot, authenticated: false, user: null });
    onExpired(); show({ expired: true });
  }
  function mount() {
    if (!owner.active) owner = createScope();
    client.onUnauthorized = unauthorized;
    if (visible) bind();
  }
  return {
    get: () => snapshot, accept, acceptUser: user => accept({ ...snapshot, user }), unauthorized, mount,
    async requireLogin() {
      mount(); const current = owner;
      try {
        const value = await client.get("/api/auth/status", { signal: current.signal });
        if (!current.active) return;
        accept(value);
      } catch (error) { if (current.active) console.warn("Anmeldestatus konnte nicht geprüft werden:", error); return; }
      if (!snapshot.configured || snapshot.authenticated) return;
      show(); await new Promise(resolve => { resolveLogin = resolve; });
    },
    unmount() {
      owner.dispose(); scope?.dispose(); scope = null; busy = false; clearSecrets();
      if (client.onUnauthorized === unauthorized) client.onUnauthorized = null;
    },
  };
}
