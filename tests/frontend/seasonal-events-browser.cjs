const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  await mkdir("artifacts/seasonal-events", { recursive: true });
  for (const mobile of [false, true]) {
    const run = await fixture({ mobile, now: "2026-10-28T12:00:00", viewport: mobile ? {width:390,height:844} : {width:1440,height:1000} });
    const { page, errors } = run;
    let enabled = false, fail = false;
    const writes = [];
    try {
      await page.route("**/api/ui/events", async route => {
        if (route.request().method() === "POST") {
          writes.push(route.request().postDataJSON());
          if (fail) { fail = false; return route.fulfill({ status:500, json:{detail:"Preference not saved"} }); }
          enabled = route.request().postDataJSON().enabled;
        }
        return route.fulfill({json:{enabled}});
      });
      await page.evaluate(async () => { await fixtureApp.home.seasonalEvents.load(); renderFixture(); });
      const geometry = () => page.evaluate(() => [document.getElementById("home-hero"), ...document.querySelectorAll("#tab-home .home-rail")].map(el => ({id:el.id,top:Math.round(el.getBoundingClientRect().top + window.scrollY),height:el.offsetHeight})));
      const before = await geometry();
      const heroTitle = await page.locator("#home-hero-title").textContent();
      await page.screenshot({path:`artifacts/seasonal-events/${mobile?"mobile":"desktop"}-off.png`});
      enabled = true;
      await page.evaluate(()=>fixtureApp.home.seasonalEvents.load());
      for (let day = 28; day <= 31; day++) {
        await page.clock.setSystemTime(new Date(2026,9,day,12));
        await page.evaluate(() => fixtureApp.home.seasonalEvents.refresh());
        assert.equal(await page.locator("#tab-home").getAttribute("data-event-stage"), String(day-27));
        assert.equal(await page.locator(".home-event-backdrop img").count(), 1);
        assert.deepEqual(await geometry(), before, "Decorations must not move or resize the existing UI");
        assert.equal(await page.locator("#home-hero-title").textContent(), heroTitle);
        await page.emulateMedia({reducedMotion:"reduce"});
        await page.waitForFunction(()=>document.querySelector(".home-event-backdrop").getAnimations({subtree:true}).length===0);
        assert.equal(await page.locator(".home-event-backdrop").evaluate(el=>el.getAnimations({subtree:true}).length), 0);
        assert.equal(await page.locator(".home-event-backdrop").evaluate(el=>getComputedStyle(el).pointerEvents), "none");
        assert.equal(await page.locator(".home-event-backdrop img").evaluate(el=>Number(getComputedStyle(el).opacity)), [.20,.18,.15,.13][day-28]);
        await page.waitForFunction(()=>[...document.querySelectorAll(".home-event-backdrop img")].every(img=>img.complete && img.naturalWidth>0));
        await page.screenshot({path:`artifacts/seasonal-events/${mobile?"mobile":"desktop"}-${day}.png`});
      }
      await page.evaluate(()=>{
        window.eventFlashCount=0;
        const root=document.getElementById("tab-home");
        new MutationObserver(records=>{
          window.eventFlashCount+=records.filter(r=>r.oldValue===null && root.hasAttribute("data-event-lightning")).length;
        }).observe(root,{attributes:true,attributeOldValue:true,attributeFilter:["data-event-lightning"]});
      });
      await page.emulateMedia({reducedMotion:"no-preference"});
      await page.waitForFunction(()=>window.eventFlashCount>0,null,{timeout:7000});
      assert.equal(await page.locator(".home-event-flash").evaluate(el=>getComputedStyle(el).pointerEvents),"none");
      assert.equal(await page.locator("#tab-home > .home-event-flash").count(),1,"The flash belongs to Home, not the Hero");
      assert.equal(await page.locator(".home-event-flash img, .home-event-flash svg").count(),0,"No lightning drawings");
      await page.clock.fastForward(1200);
      assert.equal(await page.locator("#tab-home").getAttribute("data-event-lightning"),null);
      assert.equal(await page.locator(".event-lightning-flash").evaluate(el=>getComputedStyle(el).opacity),"0");
      await page.emulateMedia({reducedMotion:"reduce"});
      const reducedCount = await page.evaluate(()=>window.eventFlashCount);
      await page.clock.fastForward(65000);
      assert.equal(await page.evaluate(()=>window.eventFlashCount),reducedCount);
      assert.equal(await page.locator(".event-lightning-flash").isVisible(),false);
      await page.emulateMedia({reducedMotion:"no-preference"});
      await page.evaluate(()=>{Object.defineProperty(document,"hidden",{configurable:true,value:true});document.dispatchEvent(new Event("visibilitychange"));});
      const hiddenCount = await page.evaluate(()=>window.eventFlashCount);
      await page.clock.fastForward(30000);
      assert.equal(await page.evaluate(()=>window.eventFlashCount),hiddenCount,"Hidden tabs cancel flashes");
      await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event("visibilitychange"));});
      await page.locator("#home-gems-title").scrollIntoViewIfNeeded();
      assert.equal(await page.locator("#home-hero").evaluate(el=>el.getBoundingClientRect().bottom<0),true);
      for (const selector of [".home-event-backdrop", ".home-event-flash"]) {
        assert.deepEqual(await page.locator(selector).evaluate(el=>{
          const r=el.getBoundingClientRect();
          return {position:getComputedStyle(el).position,x:r.x,y:r.y,width:r.width,height:r.height};
        }),{position:"fixed",x:0,y:0,...page.viewportSize()},"Background covers the viewport even far below the Hero");
      }
      const scrolledCount = await page.evaluate(()=>window.eventFlashCount);
      await page.clock.fastForward(11000);
      await page.waitForFunction(count=>window.eventFlashCount>count,scrolledCount);
      await page.clock.fastForward(500);
      await page.screenshot({path:`artifacts/seasonal-events/rails-${mobile?"mobile":"desktop"}.png`});
      // Freeze a real opacity animation for visual review of its stacking below cards/text.
      await page.evaluate(()=>{
        document.getElementById("tab-home").dataset.eventLightning="true";
        const light=document.querySelector(".event-lightning-flash");
        for(const animation of light.getAnimations()){animation.pause();animation.currentTime=22.4;}
      });
      await page.screenshot({path:`artifacts/seasonal-events/flash-${mobile?"mobile":"desktop"}.png`});
      await page.evaluate(()=>delete document.getElementById("tab-home").dataset.eventLightning);
      await page.evaluate(()=>fixtureApp.core.localization.changeLanguage("en"));
      assert.equal(await page.locator(".home-event-backdrop").count(),1);
      await page.evaluate(()=>{fixtureApp.core.actions.switchTab("einstellungen"); document.querySelector('[data-settings-target="settings-general"]').click();});
      const toggle = page.locator("#seasonal-events-enabled");
      await page.waitForFunction(()=>!document.getElementById("seasonal-events-enabled").disabled);
      assert.equal(await toggle.isChecked(), true);
      await toggle.uncheck();
      await page.waitForFunction(()=>document.getElementById("seasonal-events-status").textContent.includes("Saved"));
      assert.deepEqual(writes,[{enabled:false}]);
      await page.evaluate(()=>fixtureApp.core.actions.switchTab("home"));
      assert.equal(await page.locator(".home-event-backdrop").count(),0);
      assert.equal(await page.locator(".home-event-flash").count(),0);
      assert.equal(await page.locator("#tab-home").getAttribute("data-seasonal-event"),null);
      await page.evaluate(()=>{fixtureApp.core.actions.switchTab("einstellungen"); document.querySelector('[data-settings-target="settings-general"]').click();});
      await page.waitForFunction(()=>!document.getElementById("seasonal-events-enabled").disabled);
      fail = true;
      await toggle.check();
      await page.waitForFunction(()=>document.getElementById("seasonal-events-status").textContent.includes("Preference not saved"));
      assert.equal(await toggle.isChecked(),false);
      await toggle.check();
      await page.waitForFunction(()=>document.getElementById("seasonal-events-status").textContent.includes("Saved"));
      await page.screenshot({path:`artifacts/seasonal-events/settings-${mobile?"mobile":"desktop"}.png`});
      await page.evaluate(()=>fixtureApp.core.actions.switchTab("home"));
      await page.waitForSelector(".home-event-backdrop");
      await page.clock.setSystemTime(new Date(2026,9,31,23,59,59));
      await page.evaluate(()=>fixtureApp.home.seasonalEvents.refresh());
      await page.clock.fastForward(1200);
      assert.equal(await page.locator(".home-event-backdrop").count(),0);
      await page.clock.setSystemTime(new Date(2027,9,28,12));
      await page.evaluate(()=>fixtureApp.home.seasonalEvents.refresh());
      assert.equal(await page.locator("#tab-home").getAttribute("data-event-stage"),"1");
      await page.evaluate(()=>fixtureApp.core.actions.switchTab("filme"));
      assert.equal(await page.locator(".home-event-backdrop").count(),0);
      assert.deepEqual(errors,[]);
      console.log(JSON.stringify({mobile,passed:true,stages:4,toggle:true,saveFailure:true,midnight:true,lighting:true}));
    } finally { await run.close(); }
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
