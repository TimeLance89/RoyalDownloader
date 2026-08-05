// ── Ersteinrichtung ─────────────────────────────────────────────────────────
let setupStep = 1;
let setupRequired = false;
let initialDataStarted = false;

const setupStepCopy = {
  1: {
    title: "Welche Sprache passt zu dir?",
    intro: "Die Oberfläche wechselt sofort. Inhalte und Anbieternamen bleiben unverändert.",
  },
  2: {
    title: "Welche Inhalte möchtest du?",
    intro: "Wähle Inhaltssprachen und passende Quellen. Die Reihenfolge bestimmt Suche und Fallbacks.",
  },
  3: {
    title: "Wohin sollen deine Medien?",
    intro: "Die Ordner werden bei Bedarf angelegt. Beide müssen für den Downloader beschreibbar sein.",
  },
  4: {
    title: "Bibliothek und Filmdaten",
    intro: "Beide Verbindungen sind optional und können später in den Einstellungen ergänzt werden.",
  },
  5: {
    title: "Downloads automatisieren",
    intro: "Lege fest, was selbstständig laufen darf. Alle Werte bleiben später änderbar.",
  },
  6: {
    title: "Zugang sichern",
    intro: "Ein Konto schützt die Oberfläche. Ohne Anmeldung könnte jedes Gerät im Netzwerk Downloads auslösen.",
  },
};

const SETUP_STEP_COUNT = 6;

function setSetupStatus(message = "", error = false) {
  const el = document.getElementById("setup-status");
  el.textContent = message;
  el.classList.toggle("error", error);
}

function showSetupStep(nextStep) {
  setupStep = Math.max(1, Math.min(SETUP_STEP_COUNT, nextStep));
  document.querySelectorAll("[data-setup-step]").forEach((panel) => {
    panel.classList.toggle("hidden", Number(panel.dataset.setupStep) !== setupStep);
  });
  document.querySelectorAll("[data-setup-marker]").forEach((marker) => {
    const markerStep = Number(marker.dataset.setupMarker);
    marker.classList.toggle("active", markerStep === setupStep);
    marker.classList.toggle("complete", markerStep < setupStep);
    if (markerStep === setupStep) marker.setAttribute("aria-current", "step");
    else marker.removeAttribute("aria-current");
  });
  document.getElementById("setup-step-label").textContent = `SCHRITT ${setupStep} VON ${SETUP_STEP_COUNT}`;
  document.getElementById("setup-title").textContent = setupStepCopy[setupStep].title;
  document.getElementById("setup-intro").textContent = setupStepCopy[setupStep].intro;
  document.getElementById("setup-back").classList.toggle("hidden", setupStep === 1);
  document.getElementById("setup-next").classList.toggle("hidden", setupStep === SETUP_STEP_COUNT);
  document.getElementById("setup-finish").classList.toggle("hidden", setupStep !== SETUP_STEP_COUNT);
  setSetupStatus();
  const focusTarget = document.querySelector(
    `[data-setup-step="${setupStep}"] select, `
    + `[data-setup-step="${setupStep}"] input:not([type="checkbox"])`,
  );
  if (focusTarget) window.setTimeout(() => focusTarget.focus(), 40);
}

function validateSetupStep(step) {
  if (step === 2) {
    if (!state.providers.contentLanguages.size) {
      setSetupStatus("Mindestens eine Inhaltssprache muss aktiv sein.", true);
      return false;
    }
    if (!state.providers.enabledMovies.size || !state.providers.enabledSeries.size) {
      setSetupStatus("Für Filme und Serien muss jeweils mindestens eine Quelle aktiv sein.", true);
      return false;
    }
  }
  if (step === 3) {
    const movie = document.getElementById("setup-save-path");
    const series = document.getElementById("setup-series-path");
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
  if (step === 5 && document.getElementById("setup-telegram-enabled").checked) {
    const token = document.getElementById("setup-telegram-token");
    token.removeAttribute("aria-invalid");
    if (!token.value.trim() && token.dataset.hasSecret !== "true") {
      token.setAttribute("aria-invalid", "true");
      setSetupStatus("Für den aktivierten Telegram-Bot fehlt der Bot-Token.", true);
      token.focus();
      return false;
    }
  }
  if (step === 6) {
    const username = document.getElementById("setup-auth-username");
    const password = document.getElementById("setup-auth-password");
    const repeat = document.getElementById("setup-auth-password-repeat");
    [username, password, repeat].forEach((field) => field.removeAttribute("aria-invalid"));
    if (username.value.trim().length < 3) {
      username.setAttribute("aria-invalid", "true");
      setSetupStatus("Der Benutzername braucht mindestens 3 Zeichen.", true);
      username.focus();
      return false;
    }
    if (password.value.length < 8) {
      password.setAttribute("aria-invalid", "true");
      setSetupStatus("Das Passwort braucht mindestens 8 Zeichen.", true);
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
  const value = document.getElementById(id).value.trim();
  if (value === "") return null;
  return Math.max(0, Math.min(23, parseInt(value, 10) || 0));
}

async function finishSetup() {
  if (!validateSetupStep(5) || !validateSetupStep(6)) return;
  const finish = document.getElementById("setup-finish");
  const back = document.getElementById("setup-back");
  finish.disabled = true;
  back.disabled = true;
  setSetupStatus("Ordner und Einstellungen werden angelegt …");
  try {
    await api.setupComplete({
      save_path: document.getElementById("setup-save-path").value.trim(),
      series_path: document.getElementById("setup-series-path").value.trim(),
      ui_language: document.getElementById("setup-ui-language").value,
      movie_provider_order: state.providers.movies,
      series_provider_order: state.providers.series,
      anime_provider_order: state.providers.anime,
      movie_providers: [...state.providers.enabledMovies],
      series_providers: [...state.providers.enabledSeries],
      anime_providers: [...state.providers.enabledAnime],
      content_languages: [...state.providers.contentLanguages],
      jellyfin_url: document.getElementById("setup-jellyfin-url").value.trim(),
      jellyfin_api_key: document.getElementById("setup-jellyfin-key").value.trim(),
      jellyfin_user_id: document.getElementById("setup-jellyfin-user").value,
      jellyfin_user_name: document.getElementById("setup-jellyfin-user").value
        ? (document.getElementById("setup-jellyfin-user").selectedOptions[0]?.dataset.name
          || document.getElementById("setup-jellyfin-user").selectedOptions[0]?.textContent || "")
        : "",
      tmdb_api_key: document.getElementById("setup-tmdb-key").value.trim(),
      auto_download: document.getElementById("setup-auto-download").checked,
      check_interval_min: Math.max(5, parseInt(document.getElementById("setup-check-interval").value, 10) || 30),
      dl_window_start: parseSetupHour("setup-window-start"),
      dl_window_end: parseSetupHour("setup-window-end"),
      telegram_enabled: document.getElementById("setup-telegram-enabled").checked,
      telegram_bot_token: document.getElementById("setup-telegram-token").value.trim(),
      telegram_chat_id: document.getElementById("setup-telegram-chat").value.trim(),
      auth_username: document.getElementById("setup-auth-username").value.trim(),
      auth_password: document.getElementById("setup-auth-password").value,
    });
    document.getElementById("setup-auth-password").value = "";
    document.getElementById("setup-auth-password-repeat").value = "";
    setupRequired = false;
    document.body.classList.remove("setup-open");
    document.getElementById("setup-wizard").classList.add("hidden");
    await initSettings();
    startInitialData();
  } catch (e) {
    setSetupStatus(`Einrichtung fehlgeschlagen: ${e.message}`, true);
  } finally {
    finish.disabled = false;
    back.disabled = false;
  }
}

async function initSetupWizard() {
  try {
    const data = await api.setupStatus();
    if (!data.required) return false;
    setupRequired = true;
    const defaults = data.defaults || {};
    const jf = defaults.jellyfin || {};
    const tmdb = defaults.tmdb || {};
    const telegram = defaults.telegram || {};
    const automation = defaults.automation || {};
    const providers = defaults.providers || {};
    if (providers.movies?.length && providers.series?.length) {
      applyProviderPriority(providers);
    }
    const setupLanguage = defaults.ui_language_configured
      ? defaults.ui_language
      : i18n.browserDefaultLanguage();
    document.getElementById("setup-ui-language").value = setupLanguage;
    document.getElementById("ui-language").value = setupLanguage;
    if (setupLanguage !== i18n.language) {
      await i18n.changeLanguage(setupLanguage);
    }
    document.getElementById("setup-save-path").value = defaults.save_path || "";
    document.getElementById("setup-series-path").value = defaults.series_path || defaults.save_path || "";
    document.getElementById("setup-jellyfin-url").value = jf.url || "";
    const setupJfKey = document.getElementById("setup-jellyfin-key");
    setupJfKey.value = "";
    setupJfKey.dataset.hasSecret = jf.has_api_key ? "true" : "false";
    if (jf.has_api_key) setupJfKey.placeholder = "Bereits hinterlegt";
    fillJellyfinUserSelect("setup-jellyfin-user", [], jf.user_id || "", jf.user_name || "");
    const setupTmdbKey = document.getElementById("setup-tmdb-key");
    setupTmdbKey.value = "";
    setupTmdbKey.dataset.hasSecret = tmdb.has_api_key ? "true" : "false";
    if (tmdb.has_api_key) setupTmdbKey.placeholder = "Bereits hinterlegt";
    document.getElementById("setup-auto-download").checked = !!automation.auto_download;
    document.getElementById("setup-check-interval").value = automation.check_interval_min || 30;
    document.getElementById("setup-window-start").value = automation.dl_window_start ?? "";
    document.getElementById("setup-window-end").value = automation.dl_window_end ?? "";
    document.getElementById("setup-telegram-enabled").checked = !!telegram.enabled;
    const setupTelegramToken = document.getElementById("setup-telegram-token");
    setupTelegramToken.value = "";
    setupTelegramToken.dataset.hasSecret = telegram.has_bot_token ? "true" : "false";
    if (telegram.has_bot_token) setupTelegramToken.placeholder = "Bereits hinterlegt";
    document.getElementById("setup-telegram-chat").value = telegram.chat_id || "";
    document.getElementById("setup-config-path").textContent = data.config_path || "DATA/FilmeDownloader/settings.ini";
    document.body.classList.add("setup-open");
    document.getElementById("setup-wizard").classList.remove("hidden");
    showSetupStep(1);
    return true;
  } catch (e) {
    console.error("Ersteinrichtung konnte nicht geprüft werden:", e);
    return false;
  }
}

function retryFpInfiniteLoad() {
  if (state.fp.loadingMore || !state.fp.category) return;
  if (state.fp.lastPageFull) {
    loadNextFpPage();
  } else if (state.fp.category === "genre") {
    fpGenreChange(state.fp.activeGenre);
  } else {
    fpShowList(state.fp.category);
  }
}

function retrySeriesInfiniteLoad() {
  const mode = state.series.browseMode;
  if (state.series.loadingBrowse || !mode || mode === "search") return;
  if (state.series.lastPageFull) loadNextSeriesPage();
  else seriesBrowse(mode, 1);
}

// Vorlauf in Pixeln: sobald weniger als so viel bis zum unteren Rand des
// intern scrollenden Tabs oder bis zum Sentinel im Dokument fehlt, wird die
// naechste Seite geladen. Grosszuegig genug gewaehlt, dass die Folge-Eintraege
// laengst da sind, bevor man das Ende sieht.
const CATALOG_PRELOAD_PX = 1400;

function initCatalogInfiniteScroll() {
  document.getElementById("fp-infinite-retry").addEventListener("click", retryFpInfiniteLoad);
  document.getElementById("series-infinite-retry").addEventListener("click", retrySeriesInfiniteLoad);

  // Desktop scrollt innerhalb des aktiven Tabs, mobil dagegen das Dokument.
  // Darum werden beide Quellen beobachtet und je nach Layout entweder die
  // verbleibende Containerstrecke oder die Sentinel-Position ausgewertet.
  const bind = (containerId, sentinelId, loadNext) => {
    const container = document.getElementById(containerId);
    const sentinel = document.getElementById(sentinelId);
    if (!container || !sentinel) return () => {};
    let scheduled = false;
    const run = () => {
      scheduled = false;
      if (!container.classList.contains("active") || sentinel.classList.contains("hidden")) return;

      const overflowY = window.getComputedStyle(container).overflowY;
      const scrollsInternally = /(auto|scroll|overlay)/.test(overflowY)
        && container.scrollHeight > container.clientHeight + 1;
      if (scrollsInternally) {
        const remaining = container.scrollHeight - container.scrollTop - container.clientHeight;
        if (remaining <= CATALOG_PRELOAD_PX) loadNext();
        return;
      }

      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      if (sentinel.getBoundingClientRect().top <= viewportHeight + CATALOG_PRELOAD_PX) loadNext();
    };
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(run);
    };
    container.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    return schedule;
  };

  recheckFpInfinite = bind("tab-filme", "fp-infinite", loadNextFpPage);
  recheckSeriesInfinite = bind("tab-serien", "series-infinite", loadNextSeriesPage);
}

function startInitialData() {
  if (initialDataStarted) return;
  initialDataStarted = true;
  restoreHomeCache();
  syncTasteProfile();
  refreshGenres().catch((e) => {
    document.getElementById("genre-count").textContent = "Genres nicht verfügbar";
    console.error("Genres konnten nicht geladen werden:", e);
  });
  syncQueueSnapshot("Initiale Queue-Synchronisierung");
  refreshWatchlist();
  syncMovieSubscriptions();
  loadHomeData().catch((e) => {
    document.getElementById("fp-status").textContent = `Fehler: ${e.message}`;
    state.home.loading = false;
    renderHome();
  });
}

async function refreshGenres() {
  const data = await api.genres();
  const genres = Array.isArray(data.genres) ? data.genres : [];
  const filter = document.getElementById("genre-filter");
  filter.querySelectorAll('.genre-chip:not([data-genre="Alle Genres"])').forEach((button) => {
    button.remove();
  });
  for (const genre of genres) {
    const [mark, mood, tone] = movieGenrePresentation(genre);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "genre-chip";
    button.dataset.genre = genre;
    button.dataset.tone = tone;
    button.setAttribute("aria-pressed", "false");
    const symbol = document.createElement("span");
    symbol.className = "genre-chip-mark";
    symbol.setAttribute("aria-hidden", "true");
    symbol.textContent = mark;
    const copy = document.createElement("span");
    copy.className = "genre-chip-copy";
    const title = document.createElement("strong");
    title.textContent = genre;
    const subtitle = document.createElement("small");
    subtitle.textContent = mood;
    copy.append(title, subtitle);
    button.append(symbol, copy);
    filter.appendChild(button);
  }
  if (state.fp.activeGenre !== "Alle Genres" && !genres.includes(state.fp.activeGenre)) {
    state.fp.activeGenre = "Alle Genres";
  }
  document.getElementById("genre-count").textContent = `${genres.length} Filmwelten`;
  const genresAvailable = genres.length > 0;
  document.getElementById("genre-random").disabled = !genresAvailable;
  const genreToggle = document.getElementById("genre-toggle");
  genreToggle.disabled = !genresAvailable;
  genreToggle.dataset.collapsedLabel = `${genres.length} Genres`;
  setGenreBrowserExpanded(false);
  setActiveGenreFilter(state.fp.activeGenre);
}
