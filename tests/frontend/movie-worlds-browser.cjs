const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page } = run;
    try {
      const requests = [];
      let failNext = false;
      await page.route("**/api/movies?**", async route => {
        const params = new URL(route.request().url()).searchParams;
        requests.push(Object.fromEntries(params));
        if (failNext) {
          failNext = false;
          await route.fulfill({ status: 503, json: { detail: "TMDB temporarily unavailable" } });
          return;
        }
        const world = params.get("world"), number = Number(params.get("page") || 1);
        const results = Array.from({ length: 20 }, (_, i) => ({
          slug: `tmdb:${number * 100 + i}`, tmdb_id: number * 100 + i,
          title: `${world || "New"} ${number}-${i}`, year: "1994", rating: 8.4,
          cover_url: "/fixture-art.svg", content_language: "", is_movie: true,
        }));
        await route.fulfill({ json: { results, category: world ? "world" : "new", page: number,
          has_more: number < 2, total_results: 40, sources: [] } });
      });
      await page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="filme"]:visible`).first().click();
      await page.locator("#movie-filter-world").selectOption("disney");
      await page.waitForFunction(() => document.querySelector("#fp-results .result-card-title")?.textContent.includes("disney"));
      assert.ok(requests.some(p => p.world === "disney" && p.language === "de"));
      await page.locator("#movie-filter-period").selectOption("1990s");
      await page.waitForFunction(() => !fixtureApp.discovery.movieState.loadingMore);
      assert.equal(requests.at(-1).period, "1990s");
      await page.evaluate(() => fixtureApp.discovery.movieBrowse.next());
      assert.equal(requests.at(-1).page, "2");
      assert.equal(requests.at(-1).world, "disney");
      await page.locator("#movie-filter-world").selectOption("marvel");
      await page.waitForFunction(() => document.querySelector("#fp-results .result-card-title")?.textContent.includes("marvel"));
      assert.equal(await page.locator("#fp-results .result-card-title").filter({ hasText: "disney" }).count(), 0);
      await page.evaluate(() => fixtureApp.core.localization.changeLanguage("en"));
      await page.waitForFunction(() => !fixtureApp.discovery.movieState.loadingMore);
      await page.waitForFunction(() => document.querySelector("#genre-count")?.textContent.includes("total"));
      assert.equal(requests.at(-1).language, "en");
      assert.equal(await page.locator("#genre-count").isVisible(), true);
      assert.equal(await page.locator('#movie-filter-world option[value="disney"]').textContent(), "Disney movies");
      assert.equal(await page.locator('#movie-filter-world optgroup').last().getAttribute("label"), "Heroes & universes");
      await page.locator("#movie-filter-world").scrollIntoViewIfNeeded();
      assert.equal(await page.locator("#movie-filter-world").evaluate(el => el.getBoundingClientRect().right <= innerWidth), true);
      await mkdir("artifacts/movie-worlds", { recursive: true });
      await page.screenshot({ path: `artifacts/movie-worlds/${mobile ? "mobile" : "desktop"}.png` });
      await page.locator("#movie-filter-reset").click();
      await page.waitForFunction(() => !fixtureApp.discovery.movieState.loadingMore);
      assert.equal(await page.locator("#movie-filter-world").inputValue(), "");
      assert.equal(await page.locator("#movie-filter-period").inputValue(), "all");
      assert.equal(requests.at(-1).mode, "new");
      failNext = true;
      await page.locator("#movie-filter-world").selectOption("pixar");
      await page.waitForFunction(() => Boolean(fixtureApp.discovery.movieState.loadError));
      assert.equal(await page.locator("#fp-results .result-card").count(), 0);
      await page.locator("#fp-infinite-retry").click();
      await page.waitForFunction(() => document.querySelector("#fp-results .result-card-title")?.textContent.includes("pixar"));
      assert.equal(requests.at(-1).world, "pixar");
      assert.deepEqual(run.errors, []);
    } finally { await run.close(); }
  }
  console.log("Movie worlds: desktop/mobile, filters, pagination, language and reset passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
