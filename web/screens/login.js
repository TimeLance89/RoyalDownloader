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
  setLoginStatus();
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
    setLoginStatus(error.message, true);
    document.getElementById("login-password").select();
  } finally {
    button.disabled = false;
  }
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
