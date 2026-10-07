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
          title: 'Delayed language fixture', enabled_content_languages: ['de'], description: '', seasons: [{season: 1, episodes}], episode_count: 12}, episodes[0].slug);
      });
      await page.waitForFunction(() => document.querySelectorAll('.ep-tile').length === 12);
      await page.locator('#series-tiles .season-btn').click();
      assert.equal(await page.locator('#series-tiles .season-btn').getAttribute('aria-busy'), 'true');
      assert.match(await page.locator('#series-tiles .season-btn small').textContent(), /12 prüfen/);
      assert.equal(await page.locator('#series-add-btn').isEnabled(), true, 'pending selection can be submitted immediately');
      await page.evaluate(() => { window.selectionTile = document.querySelector(".ep-tile"); });
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
      assert.equal(await page.evaluate(() => selectionTile === document.querySelector('.ep-tile')), true, 'language batches preserve existing tiles');
      assert.equal(await page.locator('[data-episode-slug="sto:delay-s01e2"]').isDisabled(), false, 'first negative response remains pending');
      await page.locator('#series-select-none').click();
      while (requests.length < 2) await page.waitForTimeout(10);
      await respond(requests[1], ['sto:delay-s01e2']);
      while (requests.length < 3) await page.waitForTimeout(10);
      await respond(requests[2]);
      while (requests.length < 4) await page.waitForTimeout(10);
      await respond(requests[3], ['sto:delay-s01e2']);
      await page.waitForFunction(() => document.querySelectorAll('.ep-tile.language-pending').length === 0);
      assert.equal(await page.locator('.ep-tile.selected').count(), 0);
      assert.equal(await page.locator('#series-add-btn').isDisabled(), true);
      const queueRequests = [];
      await page.route('**/api/queue/add', route => {queueRequests.push(route);});
      await page.evaluate(() => {
        const episodes = Array.from({length: 8}, (_, i) => ({slug: `sto:deferred-s01e${i+1}`, season: 1, episode: i+1}));
        fixtureApp.discovery.seriesActions.showSeriesDetail({base_slug: 'sto:deferred', provider: 'serienstream',
          title: 'Deferred download fixture', enabled_content_languages: ['de'], description: '', seasons: [{season: 1, episodes}], episode_count: 8}, episodes[0].slug);
      });
      await page.locator('#series-tiles .season-btn').click();
      assert.match(await page.locator('#series-pick-count').textContent(), /8 ausgewählt · 8 prüfen/);
      await page.locator('#series-add-btn').click();
      await page.waitForFunction(() => document.querySelector('#series-status').textContent.includes('Merke 8'));
      while (!queueRequests.length) await page.waitForTimeout(10);
      assert.deepEqual(queueRequests[0].request().postDataJSON().slugs,
        Array.from({length:8},(_,i)=>`sto:deferred-s01e${i+1}`));
      await queueRequests[0].fulfill({json:{added:8,auto_started:8,done_jobs:0,total_jobs:8,
        queue:{count:8,groups:[],activity:{},providers:{}}}});
      await page.waitForFunction(() => document.querySelector('#series-status').textContent.includes('8/8 Episode(n) vorgemerkt'));
      assert.match(await page.locator('#series-status').textContent(), /Hintergrund geprüft/);
      const held = requests.filter(route=>route.request().postDataJSON().slugs.some(slug=>slug.startsWith('sto:deferred')));
      assert.equal(held.length,2);
      for (const route of held) await respond(route);
      await page.waitForFunction(() => document.querySelector('#series-probe-progress').textContent.includes('Prüfung abgeschlossen'));
      assert.equal(await page.locator('.ep-tile.selected').count(),0,'late checks do not reselect submitted episodes');
      assert.equal(queueRequests.length,1);
      assert.equal(await page.locator('#series-add-btn').isDisabled(),true);
      await page.locator('#series-detail-close').click();
      assert.deepEqual(run.errors, []);
      console.log(JSON.stringify({width, immediateFeedback: true, progressiveSelection: true, cancelledSelection: true, deferredDownload:true}));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exit(1); });
