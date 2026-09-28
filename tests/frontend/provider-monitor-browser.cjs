const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const width of [1440, 390, 430]) {
    const mobile = width !== 1440;
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile, viewport: { width, height: width === 430 ? 932 : mobile ? 844 : 1000 } });
    const { page, errors } = run;
    const calls = [];
    let config = { enabled: true, auto_repair: true, notify_changes: false, interval_hours: 12, intensity: "standard" };
    let unavailable = false, failSave = false, languageProblem = false, diagnosticOnly = false;
    const service = { service_health: "healthy", user_impact: "none", action_required: false,
      coverage: { movies: "healthy", series: "healthy", anime: "healthy" }, active_sources: 1, available_video_services: 1, last_check_at: Date.now() / 1000 - 18 * 60,
      paths: ["de", "en"].map(language => ({ media_type: "anime", language, state: "healthy" })),
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
        if (path.endsWith("/diagnostics")) return route.fulfill({ json: { config, service: diagnosticOnly ? { ...service, service_health: "degraded", user_impact: "unconfirmed", coverage: { ...service.coverage, anime: "unconfirmed" }, paths: [{ media_type: "anime", language: "de", state: "unconfirmed" }] } : languageProblem ? { ...service, service_health: "action_required", user_impact: "blocking", action_required: true, coverage: { ...service.coverage, anime: "action_required" }, paths: service.paths.map(p => ({ ...p, state: p.language === "de" ? "action_required" : "healthy" })) } : unavailable ? { ...service, service_health: "action_required", user_impact: "blocking", action_required: true, coverage: { ...service.coverage, series: "action_required" } } : service, providers: [provider], hosters: [hoster], summary: { healthy: 1 } } });
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
      await page.evaluate(async () => { await fixtureApp.settings.providers.initialize(); fixtureApp.settings.providers.apply({
        movies: ["filmpalast", "sflix"], series: ["serienstream", "sflix"], anime: ["aniworld", "mkissa"],
        enabled_movies: ["filmpalast", "sflix"], enabled_series: ["serienstream", "sflix"], enabled_anime: ["aniworld", "mkissa"],
        content_languages: ["de", "en"], languages: { de: "Deutsch", en: "English" },
        catalog: { filmpalast: { content_language: "de" }, serienstream: { content_language: "de" }, sflix: { content_language: "en" },
          aniworld: { content_language: "de", content_languages: ["de", "en"], language_labels: ["Deutsch", "English"] }, mkissa: { content_language: "en" } },
      }); });
      await page.locator('#content-language-options [data-language="de"]')[interact]();
      const animeRow = page.locator('#anime-provider-priority [data-provider="aniworld"] input');
      assert.equal(await animeRow.isChecked(), true, "Removing German preserves bilingual AniWorld");
      assert.equal(await animeRow.isEnabled(), true);
      assert.equal(await page.evaluate(() => fixtureApp.core.actions.aniworldNavigationAvailable()), true);
      await page.locator('#content-language-options [data-language="de"]')[interact]();
      await page.locator('#content-language-options [data-language="en"]')[interact]();
      assert.equal(await animeRow.isChecked(), true, "German-only AniWorld remains selectable");
      assert.equal(await page.locator('#anime-provider-priority [data-provider="mkissa"] input').isEnabled(), false);
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
      const coverage = monitor.locator('[data-monitor="coverage"]');
      assert.match(await coverage.innerText(), /Anime.*Verfügbar/s);
      assert.equal(await coverage.locator('.source-language-path').count(), 0, "Healthy language coverage stays compact");
      languageProblem = true;
      await monitor.locator('[data-action="save"]')[interact]();
      await coverage.getByText("Deutsch: ✕ Nicht verfügbar").waitFor();
      assert.equal(await coverage.getByText("Englisch: ✓ Verfügbar").isVisible(), true);
      assert.equal(await monitor.locator('[data-monitor="technical"]').evaluate(node => node.open), false);
      if (mobile) {
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
        await monitor.screenshot({ path: `${require("node:os").tmpdir()}/royal-source-languages-${width}.png` });
      }
      languageProblem = false;
      await monitor.locator('[data-action="save"]')[interact]();
      await monitor.locator('[data-monitor="health-title"]').getByText("Alles funktioniert").waitFor();
      assert.equal(await coverage.locator('.source-language-path').count(), 0);
      // AniWorld is the only configured German anime route. Incomplete
      // diagnostics must neither claim an outage nor disable its catalog.
      diagnosticOnly = true;
      await monitor.locator('[data-action="save"]')[interact]();
      await coverage.getByText("○ Noch nicht bestätigt (Deutsch)").waitFor();
      assert.doesNotMatch(await monitor.innerText(), /Keine verfügbare Quelle|Aktion erforderlich: Ja/);
      await page.route("**/api/aniworld?**", route => route.fulfill({ json: { results: [{ id: "routing-fixture", title: "Routing Fixture", cover_url: "/fixture-art.svg", translations: { dub: 1 } }], page: 1, has_more: false, disabled: false } }));
      const catalogRequest = page.waitForResponse(response => new URL(response.url()).pathname === "/api/aniworld");
      await page.evaluate(() => fixtureApp.core.actions.switchTab("aniworld"));
      assert.equal((await (await catalogRequest).json()).disabled, false);
      await page.locator("#aniworld-results button.aniworld-card").waitFor();
      assert.doesNotMatch(await page.locator("#tab-aniworld").innerText(), /AniWorld ist nicht verfügbar|AniWorld ist pausiert/);
      await page.evaluate(() => fixtureApp.core.actions.switchTab("einstellungen"));
      await monitor.waitFor({ state: "visible" });
      diagnosticOnly = false;
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
      await monitor.locator('[data-panel="filmpalast-repairs"]').evaluate(node => {
        const button = node.querySelector('[data-action="rollback"]');
        node.dispatchEvent(new Event("toggle", { bubbles: true }));
        assertDisclosureStable(node, button);
        function assertDisclosureStable(panel, control) {
          if (!panel.isConnected || !control.isConnected || !panel.open) throw new Error("Nested toggle rebuilt or closed repair controls");
        }
      });
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
      await page.waitForFunction(() => {
        const button = document.querySelector('#provider-monitor [data-action="probe"]:not([data-kind])');
        return button && !button.disabled;
      });
      await monitor.locator('[data-action="full"]:not([data-kind])').click();
      await page.waitForFunction(() => {
        const button = document.querySelector('#provider-monitor [data-action="full"]:not([data-kind])');
        return button && !button.disabled;
      });
      assert.deepEqual(calls.filter(call => call.path.endsWith("/probe")).map(call => call.body.intensity), ["standard", "full"]);
      await monitor.locator('[data-monitor="advanced-settings"] > summary')[interact]();
      await monitor.locator('[name="monitor-interval"]').fill("6");
      await monitor.locator('[name="monitor-intensity"]').selectOption("full");
      await monitor.locator('[data-action="save"]').click();
      await page.waitForFunction(() => {
        const button = document.querySelector('#provider-monitor [data-action="save"]');
        return button && !button.disabled;
      });
      assert.equal(config.interval_hours, 6);
      assert.equal(config.intensity, "full");
      await monitor.locator('[data-action="all"]').click();
      await page.waitForFunction(() => {
        const button = document.querySelector('#provider-monitor [data-action="all"]');
        return button && !button.disabled;
      });
      assert.equal(calls.filter(call => call.path.endsWith("/probe-all")).length, 1);
      await monitor.locator('[data-action="tab"][data-tab="hosters"]').click();
      const hosters = monitor.locator('[data-monitor="hosters"]');
      await hosters.waitFor({ state: "visible" });
      await hosters.locator('[data-panel="hoster-voe"] > summary').click();
      assert.match(await hosters.textContent(), /Median 1250 ms/);
      assert.match(await hosters.textContent(), /HTTP-Pfad nicht bestätigt/);
      assert.match(await hosters.textContent(), /Browser-Fallback nicht aktiv geprüft/);
      assert.match(await hosters.textContent(), /⚠/);
      assert.doesNotMatch(await hosters.textContent(), /(?:^|\s)0 ms/);
      await hosters.locator('[data-action="probe"]').click();
      await page.waitForFunction(() => {
        const button = document.querySelector('#provider-monitor [data-monitor="hosters"] [data-action="probe"]');
        return button && !button.disabled;
      });
      await hosters.locator('[data-action="full"]').click();
      await page.waitForFunction(() => {
        const button = document.querySelector('#provider-monitor [data-monitor="hosters"] [data-action="full"]');
        return button && !button.disabled;
      });
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
