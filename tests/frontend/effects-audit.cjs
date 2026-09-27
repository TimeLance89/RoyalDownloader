// Opt-in diagnostic, not a network-dependent CI gate. No production CSS changes.
const { fixture } = require('./performance-fixture.cjs');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
(async () => {
  const f = await fixture({ externalFonts: true });
  try {
    await f.page.evaluate(() => renderFixture());
    await f.page.evaluate(() => document.fonts.ready);
    const result = await f.page.evaluate(() => {
      const typography = new Map(), effects = [];
      for (const e of document.querySelectorAll('body *')) {
        const r = e.getBoundingClientRect();
        if (!r.width || !r.height || r.bottom <= 0 || r.top >= innerHeight) continue;
        const s = getComputedStyle(e);
        if ([...e.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim())) {
          const key = `${s.fontFamily} / ${s.fontWeight}`;
          typography.set(key, (typography.get(key) || 0) + 1);
        }
        if (s.backdropFilter !== 'none' || s.filter !== 'none') effects.push({ selector: e.id || e.className,
          area: Math.round(r.width * r.height), backdropFilter: s.backdropFilter, filter: s.filter });
      }
      return { viewport: { width: innerWidth, height: innerHeight }, typography: Object.fromEntries(typography),
        loadedFontFaces: [...document.fonts].filter(f => f.status === 'loaded').map(f => ({ family: f.family, weight: f.weight, display: f.display })),
        fontResources: performance.getEntriesByType('resource').filter(e => /fonts\.googleapis|fonts\.gstatic/.test(e.name)).map(e => ({ url: e.name, durationMs: e.duration, transferSize: e.transferSize })),
        effects: effects.sort((a, b) => b.area - a.area) };
    });
    console.log(JSON.stringify(result));
    if (process.env.ROYAL_PERF_OUTPUT) {
      mkdirSync(process.env.ROYAL_PERF_OUTPUT, { recursive: true });
      writeFileSync(resolve(process.env.ROYAL_PERF_OUTPUT, 'effects-fonts.json'), JSON.stringify(result, null, 2));
    }
  } finally { await f.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
