// Compare populated rails, not only the static shell. The frozen source is read-only.
const { fixture } = require('./performance-fixture.cjs');
const { resolve, dirname } = require('node:path');
const { pathToFileURL } = require('node:url');
const { mkdirSync, writeFileSync } = require('node:fs');
const assert = require('node:assert/strict');
const { edgeResidual } = require('./visual-diff.cjs');
const tooling = dirname(require.resolve(process.env.ROYAL_PLAYWRIGHT || 'playwright'));
const { PNG } = require(require.resolve('pngjs', { paths: [tooling] }));
const output = resolve(process.env.ROYAL_PERF_OUTPUT || 'artifacts/frontend-performance');
const baseline = process.env.ROYAL_VISUAL_BASELINE_WEB;
if (!baseline) throw new Error('Set ROYAL_VISUAL_BASELINE_WEB to frozen d3aada9/web');

// One CSS pixel of raster phase is already bounded by the geometry assertions.
// Require each changed edge pixel to have a matching neighbour in BOTH images;
// broad colour/image changes cannot disappear behind a larger raw diff budget.
(async () => {
  const { default: pixelmatch } = await import(pathToFileURL(require.resolve('pixelmatch', { paths: [tooling] })).href);
  mkdirSync(output, { recursive: true });
  const results = [];
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }, { width: 768, height: 1024 }]) {
    const captures = [];
    for (const webRoot of [baseline, undefined]) {
      const f = await fixture({ viewport, mobile: viewport.width < 1000, webRoot });
      try {
        const { page } = f;
        // Only the documented closed-menu correction is applied to legacy CSS.
        await page.addStyleTag({ content: '.nav-menu-scrim[hidden] { display:none !important; }' });
        await page.evaluate(() => renderFixture());
        const rails = await page.locator('[data-fixture-logical-count]').evaluateAll(es => es.map(e => e.id));
        const images = [];
        for (const id of rails) {
          const track = page.locator('#' + id);
          // Element screenshots do not account for sticky/fixed navigation.
          // Center both captures and prove the chrome cannot obscure the rail.
          await track.evaluate(element => element.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" }));
          await track.evaluate(e => {
            const first = [...e.children].find(c => c.dataset.renderSignature?.startsWith('loop:1:'));
            e.style.scrollSnapType = 'none'; // same logical starting offset on both implementations
            if (Number(e.dataset.homeLoopCount) > 1 && first) e.scrollLeft += first.getBoundingClientRect().left - e.getBoundingClientRect().left - 1;
          });
          await page.waitForTimeout(350);
          const unobscured = await track.evaluate(element => {
            const rail = element.getBoundingClientRect();
            const header = document.querySelector(".topbar").getBoundingClientRect();
            const nav = document.querySelector(".mobile-tabs");
            const bottom = getComputedStyle(nav).display === "none" ? innerHeight : nav.getBoundingClientRect().top;
            return rail.top >= header.bottom && rail.bottom <= bottom;
          });
          assert.ok(unobscured, id + " screenshot is clear of fixed navigation");
          // Page spacing can change the fractional Y origin of an otherwise
          // identical rail. Align its screenshot crop by less than one CSS px.
          await track.evaluate(element => {
            const y = element.getBoundingClientRect().top;
            element.style.translate = `0px ${Math.round(y) - y}px`;
          });
          await track.evaluate(async e => {
            await Promise.all([...e.querySelectorAll('img[src]')].map(img => img.decode().catch(() => {})));
          });
          const geometry = await track.evaluate(e => [...e.children].filter(c => c.dataset.renderSignature?.startsWith('loop:1:')).map(c => {
            const s = getComputedStyle(c), r = c.getBoundingClientRect();
            return { key: c.dataset.key, width: s.width, height: s.height, font: s.font, color: s.color,
              x: r.left - e.getBoundingClientRect().left };
          }));
          // Normalize ONLY the <1 CSS pixel raster phase caused by a different
          // number of fractional-width leading copies. Geometry is checked above
          // before this screenshot-only translation; component CSS is untouched.
          await track.evaluate(e => {
            const first = [...e.children].find(c => c.dataset.renderSignature?.startsWith('loop:1:'));
            const x = first.getBoundingClientRect().left - e.getBoundingClientRect().left;
            const delta = Math.round(x) - x;
            for (const card of e.children) card.style.translate = `${delta}px 0`;
          });
          const buffer = await track.screenshot({ animations: 'disabled' });
          writeFileSync(resolve(output, `${viewport.width}-${id}-${webRoot ? 'baseline' : 'current'}.png`), buffer);
          images.push({ id, geometry, image: PNG.sync.read(buffer) });
        }
        captures.push(images);
        assert.deepEqual(f.errors, []);
      } finally { await f.close(); }
    }
    captures[0].forEach(({ id, geometry, image: a }, i) => {
      geometry.forEach((card, j) => {
        const current = captures[1][i].geometry[j];
        assert.ok(Math.abs(card.x - current.x) <= 1, id + ' subpixel alignment');
        const { x: _oldX, ...oldStyle } = card, { x: _newX, ...newStyle } = current;
        assert.deepEqual(newStyle, oldStyle, id + ' exact card geometry/type/content');
      });
      const b = captures[1][i].image;
      assert.equal(a.width, b.width, id + ' width'); assert.equal(a.height, b.height, id + ' height');
      const diff = new PNG({ width: a.width, height: a.height });
      const pixels = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold: 0.15, diffMask: true });
      const rawRatio = pixels / (a.width * a.height);
      const ratio = edgeResidual(a, b, diff, viewport.width < 1000 ? 3 : 1);
      writeFileSync(resolve(output, `${viewport.width}-${id}-diff.png`), PNG.sync.write(diff));
      results.push({ viewport, id, rawRatio, ratio });
      assert.ok(ratio < 0.005, `${viewport.width} ${id}: ${(ratio * 100).toFixed(3)}% changed pixels`);
    });
  }
  writeFileSync(resolve(output, 'visual.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify({ comparisons: results.length, maximumChangedPixelRatio: Math.max(...results.map(r => r.ratio)) }));
})().catch(error => { console.error(error); process.exitCode = 1; });
