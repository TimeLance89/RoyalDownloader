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
      assert.equal(await page.locator('[data-nav-menu-scrim]').evaluate(e => getComputedStyle(e).display), 'none');
      const menu = page.locator('[data-nav-menu="mobile"] .nav-menu-trigger');
      if (await menu.isVisible()) {
        await menu.tap();
        assert.equal(await page.locator('[data-nav-menu-scrim]').evaluate(e => e.hidden), false);
        assert.notEqual(await page.locator('[data-nav-menu-scrim]').evaluate(e => getComputedStyle(e).display), 'none');
        await menu.tap();
        assert.equal(await page.locator('[data-nav-menu-scrim]').evaluate(e => getComputedStyle(e).display), 'none');
      }
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
      // Both physical edges must wrap to precisely the same visible card sequence.
      const seams = await page.locator(track).evaluate(track => {
        const visible = () => {
          const r = track.getBoundingClientRect();
          return [...track.children].map(c => ({ key: c.dataset.key, x: c.getBoundingClientRect().left - r.left - track.clientLeft,
            right: c.getBoundingClientRect().right - r.left - track.clientLeft }))
            .filter(c => c.right > 2 && c.x < track.clientWidth - 2);
        };
        return [0, track.scrollWidth - track.clientWidth].map(edge => {
          track.scrollLeft = edge;
          const before = visible(), start = track.scrollLeft;
          fixtureApp.home.carousel.normalizeHomeRailLoop(track);
          return { before, after: visible(), start, end: track.scrollLeft, size: fixtureApp.home.carousel.homeRailLoopSize(track), moved: Math.abs(track.scrollLeft - start) > 100 };
        });
      });
      for (const seam of seams) {
        if (process.env.ROYAL_TOUCH_DEBUG) console.log(JSON.stringify(seam));
        assert.ok(seam.moved, 'edge wraps');
        assert.deepEqual(seam.after.map(c => c.key), seam.before.map(c => c.key), 'same cards across seam');
        seam.before.forEach((c, i) => assert.ok(Math.abs(c.x - seam.after[i].x) <= 2, 'no visible seam jump'));
      }
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
      const historyBefore = await position();
      await page.evaluate(() => { history.pushState({}, '', '#carousel-check'); history.back(); });
      await page.waitForFunction(() => location.hash !== '#carousel-check');
      await page.goForward();
      assert.ok(Math.abs(await position() - historyBefore) < 2, 'same-document history preserves rail');
      const anchor = () => page.locator(track).evaluate(e => {
        const left = e.getBoundingClientRect().left;
        const cards = [...e.children];
        const index = cards.findIndex(c => c.getBoundingClientRect().right > left + 2);
        const card = cards[index], rect = card.getBoundingClientRect();
        const stride = cards[index + 1].getBoundingClientRect().left - rect.left;
        return { key: card.dataset.key, fraction: (rect.left - left) / stride };
      });
      const orientationAnchor = await anchor();
      await page.setViewportSize({ width: viewport.height, height: viewport.width });
      await page.waitForTimeout(300);
      await page.setViewportSize(viewport);
      await page.locator(track).scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      const restoredAnchor = await anchor();
      assert.equal(restoredAnchor.key, orientationAnchor.key, 'orientation keeps logical anchor');
      assert.ok(Math.abs(restoredAnchor.fraction - orientationAnchor.fraction) < 0.015, 'orientation keeps fractional offset');
      const orientationStart = await position();
      await swipe(page, cdp, track, -260);
      await page.waitForTimeout(700);
      const orientationMoved = Math.abs(await position() - orientationStart) > 20;
      // Use the actual presenter on both sides of the tab transition. The benchmark's
      // seven synthetic rails intentionally differ from its domain-selected lanes.
      await page.evaluate(() => fixtureApp.core.actions.switchTab('home'));
      await page.waitForTimeout(300);
      const tabTrack = await page.evaluate(() => {
        const e = [...document.querySelectorAll('#tab-home .home-track')].find(e => Number(e.dataset.homeLoopCount) > 3 && e.clientWidth);
        if (!e) throw new Error('fixture needs a real populated presenter rail');
        e.scrollLeft = (Number(e.dataset.homeLoopLeading) + 2) * Number(e.dataset.homeLoopStride);
        return '#' + e.id;
      });
      await page.waitForTimeout(350);
      const beforeTab = await page.locator(tabTrack).evaluate(e => e.scrollLeft);
      const tabGeometry = await page.locator(tabTrack).evaluate(e => ({ id: e.id, width: e.clientWidth, stride: e.dataset.homeLoopStride, count: e.dataset.homeLoopCount, leading: e.dataset.homeLoopLeading }));
      await page.evaluate(() => fixtureApp.core.actions.switchTab('releases'));
      await page.waitForTimeout(200);
      await page.evaluate(() => fixtureApp.home.homePresenter.render());
      await page.evaluate(() => fixtureApp.core.actions.switchTab('home'));
      await page.waitForTimeout(350);
      const afterTab = await page.locator(tabTrack).evaluate(e => e.scrollLeft);
      if (process.env.ROYAL_TOUCH_DEBUG) console.log({ beforeTab, afterTab, tabGeometry, after: await page.locator(tabTrack).evaluate(e => ({ width: e.clientWidth, stride: e.dataset.homeLoopStride, count: e.dataset.homeLoopCount, leading: e.dataset.homeLoopLeading })) });
      const result = { viewport, start, left, right, stable, swipeClicks, gestureWrites, tapOpened,
        verticalDelta: pageAfter - pageBefore, tabDelta: Math.abs(afterTab - beforeTab),
        orientationMoved, seams, errors: f.errors };
      results.push(result); console.log(JSON.stringify(result));
      if (!diagnostic) {
        assert.ok(left > start + 20, "left swipe advances");
        assert.ok(right < left - 20, "right swipe reverses");
        assert.ok(stable, "momentum settles");
        assert.equal(swipeClicks, 0, "swipe must not click");
        assert.deepEqual(gestureWrites, [], "no scrollLeft rewrites during native gesture");
        assert.ok(result.verticalDelta > 30, "vertical page scroll over cards");
        assert.ok(result.orientationMoved, "carousel survives orientation changes");
        assert.ok(result.tabDelta < 2, 'same catalog tab transition preserves position');
        assert.deepEqual(f.errors, []);
      }
    } finally { await f.close(); }
  }
  if (process.env.ROYAL_PERF_OUTPUT) {
    mkdirSync(process.env.ROYAL_PERF_OUTPUT, { recursive: true });
    writeFileSync(resolve(process.env.ROYAL_PERF_OUTPUT, "mobile.json"), JSON.stringify(results, null, 2));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
