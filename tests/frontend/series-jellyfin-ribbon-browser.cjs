const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      const series = Array.from({ length: 80 }, (_, index) => ({
        base_slug: `filmpalast:ribbon-${index}`, title: `Series ${index}`, year: "2022", provider: "filmpalast",
        cover_url: "/fixture-art.svg", backdrop_url: "/fixture-art.svg", genres: ["Drama"],
      }));
      Object.assign(series[0], { base_slug: "huhu:1421:modern-family", title: "Modern Family", year: "2009", backdrop_url: "" });
      Object.assign(series[1], { base_slug: "filmpalast:tulsa-king", title: "Tulsa King", backdrop_url: "" });
      Object.assign(series[2], { tmdb_id: 77 });
      const requests = [];
      let holdNext = false, releaseStale, markStaleRequested;
      const staleRequested = new Promise(resolve => { markStaleRequested = resolve; });
      const staleGate = new Promise(resolve => { releaseStale = resolve; });
      await page.route("**/api/series?**", route => route.fulfill({ json: { results: series, page: 1, has_more: false, sources: [] } }));
      await page.route("**/api/tmdb/series", route => route.fulfill({ json: { series: Object.fromEntries(
        route.request().postDataJSON().items.filter(item => [series[0].base_slug, series[1].base_slug].includes(item.base_slug))
          .map(item => [item.base_slug, { tmdb_id: item.base_slug === series[0].base_slug ? 1421 : 153312,
            original_title: item.title, backdrop_url: "/fixture-art.svg", genres: ["Drama"] }]),
      ) } }));
      await page.route("**/api/jellyfin/matches", async route => {
        const items = route.request().postDataJSON().items;
        requests.push(...items);
        if (holdNext) { holdNext = false; markStaleRequested(); await staleGate; }
        await route.fulfill({ json: { configured: true, available: true, statuses: Object.fromEntries(
          items.map(item => [item.slug, [1421, 153312].includes(item.tmdb_id) ? "owned" : "missing"]),
        ) } });
      });
      await page.evaluate(() => { fixtureApp.home.homeData.get().discoverySeries.length = 0; });
      await page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="serien"]:visible`).first()[mobile ? "tap" : "click"]();
      const rows = page.locator("#series-results .result-card");
      await rows.first().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => [...document.querySelectorAll("#series-results .result-card")].slice(0, 2)
        .every(row => row.querySelector(".result-card-library-badge")?.hidden === false));
      assert.ok(requests.some(item => item.title === "Modern Family" && !item.tmdb_id));
      assert.ok(requests.some(item => item.tmdb_id === 1421));
      assert.ok(requests.some(item => item.tmdb_id === 153312));
      assert.equal(await rows.nth(2).locator(".result-card-library-badge").isVisible(), false);
      holdNext = true;
      await page.evaluate(() => {
        const item = fixtureApp.discovery.seriesState.results[2];
        fixtureApp.home.homeData.get().discoverySeries.push({ ...item });
        window.staleLibraryCheck = fixtureApp.integrations.catalogJellyfin.refresh([{ kind: "series", item }]);
      });
      await staleRequested;
      await page.evaluate(() => {
        const item = fixtureApp.discovery.seriesState.results[2];
        fixtureApp.discovery.seriesActions.showSeriesDetail({ ...item, jellyfin_configured: true,
          jellyfin_available: true, episode_count: 1, seasons: [{ season: 1, episodes: [
            { slug: "ribbon-s01e01", season: 1, episode: 1, in_jellyfin: true },
          ] }] }, "ribbon-s01e01");
        fixtureApp.core.actions.closeMediaModal("series-detail-modal");
      });
      releaseStale();
      await page.evaluate(() => window.staleLibraryCheck);
      assert.equal(await rows.nth(2).locator(".result-card-library-badge").isVisible(), true);
      assert.equal(await page.evaluate(() => fixtureApp.home.homeData.get().discoverySeries[0].jellyfin_status), "owned");
      await rows.last().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelector("#series-results .result-card").classList.contains("is-catalog-placeholder"));
      await rows.first().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => [...document.querySelectorAll("#series-results .result-card")].slice(0, 3)
        .every(row => row.querySelector(".result-card-library-badge")?.hidden === false));
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ passed: true, mobile, identityRecheck: true, detailSync: true, offscreenRestore: true }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
