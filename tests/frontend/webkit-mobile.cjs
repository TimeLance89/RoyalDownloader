// WebKit mobile layout, real touchscreen taps, and scroll/resize contracts.
// Playwright's public WebKit API cannot inject a continuous native touch swipe.
// Chromium's separate mobile-browser test owns that coverage; do not fake it here.
const { fixture } = require('./performance-fixture.cjs');
const assert = require('node:assert/strict');
(async () => {
  for (const viewport of [{ width: 390, height: 844 }, { width: 430, height: 932 }, { width: 768, height: 1024 }]) {
    const f = await fixture({ engine: 'webkit', mobile: true, viewport });
    try {
      const { page } = f;
      await page.evaluate(() => renderFixture());
      const track = page.locator('#home-series-track');
      await track.scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      assert.equal(await page.evaluate(() => devicePixelRatio), 3);
      await page.evaluate(() => {
        window.webkitTapPointers = [];
        document.addEventListener('pointerdown', e => webkitTapPointers.push(e.pointerType), true);
      });
      assert.equal(await page.locator('[data-nav-menu-scrim]').evaluate(e => getComputedStyle(e).display), 'none');
      const originals = track.locator('.home-card:not([aria-hidden])');
      assert.equal(await originals.count(), 16);
      assert.ok(await track.locator('.home-card').count() < 30);
      await originals.first().locator('.home-card-primary-action').tap();
      assert.ok((await page.evaluate(() => webkitTapPointers)).includes('touch'), 'actual touch pointer, not a mouse click');
      await page.waitForFunction(() => !document.getElementById('fp-detail-modal').hidden);
      await page.evaluate(() => fixtureApp.core.actions.closeAllMediaModals(false));
      for (const size of [{ width: viewport.height, height: viewport.width }, viewport]) {
        await page.setViewportSize(size);
        await track.scrollIntoViewIfNeeded();
        await page.waitForTimeout(350);
        const contract = await track.evaluate(e => {
          const style = getComputedStyle(e), before = e.scrollLeft;
          e.scrollLeft = before + 220;
          const moved = Math.abs(e.scrollLeft - before);
          e.scrollLeft = 0;
          fixtureApp.home.carousel.normalizeHomeRailLoop(e);
          return { moved, wrapped: e.scrollLeft > 100, overflow: style.overflowX, touchAction: style.touchAction,
            width: e.clientWidth, maximum: e.scrollWidth - e.clientWidth, loop: e.dataset.homeLoopCount, stride: e.dataset.homeLoopStride,
            interacting: fixtureApp.home.carousel.isInteracting(e) };
        });
        if (!contract.wrapped) console.log(contract);
        assert.ok(contract.moved > 100); assert.ok(contract.wrapped);
        assert.equal(contract.overflow, 'auto');
        assert.ok(['auto', 'manipulation', 'pan-x pan-y'].includes(contract.touchAction));
      }
      assert.deepEqual(f.errors, []);
      console.log(JSON.stringify({ engine: 'webkit', viewport, tap: true, scrollAndResizeContract: true, nativeContinuousSwipe: 'not exposed by public Playwright WebKit API' }));
    } finally { await f.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
