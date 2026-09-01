const api = {
  // Wird von app.js gesetzt: reagiert auf eine abgelaufene oder entzogene
  // Sitzung, indem die Anmeldemaske wieder eingeblendet wird.
  onUnauthorized: null,
  _inflightGets: new Map(),

  async _req(method, url, body, signal = undefined) {
    const opts = { method, headers: {}, credentials: "same-origin" };
    if (signal) opts.signal = signal;
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url, opts);
    let data = null;
    try { data = await resp.json(); } catch (e) { /* no body */ }
    if (!resp.ok) {
      // Die Anmeldeprüfung selbst darf den Wiederanmelde-Dialog nicht
      // auslösen – sonst würde ein falsches Passwort die Maske neu aufbauen.
      if (resp.status === 401 && !url.startsWith("/api/auth/") && this.onUnauthorized) {
        this.onUnauthorized();
      }
      const detail = data && (data.detail || data.error);
      const msg = typeof detail === "string"
        ? detail
        : (detail?.message || detail?.code || `HTTP ${resp.status}`);
      const error = new Error(msg);
      error.status = resp.status;
      error.code = typeof detail === "object" ? detail?.code : "";
      error.resource = typeof detail === "object" ? detail?.resource : "";
      throw error;
    }
    return data;
  },
  get(url) {
    const running = this._inflightGets.get(url);
    if (running) return running;
    const request = this._req("GET", url).finally(() => {
      if (this._inflightGets.get(url) === request) this._inflightGets.delete(url);
    });
    this._inflightGets.set(url, request);
    return request;
  },
  _within(promise, timeoutMs, message) {
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
  },
  _postWithin(url, body, timeoutMs, message) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    return this._req("POST", url, body, controller.signal)
      .catch((error) => {
        if (error?.name === "AbortError") {
          const timeoutError = new Error(message);
          timeoutError.code = "request_timeout";
          throw timeoutError;
        }
        throw error;
      })
      .finally(() => clearTimeout(timer));
  },
  post(url, body) { return this._req("POST", url, body === undefined ? {} : body); },

  authStatus() { return this.get("/api/auth/status"); },
  authLogin(username, password) { return this.post("/api/auth/login", { username, password }); },
  authLogout() { return this.post("/api/auth/logout"); },
  authConfigGet() { return this.get("/api/auth/config"); },
  authConfigSet(username, password, currentPassword = "") {
    return this.post("/api/auth/config", {
      username, password, current_password: currentPassword,
    });
  },
  authSessionsRevoke() { return this.post("/api/auth/sessions/revoke"); },

  genres() { return this.get("/api/genres"); },
  movies(params) {
    const request = this.get("/api/movies?" + new URLSearchParams(params));
    // Die provider-first Filmsuche fragt bewusst alle aktiven Quellen ab. Sie
    // darf nicht nach 15 Sekunden im Browser verworfen werden, während der
    // Server noch korrekt weiterarbeitet. Browse-Kataloge behalten ihr Budget.
    if (params?.mode === "search") return request;
    return this._within(
      request,
      15_000,
      "Der Filmkatalog antwortet zu langsam. Die Anbieter laden im Hintergrund weiter.",
    );
  },
  movie(slug, tmdbId = null) {
    const query = Number(tmdbId) > 0
      ? `?${new URLSearchParams({ tmdb_id: String(tmdbId) })}`
      : "";
    return this.get(`/api/movie/${encodeURIComponent(slug)}${query}`);
  },
  moviesPreload(slugs) { return this.post("/api/movies/preload", { slugs }); },
  tmdbMovies(items, background = false) {
    return this.post("/api/tmdb/movies", { items, background });
  },
  tmdbMovie(item) { return this.post("/api/tmdb/movie", item); },
  tmdbSeries(items) { return this.post("/api/tmdb/series", { items }); },
  jellyfinMatches(items) {
    return this._postWithin(
      "/api/jellyfin/matches", { items }, 15_000,
      "Die Jellyfin-Statusprüfung hat nicht rechtzeitig geantwortet.",
    );
  },

  series(params) { return this.get("/api/series?" + new URLSearchParams(params)); },
  seriesCalendar(refresh = false) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    const query = refresh ? "?refresh=true" : "";
    return this._req("GET", `/api/series-calendar${query}`, undefined, controller.signal)
      .catch((error) => {
        if (error?.name === "AbortError") {
          throw new Error("Der Kalenderdienst hat nach 15 Sekunden nicht geantwortet.");
        }
        throw error;
      })
      .finally(() => clearTimeout(timer));
  },
  seriesLoad(sampleSlug, baseSlug = "", refreshJellyfin = false, deferChecks = false) {
    return this.post("/api/series/load", {
      sample_slug: sampleSlug, base_slug: baseSlug,
      refresh_jellyfin: refreshJellyfin, defer_checks: deferChecks,
    });
  },
  seriesJellyfinStatus(series, force = false) {
    return this._postWithin("/api/series/jellyfin-status", {
      title: series.title,
      tmdb_id: series.tmdb_id || null,
      aliases: series.aliases || [],
      episodes: (series.seasons || []).flatMap((season) =>
        (season.episodes || []).map((episode) => ({
          slug: episode.slug, season: episode.season, episode: episode.episode,
        }))),
      force,
    }, 15_000, "Die Jellyfin-Serienprüfung hat nicht rechtzeitig geantwortet.");
  },

  anime(params) { return this.get("/api/anime?" + new URLSearchParams(params)); },
  animeDetail(id, translation = "", episodePage = 1) {
    return this.get(
      `/api/anime/${encodeURIComponent(id)}?`
      + new URLSearchParams({
        translation,
        episode_page: String(episodePage),
      }),
    );
  },
  aniworld(params) { return this.get("/api/aniworld?" + new URLSearchParams(params)); },
  aniworldPosters(ids) { return this.post("/api/aniworld/posters", { ids }); },
  aniworldDetail(id, translation = "", episodePage = 1, season = null) {
    const params = {
      translation,
      episode_page: String(episodePage),
    };
    if (season !== null && season !== undefined && season !== "") {
      params.season = String(season);
    }
    return this.get(
      `/api/aniworld/${encodeURIComponent(id)}?`
      + new URLSearchParams(params),
    );
  },

  queueGet() { return this.get("/api/queue"); },
  queueAddFailureReason(response, slugs = []) {
    if (Number(response?.added || 0) > 0) return "";
    const requested = Array.isArray(slugs) ? slugs : [slugs];
    const details = response?.skipped_details;
    const reasons = [...new Set(requested.map((slug) => {
      const reason = details && typeof details === "object" ? details[slug] : "";
      return typeof reason === "string" ? reason.trim() : "";
    }).filter(Boolean))];
    if (reasons.length) return reasons.join(" · ");
    return Number(response?.skipped || 0) > 0
      ? "Der Inhalt wurde vom Server nicht eingeplant."
      : "Der Server hat keinen Download eingeplant.";
  },
  queueAdd(slugs, preferences = {}, source = "web") {
    return this.post("/api/queue/add", { slugs, preferences, source });
  },
  queueRemove(slug) { return this.post("/api/queue/remove", { slug }); },
  queueClear() { return this.post("/api/queue/clear"); },
  queueJobs() { return this.get("/api/queue/jobs"); },
  queueHistory() { return this.get("/api/queue/history"); },
  queueJobCancel(jobId) { return this.post(`/api/queue/jobs/${encodeURIComponent(jobId)}/cancel`); },
  queueJobRetry(jobId) { return this.post(`/api/queue/jobs/${encodeURIComponent(jobId)}/retry`); },
  queueJobMove(jobId, direction) {
    return this.post(`/api/queue/jobs/${encodeURIComponent(jobId)}/move`, { direction });
  },
  queueJobResume(jobId) { return this.post(`/api/queue/jobs/${encodeURIComponent(jobId)}/resume`); },

  downloadCancel() { return this.post("/api/download/cancel"); },

  setupStatus() { return this.get("/api/setup/status"); },
  setupComplete(cfg) { return this.post("/api/setup/complete", cfg); },

  uiConfigGet() { return this.get("/api/ui/config"); },
  uiConfigSet(language) { return this.post("/api/ui/config", { language }); },
  uiTranslate(language, texts) {
    return this.post("/api/ui/translate", {
      target_language: language,
      texts,
    });
  },

  configGet() { return this.get("/api/config"); },
  configSet(savePath, seriesPath, deploymentMode) {
    return this.post("/api/config", {
      save_path: savePath,
      series_path: seriesPath,
      deployment_mode: deploymentMode,
    });
  },
  providerPriorityGet() { return this.get("/api/providers/config"); },
  providerPrioritySet(cfg) { return this.post("/api/providers/config", cfg); },
  providerStatusGet() { return this.get("/api/providers/status"); },
  serienstreamRetry() { return this.post("/api/providers/serienstream/retry"); },

  jellyfinConfigGet() { return this.get("/api/jellyfin/config"); },
  jellyfinConfigSet(url, apiKey, userId = "", userName = "", cleanupDefault = "keep") {
    return this.post("/api/jellyfin/config", {
      url,
      api_key: apiKey,
      user_id: userId,
      user_name: userName,
      cleanup_default: cleanupDefault,
    });
  },
  jellyfinUsers(url, apiKey) { return this.post("/api/jellyfin/users", { url, api_key: apiKey }); },
  tmdbConfigGet() { return this.get("/api/tmdb/config"); },
  tmdbConfigSet(apiKey) { return this.post("/api/tmdb/config", { api_key: apiKey }); },
  automationConfigGet() { return this.get("/api/automation/config"); },
  automationConfigSet(cfg) { return this.post("/api/automation/config", cfg); },
  telegramConfigGet() { return this.get("/api/telegram/config"); },
  telegramConfigSet(cfg) { return this.post("/api/telegram/config", cfg); },
  seerrConfigGet() { return this.get("/api/seerr/config"); },
  seerrConfigSet(cfg) { return this.post("/api/seerr/config", cfg); },
  seerrSync() { return this.post("/api/seerr/sync"); },
  updaterStatus(force = false) {
    return this.get("/api/updater/status?" + new URLSearchParams({ force: String(force) }));
  },
  updaterConfigGet() { return this.get("/api/updater/config"); },
  updaterConfigSet(cfg) { return this.post("/api/updater/config", cfg); },
  updaterInstall(targetSha, confirmChannelSwitch = false) {
    return this.post("/api/updater/install", {
      target_sha: targetSha,
      confirm_channel_switch: confirmChannelSwitch,
    });
  },
  updaterInstallStatus() { return this.get("/api/updater/install/status"); },
  browseDir(path) { return this.get("/api/browse-dir?" + new URLSearchParams({ path: path || "" })); },

  clearCookies() { return this.post("/api/session/clear-cookies"); },

  watchlistGet() { return this.get("/api/watchlist"); },
  watchlistAdd(entry) { return this.post("/api/watchlist/add", entry); },
  watchlistMode(baseSlug, downloadMode, cleanupMode) {
    return this.post("/api/watchlist/mode", {
      base_slug: baseSlug,
      download_mode: downloadMode,
      cleanup_mode: cleanupMode,
    });
  },
  watchlistRemove(baseSlugs) { return this.post("/api/watchlist/remove", { base_slugs: baseSlugs }); },
  watchlistCheck(baseSlugs) { return this.post("/api/watchlist/check", { base_slugs: baseSlugs || null }); },
  watchlistOpen(baseSlug) { return this.post("/api/watchlist/open", { base_slug: baseSlug }); },
  watchlistDownloadsRead(baseSlug) {
    return this.post("/api/watchlist/downloads/read", { base_slug: baseSlug });
  },

  movieSubscriptionsGet() { return this.get("/api/movie-subscriptions"); },
  movieSubscriptionSave(entry) { return this.post("/api/movie-subscriptions", entry); },
  movieSubscriptionsCheck(keys = null) {
    return this.post("/api/movie-subscriptions/check", { keys });
  },
  movieSubscriptionsRemove(keys) {
    return this.post("/api/movie-subscriptions/remove", { keys });
  },

  tasteProfile() { return this.get("/api/taste/profile"); },
  tasteEvent(event) { return this.post("/api/taste/events", event); },
  tasteFeedback(feedback) { return this.post("/api/taste/feedback", feedback); },
  tasteImport(profile) { return this.post("/api/taste/import", profile); },
  tasteReset() { return this.post("/api/taste/reset"); },

  homeLayout() { return this.get("/api/home/layout"); },
  saveHomeLayout(layout) { return this._req("PUT", "/api/home/layout", layout); },

  _upgradeTmdbImageUrl(url) {
    const parsed = new URL(url, location.origin);
    if (parsed.protocol !== "https:" || parsed.hostname !== "image.tmdb.org") return parsed;
    parsed.pathname = parsed.pathname
      .replace(/^\/t\/p\/w500\//, "/t/p/w780/")
      .replace(/^\/t\/p\/w1280\//, "/t/p/original/");
    return parsed;
  },

  coverUrl(url) {
    if (!url) return "";
    try {
      const parsed = this._upgradeTmdbImageUrl(url);
      if (parsed.origin === location.origin) return parsed.href;
      if (parsed.protocol === "https:" && parsed.hostname === "image.tmdb.org") return parsed.href;
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      url = parsed.href;
    } catch (e) { return ""; }
    return "/api/cover?" + new URLSearchParams({ url });
  },

  coverProxyUrl(url) {
    if (!url) return "";
    try {
      const parsed = this._upgradeTmdbImageUrl(url);
      if (parsed.origin === location.origin) return parsed.href;
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return "/api/cover?" + new URLSearchParams({ url: parsed.href });
    } catch (e) { return ""; }
  },

  coverCandidates(url) {
    return [...new Set([this.coverUrl(url), this.coverProxyUrl(url)].filter(Boolean))];
  },

  coverThumbnailCandidates(url) {
    if (!url) return [];
    try {
      const parsed = new URL(url, location.origin);
      if (parsed.protocol === "https:" && parsed.hostname === "image.tmdb.org") {
        parsed.pathname = parsed.pathname.replace(/^\/t\/p\/(?:w\d+|original)\//, "/t/p/w500/");
        const direct = parsed.href;
        return [...new Set([direct, "/api/cover?" + new URLSearchParams({ url: direct })])];
      }
    } catch (e) { return []; }
    return this.coverCandidates(url);
  },
};

// In-app updates replace the backend build while an already-open browser tab
// can keep the previous CSS/JavaScript alive indefinitely. Capabilities already
// exposes the current build SHA as a public, stable contract. Once it changes,
// this tab belongs to the previous frontend build and must reload.
let royalServerBuild = "";
let royalServerHeartbeatTimer = null;
let royalFrontendReloading = false;

async function checkRoyalServerBuild() {
  if (royalFrontendReloading) return;
  try {
    const response = await fetch("/api/v1/capabilities", {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const build = String(data?.build || "").trim();
    if (!build) return;
    if (royalServerBuild && royalServerBuild !== build) {
      royalFrontendReloading = true;
      location.reload();
      return;
    }
    royalServerBuild = build;
  } catch (error) {
    // A short connection failure is expected while an update restarts Royal.
    // The next heartbeat compares against the new backend build.
  }
}

function scheduleRoyalServerHeartbeat(delay = 5000) {
  if (royalServerHeartbeatTimer) clearTimeout(royalServerHeartbeatTimer);
  royalServerHeartbeatTimer = setTimeout(async () => {
    await checkRoyalServerBuild();
    if (!royalFrontendReloading) scheduleRoyalServerHeartbeat(document.hidden ? 15000 : 5000);
  }, delay);
}

void checkRoyalServerBuild().finally(() => scheduleRoyalServerHeartbeat());
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    void checkRoyalServerBuild();
    scheduleRoyalServerHeartbeat(5000);
  }
});

// Taste Profile v2 depends on the legacy screen functions being registered.
// Schedule its classic script for the next task after DOMContentLoaded so the
// existing Discovery v2 installer has completed before Taste v2 replaces the
// personal ranking seam. Home Experience v2 is chained after Taste v2, and the
// independent Daily Top 10 v2 layer is chained last so ranked cards keep all
// previous card decorators while replacing only the Top-10 ranking seam.
function loadRoyalDailyTopV2() {
  if (document.querySelector('script[data-daily-top-v2]')) return;
  const script = document.createElement("script");
  script.src = "/daily_top_v2.js?v=royal-20260824-1";
  script.async = false;
  script.dataset.dailyTopV2 = "true";
  document.body.appendChild(script);
}

function loadRoyalHomeExperienceV2() {
  const existing = document.querySelector('script[data-home-experience-v2]');
  if (existing) {
    if (window.__royalHomeExperienceV2Installed) {
      window.setTimeout(loadRoyalDailyTopV2, 0);
    } else {
      existing.addEventListener("load", () => window.setTimeout(loadRoyalDailyTopV2, 0), { once: true });
    }
    return;
  }
  const script = document.createElement("script");
  script.src = "/home_experience_v2.js?v=royal-20260830-1";
  script.async = false;
  script.dataset.homeExperienceV2 = "true";
  script.addEventListener("load", () => window.setTimeout(loadRoyalDailyTopV2, 0), { once: true });
  document.body.appendChild(script);
}

function loadRoyalTasteProfileV2() {
  const existing = document.querySelector('script[data-taste-profile-v2]');
  if (existing) {
    if (window.__royalTasteProfileV2Installed) {
      window.setTimeout(loadRoyalHomeExperienceV2, 0);
    } else {
      existing.addEventListener("load", () => window.setTimeout(loadRoyalHomeExperienceV2, 0), { once: true });
    }
    return;
  }
  const script = document.createElement("script");
  script.src = "/taste_v2.js?v=royal-20260824-1";
  script.async = false;
  script.dataset.tasteProfileV2 = "true";
  script.addEventListener("load", () => window.setTimeout(loadRoyalHomeExperienceV2, 0), { once: true });
  document.body.appendChild(script);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    window.setTimeout(loadRoyalTasteProfileV2, 0);
  }, { once: true });
} else {
  window.setTimeout(loadRoyalTasteProfileV2, 0);
}

function loadRoyalGlobalSearchRuntime() {
  if (document.querySelector('script[data-royal-global-search-runtime]')) return;
  const script = document.createElement("script");
  script.src = "/global-search-runtime.js?v=royal-20260817-1";
  script.async = false;
  script.setAttribute("data-royal-global-search-runtime", "true");
  document.body.appendChild(script);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    window.setTimeout(loadRoyalGlobalSearchRuntime, 0);
  }, { once: true });
} else {
  window.setTimeout(loadRoyalGlobalSearchRuntime, 0);
}

function loadRoyalStorageMoveJobs() {
  if (document.querySelector('script[data-royal-storage-move-jobs]')) return;
  const script = document.createElement("script");
  script.src = "/storage-move-jobs.js?v=royal-20260817-1";
  script.async = false;
  script.setAttribute("data-royal-storage-move-jobs", "true");
  document.body.appendChild(script);
}

function loadRoyalStorageManager() {
  const existing = document.querySelector('script[data-royal-storage-manager]');
  if (existing) {
    if (window.__royalStorageManagerInstalled) {
      window.setTimeout(loadRoyalStorageMoveJobs, 0);
    } else {
      existing.addEventListener("load", () => window.setTimeout(loadRoyalStorageMoveJobs, 0), { once: true });
    }
    return;
  }
  const script = document.createElement("script");
  script.src = "/storage-manager.js?v=royal-20260823-1";
  script.async = false;
  script.setAttribute("data-royal-storage-manager", "true");
  script.addEventListener("load", () => window.setTimeout(loadRoyalStorageMoveJobs, 0), { once: true });
  document.body.appendChild(script);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    window.setTimeout(loadRoyalStorageManager, 0);
  }, { once: true });
} else {
  window.setTimeout(loadRoyalStorageManager, 0);
}
