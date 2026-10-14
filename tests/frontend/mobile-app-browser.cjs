const assert = require('node:assert/strict');
const {mkdir} = require('node:fs/promises');
const {fixture} = require('./performance-fixture.cjs');
(async () => {
  const out = process.env.ROYAL_APP_SCREENSHOTS || 'artifacts/mobile-app';
  await mkdir(out, {recursive:true});
  for (const width of [320,360,390,430,768,1440]) {
    const mobile = width <= 820;
    const run = await fixture({viewport:{width,height:844},mobile,rate:mobile?4:1,engine:process.env.ROYAL_BROWSER||"chromium"});
    const {page} = run;
    try {
      await page.evaluate(() => {
        renderFixture();
        fixtureApp.home.homeData.get().loading = false;
        fixtureApp.home.actions.renderHome();
      });
      if (mobile) {
        assert.equal(await page.locator('.mobile-tabs .tab-icon svg').count(),5);
        await page.locator('#mobile-more-toggle').click();
        assert.equal(await page.evaluate(() => document.body.classList.contains('mobile-menu-open')),true);
        assert.equal(await page.locator('[data-nav-menu-close]').evaluate(e => e === document.activeElement),true);
        await page.keyboard.press('Shift+Tab');
        assert.equal(await page.locator('#mobile-more-menu').evaluate(e => e.contains(document.activeElement)),true);
        await page.keyboard.press('Tab');
        assert.equal(await page.locator('[data-nav-menu-close]').evaluate(e => e === document.activeElement),true);
        await page.screenshot({path:`${out}/menu-${width}.png`});
        await page.locator('[data-nav-menu-close]').click();
        assert.equal(await page.evaluate(() => document.body.classList.contains('mobile-menu-open')),false);
        await page.locator('#mobile-more-toggle').click();
        await page.locator('#mobile-more-menu [data-tab="kalender"]').click();
        assert.equal(await page.locator('#tab-kalender').evaluate(e => e.classList.contains('active')),true);
        assert.equal(await page.evaluate(() => document.body.classList.contains('mobile-menu-open')),false);
      }
      if (mobile) {
        await page.evaluate(() => {
          fixtureApp.subscriptions.subscriptions.accept({ watchlist: [{ base_slug: "inbox-mobile", title: "Mobile Inbox", status: "failed", open_count: 2, failed_count: 1 }], health: {} });
          window.mobileNavigationSamples = [];
          document.querySelector(".mobile-tabs").addEventListener("click", event => {
            const button = event.target.closest("[data-tab]");
            if (!button) return;
            const started = performance.now();
            requestAnimationFrame(() => mobileNavigationSamples.push({ tab: button.dataset.tab, paintMs: performance.now()-started,
              active: document.getElementById(`tab-${button.dataset.tab}`).classList.contains("active") }));
          }, { capture: true });
        });
        assert.equal(await page.locator("[data-notif-mobile-badge]").textContent(), "1");
        await page.locator("#mobile-more-toggle").tap();
        await page.locator("#mobile-inbox-open").tap();
        assert.equal(await page.locator("#notif-dropdown").isVisible(), true, "Mobile menu opens the existing inbox despite its hidden desktop trigger");
        assert.equal(await page.evaluate(() => document.body.classList.contains("mobile-menu-open")), false);
        assert.equal(await page.evaluate(() => document.activeElement.id), "notif-close");
        const inbox = await page.locator("#notif-dropdown").boundingBox();
        assert.ok(inbox.x >= 0 && inbox.x+inbox.width <= width+1 && inbox.y+inbox.height <= 844-60, "Inbox stays between mobile header and navigation");
        await page.locator('[data-notif-filter="issue"]').tap();
        assert.equal(await page.locator(".notif-item").count(), 1);
        await page.screenshot({scale:"css",path:`${out}/inbox-${width}.png`});
        await page.keyboard.press("Escape");
        assert.equal(await page.locator("#notif-dropdown").isVisible(), false);
        assert.equal(await page.evaluate(() => document.activeElement.id), "mobile-more-toggle");
        for (const tab of ["filme", "serien", "home"]) {
          await page.locator(`.mobile-tabs [data-tab="${tab}"]`).tap();
          assert.equal(await page.locator(`#tab-${tab}`).evaluate(e => getComputedStyle(e).animationName), "none", "No catalog-wide blur animation delays mobile navigation");
        }
        await page.waitForFunction(() => mobileNavigationSamples.length === 3);
        const samples = await page.evaluate(() => mobileNavigationSamples);
        assert.ok(samples.every(sample => sample.active), "Navigation is active at its first paint");
        console.log(JSON.stringify({width, mobileNavigationSamples:samples}));
      }
      await page.evaluate(() => {
        fixtureApp.core.actions.switchTab('serien',{autoLoad:false});
        const episodes = Array.from({length:60},(_,i) => ({slug:`serienstream:fixture-s01e${i+1}`,season:1,episode:i+1,
          language_checked:true, language_available:i!==0, content_languages:[i===0?'en':'de']}));
        fixtureApp.discovery.seriesActions.showSeriesDetail({base_slug:'serienstream:fixture',provider:'serienstream',
          title:'Royal Serien',description:'Staffeln entdecken und passende Folgen auswählen.',enabled_content_languages:['de'],
          seasons:[{season:1,episodes}],episode_count:60,backdrop_url:'/fixture-art.svg',
          trailer:{site:'YouTube',key:'abcdefghijk',name:'Official preview'}},episodes[0].slug);
      });
      await page.locator('#series-tiles .ep-tile').nth(1).click();
      assert.equal(await page.locator('#series-detail-trailer').isVisible(), true,
        'series detail always offers a discoverable trailer action');
      assert.match(await page.locator('#series-detail-trailer').textContent(), /Trailer/);
      if (mobile) {
        await page.waitForTimeout(2200);
        assert.equal(await page.locator('#series-detail-hero-frame').getAttribute('src'), null,
          'mobile series must not autoplay video behind the synopsis');
        const watch = await page.locator('#series-watch-btn').boundingBox();
        const trailer = await page.locator('#series-detail-trailer').boundingBox();
        assert.ok(watch && trailer && Math.abs(watch.y - trailer.y) < 8,
          'trailer and subscription are the first two mobile actions');
        assert.ok(watch.x + watch.width <= trailer.x + 1,
          'mobile trailer and subscription buttons cannot overlap');
        const panel = await page.locator('#series-detail-modal .media-modal-panel').boundingBox();
        assert.equal(Math.round(panel.width),width); assert.equal(Math.round(panel.height),844);
        assert.equal(Math.round(panel.x),0); assert.equal(Math.round(panel.y),0);
        const dock = await page.locator('.series-selection-dock').boundingBox();
        assert.equal(Math.round(dock.y+dock.height),844, 'download action remains at viewport bottom');
        assert.ok(dock.x>=0 && dock.x+dock.width<=width+1);
        assert.equal(await page.locator('#series-add-btn').isEnabled(),true);
        assert.equal(await page.locator('#series-tiles .ep-tile').first().isDisabled(),true);
        await page.locator('#series-detail-modal .media-modal-panel').evaluate(e => { e.scrollTop=e.scrollHeight; });
        const close = await page.locator('#series-detail-close').boundingBox();
        const button = await page.locator('#series-add-btn').boundingBox();
        assert.ok(close.y>=0 && close.y+close.height<=844 && close.height>=44);
        assert.ok(button.y+button.height<=844 && button.height>=44);
        await page.screenshot({path:`${out}/series-${width}.png`});
        await page.setViewportSize({width,height:420});
        const shortDock = await page.locator('.series-selection-dock').boundingBox();
        assert.equal(Math.round(shortDock.y+shortDock.height),420);
      } else {
        assert.equal(await page.locator('.series-selection-dock').evaluate(e => getComputedStyle(e).display),'contents');
        assert.equal(await page.locator('#series-detail-close .modal-back-icon').isVisible(),false);
      }
      await page.evaluate(() => {
        window.__trailerSearch = null;
        window.open = (...args) => { window.__trailerSearch = args; return null; };
        fixtureApp.discovery.seriesActions.configureSeriesTrailer({title:'Royal Serien',year:2026});
      });
      assert.match(await page.locator('#series-detail-trailer').textContent(), /Trailer suchen/);
      await page.locator('#series-detail-trailer').click();
      const manualTrailer = await page.evaluate(() => window.__trailerSearch);
      assert.ok(manualTrailer[0].startsWith('https://www.youtube.com/results?search_query='));
      assert.equal(manualTrailer[1], '_blank');
      assert.equal(manualTrailer[2], 'noopener,noreferrer');
      await page.locator('#series-detail-close').click();
      assert.equal(await page.locator('#series-detail-modal').isVisible(),false);
      assert.equal(await page.evaluate(() => document.body.classList.contains('media-modal-open')),false);
      assert.deepEqual(run.errors,[]);
      console.log(JSON.stringify({width,appNavigation:true,detailControls:true}));
    } finally {await run.close();}
  }
})().catch(error => {console.error(error);process.exit(1);});
