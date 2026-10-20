const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const engine of process.env.ROYAL_BROWSER ? [process.env.ROYAL_BROWSER] : ["chromium", "webkit"]) {
    for (const width of [390, 1440]) {
      const mobile = width < 1000;
      const run = await fixture({ engine, mobile, viewport: { width, height: mobile ? 844 : 1000 } });
      const { page } = run;
      let release = () => {};
      try {
        const movies = Array.from({ length: 80 }, (_, i) => ({
          slug: `library-${i}`, title: `Library Film ${i}`, year: "2020", tmdb_id: 1000 + i,
          cover_url: "/fixture-art.svg", backdrop_url: "/fixture-art.svg", metadata_source: "TMDB", genres: ["Drama"],
        }));
        // A provider listing can have an incorrect year and no TMDB identity.
        // The existing metadata pass must recheck using the resolved identity.
        Object.assign(movies[3], { tmdb_id: null, year: "2025", metadata_source: "Anbieter" });
        const owned = new Set([1000, 1002, 1003]);
        const requests = [];
        let hold = true;
        const gate = new Promise(resolve => { release = resolve; });
        await page.route("**/api/movies?**", route => route.fulfill({ json: { results: movies, page: 1, has_more: false, sources: [] } }));
        await page.route("**/api/tmdb/movie", route => route.fulfill({ json: { movie: { ...movies[0], details_loaded: true } } }));
        await page.route("**/api/tmdb/movies", route => route.fulfill({ json: { movies: {
          "library-3": { ...movies[3], tmdb_id: 1003, year: "2020", metadata_source: "TMDB" },
        } } }));
        await page.route("**/api/movie/**", route => route.fulfill({ json: { ...movies[0], hosters: [], availability: { complete: true, state: "unavailable" } } }));
        await page.route("**/api/jellyfin/matches", async route => {
          const items = route.request().postDataJSON().items;
          requests.push(items);
          if (hold) await gate;
          await route.fulfill({ json: { configured: true, available: true,
            statuses: Object.fromEntries(items.map(item => [item.slug, owned.has(Number(item.tmdb_id)) ? "owned" : "missing"])) } }).catch(() => {});
        });
        await page.evaluate(() => { fixtureApp.home.homeData.get().newMovies.length = 0; });
        const tab = name => page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="${name}"]:visible`).first();
        await tab("filme").click();
        const rows = page.locator("#fp-results .result-card");
        await rows.first().waitFor();
        await page.waitForTimeout(100);
        await rows.first().click();
        await page.locator("#fp-detail-modal").waitFor({ state: "visible" });
        await page.locator("#fp-detail-close").click();
        hold = false;
        release();
        const badge = index => rows.nth(index).locator(".result-card-library-badge");
        await page.waitForFunction(() => [0, 2, 3].every(index => document.querySelectorAll("#fp-results .result-card")[index]
          ?.querySelector(".result-card-library-badge")?.hidden === false));
        assert.equal(await badge(1).isVisible(), false);

        // A Home/background match has no render callback, but must update the
        // same visible movie ribbon and its availability filter immediately.
        owned.add(1001);
        await page.evaluate(() => fixtureApp.integrations.catalogJellyfin.refresh([
          { kind: "movie", item: fixtureApp.discovery.movieState.results[1] },
        ]));
        assert.equal(await badge(1).isVisible(), true);
        assert.equal(await badge(1).textContent(), "In Jellyfin");

        // Fully warm metadata/provider caches must not suppress a library check
        // on return. A movie removed from Jellyfin must lose its old ribbon.
        await tab("home").click();
        owned.delete(1002);
        const before = requests.length;
        await tab("filme").click();
        await page.waitForFunction(() => document.querySelectorAll("#fp-results .result-card")[2]
          ?.querySelector(".result-card-library-badge")?.hidden === true);
        assert.ok(requests.length > before, "cached tab return rechecks the library");
        await rows.last().scrollIntoViewIfNeeded();
        await page.waitForFunction(() => document.querySelector("#fp-results .result-card").classList.contains("is-catalog-placeholder"));
        await rows.first().scrollIntoViewIfNeeded();
        await page.waitForFunction(() => document.querySelector("#fp-results .result-card .result-card-library-badge")?.hidden === false);
        assert.equal(await badge(1).isVisible(), true);
        assert.equal(await badge(2).isVisible(), false);
        assert.deepEqual(run.errors, []);
        assert.ok(requests.flat().every(item => item.media_type === "movie"));
        assert.ok(requests.flat().some(item => item.slug === "movie:library-3" && item.tmdb_id === 1003 && item.year === "2020"));
        console.log(JSON.stringify({ engine, width, closeKeepsCatalogChecks: true, backgroundUpdates: true, cachedReturn: true, offscreenRestore: true, enrichedIdentity: true }));
      } finally { release(); await run.close(); }
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
