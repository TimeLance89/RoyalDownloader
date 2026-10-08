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
      assert.equal(await page.locator('#series-add-btn').isDisabled(), true, 'pending intent cannot enter the queue');
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
      assert.match(await page.locator('#series-pick-count').textContent(), /0 ausgewählt · 8 in Prüfung/);
      assert.equal(await page.locator('#series-add-btn').isDisabled(), true);
      assert.equal(queueRequests.length, 0);
      assert.equal(await page.locator('.ep-tile .ep-language-lock').first().textContent(), 'PRÜFUNG');
      const held = requests.filter(route=>route.request().postDataJSON().slugs.some(slug=>slug.startsWith('sto:deferred')));
      assert.equal(held.length,2);
      for (const route of held) await respond(route);
      await page.waitForFunction(() => document.querySelectorAll('.ep-tile.selected').length === 8);
      await page.locator('#series-add-btn').click();
      await page.waitForFunction(() => document.querySelector('#series-status').textContent.includes('Merke 8'));
      while (!queueRequests.length) await page.waitForTimeout(10);
      assert.deepEqual(queueRequests[0].request().postDataJSON().slugs,
        Array.from({length:8},(_,i)=>`sto:deferred-s01e${i+1}`));
      await queueRequests[0].fulfill({json:{added:8,auto_started:8,done_jobs:0,total_jobs:8,
        queue:{count:8,groups:[],activity:{},providers:{}}}});
      await page.waitForFunction(() => document.querySelector('#series-status').textContent.includes('8/8 Episode(n) vorgemerkt'));
      assert.match(await page.locator('#series-status').textContent(), /Downloads starten automatisch/);
      await page.waitForFunction(() => document.querySelector('#series-probe-progress').textContent.includes('Prüfung abgeschlossen'));
      assert.equal(await page.locator('.ep-tile.selected').count(),0,'late checks do not reselect submitted episodes');
      assert.equal(queueRequests.length,1);
      assert.equal(await page.locator('#series-add-btn').isDisabled(),true);
      await page.unroute('**/api/series/episode-languages');
      const chicagoProbes = [];
      await page.route('**/api/series/episode-languages', async route => {
        const body = route.request().postDataJSON();
        chicagoProbes.push(body);
        assert.deepEqual(body.content_languages, ['de']);
        const pending = body.slugs.filter(slug => slug.endsWith('s14e01'));
        await route.fulfill({json: {selected_content_languages: ['de'], pending,
          available: Object.fromEntries(body.slugs.map(slug => [slug, false])),
          languages: Object.fromEntries(body.slugs.map(slug => [slug, pending.includes(slug) ? [] : ['en']]))}});
      });
      await page.evaluate(() => {
        fixtureApp.settings.providers.get().contentLanguages = new Set(['de', 'en']);
        const base = 'serienstream:chicago-pd';
        const seasons = [
          {season: 12, episodes: Array.from({length: 22}, (_, i) => ({season: 12, episode: i+1,
            slug: `${base}-s12e${String(i+1).padStart(2,'0')}`, downloaded: true, in_jellyfin: true}))},
          {season: 13, episodes: Array.from({length: 21}, (_, i) => ({season: 13, episode: i+1,
            slug: `${base}-s13e${String(i+1).padStart(2,'0')}`, downloaded: i<5, in_jellyfin: i<6,
            content_languages: i<6 ? ['de'] : ['en'], language_checked: true,
            language_available: true, language_profile: ['de', 'en']}))},
          {season: 14, episodes: Array.from({length: 4}, (_, i) => ({season: 14, episode: i+1,
            slug: `${base}-s14e${String(i+1).padStart(2,'0')}`, unreleased: i>0, provider_unreleased: i>0}))},
        ];
        fixtureApp.discovery.seriesActions.showSeriesDetail({base_slug: base, provider: 'serienstream',
          title: 'Chicago P.D.', enabled_content_languages: ['de'], seasons, episode_count: 47}, seasons[1].episodes[0].slug);
      });
      await page.locator('#series-select-all').click();
      await page.waitForFunction(() => document.querySelectorAll('.ep-tile.wrong-language').length === 15);
      assert.equal(await page.locator('.ep-tile.selected').count(), 0, 'EN-only S13E07–21 cannot be selected for German');
      assert.equal(await page.locator('#series-add-btn').isDisabled(), true);
      for (let episode = 7; episode <= 21; episode++) {
        const tile = page.locator(`[data-episode-slug="serienstream:chicago-pd-s13e${String(episode).padStart(2,'0')}"]`);
        assert.equal(await tile.isDisabled(), true);
        assert.equal(await tile.locator('.ep-language-lock').textContent(), 'NUR EN');
      }
      assert.equal(await page.locator('[data-episode-slug="serienstream:chicago-pd-s14e01"]').evaluate(node => node.classList.contains('selected')), false);
      assert.equal(queueRequests.length, 1, 'no additional queue request from missing German sources');
      assert.ok(chicagoProbes.length > 0);
      await page.locator('#series-detail-close').click();
      await page.unroute('**/api/series/episode-languages');
      for (const partial of [false, true]) {
        const probes = [];
        await page.route('**/api/series/episode-languages', route => {probes.push(route);});
        await page.evaluate(partial => {
          const base = `serienstream:hybrid-${partial ? 'partial' : 'new'}`;
          const seasons = Array.from({length: 15}, (_, index) => ({season: index+1,
            episodes: Array.from({length: 4}, (_, episode) => ({season: index+1, episode: episode+1,
              slug: `${base}-s${index+1}e${episode+1}`,
              downloaded: partial && index > 0 && index < 12,
              in_jellyfin: partial && index === 12 && episode < 2}))}));
          fixtureApp.discovery.seriesActions.showSeriesDetail({base_slug: base, provider: 'serienstream',
            title: 'Hybrid inventory fixture', enabled_content_languages: ['de'],
            jellyfin_configured: true, jellyfin_available: true, seasons, episode_count: 60}, seasons[0].episodes[0].slug);
        }, partial);
        await page.waitForFunction(() => document.querySelectorAll('.ep-tile').length === 60);
        while (probes.length < 2) await page.waitForTimeout(10);
        assert.ok(probes[0].request().postDataJSON().slugs[0].endsWith(partial ? 's13e3' : 's1e1'));
        assert.equal(await page.locator('#series-add-btn').isDisabled(), true);
        // Keep the first request pending; the other lane must keep making progress.
        await respond(probes[1]);
        while (probes.length < 3) await page.waitForTimeout(10);
        assert.ok(probes[2].request().postDataJSON().slugs[0].endsWith(partial ? 's1e1' : 's3e1'));
        await respond(probes[0]);
        let answered = 2;
        for (let turn = 0; turn < 100 && await page.locator('.ep-tile.language-pending').count(); turn++) {
          while (answered < probes.length) await respond(probes[answered++]);
          await page.waitForTimeout(10);
        }
        assert.equal(await page.locator('.ep-tile.language-pending').count(), 0);
        assert.equal(await page.locator('.ep-tile.selected').count(), 0, 'automatic order never creates a download selection');
        assert.equal(queueRequests.length, 1, 'automatic probes never enqueue downloads');
        await page.locator('#series-detail-close').click();
        await page.unroute('**/api/series/episode-languages');
      }
      assert.deepEqual(run.errors, []);
      console.log(JSON.stringify({width, immediateFeedback: true, progressiveSelection: true, cancelledSelection: true, verifiedDownload:true, chicagoGermanOnly:true, hybridInventoryOrder:true}));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exit(1); });
