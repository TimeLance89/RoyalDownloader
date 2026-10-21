// Integrated Home feed: real DOM, poster fallback and direct movie/series details.
const assert = require("node:assert/strict");
const { mkdirSync } = require("node:fs");
const { resolve } = require("node:path");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  const output = resolve("artifacts/home-discovery");
  mkdirSync(output, { recursive: true });
  for (const engine of ["chromium", "webkit"]) {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const f = await fixture({ engine, viewport, mobile: viewport.width < 1000 });
      try {
        const { page } = f;
        const events = [], queueWrites = [], omitted = new Set();
        let feedCalls = 0;
        const profile = { interactions: 5, confidence: 0.3, updated_at: 1000,
          dimensions: { genres: { Drama: 12 } }, genres: { Drama: 12 }, recent: [] };
        const suggestions = Array.from({ length: 8 }, (_, index) => ({ kind: index % 2 ? "series" : "movie", item: {
          tmdb_id: 8000 + index, slug: `tmdb:${8000 + index}`, base_slug: `tmdb:${8000 + index}`,
          title: `Unbekannter Favorit ${index}`, year: "2026", genres: ["Drama"], rating: 8.2,
          cover_url: "/fixture-art.svg", backdrop_url: "", tmdb_discovery: true, discovery_reason: ["Drama"],
        } }));
        await page.route("**/api/home/discovery", route => {
          feedCalls++;
          return route.fulfill({ json: { available: true, results: suggestions.filter(row => !omitted.has(row.item.tmdb_id)) } });
        });
        await page.route("**/api/tmdb/movie", route => route.fulfill({ json: { movie: { ...suggestions[0].item, details_loaded: true } } }));
        await page.route("**/api/movie/**", route => route.fulfill({ json: { ...suggestions[0].item, hosters: [], availability: { complete: true, state: "unavailable" } } }));
        await page.route("**/api/people/series/8001?**", route => route.fulfill({ json: { ...suggestions[1].item, seasons: [], episode_count: 0, sources: [] } }));
        await page.route("**/api/tmdb/series", route => route.fulfill({ json: { series: {}, pending: [] } }));
        await page.route("**/api/series/jellyfin-status", route => route.fulfill({ json: { configured: false, episodes: {} } }));
        await page.route("**/api/taste/events", async route => {
          const event = route.request().postDataJSON();
          if (event.action === "open") {
            events.push(event);
            omitted.add(Number(event.item_key.split(":").at(-1)));
          }
          await route.fulfill({ json: { profile: { ...profile, updated_at: 1001,
            recent: [{ key: event.item_key, action: event.action, at: Date.now() / 1000 }] } } });
        });
        page.on("request", request => {
          if (request.method() === "POST" && new URL(request.url()).pathname.startsWith("/api/queue")) queueWrites.push(request.url());
        });
        await page.evaluate(profile => {
          fixtureApp.profile.tasteProfile.accept(profile);
          fixtureApp.home.homeData.mount();
          fixtureApp.home.homeData.refreshDiscovery();
        }, profile);
        const track = page.locator("#home-discovered-track");
        const card = track.locator('.home-card[data-key="tmdb:8000"]').first();
        await card.waitFor({ state: "visible" });
        assert.match(await card.getAttribute("title"), /Drama.*Details/);
        await card.scrollIntoViewIfNeeded();
        await page.waitForFunction(() => [...document.querySelectorAll('#home-discovered-track img')]
          .some(image => image.complete && image.naturalWidth > 0));
        await page.screenshot({ path: resolve(output, `${engine}-${viewport.width}.png`) });
        await card.locator(".home-card-primary-action").click();
        await page.locator("#fp-detail-modal").waitFor({ state: "visible" });
        await page.waitForFunction(() => document.getElementById("fp-detail-title").textContent === "Unbekannter Favorit 0");
        assert.equal(await page.locator("#home-search").inputValue(), "");
        await page.locator("#fp-detail-close").click();
        const series = track.locator('.home-card[data-key="tmdb:8001"]').first();
        await series.locator(".home-card-primary-action").click();
        await page.locator("#series-detail-modal").waitFor({ state: "visible" });
        await page.waitForFunction(() => document.getElementById("series-detail-title").textContent === "Unbekannter Favorit 1");
        await page.waitForTimeout(150);
        assert.equal(await page.locator("#home-search").inputValue(), "");
        assert.equal(events.length, 2);
        assert.deepEqual(events.map(event => event.item_key), ["movie:tmdb:8000", "series:tmdb:8001"]);
        assert.ok(feedCalls >= 1);
        assert.deepEqual(queueWrites, []);
        assert.deepEqual(f.errors, []);
        console.log(JSON.stringify({ engine, width: viewport.width, posterOnlyFeed: true,
          directMovieAndSeriesDetails: true, oneOpenEventPerDetail: true }));
      } finally { await f.close(); }
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
