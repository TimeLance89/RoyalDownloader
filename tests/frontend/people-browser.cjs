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
      const largeCredits = Array.from({ length: 110 }, (_, i) => ({ ...work(100 + i, 'movie', `Archive ${i}`), departments: i < 2 ? ['Directing'] : ['Acting'], year: '1999', release_date: '1999-01-01' }));
      let delayLibrary = false, releaseLibrary, notifyLibraryStarted;
      const libraryGate = new Promise(resolve => { releaseLibrary = resolve; });
      const libraryStarted = new Promise(resolve => { notifyLibraryStarted = resolve; });
      await page.route('**/api/**', async route => {
        const url = new URL(route.request().url()), path = url.pathname;
        if (path === '/api/people') return route.fulfill({ json: { results: [{ ...person, known_for: ['Little Women', 'Dune'] },
          ...['Alex Morgan', 'Sam Rivera', 'Jamie Park', 'Taylor Reed', 'Robin Ellis'].map((name, i) => ({ ...person, id: 50 + i, name, department: i === 4 ? 'Writing' : 'Acting', known_for: ['Film fixture', 'Series fixture'] }))], total_pages: 2 } });
        if (path === '/api/people/42') {
          if (failProfile) { failProfile = false; return route.fulfill({ status: 503, json: { detail: 'TMDB nicht erreichbar' } }); }
          return route.fulfill({ json: { person } });
        }
        if (path === '/api/people/43') return route.fulfill({ json: { person: { ...person, id: 43, name: 'Director profile', department: 'Directing', credits: largeCredits } } });
        if (path === '/api/people/series/1') {
          seriesLookups.push(path);
          return route.fulfill({ json: { ...credits[3], base_slug: 'verified-series', sample_slug: 'verified-series', seasons: [], episode_count: 0, cast: [{ id: 42, name: 'Florence Pugh' }] } });
        }
        if (path === '/api/series/jellyfin-status') return route.fulfill({ json: { configured: false, available: true, episodes: {} } });
        if (path === '/api/tmdb/series') return route.fulfill({ json: { series: {}, pending: [] } });
        if (path === '/api/jellyfin/matches') {
          const items = route.request().postDataJSON().items;
          if (delayLibrary && items.some(item => item.tmdb_id >= 100)) { notifyLibraryStarted(); await libraryGate; }
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
      await page.locator('#people-directory-role').selectOption('Writing');
      assert.equal(await page.locator('#people-results button').count(), 1, 'directory filters are scoped to the current page');
      await page.locator('#people-directory-role').selectOption('all');
      if (process.env.ROYAL_PEOPLE_SCREENSHOTS) await page.screenshot({ path: `${process.env.ROYAL_PEOPLE_SCREENSHOTS}/people-directory-${mobile ? 'mobile' : 'desktop'}.png`, fullPage: true, animations: 'disabled' });
      assert.equal(await page.locator('#people-search').evaluate(el => getComputedStyle(el).borderRadius), '6px');
      assert.equal(await page.locator('#people-search-form button[type="submit"]').evaluate(el => getComputedStyle(el).borderRadius), '6px');
      await page.locator('#people-search').fill('Florence');
      await page.locator('#people-search-form button[type="submit"]').click();
      await page.waitForFunction(() => document.getElementById('people-status').textContent.includes('Florence'));
      await page.locator('#people-results button').first().click();
      await page.locator('#people-retry').waitFor(); await page.locator('#people-retry').click();
      await page.locator('.people-profile-name').waitFor();
      if (process.env.ROYAL_PEOPLE_SCREENSHOTS) await page.screenshot({ path: `${process.env.ROYAL_PEOPLE_SCREENSHOTS}/people-profile-${mobile ? 'mobile' : 'desktop'}.png`, fullPage: true });
      assert.equal(await page.locator('#people-works button').count(), 5);
      assert.equal(await page.locator('#people-highlights button').count(), 4, 'upcoming work is excluded from highlights');
      await page.locator('#people-works input[data-credit-select="movie:1"]').check();
      await page.locator('#people-filter-type').selectOption('tv');
      assert.match(await page.locator('#people-selection-note').textContent(), /ausgeblendet/);
      assert.equal(await page.locator('#people-works input[type="checkbox"]').count(), 0, 'series use episode selection');
      await page.locator('[data-people-action="clear-selection"]').click();
      await page.locator('#people-filter-type').selectOption('tv');
      assert.equal(await page.locator('#people-works button').count(), 1);
      assert.equal(await page.locator('#people-films').isDisabled(), true);
      await page.locator('#people-filter-type').selectOption('all');
      await page.locator('#people-filter-query').fill('same');
      assert.equal(await page.locator('#people-works button').count(), 1);
      await page.locator('#people-filter-query').fill('');
      await page.locator('#people-advanced-filters summary').click();
      await page.locator('#people-library-check').click();
      await page.waitForFunction(() => document.getElementById('people-library-status').textContent.includes('Bestände geprüft'));
      await page.locator('#people-filter-library').selectOption('owned');
      assert.equal(await page.locator('#people-works button').count(), 1, 'owned filter follows checked identity');
      assert.equal(await page.locator('#people-works input').isDisabled(), true, 'owned films cannot be marked');
      await page.locator('#people-filter-library').selectOption('missing');
      assert.equal(await page.locator('#people-works button').count(), 4, 'TV and film with same ID have separate statuses');
      await page.locator('#people-filter-library').selectOption('all');
      await page.locator('#people-filter-release').selectOption('upcoming');
      assert.equal(await page.locator('#people-works button').count(), 1);
      assert.equal(await page.locator('#people-works input').isDisabled(), true, 'future films cannot be marked');
      await page.locator('#people-filter-release').selectOption('all');
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
      assert.match(await page.locator('#people-recent').textContent(), /Florence Pugh/);
      assert.equal(await page.locator('#people-search').inputValue(), 'Florence', 'directory search survives profile navigation');
      await page.evaluate(() => fixtureApp.discovery.people.open(43));
      await page.waitForFunction(() => document.querySelector('.people-profile-name').textContent === 'Director profile');
      assert.equal(await page.locator('#people-works button').count(), 48, 'large filmography has a bounded initial DOM');
      await page.locator('#people-show-more').click();
      assert.equal(await page.locator('#people-works button').count(), 96);
      await page.locator('#people-advanced-filters').evaluate(el => { el.open = true; });
      await page.locator('#people-filter-role').selectOption('Directing');
      assert.equal(await page.locator('#people-works button').count(), 2, 'crew departments have independent filters');
      await page.locator('#people-works input').first().check();
      await page.evaluate(() => fixtureApp.discovery.people.open(43));
      assert.match(await page.locator('#people-selection-count').textContent(), /1 Filme/, 'same profile return preserves selection');
      delayLibrary = true;
      await page.locator('#people-library-check').click();
      let libraryDeadline;
      try { await Promise.race([libraryStarted, new Promise((_, reject) => { libraryDeadline = setTimeout(() => reject(new Error('Library request did not start')), 10_000); })]); }
      finally { clearTimeout(libraryDeadline); }
      await page.evaluate(() => fixtureApp.core.actions.switchTab('home'));
      releaseLibrary();
      await page.evaluate(() => fixtureApp.core.actions.switchTab('personen'));
      assert.match(await page.locator('#people-library-status').textContent(), /unterbrochen/);
      assert.equal(await page.locator('#people-library-check').isEnabled(), true);
      assert.match(await page.locator('.people-work-status').first().textContent(), /nicht geprüft/, 'late library response cannot update an unmounted profile');
      assert.deepEqual(errors, []);
      console.log(`People discovery ${mobile ? 'mobile' : 'desktop'} passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
