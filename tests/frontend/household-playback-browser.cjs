const assert = require('node:assert/strict');
const { fixture } = require('./performance-fixture.cjs');

(async () => {
  for (const engine of process.env.ROYAL_BROWSER ? [process.env.ROYAL_BROWSER] : ['chromium', 'webkit']) {
    const run = await fixture({ engine });
    try {
      const result = await run.page.evaluate(async () => {
        const { createMoviePlayback } = await import('/js/features/media-details/movie-playback.js');
        const { createContinueWatching } = await import('/js/features/home/continue-watching.js');
        const { createStore } = await import('/js/core/store.js');
        const { createScope } = await import('/js/core/lifecycle.js');
        const { isPlaybackUser } = await import('/js/shared/playback-access.js');
        const tick = () => new Promise(resolve => setTimeout(resolve, 0));
        const store = createStore({ user: { id: 'a', role: 'member', enabled: true, updated_at: '1' } });
        const root = document.getElementById('fp-detail-modal');
        const dialog = document.getElementById('fp-movie-player');
        const button = root.querySelector('#fp-detail-play');
        const scope = createScope();
        let deny = false, releaseRead, releaseSession;
        const requests = [];
        const client = {
          get: async () => {
            if (deny) throw { status: 403 };
            if (releaseRead === null) return new Promise(resolve => { releaseRead = resolve; });
            return { profile_id: 'profile-a', generation: 1, position_ticks: 450000000, duration_ticks: 10000000000 };
          },
          post: url => { requests.push(url); return new Promise(resolve => { releaseSession = resolve; }); },
          delete: async url => requests.push(url),
        };
        const player = createMoviePlayback(root, { client, store, canPlay: () => isPlaybackUser(store.get().user), stopTrailer() {} });
        player.mount(scope);
        player.show('demo', { title: 'Demo' }); player.setOwned(true);
        await tick(); await tick();
        const memberResume = !button.hidden && !button.disabled && button.textContent.includes('00:45');
        // Delayed progress from a prior identity cannot repopulate controls.
        player.reset(); releaseRead = null;
        player.show('late', { title: 'Late' }); player.setOwned(true);
        await tick();
        store.set({ user: { id: 'b', role: 'member', enabled: true, updated_at: '2' } });
        releaseRead({ profile_id: 'profile-a', generation: 1, position_ticks: 999999999 });
        await tick();
        const staleReadDiscarded = button.hidden;
        releaseRead = undefined; deny = true;
        player.reset(); player.show('denied', { title: 'Denied' }); player.setOwned(true);
        await tick(); await tick();
        const deniedDisabled = button.disabled && button.textContent === 'Wiedergabe nicht verfügbar';
        deny = false;
        player.openItem({ id: 'episode', profile_id: 'profile-b', generation: 1, title: 'Demo', kind: 'movie' });
        const memberOpens = dialog.open;
        store.set({ user: { id: 'b', role: 'member', enabled: true, updated_at: '3' } });
        const closedOnMappingChange = !dialog.open && !dialog.querySelector('video').hasAttribute('src');
        releaseSession({ id: 'late-session', mode: 'direct', url: '/never-play' });
        await tick(); await tick();
        const lateSessionReleased = requests.includes('/api/media-center/playback/late-session') && !dialog.querySelector('video').hasAttribute('src');
        scope.dispose();
        const section = document.createElement('section');
        section.innerHTML = '<h2>Weiterschauen</h2><div class="home-track"></div>';
        document.body.append(section);
        let railRelease, forbidden = false;
        const rail = createContinueWatching(section, { store, openItem() {}, openDetails() {}, updateNavigation() {}, client: {
          get: async () => {
            if (forbidden) throw { status: 403 };
            return new Promise(resolve => { railRelease = resolve; });
          },
        } });
        rail.mount();
        railRelease({ items: [{ id: 'one', title: 'Private A', position_ticks: 10000000 }], profile_id: 'a', generation: 1 });
        await tick();
        const memberRail = section.querySelectorAll('.continue-card').length === 1;
        forbidden = true;
        store.set({ user: { id: 'c', role: 'member', enabled: true } });
        await tick();
        const railCleared = section.hidden && section.querySelectorAll('.continue-card').length === 0;
        rail.unmount(); section.remove();
        const { createSeriesBrowser } = await import('/js/features/media-details/series-browser.js');
        const seriesRoot = document.getElementById('series-detail-modal');
        const seriesScope = createScope();
        let rejectSeries = false;
        const seriesBrowser = createSeriesBrowser(seriesRoot, { store, canPlay: () => isPlaybackUser(store.get().user),
          openItem() {}, chooseDownload() {}, canDownload: () => false, client: { get: async () => {
            if (rejectSeries) throw {status:403};
            return { profile_id:'c', generation:1, items:[{id:'ep',kind:'episode',title:'Series',episode_title:'Pilot',season:1,episode:1,position_ticks:10000000}] };
          } },
        });
        seriesBrowser.mount(seriesScope);
        seriesBrowser.update({title:'Series',seasons:[]});
        await tick();
        const memberSeries = !seriesRoot.querySelector('#series-watch-episodes').hidden && seriesRoot.querySelectorAll('.series-watch-action').length === 1;
        rejectSeries = true;
        store.set({user:{id:'c',role:'member',enabled:true,updated_at:'mapping-changed'}});
        await tick();
        const seriesCleared = seriesRoot.querySelector('#series-watch-episodes').hidden && seriesRoot.querySelectorAll('.series-watch-action').length === 0;
        seriesBrowser.close(); seriesScope.dispose();
        return { memberSeries, seriesCleared, memberResume, staleReadDiscarded, deniedDisabled, memberOpens, closedOnMappingChange, lateSessionReleased, memberRail, railCleared };
      });
      for (const [name, passed] of Object.entries(result)) assert.equal(passed, true, `${engine}: ${name}`);
      assert.deepEqual(run.errors, []);
      console.log(JSON.stringify({ engine, ...result }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
