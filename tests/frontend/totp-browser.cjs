const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const width of [1440, 390, 430]) {
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile: width !== 1440,
      viewport: { width, height: width === 1440 ? 1000 : 932 } });
    const { page, errors } = run;
    let enabled = false, firstLogin = false, failDisable = false;
    const writes = [], codes = Array.from({ length: 10 }, (_, i) => `recovery-${i}-fixture`);
    const user = { id: "performance-fixture", username: "royal", display_name: "Royal", role: "admin", enabled: true };
    try {
      await page.route("**/api/auth/config", route => route.fulfill({ json: { configured: true, username: "royal", active_sessions: 1 } }));
      await page.route("**/api/me/totp**", async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        if (request.method() === "GET") return route.fulfill({ json: { enabled, recovery_codes_remaining: 10 } });
        const body = request.postDataJSON();
        writes.push({ path, body, profile: request.headers()["x-royal-profile"] });
        if (body.current_password !== "correct-password") return route.fulfill({ status: 403, json: { detail: "Das aktuelle Passwort ist falsch." } });
        if (path.endsWith("/setup")) return route.fulfill({ json: {
          secret: "JBSWY3DPEHPK3PXP", expires_in: 600,
          qr_data_url: "data:image/svg+xml;base64," + Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220"><rect width="220" height="220" fill="white"/><path d="M20 20h70v70H20zM130 20h70v70h-70zM20 130h70v70H20zM130 130h30v30h-30z" fill="black"/></svg>').toString("base64"),
        } });
        if (path.endsWith("/disable") && failDisable) return route.fulfill({ status: 403, json: { detail: "Code ungültig." } });
        if (path.endsWith("/confirm")) { enabled = true; return route.fulfill({ json: { enabled, user: { ...user, mfa_enabled: true }, recovery_codes: codes } }); }
        if (path.endsWith("/disable")) { enabled = false; return route.fulfill({ json: { enabled, user: { ...user, mfa_enabled: false } } }); }
        return route.fulfill({ json: { recovery_codes: codes.map(code => code + "-new") } });
      });
      await page.evaluate(user => { fixtureApp.profile.auth.acceptUser(user); fixtureApp.core.actions.switchTab("einstellungen"); }, user);
      await page.locator('[data-settings-open="settings-account"]:visible').first().click();
      const panel = page.locator("[data-totp-settings]");
      await panel.getByText("2FA ist noch nicht aktiviert.", { exact: true }).waitFor();
      await panel.locator('[data-totp-ui="manage"]').click();
      await panel.locator('[data-totp="password"]').fill("correct-password");
      await panel.locator('[data-totp-action="setup"]').click();
      await panel.locator('[data-totp="setup"]:visible').waitFor();
      assert.equal(await panel.locator('[data-totp="secret"]').inputValue(), "JBSWY3DPEHPK3PXP");
      await page.waitForFunction(() => document.querySelector('[data-totp="qr"]').complete);
      assert.equal(await panel.locator('[data-totp="qr"]').evaluate(image => image.naturalWidth), 220);
      await panel.locator('[data-totp="code"]').fill("123456");
      await panel.locator('[data-totp-action="confirm"]').click();
      await panel.getByText(/2FA aktiv ·/).waitFor();
      assert.equal(await panel.locator('[data-totp="secret"]').inputValue(), "");
      assert.equal(await panel.locator('[data-totp="qr"]').getAttribute("src"), null);
      assert.equal((await panel.locator('[data-totp="recovery-list"]').textContent()).split("\n").length, 10);
      assert.equal(await page.locator("#account-otp-field").evaluate(node => node.hidden), false);
      assert.ok(writes.every(row => row.profile === user.id));
      const [download] = await Promise.all([page.waitForEvent("download"), panel.locator('[data-totp-ui="download"]').click()]);
      assert.equal(download.suggestedFilename(), "royal-wiederherstellungscodes.txt");
      assert.match(await require("node:fs/promises").readFile(await download.path(), "utf8"), /recovery-0-fixture/);
      await panel.locator('[data-totp-action="saved"]').click();
      assert.equal(await panel.locator('[data-totp="recovery-list"]').textContent(), "");
      failDisable = true;
      await panel.locator('[data-totp-ui="manage"]').click();
      await panel.locator('[data-totp="disable-section"] > summary').click();
      await panel.locator('[data-totp="password"]').fill("correct-password");
      await panel.locator('[data-totp="code"]').fill("wrong-code");
      await panel.locator('[data-totp-action="disable"]').click();
      await panel.getByText("Code ungültig.", { exact: true }).waitFor();
      assert.equal(enabled, true);
      failDisable = false;
      await panel.locator('[data-totp="code"]').fill(codes[0]);
      await panel.locator('[data-totp-action="recovery-codes"]').click();
      await panel.getByText(/Die bisherigen Codes sind ungültig/).waitFor();
      assert.match(await panel.locator('[data-totp="recovery-list"]').textContent(), /fixture-new/);
      await panel.screenshot({ path: require("node:path").join(require("node:os").tmpdir(), `royal-totp-${width}.png`) });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.evaluate(() => fixtureApp.settings.account.unmount());
      assert.equal(await panel.locator('[data-totp="recovery-list"]').textContent(), "");
      assert.equal(await panel.locator('[data-totp="password"]').inputValue(), "");

      // An unlocked member session must still offer the admin's second factor.
      const admin = { ...user, id: "admin-fixture", mfa_enabled: true };
      const member = { ...user, role: "member", mfa_enabled: false };
      let householdHasMfa = true;
      await page.route("**/api/me/household", route => route.fulfill({ json: {
        current_user_id: member.id, switching_unlocked: true, unlocked: false,
        users: [{ ...admin, mfa_enabled: householdHasMfa }, member],
      } }));
      const switchBodies = [];
      await page.route("**/api/me/household/switch", route => {
        const body = route.request().postDataJSON(); switchBodies.push(body);
        return route.fulfill({ status: 403, json: { detail: {
          code: body.otp_code ? "mfa_invalid" : "mfa_required", message: "Nächsten Authenticator-Code eingeben.",
        } } });
      });
      await page.evaluate(async member => { fixtureApp.profile.auth.acceptUser(member); await fixtureApp.profile.household.open(); }, member);
      await page.locator('.household-user[data-user-id="admin-fixture"]').click();
      await page.locator("#household-otp-field:not([hidden])").waitFor();
      assert.equal(switchBodies.length, 0);
      await page.locator("#household-password").fill("correct-password");
      await page.locator("#household-otp").fill("654321");
      await page.locator('#household-unlock button[type="submit"]').click();
      await page.locator("#household-status").filter({ hasText: "Nächsten Authenticator-Code" }).waitFor();
      assert.equal(switchBodies.at(-1).user_id, admin.id);
      assert.equal(switchBodies.at(-1).otp_code, "654321");
      await page.locator("#household-close").click();
      // Stale metadata must reveal the credential form instead of hiding errors.
      householdHasMfa = false;
      await page.evaluate(() => fixtureApp.profile.household.open());
      await page.locator('.household-user[data-user-id="admin-fixture"]').click();
      await page.locator("#household-otp-field:not([hidden])").waitFor();
      await page.locator("#household-close").click();

      await page.route("**/api/auth/status", route => route.fulfill({ json: { configured: true, required: true, authenticated: false } }));
      await page.route("**/api/auth/login", async route => {
        const body = route.request().postDataJSON(); writes.push({ path: "/api/auth/login", body });
        if (firstLogin) return route.fulfill({ status: 409, json: { detail: "Passwort-Einrichtung erforderlich." } });
        if (body.otp_code !== "123456" && body.otp_code !== codes[1]) return route.fulfill({ status: 403,
          json: { detail: { code: body.otp_code ? "mfa_invalid" : "mfa_required", message: "Authenticator-Code erforderlich." } } });
        return route.fulfill({ json: { configured: true, authenticated: true, user: { ...user, mfa_enabled: true } } });
      });
      await page.route("**/api/auth/first-login", async route => {
        const body = route.request().postDataJSON();
        if (!body.otp_code) return route.fulfill({ status: 403, json: { detail: { code: "mfa_required", message: "Authenticator-Code erforderlich." } } });
        return route.fulfill({ json: { configured: true, authenticated: true, user } });
      });
      await page.evaluate(async () => {
        fixtureApp.profile.auth.unmount();
        const { createAuthentication } = await import("/js/features/auth/index.js");
        window.totpLogin = createAuthentication(document.getElementById("login-screen"), { reload: () => { window.totpReloaded = true; } });
        window.totpLoginDone = totpLogin.requireLogin();
      });
      await page.locator("#login-screen:not(.hidden)").waitFor();
      await page.locator("#login-username").fill("royal");
      await page.locator("#login-password").fill("correct-password");
      await page.locator("#login-submit").click();
      await page.locator("#login-otp-field:not([hidden])").waitFor();
      assert.equal(await page.locator("#login-password").inputValue(), "correct-password");
      await page.locator("#login-otp").fill(codes[1]);
      await page.locator("#login-submit").click();
      await page.locator("#login-screen.hidden").waitFor({ state: "attached" });
      assert.equal(await page.locator("#login-password").inputValue(), "");
      assert.equal(await page.locator("#login-otp").inputValue(), "");
      firstLogin = true;
      await page.evaluate(() => totpLogin.unauthorized());
      await page.locator("#login-password").fill("correct-password");
      await page.locator("#login-password").press("Enter");
      await page.locator("#first-login-form:not(.hidden)").waitFor();
      await page.locator("#first-login-password").fill("new-correct-password");
      await page.locator("#first-login-repeat").fill("new-correct-password");
      await page.locator('#first-login-form button[type="submit"]').click();
      await page.locator("#first-login-otp-field:not([hidden])").waitFor();
      await page.locator("#first-login-otp").fill("123456");
      await page.locator('#first-login-form button[type="submit"]').click();
      await page.waitForFunction(() => window.totpReloaded);
      assert.equal(await page.locator("#first-login-password").inputValue(), "");
      assert.deepEqual(errors, []);
      console.log(`TOTP ${width}px: setup, recovery, isolation and second-factor login passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
