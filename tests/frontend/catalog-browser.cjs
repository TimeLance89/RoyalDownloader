// Populated catalog regression: exercise the shared ResultCard renderer, not headings.
const assert = require("node:assert/strict");
const { fixture, swipe } = require("./performance-fixture.cjs");

(async () => {
  // Fresh touch contexts keep Chromium's gesture state independent between catalogs.
  for (const { mobile, tabs } of [
    { mobile: false, tabs: ["filme", "serien"] },
    { mobile: true, tabs: ["filme"] },
    { mobile: true, tabs: ["serien"] },
  ]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
    const { page, errors } = run;
    try {
      page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
      const requests = [];
      const movies = Array.from({ length: 34 }, (_, i) => ({
        slug: `filmpalast:catalog-${i}`, title: `Catalog Movie ${String(i).padStart(2, "0")}`,
        year: i % 2 ? "2015" : "2026", rating: i % 2 ? 6 : 9, genres: ["Drama"],
        cover_url: "/fixture-art.svg", backdrop_url: "/fixture-art.svg", tmdb_id: 1000 + i,
        content_languages: [i % 2 ? "en" : "de"], provider: "filmpalast", hosters: [],
        description: "Loaded catalog detail fixture",
      }));
      const series = movies.map((movie, i) => ({ ...movie,
        title: `Catalog Series ${String(i).padStart(2, "0")}`, base_slug: `serienstream:catalog-${i}`,
        sample_slug: `serienstream:catalog-${i}-s01e01`, sample_url: `/series/catalog-${i}`,
        provider: "serienstream", season_count: 1,
      }));
      await page.route("**/api/**", async route => {
        const url = new URL(route.request().url()), path = url.pathname;
        requests.push(url.pathname + url.search);
        let data;
        if (path === "/api/movies" || path === "/api/series") {
          const source = path === "/api/movies" ? movies : series;
          const number = Number(url.searchParams.get("page") || 1);
          data = { results: source.slice((number - 1) * 32, number * 32), page: number, has_more: number === 1, sources: [] };
        } else if (path === "/api/genres") {
          data = { genres: ["Drama"] };
        } else if (path === "/api/tmdb/movies") {
          data = { movies: Object.fromEntries(movies.map(movie => [movie.slug, movie])) };
        } else if (path === "/api/tmdb/movie") {
          const body = route.request().postDataJSON();
          data = { movie: { ...movies.find(movie => movie.slug === body.slug), details_loaded: true, overview: "Catalog details fixture" } };
        } else if (path.startsWith("/api/movie/")) {
          data = movies.find(movie => movie.slug === decodeURIComponent(path.slice("/api/movie/".length))) || movies[0];
        } else if (path === "/api/series/load") {
          const body = route.request().postDataJSON();
          data = { ...series.find(item => item.base_slug === body.base_slug), seasons: [{ season: 1, episodes: [{ season: 1, episode: 1, slug: "fixture-s01e01", title: "Episode one" }] }] };
        } else if (path === "/api/jellyfin/matches") {
          data = { configured: true, statuses: Object.fromEntries(route.request().postDataJSON().items.map(item => [item.slug, item.title.endsWith("00") ? "owned" : "missing"])) };
        } else return route.fallback();
        await route.fulfill({ json: data });
      });
      // Remove Home's synthetic performance seed: catalog content must come from HTTP.
      await page.evaluate(async () => {
        fixtureApp.home.homeData.get().newMovies.length = 0;
        await fixtureApp.discovery.genres.refresh();
      });
      if (!mobile) {
        await page.evaluate(async () => {
          const { createCardDock } = await import("/js/features/home/card-dock.js");
          const root = document.createElement("section");
          root.innerHTML = '<div class="home-card" style="width:300px;height:180px"><button class="home-card-primary-action">Queue regression</button></div>';
          document.getElementById("tab-home").append(root);
          let queued = false;
          const dock = createCardDock(root, {
            trailers: { key: () => "", setMuted() {}, open() {}, muted: true },
            homeEntryMedia: entry => entry.item, mediaJellyfinStatus: () => "missing", mediaCardInitials: () => "QR",
            openHomeEntry() {}, toggleFpPick: async () => { queued = !queued; },
            getMovie: () => null, acceptMetadata() {}, isQueued: () => queued, normalizeHomeRailLoop() {},
          });
          dock.mount(); dock.register(root.firstElementChild, { kind: "movie", item: { slug: "queue-regression", title: "Queue regression" } });
          window.queueRegression = { dock, root };
          root.querySelector("button").focus();
        });
        const queue = page.locator('.home-card-dock[aria-label="Queue regression, Schnellaktionen"] .is-queue');
        for (const expected of ["true", "false"]) {
          await queue.click();
          await page.waitForFunction(expected => document.querySelector('.home-card-dock[aria-label="Queue regression, Schnellaktionen"] .is-queue')?.getAttribute("aria-pressed") === expected, expected, { timeout: 5000 });
          assert.equal(await queue.isEnabled(), true);
        }
        await page.evaluate(() => { queueRegression.dock.unmount(); queueRegression.root.remove(); });
      }
      const openTab = async name => {
        const button = page.locator(`${mobile ? ".mobile-tabs" : ".tabs"} .tab-btn[data-tab="${name}"]:visible`).first();
        await button.scrollIntoViewIfNeeded();
        await button[mobile ? "tap" : "click"]();
      };
      for (const [tab, root, title, modal] of [
        ["filme", "fp", "Catalog Movie", "fp-detail"],
        ["serien", "series", "Catalog Series", "series-detail"],
      ].filter(([tab]) => tabs.includes(tab))) {
        await openTab(tab);
        const selector = `#${root}-results .result-card`;
        await page.waitForFunction(selector => document.querySelectorAll(selector).length >= 32, selector, { timeout: 5000 })
          .catch(async error => { throw new Error(`${tab}: ${await page.locator(`#${root}-status`).textContent()}`, { cause: error }); });
        const card = page.locator(selector).first();
        await card.scrollIntoViewIfNeeded();
        await page.waitForFunction(selector => {
          const image = document.querySelector(`${selector} .result-card-poster:not(.is-pending-poster)`);
          return image?.complete && image.naturalWidth > 0;
        }, selector);
        assert.match(await card.locator(".result-card-title").textContent(), new RegExp(title));
        assert.match(await card.locator(".result-card-meta").textContent(), /2026/);
        await page.waitForFunction(selector => /Jellyfin/.test(document.querySelector(selector)?.textContent || ""), selector);
        await card.locator(".result-card-visual")[mobile ? "tap" : "click"]();
        await page.waitForSelector(`#${modal}-modal:not([hidden])`);
        assert.match(await page.locator(`#${modal}-title`).textContent(), new RegExp(title));
        await page.waitForFunction(selector => document.querySelector(selector)?.textContent === "Loaded catalog detail fixture", tab === "filme" ? "#fp-detail-desc" : "#series-desc");
        await page.keyboard.press("Escape");
        await page.waitForSelector(`#${modal}-modal`, { state: "hidden" });
        await page.locator(`${selector}`).last().scrollIntoViewIfNeeded();
        await page.waitForFunction(selector => document.querySelectorAll(selector).length === 34, selector);
        assert.ok(requests.some(path => path.startsWith(`/api/${tab === "filme" ? "movies" : "series"}?`) && /page=2/.test(path)));
        assert.equal(await page.locator(`#${tab === "filme" ? "movie" : "series"}-subscriptions-title`).isVisible(), true);
        assert.match(await page.locator(`#${tab === "filme" ? "movie" : "series"}-feature-title`).textContent(), new RegExp(title));
        if (tab === "filme") {
          for (const [filter, value, count] of [["period", "2020s", 17], ["rating", "8", 17], ["language", "de", 17], ["availability", "owned", 1]]) {
            await page.locator(`#movie-filter-${filter}`).selectOption(value);
            await page.waitForFunction(count => document.querySelectorAll("#fp-results .result-card:not([hidden])").length === count, count);
            await page.locator("#movie-filter-reset").click();
          }
          for (const sort of ["newest", "rating", "title"]) {
            await page.locator("#movie-filter-sort").selectOption(sort);
            assert.equal(await card.evaluate(node => node.style.order), "0");
            assert.ok(Number(await page.locator(selector).nth(1).evaluate(node => node.style.order)) > 0);
          }
          await page.locator("#movie-filter-reset").click();
          await page.locator("#movie-filter-genre").selectOption("Drama");
          await page.waitForFunction(() => document.querySelector("#fp-status").textContent.includes("Drama") && document.querySelectorAll("#fp-results .result-card").length >= 32);
          assert.ok(requests.some(path => /mode=genre/.test(path) && /genre=Drama/.test(path)));
          await page.locator("#movie-filter-genre").selectOption("Alle Genres");
          await page.waitForFunction(() => document.querySelectorAll("#fp-results .result-card").length >= 32);
        }
        if (mobile) {
          await card.scrollIntoViewIfNeeded();
          const before = await page.evaluate(() => scrollY);
          await swipe(page, run.cdp, `${selector}:first-child`, 0, -160);
          await page.waitForFunction(before => scrollY > before + 20, before);
          // A following native tap must not merely stop the preceding momentum.
          await page.evaluate(() => new Promise(resolve => {
            let timer;
            const done = () => { removeEventListener("scroll", settle); resolve(); };
            const settle = () => { clearTimeout(timer); timer = setTimeout(done, 700); };
            addEventListener("scroll", settle, { passive: true }); settle();
          }));
          assert.equal(await page.locator(`#${modal}-modal`).isVisible(), false);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
        }
        assert.doesNotMatch(await page.locator(`#${root}-status`).textContent(), /ReferenceError|TypeError|before initialization|Fehler:/);
      }
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ passed: true, mobile, tabs, cardsPerCatalog: 34 }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
