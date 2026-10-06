const assert = require('node:assert/strict');
const {mkdir} = require('node:fs/promises');
const {fixture} = require('./performance-fixture.cjs');
(async () => {
  await mkdir('artifacts/episode-probe', {recursive:true});
  for (const width of [320,390,1440]) {
    const run = await fixture({viewport:{width,height:1000},mobile:width<820});
    const {page} = run;
    const requests = [], bodies = new Map();
    let progressCalls = 0;
    try {
      await page.route('**/api/series/episode-languages', route => {
        requests.push(route); const body = route.request().postDataJSON(); bodies.set(body.probe_id, body);
      });
      await page.route('**/api/series/episode-probe/*', route => {
        progressCalls++;
        const id = route.request().url().split('/').at(-1);
        const body = bodies.get(id);
        const providers = body ? [
          {slug:body.slugs[0],provider:'serienstream',label:'SerienStream',status:'checking'},
          {slug:body.slugs[0],provider:'huhu',label:'Huhu',status:'searching'},
          {slug:body.slugs[0],provider:'filmpalast',label:'Filmpalast',status:'waiting'},
        ] : [];
        return route.fulfill({contentType:'application/json',body:JSON.stringify({providers})});
      });
      await page.evaluate(() => {
        fixtureApp.core.actions.switchTab('serien',{autoLoad:false});
        const episodes = Array.from({length:8},(_,i)=>({slug:`sto:probe-s01e${i+1}`,season:1,episode:i+1}));
        fixtureApp.discovery.seriesActions.showSeriesDetail({base_slug:'sto:probe',provider:'serienstream',title:'Royal Prüfanzeige',
          enabled_content_languages:['de'],description:'',seasons:[{season:1,episodes}],episode_count:8},episodes[0].slug);
      });
      await page.locator('#series-tiles .season-btn').click();
      await page.waitForFunction(()=>document.querySelector('#series-probe-progress').textContent.includes('Huhu'));
      assert.equal(requests.length,2,'two bounded batches start together');
      const panel = page.locator('#series-probe-progress');
      assert.match(await panel.textContent(),/SerienStream/);
      assert.match(await panel.textContent(),/Sucht Serie, Episode und Quellen/);
      assert.match(await panel.textContent(),/Filmpalast/);
      const bounds = await panel.boundingBox();
      assert.ok(bounds.x>=0 && bounds.x+bounds.width<=width+1);
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({path:`artifacts/episode-probe/running-${width}.png`});
      const respond = async (route, deny = false) => {
        const {slugs} = route.request().postDataJSON();
        return route.fulfill({contentType:'application/json',body:JSON.stringify({
          languages:Object.fromEntries(slugs.map(slug=>[slug,[deny && slug.endsWith('e1')?'en':'de']])),
          available:Object.fromEntries(slugs.map(slug=>[slug,!(deny && slug.endsWith('e1'))]))})});
      };
      await respond(requests[1]);
      await page.waitForFunction(()=>document.querySelectorAll('.ep-tile.selected').length===4);
      assert.doesNotMatch(await panel.textContent(),/Prüfung abgeschlossen/,'slow first batch remains visible');
      await respond(requests[0],true);
      await page.waitForFunction(()=>document.querySelector('#series-probe-progress').textContent.includes('automatisch wiederholt'));
      assert.equal(await page.locator('[data-episode-slug="sto:probe-s01e1"]').isDisabled(),false);
      while (requests.length<3) await page.waitForTimeout(10);
      assert.deepEqual(requests[2].request().postDataJSON().slugs,['sto:probe-s01e1']);
      await respond(requests[2]);
      await page.waitForFunction(()=>document.querySelectorAll('.ep-tile.selected').length===8);
      assert.match(await panel.textContent(),/Prüfung abgeschlossen/);
      await page.locator('#series-detail-close').click();
      const stopped = progressCalls;
      await page.waitForTimeout(850);
      assert.equal(progressCalls,stopped,'progress polling ends with the request and view');
      assert.deepEqual(run.errors,[]);
      console.log(JSON.stringify({width,liveProviderProgress:true,concurrentBatches:true,automaticRecovery:true}));
    } finally {await run.close();}
  }
})().catch(error=>{console.error(error);process.exit(1);});
