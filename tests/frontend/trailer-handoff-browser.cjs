const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const [kind, mobile] of [["film", false], ["series", false], ["film", true]]) {
    const run = await fixture({ mobile, viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
      engine: process.env.ROYAL_BROWSER || "chromium" });
    const { page, errors } = run;
    try {
      // Real iframe origins and messages, without contacting YouTube or playing audio.
      await page.route("https://www.youtube-nocookie.com/embed/**", route => route.fulfill({
        contentType: "text/html", body: "<!doctype html><html><body>Offline trailer player</body></html>",
      }));
      const prefix = kind === "film" ? "fp" : "series";
      await page.evaluate(({ kind, prefix }) => {
        window.handoffMovie = { title: "Trailer handoff", trailer: { site: "YouTube", key: "abcdefghijk" } };
        window.handoffTimeReceived = false;
        window.addEventListener("message", event => {
          if (event.data?.info?.currentTime === 37) window.handoffTimeReceived = true;
        });
        fixtureApp.core.actions.openMediaModal(`${prefix}-detail-modal`);
        document.querySelector(`#${prefix}-detail-modal .media-modal-panel`).classList.remove("is-empty");
        fixtureApp.discovery.trailers[kind].configure(window.handoffMovie);
      }, { kind, prefix });
      const hero = page.locator(`#${prefix}-detail-hero-frame`);
      await page.waitForFunction(prefix => document.getElementById(`${prefix}-detail-hero-frame`).getAttribute("src"), prefix);
      await page.waitForFunction(prefix => Boolean(document.getElementById(`${prefix}-detail-hero-frame`).contentDocument) === false, prefix);
      const embedded = page.frames().find(frame => frame.url().startsWith("https://www.youtube-nocookie.com/embed/"));
      assert.ok(embedded);
      await embedded.evaluate(() => parent.postMessage({ event: "infoDelivery", info: { currentTime: 37 } }, "*"));
      await page.waitForFunction(() => window.handoffTimeReceived);
      await page.locator(`#${prefix}-detail-trailer`).click();
      const player = page.locator("#fp-trailer-frame");
      const resumed = await player.getAttribute("src");
      assert.match(resumed, /&start=37&/);
      assert.equal(await hero.getAttribute("src"), null);
      await page.evaluate(kind => {
        fixtureApp.discovery.trailers[kind].configure(window.handoffMovie);
        fixtureApp.discovery.trailers[kind].schedule(window.handoffMovie);
      }, kind);
      await page.waitForTimeout(2500);
      assert.equal(await hero.getAttribute("src"), null, "Late metadata must not restart background autoplay");
      assert.equal(await player.getAttribute("src"), resumed);
      await page.evaluate(({ kind, prefix }) => {
        document.getElementById(`${prefix}-detail-trailer`).onclick();
        fixtureApp.discovery.trailers.open(window.handoffMovie, null, kind);
      }, { kind, prefix });
      assert.equal(await player.getAttribute("src"), resumed, "Repeated clicks must not reset playback position");
      assert.equal(await page.locator('iframe[src^="https://www.youtube-nocookie.com/embed/"]').count(), 1);
      await page.locator("#fp-trailer-close").click();
      assert.equal(await player.getAttribute("src"), null);
      assert.equal(await hero.getAttribute("src"), null);
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ passed: true, kind, mobile, resumedAt: 37, activePlayers: 1 }));
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
