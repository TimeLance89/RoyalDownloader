// CI quality gate: isolated Playwright tooling, no application build required.
// ROYAL_PLAYWRIGHT can point at its package directory. API/WS are deterministic fixtures.
const { chromium } = require(process.env.ROYAL_PLAYWRIGHT || "playwright");
const { createServer } = require("node:http");
const { readFile } = require("node:fs/promises");
const { resolve, extname, sep } = require("node:path");
const assert = require("node:assert/strict");
const web = resolve(__dirname, "../../web");
const server = createServer(async (req, res) => {
  const path = resolve(web, `.${new URL(req.url, "http://local").pathname.replace(/\/$/, "/index.html")}`);
  if (!path.startsWith(web + sep)) { res.writeHead(403).end(); return; }
  try {
    const data = await readFile(path);
    res.setHeader("Content-Type", { ".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".png": "image/png" }[extname(path)] || "application/octet-stream");
    res.end(data);
  } catch { res.writeHead(404).end(); }
});

(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ headless: true, channel: process.env.ROYAL_BROWSER === "chromium" ? undefined : process.env.ROYAL_BROWSER || "msedge" });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [], missing = [], writes = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => { if (response.status() === 404 && /\.(js|css)/.test(response.url())) missing.push(response.url()); });
    const providers = { movies: ["movie-de", "movie-en"], series: ["series-de", "series-en"], anime: [],
      enabled_movies: ["movie-de", "movie-en"], enabled_series: ["series-de", "series-en"], enabled_anime: [],
      content_languages: ["de", "en"], languages: { de: "Deutsch", en: "English" },
      catalog: Object.fromEntries(["movie-de", "movie-en", "series-de", "series-en"].map(key => [key, { label: key, content_language: key.endsWith("de") ? "de" : "en" }])) };
    let setupRequired = true, jellyfinSlow = false, loginRequired = false, tasteSlow = false;
    let releaseAuth, releaseSetup, authRequested, setupRequested;
    const authGate = new Promise(resolve => { releaseAuth = resolve; });
    const setupGate = new Promise(resolve => { releaseSetup = resolve; });
    const authStarted = new Promise(resolve => { authRequested = resolve; });
    const setupStarted = new Promise(resolve => { setupRequested = resolve; });
    await page.addInitScript(() => {
      window.sessionExpirations = 0;
      document.addEventListener("royal:session-expired", () => window.sessionExpirations++);
    });
    const jf = { url: "http://jellyfin.fixture", has_api_key: true, user_id: "fixture-user", user_name: "Fixture", cleanup_default: "keep" };
    await page.routeWebSocket("**/ws", () => {});
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url()), method = route.request().method();
      let data = {};
      if (method !== "GET") writes.push({ path: url.pathname, body: route.request().postDataJSON() });
      if (url.pathname === "/api/fixture-protected") {
        await route.fulfill({ status: 401, json: { detail: "Unauthorized" } }); return;
      }
      if (url.pathname === "/api/auth/status") {
        authRequested(); await authGate;
        data = { configured: loginRequired, authenticated: !loginRequired };
      }
      if (url.pathname === "/api/taste/onboarding") {
        if (tasteSlow) await new Promise(resolve => setTimeout(resolve, 450));
        data = { user: { id: "fixture", username: "fixture-owner", role: "admin", taste_onboarding_required: false }, profile: {} };
      }
      if (url.pathname === "/api/auth/login") { loginRequired = false; data = { configured: true, authenticated: true, user: { id: "fixture", username: "fixture-owner", role: "admin" } }; }
      if (url.pathname === "/api/ui/config") data = { language: "en", configured: true };
      if (url.pathname === "/api/ui/translate") data = { translations: route.request().postDataJSON().texts };
      if (url.pathname === "/api/setup/status") {
        setupRequested(); await setupGate;
        data = { required: setupRequired, bootstrap_required: true, bootstrap_hint: "Fixture bootstrap", defaults: { providers, save_path: "/fixture/movies", series_path: "/fixture/series", jellyfin: jf } };
      }
      if (url.pathname === "/api/setup/complete") { setupRequired = false; data = { ok: true }; }
      if (url.pathname === "/api/config") data = { save_path: "/fixture/movies", series_path: "/fixture/series", deployment_mode: "desktop" };
      if (url.pathname === "/api/providers/config") data = providers;
      if (url.pathname === "/api/jellyfin/config") data = jf;
      if (url.pathname === "/api/jellyfin/users") {
        if (jellyfinSlow) await new Promise(resolve => setTimeout(resolve, 450));
        data = { users: [{ id: "fixture-user", name: "Fixture" }, { id: "other", name: "Other" }] };
      }
      if (url.pathname === "/api/genres") data = { genres: [] };
      if (url.pathname === "/api/queue") data = { queue: { count: 0, groups: [], activity: {}, providers: {} } };
      if (url.pathname === "/api/watchlist") data = { watchlist: [], health: {} };
      if (url.pathname === "/api/movie-subscriptions") data = { subscriptions: [] };
      if (url.pathname === "/api/modules") data = { modules: [] };
      if (url.pathname === "/api/calendar") data = { ready: true, days: [] };
      if (url.pathname === "/api/v1/capabilities") data = { build: "fixture" };
      await route.fulfill({ json: data });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: "domcontentloaded" });
    const protectedRequest = () => page.evaluate(async () => {
      const { api } = await import("/js/core/api.js");
      try { await api.get("/api/fixture-protected"); }
      catch (error) { return error.status; }
    });
    // Startup 401s must not open login before either status request has resolved.
    await authStarted;
    assert.equal(await protectedRequest(), 401);
    assert.equal(await page.locator("#login-screen").isVisible(), false);
    assert.equal(await page.evaluate(() => window.sessionExpirations), 0);
    releaseAuth();
    await setupStarted;
    assert.equal(await protectedRequest(), 401);
    assert.equal(await page.locator("#login-screen").isVisible(), false);
    assert.equal(await page.evaluate(() => window.sessionExpirations), 0);
    releaseSetup();
    await page.locator("#setup-wizard").waitFor({ state: "visible" });
    assert.equal(await page.locator("#login-screen").isVisible(), false);
    assert.equal(await page.locator("#setup-title").textContent(), "How would you like to use Royal?");
    await page.locator(".runtime-mode-card").filter({ has: page.locator("#setup-mode-nas") }).click();
    await page.locator("#setup-next").click();
    const languages = page.locator("#setup-content-language-options");
    await languages.locator('[data-language="en"]').click();
    assert.equal(await languages.locator('[data-language="en"]').getAttribute("aria-pressed"), "false");
    await languages.locator('[data-language="de"]').click();
    assert.equal(await languages.locator('[data-language="de"]').getAttribute("aria-pressed"), "true");
    await page.locator("#setup-next").click();
    await page.locator("#setup-save-path").fill("");
    await page.locator("#setup-next").click();
    assert.equal(await page.locator("#setup-save-path").getAttribute("aria-invalid"), "true");
    await page.locator("#setup-save-path").fill("/fixture/movies");
    await page.locator("#setup-next").click();
    await page.locator("#setup-jellyfin-users-load").click();
    await page.waitForFunction(() => document.querySelectorAll("#setup-jellyfin-user option").length === 3);
    await page.locator("#setup-jellyfin-user").selectOption("other");
    await page.locator("#setup-next").click();
    assert.equal(await page.locator("#setup-tmdb-key").getAttribute("aria-invalid"), "true");
    await page.locator("#setup-tmdb-key").fill("fixture-only-key");
    await page.locator("#setup-next").click();
    await page.locator("#setup-next").click();
    await page.locator("#setup-auth-username").fill("fixture-owner");
    await page.locator("#setup-auth-password").fill("fixture-password-only");
    await page.locator("#setup-auth-password-repeat").fill("fixture-password-only");
    await page.locator("#setup-bootstrap-token").fill("fixture-bootstrap");
    await page.locator("#setup-next").click();
    await page.locator("#setup-finish").click();
    try { await page.locator("#setup-wizard").waitFor({ state: "hidden", timeout: 10000 }); }
    catch (error) { console.error({ status: await page.locator("#setup-status").textContent(), errors, writes: writes.map(item => item.path) }); throw error; }
    assert.deepEqual(await page.evaluate(() => ["state", "sharedPresentation", "switchTab", "royalLoader"].filter(name => name in window)), []);
    const submissions = writes.filter(write => write.path === "/api/setup/complete");
    assert.equal(submissions.length, 1);
    assert.equal(submissions[0].body.deployment_mode, "nas");
    assert.deepEqual(submissions[0].body.content_languages, ["de"]);
    assert.equal(submissions[0].body.jellyfin_user_id, "other");
    assert.equal(submissions[0].body.bootstrap_token, "fixture-bootstrap");
    assert.equal(await page.locator("#setup-auth-password").inputValue(), "");
    // Retain the composed app across evaluations instead of repeatedly awaiting
    // dynamic-import promises that Chromium can garbage-collect during the test.
    const applicationHandle = await page.evaluateHandle(async () =>
      (await import(document.querySelector('script[type="module"]').src)).application);
    // General settings saves must not contact an untouched optional Jellyfin server.
    await page.evaluate(async () => {
      const { createJellyfinSettings } = await import("/js/features/integrations/jellyfin.js");
      const root = document.querySelector("#jellyfin-url").closest(".settings-group").cloneNode(true);
      const writes = [];
      const view = createJellyfinSettings(root, { client: {
        get: async () => ({ url: "http://optional:8096", has_api_key: false }),
        post: async (_url, body) => {
          writes.push(body);
          return { ...body, has_api_key: false, saved: true };
        },
      } });
      try {
        view.mount(); await view.initialize();
        await view.save();
        if (writes.length) throw new Error("Untouched Jellyfin must not block other settings");
        root.querySelector("#jellyfin-url").value = "";
        root.dispatchEvent(new Event("input"));
        await view.save();
        if (writes.length !== 1 || writes[0].url || writes[0].api_key) throw new Error("Empty optional Jellyfin must be savable");
        if (view.get().userConfigured) throw new Error("Empty Jellyfin must remain inactive");
      } finally { view.dispose(); }
    });
    await page.evaluate(async () => {
      const { createDirectoryPicker } = await import("/js/features/settings/directory.js");
      const root = document.querySelector("#dir-modal").cloneNode(true);
      root.id = "fixture-directory";
      document.body.appendChild(root);
      const target = document.createElement("input"); target.value = "/original";
      const picker = createDirectoryPicker(root, { client: {
        get: async () => ({ path: "/denied", parent: "/", dirs: [], error: "Permission denied" }),
      } });
      try {
        picker.open(target);
        await new Promise(resolve => setTimeout(resolve, 0));
        if (!root.querySelector("#dir-modal-select").disabled) throw new Error("Unreadable folder cannot be selected");
        if (!root.querySelector("#dir-modal-list").textContent.includes("Permission denied")) throw new Error("Folder errors must be visible");
        root.querySelector("#dir-modal-select").dispatchEvent(new Event("click"));
        if (target.value !== "/original") throw new Error("Failed browse must preserve the original path");
      } finally { picker.unmount(); root.remove(); }
    });
    await applicationHandle.evaluate(application => { application.core.actions.switchTab("einstellungen"); document.querySelector('[data-settings-target="settings-media"]').click(); });
    await page.waitForFunction(() => document.querySelector("#jellyfin-url").value.includes("jellyfin.fixture"));
    await page.locator("#jellyfin-url").fill("http://unsaved.fixture");
    await applicationHandle.evaluate(application => application.integrations.jellyfin.refresh());
    assert.equal(await page.locator("#jellyfin-url").inputValue(), "http://unsaved.fixture");
    jellyfinSlow = true;
    const usersRequest = page.waitForRequest(request => request.url().endsWith("/api/jellyfin/users"));
    await page.locator("#jellyfin-users-load").click(); await usersRequest;
    await applicationHandle.evaluate(application => application.core.actions.switchTab("home"));
    const hidden = await page.locator("#jellyfin-user-status").textContent();
    await page.waitForTimeout(550);
    assert.equal(await page.locator("#jellyfin-user-status").textContent(), hidden);
    loginRequired = true;
    await applicationHandle.evaluate(application => { void application.profile.auth.requireLogin(); });
    await page.locator("#login-screen").waitFor({ state: "visible" });
    await page.locator("#login-username").fill("fixture-owner");
    await page.locator("#login-password").fill("fixture-password-only");
    await page.locator("#login-password-toggle").click();
    assert.equal(await page.locator("#login-password").getAttribute("type"), "text");
    await page.locator("#login-submit").click();
    await page.locator("#login-screen").waitFor({ state: "hidden" });
    assert.equal(writes.filter(write => write.path === "/api/auth/login").length, 1);
    assert.equal(await page.locator("#login-password").inputValue(), "");
    assert.equal(await applicationHandle.evaluate(application => application.profile.auth.get().user.username), "fixture-owner");
    await applicationHandle.evaluate(({ home, profile }) => {
      const items = Array.from({ length: 65 }, (_, index) => ({ slug: `taste-${index}`, title: `Taste ${index}`, year: String(1980 + index % 40), genres: ["Drama", index % 2 ? "Action" : "Comedy"], cover_url: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E" }));
      home.homeData.get().newMovies.push(...items);
      profile.auth.acceptUser({ ...profile.auth.get().user, taste_onboarding_required: true });
      profile.tasteOnboarding.show();
    });
    await page.locator("#taste-onboarding").waitFor({ state: "visible" });
    await page.waitForFunction(() => document.querySelectorAll(".taste-onboarding-card").length >= 20);
    assert.equal(await page.locator("#taste-onboarding-submit").isDisabled(), true);
    for (let index = 0; index < 5; index++) await page.locator(".taste-onboarding-card").nth(index).click();
    assert.equal(await page.locator("#taste-onboarding-submit").isDisabled(), false);
    await page.locator(".taste-onboarding-selection").first().click();
    assert.equal(await page.locator("#taste-onboarding-submit").isDisabled(), true);
    await page.locator(".taste-onboarding-card").first().click();
    const cardsBefore = await page.locator(".taste-onboarding-card").count();
    await page.locator("#taste-onboarding-more").click();
    assert.ok(await page.locator(".taste-onboarding-card").count() > cardsBefore);
    assert.equal(await page.locator("#taste-onboarding-count").textContent(), "5");
    tasteSlow = true;
    const tasteRequest = page.waitForRequest(request => request.url().endsWith("/api/taste/onboarding"));
    await page.locator("#taste-onboarding-submit").click(); await tasteRequest;
    await applicationHandle.evaluate(application => application.profile.tasteOnboarding.unmount());
    await page.waitForTimeout(550);
    assert.equal(await applicationHandle.evaluate(application => application.profile.auth.get().user.taste_onboarding_required), true);
    tasteSlow = false;
    await applicationHandle.evaluate(application => application.profile.tasteOnboarding.mount());
    assert.equal(await page.locator("#taste-onboarding-count").textContent(), "5");
    await page.locator("#taste-onboarding-submit").click();
    await page.locator("#taste-onboarding").waitFor({ state: "hidden" });
    const tasteWrites = writes.filter(write => write.path === "/api/taste/onboarding");
    assert.equal(tasteWrites.length, 2); assert.equal(tasteWrites[1].body.items.length, 5);
    // Once an account exists, a protected 401 still opens the expired-session login.
    assert.equal(await protectedRequest(), 401);
    await page.locator("#login-screen").waitFor({ state: "visible" });
    assert.equal(await page.evaluate(() => window.sessionExpirations), 1);
    assert.equal(await applicationHandle.evaluate(application => application.profile.auth.get().authenticated), false);
    assert.equal(await page.locator("#login-status").evaluate(element => element.classList.contains("error")), true);
    assert.equal(await protectedRequest(), 401);
    assert.equal(await page.evaluate(() => window.sessionExpirations), 1);
    assert.deepEqual(errors, []); assert.deepEqual(missing, []);
    await applicationHandle.dispose();
    console.log(JSON.stringify({ passed: true, setupSubmissions: submissions.length, errors, missing }));
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });
