const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

async function waitUntil(page, predicate) {
  for (let attempt = 0; attempt < 75; attempt++) {
    if (predicate()) return;
    await page.waitForTimeout(200);
  }
  assert.ok(predicate(), "Background catalog request did not arrive");
}

(async () => {
  for (const width of [390, 1440, 3840]) {
    const mobile = width < 1000;
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile, viewport: { width, height: mobile ? 844 : 1100 } });
    const { page, errors } = run;
    try {
      let failures = 1;
      let initialFailures = 1;
      const requests = [];
      const receivedCounts = [];
      let releaseSecondPage;
      const secondPageGate = new Promise(resolve => { releaseSecondPage = resolve; });
      let releaseSecondPageTail;
      const secondPageTailGate = new Promise(resolve => { releaseSecondPageTail = resolve; });
      const items = Array.from({ length: 66 }, (_, i) => ({
        title: `Pagination Series ${i}`, base_slug: `serienstream:pagination-${i}`,
        sample_slug: `serienstream:pagination-${i}-s01e01`, provider: "serienstream",
        cover_url: "/fixture-art.svg", year: "2026",
      }));
      await page.route("**/api/series?**", async route => {
        const params = new URL(route.request().url()).searchParams;
        const number = Number(params.get("page") || 1);
        const received = Number(params.get("received") || 0);
        requests.push(number);
        if (number === 2) receivedCounts.push(received);
        if (number === 1 && initialFailures > 0) {
          initialFailures--;
          return route.fulfill({ status: 409, json: { detail: { code: "series_catalog_pending", message: "Vorbereitung" } } });
        }
        if (number > 1 && failures > 0) {
          failures--;
          return route.fulfill({ status: 409, json: { detail: { code: "series_catalog_pending", message: "Vorbereitung" } } });
        }
        if (number === 2) {
          if (!received) {
            await secondPageGate;
            return route.fulfill({ json: { results: items.slice(32, 40), page: 2, partial_page: true, has_more: true, sources: [] } });
          }
          await secondPageTailGate;
          return route.fulfill({ json: { results: items.slice(32 + received, 64), page: 2, has_more: true, sources: [] } });
        }
        return route.fulfill({ json: { results: items.slice((number - 1) * 32, number * 32), page: number, has_more: number < 3, sources: [] } });
      });
      await page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="serien"]:visible`).first()[mobile ? "tap" : "click"]();
      await page.waitForFunction(() => document.querySelectorAll("#series-results .result-card").length === 32);
      await page.evaluate(() => { window.originalSeriesCard = document.querySelector("#series-results .result-card"); });
      await waitUntil(page, () => requests.includes(2));
      await page.locator("#series-infinite").scrollIntoViewIfNeeded();
      await page.waitForTimeout(250);
      assert.equal(await page.locator("#series-results .result-card").count(), 32);
      assert.notEqual(await page.locator("#series-infinite").getAttribute("data-state"), "loading");
      releaseSecondPage();
      await page.waitForFunction(() => document.querySelectorAll("#series-results .result-card").length === 40);
      assert.equal(await page.locator("#series-infinite").getAttribute("data-state"), "waiting");
      await waitUntil(page, () => receivedCounts.includes(8));
      releaseSecondPageTail();
      await page.waitForFunction(() => document.querySelectorAll("#series-results .result-card").length === 64);
      await waitUntil(page, () => requests.includes(3));
      await page.waitForTimeout(2500);
      assert.equal(await page.locator("#series-results .result-card").count(), 64);
      await page.locator("#series-infinite").scrollIntoViewIfNeeded();
      await page.waitForFunction(
        () => document.querySelectorAll("#series-results .result-card").length === 66,
        null,
        { timeout: 15000 },
      );
      assert.deepEqual(requests, [1, 1, 2, 2, 2, 3]);
      assert.deepEqual(receivedCounts, [0, 0, 8]);
      assert.equal(await page.evaluate(() => originalSeriesCard === document.querySelector("#series-results .result-card")), true);
      assert.equal(await page.locator("#series-infinite-retry").isVisible(), false);
      assert.deepEqual(errors, []);
      console.log(`series pagination ${width}px: partial page and remaining cards append without another gesture`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
