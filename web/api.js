const api = {
  // Wird von app.js gesetzt: reagiert auf eine abgelaufene oder entzogene
  // Sitzung, indem die Anmeldemaske wieder eingeblendet wird.
  onUnauthorized: null,

  async _req(method, url, body) {
    const opts = { method, headers: {}, credentials: "same-origin" };
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
      const msg = (data && (data.detail || data.error)) || `HTTP ${resp.status}`;
      const error = new Error(msg);
      error.status = resp.status;
      throw error;
    }
    return data;
  },
  get(url) { return this._req("GET", url); },
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
  movies(params) { return this.get("/api/movies?" + new URLSearchParams(params)); },
  movie(slug) { return this.get(`/api/movie/${encodeURIComponent(slug)}`); },
  moviesPreload(slugs) { return this.post("/api/movies/preload", { slugs }); },
  tmdbMovies(items) { return this.post("/api/tmdb/movies", { items }); },
  tmdbMovie(item) { return this.post("/api/tmdb/movie", item); },
  tmdbSeries(items) { return this.post("/api/tmdb/series", { items }); },
  jellyfinMatches(items) { return this.post("/api/jellyfin/matches", { items }); },

  series(params) { return this.get("/api/series?" + new URLSearchParams(params)); },
  seriesLoad(sampleSlug, baseSlug = "", refreshJellyfin = false, deferChecks = false) {
    return this.post("/api/series/load", {
      sample_slug: sampleSlug, base_slug: baseSlug,
      refresh_jellyfin: refreshJellyfin, defer_checks: deferChecks,
    });
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

  queueGet() { return this.get("/api/queue"); },
  queueAdd(slugs, preferences = {}) {
    return this.post("/api/queue/add", { slugs, preferences });
  },
  queueRemove(slug) { return this.post("/api/queue/remove", { slug }); },
  queueClear() { return this.post("/api/queue/clear"); },

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
  configSet(savePath, seriesPath) { return this.post("/api/config", { save_path: savePath, series_path: seriesPath }); },
  providerPriorityGet() { return this.get("/api/providers/config"); },
  providerPrioritySet(cfg) { return this.post("/api/providers/config", cfg); },

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
  updaterInstall(targetSha) { return this.post("/api/updater/install", { target_sha: targetSha }); },
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

  movieSubscriptionsGet() { return this.get("/api/movie-subscriptions"); },
  movieSubscriptionSave(entry) { return this.post("/api/movie-subscriptions", entry); },
  movieSubscriptionsCheck(keys = null) {
    return this.post("/api/movie-subscriptions/check", { keys });
  },
  movieSubscriptionsRemove(keys) {
    return this.post("/api/movie-subscriptions/remove", { keys });
  },

  coverUrl(url) {
    if (!url) return "";
    try {
      const parsed = new URL(url, location.origin);
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
      const parsed = new URL(url, location.origin);
      if (parsed.origin === location.origin) return parsed.href;
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return "/api/cover?" + new URLSearchParams({ url: parsed.href });
    } catch (e) { return ""; }
  },

  coverCandidates(url) {
    return [...new Set([this.coverUrl(url), this.coverProxyUrl(url)].filter(Boolean))];
  },
};
