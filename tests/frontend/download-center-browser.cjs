const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { fixture } = require("./performance-fixture.cjs");

const engine = process.env.ROYAL_BROWSER || "chromium";
const output = "artifacts/mobile-download-center";
function snapshot(count = 50) {
  const statuses = ["downloading", "preparing", "waiting_provider", "paused", "failed", "completed", "queued"];
  return { count, groups: count ? [{ name: "The Last of Us", items: Array.from({ length: count }, (_, index) => ({
    job_id: `cinema-${index}`, slug: `cinema-s02e${String(index + 1).padStart(2, "0")}`,
    title: index === 7 ? "Ein außergewöhnlich langer Serien- und Filmtitel mit weiteren Details und einemsehrlangenuntrennbarenWortdamitdasLayoutniemalsüberläuft" : `The Last of Us · S02E${String(index + 1).padStart(2, "0")}`,
    content_language: "de", provider: "SerienStream", hoster: "VOE",
    job_status: statuses[index] || "queued", progress: index === 0 ? 42 : null,
    downloaded_bytes: index === 0 ? 450000000 : 0, total_bytes: index === 0 ? 1070000000 : null,
    speed_bps: index === 0 ? 4500000 : 0, eta_seconds: index === 0 ? 138 : null,
  })) }] : [], activity: { active_downloads: count ? 1 : 0, pending_downloads: Math.max(0, count - 1) }, providers: {} };
}
async function seed(page, payload) {
  await page.evaluate(payload => {
    fixtureApp.discovery.seriesState.cache.cinema = { base_slug: "cinema", title: "The Last of Us", backdrop_url: "/fixture-art.svg" };
    fixtureApp.core.actions.renderQueue(payload);
    fixtureApp.core.actions.setDownloadState(payload.count ? "active" : "idle", payload.count ? "Download läuft" : "Bereit", document.getElementById("queue-summary")?.textContent || "Downloadplan", payload.count ? 42 : null);
  }, payload);
}
async function box(page, selector) { return page.locator(selector).boundingBox(); }

(async () => {
  await mkdir(output, { recursive: true });
  // Same deterministic data, original HTML/CSS/JS and real browser: reproducible before rendering.
  if (process.env.ROYAL_DOWNLOAD_BASELINE) {
    for (const width of [390, 1440]) {
      const run = await fixture({ engine, webRoot: process.env.ROYAL_DOWNLOAD_BASELINE, viewport: { width, height: width === 390 ? 844 : 1000 }, mobile: width === 390 });
      try {
        await seed(run.page, snapshot(50));
        await run.page.evaluate(width => width < 821 ? fixtureApp.core.actions.openMobileQueue() : fixtureApp.core.actions.setQueueDockExpanded(true), width);
        await run.page.waitForTimeout(500);
        await run.page.screenshot({ scale: "css", path: `${output}/${engine}-before-${width}.png` });
      } finally { await run.close(); }
    }
  }
  for (const width of [320, 360, 390, 430, 768, 1440]) {
    const mobile = width <= 820;
    const run = await fixture({ engine, viewport: { width, height: mobile ? 844 : 1000 }, mobile });
    const { page } = run;
    const requests = [];
    page.on("request", request => requests.push(new URL(request.url()).pathname));
    try {
      await seed(page, snapshot());
      if (mobile) await page.locator("#mobile-queue-btn").tap();
      else await page.locator("#queue-dock-toggle").click();
      await page.waitForTimeout(450);
      assert.equal(await page.locator("#queue-drawer").getAttribute("aria-hidden"), "false");
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      if (mobile) {
        await page.waitForSelector(".queue-wallpaper img.is-visible");
        assert.equal(await page.locator("#queue-dock").getAttribute("aria-modal"), "true");
        assert.equal(await page.evaluate(() => document.activeElement.id), "mobile-queue-close");
        assert.equal(await page.locator(".queue-wallpaper img").count(), 2);
        const header = await box(page, "#queue-dock .panel-head"), list = await box(page, "#queue-list");
        const stage = await box(page, "#download-stage"), actions = await box(page, ".queue-drawer-actions");
        assert.ok(header.y + header.height <= list.y + 1, "Close and title remain above queue");
        assert.ok(list.y + list.height <= actions.y + 1, "Queue never covers global actions");
        assert.ok(actions.y + actions.height <= stage.y + 1, "Transfer remains below actions");
        assert.ok(stage.y + stage.height <= 844 - 8, "Transfer keeps the bottom safe gutter");
        for (const selector of ["#mobile-queue-close", ".queue-action-btn", ".queue-drawer-actions button"]) {
          for (const button of await page.locator(selector).all()) {
            const rect = await button.boundingBox();
            assert.ok(rect.width >= 43.5 && rect.height >= 43.5, `${selector}: 44px touch targets`);
          }
        }
        for (const row of await page.locator(".queue-item").all()) {
          const status = await row.locator(".queue-item-status").boundingBox();
          const actions = await row.locator(".queue-item-actions").boundingBox();
          assert.ok(status.x + status.width <= actions.x + 1, "Status and actions never overlap");
        }
        await page.locator("#queue-list").evaluate(node => { node.scrollTop = 650; });
        assert.ok(await page.locator("#queue-list").evaluate(node => node.scrollTop > 0));
        await page.locator("#queue-list").evaluate(node => { node.scrollTop = 0; });
      } else {
        assert.equal(await page.locator(".queue-wallpaper").isVisible(), false);
        assert.equal(await page.locator(".queue-mobile-copy").first().isVisible(), false);
      }
      await page.screenshot({ scale: "css", path: `${output}/${engine}-after-${width}.png` });

      // Snapshots, WebSocket-style progress and actions retain nodes, focus and scroll.
      const stable = await page.locator('.queue-item[data-job-id="cinema-0"]').elementHandle();
      const imageRequests = requests.filter(path => path === "/fixture-art.svg").length;
      await page.evaluate(payload => {
        window.queueStableNode = document.querySelector('[data-job-id="cinema-0"]');
        window.queueDomSize = document.getElementById("queue-dock").querySelectorAll("*").length;
        for (let index = 0; index < 30; index++) {
          payload.groups[0].items[0].progress = index;
          fixtureApp.core.actions.renderQueue(payload);
          fixtureApp.core.actions.updateQueueJobProgress("cinema-0", { pct: index, speed_bps: 5000000 });
        }
      }, snapshot());
      assert.equal(await page.evaluate(() => queueStableNode === document.querySelector('[data-job-id="cinema-0"]')), true);
      assert.equal(await page.evaluate(() => queueDomSize === document.getElementById("queue-dock").querySelectorAll("*").length), true);
      assert.equal(requests.filter(path => path === "/fixture-art.svg").length, imageRequests, "No image reload on progress updates");
      await stable.dispose();

      await page.evaluate(() => fixtureApp.core.actions.renderQueueHistory(Array.from({ length: 500 }, (_, index) => ({ job_id: `history-${index}`, title: `Historie ${index}`, status: index ? "completed" : "failed", error: index ? "" : "Quelle nicht verfügbar" }))));
      assert.equal(await page.locator(".queue-history-item").count(), 0, "Closed history creates no rows");
      await page.locator(".queue-history-panel summary").click();
      await page.waitForFunction(() => document.querySelectorAll(".queue-history-item").length === 500);
      await page.locator(".queue-history-panel summary").click();

      const calls = [];
      await page.route("**/api/queue/jobs/**", async route => {
        calls.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() });
        await route.fulfill({ json: { queue: snapshot(8) } });
      });
      await page.route("**/api/queue/history", route => route.fulfill({ json: { jobs: [] } }));
      for (const [jobId, label, endpoint, direction] of [
        ["cinema-1", "nach oben", "move", "up"], ["cinema-1", "nach unten", "move", "down"],
        ["cinema-2", "fortsetzen", "resume"], ["cinema-0", "abbrechen", "cancel"],
      ]) {
        await seed(page, snapshot(8));
        await page.locator(`.queue-item[data-job-id="${jobId}"] button[aria-label$="${label}"]`).click();
        await page.waitForFunction(() => !document.querySelector('.queue-item button:disabled'));
        assert.equal(calls.at(-1).path, `/api/queue/jobs/${jobId}/${endpoint}`);
        if (direction) assert.equal(calls.at(-1).body.direction, direction);
      }
      await page.evaluate(() => fixtureApp.core.actions.renderQueueHistory([{ job_id: "retry", title: "Fehler", status: "failed" }]));
      await page.locator(".queue-history-panel summary").click();
      await page.locator(".queue-retry-btn").click();
      assert.equal(calls.at(-1).path, "/api/queue/jobs/retry/retry");
      await page.locator(".queue-history-panel summary").click();

      if (mobile) {
        // Unknown progress, source activity, failure and reduced motion.
        await page.evaluate(() => fixtureApp.core.actions.setDownloadState("active", "Quelle wird geprüft", "1 aktiv", null));
        assert.equal(await page.locator("#download-stage .progress-bar").getAttribute("aria-valuenow"), null);
        assert.equal(await page.locator("#download-stage").getAttribute("data-progress"), "unknown");
        await page.emulateMedia({ reducedMotion: "reduce" });
        assert.equal(await page.locator("#progress-fill").evaluate(node => getComputedStyle(node).animationName), "none");

        // Failed backdrop falls back to poster. A delayed old image cannot replace newer content.
        await page.evaluate(() => { fixtureApp.discovery.seriesState.cache.cinema = { backdrop_url: "/missing.jpg", cover_url: "/fixture-art.svg?poster" }; });
        await seed(page, snapshot(1));
        await page.evaluate(() => { fixtureApp.discovery.seriesState.cache.cinema = { backdrop_url: "/missing.jpg", cover_url: "/fixture-art.svg?poster" }; fixtureApp.core.actions.renderQueue({ ...fixtureApp.core.state.queue }); });
        await page.waitForFunction(() => document.querySelector(".queue-wallpaper img.is-visible")?.src.includes("poster"));
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        await page.route("**/late.svg", async route => { await gate; await route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="300"><rect width="500" height="300" fill="red"/></svg>' }).catch(() => {}); });
        await page.evaluate(() => { fixtureApp.discovery.seriesState.cache.cinema = { backdrop_url: "/late.svg" }; fixtureApp.core.actions.renderQueue({ ...fixtureApp.core.state.queue }); });
        await page.waitForTimeout(100);
        await page.evaluate(() => { fixtureApp.discovery.seriesState.cache.cinema = { backdrop_url: "/fixture-art.svg?new" }; fixtureApp.core.actions.renderQueue({ ...fixtureApp.core.state.queue }); });
        await page.waitForFunction(() => document.querySelector(".queue-wallpaper img.is-visible")?.src.includes("new"));
        release();
        await page.waitForTimeout(200);
        assert.ok(await page.locator(".queue-wallpaper img.is-visible").evaluate(node => node.src.includes("new")));
        await page.evaluate(() => { delete fixtureApp.discovery.seriesState.cache.cinema; fixtureApp.core.actions.renderQueue({ ...fixtureApp.core.state.queue }); });
        assert.equal(await page.locator(".queue-wallpaper img.is-visible").count(), 0);

        await seed(page, snapshot(150));
        await page.setViewportSize({ width, height: 420 });
        assert.ok(await page.locator("#download-stage").isVisible());
        await page.locator(".queue-drawer-main").evaluate(node => { node.scrollTop = node.scrollHeight; });
        await page.locator("#queue-clear").scrollIntoViewIfNeeded();
        const short = await box(page, "#queue-clear"), transfer = await box(page, "#download-stage");
        assert.ok(short.y + short.height <= transfer.y + 1, "Short screen can reach global actions above transfer");
        await page.setViewportSize({ width, height: 844 });
        await seed(page, snapshot(0));
        await page.locator("#cancel-btn").evaluate(node => { node.disabled = false; node.focus(); });
        await page.keyboard.press("Tab");
        assert.equal(await page.evaluate(() => document.activeElement.id), "mobile-queue-close", "Focus remains in sheet");
        await page.locator("#mobile-queue-close").tap();
        assert.equal(await page.locator("#queue-drawer").getAttribute("aria-hidden"), "true");
        assert.equal(await page.evaluate(() => document.activeElement.id), "mobile-queue-btn");
      }
      assert.ok(!requests.some(path => /\/api\/(tmdb|providers)/.test(path)), "Presentation performs no metadata/provider searches");
      assert.deepEqual(run.errors, []);
      console.log(JSON.stringify({ engine, width, passed: true }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
