const assert = require('node:assert/strict');
const { fixture } = require('./performance-fixture.cjs');

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, engine: process.env.ROYAL_BROWSER || 'chromium', viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      let owner = 'a', failWrite = false, delayRead = false, releaseRead;
      const saved = new Map([['a', []], ['b', []]]), writes = [], queue = [];
      const gate = new Promise(resolve => { releaseRead = resolve; });
      const movie = id => ({ slug: `tmdb:${id}`, tmdb_id: id, title: `Movie ${id}`, year: '2020', cover_url: '/fixture-art.svg', details_loaded: true, hosters: [], genres: [] });
      const series = { base_slug: 'verified-series', sample_slug: 'verified-series', tmdb_id: 7, title: 'Series 7', year: '2020', seasons: [], episode_count: 0, cover_url: '/fixture-art.svg' };
      await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/me/saved-media') {
          const requestOwner = owner;
          if (route.request().method() === 'POST') {
            const body = route.request().postDataJSON(); writes.push({ owner: requestOwner, ...body });
            if (failWrite) return route.fulfill({ status: 503, json: { detail: 'Disk full' } });
            const items = saved.get(requestOwner).filter(item => !(item.media_type === body.media_type && item.tmdb_id === body.tmdb_id));
            if (body.saved) items.push(body);
            saved.set(requestOwner, items);
          } else if (delayRead) {
            delayRead = false;
            await gate;
          }
          return route.fulfill({ json: { items: saved.get(requestOwner), sync: { state: 'pending', ready: [] } } });
        }
        if (path.startsWith('/api/movie/')) return route.fulfill({ json: movie(Number(decodeURIComponent(path.split('/').pop()).split(':').pop())) });
        if (path === '/api/people/series/7') return route.fulfill({ json: series });
        if (path === '/api/series/jellyfin-status') return route.fulfill({ json: { configured: false, available: true, episodes: {} } });
        if (path === '/api/tmdb/series') return route.fulfill({ json: { series: {}, pending: [] } });
        if (path === '/api/queue/add') { queue.push(route.request().postDataJSON()); return route.fulfill({ json: {} }); }
        return route.fallback();
      });
      const open = async id => {
        await page.evaluate(({ id, item }) => { void fixtureApp.discovery.movieActions.selectFpRow(`tmdb:${id}`, item); }, { id, item: movie(id) });
        await page.waitForFunction(() => !document.getElementById('fp-detail-save').disabled);
      };
      const close = () => page.evaluate(() => fixtureApp.core.actions.closeMediaModal('fp-detail-modal'));
      await open(7);
      await page.locator('#fp-detail-save').click();
      await page.waitForFunction(() => document.getElementById('fp-detail-save').textContent === 'Gemerkt ✓');
      assert.match(await page.locator('#fp-detail-save-note').textContent(), /sobald verfügbar/);
      if (mobile) {
        const savedBounds = await page.locator('#fp-detail-save').boundingBox();
        assert.ok(savedBounds.width > 300 && savedBounds.x >= 0 && savedBounds.x + savedBounds.width <= 390, 'mobile save button spans its row without overflowing');
      }
      assert.equal(writes[0].media_type, 'movie');
      assert.equal(writes[0].tmdb_id, 7);
      assert.equal(Object.hasOwn(writes[0], 'jellyfin_user_id'), false);
      if (process.env.ROYAL_PEOPLE_SCREENSHOTS) await page.screenshot({ path: `${process.env.ROYAL_PEOPLE_SCREENSHOTS}/saved-movie-${mobile ? 'mobile' : 'desktop'}.png` });
      await close(); await open(7);
      assert.equal(await page.locator('#fp-detail-save').getAttribute('aria-pressed'), 'true');
      owner = 'b'; await close(); await open(7);
      assert.equal(await page.locator('#fp-detail-save').getAttribute('aria-pressed'), 'false', 'another profile does not inherit personal state');
      failWrite = true;
      await page.locator('#fp-detail-save').click();
      await page.waitForFunction(() => document.getElementById('fp-detail-save-note').textContent.includes('nicht geändert'));
      assert.equal(await page.locator('#fp-detail-save').getAttribute('aria-pressed'), 'false', 'failed writes never paint a saved state');
      failWrite = false;
      owner = 'a'; await close();
      await page.evaluate(() => { void fixtureApp.discovery.seriesActions.loadSeries({ base_slug: 'people-tmdb:7', sample_slug: 'people-tmdb:7', tmdb_id: 7, title: 'Series 7' }); });
      await page.waitForFunction(() => !document.getElementById('series-save').disabled && document.getElementById('series-detail-title').textContent === 'Series 7');
      assert.equal(await page.locator('#series-save').getAttribute('aria-pressed'), 'false', 'equal numeric film and TV identities are distinct');
      await page.locator('#series-save').click();
      await page.waitForFunction(() => document.getElementById('series-save').textContent === 'Gemerkt ✓');
      assert.equal(await page.locator('#series-detail-modal').evaluate(el => el.scrollWidth <= el.clientWidth), true, 'series save controls fit the detail');
      if (process.env.ROYAL_PEOPLE_SCREENSHOTS) await page.screenshot({ path: `${process.env.ROYAL_PEOPLE_SCREENSHOTS}/saved-series-${mobile ? 'mobile' : 'desktop'}.png` });
      await page.evaluate(() => fixtureApp.core.actions.closeMediaModal('series-detail-modal'));
      await open(7); await page.locator('#fp-detail-save').click();
      await page.waitForFunction(() => document.getElementById('fp-detail-save').getAttribute('aria-pressed') === 'false');
      assert.deepEqual(saved.get('a').map(item => item.media_type), ['tv'], 'removing a movie preserves the series');
      await close();
      delayRead = true;
      await page.evaluate(item => fixtureApp.discovery.moviePresentation.showFpDetail(item.slug, item), movie(7));
      await page.waitForTimeout(100);
      await open(8);
      releaseRead();
      await page.waitForTimeout(100);
      assert.equal(await page.locator('#fp-detail-save').getAttribute('aria-pressed'), 'false', 'late responses cannot overwrite the next title');
      assert.deepEqual(queue, [], 'saving a wish never queues downloads');
      assert.deepEqual(errors, []);
      console.log(`Personal saved media ${mobile ? 'mobile' : 'desktop'} passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
