const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const width of [1440, 390, 430]) {
    const mobile = width !== 1440;
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile, viewport: { width, height: width === 430 ? 932 : mobile ? 844 : 1000 } });
    const { page, errors } = run;
    let policy = { mode: "monitor", auto_delete: false, delete_categories: [], window_enabled: true,
      window_start: "02:00", window_end: "07:00", interval_hours: 6, cooldown_hours: 168,
      max_moves: 1, max_move_gib: 200, unknown_download_gib: 8, archive_age_days: 180, allow_series_split: false };
    const volumePolicy = { role: "primary", media_types: ["movies", "series", "anime"], target_percent: 75,
      warning_percent: 85, critical_percent: 92, reserve_gib: 5, allow_moves_in: true, allow_moves_out: true };
    const roots = [{ key: "movies", label: "NAS Hauptspeicher", path: "/media", available: true,
      location_mode: "media", used_percent: 91, volume_id: "main", policy: { ...volumePolicy }, pressure: "warning" },
    { key: "location:archive", label: "Archiv HDD", path: "/archive", available: false,
      location_mode: "media", used_percent: 40, volume_id: "archive", policy: { ...volumePolicy, role: "archive" }, pressure: "offline", last_seen_at: 1_800_000_000 }];
    let recommendations = [{ id: "fixture-rec", name: "Storage Fixture", state: "available", item_id: "owned-item",
      destination_root: "location:archive", size_bytes: 100 * 1024 ** 3, before_percent: 91, after_percent: 81,
      expected_target_percent: 51, reasons: ["Genügend freie Sicherheitsreserve"], reason: "Speicher oberhalb der Warnschwelle" }];
    const calls = [];
    page.on("dialog", dialog => dialog.accept());
    try {
      await page.route("**/api/storage/**", async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        const body = request.method() === "GET" ? null : request.postDataJSON();
        calls.push({ path, method: request.method(), body });
        if (path === "/api/storage/autopilot") {
          if (body) policy = { ...policy, ...body.policy };
          return route.fulfill({ json: body ? { saved: true, policy } : { policy, roots, pressure: "warning", summary: {},
            active_moves: 0, recommendations, activity: [] } });
        }
        if (path === "/api/storage/autopilot/volume") {
          roots.find(root => root.key === body.root).policy = body.policy;
          return route.fulfill({ json: { saved: true } });
        }
        if (path === "/api/storage/cleanup/preview") return route.fulfill({ json: { candidates: [], size_bytes: 0,
          description: "Nur markierte Royal-Downloadreste. Keine Medien, fremden Dateien oder Backups." } });
        if (path.endsWith("/dismiss")) { recommendations = []; return route.fulfill({ json: { dismissed: true } }); }
        if (path.endsWith("/apply")) { recommendations = []; return route.fulfill({ json: { job: { job_id: "move-one", status: "queued" } } }); }
        if (path === "/api/storage/recommendations") return route.fulfill({ json: { recommendations } });
        if (path === "/api/storage/move/jobs") return route.fulfill({ json: { jobs: [], history: [], active_count: 0 } });
        return route.fulfill({ json: { roots: [], volumes: [], locations: [], summary: {}, observed_at: 0 } });
      });
      if (mobile) {
        await page.locator("#mobile-more-toggle").tap();
        await page.locator('[data-tab="einstellungen"]:visible').tap();
      } else await page.locator("#settings-btn").click();
      await page.locator('[data-settings-open="settings-storage"]').click();
      const panel = page.locator("#storage-autopilot");
      await panel.getByText("Speicher wird knapp", { exact: true }).waitFor();
      const interact = async locator => {
        await locator.evaluate(node => node.scrollIntoView({ block: "center", behavior: "instant" }));
        await locator[mobile ? "tap" : "click"]();
      };
      const command = async (locator, path, method) => {
        const response = page.waitForResponse(response => new URL(response.url()).pathname === path && (!method || response.request().method() === method));
        await interact(locator);
        await (await response).finished();
        await page.waitForFunction(() => document.querySelector("#storage-autopilot").getAttribute("aria-busy") === "false");
      };
      await interact(panel.locator('[name="storage-autonomy"][value="automatic"]'));
      await command(panel.locator('#storage-autopilot-form button[type="submit"]'), "/api/storage/autopilot", "PUT");
      assert.equal(policy.mode, "automatic");
      assert.equal(policy.auto_delete, false);
      await interact(panel.locator("#storage-autopilot-advanced > summary"));
      await panel.locator('[name="window_start"]').fill("03:00");
      await command(panel.locator('#storage-autopilot-form button[type="submit"]'), "/api/storage/autopilot", "PUT");
      assert.equal(policy.window_start, "03:00");
      await interact(panel.locator("#storage-volume-policies > summary"));
      const volume = panel.locator('[data-volume-root="movies"]');
      await volume.locator('[name="role"]').selectOption("overflow");
      await volume.locator('[name="reserve_gib"]').fill("50");
      await volume.locator('[name="target_percent"]').fill("70");
      await command(volume.locator('button[type="submit"]'), "/api/storage/autopilot/volume", "PUT");
      assert.equal(roots[0].policy.role, "overflow");
      assert.equal(roots[0].policy.reserve_gib, 50);
      assert.match(await panel.locator('[data-volume-root="location:archive"]').innerText(), /Offline.*keine Aktionen/s);
      await interact(panel.locator("#storage-cleanup-permission > summary"));
      await interact(panel.locator("#storage-auto-delete"));
      await panel.locator("#storage-cleanup-preview").waitFor({ state: "visible" });
      assert.equal(policy.auto_delete, false, "Preview cannot grant deletion");
      assert.match(await panel.locator("#storage-cleanup-preview-copy").innerText(), /Keine Medien/);
      await command(panel.locator('[data-autopilot-action="confirm-delete"]'), "/api/storage/autopilot", "PUT");
      assert.equal(policy.auto_delete, true);
      const deleteCall = calls.find(call => call.body?.delete_confirmed);
      assert.deepEqual(deleteCall.body.policy.delete_categories, ["royal_partials"]);
      await command(panel.locator('[data-autopilot-action="apply"]'), "/api/storage/recommendations/fixture-rec/apply");
      assert.equal(calls.find(call => call.path.endsWith("/apply")).body.confirm, true);
      recommendations = [{ id: "ignored-rec", name: "Other Fixture", state: "available", destination_root: "movies", size_bytes: 1024,
        before_percent: 91, after_percent: 80, expected_target_percent: 75, reasons: [], reason: "Freier Speicher" }];
      await command(panel.locator('[data-autopilot-action="recommend"]'), "/api/storage/recommendations");
      await command(panel.locator('[data-autopilot-action="dismiss"]'), "/api/storage/recommendations/ignored-rec/dismiss");
      assert.equal(recommendations.length, 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.deepEqual(errors, []);
      await panel.evaluate(node => node.scrollIntoView({ block: "start", behavior: "instant" }));
      await mkdir("artifacts/storage-autopilot", { recursive: true });
      await page.screenshot({ path: `artifacts/storage-autopilot/${process.env.ROYAL_BROWSER || "chromium"}-${width}.png` });
      console.log(`storage autopilot ${width}px: autonomy, roles, thresholds, offline, cleanup preview, apply and dismiss passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
