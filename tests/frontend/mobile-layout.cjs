const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

async function bounds(page, selector) {
  return page.locator(selector).evaluate(element => {
    const { top, bottom, left, right, width, height } = element.getBoundingClientRect();
    return { top, bottom, left, right, width, height };
  });
}
async function touchTargets(page, selector) {
  for (const target of await page.locator(selector).all()) {
    if (!await target.isVisible()) continue;
    const box = await target.boundingBox();
    assert.ok(box.height >= 43.5, `${await target.getAttribute("id") || selector}: target height ${box.height}`);
  }
}

(async () => {
  for (const width of [320, 360, 390, 430, 768]) {
    const run = await fixture({ viewport: { width, height: 844 }, mobile: true });
    const { page } = run;
    try {
      await page.evaluate(() => renderFixture());
      for (const tab of ["home", "filme", "serien", "bibliothek", "kalender", "profil", "einstellungen"]) {
        await page.evaluate(tab => fixtureApp.core.actions.switchTab(tab), tab);
        if (tab === "einstellungen") await page.evaluate(() => fixtureApp.settings.settings.initialize());
        await page.evaluate(() => scrollTo(0, 0));
        await page.waitForTimeout(450);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${tab}: page overflow at ${width}`);
        await touchTargets(page, "#mobile-queue-btn, #series-subscriptions-manage, .library-action, .library-filter-tabs button, .library-view-switch button, .calendar-controls button, .calendar-toolbar button, .calendar-view-switch button, .profile-detail-button");
        if (tab === "home") {
          const controls = await bounds(page, ".home-hero-controls");
          const program = await bounds(page, ".home-program");
          assert.ok(controls.bottom <= program.top, "Hero controls remain clear of the program card");
          for (const action of ["#home-program-mood", "#home-discovery-shuffle", "#home-layout-open"]) {
            const box = await bounds(page, action);
            assert.ok(box.left >= 0 && box.right <= width, `${action}: clipped action`);
            assert.ok(box.height >= 44);
          }
        }
        if (tab === "bibliothek") {
          const copy = await bounds(page, ".library-hero-copy");
          const signals = await bounds(page, ".library-signal-board");
          const filters = await bounds(page, ".library-index");
          assert.ok(copy.bottom <= signals.top, "Library status does not cover the title or actions");
          assert.ok(copy.left >= 11 && copy.right <= width - 11, "Library content keeps the mobile gutter");
          assert.ok(signals.bottom <= filters.top, "Library filters follow the status board");
        }
        if (tab === "einstellungen") {
          const header = await bounds(page, ".topbar");
          const hero = await bounds(page, ".settings-hero");
          assert.ok(hero.top >= header.bottom && hero.top <= header.bottom + 40, "No duplicate header spacer");
        }
        if (tab === "kalender") {
          const days = page.locator(".calendar-week-strip button");
          assert.equal(await days.count(), 7);
          assert.ok(await days.evaluateAll(elements => elements.every(element => element.getBoundingClientRect().width >= 43.5)), "Every weekday has a touchable width");
          await days.last().tap();
          assert.equal(await days.last().getAttribute("aria-pressed"), "true", "Sunday remains reachable on narrow screens");
        }
        if (tab === "filme") {
          assert.ok(await page.locator(".movie-filter-field select").evaluateAll(elements => elements.every(element => parseFloat(getComputedStyle(element).fontSize) >= 16)), "Fields avoid iOS focus zoom");
          await touchTargets(page, ".movie-filter-field select, .movie-filter-actions button");
        }
      }
      await page.locator("#mobile-more-toggle").tap();
      const menu = await bounds(page, "#mobile-more-menu");
      const nav = await bounds(page, ".mobile-tabs");
      assert.ok(menu.left >= 0 && menu.right <= width && menu.bottom <= nav.top, "More menu fits above navigation");
      await page.locator("#mobile-more-toggle").tap();
      await page.locator("#global-search-toggle").tap();
      await page.locator("#global-search-input").focus();
      await page.waitForTimeout(300);
      const search = await bounds(page, ".global-search-shell");
      assert.ok(search.left >= 0 && search.right <= width, "Expanded search fits the header");
      await page.setViewportSize({ width, height: 420 });
      const smallSearch = await bounds(page, ".global-search-shell");
      assert.ok(smallSearch.left >= 0 && smallSearch.right <= width, "Search remains usable with reduced viewport height");
      assert.deepEqual(run.errors, []);
      console.log(JSON.stringify({ width, passed: true }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
