const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    const calls = [];
    let config = { enabled: true, auto_repair: true, notify_changes: false, interval_hours: 12, intensity: "standard" };
    const provider = {
      provider: "filmpalast", label: "Filmpalast", enabled: true, domain: "filmpalast.to", diagnosis: "healthy", running: false,
      contract: { media_types: ["movies", "series"] }, runtime: { state: "healthy" },
      last_check_at: 1000, next_check_at: 45000, last_success_at: 1000, error_rate_24h: 0, average_duration_ms: 120,
      steps: [{ name: "catalog", sample: "movies", ok: true, code: "ok", duration_ms: 120, http_status: 200 }],
      changed: true, active_repair: "fixture-repair", hosters: [],
      repairs: [{ id: "fixture-repair", state: "active", confidence: "high", previous_profile: {}, profile: { title_selector: "h1.media-heading" }, validation: { known_detail_pages: 5, validated_detail_pages: 5 } }],
      history: [{ timestamp: 1000, event: "probe", diagnosis: "healthy", changed: true }],
    };
    try {
      await page.route("**/api/providers/**", async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        const body = request.method() === "GET" ? null : request.postDataJSON();
        calls.push({ path, method: request.method(), body });
        if (path.endsWith("/diagnostics")) return route.fulfill({ json: { config, providers: [provider], summary: { healthy: 1 } } });
        if (path.endsWith("/monitor/config")) { config = body; return route.fulfill({ json: config }); }
        if (path.endsWith("/rollback")) { assert.equal(body.confirmed, true); provider.active_repair = null; provider.repairs[0].state = "rolled_back"; }
        if (path.endsWith("/config")) return route.fallback();
        return route.fulfill({ json: { started: true } });
      });
      if (mobile) {
        await page.locator("#mobile-more-toggle").tap();
        await page.locator('[data-tab="einstellungen"]:visible').tap();
      } else await page.locator("#settings-btn").click();
      await page.locator('[data-settings-open="settings-sources"]:visible').first()[mobile ? "tap" : "click"]();
      const monitor = page.locator("#provider-monitor");
      await monitor.locator('details[data-provider="filmpalast"] > summary').click();
      assert.match(await monitor.textContent(), /Gesund/);
      await monitor.locator('[data-panel="filmpalast-repairs"] > summary').click();
      await monitor.locator('[data-action="rollback"]').click();
      assert.equal(calls.some(call => call.path.endsWith("/rollback")), false);
      await monitor.locator('[data-action="cancel"]').click();
      assert.equal(calls.some(call => call.path.endsWith("/rollback")), false);
      await monitor.locator('[data-action="rollback"]').click();
      await monitor.locator('[data-action="confirm"]').click();
      await page.waitForFunction(() => !document.querySelector('#provider-monitor [data-action="rollback"]'));
      assert.equal(calls.filter(call => call.path.endsWith("/rollback")).length, 1);
      assert.equal(await monitor.locator('[data-panel="filmpalast-repairs"]').evaluate(node => node.open), true);
      await monitor.locator('[data-action="probe"]').click();
      await monitor.locator('[data-action="full"]').click();
      assert.deepEqual(calls.filter(call => call.path.endsWith("/probe")).map(call => call.body.intensity), ["standard", "full"]);
      await monitor.locator('[name="monitor-interval"]').fill("6");
      await monitor.locator('[name="monitor-intensity"]').selectOption("full");
      await monitor.locator('[data-action="save"]').click();
      assert.equal(config.interval_hours, 6);
      assert.equal(config.intensity, "full");
      await monitor.locator('[data-action="all"]').click();
      assert.equal(calls.filter(call => call.path.endsWith("/probe-all")).length, 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.deepEqual(errors, []);
      console.log(`provider monitor ${mobile ? "mobile" : "desktop"}: diagnostics, probe, config, confirmation and rollback passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
