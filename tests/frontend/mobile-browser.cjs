const { fixture, swipe } = require("./performance-fixture.cjs");
const assert = require("node:assert/strict");
const { writeFileSync, mkdirSync } = require("node:fs");
const { resolve } = require("node:path");
const diagnostic = process.env.ROYAL_MOBILE_DIAGNOSTIC === "1";
const results = [];

(async () => {
  for (const viewport of [{ width: 390, height: 844 }, { width: 430, height: 932 }, { width: 768, height: 1024 }]) {
    const f = await fixture({ viewport, mobile: true });
    try {
      const { page, cdp } = f;
      await page.evaluate(() => renderFixture());
      const track = "#home-series-track";
      await page.locator(track).scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      await page.evaluate(() => {
        window.touchAudit = { active: false, writes: [], clicks: 0 };
        window.addEventListener("pointerdown", e => { if (e.pointerType === "touch") touchAudit.active = true; }, true);
        window.addEventListener("touchend", () => { touchAudit.active = false; }, true);
        window.addEventListener("touchcancel", () => { touchAudit.active = false; }, true);
        const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, "scrollLeft");
        Object.defineProperty(Element.prototype, "scrollLeft", { ...descriptor, set(value) {
          if (touchAudit.active && this.id === "home-series-track") touchAudit.writes.push({ before: descriptor.get.call(this), value });
          descriptor.set.call(this, value);
        } });
        document.getElementById("home-series-track").addEventListener("click", () => touchAudit.clicks++);
      });
      // Actual touch tap on a visible card: it must still open real movie details.
      const tapPoint = await page.locator(track).evaluate(e => {
        const r = e.getBoundingClientRect();
        const card = [...e.querySelectorAll('.home-card')].find(c => {
          const b = c.getBoundingClientRect(); return b.right > 60 && b.left < innerWidth - 60;
        });
        const b = card.getBoundingClientRect();
        return { x: Math.max(30, Math.min(innerWidth - 30, (Math.max(b.left, 0) + Math.min(b.right, innerWidth)) / 2)), y: r.top + r.height * 0.7 };
      });
      await page.touchscreen.tap(tapPoint.x, tapPoint.y);
      const tapOpened = await page.waitForFunction(() => !document.getElementById("fp-detail-modal").hidden, null, { timeout: diagnostic ? 600 : 5000 }).then(() => true, error => { if (!diagnostic) throw error; return false; });
      await page.evaluate(() => fixtureApp.core.actions.closeAllMediaModals(false));
      await page.waitForTimeout(350);
      await page.evaluate(() => { touchAudit.clicks = 0; touchAudit.writes = []; });
      const position = () => page.locator(track).evaluate(e => e.scrollLeft);
      const start = await position();
      await swipe(page, cdp, track, -230);
      await page.waitForTimeout(700);
      const left = await position();
      await swipe(page, cdp, track, 230);
      await page.waitForTimeout(700);
      const right = await position();
      for (let i = 0; i < 3; i++) await swipe(page, cdp, track, -180);
      await page.waitForTimeout(900);
      const settled = await position();
      await page.waitForTimeout(350);
      const stable = Math.abs(await position() - settled) < 2;
      const swipeClicks = await page.evaluate(() => touchAudit.clicks);
      // Start within the old leading clone, beyond its scroll-event wrap point.
      await page.evaluate(() => {
        const track = document.getElementById("home-series-track");
        track.scrollLeft = fixtureApp.home.carousel.homeRailLoopSize(track) * 0.3;
      });
      await page.waitForTimeout(250);
      await swipe(page, cdp, track, -150);
      await page.waitForTimeout(700);
      const gestureWrites = await page.evaluate(() => touchAudit.writes);
      const pageBefore = await page.evaluate(() => scrollY);
      await swipe(page, cdp, track, 0, -230);
      await page.waitForTimeout(700);
      const pageAfter = await page.evaluate(() => scrollY);
      await page.locator(track).scrollIntoViewIfNeeded();
      await page.evaluate(() => new Promise(resolve => {
        let last = scrollY, quiet = performance.now();
        const tick = () => { if (scrollY !== last) { last = scrollY; quiet = performance.now(); } if (performance.now() - quiet > 400) resolve(); else requestAnimationFrame(tick); }; tick();
      }));
      const beforeTab = await position();
      await page.evaluate(() => { fixtureApp.core.actions.switchTab("releases"); fixtureApp.core.actions.switchTab("home"); });
      // Fixture re-supplies the same catalog after the empty API-backed presenter refresh.
      await page.evaluate(() => renderFixture());
      await page.waitForTimeout(300);
      const afterTab = await position();
      await page.setViewportSize({ width: viewport.height, height: viewport.width });
      await page.waitForTimeout(300);
      await page.setViewportSize(viewport);
      await page.locator(track).scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      const orientationStart = await position();
      await swipe(page, cdp, track, -180);
      await page.waitForTimeout(700);
      const result = { viewport, start, left, right, stable, swipeClicks, gestureWrites, tapOpened,
        verticalDelta: pageAfter - pageBefore, tabDelta: Math.abs(afterTab - beforeTab),
        orientationMoved: Math.abs(await position() - orientationStart) > 20, errors: f.errors };
      results.push(result); console.log(JSON.stringify(result));
      if (!diagnostic) {
        assert.ok(left > start + 20, "left swipe advances");
        assert.ok(right < left - 20, "right swipe reverses");
        assert.ok(stable, "momentum settles");
        assert.equal(swipeClicks, 0, "swipe must not click");
        assert.deepEqual(gestureWrites, [], "no scrollLeft rewrites during native gesture");
        assert.ok(result.verticalDelta > 30, "vertical page scroll over cards");
        assert.ok(result.orientationMoved, "carousel survives orientation changes");
        assert.deepEqual(f.errors, []);
      }
    } finally { await f.close(); }
  }
  if (process.env.ROYAL_PERF_OUTPUT) {
    mkdirSync(process.env.ROYAL_PERF_OUTPUT, { recursive: true });
    writeFileSync(resolve(process.env.ROYAL_PERF_OUTPUT, "mobile.json"), JSON.stringify(results, null, 2));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
