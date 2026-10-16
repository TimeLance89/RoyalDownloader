const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      await page.route("**/api/movies?**", route => route.fulfill({ json: {
        results: Array.from({ length: 640 }, (_, index) => ({ slug: `filmpalast:window-${index}`,
          title: `Window Movie ${index}`, year: "2026", cover_url: "/fixture-art.svg" })),
        page: 1, has_more: false, sources: [],
      } }));
      await page.route("**/api/series?**", route => route.fulfill({ json: {
        results: Array.from({ length: 640 }, (_, index) => ({ base_slug: `serienstream:window-${index}`,
          sample_slug: `serienstream:window-${index}-s01e01`, title: `Window Series ${index}`,
          year: "2026", cover_url: "/fixture-art.svg" })),
        page: 1, has_more: false, sources: [],
      } }));
      await page.evaluate(() => {
        fixtureApp.home.homeData.get().newMovies.length = 0;
        fixtureApp.home.homeData.get().discoverySeries.length = 0;
      });
      for (const [tab, id] of [["filme", "fp-results"], ["serien", "series-results"]]) {
        await page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="${tab}"]:visible`).first()[mobile ? "tap" : "click"]();
        const cards = page.locator(`#${id} .result-card`);
        await page.waitForFunction(id => document.querySelectorAll(`#${id} .is-catalog-placeholder`).length > 560, id);
        assert.equal(await cards.count(), 640);
        await cards.first().scrollIntoViewIfNeeded();
        await page.waitForFunction(id => document.querySelector(`#${id} .result-card-title`), id);
        const initialHeight = await page.locator(`#${id}`).evaluate(node => node.getBoundingClientRect().height);
        let maxLive = 0;
        await page.waitForFunction(id => document.querySelector(`#${id} .result-card-poster:not(.is-pending-poster)`)?.complete, id);
        await page.evaluate(id => {
          window.windowTestPoster = document.querySelector(`#${id} .result-card-poster:not(.is-pending-poster)`);
        }, id);
        for (const index of [320, 639, 0]) {
          await cards.nth(index).scrollIntoViewIfNeeded();
          await page.waitForFunction(({ id, index }) => {
            const row = document.querySelectorAll(`#${id} .result-card`)[index];
            return row && !row.classList.contains("is-catalog-placeholder") && row.querySelector(".result-card-title");
          }, { id, index });
          await page.waitForFunction(id => document.querySelectorAll(`#${id} .result-card:not(.is-catalog-placeholder)`).length < 72, id);
          const live = await page.locator(`#${id} .result-card:not(.is-catalog-placeholder)`).count();
          maxLive = Math.max(maxLive, live);
          const posters = await page.locator(`#${id} .result-card-poster`).count();
          assert.ok(live < 72 && posters < 72, `Unbounded card/poster retention: ${live}/${posters}`);
          assert.match(await cards.nth(index).locator(".result-card-title").textContent(), new RegExp(`${index}$`));
          const height = await page.locator(`#${id}`).evaluate(node => node.getBoundingClientRect().height);
          assert.ok(Math.abs(height - initialHeight) < 3, `Scroll height changed: ${initialHeight} -> ${height}`);
          if (index !== 0) assert.equal(await page.evaluate(() => !windowTestPoster.isConnected && !windowTestPoster.getAttribute("src")), true);
        }
        assert.equal(await cards.first().getAttribute("role"), "button");
        await cards.nth(500).focus();
        assert.match(await cards.nth(500).locator(".result-card-title").textContent(), /500$/);
        console.log(JSON.stringify({ passed: true, mobile, tab, catalog: 640, maxObservedLiveCards: maxLive }));
      }
      await page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="filme"]:visible`).first()[mobile ? "tap" : "click"]();
      await page.waitForFunction(() => document.querySelectorAll("#series-results .result-card-poster").length === 0);
      await page.locator("#fp-results .result-card").first().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelector("#fp-results .result-card .result-card-title"));
      assert.deepEqual(errors, []);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
