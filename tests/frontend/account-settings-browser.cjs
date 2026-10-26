const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  const output = path.resolve("artifacts/account-review"); await fs.mkdir(output, { recursive: true });
  for (const width of [1600, 430]) {
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile: width !== 1600, viewport: { width, height: 1050 } });
    const { page, errors } = run;
    let user = { id: "performance-fixture", username: "jester", display_name: "Steffen", role: "admin", enabled: true, mfa_enabled: true, avatar_id: "avatar-gold" };
    let users = [user, { id: "mara", username: "mara", display_name: "Mara", role: "member", enabled: true, avatar_id: "avatar-blue", mfa_enabled: false }, { id: "guest", username: "gast", display_name: "Gäste", role: "member", enabled: true, setup_required: true, avatar_id: "avatar-green" }];
    let sessions = [{ id: "a".repeat(64), label: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/132.0", kind: "web", current: true, last_seen_at: Date.now() / 1000 },
      { id: "b".repeat(64), label: "Royal TV · Wohnzimmer", kind: "mobile", current: false, last_seen_at: Date.now() / 1000 - 1800 },
      { id: "c".repeat(64), label: "Mozilla/5.0 (Android) Firefox/132.0", kind: "web", current: false, last_seen_at: Date.now() / 1000 - 86400 }];
    const writes = []; let failRevoke = false;
    page.on("dialog", dialog => dialog.accept());
    try {
      await page.route("**/assets/profile-avatars/*.svg", async route => {
        const name = new URL(route.request().url()).pathname.split("/").at(-1);
        await route.fulfill({ contentType: "image/svg+xml", body: await fs.readFile(path.resolve(__dirname, "../../web/assets/profile-avatars", name)) });
      });
      await page.route("**/api/auth/config", route => route.fulfill({ json: { configured: true, username: user.username, user, active_sessions: sessions.length } }));
      await page.route("**/api/auth/users**", async route => {
        const request = route.request(), url = new URL(request.url());
        if (user.role !== "admin") return route.fulfill({ status: 403, json: { detail: "Administratorrechte erforderlich." } });
        if (request.method() === "GET") return route.fulfill({ json: { users } });
        writes.push({ path: url.pathname, body: request.postDataJSON() });
        if (url.pathname.endsWith("/enabled")) { const target = users.find(row => row.id === url.pathname.split("/").at(-2)); target.enabled = url.searchParams.get("enabled") === "true"; return route.fulfill({ json: { user: target } }); }
        if (url.pathname === "/api/auth/users") { const next = { id: "new-member", ...request.postDataJSON(), enabled: true, setup_required: true }; users.push(next); return route.fulfill({ json: { user: next } }); }
        return route.fulfill({ json: { user: users[1] } });
      });
      await page.route("**/api/profile-avatars", route => route.fulfill({ json: { avatars: [] } }));
      await page.route("**/api/me/totp", route => route.fulfill({ json: { enabled: user.mfa_enabled, recovery_codes_remaining: 7 } }));
      await page.route("**/api/me/sessions**", async route => {
        const request = route.request(), url = new URL(request.url());
        if (request.method() === "GET") return route.fulfill({ json: { sessions } });
        writes.push({ path: url.pathname, profile: request.headers()["x-royal-profile"] });
        if (failRevoke) return route.fulfill({ status: 503, json: { detail: "Speichern nicht möglich." } });
        const before = sessions.length;
        sessions = request.method() === "DELETE" ? sessions.filter(row => row.id !== url.pathname.split("/").at(-1)) : sessions.filter(row => row.current);
        return route.fulfill({ json: { sessions, revoked: before - sessions.length } });
      });
      await page.route("**/api/me/password", async route => {
        const body = route.request().postDataJSON(); writes.push({ path: "/api/me/password", body });
        assert.equal(body.otp_code, "123456");
        sessions = sessions.filter(row => row.current);
        return route.fulfill({ json: { configured: true, user, active_sessions: 1 } });
      });
      await page.route("**/api/me/household/*/profile", async route => {
        const body = route.request().postDataJSON(); user = { ...user, ...body }; users[0] = user;
        return route.fulfill({ json: { user } });
      });
      await page.evaluate(user => { fixtureApp.profile.auth.acceptUser(user); fixtureApp.core.actions.switchTab("einstellungen"); document.querySelector('[data-settings-target="settings-account"]').click(); }, user);
      const account = page.locator("#settings-account");
      await account.locator("#account-display-name").filter({ hasText: "Steffen" }).waitFor();
      await account.locator('[data-totp="badge"]').filter({ hasText: "Aktiv" }).waitFor();
      await page.waitForFunction(() => document.querySelector("#account-device-count").textContent === "3");
      await page.waitForTimeout(350);
      await page.evaluate(() => document.fonts.ready);
      assert.equal(await account.locator("#account-credential-editor").isVisible(), false);
      assert.equal(await account.locator('[data-totp="editor"]').isVisible(), false);
      assert.equal(await page.locator("#settings-save").isVisible(), false);
      await page.screenshot({ path: path.join(output, `konto-${width}.png`) });
      await account.locator('[data-account-tab="devices"]').click();
      await account.getByText("Royal TV · Wohnzimmer", { exact: true }).waitFor();
      await page.screenshot({ path: path.join(output, `geraete-${width}.png`) });
      failRevoke = true;
      await account.getByRole("button", { name: "Royal TV · Wohnzimmer abmelden", exact: true }).click();
      await account.getByText("Speichern nicht möglich.", { exact: true }).waitFor();
      assert.equal(sessions.length, 3);
      failRevoke = false;
      await account.getByRole("button", { name: "Royal TV · Wohnzimmer abmelden", exact: true }).click();
      await page.waitForFunction(() => document.querySelector("#account-device-count").textContent === "2");
      assert.equal(writes.at(-1).profile, user.id);
      await account.locator('[data-account-tab="household"]').click();
      await account.getByText("Mara", { exact: true }).waitFor();
      await page.screenshot({ path: path.join(output, `haushalt-${width}.png`) });
      const mara = account.locator(".account-household-row").filter({ hasText: "Mara" });
      await mara.locator("summary").click();
      await mara.getByRole("button", { name: "Zugang pausieren", exact: true }).click();
      await mara.getByText(/Zugang pausiert/).waitFor();
      await mara.locator("summary").click(); await mara.getByRole("button", { name: "Zugang aktivieren", exact: true }).click();
      await account.getByText("Zugang wieder aktiviert.", { exact: true }).waitFor();
      await account.locator('[data-account-tab="security"]').click();
      await account.locator('[data-totp-ui="manage"]').click();
      await page.screenshot({ path: path.join(output, `authenticator-${width}.png`) });
      await account.locator('[data-totp-ui="close"]').click();
      await account.locator('[data-account-credential="password"]').click();
      await account.locator("#account-password").fill("new-correct-password");
      await account.locator("#account-password-repeat").fill("new-correct-password");
      await account.locator("#account-current-password").fill("correct-password");
      await account.locator("#account-otp").fill("123456");
      await account.locator("#account-save").click();
      await account.getByText("✓ Passwort geändert. Andere Sitzungen wurden beendet.", { exact: true }).waitFor();
      assert.equal(await account.locator("#account-current-password").inputValue(), "");
      await account.locator("#account-profile-edit").click();
      await page.screenshot({ path: path.join(output, `profil-${width}.png`) });
      await account.locator("#account-profile-name").fill("Steffen Royal");
      await account.locator("#account-profile-save").click();
      await account.getByText("Profil gespeichert.", { exact: true }).waitFor();
      assert.equal(await account.locator("#account-display-name").textContent(), "Steffen Royal");
      assert.equal(user.username, "jester");
      await account.locator("#account-profile-cancel").click();
      await account.locator('[data-account-credential="username"]').click();
      await account.locator("#account-current-password").fill("must-clear-on-tab-change");
      await account.locator('[data-account-tab="devices"]').click();
      assert.equal(await account.locator("#account-current-password").inputValue(), "");
      await page.evaluate(() => fixtureApp.settings.account.unmount());
      user = { ...user, role: "member" };
      await page.route("**/api/me/totp", route => route.fulfill({ status: 503, json: { detail: "Authenticator nicht abrufbar." } }));
      await page.evaluate(user => { fixtureApp.profile.auth.acceptUser(user); fixtureApp.settings.account.mount(); }, user);
      assert.equal(await account.locator('[data-account-tab="household"]').isVisible(), false);
      await account.getByText("Authenticator nicht abrufbar.", { exact: true }).waitFor();
      assert.equal(await account.locator('[data-totp="badge"]').textContent(), "Wird geprüft");
      assert.equal(await account.locator('[data-totp-ui="manage"]').isDisabled(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.deepEqual(errors, []);
      console.log(`Account ${width}: overview, sessions, household, profile and credentials passed`);
    } finally { await run.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
