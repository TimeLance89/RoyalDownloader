const assert = require('node:assert/strict');
const { fixture } = require('./performance-fixture.cjs');
(async () => {
  for (const width of [390, 1440]) {
    const run = await fixture({viewport: {width, height: 1000}, mobile: width < 820});
    const {page} = run;
    const requests = [];
    try {
      await page.route('**/api/series/episode-languages', route => { requests.push(route); });
      await page.evaluate(() => {
        fixtureApp.core.actions.switchTab('serien', {autoLoad: false});
        const episodes = Array.from({length: 12}, (_, i) => ({slug: `sto:delay-s01e${i+1}`, season: 1, episode: i+1}));
        fixtureApp.discovery.seriesActions.showSeriesDetail({base_slug: 'sto:delay', provider: 'serienstream',
          title: 'Delayed language fixture', description: '', seasons: [{season: 1, episodes}], episode_count: 12}, episodes[0].slug);
      });
      await page.waitForFunction(() => document.querySelectorAll('.ep-tile').length === 12);
      await page.locator('#series-tiles .season-btn').click();
      assert.equal(await page.locator('#series-tiles .season-btn').getAttribute('aria-busy'), 'true');
      assert.match(await page.locator('#series-tiles .season-btn small').textContent(), /12 prüfen/);
      assert.equal(await page.locator('#series-add-btn').isDisabled(), true);
      const respond = async (route, denied = []) => {
        const {slugs} = route.request().postDataJSON();
        await route.fulfill({contentType: 'application/json', body: JSON.stringify({
          available: Object.fromEntries(slugs.map(slug => [slug, !denied.includes(slug)])),
          languages: Object.fromEntries(slugs.map(slug => [slug, [denied.includes(slug) ? 'en' : 'de']]))})});
      };
      while (!requests.length) await page.waitForTimeout(10);
      await respond(requests[0], ['sto:delay-s01e2']);
      await page.waitForFunction(() => document.querySelectorAll('.ep-tile.selected').length === 3);
      assert.equal(await page.locator('#series-add-btn').isEnabled(), true);
      assert.equal(await page.locator('[data-episode-slug="sto:delay-s01e2"]').isDisabled(), true);
      await page.locator('#series-select-none').click();
      while (requests.length < 2) await page.waitForTimeout(10);
      await respond(requests[1]);
      while (requests.length < 3) await page.waitForTimeout(10);
      await respond(requests[2]);
      await page.waitForFunction(() => document.querySelectorAll('.ep-tile.language-pending').length === 0);
      assert.equal(await page.locator('.ep-tile.selected').count(), 0);
      assert.equal(await page.locator('#series-add-btn').isDisabled(), true);
      assert.deepEqual(run.errors, []);
      console.log(JSON.stringify({width, immediateFeedback: true, progressiveSelection: true, cancelledSelection: true}));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exit(1); });
