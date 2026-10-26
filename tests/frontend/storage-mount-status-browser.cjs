const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const engine of process.env.ROYAL_BROWSER ? [process.env.ROYAL_BROWSER] : ["chromium", "webkit"]) {
    for (const width of [390, 1440]) {
      const mobile = width < 1000;
      const run = await fixture({ engine, mobile, viewport: { width, height: mobile ? 844 : 1000 } });
      const { page } = run;
      try {
        const GiB = 1024 ** 3;
        const policy = { mode: "full", auto_delete: false, delete_categories: [], window_enabled: false,
          window_start: "02:00", window_end: "07:00", interval_hours: 6, cooldown_hours: 168,
          max_moves: 1, max_move_gib: 200, unknown_download_gib: 8, archive_age_days: 180, allow_series_split: false };
        const volumePolicy = { role: "primary", media_types: ["movies", "series", "anime"], target_percent: 75,
          warning_percent: 85, critical_percent: 92, reserve_gib: 5, allow_moves_in: true, allow_moves_out: true };
        const raw = [
          { key: "movies", label: "Filme", path: "/movies_extern", source: "media", available: true, configured: true, volume_id: "large", total_bytes: 10000 * GiB, free_bytes: 8500 * GiB, used_percent: 15 },
          { key: "series", label: "Serien", path: "/serien_extern", source: "media", available: false, configured: true, error: "Pfad nicht gefunden" },
          { key: "location:main", location_id: "main", label: "Hauptspeicher", path: "/movies", source: "custom", available: true, volume_id: "main", total_bytes: 4000 * GiB, free_bytes: 480 * GiB, used_percent: 88 },
          { key: "location:large", location_id: "large", label: "Volume 2", path: "/movies_vol2", source: "custom", available: true, volume_id: "large", total_bytes: 10000 * GiB, free_bytes: 8500 * GiB, used_percent: 15 },
        ];
        let confirmed = false, accept = false;
        const writes = [];
        page.on("dialog", dialog => accept ? dialog.accept() : dialog.dismiss());
        await page.route("**/api/storage/**", async route => {
          const path = new URL(route.request().url()).pathname;
          if (route.request().method() !== "GET") {
            const body = route.request().postDataJSON();
            writes.push({ path, body });
            assert.equal(path, "/api/storage/autopilot/volume");
            assert.deepEqual(body, { root: "movies", policy: {}, confirm_mount: true });
            confirmed = true;
            return route.fulfill({ json: { saved: true, policy: volumePolicy } });
          }
          if (path === "/api/storage/autopilot") {
            const roots = raw.map(root => ({ ...root, reachable: root.available,
              available: root.available && (root.key !== "movies" || confirmed), writable: root.available && (root.key !== "movies" || confirmed),
              mount_confirmation_required: root.key === "movies" && !confirmed,
              location_mode: "media", policy: volumePolicy, reserved_bytes: 0, pressure: root.available ? "normal" : "offline" }));
            return route.fulfill({ json: { policy, roots, pressure: "warning", summary: { volume_count: 2, free_bytes: 8980 * GiB }, recommendations: [], activity: [], active_moves: 0 } });
          }
          if (path === "/api/storage/status") return route.fulfill({ json: { roots: raw, locations: [], deployment_mode: "nas",
            summary: { volume_count: 2, free_bytes: 8980 * GiB, total_bytes: 14000 * GiB },
            volumes: [raw[2], raw[3]].map(root => ({ id: root.volume_id, ...root, members: [], paths: [root.path], mode: "media" })) } });
          return route.fulfill({ json: { jobs: [], history: [], active_count: 0 } });
        });
        if (mobile) {
          await page.locator("#mobile-more-toggle").tap();
          await page.locator('[data-tab="einstellungen"]:visible').tap();
        } else await page.locator("#settings-btn").click();
        await page.locator('[data-settings-open="settings-storage"]').click();
        await page.getByText("Standardziel bestätigen", { exact: true }).waitFor();
        await page.locator(".operation-path-health > summary").click();
        const targets = page.locator("#storage-standard-target-list .storage-standard-target");
        await targets.first().waitFor();
        assert.doesNotMatch((await targets.allInnerTexts()).join(" "), /Immer verfügbar/);
        assert.match(await targets.first().innerText(), /erreichbar.*Bestätigung erforderlich/s);
        assert.match(await targets.nth(1).innerText(), /nicht erreichbar.*Nicht verfügbar/s);
        assert.equal(await targets.nth(1).locator("button").count(), 0);
        assert.match(await page.locator("#storage-live-state").innerText(), /2 physische Volumes/);
        const button = targets.first().locator('[data-autopilot-action="mount"]');
        await button.click();
        assert.equal(writes.length, 0, "cancelling confirmation must not authorize a changed mount");
        accept = true;
        await button.click();
        await page.waitForFunction(() => document.querySelector("#storage-standard-target-list .storage-standard-target-note strong")?.textContent === "Verfügbar");
        assert.equal(writes.length, 1);
        assert.match(await page.locator("#storage-autopilot-health").innerText(), /Ein Volume ist stark belegt/);
        assert.equal(await targets.first().locator("button").count(), 0);
        assert.match(await targets.nth(1).innerText(), /Nicht verfügbar/);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        assert.deepEqual(run.errors, []);
        console.log(JSON.stringify({ engine, width, blockedVersusOffline: true, explicitConfirmation: true, immediateRefresh: true }));
      } finally { await run.close(); }
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
