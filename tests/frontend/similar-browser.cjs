const assert = require('node:assert/strict');
const { fixture } = require('./performance-fixture.cjs');

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, engine: process.env.ROYAL_BROWSER || 'chromium', viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      const consoleErrors = [];
      page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
      const item = id => ({ tmdb_id: id, slug: `tmdb:${id}`, title: `Similar ${id}`, year: '2026', rating: 7.3,
        backdrop_url: '/fixture-art.svg', cover_url: '/fixture-art.svg', description: `Recommendation ${id}`,
        genres: ['Drama'], original_language: 'de', original_title: `Original ${id}`, metadata_source: 'TMDB' });
      const full = id => ({ ...item(id), description: `Complete metadata ${id}`, countries: ['Deutschland'],
        spoken_languages: ['Deutsch'], details_loaded: true, similar_titles: [item(id + 1), item(id + 2)] });
      let releaseLibrary, releaseOld;
      const libraryGate = new Promise(resolve => { releaseLibrary = resolve; });
      const oldGate = new Promise(resolve => { releaseOld = resolve; });
      const providerRequests = [];
      await page.route('**/api/**', async route => {
        const url = new URL(route.request().url());
        const path = url.pathname;
        if (path === '/api/tmdb/movie') return route.fulfill({ json: { movie: full(route.request().postDataJSON().tmdb_id) } });
        if (path === '/api/tmdb/series') {
          const items = route.request().postDataJSON().items;
          return route.fulfill({ json: { series: Object.fromEntries(items.filter(item => item.tmdb_id).map(item => [item.base_slug, full(item.tmdb_id)])), pending: [] } });
        }
        if (path.startsWith('/api/movie/')) {
          const id = Number(decodeURIComponent(path.split('/').at(-1)).split(':')[1]);
          providerRequests.push(id);
          if (id === 2) return route.fulfill({ status: 503, json: { detail: 'Cloudflare origin invalid or incomplete response' } });
          if (id === 4) await oldGate;
          return route.fulfill({ json: { title: `Similar ${id}`, description: '', genres: [], hosters: id === 6 ? [] : [{ name: 'VOE', url: 'https://example.test/embed' }] } });
        }
        if (path === '/api/jellyfin/matches') {
          const items = route.request().postDataJSON().items;
          if (items.some(item => item.tmdb_id === 2)) await libraryGate;
          return route.fulfill({ json: { configured: true, available: false, statuses: Object.fromEntries(items.map(item => [item.slug, 'unavailable'])) } });
        }
        if (path === '/api/series/load') {
          const title = route.request().postDataJSON().sample_slug;
          if (title === 'Similar 21') return route.fulfill({ status: 503, json: { detail: 'Cloudflare 520 origin error' } });
          return route.fulfill({ json: { title, base_slug: 'similar-series', description: '', genres: [], seasons: [], episode_count: 0 } });
        }
        if (path === '/api/series/jellyfin-status') return route.fulfill({ json: { configured: false, available: true, episodes: {} } });
        return route.fallback();
      });
      await page.evaluate(item => { void fixtureApp.discovery.movieDetailsLoader.open(item.slug, item); }, item(1));
      const waitMovie = async id => {
        await page.waitForFunction(id => document.getElementById('fp-detail-title').textContent === `Similar ${id}` && document.getElementById('fp-detail-desc').textContent === `Complete metadata ${id}` && !document.getElementById('fp-detail-availability').classList.contains('is-loading'), id);
        assert.match(await page.locator('#fp-detail-origin').textContent(), /Deutsch.*Deutschland/);
      };
      const similar = async id => {
        const card = page.locator(`#fp-detail-similar button[aria-label="Similar ${id} öffnen"]`);
        await card.scrollIntoViewIfNeeded(); await card[mobile ? 'tap' : 'click']();
      };
      await waitMovie(1);
      await similar(2); await waitMovie(2);
      assert.equal(await page.locator('#fp-detail-availability').textContent(), 'Anbieter derzeit nicht erreichbar');
      assert.equal(await page.locator('#fp-detail-title').textContent(), 'Similar 2');
      assert.ok(providerRequests.includes(2), 'provider completes while Jellyfin is still blocked');
      assert.doesNotMatch(await page.locator('#fp-detail-modal').textContent(), /Cloudflare|origin invalid/);
      releaseLibrary();
      await page.waitForFunction(() => document.querySelector('#fp-detail-jellyfin strong').textContent === 'Jellyfin nicht erreichbar');
      await similar(3); await waitMovie(3);
      assert.match(await page.locator('#fp-detail-availability').textContent(), /Hoster bereit/);
      await similar(4);
      await page.waitForFunction(() => document.getElementById('fp-detail-desc').textContent === 'Complete metadata 4');
      await similar(5); await waitMovie(5); releaseOld();
      await page.waitForTimeout(150);
      assert.equal(await page.locator('#fp-detail-title').textContent(), 'Similar 5');
      await similar(6); await waitMovie(6);
      assert.equal(await page.locator('#fp-detail-availability').textContent(), 'Derzeit nicht verfügbar');
      await page.evaluate(item => { void fixtureApp.discovery.seriesDetailsLoader.open({ ...item, sample_slug: item.title, base_slug: '', similar_titles: [{ ...item, tmdb_id: 21, title: 'Similar 21', description: 'Series recommendation 21' }] }); }, item(20));
      await page.waitForFunction(() => !document.querySelector('#series-tiles .series-loading'));
      const card = page.locator('#series-detail-similar button').first();
      await card.scrollIntoViewIfNeeded(); await card[mobile ? 'tap' : 'click']();
      await page.waitForFunction(() => document.getElementById('series-detail-title').textContent === 'Similar 21' && document.querySelector('#series-tiles .series-loading')?.textContent === 'Staffeln derzeit nicht verfügbar');
      await page.waitForFunction(() => document.getElementById('series-desc').textContent === 'Complete metadata 21');
      assert.doesNotMatch(await page.locator('#series-detail-modal').textContent(), /Cloudflare|origin error/);
      const nextSeries = page.locator('#series-detail-similar button[aria-label="Similar 22 öffnen"]');
      await nextSeries.scrollIntoViewIfNeeded(); await nextSeries[mobile ? 'tap' : 'click']();
      await page.waitForFunction(() => document.getElementById('series-detail-title').textContent === 'Similar 22' && document.getElementById('series-desc').textContent === 'Complete metadata 22' && !document.querySelector('#series-tiles .series-loading'));
      assert.deepEqual(errors, []);
      assert.equal(consoleErrors.length, 2, JSON.stringify(consoleErrors));
      assert.ok(consoleErrors.every(text => /^Failed to load resource: the server responded with a status of 503 \(Service Unavailable\)$/.test(text)), JSON.stringify(consoleErrors));
      console.log(JSON.stringify({ passed: true, mobile, similar: 'success, provider failure, library unavailable, race, recovery, no hoster, series failure' }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
