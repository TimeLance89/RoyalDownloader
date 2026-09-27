const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      let failures = 1;
      const requests = [];
      const items = Array.from({ length: 66 }, (_, i) => ({
        title: `Pagination Series ${i}`, base_slug: `serienstream:pagination-${i}`,
        sample_slug: `serienstream:pagination-${i}-s01e01`, provider: "serienstream",
        cover_url: "/fixture-art.svg", year: "2026",
      }));
      await page.route("**/api/series?**", async route => {
        const number = Number(new URL(route.request().url()).searchParams.get("page") || 1);
        requests.push(number);
        if (number > 1 && failures > 0) {
          failures--;
          return route.fulfill({ status: 409, json: { detail: { code: "series_catalog_pending", message: "Vorbereitung" } } });
        }
        return route.fulfill({ json: { results: items.slice((number - 1) * 32, number * 32), page: number, has_more: number < 3, sources: [] } });
      });
      await page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="serien"]:visible`).first()[mobile ? "tap" : "click"]();
      await page.waitForFunction(() => document.querySelectorAll("#series-results .result-card").length === 32);
      await page.evaluate(() => { window.originalSeriesCard = document.querySelector("#series-results .result-card"); });
      await page.locator("#series-infinite").scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelectorAll("#series-results .result-card").length === 64);
      assert.deepEqual(requests, [1, 2, 2]);
      failures = 3;
      await page.locator("#series-infinite").scrollIntoViewIfNeeded();
      await page.waitForSelector("#series-infinite-retry:visible");
      assert.deepEqual(requests, [1, 2, 2, 3, 3, 3]);
      assert.equal(await page.locator("#series-results .result-card").count(), 64);
      await page.evaluate(() => { window.dispatchEvent(new Event("scroll")); window.dispatchEvent(new Event("resize")); });
      await page.waitForTimeout(1000);
      assert.equal(requests.length, 6);
      await page.locator("#series-infinite-retry")[mobile ? "tap" : "click"]();
      await page.waitForFunction(() => document.querySelectorAll("#series-results .result-card").length === 66);
      assert.deepEqual(requests, [1, 2, 2, 3, 3, 3, 3]);
      assert.equal(await page.evaluate(() => originalSeriesCard === document.querySelector("#series-results .result-card")), true);
      assert.equal(await page.locator("#series-infinite-retry").isVisible(), false);
      assert.deepEqual(errors, []);
      console.log(`series pagination ${mobile ? "mobile" : "desktop"}: automatic recovery, bounded retries, manual recovery, retained cards passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
