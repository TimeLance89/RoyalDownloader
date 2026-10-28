const assert = require("node:assert/strict");
const { fixture } = require("./performance-fixture.cjs");

(async () => {
  for (const width of [1440, 390, 430]) {
    const run = await fixture({ engine: process.env.ROYAL_BROWSER || "chromium", mobile: width !== 1440,
      viewport: { width, height: width === 1440 ? 1000 : 932 } });
    const { page, errors } = run;
    const hidden = new Map(), writes = [];
    let revision = 1, fail = false;
    const user = { id: "performance-fixture", username: "royal", role: "admin" };
    const series = { base_slug: "series-one", title: "Serie Eins", open_count: 1, new_count: 1, inbox_episode_revision: "episode-a" };
    try {
      await page.route("**/api/watchlist", route => route.fulfill({ json: { watchlist: [series], health: {} } }));
      await page.route("**/api/announcements", route => route.fulfill({ json: { enabled: true, items: [
        { id: "news", revision: 1, title: "Royal-Mitteilung", body: "Eine Nachricht", created_at: 1700000000, read: false },
      ] } }));
      await page.route("**/api/providers/incidents", route => route.fulfill({ json: { items: Array.from({ length: 27 }, (_, i) => ({
        id: `incident-${i}-${revision}`, label: `Hoster ${i}`, read: false, message: "Prüfhinweis", kind: "hoster",
      })) } }));
      await page.route("**/api/inbox/dismissals", async route => {
        const request = route.request(), owner = request.headers()["x-royal-profile"];
        if (!hidden.has(owner)) hidden.set(owner, new Set());
        if (request.method() === "POST") {
          if (fail) return route.fulfill({ status: 503, json: { detail: "Speichern fehlgeschlagen." } });
          const body = request.postDataJSON(); writes.push({ owner, body });
          body.keys.forEach(key => hidden.get(owner).add(key));
          return route.fulfill({ json: { dismissed: true } });
        }
        return route.fulfill({ json: { keys: [...hidden.get(owner)] } });
      });
      await page.evaluate(({ user, series }) => {
        fixtureApp.profile.auth.acceptUser(user);
        fixtureApp.subscriptions.subscriptions.accept({ watchlist: [series], health: {} });
        fixtureApp.subscriptions.notifications.open();
      }, { user, series });
      const inbox = page.locator("#notif-dropdown");
      await inbox.locator(".source-issue-group summary").filter({ hasText: "27 Hinweise" }).waitFor();
      await page.waitForFunction(() => document.querySelector("#notif-summary").textContent === "3 Einträge");
      assert.equal(await inbox.locator(".source-issue-group").evaluate(node => node.open), false);
      assert.equal(await inbox.locator('[data-notif-filter="all"] .notif-filter-count').textContent(), "3");
      assert.equal(await inbox.locator('[data-notif-filter="new"] .notif-filter-count').textContent(), "2");
      assert.equal(await inbox.locator('[data-notif-filter="issue"] .notif-filter-count').textContent(), "1");
      const bounds = await inbox.evaluate(node => {
        const title = node.querySelector(".notif-head-copy").getBoundingClientRect();
        const range = document.createRange(); range.selectNodeContents(node.querySelector("#notif-title"));
        const titleText = range.getBoundingClientRect();
        const actions = node.querySelector(".notif-head-actions").getBoundingClientRect();
        const close = node.querySelector("#notif-close").getBoundingClientRect();
        const refresh = node.querySelector("#notif-refresh").getBoundingClientRect();
        const remove = node.querySelector("#notif-dismiss-all").getBoundingClientRect();
        return { separateRows: actions.top >= title.bottom, buttonsFit: refresh.right <= remove.left && remove.right <= node.getBoundingClientRect().right,
          closeClear: close.left >= titleText.right };
      });
      if (width !== 1440) assert.deepEqual(bounds, { separateRows: true, buttonsFit: true, closeClear: true });
      await inbox.screenshot({ path: require("node:path").join(require("node:os").tmpdir(), `royal-inbox-${width}.png`) });
      await inbox.getByRole("button", { name: "Meldung für Serie Eins entfernen", exact: true }).click();
      await page.waitForFunction(() => !document.querySelector('.notif-item[data-base-slug="series-one"]'));
      assert.equal(await page.evaluate(() => fixtureApp.subscriptions.subscriptions.get().items.length), 1);
      await inbox.locator('[data-notif-filter="issue"]').click();
      await inbox.locator(".source-issue-group summary").click();
      await inbox.getByRole("button", { name: "Quellenhinweis Hoster 0 entfernen", exact: true }).click();
      await inbox.locator(".source-issue-group summary").filter({ hasText: "26 Hinweise" }).waitFor();
      fail = true;
      await inbox.locator("#notif-dismiss-all").click();
      await inbox.getByText(/Entfernen fehlgeschlagen/).waitFor();
      assert.equal(await inbox.locator(".source-issue-group").count(), 1);
      fail = false;
      await inbox.locator("#notif-dismiss-all").click();
      await page.waitForFunction(() => !document.querySelector(".source-issue-group"));
      assert.equal(writes.at(-1).body.keys.length, 26);
      await inbox.locator('[data-notif-filter="all"]').click();
      await inbox.getByRole("button", { name: "Mitteilung Royal-Mitteilung entfernen", exact: true }).click();
      await page.waitForFunction(() => document.querySelector("#notif-summary").textContent === "Keine Meldungen");
      await page.evaluate(() => { fixtureApp.subscriptions.notifications.unmount(); fixtureApp.subscriptions.notifications.mount(); fixtureApp.subscriptions.notifications.open(); });
      await page.waitForFunction(() => document.querySelector("#notif-summary").textContent === "Keine Meldungen");
      revision++;
      await page.evaluate(() => fixtureApp.subscriptions.notifications.open());
      await inbox.locator(".source-issue-group summary").waitFor();
      assert.equal(await inbox.locator('[data-notif-filter="all"] .notif-filter-count').textContent(), "1");
      assert.ok(writes.every(write => write.owner === user.id));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.evaluate(user => {
        fixtureApp.subscriptions.notifications.unmount();
        fixtureApp.profile.auth.acceptUser({ ...user, id: "other-profile" });
        fixtureApp.subscriptions.notifications.mount(); fixtureApp.subscriptions.notifications.open();
      }, user);
      await page.waitForFunction(() => document.querySelector("#notif-summary").textContent === "3 Einträge");
      assert.equal(await inbox.locator('.notif-item[data-base-slug="series-one"]').count(), 1);
      assert.deepEqual(errors, []);
    } finally { await run.close(); }
  }
  console.log("Inbox: 27 sources collapsed, consistent counts, profile-bound persistent removal, failures and fresh events passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
