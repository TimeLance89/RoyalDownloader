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
      const geometry = () => page.evaluate(() => [document.getElementById("home-hero"), ...document.querySelectorAll("#tab-home .home-rail")].map(el => ({id:el.id,top:el.offsetTop,height:el.offsetHeight})));
      const before = await geometry();
      const heroTitle = await page.locator("#home-hero-title").textContent();
      await page.screenshot({path:`artifacts/seasonal-events/${mobile?"mobile":"desktop"}-off.png`});
      enabled = true;
      await page.evaluate(()=>fixtureApp.home.seasonalEvents.load());
      for (let day = 28; day <= 31; day++) {
        await page.clock.setSystemTime(new Date(2026,9,day,12));
        await page.evaluate(() => fixtureApp.home.seasonalEvents.refresh());
        assert.equal(await page.locator("#tab-home").getAttribute("data-event-stage"), String(day-27));
        assert.equal(await page.locator(".home-event-ornaments img:not([hidden])").count(), [1,3,4,6][day-28]);
        assert.deepEqual(await geometry(), before, "Decorations must not move or resize the existing UI");
        assert.equal(await page.locator("#home-hero-title").textContent(), heroTitle);
        await page.emulateMedia({reducedMotion:"reduce"});
        assert.equal(await page.locator(".home-event-ornaments").evaluate(el=>el.getAnimations({subtree:true}).length), 0);
        assert.equal(await page.locator(".home-event-ornaments").evaluate(el=>getComputedStyle(el).pointerEvents), "none");
        assert.equal(await page.locator(".event-candle").isVisible(), day===31);
        await page.waitForFunction(()=>[...document.querySelectorAll(".home-event-ornaments img")].every(img=>img.complete && img.naturalWidth>0));
        await page.screenshot({path:`artifacts/seasonal-events/${mobile?"mobile":"desktop"}-${day}.png`});
      }
      await page.emulateMedia({reducedMotion:"no-preference"});
      await page.locator("#home-hero").scrollIntoViewIfNeeded();
      await page.waitForFunction(()=>!document.getElementById("tab-home").hasAttribute("data-event-lights-paused"));
      const lighting = await page.locator(".home-event-ornaments").evaluate(el=>el.getAnimations({subtree:true}).map(a=>({
        target:a.effect.target.className, state:a.playState,
        properties:[...new Set(a.effect.getKeyframes().flatMap(frame=>Object.keys(frame)))],
      })));
      assert.equal(lighting.length,2);
      assert.ok(lighting.every(a=>a.target.includes("event-light") && a.state==="running"));
      assert.ok(lighting.every(a=>a.properties.every(key=>["offset","computedOffset","easing","composite","opacity"].includes(key))));
      await page.evaluate(()=>{Object.defineProperty(document,"hidden",{configurable:true,value:true});document.dispatchEvent(new Event("visibilitychange"));});
      assert.equal(await page.locator(".event-light-candle").evaluate(el=>getComputedStyle(el).animationPlayState),"paused");
      await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event("visibilitychange"));});
      await page.locator("#home-gems-title").scrollIntoViewIfNeeded();
      await page.waitForFunction(()=>document.getElementById("tab-home").hasAttribute("data-event-lights-paused"));
      assert.equal(await page.locator(".event-light-pumpkins").evaluate(el=>getComputedStyle(el).animationPlayState),"paused");
      await page.locator("#home-movies-title").scrollIntoViewIfNeeded();
      await page.screenshot({path:`artifacts/seasonal-events/rails-${mobile?"mobile":"desktop"}.png`});
      await page.evaluate(()=>fixtureApp.core.localization.changeLanguage("en"));
      assert.equal(await page.locator(".home-event-ornaments").count(),1);
      await page.evaluate(()=>{fixtureApp.core.actions.switchTab("einstellungen"); document.querySelector('[data-settings-target="settings-general"]').click();});
      const toggle = page.locator("#seasonal-events-enabled");
      await page.waitForFunction(()=>!document.getElementById("seasonal-events-enabled").disabled);
      assert.equal(await toggle.isChecked(), true);
      await toggle.uncheck();
      await page.waitForFunction(()=>document.getElementById("seasonal-events-status").textContent.includes("Saved"));
      assert.deepEqual(writes,[{enabled:false}]);
      await page.evaluate(()=>fixtureApp.core.actions.switchTab("home"));
      assert.equal(await page.locator(".home-event-ornaments").count(),0);
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
      await page.waitForSelector(".home-event-ornaments");
      await page.clock.setSystemTime(new Date(2026,9,31,23,59,59));
      await page.evaluate(()=>fixtureApp.home.seasonalEvents.refresh());
      await page.clock.fastForward(1200);
      assert.equal(await page.locator(".home-event-ornaments").count(),0);
      await page.clock.setSystemTime(new Date(2027,9,28,12));
      await page.evaluate(()=>fixtureApp.home.seasonalEvents.refresh());
      assert.equal(await page.locator("#tab-home").getAttribute("data-event-stage"),"1");
      await page.evaluate(()=>fixtureApp.core.actions.switchTab("filme"));
      assert.equal(await page.locator(".home-event-ornaments").count(),0);
      assert.deepEqual(errors,[]);
      console.log(JSON.stringify({mobile,passed:true,stages:4,toggle:true,saveFailure:true,midnight:true,lighting:true}));
    } finally { await run.close(); }
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
