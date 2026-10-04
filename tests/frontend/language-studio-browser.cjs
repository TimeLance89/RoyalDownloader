const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  await mkdir("artifacts/language-studio", { recursive: true });
  for (const width of [1440, 390]) {
    const run = await fixture({ viewport: { width, height: 1000 }, mobile: width < 600 });
    const { page, errors } = run;
    const config = { movies: ["filmpalast", "moviebox"], series: ["serienstream", "huhu", "vidrift"], anime: ["aniworld", "mkissa"],
      enabled_movies: ["filmpalast"], enabled_series: ["serienstream", "huhu"], enabled_anime: ["aniworld"],
      content_languages: ["de"], languages: { de: "Deutsch", en: "English" }, labels: { filmpalast: "Filmpalast", moviebox: "MovieBox", serienstream: "SerienStream", huhu: "Huhu", vidrift: "VidRift", aniworld: "AniWorld", mkissa: "MKissa" },
      catalog: { filmpalast: { content_languages: ["de"] }, moviebox: { content_languages: ["en"] }, serienstream: { content_languages: ["de", "en"] }, huhu: { content_languages: ["de", "en"] }, vidrift: { content_languages: ["en"] }, aniworld: { content_languages: ["de"] }, mkissa: { content_languages: ["en"] } } };
    const snapshot = { ui_language: "de", ui_languages: { de: "Deutsch", en: "English", fr: "Français" }, providers: config,
      subscriptions: [{ base_slug: "ahs", title: "American Horror Story", content_languages: ["de"] }, { base_slug: "dark", title: "Dark", content_languages: ["de"] }], revision: "fixture-review" };
    const writes = [];
    let committed = false, releaseCatalog;
    let failSave = width === 1440, failCatalog = width === 1440, failTranslation = width === 1440;
    const catalogGate = new Promise(resolve => { releaseCatalog = resolve; });
    try {
      // Keep translation failure deterministic; no browser model download.
      await page.evaluate(() => Object.defineProperty(window, "Translator", { configurable: true, value: { availability: async () => "unavailable" } }));
      await page.route("**/api/providers/config", route => route.fulfill({ json: config }));
      await page.route("**/api/providers/language-setup", async route => {
        if (route.request().method() === "POST") {
          const body = route.request().postDataJSON(); writes.push(body);
          if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { detail: "Disk temporarily unavailable" } }); }
          committed = true;
          await route.fulfill({ json: { ...snapshot, saved: true, ui_language: body.ui_language,
            providers: { ...config, content_languages: body.content_languages, enabled_movies: ["moviebox"], enabled_series: ["serienstream", "huhu", "vidrift"], enabled_anime: ["mkissa"] } } });
        } else await route.fulfill({ json: snapshot });
      });
      await page.route("**/api/ui/config", route => {
        assert.equal(route.request().method(), "GET", "Wizard must use the single profile transaction");
        return route.fulfill({ json: { language: "de", configured: true } });
      });
      await page.route("**/api/ui/translate", route => {
        const body = route.request().postDataJSON();
        if (committed && failTranslation) { failTranslation = false; return route.fulfill({ status: 503, json: { detail: "Translator unavailable" } }); }
        return route.fulfill({ json: { engine: "server", translations: body.texts } });
      });
      await page.route("**/api/movies?**", async route => {
        if (committed && failCatalog) { failCatalog = false; return route.fulfill({ status: 503, json: { detail: "Catalog temporarily unavailable" } }); }
        if (committed) await catalogGate;
        await route.fulfill({ json: { results: [], sources: [] } });
      });
      await page.evaluate(async () => {
        fixtureApp.core.actions.switchTab("einstellungen");
        await fixtureApp.settings.settings.initialize();
      });
      await page.locator('[data-settings-target="settings-sources"]').click();
      await page.locator("#provider-catalog").screenshot({ path: `artifacts/language-studio/catalog-${width}.png` });
      assert.equal(await page.locator('#series-provider-priority [data-route-role="primary"]:visible .provider-source-role').innerText(), "Erste Wahl");
      assert.equal(await page.locator('#movie-provider-priority [data-provider="moviebox"]').isVisible(), false);
      await page.locator('#movie-provider-priority + .catalog-more-sources').click();
      assert.equal(await page.locator('#movie-provider-priority [data-provider="moviebox"]').isVisible(), true);
      await page.locator('[data-settings-target="settings-general"]').click();
      await page.locator("#ui-language").selectOption("en");
      await page.locator("#language-setup-interface").waitFor();
      await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.querySelector("#language-setup-dialog").contains(document.activeElement)), true);
      assert.equal(await page.evaluate(() => document.documentElement.lang), "de");
      await page.locator("#language-setup-dialog").screenshot({ path: `artifacts/language-studio/interface-${width}.png` });
      await page.locator('[data-language-setup="cancel"]').click();
      assert.equal(writes.length, 0);
      assert.equal(await page.evaluate(() => document.documentElement.lang), "de");
      await page.locator("#ui-language").selectOption("en");
      await page.locator("#language-setup-interface").waitFor();
      await page.locator('[data-language-setup="next"]').click();
      await page.locator('[data-content-language="en"]').click();
      await page.locator('[data-content-language="de"]').click();
      if (width === 390) {
        await page.locator('[data-content-language="en"]').click();
        await page.locator('[data-language-setup="next"]').click();
        await page.locator('[data-language-setup="error"]').filter({ hasText: "Choose at least one language" }).waitFor();
        assert.equal(writes.length, 0);
        await page.locator('[data-content-language="en"]').click();
        await page.emulateMedia({ reducedMotion: "reduce" });
        assert.equal(await page.locator("#language-setup-dialog").evaluate(node => getComputedStyle(node).animationName), "none");
      }
      await page.locator("#language-setup-dialog").screenshot({ path: `artifacts/language-studio/content-${width}.png` });
      await page.locator('[data-language-setup="next"]').click();
      await page.locator('[data-subscription="ahs"]').check();
      await page.locator("#language-setup-dialog").screenshot({ path: `artifacts/language-studio/subscriptions-${width}.png` });
      const fits = await page.locator("#language-setup-dialog").evaluate(element => element.scrollWidth <= element.clientWidth + 1);
      assert.equal(fits, true);
      await page.locator('[data-language-setup="next"]').click();
      if (width === 1440) {
        await page.locator('[data-language-setup="error"]').filter({ hasText: "Disk temporarily unavailable" }).waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.lang), "de");
        await page.locator('[data-language-setup="next"]').click();
        await page.locator('[data-language-setup="error"]').filter({ hasText: "Catalog temporarily unavailable" }).waitFor();
        assert.equal(await page.locator('[data-language-setup="cancel"]').isDisabled(), true);
        await page.locator('[data-language-setup="next"]').click();
      }
      await page.waitForFunction(() => document.querySelector('[data-language-setup="busy-copy"]').textContent.includes("Preparing sources"));
      const payload = { revision: "fixture-review", ui_language: "en", content_languages: ["en"], update_subscriptions: ["ahs"] };
      assert.deepEqual(writes, width === 1440 ? [payload, payload] : [payload]);
      assert.equal(await page.locator("#language-setup-dialog").evaluate(element => element.open), true);
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("#language-setup-dialog").evaluate(element => element.open), true);
      await page.locator("#language-setup-dialog").screenshot({ path: `artifacts/language-studio/preparing-${width}.png` });
      releaseCatalog();
      if (width === 1440) {
        await page.locator('[data-language-setup="error"]').filter({ hasText: "Übersetzung ist noch nicht verfügbar" }).waitFor();
        assert.equal(await page.locator("#language-setup-dialog").evaluate(element => element.open), true);
        await page.locator('[data-language-setup="next"]').click();
      }
      await page.waitForFunction(() => !document.querySelector("#language-setup-dialog").open, { timeout: 20000 });
      assert.equal(await page.evaluate(() => document.documentElement.lang), "en");
      assert.equal(writes.length, width === 1440 ? 2 : 1);
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ width, passed: true, writes: writes.length, errors }));
    } catch (error) { console.log(JSON.stringify({ writes, errors, dialog: await page.locator("#language-setup-dialog").innerText() })); throw error; } finally { releaseCatalog(); await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
