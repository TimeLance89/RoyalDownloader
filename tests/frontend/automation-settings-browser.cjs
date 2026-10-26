const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { fixture } = require('./performance-fixture.cjs');
(async () => {
  const output = path.resolve('artifacts/automation-review'); await fs.mkdir(output, { recursive: true });
  for (const width of [1600, 430]) {
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || 'chromium', mobile: width !== 1600, viewport: { width, height: 1150 } });
    const { page, errors } = run;
    const writes = []; let failSave = false, failRead = false;
    let policy = { auto_download: true, check_interval_min: 30, weekday_window_start: 0, weekday_window_end: 6,
      weekend_window_start: null, weekend_window_end: null, max_parallel_downloads: 2, max_bandwidth_mbps: 20, min_free_space_gb: 50,
      jellyfin_throttle_enabled: true, jellyfin_streaming_bandwidth_mbps: 5,
      movie_upgrades_night_only: true, movie_upgrade_window_start: 0, movie_upgrade_window_end: 6,
      policy_state: { schedule_open: false, movie_upgrade_window_open: false, storage: { ok: true, free_gb: 431.2 },
        bandwidth: { effective_mbps: 5, jellyfin: { configured: true, reachable: true, active_streams: 1 } } } };
    try {
      await page.route('**/api/automation/policy', async route => {
        if (route.request().method() === 'GET') return route.fulfill(failRead ? { status: 503, json: { detail: 'Status vorübergehend nicht verfügbar.' } } : { json: policy });
        writes.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() });
        if (failSave) return route.fulfill({ status: 503, json: { detail: 'Regeln konnten nicht gespeichert werden.' } });
        policy = { ...policy, ...route.request().postDataJSON() };
        return route.fulfill({ json: { ...policy, saved: true } });
      });
      await page.route('**/assets/profile-avatars/*.svg', async route => {
        const name = new URL(route.request().url()).pathname.split('/').at(-1);
        await route.fulfill({ contentType: 'image/svg+xml', body: await fs.readFile(path.resolve(__dirname, '../../web/assets/profile-avatars', name)) });
      });
      await page.evaluate(async () => {
        fixtureApp.profile.auth.acceptUser({ id: 'performance-fixture', username: 'jester', display_name: 'Steffen', role: 'admin', avatar_id: 'avatar-gold' });
        fixtureApp.core.actions.switchTab('einstellungen');
        document.querySelector('[data-settings-target="settings-automation"]').click();
        await fixtureApp.settings.automation.initialize();
      });
      const section = page.locator('#settings-automation');
      await page.waitForFunction(() => document.querySelector('#max-bandwidth-mbps').value === '20');
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(350);
      assert.equal(await page.locator('#settings-save').isVisible(), false);
      assert.equal(await section.locator('[data-automation-panel="limits"]').isVisible(), false);
      assert.equal(await section.locator('#check-interval').inputValue(), '30');
      await page.screenshot({ path: path.join(output, `wochenplan-${width}.png`) });
      await section.locator('[data-automation-tab="limits"]').click();
      await page.screenshot({ path: path.join(output, `leistung-${width}.png`) });
      await section.locator('[data-automation-tab="status"]').click();
      await page.screenshot({ path: path.join(output, `status-${width}.png`) });
      await section.locator('[data-automation-tab="schedule"]').click();
      await section.locator('.smart-schedule-choice:has(input[name="weekday-mode"][value="custom"])').click();
      await section.locator('#weekday-custom-start').fill('22:00'); await section.locator('#weekday-custom-start').dispatchEvent('change');
      await section.locator('#weekday-custom-end').fill('07:00'); await section.locator('#weekday-custom-end').dispatchEvent('change');
      await section.locator('.smart-schedule-choice:has(input[name="weekend-mode"][value="same"])').click();
      await section.locator('#check-interval').fill('45');
      await section.locator('.automation-movie-block > summary').click();
      await section.locator('#movie-upgrades-night-only').uncheck();
      assert.equal(await section.locator('#movie-upgrade-window-start').isDisabled(), true);
      await section.locator('[data-automation-tab="limits"]').click();
      await section.locator('#max-parallel-downloads').selectOption('3');
      await section.locator('#max-bandwidth-mbps').fill('12.5');
      await section.locator('#min-free-space-gb').fill('100');
      await section.locator('#jellyfin-throttle-enabled').uncheck();
      assert.equal(await section.locator('#jellyfin-streaming-bandwidth-mbps').isDisabled(), true);
      await section.locator('[data-automation-tab="status"]').click();
      await section.locator('#automation-refresh').click();
      await section.locator('#automation-refresh').waitFor({ state: 'visible' });
      assert.equal(await section.locator('#max-bandwidth-mbps').inputValue(), '12.5');
      assert.match(await section.locator('[data-policy-state="performance"] small').textContent(), /5 MB/);
      assert.equal(writes.length, 0);
      failSave = true;
      await section.locator('#automation-save').click();
      await section.getByText('Nicht gespeichert: Regeln konnten nicht gespeichert werden.', { exact: true }).waitFor();
      assert.equal(await section.locator('#max-bandwidth-mbps').inputValue(), '12.5');
      failSave = false;
      await section.locator('#automation-save').click();
      await section.getByText('Automatik gespeichert. Die Regeln gelten jetzt.', { exact: true }).waitFor();
      const saved = writes.at(-1).body;
      assert.equal(saved.weekday_window_start, 22); assert.equal(saved.weekday_window_end, 7);
      assert.equal(saved.weekend_window_start, 22); assert.equal(saved.weekend_window_end, 7);
      assert.equal(saved.check_interval_min, 45); assert.equal(saved.max_parallel_downloads, 3);
      assert.equal(saved.max_bandwidth_mbps, 12.5); assert.equal(saved.min_free_space_gb, 100);
      assert.equal(saved.jellyfin_throttle_enabled, false); assert.equal(saved.movie_upgrades_night_only, false);
      await section.locator('.automation-switch').click();
      assert.doesNotMatch(await section.locator('#auto-status').textContent(), /Auto-Download aus/);
      await section.locator('#automation-save').click();
      await section.getByText('Automatik gespeichert. Die Regeln gelten jetzt.', { exact: true }).waitFor();
      assert.match(await section.locator('#auto-status').textContent(), /Auto-Download aus/);
      assert.equal(policy.max_bandwidth_mbps, 12.5);
      failRead = true; await section.locator('#automation-refresh').click();
      await section.getByText(/Automatik-Regeln nicht abrufbar: Status vorübergehend/).waitFor();
      assert.equal(await section.getAttribute('data-view-state'), 'error');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.deepEqual(errors, []);
      console.log(`Automation ${width}: schedule, limits, saved state, failed save and isolated persistence passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
