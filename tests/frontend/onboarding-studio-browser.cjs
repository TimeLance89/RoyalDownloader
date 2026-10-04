const assert = require('node:assert/strict');
const {mkdir}=require('node:fs/promises');
const {fixture}=require('./performance-fixture.cjs');
(async()=>{
  await mkdir('artifacts/onboarding-studio',{recursive:true});
  for(const width of [1440,390]){
    const run=await fixture({viewport:{width,height:1000},mobile:width===390});
    const {page,errors}=run;
    let failStatus=true, failSave=width===1440, required=true, catalogFailure=true, holdCatalog=false, release;
    const gate=new Promise(resolve=>release=resolve), writes=[];
    const providers={movies:['filmpalast','moviebox'],series:['serienstream','vidrift'],anime:['aniworld','mkissa'],enabled_movies:['filmpalast'],enabled_series:['serienstream'],enabled_anime:['aniworld'],content_languages:['de'],languages:{de:'Deutsch',en:'English'},labels:{filmpalast:'Filmpalast',moviebox:'MovieBox',serienstream:'SerienStream',vidrift:'VidRift',aniworld:'AniWorld',mkissa:'MKissa'},catalog:{filmpalast:{content_language:'de'},moviebox:{content_language:'en'},serienstream:{content_language:'de',content_languages:['de','en']},vidrift:{content_language:'en'},aniworld:{content_language:'de',content_languages:['de','en']},mkissa:{content_language:'en'}}};
    try {
      await page.route('**/api/setup/status',r=>{if(failStatus){failStatus=false;return r.fulfill({status:502,json:{detail:'Cloudflare token=secret'}});}return r.fulfill({json:{required,bootstrap_required:true,bootstrap_hint:'Fixture code',defaults:{ui_language_configured:true,ui_language:'de',existing_series_count:width===1440?2:0,providers,save_path:'/media/Filme',series_path:'/media/Serien'}}});});
      await page.route('**/api/setup/complete',r=>{writes.push(r.request().postDataJSON());if(failSave){failSave=false;return r.fulfill({status:502,json:{detail:'The origin web server returned an invalid or incomplete response to Cloudflare'}});}required=false;return r.fulfill({json:{saved:true}});});
      await page.route('**/api/providers/config',r=>r.fulfill({json:providers}));
      await page.route('**/api/ui/translate',r=>r.fulfill({json:{engine:'server',translations:r.request().postDataJSON().texts}}));
      await page.route('**/api/movies?**',async r=>{if(!required&&catalogFailure){catalogFailure=false;return r.fulfill({status:503,json:{detail:'Catalog unavailable'}});}if(holdCatalog)await gate;return r.fulfill({json:{results:[],sources:[]}});});
      await page.evaluate(()=>fixtureApp.settings.setup.refresh());
      assert.equal(await page.locator('#setup-wizard').getAttribute('data-state'),'load-error');
      assert.doesNotMatch(await page.locator('#setup-wizard').innerText(),/Cloudflare|token=secret/);
      await page.locator('#setup-next').click();
      await page.locator('#setup-wizard[data-state="editing"]').waitFor();
      assert.equal(await page.locator('#setup-ui-language').isVisible(),false);
      await page.locator('#setup-wizard').screenshot({path:`artifacts/onboarding-studio/welcome-${width}.png`});
      await page.locator('#setup-next').click();
      assert.equal(await page.locator('#setup-ui-language').isVisible(),true);
      assert.equal(await page.locator('.setup-source-details').evaluate(n=>n.open),false);
      assert.equal(await page.locator('#setup-subscription-choice').isVisible(),width===1440);
      if(width===1440)await page.locator('#setup-update-subscriptions').check();
      assert.equal(await page.locator('#setup-wizard').evaluate(n=>n.scrollWidth<=n.clientWidth+1),true);
      await page.locator('#setup-wizard').screenshot({path:`artifacts/onboarding-studio/language-${width}.png`});
      await page.locator('.setup-source-details summary').click();
      assert.equal(await page.locator('#setup-movie-provider-priority').isVisible(),true);
      await page.locator('.setup-source-details summary').click();
      await page.locator('#setup-next').click();
      await page.locator('#setup-next').click();
      await page.locator('#setup-tmdb-key').fill('fixture-key');
      await page.locator('#setup-next').click();
      await page.locator('#setup-next').click();
      await page.locator('#setup-auth-username').fill('fixture-owner');
      await page.locator('#setup-auth-password').fill('fixture-password');
      await page.locator('#setup-auth-password-repeat').fill('fixture-password');
      await page.locator('#setup-next').click();
      assert.equal(await page.locator('#setup-review > div').count(),width===1440?7:6);
      assert.doesNotMatch(await page.locator('#setup-review').innerText(),/fixture-password|fixture-key/);
      await page.locator('#setup-finish').click();
      assert.equal(writes.length,0);
      assert.equal(await page.locator('#setup-bootstrap-token').getAttribute('aria-invalid'),'true');
      await page.locator('#setup-bootstrap-token').fill('fixture-bootstrap');
      await page.locator('#setup-next').click();
      await page.locator('[data-setup-edit="2"]').first().click();
      assert.equal(await page.locator('#setup-update-subscriptions').isChecked(),width===1440);
      for(let step=2;step<7;step++)await page.locator('#setup-next').click();
      await page.locator('#setup-finish').focus(); await page.keyboard.press('Tab');
      assert.equal(await page.locator('#setup-wizard').evaluate(n=>n.contains(document.activeElement)),true);
      if(width===390){await page.emulateMedia({reducedMotion:'reduce'}); assert.equal(await page.locator('.setup-shell').evaluate(n=>getComputedStyle(n).animationName),'none');}
      await page.locator('#setup-wizard').screenshot({path:`artifacts/onboarding-studio/review-${width}.png`});
      await page.locator('#setup-finish').click();
      if(width===1440){await page.locator('#setup-status.error').waitFor(); assert.equal(required,true); assert.doesNotMatch(await page.locator('#setup-status').innerText(),/Cloudflare|origin web/); await page.locator('#setup-finish').click();}
      await page.locator('#setup-wizard[data-state="prepare-error"]').waitFor();
      assert.equal(writes.length,width===1440?2:1);
      assert.equal(await page.locator('#setup-auth-password').inputValue(),'');
      assert.equal(writes[0].bootstrap_token,'fixture-bootstrap');
      assert.equal(writes[0].update_existing_subscriptions,width===1440);
      assert.equal(await page.locator('#setup-back').isDisabled(),true);
      holdCatalog=true;
      await page.locator('#setup-finish').click();
      await page.locator('#setup-wizard[data-state="preparing"]').waitFor();
      await page.keyboard.press('Enter');
      assert.equal(writes.length,width===1440?2:1);
      await page.locator('#setup-wizard').screenshot({path:`artifacts/onboarding-studio/preparing-${width}.png`});
      release();
      await page.locator('#setup-wizard').waitFor({state:'hidden'});
      assert.equal(writes.length,width===1440?2:1);
      assert.deepEqual(errors,[]);
      console.log(JSON.stringify({width,passed:true,writes:writes.length}));
    }finally{release();await run.close();}
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
