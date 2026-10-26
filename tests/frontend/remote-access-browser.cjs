const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const width of [1440, 390, 430]) {
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile: width !== 1440,
      viewport: { width, height: width === 1440 ? 1000 : 932 } });
    const { page, errors } = run;
    const writes = [], user = { id: "performance-fixture", username: "royal", role: "admin", enabled: true };
    let verified = false;
    try {
      await page.route("**/api/remote-access/*", async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        const body = request.postDataJSON(); writes.push({ path, body, profile: request.headers()["x-royal-profile"] });
        if (path.endsWith("/plan")) {
          if (!body.domain.includes("example.com")) return route.fulfill({ status: 400, json: { detail: "Eigene öffentliche Domain eingeben." } });
          return route.fulfill({ json: { url: "https://royal.example.com", hostname: "royal.example.com", origin: "http://127.0.0.1:8765",
            command: "docker compose -f docker-compose.yml -f docker-compose.remote.yml up -d --force-recreate seriendownloader cloudflare-tunnel" } });
        }
        if (path.endsWith("/bundle")) return route.fulfill({ contentType: "application/zip", body: Buffer.from("fixture-archive") });
        if (!verified) return route.fulfill({ status: 400, json: { detail: "Diese Royal-Installation wurde nicht bestätigt." } });
        return route.fulfill({ json: { verified: true, url: "https://royal.example.com", checks: ["HTTPS-Zertifikat gültig", "Anmeldung erforderlich"],
          qr_data_url: "data:image/svg+xml;base64," + Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="168" height="168"><rect width="168" height="168" fill="white"/></svg>').toString("base64") } });
      });
      await page.evaluate(user => { fixtureApp.profile.auth.acceptUser(user); fixtureApp.core.actions.switchTab("einstellungen"); }, user);
      await page.locator('[data-settings-open="settings-remote-access"]:visible').first().click();
      const panel = page.locator("#settings-remote-access");
      await panel.locator('[data-remote="domain"]').fill("localhost");
      await panel.locator('[data-remote-action="plan"]').click();
      await panel.getByText("Eigene öffentliche Domain eingeben.", { exact: true }).waitFor();
      await panel.locator('[data-remote="domain"]').fill("royal.example.com");
      await panel.locator('[data-remote-action="plan"]').click();
      await panel.locator('[data-remote="instructions"]:visible').waitFor();
      assert.equal(await panel.locator('[data-remote="hostname"]').textContent(), "royal.example.com");
      await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined }));
      await panel.locator('[data-remote-action="copy-origin"]').click();
      await panel.locator('[data-remote="status"]').filter({ hasText: /Kopiert|Text markiert/ }).waitFor();
      assert.equal(await page.locator("#settings-save").isVisible(), false);
      await panel.locator('[data-remote="token"]').fill("test-tunnel-token-".repeat(5));
      const download = page.waitForEvent("download");
      await panel.locator('[data-remote-action="bundle"]').click();
      assert.equal((await download).suggestedFilename(), "royal-remote-access.zip");
      await panel.getByText(/ZIP heruntergeladen/).waitFor();
      assert.equal(await panel.locator('[data-remote="token"]').inputValue(), "");
      await panel.locator('[data-remote-action="verify"]').click();
      await panel.getByText("Diese Royal-Installation wurde nicht bestätigt.", { exact: true }).waitFor();
      assert.equal(await panel.locator('[data-remote="result"]').evaluate(node => node.hidden), true);
      verified = true;
      await panel.locator('[data-remote-action="verify"]').click();
      await panel.locator('[data-remote="result"]:visible').waitFor();
      assert.equal(await panel.locator('[data-remote="url"]').getAttribute("href"), "https://royal.example.com");
      await page.waitForFunction(() => document.querySelector('[data-remote="qr"]').complete);
      assert.ok(writes.every(write => write.profile === user.id));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await panel.locator('[data-remote="status"]').scrollIntoViewIfNeeded();
      await page.screenshot({ path: require("node:path").join(require("node:os").tmpdir(), `royal-remote-access-${width}.png`) });
      await panel.locator('[data-remote="token"]').fill("secret-must-disappear");
      await page.locator('[data-settings-target="settings-account"]').click();
      await page.waitForFunction(() => document.querySelector('[data-remote="token"]').value === "");
      await page.locator('[data-settings-target="settings-remote-access"]').click();
      await panel.locator('[data-remote="domain"]').fill("changed.example.com");
      assert.equal(await panel.locator('[data-remote="instructions"]').evaluate(node => node.hidden), true);
      assert.equal(await panel.locator('[data-remote="qr"]').getAttribute("src"), null);
      await panel.locator('[data-remote="domain"]').fill("royal.example.com");
      await panel.locator('[data-remote-action="plan"]').click();
      await panel.locator('[data-remote="instructions"]:visible').waitFor();
      await panel.locator('[data-remote="token"]').fill("clear-on-session-expiry");
      await page.evaluate(() => document.dispatchEvent(new CustomEvent("royal:session-expired")));
      assert.equal(await panel.locator('[data-remote="token"]').inputValue(), "");
      await page.evaluate(user => {
        fixtureApp.profile.auth.acceptUser({ ...user, role: "member" });
        fixtureApp.settings.remoteAccess.mount();
      }, user);
      assert.equal(await panel.locator('[data-remote="form"]').evaluate(node => getComputedStyle(node).display), "none");
      assert.deepEqual(errors, []);
    } finally { await run.close(); }
  }
  console.log("Own-domain wizard: validated domain, download, proof failure/success and secret cleanup passed at desktop/mobile widths.");
})().catch(error => { console.error(error); process.exitCode = 1; });
