const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const width of [1440, 390, 320]) {
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile: width < 600, viewport: { width, height: 1000 } });
    const { page } = run;
    try {
      const opened = [];
      await page.route("**/api/watchlist/open", async route => {
        opened.push(route.request().postDataJSON().base_slug);
        await route.fulfill({ json: { base_slug: "rookie", title: "The Rookie", seasons: [] } });
      });
      await page.route("**/subscription-art/*", route => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith("broken")) return route.fulfill({ status: 404, body: "" });
        const color = path.endsWith("rookie") ? "#32677c" : "#7e5440";
        return route.fulfill({ contentType: "image/svg+xml", body: `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="240"><rect width="160" height="240" fill="${color}"/><circle cx="80" cy="90" r="45" fill="#e5ce99"/><path d="M10 240Q20 135 80 150Q145 135 150 240" fill="#131a25"/></svg>` });
      });
      await page.evaluate(() => {
        fixtureApp.core.actions.switchTab("serien");
        window.summaryItems = [
          { base_slug: "rookie", title: "The Rookie", cover_url: "/subscription-art/rookie", backdrop_url: "/subscription-art/unused", download_mode: "latest", status: "upcoming", upcoming_count: 1 },
          { base_slug: "silo", title: "Silo", cover_url: "/subscription-art/broken", backdrop_url: "/subscription-art/silo", download_mode: "all", status: "queued", new_count: 2, queued_count: 2 },
          { base_slug: "missing", title: "House of the Dragon – Ein sehr langer Titel für kleine Bildschirme", cover_url: "/subscription-art/broken", download_mode: "all", status: "blocked", last_error: "Quelle vorübergehend nicht erreichbar" },
          { base_slug: "plain", title: "Lucky", download_mode: "all", status: "current" },
        ];
        fixtureApp.subscriptions.subscriptions.accept({ watchlist: summaryItems });
      });
      const cards = page.locator("#series-subscriptions-list .subscription-card");
      await cards.first().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => {
        const images = [...document.querySelectorAll("#series-subscriptions-list img")];
        return images.length === 2 && images.every(image => image.complete && image.naturalWidth > 0);
      });
      assert.equal(await cards.count(), 4);
      assert.match(await page.locator("#series-subscriptions-count").innerText(), /4 Serien/);
      assert.match(await cards.nth(1).locator("img").getAttribute("src"), /silo$/);
      assert.equal(await cards.nth(2).locator("img").count(), 0, "a failed poster falls back to the visible monogram");
      assert.equal(await cards.nth(2).locator(".subscription-monogram").innerText(), "HO");
      assert.match(await cards.nth(1).innerText(), /2 in der Queue/);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "no page overflow");
      assert.ok(await cards.evaluateAll(items => items.every(item => item.getBoundingClientRect().height >= 96)), "usable poster and touch target height");
      await cards.last().focus();
      assert.ok(await page.locator("#series-subscriptions-list").evaluate(node => node.scrollLeft > 0 || node.scrollWidth <= node.clientWidth), "keyboard focus reveals offscreen subscriptions");
      await cards.first().focus();
      await cards.first().blur();
      await mkdir("artifacts/subscription-summary", { recursive: true });
      await page.locator(".series-subscriptions").screenshot({ path: `artifacts/subscription-summary/${process.env.ROYAL_BROWSER || "chromium"}-${width}.png`, scale: "css" });
      await cards.first().press("Enter");
      await page.waitForFunction(() => document.getElementById("series-detail-title")?.textContent.includes("The Rookie"));
      assert.deepEqual(opened, ["rookie"], "one activation opens the existing subscription detail endpoint");
      await page.evaluate(() => fixtureApp.subscriptions.subscriptions.accept({ watchlist: [] }));
      assert.match(await page.locator("#series-subscriptions-list").innerText(), /Noch keine Abos/);
      assert.deepEqual(run.errors, []);
      console.log(JSON.stringify({ engine: process.env.ROYAL_BROWSER || "chromium", width, posters: true, fallback: true, details: true }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
