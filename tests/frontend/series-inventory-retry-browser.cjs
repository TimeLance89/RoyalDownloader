const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      const checks = new Map();
      await page.route("**/api/series/jellyfin-status", route => route.fulfill({ json: {
        configured: true, available: true, stale: false, episodes: {},
      } }));
      await page.route("**/api/series/load", route => {
        const body = route.request().postDataJSON();
        const count = (checks.get(body.base_slug) || 0) + (body.defer_checks ? 0 : 1);
        checks.set(body.base_slug, count);
        if (!body.defer_checks && (count < 3 || body.base_slug.endsWith("cancel"))) {
          return route.fulfill({ status: 503, json: { detail: {
            code: "series_details_pending", message: "Serienbestand wird geprüft",
          } } });
        }
        return route.fulfill({ json: {
          title: "Inventory fixture", base_slug: body.base_slug, url: body.sample_slug,
          provider: "filmpalast", episode_count: 1, availability_pending: body.defer_checks,
          jellyfin_configured: true, jellyfin_available: !body.defer_checks,
          jellyfin_pending: body.defer_checks, seasons: [{ season: 1, episodes: [{
            slug: body.sample_slug, season: 1, episode: 1, downloaded: !body.defer_checks,
            content_languages: ["de"],
          }] }],
        } });
      });
      await page.evaluate(() => fixtureApp.discovery.seriesActions.loadSeries({
        title: "Inventory fixture", base_slug: "filmpalast:inventory", sample_slug: "filmpalast:inventory-s01e01",
      }));
      await page.waitForFunction(() => fixtureApp.discovery.seriesState.current?.availability_pending === false);
      assert.equal(checks.get("filmpalast:inventory"), 3);
      assert.equal(await page.locator("#series-detail-modal").isVisible(), true);
      assert.equal(await page.locator("#series-tiles .ep-tile.downloaded").count(), 1);
      await page.evaluate(() => {
        fixtureApp.core.actions.closeMediaModal("series-detail-modal");
        return fixtureApp.discovery.seriesActions.loadSeries({
          title: "Cancelled inventory", base_slug: "filmpalast:cancel", sample_slug: "filmpalast:cancel-s01e01",
        });
      });
      await page.waitForResponse(response => response.url().endsWith("/api/series/load") && response.status() === 503);
      await page.evaluate(() => fixtureApp.core.actions.closeMediaModal("series-detail-modal"));
      const before = checks.get("filmpalast:cancel");
      await page.waitForTimeout(1300);
      assert.equal(checks.get("filmpalast:cancel"), before, "closed details must stop inventory polling");
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ passed: true, mobile, lateInventory: true, cancellation: true }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
