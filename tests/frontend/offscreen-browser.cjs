const { fixture } = require('./performance-fixture.cjs');
const assert = require('node:assert/strict');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
(async () => {
  const f = await fixture({ rate: 6 });
  try {
    const { page, cdp } = f;
    await page.evaluate(() => {
      window.skippedRails = new Set();
      document.addEventListener('contentvisibilityautostatechange', e => {
        const id = e.target.querySelector('.home-track')?.id;
        if (e.skipped) skippedRails.add(id); else skippedRails.delete(id);
      }, true);
      renderFixture(true); scrollTo(0, 0);
    });
    await page.waitForTimeout(700);
    const skipped = await page.evaluate(() => [...skippedRails]);
    assert.ok(skipped.length > 0, 'far-offscreen rails actually skip rendering');
    const results = [];
    for (const mode of ['auto', 'visible', 'visible', 'auto']) {
      await page.evaluate(mode => {
        const tracks = [...document.querySelectorAll('[data-fixture-logical-count]')];
        window.offscreenTrack = tracks.at(-1).closest('.home-rail');
        offscreenTrack.style.contentVisibility = mode;
        window.offscreenTitles = [...offscreenTrack.querySelectorAll('.home-card-overlay > strong')];
      }, mode);
      await page.waitForTimeout(400);
      const before = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m => [m.name, m.value]));
      const heightBefore = await page.evaluate(() => document.documentElement.scrollHeight);
      await page.evaluate(async () => {
        for (let i = 0; i < 40; i++) {
          await new Promise(requestAnimationFrame);
          offscreenTitles.forEach((title, j) => { title.textContent = `Royal background update ${i} ${j}`; });
        }
        await new Promise(requestAnimationFrame);
      });
      const after = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m => [m.name, m.value]));
      const heightAfter = await page.evaluate(() => document.documentElement.scrollHeight);
      assert.ok(Math.abs(heightAfter - heightBefore) <= 1, 'stable document height');
      results.push({ mode, layoutCount: after.LayoutCount - before.LayoutCount, layoutMs: 1000 * (after.LayoutDuration - before.LayoutDuration) });
    }
    assert.ok(results.filter(r => r.mode === 'auto').every(r => r.layoutCount < 5), 'offscreen changes must not lay out each frame');
    assert.ok(results.filter(r => r.mode === 'visible').every(r => r.layoutCount >= 30), 'control really triggers layout');
    assert.deepEqual(f.errors, []);
    console.log(JSON.stringify({ skippedRails: skipped, results }));
    if (process.env.ROYAL_PERF_OUTPUT) {
      mkdirSync(process.env.ROYAL_PERF_OUTPUT, { recursive: true });
      writeFileSync(resolve(process.env.ROYAL_PERF_OUTPUT, 'offscreen.json'), JSON.stringify({ skippedRails: skipped, results }, null, 2));
    }
  } finally { await f.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
