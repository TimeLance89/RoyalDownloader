const { fixture, swipe } = require("./performance-fixture.cjs");
const { mkdirSync, writeFileSync } = require("node:fs");
const { resolve, dirname } = require("node:path");
const { platform, arch } = require('node:os');
const { execFileSync } = require("node:child_process");
const output = resolve(process.env.ROYAL_PERF_OUTPUT || "artifacts/frontend-performance");
const profiles = [
  { name: "desktop", rate: 1 },
  { name: "desktop-4x", rate: 4 },
  { name: "desktop-6x", rate: 6 },
  { name: "mobile-4x", rate: 4, mobile: true, viewport: { width: 390, height: 844 } },
];

(async () => {
  mkdirSync(output, { recursive: true });
  const results = [];
  for (const profile of profiles) for (let repetition = 0; repetition < Number(process.env.ROYAL_PERF_REPEATS || 3); repetition++) {
    const f = await fixture(profile);
    try {
      const { page, cdp } = f;
      const trace = [];
      cdp.on("Tracing.dataCollected", ({ value }) => trace.push(...value));
      await cdp.send("Tracing.start", { categories: "devtools.timeline,disabled-by-default-devtools.timeline", transferMode: "ReportEvents" });
      const before = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map(m => [m.name, m.value]));
      const initialRenderMs = await page.evaluate(() => renderFixture());
      await page.waitForTimeout(800);
      const counts = await page.evaluate(() => ({
        domNodes: document.querySelectorAll("*").length,
        cards: document.querySelectorAll("#tab-home .home-track .home-card").length,
        logicalCards: [...document.querySelectorAll("[data-fixture-logical-count]")].reduce((n, e) => n + Number(e.dataset.fixtureLogicalCount), 0),
        logicalCardsRendered: [...document.querySelectorAll('[data-fixture-logical-count]')].reduce((n, e) => n + new Set([...e.querySelectorAll('.home-card')].map(card => card.dataset.key)).size, 0),
      }));
      const track = "#home-series-track";
      await page.locator(track).scrollIntoViewIfNeeded();
      await page.waitForTimeout(250);
      const start = await page.locator(track).evaluate(e => e.scrollLeft);
      const interactionStart = performance.now();
      if (profile.mobile) await swipe(page, cdp, track, -230);
      else await page.locator('[data-home-scroll="home-series-track"][data-direction="1"]').click();
      const responseMs = performance.now() - interactionStart;
      await page.waitForTimeout(1000);
      const afterSwipe = await page.locator(track).evaluate(e => e.scrollLeft);
      await page.screenshot({ path: resolve(output, `${profile.name}.png`) });
      const after = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map(m => [m.name, m.value]));
      const observation = await page.evaluate(() => ({
        longTasks: perfSample.longTasks.length,
        tbtMs: perfSample.longTasks.reduce((n, e) => n + Math.max(0, e.duration - 50), 0),
        lcpMs: perfSample.lcp,
        interactionEventMaxMs: Math.max(0, ...perfSample.events.map(e => e.duration)),
      }));
      const complete = new Promise(resolve => cdp.once("Tracing.tracingComplete", resolve));
      await cdp.send("Tracing.end"); await complete;
      const traceMs = pattern => trace.filter(e => e.ph === "X" && pattern.test(e.name)).reduce((n, e) => n + (e.dur || 0) / 1000, 0);
      const result = { ...profile, repetition, viewport: profile.viewport || { width: 1440, height: 1000 },
        browser: f.browser.version(), ...counts, initialRenderMs, ...observation,
        swipeStart: start, swipeEnd: afterSwipe, gestureWallMs: responseMs,
        layoutCount: after.LayoutCount - before.LayoutCount,
        styleRecalculationCount: after.RecalcStyleCount - before.RecalcStyleCount,
        layoutMs: (after.LayoutDuration - before.LayoutDuration) * 1000,
        styleMs: (after.RecalcStyleDuration - before.RecalcStyleDuration) * 1000,
        scriptMs: (after.ScriptDuration - before.ScriptDuration) * 1000,
        heapBytes: after.JSHeapUsedSize, imageDecodeMs: traceMs(/Decode Image|ImageDecode/), scriptEvaluationMs: traceMs(/^EvaluateScript$/),
        errors: f.errors };
      results.push(result); console.log(JSON.stringify(result));
    } finally { await f.close(); }
  }
  writeFileSync(resolve(output, "metrics.json"), JSON.stringify({
    commit: execFileSync("git", ['-C', process.env.ROYAL_WEB_ROOT ? dirname(resolve(process.env.ROYAL_WEB_ROOT)) : resolve(__dirname, '../..'), "rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
    harnessCommit: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    sourceDirty: Boolean(execFileSync('git', ['-C', process.env.ROYAL_WEB_ROOT ? dirname(resolve(process.env.ROYAL_WEB_ROOT)) : resolve(__dirname, '../..'), 'status', '--porcelain', '--', 'web'], { encoding: 'utf8' }).trim()),
    platform: platform(), architecture: arch(),
    capturedAt: new Date().toISOString(), results,
  }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
