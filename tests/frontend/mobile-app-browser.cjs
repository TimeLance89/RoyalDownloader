const assert = require('node:assert/strict');
const {mkdir} = require('node:fs/promises');
const {fixture} = require('./performance-fixture.cjs');
(async () => {
  const out = process.env.ROYAL_APP_SCREENSHOTS || 'artifacts/mobile-app';
  await mkdir(out, {recursive:true});
  for (const width of [320,390,430,768,1440]) {
    const mobile = width <= 820;
    const run = await fixture({viewport:{width,height:844},mobile});
    const {page} = run;
    try {
      await page.evaluate(() => renderFixture());
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
      await page.evaluate(() => {
        fixtureApp.core.actions.switchTab('serien',{autoLoad:false});
        const episodes = Array.from({length:60},(_,i) => ({slug:`serienstream:fixture-s01e${i+1}`,season:1,episode:i+1,
          language_checked:true, language_available:i!==0, content_languages:[i===0?'en':'de']}));
        fixtureApp.discovery.seriesActions.showSeriesDetail({base_slug:'serienstream:fixture',provider:'serienstream',
          title:'Royal Serien',description:'Staffeln entdecken und passende Folgen auswählen.',enabled_content_languages:['de'],
          seasons:[{season:1,episodes}],episode_count:60,backdrop_url:'/fixture-art.svg'},episodes[0].slug);
      });
      await page.locator('#series-tiles .ep-tile').nth(1).click();
      if (mobile) {
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
      await page.locator('#series-detail-close').click();
      assert.equal(await page.locator('#series-detail-modal').isVisible(),false);
      assert.equal(await page.evaluate(() => document.body.classList.contains('media-modal-open')),false);
      assert.deepEqual(run.errors,[]);
      console.log(JSON.stringify({width,appNavigation:true,detailControls:true}));
    } finally {await run.close();}
  }
})().catch(error => {console.error(error);process.exit(1);});
