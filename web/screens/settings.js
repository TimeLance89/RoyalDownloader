// ── Einstellungen (Speicherort) ──────────────────────────────────────────────
let dirModalPath = "";
let dirModalTarget = "save-path";   // welches Feld der Ordner-Dialog befüllt

function updateDeploymentModeHints(context, mode) {
  const nas = mode === "nas";
  const movie = document.getElementById(context === "setup" ? "setup-save-path" : "save-path");
  const series = document.getElementById(context === "setup" ? "setup-series-path" : "series-path");
  if (movie) {
    movie.placeholder = nas ? "/volume1/media/Filme" : "C:\\Users\\Name\\Downloads\\Royal\\Filme";
  }
  if (series) {
    series.placeholder = nas ? "/volume1/media/Serien" : "C:\\Users\\Name\\Downloads\\Royal\\Serien";
  }
  const status = document.getElementById("deployment-mode-status");
  if (context === "settings" && status) {
    status.textContent = nas
      ? "NAS-Modus · start.sh/Docker · im Netzwerk erreichbar"
      : "Computer-Modus · lokaler Browser · nur auf diesem Gerät";
  }
}

function selectedDeploymentMode(name = "deployment-mode") {
  return document.querySelector(`input[name="${name}"]:checked`)?.value || "desktop";
}

function fillJellyfinUserSelect(selectId, users, selectedId = "", selectedName = "") {
  const select = document.getElementById(selectId);
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = users.length ? "Benutzer auswählen …" : "Benutzer laden …";
  select.appendChild(placeholder);
  for (const user of users) {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.name;
    option.translate = false;
    option.dataset.name = user.name;
    select.appendChild(option);
  }
  if (selectedId && !users.some((user) => user.id === selectedId)) {
    const option = document.createElement("option");
    option.value = selectedId;
    option.textContent = selectedName || "Gespeicherter Benutzer";
    option.translate = false;
    option.dataset.name = selectedName || "";
    select.appendChild(option);
  }
  select.value = selectedId && [...select.options].some((option) => option.value === selectedId)
    ? selectedId
    : (users.length === 1 ? users[0].id : "");
}

async function loadJellyfinUsers({ urlId, keyId, selectId, buttonId, statusId = "" }) {
  const button = document.getElementById(buttonId);
  const select = document.getElementById(selectId);
  const status = statusId ? document.getElementById(statusId) : null;
  const url = document.getElementById(urlId).value.trim();
  const apiKey = document.getElementById(keyId).value.trim();
  button.disabled = true;
  if (status) status.textContent = "Lade Jellyfin-Benutzer …";
  try {
    const data = await api.jellyfinUsers(url, apiKey);
    const previous = select.value;
    fillJellyfinUserSelect(selectId, data.users || [], previous);
    if (status) status.textContent = data.users?.length
      ? `${data.users.length} ${data.users.length === 1 ? "Benutzer" : "Benutzer"} gefunden`
      : "Keine aktiven Jellyfin-Benutzer gefunden";
  } catch (error) {
    if (status) status.textContent = error.message;
    else setSetupStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function providerEnabledSet(mediaType) {
  if (mediaType === "movies") return state.providers.enabledMovies;
  if (mediaType === "anime") return state.providers.enabledAnime;
  return state.providers.enabledSeries;
}

function providerLanguage(provider) {
  return String(state.providers.catalog[provider]?.content_language || "").toLowerCase();
}

function providersForLanguage(language, mediaType) {
  return (state.providers[mediaType] || []).filter(
    (provider) => providerLanguage(provider) === language,
  );
}

function renderContentLanguageSelectors() {
  const ids = ["content-language-options", "setup-content-language-options"];
  const selected = state.providers.contentLanguages;
  for (const id of ids) {
    const container = document.getElementById(id);
    if (!container) continue;
    const context = id.startsWith("setup-") ? "setup" : "settings";
    container.innerHTML = Object.entries(state.providers.languages).map(([language, label]) => {
      const active = selected.has(language);
      const providerCount = new Set([
        ...providersForLanguage(language, "movies"),
        ...providersForLanguage(language, "series"),
        ...providersForLanguage(language, "anime"),
      ]).size;
      return `
        <button class="content-language-card ${active ? "is-selected" : ""}" type="button"
          data-language="${escapeHtml(language)}" aria-pressed="${active}">
          <span class="content-language-code" translate="no">${escapeHtml(language.toUpperCase())}</span>
          <span class="content-language-copy">
            <strong translate="no">${escapeHtml(label)}</strong>
            <small>${providerCount} ${providerCount === 1 ? "Quelle" : "Quellen"}</small>
          </span>
          <span class="content-language-signal" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        </button>
      `;
    }).join("");
    container.querySelectorAll(".content-language-card").forEach((button) => {
      button.addEventListener("click", () => {
        const language = button.dataset.language;
        if (selected.has(language) && selected.size <= 1) {
          setProviderSelectionStatus(context, "Mindestens eine Inhaltssprache muss aktiv bleiben.", true);
          return;
        }
        if (selected.has(language)) {
          const remaining = new Set(selected);
          remaining.delete(language);
          const leavesMovies = state.providers.movies.some(
            (provider) => remaining.has(providerLanguage(provider)),
          );
          const leavesSeries = state.providers.series.some(
            (provider) => remaining.has(providerLanguage(provider)),
          );
          if (!leavesMovies || !leavesSeries) {
            setProviderSelectionStatus(
              context,
              "Die Auswahl benötigt mindestens eine Sprache mit Film- und Serienquellen.",
              true,
            );
            return;
          }
          selected.delete(language);
          for (const mediaType of ["movies", "series", "anime"]) {
            const enabled = providerEnabledSet(mediaType);
            providersForLanguage(language, mediaType).forEach((provider) => enabled.delete(provider));
          }
        } else {
          selected.add(language);
          for (const mediaType of ["movies", "series", "anime"]) {
            const enabled = providerEnabledSet(mediaType);
            providersForLanguage(language, mediaType).forEach((provider) => enabled.add(provider));
          }
        }
        const labels = [...selected].map((key) => state.providers.languages[key] || key.toUpperCase());
        setProviderSelectionStatus(context, `Inhaltssprachen: ${labels.join(" + ")}.`);
        renderAllProviderBoards();
      });
    });
  }
  const labels = [...selected].map(
    (language) => state.providers.languages[language] || language.toUpperCase(),
  );
  const summary = labels.length > 1
    ? `${labels.join(" + ")} · gemischter Katalog`
    : `${labels[0] || "Keine"} · fokussierter Katalog`;
  ["content-language-summary", "setup-content-language-summary"].forEach((id) => {
    const element = document.getElementById(id);
    if (element) element.textContent = summary;
  });
}

function providerMonogram(label) {
  const words = String(label || "").match(/[\p{L}\p{N}]+/gu) || [];
  return (words.length > 1
    ? words.slice(0, 2).map((word) => word[0]).join("")
    : String(words[0] || "?").slice(0, 2)
  ).toUpperCase();
}

function providerLogoUrl(meta) {
  const homepage = String(meta?.homepage || "").trim();
  if (!homepage) return "";
  return `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(homepage)}&sz=128`;
}

function providerListIds(mediaType) {
  if (mediaType === "movies") {
    return ["movie-provider-priority", "setup-movie-provider-priority"];
  }
  if (mediaType === "anime") {
    return ["anime-provider-priority", "setup-anime-provider-priority"];
  }
  return ["series-provider-priority", "setup-series-provider-priority"];
}

function setProviderSelectionStatus(context, message, error = false) {
  if (context === "setup") {
    setSetupStatus(message, error);
    return;
  }
  const status = document.getElementById("provider-selection-status");
  if (!status) return;
  status.textContent = message || "";
  status.classList.toggle("error", error);
}

function renderProviderList(list, mediaType) {
  const providers = state.providers[mediaType] || [];
  const enabled = providerEnabledSet(mediaType);
  const isSetup = list.id.startsWith("setup-");
  const context = isSetup ? "setup" : "settings";
  const mediaLabel = {
    movies: "Filmquelle",
    series: "Serienquelle",
    anime: "Animequelle",
  }[mediaType];
  list.innerHTML = providers.map((provider, index) => {
    const meta = state.providers.catalog[provider] || {};
    const label = state.providers.labels[provider] || meta.label || provider;
    const languageActive = state.providers.contentLanguages.has(providerLanguage(provider));
    const active = languageActive && enabled.has(provider);
    const logoUrl = providerLogoUrl(meta);
    const languageCode = String(meta.content_language || "").toUpperCase();
    const languageLabel = meta.language_label || languageCode;
    return `
      <li class="provider-source-card ${active ? "is-enabled" : "is-disabled"} ${languageActive ? "" : "is-language-muted"} ${mediaType === "series" ? "is-series" : ""}"
          data-provider="${escapeHtml(provider)}">
        <label class="provider-source-toggle">
          <input type="checkbox" ${active ? "checked" : ""}
            ${languageActive ? "" : "disabled"}
            aria-label="${escapeHtml(`${label} als ${mediaLabel} verwenden`)}">
          <span class="provider-logo-frame" aria-hidden="true">
            <span class="provider-logo-monogram">${escapeHtml(providerMonogram(label))}</span>
            ${logoUrl ? `<img class="provider-logo-image" src="${escapeHtml(logoUrl)}" alt="">` : ""}
          </span>
          <span class="provider-source-copy">
            <strong class="provider-name" translate="no">${escapeHtml(label)}</strong>
            <span class="provider-source-meta" translate="no">
              <em>${escapeHtml(languageCode)}</em>
              <small>${escapeHtml(languageLabel)}</small>
            </span>
          </span>
          <span class="provider-source-state" aria-hidden="true">
            <i>✓</i><small>${active ? "aktiv" : (languageActive ? "aus" : "Sprache aus")}</small>
          </span>
        </label>
        <span class="provider-source-order">
          <b title="Priorität">${String(index + 1).padStart(2, "0")}</b>
          <button class="provider-order-button" type="button" data-direction="-1"
            aria-label="${escapeHtml(`${label} nach oben`)}"
            ${index === 0 ? "disabled" : ""}>↑</button>
          <button class="provider-order-button" type="button" data-direction="1"
            aria-label="${escapeHtml(`${label} nach unten`)}"
            ${index === providers.length - 1 ? "disabled" : ""}>↓</button>
        </span>
      </li>
    `;
  }).join("");

  list.querySelectorAll(".provider-logo-image").forEach((image) => {
    image.addEventListener("error", () => image.remove(), { once: true });
  });
  list.querySelectorAll('.provider-source-toggle input[type="checkbox"]').forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const provider = checkbox.closest(".provider-source-card").dataset.provider;
      if (mediaType !== "anime" && !checkbox.checked && enabled.size <= 1) {
        checkbox.checked = true;
        setProviderSelectionStatus(
          context,
          `Mindestens eine ${mediaType === "movies" ? "Filmquelle" : "Serienquelle"} muss aktiv bleiben.`,
          true,
        );
        return;
      }
      if (checkbox.checked) enabled.add(provider);
      else enabled.delete(provider);
      setProviderSelectionStatus(
        context,
        `${enabled.size} ${{
          movies: "Filmquellen",
          series: "Serienquellen",
          anime: "Animequellen",
        }[mediaType]} aktiv.`,
      );
      renderAllProviderBoards();
    });
  });
  list.querySelectorAll(".provider-order-button").forEach((button) => {
    button.addEventListener("click", () => {
      const item = button.closest(".provider-source-card");
      const from = state.providers[mediaType].indexOf(item.dataset.provider);
      const to = from + Number(button.dataset.direction);
      if (from < 0 || to < 0 || to >= state.providers[mediaType].length) return;
      [state.providers[mediaType][from], state.providers[mediaType][to]] =
        [state.providers[mediaType][to], state.providers[mediaType][from]];
      renderAllProviderBoards();
    });
  });
}

function renderAllProviderBoards() {
  renderContentLanguageSelectors();
  for (const mediaType of ["movies", "series", "anime"]) {
    for (const id of providerListIds(mediaType)) {
      const list = document.getElementById(id);
      if (list) renderProviderList(list, mediaType);
    }
    const enabledCount = providerEnabledSet(mediaType).size;
    const eligibleCount = (state.providers[mediaType] || []).filter(
      (provider) => state.providers.contentLanguages.has(providerLanguage(provider)),
    ).length;
    const summary = `${enabledCount} aktiv · ${eligibleCount} passend`;
    const ids = {
      movies: ["movie-provider-summary", "setup-movie-provider-summary"],
      series: ["series-provider-summary", "setup-series-provider-summary"],
      anime: ["anime-provider-summary", "setup-anime-provider-summary"],
    }[mediaType];
    ids.forEach((id) => {
      const element = document.getElementById(id);
      if (element) element.textContent = summary;
    });
  }
  syncAnimeNavigationVisibility();
  syncAniworldNavigationVisibility();
}

function applyProviderPriority(cfg) {
  state.providers.movies = [...(cfg.movies || [])];
  state.providers.series = [...(cfg.series || [])];
  state.providers.anime = [...(cfg.anime || [])];
  state.providers.labels = { ...(cfg.labels || {}) };
  state.providers.catalog = { ...(cfg.catalog || {}) };
  state.providers.languages = { ...(cfg.languages || {}) };
  state.providers.enabledMovies = new Set(
    cfg.enabled_movies?.length ? cfg.enabled_movies : state.providers.movies,
  );
  state.providers.enabledSeries = new Set(
    cfg.enabled_series?.length ? cfg.enabled_series : state.providers.series,
  );
  state.providers.enabledAnime = new Set(
    Array.isArray(cfg.enabled_anime) ? cfg.enabled_anime : state.providers.anime,
  );
  if (!Object.keys(state.providers.languages).length) {
    for (const meta of Object.values(state.providers.catalog)) {
      const language = String(meta.content_language || "").toLowerCase();
      if (language) state.providers.languages[language] = meta.language_label || language.toUpperCase();
    }
  }
  const inferredLanguages = [
    ...state.providers.enabledMovies,
    ...state.providers.enabledSeries,
    ...state.providers.enabledAnime,
  ].map(providerLanguage).filter(Boolean);
  state.providers.contentLanguages = new Set(
    cfg.content_languages?.length
      ? cfg.content_languages
      : (inferredLanguages.length ? inferredLanguages : Object.keys(state.providers.languages)),
  );
  for (const mediaType of ["movies", "series", "anime"]) {
    const enabled = providerEnabledSet(mediaType);
    [...enabled].forEach((provider) => {
      if (!state.providers.contentLanguages.has(providerLanguage(provider))) enabled.delete(provider);
    });
  }
  state.anime.loaded = false;
  state.anime.disabledReason = "";
  renderAllProviderBoards();
}

async function initSettings() {
  document.getElementById("ui-language").value = i18n.language;
  const cfg = await api.configGet();
  const mode = ["desktop", "nas"].includes(cfg.deployment_mode)
    ? cfg.deployment_mode
    : "desktop";
  const modeRadio = document.querySelector(`input[name="deployment-mode"][value="${mode}"]`);
  if (modeRadio) modeRadio.checked = true;
  updateDeploymentModeHints("settings", mode);
  document.getElementById("save-path").value = cfg.save_path;
  document.getElementById("series-path").value = cfg.series_path || "";
  const jf = await api.jellyfinConfigGet();
  document.getElementById("jellyfin-url").value = jf.url || "";
  const jfKey = document.getElementById("jellyfin-api-key");
  jfKey.value = "";
  jfKey.placeholder = jf.has_api_key ? "Gespeichert · leer lassen zum Beibehalten" : "API-Schlüssel";
  fillJellyfinUserSelect("jellyfin-user-id", [], jf.user_id || "", jf.user_name || "");
  state.watchlistCleanupDefault = WATCH_CLEANUP_LABELS[jf.cleanup_default]
    ? jf.cleanup_default
    : WATCH_CLEANUP_DEFAULT;
  document.querySelectorAll('input[name="jellyfin-cleanup-default"]').forEach((radio) => {
    radio.checked = radio.value === state.watchlistCleanupDefault;
  });
  state.jellyfinUserConfigured = !!(jf.url && jf.has_api_key && jf.user_id);
  document.getElementById("jellyfin-user-status").textContent = jf.user_id
    ? `Gesehen-Status: ${jf.user_name || "Benutzer gewählt"}`
    : "Für „Nächste Staffel“ und automatische Löschregeln erforderlich.";
  const tmdb = await api.tmdbConfigGet();
  applyTmdbCfg(tmdb);
  applyAiConfig(await api.aiConfigGet());
  const auto = await api.automationConfigGet();
  applyAutomationCfg(auto);
  applyUpdaterConfig(await api.updaterConfigGet());
  const seerr = await api.seerrConfigGet();
  applySeerrCfg(seerr);
  const telegram = await api.telegramConfigGet();
  applyTelegramCfg(telegram);
  applyProviderPriority(await api.providerPriorityGet());
  await refreshAccountCard();
  checkForUpdates(false);
}
