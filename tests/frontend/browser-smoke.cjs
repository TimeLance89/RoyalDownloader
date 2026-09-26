// Optional integration check: use an existing Playwright installation, no build required.
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
  const browser = await chromium.launch({ headless: true, channel: process.env.ROYAL_BROWSER || "msedge" });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.addInitScript(paths => {
      document.addEventListener("DOMContentLoaded", async () => {
        for (const path of paths) Object.assign(window, await import(path));
      }, { once: true });
    }, ["/js/shell/presentation.js", "/js/shell/state.js", "/js/shell/actions/anime.js", "/js/shell/actions/aniworld.js", "/js/shell/actions/home.js", "/js/shell/actions/library.js", "/js/shell/actions/movie-collections.js", "/js/shell/actions/movies.js", "/js/shell/actions/movie_download_feedback.js", "/js/shell/actions/series.js", "/js/shell/actions/settings.js", "/js/shell/actions/user-profile.js"]);
    const errors = [], missing = [], calls = [];
    page.on("pageerror", error => { errors.push(error.message); console.error(error.stack); });
    page.on("console", message => { if (message.type() === "error" && !message.text().includes("503 (Service Unavailable)")) errors.push(message.text()); });
    page.on("response", response => { if (response.status() === 404 && /\.(js|css)/.test(response.url())) missing.push(response.url()); });
    const calendarDate = new Date().toLocaleDateString("sv-SE");
    let aniworldFixture = false, slowAniworldDetail = false;
    let animeFixture = false, slowAnimeDetail = false, animeDetailCalls = 0;
    let calendarMode = "ready", searchMode = "ready", directorySlow = false;
    let layout = { version: 1, hero_visible: true, rail_order: ["personal", "top", "series", "genre", "explore", "gems", "fresh", "new_movies", "new_series", "high_rated", "movies", "library"], hidden_rails: ["new_movies", "new_series", "high_rated", "movies", "library"] };
    let layoutWrites = 0, layoutSlow = false, dockSlow = false, moodSlow = false;
    let seerrSyncs = 0;
    let recommendationMode = "ready", recommendationCalls = 0, intelligenceTests = 0;
    const calendarSnapshot = { ready: true, days: [{ date: calendarDate, entries: [
      { title: "Calendar Alpha", base_slug: "serienstream:calendar-alpha", season: 1, episode: 2, language_id: 1, released: true, time: "18:00" },
      { title: "Calendar Beta", base_slug: "serienstream:calendar-beta", season: 2, episode: 3, language_id: 2, released: false, time: "19:00" },
    ] }] };
    let movieSubscriptions = [], movieSubscriptionWrites = [], movieSubscriptionChecks = 0, slowMovieSubscriptionSave = false, movieSubscriptionMode = "ready";
    let releaseMode = "ready", socket, sockets = 0;
    let moduleEnabled = true, moduleWrites = 0, profileMode = "ready", householdSlow = false;
    let storageJobs = [], storageHistory = [], storageMode = "ready", storageMoves = 0, storageSaves = 0;
    let policyMode = "ready", policyWrites = [];
    let policy = { auto_download: false, check_interval_min: 30, max_parallel_downloads: 2, weekday_window_start: null, weekday_window_end: null, weekend_window_start: null, weekend_window_end: null };
    let inboxItems = [], inboxReads = [], inboxChecks = 0, slowInboxRead = false, slowLibraryCheck = false, libraryRemoves = [], libraryRuleWrites = [], libraryAdds = [], slowRuleSave = false, slowLibraryRemove = false;
    const queue = { count: 0, groups: [], activity: {}, providers: {} };
    let accountMode = "ready", accountCreates = 0, accountResets = 0, accountDeletes = 0, passwordChanges = 0, accountRevokes = 0;
    let accountUsers = [];
    const user = { id: "fixture", display_name: "Test", username: "test", role: "admin" };
    await page.routeWebSocket("**/ws", ws => { socket = ws; sockets++; });
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      calls.push(url.pathname);
      let data = {};
      if (url.pathname === "/api/tmdb/movies" && moodSlow) {
        await new Promise(resolve => setTimeout(resolve, 600));
        data = { movies: { "mood-fixture": { title: "Late Mood Metadata" } } };
      }
      if (url.pathname === "/api/tmdb/movie") {
        if (dockSlow) await new Promise(resolve => setTimeout(resolve, 600));
        data = { movie: { title: "Dock Fixture", trailer: { site: "YouTube", key: "abcdefghijk" } } };
      }
      if (url.pathname === "/api/home/layout") {
        if (route.request().method() === "PUT") {
          layoutWrites++; layout = route.request().postDataJSON();
          if (layoutSlow) await new Promise(resolve => setTimeout(resolve, 600));
        }
        data = layout;
      }
      if (url.pathname === "/api/intelligence/recommendations") {
        recommendationCalls++;
        if (recommendationMode === "slow") await new Promise(resolve => setTimeout(resolve, 450));
        const candidates = route.request().postDataJSON().candidates;
        data = { available: true, recommendations: candidates.slice(0, 2).map(item => ({ key: item.key, score: 90 })),
          source: recommendationMode === "baseline" ? "baseline" : "refined", model: "Fixture" };
      }
      if (url.pathname === "/api/intelligence/test") { intelligenceTests++; data = { models: ["Fixture"], model_available: true }; }
      if (url.pathname === "/api/browse-dir") {
        if (directorySlow) await new Promise(resolve => setTimeout(resolve, 450));
        const path = url.searchParams.get("path") || "/fixture";
        data = { path, parent: path === "/fixture" ? null : "/fixture",
          dirs: path === "/fixture" ? [{ name: "Child", path: "/fixture/child" }] : [] };
      }
      if (url.pathname === "/api/seerr/config" || url.pathname === "/api/seerr/sync") {
        if (url.pathname.endsWith("/sync")) seerrSyncs++;
        data = { enabled: true, url: "http://fixture", has_api_key: true, poll_interval_seconds: 60, connected: true };
      }
      if (url.pathname === "/api/ui/config") data = { language: "de", configured: true };
      if (url.pathname.startsWith("/api/auth/")) data = { configured: true, authenticated: true, user, users: [user] };
      if (url.pathname === "/api/auth/config") data = { configured: true, active_sessions: 2 };
      if (url.pathname === "/api/auth/users") {
        if (route.request().method() === "POST") {
          accountCreates++;
          const body = route.request().postDataJSON();
          accountUsers.push({ id: "new-member", enabled: true, ...body });
          data = { user: accountUsers.at(-1) };
        } else data = { users: [user, ...accountUsers] };
      }
      if (url.pathname.endsWith("/reset-password")) { accountResets++; data = { ok: true }; }
      if (url.pathname === "/api/auth/users/new-member" && route.request().method() === "DELETE") {
        accountDeletes++; accountUsers = []; data = { ok: true };
      }
      if (url.pathname === "/api/auth/sessions/revoke") { accountRevokes++; data = { revoked: 1, active_sessions: 1 }; }
      if (url.pathname === "/api/me/password") {
        passwordChanges++;
        if (accountMode === "slow") await new Promise(resolve => setTimeout(resolve, 450));
        data = { configured: true, user, active_sessions: 1 };
      }
      if (url.pathname === "/api/setup/status") data = { required: false };
      if (url.pathname === "/api/config") data = { save_path: "", series_path: "" };
      if (url.pathname === "/api/modules/seerr-sync") { moduleEnabled = route.request().postDataJSON().enabled; moduleWrites++; }
      if (url.pathname === "/api/modules") data = { modules: [{ id: "seerr-sync", name: "Seerr Fixture", category: "integration", enabled: moduleEnabled, runtime_status: "running", health: "healthy", integration_health: { state: "healthy", detail: "Fixture" }, configured: true }] };
      if (url.pathname === "/api/storage/status") {
        if (storageMode === "slow") await new Promise(resolve => setTimeout(resolve, 450));
        if (storageMode === "error") { await route.fulfill({ status: 503, json: { detail: "storage offline" } }); return; }
        data = { locations: [], roots: [], volumes: [], summary: { free_bytes: 1024, total_bytes: 2048, used_bytes: 1024, used_percent: 50, volume_count: 0 } };
      }
      if (url.pathname === "/api/storage/locations/save") { storageSaves++; data = { saved: true }; }
      if (url.pathname === "/api/storage/scan") data = { scanned_files: 1, candidates: [{ root: "movies", relative_path: "Fixture.mkv", name: "Storage Fixture", size_bytes: 1024, token: "fixture-only", expires_at: 1900000000, kind: "file" }] };
      if (url.pathname === "/api/storage/move/plan") data = { source_name: "Storage Fixture", source_kind: "movie", size_bytes: 1024, targets: [{ root: "destination", label: "Fixture Target", eligible: true, free_bytes: 4096, required_bytes: 1024 }] };
      if (url.pathname === "/api/storage/move") {
        storageMoves++;
        const job = { job_id: "fixture-move", source_root: "movies", candidate_path: "Fixture.mkv", source_name: "Storage Fixture", destination_label: "Fixture Target", size_bytes: 1024, status: "running" };
        storageJobs = [job]; data = { job };
      }
      if (url.pathname === "/api/storage/move/jobs") data = { jobs: storageJobs, history: storageHistory };
      if (url.pathname === "/api/automation/policy") {
        if (route.request().method() === "POST") { const body = route.request().postDataJSON(); policyWrites.push(body); policy = { ...policy, ...body }; }
        if (policyMode === "slow") await new Promise(resolve => setTimeout(resolve, 450));
        if (policyMode === "error") { await route.fulfill({ status: 503, json: { detail: "policy offline" } }); return; }
        data = policy;
      }
      if (url.pathname === "/api/genres") data = { genres: [] };
      if (url.pathname === "/api/queue") data = { queue };
      if (url.pathname === "/api/queue/history") data = { jobs: [] };
      if (url.pathname === "/api/queue/jobs/job/cancel") data = { queue };
      if (url.pathname === "/api/watchlist") data = { watchlist: inboxItems, health: {} };
      if (url.pathname === "/api/watchlist/check") {
        inboxChecks++; data = { watchlist: inboxItems, health: {}, checked: inboxItems.length, total: inboxItems.length };
        if (slowLibraryCheck) await new Promise(resolve => setTimeout(resolve, 450));
      }
      if (url.pathname === "/api/watchlist/add") {
        const body = route.request().postDataJSON(); libraryAdds.push(body);
        inboxItems.push({ ...body, status: "current" });
        data = { watchlist: inboxItems, health: {} };
      }
      if (url.pathname === "/api/watchlist/mode") {
        const body = route.request().postDataJSON(); libraryRuleWrites.push(body);
        if (slowRuleSave) await new Promise(resolve => setTimeout(resolve, 450));
        inboxItems = inboxItems.map(item => item.base_slug === body.base_slug ? { ...item, ...body } : item);
        data = { watchlist: inboxItems, health: {} };
      }
      if (url.pathname === "/api/watchlist/remove") {
        const body = route.request().postDataJSON(); libraryRemoves.push(body);
        if (slowLibraryRemove) await new Promise(resolve => setTimeout(resolve, 450));
        inboxItems = inboxItems.filter(item => !body.base_slugs.includes(item.base_slug));
        data = { watchlist: inboxItems, health: {} };
        socket.send(JSON.stringify({ type: "watchlist_update", ...data }));
      }
      if (url.pathname === "/api/watchlist/downloads/read") {
        inboxReads.push(route.request().postDataJSON());
        if (slowInboxRead) await new Promise(resolve => setTimeout(resolve, 450));
        inboxItems = inboxItems.map(item => ({ ...item, downloaded_count: 0 }));
        data = { watchlist: [] };
      }
      if (url.pathname === "/api/movie-subscriptions") {
        if (route.request().method() === "POST") {
          const body = route.request().postDataJSON(); movieSubscriptionWrites.push(body);
          if (slowMovieSubscriptionSave) await new Promise(resolve => setTimeout(resolve, 450));
          movieSubscriptions = [{ key: "tmdb:321", status: "current", ...body }];
          socket.send(JSON.stringify({ type: "movie_subscriptions_update", movie_subscriptions: movieSubscriptions }));
        }
        data = { movie_subscriptions: movieSubscriptions };
      }
      if (url.pathname === "/api/movie-subscriptions/check") {
        movieSubscriptionChecks++;
        if (movieSubscriptionMode === "error") { await route.fulfill({ status: 503, json: { detail: "movie check offline" } }); return; }
        data = { movie_subscriptions: movieSubscriptions };
      }
      if (url.pathname === "/api/movie-subscriptions/remove") {
        movieSubscriptions = []; data = { movie_subscriptions: movieSubscriptions };
        socket.send(JSON.stringify({ type: "movie_subscriptions_update", ...data }));
      }

      if (url.pathname === "/api/movies") data = { results: [], movies: [], sources: [] };
      if (url.pathname === "/api/series") data = { results: [], series: [], sources: [] };
      if (url.pathname === "/api/anime" || url.pathname === "/api/aniworld") data = { results: [], items: [] };
      if (["/api/movies", "/api/series", "/api/anime", "/api/movie-collections"].includes(url.pathname) && url.searchParams.get("query")) {
        if (searchMode === "slow" || url.pathname === "/api/series") await new Promise(resolve => setTimeout(resolve, 450));
        if (searchMode === "error") { await route.fulfill({ status: 503, json: { detail: "search offline" } }); return; }
        const query = url.searchParams.get("query");
        data = { results: url.pathname === "/api/movies" ? Array.from({ length: 70 }, (_, id) => ({ slug: `${query}-${id}`, title: `${query} Movie ${id}`, year: "2026" })) : [] };
      }
      if (aniworldFixture && url.pathname === "/api/aniworld") data = {
        results: [{ id: "fixture", title: "AniWorld Fixture", translations: { dub: 3, sub: 3 } }],
        page: 1, total: 1, has_more: false, facets: { letters: { A: 1 }, genres: { Drama: 1 } },
      };
      if (url.pathname === "/api/aniworld/fixture") {
        if (slowAniworldDetail) await new Promise(resolve => setTimeout(resolve, 450));
        data = { id: "fixture", title: "AniWorld Fixture", translation: url.searchParams.get("translation") || "dub",
          translations: { dub: 3, sub: 3 }, seasons: [{ season: 1, label: "Staffel 1", count: 2 }, { season: 0, label: "Filme", count: 1 }],
          episodes: [{ slug: "aw-1", season: 1, number: 1, label: "Folge 1" }, { slug: "aw-2", season: 1, number: 2, label: "Folge 2" },
            { slug: "aw-film", season: 0, number: 1, label: "Film", kind: "movie" }],
        };
      }
      if (animeFixture && url.pathname === "/api/anime") data = {
        results: [{ id: "fixture", title: "Anime Fixture", translations: { dub: 4, sub: 4 } }], page: 1, total: 1, has_more: false,
      };
      if (url.pathname === "/api/anime/fixture") {
        animeDetailCalls++;
        if (slowAnimeDetail) await new Promise(resolve => setTimeout(resolve, 450));
        const episodePage = Number(url.searchParams.get("episode_page") || 1);
        data = { id: "fixture", title: "Anime Fixture", translation: url.searchParams.get("translation") || "dub",
          translations: { dub: 4, sub: 4 }, page: episodePage, page_count: 2,
          episodes: [1, 2].map(number => ({ slug: `anime-fixture-${episodePage}-${number}`, number, label: `Episode ${number}` })),
        };
      }
      if (url.pathname === "/api/series-calendar") {
        if (calendarMode === "slow") await new Promise(resolve => setTimeout(resolve, 450));
        if (calendarMode === "error") { await route.fulfill({ status: 503, json: { detail: "calendar offline" } }); return; }
        data = calendarSnapshot;
      }
      if (url.pathname === "/api/me/profile-summary") {
        if (profileMode === "slow") await new Promise(resolve => setTimeout(resolve, 400));
        if (profileMode === "error") { await route.fulfill({ status: 503, json: { detail: "profile offline" } }); return; }
        data = { user, recent_downloads: [{ title: "Persistent Request", status: "completed", requested_at: 1700000000 }], favorites: [] };
      }
      if (url.pathname === "/api/me/household") {
        if (householdSlow) await new Promise(resolve => setTimeout(resolve, 400));
        data = { users: [user], current_user_id: user.id, unlocked: true };
      }
      if (url.pathname === "/api/taste/profile") data = { profile: { interactions: 5 } };
      if (url.pathname === "/api/v1/capabilities") data = { build: "fixture" };
      if (url.pathname === "/api/releases/config") data = { region: "de", has_api_key: true };
      if (url.pathname === "/api/releases") {
        if (releaseMode === "error") { await route.fulfill({ status: 503, json: { detail: "offline" } }); return; }
        if (releaseMode === "slow") await new Promise(resolve => setTimeout(resolve, 500));
        data = { region: "de", configured: true, entries: releaseMode === "empty" ? [] : [
          { id: "one", title: "Fixture Movie", platform: "Fixture", platform_id: "test", media_type: "movie", year: "2026", has_started: false, timestamp: 1900000000, can_check: false },
        ] };
      }
      await route.fulfill({ json: data });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => !document.getElementById("setup-wizard").classList.contains("is-open"));
    // Layout draft previews are local; cancelled writes are reconciled from the server.
    await page.locator("#home-layout-open").click();
    await page.locator("#home-layout-modal").waitFor({ state: "visible" });
    assert.equal(await page.locator(".home-layout-row").count(), 12);
    await page.locator("#home-layout-hero").uncheck();
    assert.equal(await page.locator("#home-hero").evaluate(el => el.classList.contains("home-layout-hidden")), true);
    await page.locator("#home-layout-cancel").click();
    assert.equal(await page.locator("#home-hero").evaluate(el => el.classList.contains("home-layout-hidden")), false);
    await page.locator("#home-layout-open").click();
    await page.locator('.home-layout-row[data-rail-id="top"] .home-layout-move').first().click();
    await page.locator("#home-layout-save").click();
    await page.locator("#home-layout-modal").waitFor({ state: "hidden" });
    assert.equal(layoutWrites, 1);
    assert.equal(layout.rail_order[0], "top");
    layoutSlow = true;
    await page.locator("#home-layout-open").click();
    await page.locator("#home-layout-hero").uncheck();
    await page.locator("#home-layout-save").click();
    await page.waitForFunction(() => document.getElementById("home-layout-save").disabled);
    await page.evaluate(() => switchTab("releases"));
    await page.locator("#home-layout-modal").waitFor({ state: "hidden" });
    await page.waitForTimeout(700);
    await page.evaluate(() => switchTab("home"));
    await page.locator("#home-layout-open").click();
    await page.locator("#home-layout-modal").waitFor({ state: "visible" });
    assert.equal(await page.locator("#home-layout-hero").isChecked(), false);
    layoutSlow = false;
    await page.locator("#home-layout-reset").click();
    await page.locator("#home-layout-save").click();
    await page.locator("#home-layout-modal").waitFor({ state: "hidden" });
    assert.equal(layoutWrites, 3);
    // The card dock owns keyboard interactions and aborts late trailer metadata.
    await page.evaluate(() => {
      const card = createHomeCard({ kind: "movie", item: { slug: "dock-fixture", title: "Dock Fixture" } });
      card.id = "dock-fixture-card";
      document.getElementById("tab-home").append(card);
    });
    await page.locator("#dock-fixture-card .home-card-primary-action").focus();
    await page.locator(".home-card-dock.is-visible").waitFor();
    await page.locator("#dock-fixture-card .home-card-primary-action").press("ArrowDown");
    await page.waitForFunction(() => document.activeElement.matches(".home-card-dock-action"));
    await page.keyboard.press("Escape");
    await page.locator(".home-card-dock").waitFor({ state: "hidden" });
    assert.equal(await page.locator("#dock-fixture-card .home-card-primary-action").evaluate(el => el === document.activeElement), true);
    await page.locator("#home-layout-open").focus();
    await page.locator("#dock-fixture-card .home-card-primary-action").focus();
    await page.locator(".home-card-dock.is-visible").waitFor();
    dockSlow = true;
    const trailerRequest = page.waitForRequest(request => request.url().includes("/api/tmdb/movie"));
    await page.locator('.home-card-dock button[aria-label="Dock Fixture: Trailer abspielen"]').click();
    await trailerRequest;
    await page.evaluate(() => switchTab("releases"));
    await page.waitForTimeout(750);
    assert.equal(await page.locator(".home-card-dock").count(), 0);
    assert.equal(await page.locator("#fp-trailer-modal").evaluate(el => el.hidden), true);
    assert.equal(await page.evaluate(() => sharedPresentation.movieState.metadataCache["dock-fixture"]?.trailer || null), null);
    dockSlow = false;
    await page.evaluate(() => { switchTab("home"); document.getElementById("dock-fixture-card").remove(); });
    // Content-language choices share the dialog lifecycle, including superseded prompts.
    const languageResult = await page.evaluate(async () => {
      const { createMediaLanguage } = await import("/js/features/media-details/language.js");
      const feature = createMediaLanguage(document, { getProviders: () => ({ contentLanguages: new Set(["de", "en"]), catalog: {} }) });
      const movie = { source_providers: [{ content_language: "de", label: "DE", hoster_count: 2 }, { content_language: "en", label: "EN", hoster_count: 3 }] };
      feature.mount(); feature.mount();
      const first = feature.choose(movie);
      const second = feature.choose(movie);
      const cancelled = await first;
      document.querySelector('#movie-language-choice [data-language="en"]').click();
      const selected = await second;
      const third = feature.choose(movie);
      feature.unmount();
      return { cancelled, selected, unmounted: await third, remaining: document.querySelectorAll("#movie-language-choice").length };
    });
    assert.deepEqual(languageResult, { cancelled: "", selected: "en", unmounted: "", remaining: 0 });
    // Mood choices keep hard genre constraints and nested Escape behavior.
    await page.locator("#home-program-mood").click();
    await page.locator('#mood-options [data-value="movie"]').click();
    await page.locator("#mood-next").click();
    await page.locator("#mood-genre-toggle").click();
    await page.locator('#mood-genre-options [data-value="Drama"]').click();
    await page.locator('#mood-genre-options [data-value="Horror"]').click();
    assert.equal(await page.locator('#mood-genre-options [data-value="Action"]').isDisabled(), true);
    await page.locator("#mood-genre-clear").click();
    await page.locator('#mood-options [data-value="shadow"]').click();
    await page.locator("#mood-quick").click();
    await page.locator("#mood-empty").waitFor({ state: "visible" });
    await page.locator("#mood-refine-toggle").click();
    await page.locator("#mood-refine").waitFor({ state: "visible" });
    await page.keyboard.press("Escape");
    await page.locator("#mood-results").waitFor({ state: "visible" });
    await page.keyboard.press("Escape");
    await page.locator("#mood-modal").waitFor({ state: "hidden" });
    assert.equal(await page.locator("#home-program-mood").evaluate(el => document.activeElement === el), true);
    moodSlow = true;
    await page.evaluate(() => sharedPresentation.homeData.get().newMovies.push({ slug: "mood-fixture", title: "Mood Fixture", genres: ["Horror"] }));
    const moodRequest = page.waitForRequest(request => request.url().includes("/api/tmdb/movies"));
    await page.locator("#home-program-mood").click();
    await moodRequest;
    await page.locator("#mood-close").click();
    const closedMood = await page.locator("#mood-modal").innerHTML();
    await page.waitForTimeout(700);
    assert.equal(await page.locator("#mood-modal").innerHTML(), closedMood);
    assert.equal(await page.evaluate(() => sharedPresentation.movieState.metadataCache["mood-fixture"]?.title || null), null);
    moodSlow = false;
    await page.evaluate(() => sharedPresentation.homeData.get().newMovies.splice(0));


    await page.evaluate(() => switchTab("releases"));
    await page.getByRole("heading", { name: "Fixture Movie", exact: true }).waitFor();
    assert.equal(sockets, 1);
    // Modal focus is restored, Tab is trapped, and closing cancels pending focus work.
    const modalResult = await page.evaluate(async () => {
      const trigger = document.createElement("button");
      document.body.append(trigger);
      trigger.focus();
      openMediaModal("series-detail-modal", trigger);
      await new Promise(requestAnimationFrame);
      const focused = document.activeElement.classList.contains("media-modal-close");
      const modal = document.getElementById("series-detail-modal");
      const buttons = [...modal.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')].filter(el => !el.hidden && el.getClientRects().length);
      buttons.at(-1).focus();
      handleMediaModalKeydown(new KeyboardEvent("keydown", { key: "Tab", cancelable: true }));
      const trapped = document.activeElement === buttons[0];
      handleMediaModalKeydown(new KeyboardEvent("keydown", { key: "Escape", cancelable: true }));
      const restored = modal.hidden && document.activeElement === trigger;
      openMediaModal("series-detail-modal", trigger);
      closeMediaModal("series-detail-modal");
      await new Promise(requestAnimationFrame);
      const cancelled = document.activeElement === trigger;
      trigger.remove();
      return { focused, trapped, restored, cancelled };
    });
    assert.deepEqual(modalResult, { focused: true, trapped: true, restored: true, cancelled: true });

    const startCalls = calls.filter(path => path === "/api/releases").length;
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => { switchTab("home"); switchTab("releases"); });
      await page.getByRole("heading", { name: "Fixture Movie", exact: true }).waitFor();
      await page.waitForLoadState("networkidle");
    }
    assert.equal(calls.filter(path => path === "/api/releases").length - startCalls, 3);
    assert.equal(sockets, 1);
    await page.locator("#release-search").fill("no matching title");
    await page.getByRole("heading", { name: "Keine Releases in dieser Auswahl" }).waitFor();
    await page.locator("#release-search").fill("");
    await page.evaluate(() => switchTab("einstellungen"));
    await page.locator("#release-settings").waitFor({ state: "attached" });
    assert.equal(await page.locator("#release-settings").count(), 1);
    assert.equal(calls.filter(path => path === "/api/releases/config").length, 1);
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => switchTab("einstellungen"));
      await page.locator('[data-settings-target="settings-modules"]').click();
      await page.locator('[data-module="seerr-sync"]').waitFor();
      await page.waitForLoadState("networkidle");
      await page.locator('[data-module="seerr-sync"]').setChecked(!moduleEnabled);
      await page.waitForLoadState("networkidle");
      assert.equal(moduleWrites, i + 1);
      await page.evaluate(() => switchTab("home"));
    }

    releaseMode = "empty";
    await page.evaluate(() => switchTab("releases"));
    await page.getByRole("heading", { name: "Keine Releases in dieser Auswahl" }).waitFor();
    releaseMode = "error";
    await page.evaluate(() => { switchTab("home"); switchTab("releases"); });
    await page.getByRole("heading", { name: "Termine gerade nicht erreichbar" }).waitFor();
    releaseMode = "slow";
    await page.evaluate(() => { switchTab("home"); switchTab("releases"); switchTab("home"); });
    await page.waitForTimeout(650);
    assert.equal(await page.locator("#tab-home").evaluate(el => el.classList.contains("active")), true);
    socket.send(JSON.stringify({ type: "queue_update", queue: { ...queue, count: 1, groups: [{ name: "Test", items: [{ job_id: "job", slug: "film", title: "Fixture Download", job_status: "downloading", progress: 10 }] }] } }));
    await page.getByText("Fixture Download", { exact: true }).waitFor({ state: "attached" });
    socket.send(JSON.stringify({ type: "progress", job_id: "job", pct: 55, label: "Fixture Download", job: { progress: 55 } }));
    await page.waitForFunction(() => document.querySelector('.queue-item-progress i')?.style.width === "55%");
    await page.evaluate(() => document.querySelector('.queue-item button[aria-label$="abbrechen"]').click());
    await page.waitForFunction(() => document.getElementById("queue-count").textContent === "0 Einträge");
    socket.send(JSON.stringify({ type: "queue_done", done_jobs: 1, total_jobs: 1, failed_jobs: 0 }));
    await page.waitForFunction(() => document.getElementById("dl-state-title").textContent === "Abgeschlossen");
    const beforeReconnect = calls.filter(path => path === "/api/queue").length;
    socket.close({ code: 1012, reason: "fixture server restart" });
    const reconnectDeadline = Date.now() + 10_000;
    while (sockets < 2 && Date.now() < reconnectDeadline) await page.waitForTimeout(50);
    await page.waitForFunction(async () => (await import("/js/core/store.js")).appStore.get().connection === "connected");
    await page.waitForLoadState("networkidle");
    assert.equal(sockets, 2);
    assert.equal(calls.filter(path => path === "/api/queue").length, beforeReconnect + 1);
    // Exercise actual decorated cards at a larger size, including safe title text.
    await page.evaluate(() => {
      switchTab("home");
      const entries = Array.from({ length: 100 }, (_, id) => ({ kind: "movie", item: {
        slug: `fixture-${id}`, title: id ? `Fixture ${id}` : '<script>throw "injected"</script>', year: "2026",
      } }));
      renderHomeRail("home-movies-track", entries);
    });
    assert.equal(await page.locator("#home-movies-track .home-card").count(), 300);
    assert.equal(await page.locator("#home-movies-track script").count(), 0);

    // Intelligence is owned by the visible Home; late refinements cannot repaint it.
    await page.evaluate(() => {
      sharedPresentation.homeData.get().newMovies.push({ slug: "ai-fixture", title: "AI Fixture", genres: ["Drama"] });
      sharedPresentation.intelligence.apply({ enabled: true, module_available: true, model: "Fixture" });
    });
    await page.waitForFunction(() => document.getElementById("home-ai-rail").dataset.state === "ready");
    const intelligenceInitial = recommendationCalls;
    await page.evaluate(() => sharedPresentation.recommendations.refresh());
    assert.equal(recommendationCalls, intelligenceInitial);
    recommendationMode = "slow";
    await page.evaluate(() => { void sharedPresentation.recommendations.refresh(true); });
    await page.waitForTimeout(50);
    await page.evaluate(() => switchTab("releases"));
    const intelligenceHidden = await page.locator("#home-ai-rail").innerHTML();
    await page.waitForTimeout(500);
    assert.equal(await page.locator("#home-ai-rail").innerHTML(), intelligenceHidden);
    recommendationMode = "baseline";
    await page.evaluate(() => switchTab("home"));
    await page.waitForFunction(() => document.getElementById("home-ai-note").textContent.includes("verfeinert"));
    await page.evaluate(() => switchTab("einstellungen"));
    const intelligenceStopped = recommendationCalls;
    await page.waitForTimeout(4100);
    assert.equal(recommendationCalls, intelligenceStopped);
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => { switchTab("releases"); switchTab("einstellungen"); });
    }
    await page.locator("#ai-test").evaluate(button => button.click());
    await page.waitForFunction(() => document.getElementById("ai-status").textContent.includes("Verbunden"));
    assert.equal(intelligenceTests, 1);
    await page.evaluate(() => {
      sharedPresentation.intelligence.apply({ enabled: false });
      sharedPresentation.homeData.get().newMovies.splice(0);
      switchTab("home");
    });

    inboxItems = [{ base_slug: "inbox-fixture", title: "Inbox Fixture", status: "failed", open_count: 2, new_count: 2, failed_count: 1, downloaded_count: 1, last_unread_downloaded_episode: { season: 1, episode: 4, downloaded_at: 123 } }];
    socket.send(JSON.stringify({ type: "watchlist_update", watchlist: inboxItems, health: {} }));
    await page.waitForFunction(() => document.getElementById("notif-badge").textContent === "1");
    for (let i = 0; i < 3; i++) {
      await page.locator("#notif-bell").click();
      await page.locator('[data-notif-filter="downloaded"]').click();
      await page.locator(".notif-item-read").waitFor();
      await page.locator("#notif-close").click();
    }
    await page.locator("#notif-bell").click();
    await page.locator(".notif-item-read").click();
    await page.waitForFunction(() => document.querySelector("#notif-feedback")?.textContent.includes("als gelesen"));
    assert.deepEqual(inboxReads, [{ base_slug: "inbox-fixture", downloaded_before: 123 }]);
    await page.locator('[data-notif-filter="new"]').click();
    await page.locator(".notif-item-check").click();
    await page.waitForFunction(() => document.querySelector("#notif-feedback")?.textContent.includes("Prüfung abgeschlossen"));
    assert.equal(inboxChecks, 1);
    await page.locator("#notif-close").click();

    // Account actions remain scoped through repeated settings mounts.
    for (let i = 0; i < 3; i++) await page.evaluate(() => { switchTab("home"); switchTab("einstellungen"); });
    await page.evaluate(() => document.querySelector('[data-settings-target="settings-account"]').click());
    await page.waitForFunction(() => document.getElementById("account-state").textContent.includes("Angemeldet"));
    await page.locator("#new-user-display-name").evaluate(input => { input.value = "Member Fixture"; });
    await page.locator("#new-user-username").evaluate(input => { input.value = "member"; });
    await page.locator("#new-user-create").evaluate(button => button.click());
    await page.waitForFunction(() => document.querySelector('[data-user-id="new-member"]'));
    assert.equal(accountCreates, 1);
    await page.locator('[data-user-action="reset"][data-user-id="new-member"]').click();
    await page.waitForFunction(() => document.getElementById("account-users-status").textContent.includes("zurückgesetzt"));
    assert.equal(accountResets, 1);
    page.once("dialog", dialog => dialog.accept());
    await page.locator('[data-user-action="delete"][data-user-id="new-member"]').click();
    await page.waitForFunction(() => !document.querySelector('[data-user-id="new-member"]')).catch(async error => {
      console.error({ accountDeletes, accountResets, status: await page.locator("#account-users-status").textContent(), errors }); throw error;
    });
    assert.equal(accountDeletes, 1);
    await page.locator("#account-revoke").evaluate(button => button.click());
    await page.waitForFunction(() => document.getElementById("account-revoke-status").textContent.includes("1 Sitzung"));
    assert.equal(accountRevokes, 1);
    await page.evaluate(() => {
      document.getElementById("account-password").value = "fixture-only-password";
      document.getElementById("account-password-repeat").value = "wrong";
      document.getElementById("account-save").click();
    });
    assert.equal(passwordChanges, 0);
    assert.match(await page.locator("#account-status").textContent(), /stimmen nicht/);
    accountMode = "slow";
    await page.evaluate(() => {
      document.getElementById("account-password-repeat").value = "fixture-only-password";
      document.getElementById("account-save").click();
    });
    await page.waitForTimeout(50);
    await page.evaluate(() => switchTab("home"));
    const accountHidden = await page.locator("#settings-account").innerHTML();
    await page.waitForTimeout(500);
    assert.equal(await page.locator("#settings-account").innerHTML(), accountHidden);
    assert.equal(await page.locator("#account-password").inputValue(), "");
    assert.equal(passwordChanges, 1);
    accountMode = "ready";

    // Search starts only on submit, paints progressively, and cancels superseded queries.
    await page.locator("#global-search-toggle").click();
    await page.locator("#global-search-input").fill("SearchFixture");
    assert.equal(await page.locator("#global-search-grid .home-card").count(), 0);
    await page.locator("#global-search-input").press("Enter");
    await page.waitForFunction(() => document.querySelectorAll("#global-search-grid .home-card").length === 70);
    await page.waitForFunction(() => !document.getElementById("global-search-status").textContent.includes("durchsucht"));
    await page.locator('[data-global-search-scope="series"]').click();
    assert.match(await page.locator("#global-search-grid").textContent(), /Nichts in diesem Filter/);
    await page.locator('[data-global-search-scope="all"]').click();
    searchMode = "slow";
    await page.locator("#global-search-input").fill("ObsoleteFixture");
    await page.locator("#global-search-input").press("Enter");
    await page.locator("#global-search-input").fill("LatestFixture");
    searchMode = "ready";
    await page.locator("#global-search-input").press("Enter");
    await page.waitForFunction(() => document.getElementById("global-search-grid").textContent.includes("LatestFixture"));
    await page.waitForTimeout(500);
    assert.doesNotMatch(await page.locator("#global-search-grid").textContent(), /ObsoleteFixture/);
    searchMode = "error";
    await page.locator("#global-search-input").fill("FailureFixture");
    await page.locator("#global-search-input").press("Enter");
    await page.waitForFunction(() => document.getElementById("global-search-grid").textContent.includes("Suche fehlgeschlagen"));
    await page.locator("#global-search-clear").click();
    assert.equal(await page.locator("#global-search-page").isHidden(), true);
    searchMode = "ready";

    // Integration reads and sync do not overwrite an unsaved form.
    moduleEnabled = true;
    await page.evaluate(() => { switchTab("einstellungen"); document.querySelector('[data-settings-target="settings-media"]').click(); });
    await page.locator("#seerr-url").fill("http://draft-fixture");
    await page.evaluate(() => sharedPresentation.integrations.refresh());
    assert.equal(await page.locator("#seerr-url").inputValue(), "http://draft-fixture");
    await page.locator("#seerr-sync").click();
    await page.waitForFunction(() => document.getElementById("seerr-status").textContent.includes("Verbunden"));
    assert.equal(seerrSyncs, 1);
    assert.equal(await page.locator("#seerr-url").inputValue(), "http://draft-fixture");
    // Shared folder dialog supports selection, focus restoration and cancellation.
    await page.locator('[data-settings-target="settings-general"]').click();
    await page.locator("#save-path").fill("/fixture");
    await page.locator("#browse-dir-btn").click();
    await page.locator("#dir-modal .dir-item").waitFor();
    await page.locator("#dir-modal .dir-item").focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.getElementById("dir-modal-path").textContent === "/fixture/child");
    await page.locator("#dir-modal-select").click();
    assert.equal(await page.locator("#save-path").inputValue(), "/fixture/child");
    assert.equal(await page.evaluate(() => document.activeElement.id), "browse-dir-btn");
    directorySlow = true;
    await page.locator("#browse-dir-btn").click();
    await page.keyboard.press("Escape");
    await page.waitForTimeout(500);
    assert.equal(await page.locator("#dir-modal").evaluate(root => root.classList.contains("hidden")), true);
    directorySlow = false;
    await page.evaluate(() => switchTab("home"));

    // Library filters are local; remounts bind once and abandoned checks cannot render.
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => switchTab("bibliothek"));
      await page.locator("#wl-list .library-card").waitFor();
      await page.locator("#wl-search").fill("absent");
      assert.equal(await page.locator("#wl-list .library-card").count(), 0);
      await page.locator("#wl-search-clear").click();
      await page.locator('[data-library-view="list"]').click();
      assert.equal(await page.locator("#wl-list").evaluate(el => el.classList.contains("is-list-view")), true);
      await page.locator("#wl-select-visible").click();
      assert.equal(await page.locator("#wl-selected-count").textContent(), "1");
      await page.locator("#wl-select-visible").click();
      await page.locator("#wl-check-all").click();
      await page.waitForFunction(() => document.getElementById("wl-status").textContent === "1/1 geprüft");
      assert.equal(inboxChecks, i + 2);
      await page.evaluate(() => switchTab("home"));
    }
    await page.evaluate(() => switchTab("bibliothek"));
    slowLibraryCheck = true;
    await page.locator("#wl-check-all").click();
    await page.waitForFunction(() => sharedPresentation.subscriptions.get().checkRunning);
    await page.evaluate(() => switchTab("home"));
    await page.waitForFunction(() => !sharedPresentation.subscriptions.get().checkRunning);
    const abandonedLibrary = await page.locator("#tab-bibliothek").innerHTML();
    await page.waitForTimeout(500);
    assert.equal(await page.locator("#tab-bibliothek").innerHTML(), abandonedLibrary);
    slowLibraryCheck = false;
    await page.evaluate(() => switchTab("bibliothek"));
    for (let i = 0; i < 3; i++) {
      await page.locator("#wl-list .wl-rule-btn").click();
      await page.locator('.watch-mode-option:has(input[value="all"])').click();
      await page.locator("#watch-mode-save").click();
      await page.waitForFunction(() => document.getElementById("watch-mode-modal").classList.contains("hidden"));
      assert.equal(libraryRuleWrites.length, i + 1);
      assert.deepEqual(libraryRuleWrites[i], { base_slug: "inbox-fixture", download_mode: "all", cleanup_mode: "keep" });
    }
    slowRuleSave = true;
    await page.locator("#wl-list .wl-rule-btn").click();
    await page.locator("#watch-mode-save").click();
    await page.waitForFunction(() => document.getElementById("watch-mode-save").disabled);
    await page.keyboard.press("Escape");
    const closedRule = await page.locator("#watch-mode-modal").innerHTML();
    await page.waitForTimeout(500);
    assert.equal(await page.locator("#watch-mode-modal").innerHTML(), closedRule);
    slowRuleSave = false;
    await page.locator("#wl-list .wl-rule-btn").click();
    await page.waitForFunction(() => document.activeElement === document.querySelector('input[name="watch-mode"]:checked'));
    await page.locator("#watch-mode-close").focus();
    await page.keyboard.press("Shift+Tab");
    assert.equal(await page.evaluate(() => document.activeElement.id), "watch-mode-save");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.id), "watch-mode-close");
    await page.evaluate(() => switchTab("home"));
    assert.equal(await page.locator("#watch-mode-modal").evaluate(el => el.classList.contains("hidden")), true);
    await page.evaluate(() => switchTab("bibliothek"));
    await page.locator("#wl-select-visible").click();
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#wl-remove").click();
    await page.locator("#wl-list .library-empty").waitFor();
    assert.deepEqual(libraryRemoves, [{ base_slugs: ["inbox-fixture"] }]);
    const priorSeries = await page.evaluate(() => sharedPresentation.seriesState.current);
    await page.evaluate(() => {
      sharedPresentation.seriesState.current = {
        base_slug: "new-fixture", title: "New Fixture", url: "/series/new-fixture", tmdb_id: 99,
        aliases: ["New Alias"], season_episode_counts: { 1: 1 }, season_counts_checked_at: 123,
        seasons: [{ episodes: [{ slug: "new-e1" }] }],
      };
      openWatchModeModal();
    });
    await page.locator('.watch-mode-option:has(input[value="latest_season"])').click();
    await page.locator("#watch-mode-save").click();
    await page.waitForFunction(() => document.getElementById("watch-mode-modal").classList.contains("hidden"));
    assert.deepEqual(libraryAdds, [{
      base_slug: "new-fixture", title: "New Fixture", sample_url: "/series/new-fixture", tmdb_id: 99,
      aliases: ["New Alias"], season_episode_counts: { 1: 1 }, season_counts_checked_at: 123,
      known_slugs: ["new-e1"], download_mode: "latest_season", cleanup_mode: "keep",
    }]);
    await page.evaluate(current => { sharedPresentation.seriesState.current = current; }, priorSeries);
    slowLibraryRemove = true;
    await page.locator("#wl-select-visible").click();
    page.once("dialog", dialog => dialog.accept());
    const removingRequest = page.waitForRequest(request => request.url().endsWith("/api/watchlist/remove"));
    await page.locator("#wl-remove").click();
    await removingRequest;
    await page.evaluate(() => switchTab("home"));
    await page.waitForFunction(() => sharedPresentation.subscriptions.get().items.length === 0);
    await page.evaluate(() => switchTab("bibliothek"));
    await page.locator("#wl-list .library-empty").waitFor();
    assert.equal(libraryRemoves.length, 2);
    slowLibraryRemove = false;



    animeFixture = true;
    const hadEnglish = await page.evaluate(() => sharedPresentation.providers.get().contentLanguages.has("en"));
    await page.evaluate(() => {
      sharedPresentation.providers.get().contentLanguages.add("en"); syncAnimeNavigationVisibility();
      sharedPresentation.anime.get().loaded = false; switchTab("anime");
    });
    await page.locator("#anime-results .anime-card").waitFor();
    for (let index = 0; index < 3; index++) {
      await page.locator("#anime-results .anime-card").click();
      await page.locator("#anime-episode-grid .anime-episode").first().waitFor();
      await page.locator("#anime-episode-grid .anime-episode").first().click();
      assert.equal(await page.locator("#anime-pick-count").textContent(), "1 ausgewählt");
      await page.locator("#anime-select-none").click();
      assert.equal(await page.locator("#anime-pick-count").textContent(), "0 ausgewählt");
      await page.evaluate(() => closeMediaModal("anime-detail-modal"));
    }
    assert.equal(animeDetailCalls, 3);
    await page.locator("#anime-results .anime-card").click();
    await page.locator("#anime-track-options [data-track=sub]").click();
    await page.waitForFunction(() => sharedPresentation.anime.get().current?.translation === "sub");
    await page.locator("#anime-episode-next").click();
    await page.waitForFunction(() => sharedPresentation.anime.get().current?.page === 2);
    await page.evaluate(() => closeMediaModal("anime-detail-modal"));
    slowAnimeDetail = true;
    const beforeSlowAnime = animeDetailCalls;
    await page.locator("#anime-results .anime-card").click();
    await page.waitForTimeout(60);
    assert.equal(animeDetailCalls, beforeSlowAnime + 1);
    await page.evaluate(() => { closeMediaModal("anime-detail-modal"); switchTab("home"); });
    await page.waitForTimeout(500);
    assert.equal(await page.evaluate(() => sharedPresentation.anime.get().current.episodes.length), 0);
    slowAnimeDetail = false; animeFixture = false;
    if (!hadEnglish) await page.evaluate(() => { sharedPresentation.providers.get().contentLanguages.delete("en"); syncAnimeNavigationVisibility(); });

    aniworldFixture = true;
    const hadGerman = await page.evaluate(() => sharedPresentation.providers.get().contentLanguages.has("de"));
    await page.evaluate(() => {
      sharedPresentation.providers.get().contentLanguages.add("de"); syncAniworldNavigationVisibility();
      sharedPresentation.aniworld.get().loaded = false; switchTab("aniworld");
    });
    await page.locator("#aniworld-results button.aniworld-card").waitFor();
    await page.locator("#aniworld-results button.aniworld-card").click();
    await page.locator("#aniworld-season-options button").first().waitFor();
    assert.equal(await page.locator("#aniworld-episode-grid .aniworld-episode").count(), 2);
    await page.locator("#aniworld-select-all").click();
    assert.equal(await page.locator("#aniworld-pick-count").textContent(), "2 ausgewählt");
    await page.locator("#aniworld-season-options button").filter({ hasText: "Filme" }).click();
    assert.equal(await page.locator("#aniworld-episode-grid .aniworld-episode").count(), 1);
    await page.locator("#aniworld-select-all").click();
    assert.equal(await page.locator("#aniworld-pick-count").textContent(), "3 ausgewählt");
    await page.locator("#aniworld-track-options .is-sub").click();
    await page.waitForFunction(() => sharedPresentation.aniworld.get().current?.translation === "sub");
    assert.equal(await page.locator("#aniworld-pick-count").textContent(), "0 ausgewählt");
    await page.evaluate(() => closeMediaModal("aniworld-detail-modal"));
    slowAniworldDetail = true;
    const awRequest = page.waitForRequest(request => request.url().includes("/api/aniworld/fixture?"));
    await page.locator("#aniworld-results button.aniworld-card").click(); await awRequest;
    await page.evaluate(() => { closeMediaModal("aniworld-detail-modal"); switchTab("home"); });
    await page.waitForTimeout(500);
    assert.equal(await page.evaluate(() => sharedPresentation.aniworld.get().current.episodes.length), 0);
    slowAniworldDetail = false; aniworldFixture = false;
    if (!hadGerman) await page.evaluate(() => { sharedPresentation.providers.get().contentLanguages.delete("de"); syncAniworldNavigationVisibility(); });

    movieSubscriptions = [{ key: "tmdb:321", tmdb_id: 321, source_slug: "movie-fixture", title: "Movie Fixture", year: "2024", target_quality: "best", cleanup_mode: "keep", status: "upgrade" }];
    socket.send(JSON.stringify({ type: "movie_subscriptions_update", movie_subscriptions: movieSubscriptions }));
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => switchTab("filme"));
      await page.locator("#movie-subscriptions-list .subscription-card").click();
      await page.locator('#movie-subscription-modal label:has(input[name="movie-target-quality"][value="1080p"])').click();
      await page.locator("#movie-upgrade-enabled").uncheck();
      await page.locator("#movie-subscription-save").click();
      await page.waitForFunction(() => document.getElementById("movie-subscription-modal").classList.contains("hidden"));
      assert.equal(movieSubscriptionWrites.length, i + 1);
      assert.deepEqual(movieSubscriptionWrites[i], { source_slug: "movie-fixture", title: "Movie Fixture", year: "2024", tmdb_id: 321, cover_url: "", target_quality: "1080p", cleanup_mode: "keep", upgrade_enabled: false });
      await page.locator("#movie-subscriptions-check").click();
      await page.waitForFunction(() => !document.getElementById("movie-subscriptions-check").disabled);
      assert.equal(movieSubscriptionChecks, i + 1);
      await page.evaluate(() => switchTab("home"));
    }

    await page.evaluate(() => switchTab("filme"));
    movieSubscriptionMode = "error";
    await page.locator("#movie-subscriptions-check").click();
    await page.locator('#movie-subscriptions-list [data-view-state="error"]').waitFor();
    assert.match(await page.locator("#movie-subscriptions-list").textContent(), /movie check offline/);
    movieSubscriptionMode = "ready";
    await page.locator("#movie-subscriptions-check").click();
    await page.waitForFunction(() => !document.querySelector('#movie-subscriptions-list [data-view-state="error"]'));
    slowMovieSubscriptionSave = true;
    await page.locator("#movie-subscriptions-list .subscription-card").click();
    await page.locator("#movie-subscription-save").click();
    await page.waitForFunction(() => document.getElementById("movie-subscription-save").disabled);
    await page.keyboard.press("Escape");
    const closedMovieRule = await page.locator("#movie-subscription-modal").innerHTML();
    await page.waitForTimeout(500);
    assert.equal(await page.locator("#movie-subscription-modal").innerHTML(), closedMovieRule);
    slowMovieSubscriptionSave = false;
    await page.locator("#movie-subscriptions-list .subscription-card").click();
    await page.locator("#movie-subscription-remove").click();
    await page.waitForFunction(() => document.getElementById("movie-subscription-modal").classList.contains("hidden"));
    assert.equal(await page.locator("#movie-subscriptions-list .subscription-card").count(), 0);

    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => switchTab("kalender"));
      await page.locator(".calendar-entry").first().waitFor();
      assert.equal(await page.locator(".calendar-entry").count(), 2);
      await page.locator('[data-calendar-language="1"]').click();
      assert.equal(await page.locator(".calendar-entry").count(), 1);
      await page.locator('[data-calendar-language="all"]').click();
      await page.locator('[data-calendar-status="upcoming"]').click();
      assert.match(await page.locator(".calendar-entry").textContent(), /Calendar Beta/);
      await page.locator('[data-calendar-status="all"]').click();
      await page.locator("#calendar-search").fill("Alpha");
      assert.equal(await page.locator(".calendar-entry").count(), 1);
      await page.locator("#calendar-search").fill("missing");
      assert.equal(await page.locator("#calendar-days").isVisible(), false);
      await page.locator("#calendar-search").fill("");
      await page.locator('[data-calendar-view="week"]').click();
      assert.equal(await page.locator(".calendar-day").count(), 7);
      await page.locator("#calendar-today").click();
      await page.evaluate(() => switchTab("home"));
    }

    await page.evaluate(() => switchTab("kalender"));
    calendarMode = "error";
    await page.evaluate(() => sharedPresentation.calendar.refresh());
    assert.equal(await page.locator(".calendar-entry").count(), 2);
    assert.match(await page.locator("#calendar-range").textContent(), /Aktualisierung fehlgeschlagen/);
    calendarMode = "slow";
    await page.evaluate(() => { void sharedPresentation.calendar.refresh(); switchTab("home"); });
    const closedCalendar = await page.locator("#tab-kalender").innerHTML();
    await page.waitForTimeout(500);
    assert.equal(await page.locator("#tab-kalender").innerHTML(), closedCalendar);
    calendarMode = "ready";
    await page.evaluate(() => { switchTab("kalender"); return sharedPresentation.calendar.refresh(); });
    socket.send(JSON.stringify({ type: "watchlist_update", watchlist: [{ base_slug: "serienstream:calendar-alpha", title: "Calendar Alpha" }], health: {} }));
    await page.waitForFunction(() => document.getElementById("calendar-upcoming-count").textContent === "1");
    await page.locator("#calendar-subscribed").click();
    assert.equal(await page.locator(".calendar-entry").count(), 1);
    socket.send(JSON.stringify({ type: "watchlist_update", watchlist: [], health: {} }));
    await page.waitForFunction(() => document.getElementById("calendar-days").hidden);
    await page.locator("#calendar-subscribed").click();
    assert.equal(await page.locator(".calendar-entry").count(), 2);

    // Advanced policy persists friendly schedules without replacing in-flight edits.
    await page.evaluate(() => switchTab("einstellungen"));
    await page.locator('[data-settings-target="settings-automation"]').click();
    await page.locator('.smart-schedule-choice:has(input[name="weekday-mode"][value="night"])').click();
    await page.locator('.smart-schedule-choice:has(input[name="weekend-mode"][value="same"])').click();
    await page.locator("#max-parallel-downloads").selectOption("3");
    await page.locator("#max-bandwidth-mbps").fill("7.5");
    await page.evaluate(() => sharedPresentation.automation.save());
    assert.equal(policyWrites.length, 1);
    assert.equal(policyWrites[0].weekday_window_start, 0);
    assert.equal(policyWrites[0].weekday_window_end, 6);
    assert.equal(policyWrites[0].weekend_window_end, 6);
    assert.equal(policyWrites[0].max_parallel_downloads, 3);
    assert.equal(policyWrites[0].max_bandwidth_mbps, 7.5);
    policyMode = "slow";
    await page.evaluate(() => { document.getElementById("settings-saved-status").textContent = ""; void sharedPresentation.automation.refresh(); });
    await page.locator("#max-bandwidth-mbps").fill("11");
    await page.waitForTimeout(550);
    assert.equal(await page.locator("#max-bandwidth-mbps").inputValue(), "11");
    const beforePolicy = calls.filter(path => path === "/api/automation/policy").length;
    await page.evaluate(() => sharedPresentation.automation.refresh());
    assert.equal(calls.filter(path => path === "/api/automation/policy").length, beforePolicy);
    await page.evaluate(() => { document.getElementById("settings-saved-status").textContent = ""; void sharedPresentation.automation.refresh(); });
    await page.locator('[data-settings-target="settings-general"]').click();
    await page.waitForTimeout(550);
    assert.equal(await page.locator("#max-bandwidth-mbps").inputValue(), "11");
    await page.evaluate(() => switchTab("home"));
    policyMode = "ready";

    // Storage actions use fixture routes only; no real files are touched.
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => switchTab("einstellungen"));
      await page.locator('[data-settings-target="settings-storage"]').click();
      await page.waitForFunction(() => document.getElementById("storage-live-state").textContent.includes("Volume"));
      await page.locator("#storage-location-label").fill("Fixture Location");
      await page.locator("#storage-location-path").fill("/fixture-only");
      await page.locator("#storage-location-save").click();
      await page.waitForLoadState("networkidle");
      assert.equal(storageSaves, i + 1);
      if (i < 2) await page.evaluate(() => switchTab("home"));
    }
    await page.locator("#storage-scan").click();
    await page.locator("[data-storage-move]").waitFor();
    await page.locator("[data-storage-move]").click();
    await page.locator("#storage-move-modal").waitFor({ state: "visible" });
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#storage-move-confirm").click();
    await page.waitForFunction(() => document.querySelector('[data-storage-move]')?.dataset.moveJobLocked);
    assert.equal(storageMoves, 1);
    assert.equal(await page.locator("[data-storage-cleanup]").isDisabled(), true);
    storageHistory = storageJobs.map(job => ({ ...job, status: "completed", moved_bytes: 1024 })); storageJobs = [];
    await page.waitForFunction(() => document.querySelector('.storage-move-job.is-completed'));
    await page.waitForFunction(() => !document.querySelector('[data-storage-move]')?.disabled);
    storageMode = "error";
    await page.locator("#storage-refresh").click();
    await page.getByText("Live-Abfrage fehlgeschlagen", { exact: false }).waitFor();
    storageMode = "slow";
    await page.locator("#storage-refresh").click();
    await page.evaluate(() => switchTab("home"));
    await page.waitForTimeout(550);
    const storageCalls = calls.filter(path => path.startsWith("/api/storage/")).length;
    await page.waitForTimeout(2700);
    assert.equal(calls.filter(path => path.startsWith("/api/storage/")).length, storageCalls);

    // Movie hero controls mount once; leaving discovery removes its rotation timer.
    const movieHeroResult = await page.evaluate(() => {
      const originalSet = window.setInterval, originalClear = window.clearInterval;
      const timers = new Set();
      window.setInterval = (callback, ms, ...args) => {
        const id = originalSet(callback, ms, ...args);
        if (ms === 9000) timers.add(id);
        return id;
      };
      window.clearInterval = id => { timers.delete(id); originalClear(id); };
      let single = true, cleaned = true;
      try {
        sharedPresentation.movieState.category = "new";
        sharedPresentation.movieState.results = Array.from({ length: 3 }, (_, id) => ({ slug: `hero-${id}`, title: `Hero ${id}`, year: new Date().getFullYear() }));
        for (let i = 0; i < 3; i++) {
          switchTab("filme", { autoLoad: false });
          refreshMovieFeatureCandidates();
          const count = document.getElementById("movie-feature-count");
          const before = Number(count.textContent.split(" / ")[0]);
          document.getElementById("movie-feature-next").click();
          const after = Number(count.textContent.split(" / ")[0]);
          single &&= after === before % 3 + 1;
          switchTab("home");
          cleaned &&= timers.size === 0;
        }
      } finally { window.setInterval = originalSet; window.clearInterval = originalClear; }
      return { single, cleaned };
    });
    assert.deepEqual(movieHeroResult, { single: true, cleaned: true });

    // Personal request history survives an empty queue and remounts do not duplicate loads.
    const profileCalls = calls.filter(path => path === "/api/me/profile-summary").length;
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => switchTab("profil"));
      await page.getByText("Persistent Request", { exact: true }).waitFor();
      await page.waitForLoadState("networkidle");
      assert.equal(calls.filter(path => path === "/api/me/profile-summary").length, profileCalls + i + 1);
      await page.locator("#profile-household-open").click();
      await page.locator(".household-user").waitFor();
      await page.locator("#household-close").click();
      await page.evaluate(() => switchTab("home"));
    }
    profileMode = "error";
    await page.evaluate(() => switchTab("profil"));
    await page.getByText("Profil konnte nicht geladen werden", { exact: true }).waitFor();
    profileMode = "ready";
    await page.locator('#profile-recent-downloads button').click();
    await page.getByText("Persistent Request", { exact: true }).waitFor();
    householdSlow = true;
    await page.locator("#profile-household-open").click();
    await page.locator("#household-close").click();
    await page.waitForTimeout(450);
    assert.equal(await page.locator("#household-panel").evaluate(el => el.hidden), true);
    await page.evaluate(() => switchTab("home"));
    profileMode = "slow";
    await page.evaluate(() => { switchTab("profil"); switchTab("home"); });
    await page.waitForTimeout(450);
    assert.equal(await page.locator("#tab-home").evaluate(el => el.classList.contains("active")), true);
    await page.setViewportSize({ width: 390, height: 844 });
    releaseMode = "ready";
    await page.evaluate(() => switchTab("releases"));
    await page.getByRole("heading", { name: "Fixture Movie", exact: true }).waitFor();
    socket.close({ code: 1008, reason: "fixture session expired" });
    await page.waitForFunction(() => document.body.classList.contains("login-open"));
    await page.waitForTimeout(3000);
    assert.equal(sockets, 2);
    await page.locator("#login-username").fill("test");
    await page.locator("#login-password").fill("fixture-only");
    await Promise.all([page.waitForEvent("load"), page.locator("#login-submit").click()]);
    await page.waitForLoadState("networkidle");
    await page.waitForFunction(() => !document.body.classList.contains("login-open"));
    assert.equal(sockets, 3);
    await page.evaluate(() => appendLog("Frontend checkpoint OK", "info"));
    assert.match(await page.locator("#log-console").textContent(), /Frontend checkpoint OK/);
    assert.deepEqual(missing, []);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, sockets, releaseRequests: calls.filter(path => path === "/api/releases").length, errors, missing }));
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
