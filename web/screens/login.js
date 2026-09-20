// Login screen: browser session lifecycle and reauthentication.
let authStatus = { configured: false, authenticated: true, prompt_setup: false };
let loginResolve = null;
let loginVisible = false;

function setLoginStatus(message = "", error = false) {
  const el = document.getElementById("login-status");
  el.textContent = message;
  el.classList.toggle("error", !!error);
}

function showLoginScreen({ expired = false } = {}) {
  const screen = document.getElementById("login-screen");
  if (loginVisible) return;
  loginVisible = true;
  document.body.classList.add("login-open");
  screen.classList.remove("hidden");
  document.getElementById("login-form").classList.remove("hidden");
  document.getElementById("first-login-form").classList.add("hidden");
  window.royalLoader?.finish();
  setLoginStatus(expired ? "Die Sitzung ist abgelaufen. Bitte erneut anmelden." : "", expired);
  const username = document.getElementById("login-username");
  const password = document.getElementById("login-password");
  password.value = "";
  window.setTimeout(() => (username.value.trim() ? password : username).focus(), 60);
}

function hideLoginScreen() {
  loginVisible = false;
  document.body.classList.remove("login-open");
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("login-password").value = "";
  document.getElementById("first-login-password").value = "";
  document.getElementById("first-login-repeat").value = "";
  setLoginStatus();
}

function showFirstLogin(username) {
  document.getElementById("login-form").classList.add("hidden");
  document.getElementById("first-login-form").classList.remove("hidden");
  document.getElementById("first-login-greeting").textContent = `Hallo ${username}. Lege für deinen Zugang ein Passwort fest.`;
  setLoginStatus();
  document.getElementById("first-login-password").focus();
}

async function submitLogin(event) {
  if (event) event.preventDefault();
  const button = document.getElementById("login-submit");
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  if (!username || !password) {
    setLoginStatus("Benutzername und Passwort werden benötigt.", true);
    return;
  }
  button.disabled = true;
  setLoginStatus("Anmeldung läuft …");
  try {
    authStatus = await api.authLogin(username, password);
    hideLoginScreen();
    if (loginResolve) {
      const resolve = loginResolve;
      loginResolve = null;
      resolve();
    } else {
      location.reload();
    }
  } catch (error) {
    if (error.status === 409) showFirstLogin(username);
    else { setLoginStatus(error.message, true); document.getElementById("login-password").select(); }
  } finally {
    button.disabled = false;
  }
}

async function submitFirstLogin(event) {
  event.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("first-login-password").value;
  const repeat = document.getElementById("first-login-repeat").value;
  if (!password || password !== repeat) { setLoginStatus("Passwörter stimmen nicht überein.", true); return; }
  try {
    authStatus = await api.authFirstLogin(username, password, repeat);
    hideLoginScreen();
    location.reload();
  } catch (error) { setLoginStatus(error.message, true); }
}

function handleUnauthorized() {
  if (loginVisible || setupRequired) return;
  showLoginScreen({ expired: true });
}

async function requireLogin() {
  try {
    authStatus = await api.authStatus();
  } catch (error) {
    console.warn("Anmeldestatus konnte nicht geprüft werden:", error);
    return;
  }
  if (!authStatus.configured || authStatus.authenticated) return;
  showLoginScreen();
  await new Promise((resolve) => { loginResolve = resolve; });
}

function initLoginScreen() {
  api.onUnauthorized = handleUnauthorized;
  document.getElementById("login-form").addEventListener("submit", submitLogin);
  document.getElementById("first-login-form").addEventListener("submit", submitFirstLogin);
  document.getElementById("login-password-toggle").addEventListener("click", (event) => {
    const button = event.currentTarget;
    const password = document.getElementById("login-password");
    const visible = password.type === "text";
    password.type = visible ? "password" : "text";
    button.setAttribute("aria-pressed", String(!visible));
    button.setAttribute("aria-label", visible ? "Passwort anzeigen" : "Passwort verbergen");
    password.focus();
  });
}
