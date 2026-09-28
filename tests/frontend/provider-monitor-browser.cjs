const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const width of [1440, 390, 430]) {
    const mobile = width !== 1440;
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile, viewport: { width, height: width === 430 ? 932 : mobile ? 844 : 1000 } });
    const { page, errors } = run;
    const calls = [];
    let config = { enabled: true, auto_repair: true, notify_changes: false, interval_hours: 12, intensity: "standard" };
    let unavailable = false, failSave = false;
    const service = { service_health: "healthy", user_impact: "none", action_required: false,
      coverage: { movies: "healthy", series: "healthy", anime: "not_configured" }, active_sources: 1, available_video_services: 1, last_check_at: Date.now() / 1000 - 18 * 60,
      sources: { providers: { filmpalast: { availability: "available", impact: "none", action_required: false } }, hosters: { voe: { availability: "available", impact: "none", action_required: false } } } };
    const provider = {
      provider: "filmpalast", label: "Filmpalast", enabled: true, domain: "filmpalast.to", diagnosis: "healthy", running: false,
      contract: { media_types: ["movies", "series"] }, runtime: { state: "healthy" },
      last_check_at: 1000, next_check_at: 45000, last_success_at: 1000, error_rate_24h: 0, average_duration_ms: 120,
      steps: [{ name: "catalog", sample: "movies", ok: true, code: "ok", duration_ms: 120, http_status: 200 }],
      last_error: "The origin web server returned an invalid or incomplete response to Cloudflare", changed: true, active_repair: "fixture-repair", hosters: [],
      repairs: [{ id: "fixture-repair", state: "active", confidence: "high", previous_profile: {}, profile: { title_selector: "h1.media-heading" }, validation: { known_detail_pages: 5, validated_detail_pages: 5 } }],
      history: [{ timestamp: 1000, event: "probe", diagnosis: "healthy", changed: true }],
    };
    const hoster = {
      hoster: "voe", label: "VOE", diagnosis: "degraded", domains: ["voe.example"], providers: ["filmpalast"], running: false,
      contract: { resolver: "extract_stream_url", capabilities: ["embed", "resolver"], browser_fallback: true, probe_mode: "browser_capable" },
      metrics_24h: { attempts: 15, success_rate: .2, median_resolve_ms: 1250 }, metrics_7d: { attempts: 30, success_rate: .5 },
      steps: [{ name: "reachability", ok: true, code: "ok", duration_ms: 25 }, { name: "redirect", ok: true, code: "ok", duration_ms: null }, { name: "resolver", ok: null, code: "browser_fallback_required", duration_ms: 12 }], history: [{ timestamp: 1000, event: "parser_error" }],
      active_repair: null, repairs: [{ id: "hoster-repair", confidence: "high", state: "available", previous_profile: {}, profile: { player_selector: "script#config", player_json_path: ["player", "sources", 0, "url"] }, validation: { known_detail_pages: 5, validated_detail_pages: 5 } }],
    };
    try {
      await page.route("**/api/hosters/**", async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        calls.push({ path, method: request.method(), body: request.method() === "GET" ? null : request.postDataJSON() });
        if (path.endsWith("/activate")) { hoster.active_repair = "hoster-repair"; hoster.repairs[0].state = "active"; }
        if (path.endsWith("/rollback")) { hoster.active_repair = null; hoster.repairs[0].state = "rolled_back"; }
        return route.fulfill({ json: { started: true } });
      });
      await page.route("**/api/providers/**", async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        const body = request.method() === "GET" ? null : request.postDataJSON();
        calls.push({ path, method: request.method(), body });
        if (path.endsWith("/diagnostics")) return route.fulfill({ json: { config, service: unavailable ? { ...service, service_health: "action_required", user_impact: "blocking", action_required: true, coverage: { ...service.coverage, series: "action_required" } } : service, providers: [provider], hosters: [hoster], summary: { healthy: 1 } } });
        if (path.endsWith("/monitor/config")) { if (failSave) return route.fulfill({ status: 502, json: { detail: "The origin web server returned an invalid or incomplete response to Cloudflare token=secret" } }); config = body; return route.fulfill({ json: config }); }
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
      assert.equal(await page.locator("#settings-sources > .settings-card").first().getAttribute("id"), "provider-monitor", "Availability comes before source configuration");
      const interact = mobile ? "tap" : "click";
      await monitor.locator('[data-monitor="health-title"]').getByText("Alles funktioniert").waitFor();
      assert.equal(await monitor.locator('[data-monitor="technical"]').evaluate(node => node.open), false);
      assert.equal(await monitor.locator('[data-monitor="providers"] details').count(), 0, "Technical rows mount only on demand");
      assert.equal(await monitor.locator('[data-action="all"]').isVisible(), false);
      assert.equal(await monitor.locator('[name="monitor-interval"]').isVisible(), false);
      const plain = await monitor.innerText();
      assert.doesNotMatch(plain, /Resolver|Hoster|Parserfehler|Browser-Fallback|Runtime|Repair Candidate|Cloudflare/);
      assert.match(plain, /Keine Einschränkungen/);
      assert.match(plain, /Aktion erforderlich: Nein/);
      assert.equal(await monitor.locator("table:visible").count(), 0);
      const rect = await monitor.boundingBox();
      await monitor.screenshot({ path: `${require("node:os").tmpdir()}/royal-source-summary-${width}.png` });
      if (mobile) assert.ok(rect.height < 850, `Compact default monitor: ${rect.height}`);
      failSave = true;
      await monitor.locator('[data-action="save"]')[interact]();
      await monitor.locator('[data-monitor="status"]').getByText(/nicht übernommen/).waitFor();
      assert.doesNotMatch(await monitor.innerText(), /Cloudflare|token=secret/);
      failSave = false;
      unavailable = true;
      await monitor.locator('[data-action="save"]')[interact]();
      await monitor.locator('[data-monitor="health-title"]').getByText("Aktion erforderlich").waitFor();
      assert.match(await monitor.locator('[data-monitor="coverage"]').innerText(), /Serien.*Keine verfügbare Quelle/s);
      await monitor.locator('[data-action="details"]')[interact]();
      assert.equal(await monitor.locator('[data-monitor="technical"]').evaluate(node => node.open), true);
      unavailable = false;
      await monitor.locator('details[data-provider="filmpalast"] > summary')[interact]();
      assert.match(await monitor.textContent(), /Gesund/);
      await monitor.locator('[data-panel="filmpalast-repairs"] > summary').click();
      await monitor.locator('[data-action="rollback"]:not([data-kind])').click();
      assert.equal(calls.some(call => call.path.endsWith("/rollback")), false);
      await monitor.locator('[data-action="cancel"]').click();
      assert.equal(calls.some(call => call.path.endsWith("/rollback")), false);
      await monitor.locator('[data-action="rollback"]:not([data-kind])').click();
      await monitor.locator('[data-action="confirm"]').click();
      await page.waitForFunction(() => !document.querySelector('#provider-monitor [data-action="rollback"]:not([data-kind])'));
      assert.equal(calls.filter(call => call.path.endsWith("/rollback")).length, 1);
      assert.equal(await monitor.locator('[data-panel="filmpalast-repairs"]').evaluate(node => node.open), true);
      await monitor.locator('[data-action="probe"]:not([data-kind])').click();
      await monitor.locator('[data-action="full"]:not([data-kind])').click();
      assert.deepEqual(calls.filter(call => call.path.endsWith("/probe")).map(call => call.body.intensity), ["standard", "full"]);
      await monitor.locator('[data-monitor="advanced-settings"] > summary')[interact]();
      await monitor.locator('[name="monitor-interval"]').fill("6");
      await monitor.locator('[name="monitor-intensity"]').selectOption("full");
      await monitor.locator('[data-action="save"]').click();
      assert.equal(config.interval_hours, 6);
      assert.equal(config.intensity, "full");
      await monitor.locator('[data-action="all"]').click();
      assert.equal(calls.filter(call => call.path.endsWith("/probe-all")).length, 1);
      await monitor.locator('[data-action="tab"][data-tab="hosters"]').click();
      const hosters = monitor.locator('[data-monitor="hosters"]');
      await hosters.locator('[data-panel="hoster-voe"] > summary').click();
      assert.match(await hosters.textContent(), /Median 1250 ms/);
      assert.match(await hosters.textContent(), /HTTP-Pfad nicht bestätigt/);
      assert.match(await hosters.textContent(), /Browser-Fallback nicht aktiv geprüft/);
      assert.match(await hosters.textContent(), /⚠/);
      assert.doesNotMatch(await hosters.textContent(), /(?:^|\s)0 ms/);
      await hosters.locator('[data-action="probe"]').click();
      await hosters.locator('[data-action="full"]').click();
      assert.deepEqual(calls.filter(call => call.path === "/api/hosters/voe/probe").map(call => call.body.intensity), ["standard", "full"]);
      await hosters.locator('details details > summary').first().click();
      await hosters.locator('[data-action="activate"]').click();
      assert.equal(calls.some(call => call.path.endsWith("/activate")), false);
      await monitor.locator('[data-action="confirm"]').click();
      await hosters.locator('[data-action="rollback"]').waitFor();
      assert.equal(calls.filter(call => call.path.endsWith("/activate"))[0].body.confirmed, true);
      await hosters.locator('[data-action="rollback"]').click();
      await monitor.locator('[data-action="confirm"]').click();
      assert.equal(calls.filter(call => call.path === "/api/hosters/voe/repairs/hoster-repair/rollback").length, 1);
      await monitor.locator('[data-action="tab"][data-tab="history"]').click();
      assert.match(await monitor.locator('[data-monitor="history"]').textContent(), /parser_error/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await monitor.locator('[data-monitor="technical"] > summary')[interact]();
      await monitor.locator('[data-monitor="advanced-settings"] > summary')[interact]();
      assert.doesNotMatch(await monitor.innerText(), /Resolver|Hoster|Parserfehler|Browser-Fallback|Runtime|Cloudflare/);
      assert.deepEqual(errors, []);
      console.log(`provider monitor ${width}px: diagnostics, probe, config, confirmation and rollback passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
