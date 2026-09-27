// Real application, deterministic catalog/artwork and no external services.
const { createServer } = require("node:http");
const { readFile } = require("node:fs/promises");
const { resolve, extname, sep } = require("node:path");
const playwright = require(process.env.ROYAL_PLAYWRIGHT || "playwright");
const defaultWeb = resolve(process.env.ROYAL_WEB_ROOT || resolve(__dirname, "../../web"));

async function fixture({ viewport = { width: 1440, height: 1000 }, mobile = false, rate = 1, engine = "chromium", webRoot = defaultWeb, externalFonts = false } = {}) {
  const web = resolve(webRoot);
  const server = createServer(async (req, res) => {
    const path = resolve(web, `.${new URL(req.url, "http://local").pathname.replace(/\/$/, "/index.html")}`);
    if (!path.startsWith(web + sep)) return res.writeHead(403).end();
    try {
      res.setHeader("Content-Type", { ".js": "text/javascript", ".css": "text/css", ".html": "text/html" }[extname(path)] || "application/octet-stream");
      res.end(await readFile(path));
    } catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await playwright[engine].launch({ headless: true });
  const context = await browser.newContext({ viewport, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: mobile ? 3 : 1 });
  try {
  const page = await context.newPage();
  if (process.env.ROYAL_SCROLLEND_FALLBACK === '1') await page.addInitScript(() => {
    window.addEventListener('scrollend', event => event.stopImmediatePropagation(), true);
  });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const cdp = engine === "chromium" ? await context.newCDPSession(page) : null;
  if (cdp) { await cdp.send("Emulation.setCPUThrottlingRate", { rate }); await cdp.send("Performance.enable"); }
  const user = { id: "performance-fixture", display_name: "Performance", role: "admin" };
  await page.routeWebSocket("**/ws", () => {});
  await page.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (externalFonts && ['fonts.googleapis.com', 'fonts.gstatic.com'].includes(url.hostname)) return route.continue();
    if (url.hostname !== "127.0.0.1") return route.fulfill({ contentType: "text/css", body: "" });
    if (url.pathname === "/fixture-art.svg") return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="780" height="440"><defs><linearGradient id="g"><stop stop-color="#162844"/><stop offset="1" stop-color="#88533a"/></linearGradient></defs><path fill="url(#g)" d="M0 0h780v440H0z"/><circle fill="#bea172" cx="550" cy="160" r="90"/></svg>' });
    if (!url.pathname.startsWith("/api/")) return route.continue();
    let data = {};
    if (url.pathname.startsWith("/api/auth/")) data = { configured: true, authenticated: true, user, users: [user] };
    if (url.pathname === "/api/setup/status") data = { required: false };
    if (url.pathname === "/api/config") data = { save_path: "", series_path: "" };
    if (url.pathname === "/api/me/household") data = { users: [user], current_user_id: user.id };
    if (url.pathname === "/api/taste/profile") data = { profile: { interactions: 5 } };
    if (url.pathname === "/api/v1/capabilities") data = { build: "fixture" };
    if (url.pathname === "/api/movies" || url.pathname === "/api/series") data = { results: [], sources: [] };
    if (url.pathname === "/api/queue") data = { count: 0, groups: [], activity: {}, providers: {} };
    if (url.pathname === "/api/watchlist") data = { watchlist: [] };
    if (url.pathname === "/api/movie-subscriptions") data = { movie_subscriptions: [] };
    if (url.pathname === "/api/modules") data = { modules: [] };
    if (url.pathname.startsWith("/api/movie/")) data = { movie: { slug: url.pathname.split("/").pop(), title: "Performance Detail", hosters: [], streams: [] } };
    await route.fulfill({ json: data });
  });
  await page.addInitScript(() => {
    performance.setResourceTimingBufferSize(2000);
    window.perfSample = { longTasks: [], lcp: 0, events: [] };
    for (const type of ["longtask", "largest-contentful-paint", "event"]) {
      if (!PerformanceObserver.supportedEntryTypes.includes(type)) continue;
      new PerformanceObserver(list => {
        for (const e of list.getEntries()) {
          if (type === "longtask") perfSample.longTasks.push({ start: e.startTime, duration: e.duration });
          if (type === "largest-contentful-paint") perfSample.lcp = e.startTime;
          if (type === "event") perfSample.events.push({ name: e.name, duration: e.duration });
        }
      }).observe({ type, buffered: true, ...(type === "event" ? { durationThreshold: 16 } : {}) });
    }
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: "networkidle" });
  await page.waitForSelector("#user-menu", { state: "attached" });
  await page.waitForFunction(() => document.querySelector("#setup-wizard") && !document.querySelector("#setup-wizard").classList.contains("is-open") && !document.getElementById("royal-loader"));
  await page.evaluate(async () => {
    const { application } = await import(document.querySelector('script[type="module"]').src);
    const { HOME_RAIL_CATALOG } = await import("/js/features/home/layout-model.js");
    window.fixtureApp = application;
    application.home.homeData.unmount();
    application.home.hero.unmount();
    application.home.recommendations.unmount();
    window.fixtureEntries = Array.from({ length: 24 }, (_, id) => ({ kind: "movie", item: {
      slug: `performance-${id}`, title: `Royal Performance ${String(id + 1).padStart(2, "0")}`, year: "2026", rating: 7.8,
      cover_url: "/fixture-art.svg", backdrop_url: "/fixture-art.svg", genres: ["Drama"], hosters: [],
    } }));
    application.home.homeData.get().newMovies.push(...fixtureEntries.map(e => e.item));
    for (const entry of fixtureEntries) application.discovery.movieState.moviesCache[entry.item.slug] = entry.item;
    window.renderFixture = (all = false) => {
      const start = performance.now();
      const visible = new Set(["personal", "top", "series", "genre", "explore", "gems", "fresh"]);
      for (const rail of HOME_RAIL_CATALOG) {
        const track = document.getElementById(rail.trackId);
        if (!all && !visible.has(rail.id)) continue;
        track.closest(".home-rail")?.classList.remove("home-layout-hidden");
        const count = rail.ranked ? 10 : rail.layout === "spotlight" ? 7 : 16;
        const entries = fixtureEntries.slice(0, count);
        track.dataset.fixtureLogicalCount = String(count);
        application.home.rows(rail.trackId, entries, { ranked: !!rail.ranked, layout: rail.layout || "rail" });
      }
      return performance.now() - start;
    };
  });
  return { browser, page, cdp, errors, async close() { await browser.close(); await new Promise(resolve => server.close(resolve)); } };
  } catch (error) {
    await browser.close(); await new Promise(resolve => server.close(resolve)); throw error;
  }
}

async function swipe(page, cdp, selector, dx, dy = 0, { release = true, start = true } = {}) {
  const box = await page.locator(selector).boundingBox();
  const viewport = page.viewportSize();
  const x = Math.min(viewport.width - 45, box.x + (dx < 0 ? Math.min(box.width - 45, viewport.width - 65) : 45));
  const y = Math.max(90, Math.min(viewport.height - 70, box.y + box.height / 2));
  if (!cdp) throw new Error("Native continuous touch injection requires Chromium CDP; WebKit uses its separate coverage contract.");
  if (start) await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  for (let i = 1; i <= 12; i++) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + dx * i / 12, y: y + dy * i / 12 }] });
    await page.waitForTimeout(16);
  }
  if (release) await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}
module.exports = { fixture, swipe };
