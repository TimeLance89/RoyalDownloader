const assert = require('node:assert/strict');
const { mkdir } = require('node:fs/promises');
const { fixture } = require('./performance-fixture.cjs');

(async () => {
  const directory = 'artifacts/media-center';
  await mkdir(directory, { recursive: true });
  for (const width of [1440, 390]) {
    const run = await fixture({ viewport: { width, height: 1100 }, mobile: width === 390 });
    const { page, errors } = run;
    const connected = { provider: 'jellyfin', generation: 0, libraries: [], url: 'http://jellyfin.local:8096', has_api_key: true, user_name: 'Hauptprofil', user_id: 'owner' };
    let current = { ...connected }, probeFailure = false, saveFailure = true, empty = false, saves = 0, probes = 0;
    try {
      await page.route('**/api/jellyfin/config', route => route.fulfill({ json: connected }));
      await page.route('**/api/media-center/config', route => route.fulfill({ json: current }));
      await page.route('**/api/media-center/probe', route => {
        probes++;
        if (probeFailure) return route.fulfill({ status: 502, json: { detail: 'Token ungültig' } });
        const { provider } = route.request().postDataJSON();
        return route.fulfill({ json: { provider, server_id: 'machine', server_name: provider === 'plex' ? 'Wohnzimmer' : 'Jellyfin',
          libraries: empty || provider === 'jellyfin' ? [] : [{ id: '1', name: 'Filme', type: 'movie' }, { id: '2', name: 'Serien', type: 'series' }],
          users: [{ id: 'token-profile', name: 'Plex-Konto dieser Verbindung' }], profile_hint: 'Der Token bestimmt das Plex-Profil.' } });
      });
      await page.route('**/api/media-center/activate', route => {
        saves++;
        if (saveFailure) { saveFailure = false; return route.fulfill({ status: 502, json: { detail: 'Server momentan nicht erreichbar' } }); }
        const body = route.request().postDataJSON();
        assert.deepEqual(body.libraries, ['1', '2']);
        current = { provider: body.provider, url: body.url, libraries: body.libraries, has_api_key: true, generation: 1, user_id: body.user_id, user_name: 'Plex-Konto dieser Verbindung' };
        return route.fulfill({ json: current });
      });
      await page.evaluate(async () => {
        fixtureApp.core.actions.switchTab('einstellungen');
        document.querySelector('[data-settings-target="settings-media"]').click();
        await fixtureApp.integrations.jellyfin.refresh();
      });
      const card = page.locator('#media-center-settings');
      await page.evaluate(() => {
        window.verifyCleanupControls = async provider => {
          const { createMovieSubscriptionRules } = await import('/js/features/subscriptions/movie-rules.js');
          const root = document.getElementById('movie-subscription-modal').cloneNode(true);
          root.id = 'media-center-cleanup-regression';
          document.body.append(root);
          const rules = createMovieSubscriptionRules(root, { model: { get: () => ({ items: [] }) }, isJellyfinConfigured: () => false });
          try {
            rules.open('fixture-movie', { title: 'Cleanup regression' });
            const watched = root.querySelector('input[name="movie-cleanup"][value="watched"]');
            if (provider === 'plex') {
              if (!watched.disabled) throw new Error('Plex must keep destructive cleanup disabled');
            } else {
              watched.checked = true;
              watched.dispatchEvent(new Event('change', { bubbles: true }));
              if (!root.querySelector('#movie-subscription-status').textContent.includes('Profil gewählt')) throw new Error('Jellyfin cleanup must explain its missing profile');
            }
          } finally { rules.unmount(); root.remove(); }
        };
      });
      await page.evaluate(() => verifyCleanupControls('jellyfin'));
      await card.getByText('Eingerichtet', { exact: true }).waitFor();
      assert.equal(await card.locator('[data-mc-open="jellyfin"]:not([data-mc-edit])').count(), 0);
      await card.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${directory}/connected-${width}.png` });
      await card.locator('[data-mc-open="plex"]').click();
      const dialog = page.locator('.mc-dialog');
      await dialog.screenshot({ path: `${directory}/switch-${width}.png` });
      await page.keyboard.press('Escape');
      assert.equal(await dialog.isVisible(), false);
      assert.equal(await card.locator('[data-mc-open="plex"]').evaluate(node => node === document.activeElement), true);
      await card.locator('[data-mc-open="plex"]').click();
      await dialog.locator('[data-mc="next"]').click();
      await dialog.screenshot({ path: `${directory}/connection-${width}.png` });
      await page.locator('#mc-url').fill('javascript:invalid');
      await dialog.locator('[data-mc="next"]').click();
      assert.equal(probes, 0);
      assert.match(await dialog.locator('[role="alert"]').innerText(), /gültige Serveradresse/);
      await page.locator('#mc-url').fill('http://plex.local:32400');
      await page.locator('#mc-token').fill('private-test-token');
      probeFailure = true;
      await dialog.locator('[data-mc="next"]').click();
      await dialog.getByText('Token ungültig', { exact: true }).waitFor();
      assert.equal(await dialog.getAttribute('data-step'), '1');
      probeFailure = false; empty = true;
      await dialog.locator('[data-mc="next"]').click();
      await dialog.getByText(/Noch keine Film-/).waitFor();
      await dialog.locator('[data-mc="next"]').click();
      assert.equal(await dialog.getAttribute('data-step'), '2');
      await dialog.locator('[data-mc="back"]').click();
      empty = false;
      assert.equal(await page.locator('#mc-token').inputValue(), 'private-test-token');
      await dialog.locator('[data-mc="next"]').click();
      await dialog.locator('[name="mc-library"]').first().waitFor();
      await dialog.screenshot({ path: `${directory}/libraries-${width}.png` });
      for (const input of await dialog.locator('[name="mc-library"]').all()) await input.uncheck();
      await dialog.locator('[data-mc="next"]').click();
      assert.match(await dialog.locator('[role="alert"]').innerText(), /mindestens eine Bibliothek/);
      for (const input of await dialog.locator('[name="mc-library"]').all()) await input.check();
      await dialog.locator('[data-mc="next"]').click();
      await dialog.screenshot({ path: `${directory}/review-${width}.png` });
      assert.equal(saves, 0);
      await dialog.locator('[data-mc="next"]').click();
      await dialog.getByText('Server momentan nicht erreichbar', { exact: true }).waitFor();
      assert.equal(current.provider, 'jellyfin');
      assert.equal(await dialog.getAttribute('data-step'), '3');
      await dialog.locator('[data-mc="next"]').click();
      await dialog.waitFor({ state: 'hidden' });
      await card.getByText('Plex', { exact: true }).waitFor();
      assert.equal(current.provider, 'plex');
      await page.evaluate(() => verifyCleanupControls('plex'));
      assert.equal(await page.locator('.media-center-existing').isVisible(), false);
      assert.equal(await page.locator('#global-search-jellyfin').innerText(), '✓ In Plex');
      assert.equal(await card.locator('[data-mc-open="jellyfin"]').count(), 1);
      await card.screenshot({ path: `${directory}/plex-active-${width}.png` });
      await card.locator('[data-mc-edit]').click();
      assert.equal(await page.locator('#mc-token').inputValue(), '');
      assert.equal(await page.locator('#mc-url').inputValue(), 'http://plex.local:32400');
      await page.keyboard.press('Escape');
      current = {};
      await page.evaluate(() => fixtureApp.integrations.jellyfin.refresh());
      assert.equal(await card.locator('[data-mc-open]').count(), 2);
      await card.screenshot({ path: `${directory}/choose-${width}.png` });
      await card.locator('[data-mc-open="jellyfin"]').click();
      await dialog.locator('[data-mc="next"]').click();
      assert.match(await dialog.locator('label[for="mc-token"]').innerText(), /API-Schlüssel/);
      await page.keyboard.press('Escape');
      await page.evaluate(() => fixtureApp.core.actions.switchTab('home'));
      assert.equal(await page.locator('.mc-dialog').count(), 0);
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ width, passed: true, probes, saves }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
