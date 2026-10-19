const assert = require("node:assert/strict");
const { mkdirSync } = require("node:fs");
const { resolve } = require("node:path");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  const output = resolve("artifacts/home-spotlight");
  mkdirSync(output, { recursive: true });
  for (const engine of ["chromium", "webkit"]) {
    for (const width of [390, 768, 1100, 1440, 1920, 2560, 3840]) {
      const f = await fixture({ engine, viewport: { width, height: width < 1000 ? 1024 : 1400 }, mobile: width < 1000 });
      try {
        await f.page.evaluate(() => {
          const movies = Array.from({ length: 100 }, (_, i) => ({
            slug: `landscape-${i}`, title: `Landscape ${i}`, year: "2026", genres: ["Drama"], rating: 8,
            cover_url: `/fixture-art.svg?poster=${i}`,
            backdrop_url: i < 20 ? "" : `/fixture-art.svg?wallpaper=${i}`, hosters: [],
          }));
          fixtureApp.profile.tasteProfile.accept({ interactions: 100, confidence: .8, genres: { Drama: 12 }, dimensions: { genres: { Drama: 12 } } });
          const data = fixtureApp.home.homeData.get();
          data.newMovies.splice(0, data.newMovies.length, ...movies);
          fixtureApp.home.actions.renderHome({ force: true });
        });
        const track = f.page.locator("#home-movies-track");
        await track.scrollIntoViewIfNeeded();
        const geometry = await track.evaluate(element => {
          const bounds = element.getBoundingClientRect();
          return [...element.children].map(card => {
            const rect = card.getBoundingClientRect();
            return { width: rect.width, height: rect.height,
              inside: rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1,
              horizontal: rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1 && rect.right < innerWidth,
              images: [...card.querySelectorAll("img")].map(image => image.getAttribute("src") || image.dataset.src || "") };
          });
        });
        assert.equal(geometry.length, 7, `${engine}/${width}: seven slots`);
        for (const card of geometry) {
          assert.ok(card.height > 100, `${engine}/${width}: no squashed cards`);
          assert.ok(card.inside, `${engine}/${width}: no clipped third row`);
          assert.ok(card.images.every(src => !src.includes("poster=")), "landscape artwork only");
          if (width >= 1100) {
            assert.ok(card.horizontal, "all desktop cards fit with a right gutter");
            assert.ok(card.width / card.height > 1.65 && card.width / card.height < 2.1, "landscape proportions");
          }
        }
        await f.page.screenshot({ path: resolve(output, `${engine}-${width}.png`) });
        assert.deepEqual(f.errors, []);
        console.log(JSON.stringify({ engine, width, cards: geometry.length, unclipped: true }));
      } finally { await f.close(); }
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
