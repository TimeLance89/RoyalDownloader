const assert = require('node:assert/strict');
const { fixture } = require('./performance-fixture.cjs');

(async () => {
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, engine: process.env.ROYAL_BROWSER || 'chromium', viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      const work = (id, type, title) => ({ tmdb_id: id, slug: `tmdb:${id}`, media_type: type, title, original_title: title, year: '2020', release_date: '2020-01-01', cover_url: '/fixture-art.svg', roles: ['Leading role'], departments: ['Acting'], popularity: 10 - id });
      const credits = [work(1, 'movie', 'Available film'), work(2, 'movie', 'Owned film'), work(3, 'movie', 'Unavailable film'), work(1, 'tv', 'Series with same ID'), { ...work(4, 'movie', 'Future film'), release_date: '2099-01-01', year: '2099' }];
      const person = { id: 42, name: 'Florence Pugh', department: 'Acting', profile_url: '/fixture-art.svg', birthplace: 'Oxford, England', birthday: '1996-01-03', biography: 'An actor with stories across films and television.', credits };
      const queues = [], lookups = [], seriesLookups = [];
      let failProfile = true;
      await page.route('**/api/**', async route => {
        const url = new URL(route.request().url()), path = url.pathname;
        if (path === '/api/people') return route.fulfill({ json: { results: [{ ...person, known_for: ['Little Women', 'Dune'] }], total_pages: 2 } });
        if (path === '/api/people/42') {
          if (failProfile) { failProfile = false; return route.fulfill({ status: 503, json: { detail: 'TMDB nicht erreichbar' } }); }
          return route.fulfill({ json: { person } });
        }
        if (path === '/api/people/series/1') {
          seriesLookups.push(path);
          return route.fulfill({ json: { ...credits[3], base_slug: 'verified-series', sample_slug: 'verified-series', seasons: [], episode_count: 0, cast: [{ id: 42, name: 'Florence Pugh' }] } });
        }
        if (path === '/api/series/jellyfin-status') return route.fulfill({ json: { configured: false, available: true, episodes: {} } });
        if (path === '/api/tmdb/series') return route.fulfill({ json: { series: {}, pending: [] } });
        if (path === '/api/jellyfin/matches') {
          const items = route.request().postDataJSON().items;
          return route.fulfill({ json: { configured: true, available: true, statuses: Object.fromEntries(items.map(item => [item.slug, item.tmdb_id === 2 ? 'owned' : 'missing'])) } });
        }
        if (path.startsWith('/api/movie/')) {
          const id = Number(url.searchParams.get('tmdb_id')); lookups.push(id);
          if (id === 3) return route.fulfill({ status: 404, json: { detail: { code: 'movie_hoster_unavailable', message: 'Kein Hoster verfügbar' } } });
          return route.fulfill({ json: { ...credits.find(item => item.tmdb_id === id), hosters: id === 3 ? [] : [{ name: 'VOE', url: 'https://example.test/embed' }] } });
        }
        if (path === '/api/queue/add') { queues.push(route.request().postDataJSON()); return route.fulfill({ json: { count: 1, groups: [], added: 1, skipped_details: [] } }); }
        return route.fallback();
      });
      await page.evaluate(() => fixtureApp.core.actions.switchTab('personen'));
      await page.locator('#people-results button').first().waitFor();
      assert.equal(await page.locator('#people-search').evaluate(el => getComputedStyle(el).borderRadius), '6px');
      assert.equal(await page.locator('#people-search-form button').evaluate(el => getComputedStyle(el).borderRadius), '6px');
      await page.locator('#people-search').fill('Florence');
      await page.locator('#people-search-form button').click();
      await page.waitForFunction(() => document.getElementById('people-status').textContent.includes('Florence'));
      await page.locator('#people-results button').first().click();
      await page.locator('#people-retry').waitFor(); await page.locator('#people-retry').click();
      await page.locator('.people-profile-name').waitFor();
      assert.equal(await page.locator('#people-works button').count(), 5);
      await page.locator('#people-filter-type').selectOption('tv');
      assert.equal(await page.locator('#people-works button').count(), 1);
      assert.equal(await page.locator('#people-films').isDisabled(), true);
      await page.locator('#people-filter-type').selectOption('all');
      await page.locator('#people-filter-query').fill('same');
      assert.equal(await page.locator('#people-works button').count(), 1);
      await page.locator('#people-filter-query').fill('');
      assert.equal(await page.locator('#tab-personen').evaluate(el => el.scrollWidth <= el.clientWidth), true);
      if (process.env.ROYAL_PEOPLE_SCREENSHOTS) await page.screenshot({ path: `${process.env.ROYAL_PEOPLE_SCREENSHOTS}/people-${mobile ? 'mobile' : 'desktop'}.png`, fullPage: true });
      await page.locator('#people-films').click();
      await page.waitForFunction(() => !fixtureApp.discovery.movieCollections.get().resolving && fixtureApp.discovery.movieCollections.get().collection);
      await page.waitForFunction(() => document.getElementById('movie-collection-status').textContent.includes('vollständig geprüft'));
      assert.ok(!lookups.includes(2), 'owned films skip provider lookup');
      assert.ok(!lookups.includes(4), 'future films skip provider lookup');
      await page.locator('#movie-collection-select-all').click();
      assert.equal(await page.locator('#movie-collection-download-all').isDisabled(), true, 'toggle clears the confirmed selection');
      await page.locator('#movie-collection-select-all').click();
      await page.locator('#movie-collection-download-all').click();
      await page.waitForFunction(() => !fixtureApp.discovery.movieCollections.get().queuePending);
      assert.deepEqual(queues[0].slugs, ['tmdb:1'], 'only available missing films enter queue; TV identity never leaks');
      await page.evaluate(() => fixtureApp.core.actions.closeMediaModal('movie-collection-modal'));
      await page.locator('#people-works [data-media-type="tv"]').click();
      await page.waitForFunction(() => document.getElementById('series-detail-title').textContent === 'Series with same ID' && document.querySelector('#series-detail-about-cast button'));
      assert.deepEqual(seriesLookups, ['/api/people/series/1'], 'series opens using exact TMDB identity');
      await page.locator('#series-detail-about-cast button').click();
      await page.locator('.people-profile-name').waitFor();
      assert.equal(await page.locator('#series-detail-modal').isVisible(), false, 'cast link closes the old detail');
      await page.locator('#people-back').click();
      assert.equal(await page.locator('#people-search').inputValue(), 'Florence', 'directory search survives profile navigation');
      assert.deepEqual(errors, []);
      console.log(`People discovery ${mobile ? 'mobile' : 'desktop'} passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
