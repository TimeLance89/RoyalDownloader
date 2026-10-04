import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { selectedDeploymentMode, updateDeploymentModeHints } from "../settings/deployment.js";
import { setupStepCopy, setupEnglishStepCopy } from "./copy.js";

export function createSetup(root, { providers, jellyfin, directory, i18n, onComplete,
  onVisibility = () => {}, onError = console.error, client = api }) {
  const byId = id => root.querySelector(`#${id}`);
  let scope, saving = false, committed = false, loadFailed = false, existingSeriesCount = 0;
// ── Ersteinrichtung ─────────────────────────────────────────────────────────
let setupStep = 1;
let setupRequired = false;
let setupBootstrapRequired = false;
let setupBootstrapToken = "";
let setupBootstrapHint = "";

let localizedSetupStepCopy = setupEnglishStepCopy;
let localizedSetupStepLabels = Array.from(
  { length: 7 },
  (_, index) => `STEP ${index + 1} OF 7`,
);
let setupLanguageGeneration = 0;

const SETUP_STEP_COUNT = 7;

function setSetupStatus(message = "", error = false) {
  const el = byId("setup-status");
  el.textContent = message;
  el.classList.toggle("error", error);
}

function showSetupStep(nextStep) {
  setupStep = Math.max(1, Math.min(SETUP_STEP_COUNT, nextStep));
  root.querySelector(".setup-panels").scrollTop = 0;
  root.querySelectorAll("[data-setup-step]").forEach((panel) => {
    panel.classList.toggle("hidden", Number(panel.dataset.setupStep) !== setupStep);
  });
  root.querySelectorAll("[data-setup-marker]").forEach((marker) => {
    const markerStep = Number(marker.dataset.setupMarker);
    marker.classList.toggle("active", markerStep === setupStep);
    marker.classList.toggle("complete", markerStep < setupStep);
    if (markerStep === setupStep) marker.setAttribute("aria-current", "step");
    else marker.removeAttribute("aria-current");
  });
  byId("setup-step-label").textContent = localizedSetupStepLabels[setupStep - 1];
  byId("setup-title").textContent = localizedSetupStepCopy[setupStep].title;
  byId("setup-intro").textContent = localizedSetupStepCopy[setupStep].intro;
  byId("setup-back").classList.toggle("hidden", setupStep === 1);
  byId("setup-next").classList.toggle("hidden", setupStep === SETUP_STEP_COUNT);
  byId("setup-finish").classList.toggle("hidden", setupStep !== SETUP_STEP_COUNT);
  if (setupStep === 7) renderReview();
  byId("setup-next").textContent = text("Weiter", "Continue");
  byId("setup-finish").textContent = text("Royal vorbereiten", "Prepare Royal");
  setSetupStatus();
  const focusTarget = root.querySelector(
    `[data-setup-step="${setupStep}"] select, `
    + `[data-setup-step="${setupStep}"] input:not([type="checkbox"])`,
  ) || root.querySelector(`[data-setup-step="${setupStep}"] button`);
  if (focusTarget) scope.timeout(() => {
    const panel = focusTarget.closest("[data-setup-step]");
    if (Number(panel.dataset.setupStep) === setupStep && !panel.contains(root.ownerDocument.activeElement)) focusTarget.focus();
  }, 40);
}

async function localizeSetupStepCopy(language, userInitiated = false) {
  const current = scope;
  const generation = setupLanguageGeneration;
  if (language === "en") {
    localizedSetupStepCopy = setupEnglishStepCopy;
    localizedSetupStepLabels = Array.from(
      { length: SETUP_STEP_COUNT },
      (_, index) => `STEP ${index + 1} OF ${SETUP_STEP_COUNT}`,
    );
    return;
  }
  if (language === "de") {
    localizedSetupStepCopy = setupStepCopy;
    localizedSetupStepLabels = Array.from(
      { length: SETUP_STEP_COUNT },
      (_, index) => `SCHRITT ${index + 1} VON ${SETUP_STEP_COUNT}`,
    );
    return;
  }
  const sources = [];
  for (let step = 1; step <= SETUP_STEP_COUNT; step += 1) {
    sources.push(setupStepCopy[step].title, setupStepCopy[step].intro);
  }
  sources.push(...Array.from(
    { length: SETUP_STEP_COUNT },
    (_, index) => `SCHRITT ${index + 1} VON ${SETUP_STEP_COUNT}`,
  ));
  const translated = await i18n.translateTexts(sources, { userInitiated });
  if (!current.active || generation !== setupLanguageGeneration) return;
  localizedSetupStepCopy = {};
  for (let step = 1; step <= SETUP_STEP_COUNT; step += 1) {
    localizedSetupStepCopy[step] = {
      title: translated[(step - 1) * 2],
      intro: translated[((step - 1) * 2) + 1],
    };
  }
  localizedSetupStepLabels = translated.slice(SETUP_STEP_COUNT * 2);
}

async function changeSetupLanguage(language, userInitiated = false) {
  const wizard = root;
  const current = scope;
  const requestGeneration = ++setupLanguageGeneration;
  wizard.setAttribute("aria-busy", "true");
  try {
    await i18n.changeLanguage(language, {
      userInitiated,
      priorityRoot: [
        "#setup-wizard .setup-rail",
        "#setup-wizard .setup-stage-head",
        `#setup-wizard [data-setup-step="${setupStep}"]`,
        "#setup-wizard .setup-actions",
      ],
    });
    if (!current.active || requestGeneration !== setupLanguageGeneration) return;
    await localizeSetupStepCopy(i18n.language, userInitiated);
    if (!current.active || requestGeneration !== setupLanguageGeneration) return;
    showSetupStep(setupStep);
  } finally {
    if (current.active && requestGeneration === setupLanguageGeneration) wizard.removeAttribute("aria-busy");
  }
}

function validateSetupStep(step) {
  if (step === 2) {
    if (!providers.get().contentLanguages.size) {
      setSetupStatus("Mindestens eine Inhaltssprache muss aktiv sein.", true);
      return false;
    }
    if (!providers.get().enabledMovies.size || !providers.get().enabledSeries.size) {
      setSetupStatus("Für Filme und Serien muss jeweils mindestens eine Quelle aktiv sein.", true);
      return false;
    }
  }
  if (step === 3) {
    const movie = byId("setup-save-path");
    const series = byId("setup-series-path");
    movie.removeAttribute("aria-invalid");
    series.removeAttribute("aria-invalid");
    if (!movie.value.trim() || !series.value.trim()) {
      if (!movie.value.trim()) movie.setAttribute("aria-invalid", "true");
      if (!series.value.trim()) series.setAttribute("aria-invalid", "true");
      setSetupStatus("Film- und Serienordner müssen angegeben werden.", true);
      (!movie.value.trim() ? movie : series).focus();
      return false;
    }
  }
  if (step === 4) {
    const tmdb = byId("setup-tmdb-key");
    tmdb.removeAttribute("aria-invalid");
    if (!tmdb.value.trim() && tmdb.dataset.hasSecret !== "true") {
      tmdb.setAttribute("aria-invalid", "true");
      setSetupStatus("TMDB ist erforderlich. Trage einen API-Key oder Read Access Token ein.", true);
      tmdb.focus();
      return false;
    }
  }
  if (step === 5 && byId("setup-telegram-enabled").checked) {
    const token = byId("setup-telegram-token");
    token.removeAttribute("aria-invalid");
    if (!token.value.trim() && token.dataset.hasSecret !== "true") {
      token.setAttribute("aria-invalid", "true");
      setSetupStatus("Für den aktivierten Telegram-Bot fehlt der Bot-Token.", true);
      token.focus();
      return false;
    }
  }
  if (step === 6) {
    const username = byId("setup-auth-username");
    const password = byId("setup-auth-password");
    const repeat = byId("setup-auth-password-repeat");
    [username, password, repeat].forEach((field) => field.removeAttribute("aria-invalid"));
    if (username.value.trim().length < 3) {
      username.setAttribute("aria-invalid", "true");
      setSetupStatus("Der Benutzername braucht mindestens 3 Zeichen.", true);
      username.focus();
      return false;
    }
    if (password.value.length < 12) {
      password.setAttribute("aria-invalid", "true");
      setSetupStatus("Das Passwort braucht mindestens 12 Zeichen.", true);
      password.focus();
      return false;
    }
    if (password.value !== repeat.value) {
      repeat.setAttribute("aria-invalid", "true");
      setSetupStatus("Die beiden Passwörter stimmen nicht überein.", true);
      repeat.focus();
      return false;
    }
  }
  return true;
}

function parseSetupHour(id) {
  const value = byId(id).value.trim();
  if (value === "") return null;
  return Math.max(0, Math.min(23, parseInt(value, 10) || 0));
}

const text = (de, en) => i18n.language === "en" ? en : de;
function renderReview() {
  const config = providers.get();
  const selected = [...config.contentLanguages].map(code => config.languages[code] || code).join(" + ");
  const values = [
    [1, text("Betriebsart", "Operating mode"), selectedDeploymentMode(root, "setup-deployment-mode") === "nas" ? "NAS / Docker" : text("Computer", "Computer")],
    [2, text("Sprachprofil", "Language profile"), `${byId("setup-ui-language").selectedOptions[0]?.textContent} / ${selected}`],
    [3, text("Speicher", "Storage"), `${byId("setup-save-path").value} / ${byId("setup-series-path").value}`],
    [4, text("Bibliothek", "Library"), byId("setup-jellyfin-url").value.trim() ? "TMDB + Jellyfin" : "TMDB"],
    [5, text("Automatik", "Automation"), byId("setup-auto-download").checked ? text("Automatische Downloads", "Automatic downloads") : text("Downloads manuell starten", "Start downloads manually")],
    [6, text("Zugang", "Access"), byId("setup-auth-username").value],
  ];
  if (existingSeriesCount) values.push([2, text("Bestehende Abos", "Existing subscriptions"), byId("setup-update-subscriptions").checked ? selected : text("Bisherige Sprachen behalten", "Keep current languages")]);
  const list = byId("setup-review"); list.replaceChildren();
  for (const [step, label, value] of values) {
    const row = root.ownerDocument.createElement("div");
    const title = root.ownerDocument.createElement("strong"); title.textContent = label;
    const content = root.ownerDocument.createElement("span"); content.textContent = value; content.setAttribute("translate", "no");
    const edit = root.ownerDocument.createElement("button"); edit.type = "button"; edit.dataset.setupEdit = step;
    edit.textContent = text("Ändern", "Edit"); edit.setAttribute("aria-label", `${label}: ${edit.textContent}`);
    row.append(title, content, edit); list.append(row);
  }
}
function requestSetupBootstrapToken() {
  if (!setupBootstrapRequired) return true;
  byId("setup-bootstrap-token").removeAttribute("aria-invalid");
  setupBootstrapToken = byId("setup-bootstrap-token").value.trim();
  if (!setupBootstrapToken) {
    showSetupStep(6);
    setSetupStatus(text("Gib den einmaligen Sicherheitscode aus dem Royal-Log ein.", "Enter the one-time security code from the Royal log."), true);
    byId("setup-bootstrap-token").setAttribute("aria-invalid", "true");
    byId("setup-bootstrap-token").focus(); return false;
  }
  return true;
}
function prepare(stage) {
  root.dataset.state = "preparing";
  root.setAttribute("aria-busy", "true");
  byId("setup-preparing").hidden = false;
  byId("setup-preparing-title").textContent = text("Royal macht alles bereit.", "Royal is getting everything ready.");
  byId("setup-preparing-copy").textContent = [text("Dein Profil wird gespeichert …", "Saving your profile …"), text("Quellen, Katalog und Oberfläche werden vorbereitet …", "Preparing sources, catalog and interface …")][stage];
  byId("setup-preparing").querySelectorAll("li").forEach((node, i) => {
    node.textContent = [text("Profil speichern", "Save profile"), text("Quellen und Katalog vorbereiten", "Prepare sources and catalog"), text("Oberfläche bereitstellen", "Prepare interface")][i];
    node.classList.toggle("is-done", i < stage); node.classList.toggle("is-current", i === stage);
  });
}

async function finishSetup() {
  if (!scope?.active || saving) return;
  const current = scope;
  if (!committed) {
    for (const step of [2, 3, 4, 5, 6]) {
      if (!validateSetupStep(step)) { const message = byId("setup-status").textContent; showSetupStep(step); setSetupStatus(message, true); return; }
    }
    if (!requestSetupBootstrapToken()) return;
  }
  const finish = byId("setup-finish");
  const back = byId("setup-back");
  saving = true;
  finish.disabled = true;
  back.disabled = true;
  setSetupStatus(); prepare(committed ? 1 : 0);
  try {
    if (!committed) await client.post("/api/setup/complete", {
      deployment_mode: selectedDeploymentMode(root, "setup-deployment-mode"),
      save_path: byId("setup-save-path").value.trim(),
      series_path: byId("setup-series-path").value.trim(),
      ui_language: byId("setup-ui-language").value,
      movie_provider_order: providers.get().movies,
      series_provider_order: providers.get().series,
      anime_provider_order: providers.get().anime,
      movie_providers: [...providers.get().enabledMovies],
      series_providers: [...providers.get().enabledSeries],
      anime_providers: [...providers.get().enabledAnime],
      content_languages: [...providers.get().contentLanguages],
      jellyfin_url: byId("setup-jellyfin-url").value.trim(),
      jellyfin_api_key: byId("setup-jellyfin-key").value.trim(),
      jellyfin_user_id: byId("setup-jellyfin-user").value,
      jellyfin_user_name: byId("setup-jellyfin-user").value
        ? (byId("setup-jellyfin-user").selectedOptions[0]?.dataset.name
          || byId("setup-jellyfin-user").selectedOptions[0]?.textContent || "")
        : "",
      tmdb_api_key: byId("setup-tmdb-key").value.trim(),
      auto_download: byId("setup-auto-download").checked,
      check_interval_min: Math.max(5, parseInt(byId("setup-check-interval").value, 10) || 30),
      dl_window_start: parseSetupHour("setup-window-start"),
      dl_window_end: parseSetupHour("setup-window-end"),
      telegram_enabled: byId("setup-telegram-enabled").checked,
      telegram_bot_token: byId("setup-telegram-token").value.trim(),
      telegram_chat_id: byId("setup-telegram-chat").value.trim(),
      auth_username: byId("setup-auth-username").value.trim(),
      auth_password: byId("setup-auth-password").value,
      bootstrap_token: setupBootstrapToken,
      update_existing_subscriptions: byId("setup-update-subscriptions").checked,
    }, { signal: current.signal });
    if (!current.active) return;
    byId("setup-auth-password").value = "";
    byId("setup-auth-password-repeat").value = "";
    committed = true;
    setupBootstrapToken = "";
    byId("setup-bootstrap-token").value = "";
    setupBootstrapRequired = false;
    prepare(1);
    await onComplete();
    if (!current.active) return;
    setupRequired = false;
    onVisibility(false);
    providers.setup.unmount();
    jellyfin.unmount();
    root.classList.add("hidden");
    unmount();

  } catch (e) {
    if (!current.active) return;
    // A failed bootstrap attempt is never retained in browser storage or reused.
    if (setupBootstrapRequired) setupBootstrapToken = "";
    root.dataset.state = committed ? "prepare-error" : "editing";
    if (!committed) byId("setup-preparing").hidden = true;
    if (!committed && [403, 429].includes(e.status)) {
      byId("setup-bootstrap-token").value = "";
      showSetupStep(6); byId("setup-bootstrap-token").focus();
    }
    const detail = /cloudflare|origin web|HTTP 5\d\d/i.test(e.message) ? text("Royal ist gerade nicht erreichbar. Bitte erneut versuchen.", "Royal is currently unavailable. Please try again.") : e.message;
    setSetupStatus(`${committed ? text("Profil gespeichert. Vorbereitung noch nicht abgeschlossen: ", "Profile saved. Preparation is not finished: ") : text("Einrichtung fehlgeschlagen: ", "Setup failed: ")}${detail}`, true);
    finish.textContent = text("Erneut versuchen", "Try again");
  } finally {
    if (current.active) { saving = false; finish.disabled = false; back.disabled = committed; root.removeAttribute("aria-busy"); }
  }
}

async function initSetupWizard() {
  mount();
  const current = scope;
  try {
    const data = await client.get("/api/setup/status", { signal: current.signal });
    if (!current.active) return false;
    if (!data.required) { root.classList.add("hidden"); onVisibility(false); unmount(); return false; }
    committed = false; loadFailed = false; root.dataset.state = "editing"; byId("setup-preparing").hidden = true;
    providers.setup.mount();
    jellyfin.mount();
    setupRequired = true;
    setupBootstrapRequired = Boolean(data.bootstrap_required);
    setupBootstrapHint = String(data.bootstrap_hint || "");
    byId("setup-bootstrap-field").hidden = !setupBootstrapRequired;
    byId("setup-bootstrap-hint").textContent = setupBootstrapHint || text("Du findest den Code im Royal-Server- oder Container-Log.", "Find the code in the Royal server or container log.");
    setupBootstrapToken = "";
    const defaults = data.defaults || {};
    existingSeriesCount = Number(defaults.existing_series_count) || 0;
    byId("setup-subscription-choice").hidden = !existingSeriesCount;
    byId("setup-update-subscriptions").checked = false;
    const deploymentMode = ["desktop", "nas"].includes(defaults.deployment_mode)
      ? defaults.deployment_mode
      : "desktop";
    const setupMode = root.querySelector(
      `input[name="setup-deployment-mode"][value="${deploymentMode}"]`,
    );
    if (setupMode) setupMode.checked = true;
    updateDeploymentModeHints(root, "setup", deploymentMode);
    const jf = defaults.jellyfin || {};
    const tmdb = defaults.tmdb || {};
    const telegram = defaults.telegram || {};
    const automation = defaults.automation || {};
    const providerDefaults = defaults.providers || {};
    if (providerDefaults.movies?.length && providerDefaults.series?.length) {
      providers.apply(providerDefaults);
    }
    const setupLanguage = defaults.ui_language_configured
      ? defaults.ui_language
      : "en";
    byId("setup-ui-language").value = setupLanguage;
    if (setupLanguage !== i18n.language) {
      await changeSetupLanguage(setupLanguage);
    } else {
      await localizeSetupStepCopy(setupLanguage);
    }
    if (!current.active) return false;
    byId("setup-save-path").value = defaults.save_path || "";
    byId("setup-series-path").value = defaults.series_path || defaults.save_path || "";
    byId("setup-jellyfin-url").value = jf.url || "";
    const setupJfKey = byId("setup-jellyfin-key");
    setupJfKey.value = "";
    setupJfKey.dataset.hasSecret = jf.has_api_key ? "true" : "false";
    if (jf.has_api_key) setupJfKey.placeholder = "Bereits hinterlegt";
    jellyfin.fill([], jf.user_id || "", jf.user_name || "");
    const setupTmdbKey = byId("setup-tmdb-key");
    setupTmdbKey.value = "";
    setupTmdbKey.dataset.hasSecret = tmdb.has_api_key ? "true" : "false";
    if (tmdb.has_api_key) setupTmdbKey.placeholder = "Bereits hinterlegt";
    byId("setup-auto-download").checked = !!automation.auto_download;
    byId("setup-check-interval").value = automation.check_interval_min || 30;
    byId("setup-window-start").value = automation.dl_window_start ?? "";
    byId("setup-window-end").value = automation.dl_window_end ?? "";
    byId("setup-telegram-enabled").checked = !!telegram.enabled;
    const setupTelegramToken = byId("setup-telegram-token");
    setupTelegramToken.value = "";
    setupTelegramToken.dataset.hasSecret = telegram.has_bot_token ? "true" : "false";
    if (telegram.has_bot_token) setupTelegramToken.placeholder = "Bereits hinterlegt";
    byId("setup-telegram-chat").value = telegram.chat_id || "";
    byId("setup-config-path").textContent = data.config_path || "DATA/FilmeDownloader/settings.ini";
    onVisibility(true);
    root.classList.remove("hidden");
    showSetupStep(1);
    return true;
  } catch (e) {
    if (current.active) {
      loadFailed = true; root.dataset.state = "load-error"; root.classList.remove("hidden"); onVisibility(true);
      byId("setup-title").textContent = text("Einrichtung gerade nicht erreichbar", "Setup is currently unavailable");
      byId("setup-intro").textContent = text("Deine Einstellungen bleiben unverändert. Lade die Einrichtung erneut.", "Your settings are unchanged. Try loading setup again.");
      byId("setup-next").classList.remove("hidden"); byId("setup-next").textContent = text("Erneut versuchen", "Try again");
      byId("setup-back").classList.add("hidden"); byId("setup-finish").classList.add("hidden");
      onError(e);
    }
    return true;
  }
}


  function mount() {
    if (scope) return;
    const current = scope = createScope(); saving = false;
    byId("setup-finish").disabled = false; byId("setup-back").disabled = false;
    current.listen(byId("setup-ui-language"), "change", event => {
      void changeSetupLanguage(event.target.value, true).catch(error => {
        if (current.active) setSetupStatus(`Sprache konnte nicht geladen werden: ${error.message}`, true);
      });
    });
    for (const radio of root.querySelectorAll('input[name="setup-deployment-mode"]')) current.listen(radio, "change", () =>
      updateDeploymentModeHints(root, "setup", selectedDeploymentMode(root, "setup-deployment-mode")));
    current.listen(byId("setup-next"), "click", () => { if (loadFailed) { void initSetupWizard(); return; } if (!saving && validateSetupStep(setupStep)) showSetupStep(setupStep + 1); });
    current.listen(byId("setup-back"), "click", () => { if (!saving && !committed) showSetupStep(setupStep - 1); });
    current.listen(byId("setup-review"), "click", event => { const edit = event.target.closest("[data-setup-edit]"); if (edit && !saving) showSetupStep(Number(edit.dataset.setupEdit)); });
    current.listen(byId("setup-finish"), "click", finishSetup);
    current.listen(root, "keydown", event => {
      if (event.key === "Tab") {
        const controls = [...root.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary')].filter(node => node.getClientRects().length);
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && event.target === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && event.target === last) { event.preventDefault(); first?.focus(); }
        return;
      }
      if (saving || !setupRequired || event.key !== "Enter" || event.target.closest("button") || event.target.type === "checkbox") return;
      event.preventDefault();
      if (committed) { void finishSetup(); return; }
      if (setupStep < SETUP_STEP_COUNT) { if (validateSetupStep(setupStep)) showSetupStep(setupStep + 1); }
      else void finishSetup();
    });
    for (const [button, input] of [["setup-browse-movies", "setup-save-path"], ["setup-browse-series", "setup-series-path"]]) {
      current.listen(byId(button), "click", event => directory.open(byId(input), event.currentTarget));
    }
    if (setupRequired) { providers.setup.mount(); jellyfin.mount(); }
  }
  function unmount() {
    scope?.dispose(); scope = null; saving = false; setupLanguageGeneration++;
    providers.setup.unmount(); jellyfin.unmount(); directory.unmount();
    setupBootstrapToken = "";
    for (const id of ["setup-auth-password", "setup-auth-password-repeat", "setup-jellyfin-key", "setup-tmdb-key", "setup-telegram-token", "setup-bootstrap-token"]) byId(id).value = "";
  }
  return { initialize: initSetupWizard, refresh: initSetupWizard, mount, unmount, status: setSetupStatus,
    get required() { return setupRequired; } };
}
