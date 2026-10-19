// Integrated Home feed: real DOM, poster fallback, feedback and source handoff.
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
        assert.match(await card.getAttribute("title"), /Drama.*Quellen suchen/);
        await card.scrollIntoViewIfNeeded();
        await page.waitForFunction(() => [...document.querySelectorAll('#home-discovered-track img')]
          .some(image => image.complete && image.naturalWidth > 0));
        await page.screenshot({ path: resolve(output, `${engine}-${viewport.width}.png`) });
        await card.locator(".home-card-primary-action").click();
        await page.waitForFunction(() => document.getElementById("home-search").value === "Unbekannter Favorit 0");
        await page.waitForFunction(() => !document.querySelector('#home-discovered-track .home-card[data-key="tmdb:8000"]'));
        assert.equal(events.length, 1);
        assert.equal(events[0].action, "open");
        assert.equal(events[0].item_key, "movie:tmdb:8000");
        assert.ok(feedCalls >= 2);
        assert.deepEqual(queueWrites, []);
        assert.deepEqual(f.errors, []);
        console.log(JSON.stringify({ engine, width: viewport.width, posterOnlyFeed: true,
          sourceSearch: true, oneOpenEvent: true, postFeedbackRefresh: true }));
      } finally { await f.close(); }
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
