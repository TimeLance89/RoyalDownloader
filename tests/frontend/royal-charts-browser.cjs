// Real Home and detail navigation, with deterministic chart and artwork responses.
const assert = require("node:assert/strict");
const { mkdirSync } = require("node:fs");
const { resolve } = require("node:path");
const { fixture } = require("./performance-fixture.cjs");

const output = resolve(process.env.ROYAL_CHARTS_OUTPUT || "artifacts/royal-charts-v3");
const day = new Date().toISOString().slice(0, 10);
const history = Array.from({ length: 30 }, (_, index) => ({
  period: new Date(Date.parse(day) - (29 - index) * 86400000).toISOString().slice(0, 10),
  recorded: index >= 27,
  rank: index >= 27 ? [4, 3, 1][index - 27] : null,
}));
const titles = ["Nachtfahrt", "Unter Strom", "Roter Horizont", "Der letzte Hafen", "Nachhall",
  "Das Schattenarchiv", "Stiller Alarm", "Nordlicht", "Fluchtpunkt", "Die dritte Tür", "Dunkelkammer"];
const entries = titles.map((title, index) => {
  const series = index === 1 || index === 4;
  const slug = `chart-${index}`;
  return {
    identity: `${series ? "series" : "movie"}:fixture:${index}`,
    kind: series ? "series" : "movie", global_rank: index + 1, score: 93 - index, mode_score: 93 - index,
    item: { title, ...(series ? { base_slug: slug, sample_slug: slug + "-s01e01" } : { slug }),
      year: "2026", rating: 7.8, vote_count: 2200, cover_url: `/chart-poster-${index}.svg`,
      provider: series ? "serienstream" : "megakino", genres: [index % 2 ? "Krimi" : "Drama"] },
    movement: [{ direction: "up", delta: 2, previous_rank: 3 }, { direction: "returning" },
      { direction: "new" }, { direction: "down", delta: -1, previous_rank: 3 }][index] || { direction: "unknown" },
    provider_signals: { megakino: { rank: index + 1, type: "views_rank", source: "megakino" } },
    availability_providers: [series ? "serienstream" : "megakino"],
    confidence: "medium", components: { popularity: 95, quality: 75 }, quality_source: "tmdb_votes",
    history: { days_charted: 3, best_rank: 1, streak: 3, last_day: day, last_7: history.slice(-7), last_30: history },
  };
});

function poster(index) {
  const hue = [3, 195, 35, 220, 280, 140][index % 6];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="480" viewBox="0 0 320 480">
  <defs><linearGradient id="sky" x2="1" y2="1"><stop stop-color="hsl(${hue},50%,44%)"/><stop offset="1" stop-color="#171922"/></linearGradient></defs>
  <path fill="url(#sky)" d="M0 0h320v480H0z"/><circle cx="191" cy="137" r="73" fill="#ffe5b5" opacity=".6"/>
  <path fill="#20232d" d="M0 328l74-97 49 46 66-100 131 158v145H0z"/><path fill="#12141c" d="M0 359l105-63 66 34 149-90v240H0z"/>
  <text x="160" y="75" text-anchor="middle" fill="#fff2d8" font-family="sans-serif" font-size="22" font-weight="bold">${titles[index]}</text>
  </svg>`;
}

async function verify(viewport, mobile) {
  const { page, errors, close } = await fixture({ viewport, mobile });
  const calls = [];
  const detailRequests = [];
  let breakoutError = true;
  const click = locator => mobile ? locator.tap() : locator.click();
  try {
    await page.route("**/chart-poster-*.svg", route => {
      const index = Number(new URL(route.request().url()).pathname.match(/\d+/)[0]);
      return route.fulfill({ contentType: "image/svg+xml", body: poster(index) });
    });
    await page.route("**/api/jellyfin/matches", route => route.fulfill({ json: {
      configured: true, statuses: Object.fromEntries((route.request().postDataJSON().items || [])
        .map((item, index) => [item.slug, index % 2 ? "missing" : "owned"])),
    } }));
    await page.route("**/api/movie/chart-*", route => {
      detailRequests.push("movie");
      return route.fulfill({ json: { movie: { ...entries[0].item, hosters: [], streams: [] } } });
    });
    await page.route("**/api/series/load", route => {
      detailRequests.push("series");
      return route.fulfill({ json: { ...entries[1].item, seasons: [], episode_count: 0 } });
    });
    const feedback = [];
    await page.route("**/api/taste/feedback", route => {
      const body = route.request().postDataJSON();
      feedback.push(body);
      return route.fulfill({ json: { profile: { blocked_items: [body.item_key] } } });
    });
    await page.route("**/api/v3/royal-charts?*", async route => {
      const mode = new URL(route.request().url()).searchParams.get("mode");
      calls.push(mode);
      if (mode === "week") await new Promise(resolve => setTimeout(resolve, 350));
      if (mode === "breakouts" && breakoutError) {
        breakoutError = false;
        return route.fulfill({ status: 503, json: { detail: "fixture unavailable" } });
      }
      const candidates = { today: entries, week: [entries[1], entries[0]], month: entries.slice(0, 3),
        breakouts: [], new: [entries[2]] }[mode];
      await route.fulfill({ json: { version: 3, scope: "fixture", period: day, chart_day: day, mode, recorded_days: 3,
        empty_reason: mode === "breakouts" ? "insufficient_history" : null, candidates } });
    });
    await page.reload({ waitUntil: "networkidle" });
    const rail = page.locator(".home-rail-top");
    const track = rail.locator("#home-top-track");
    const cards = track.locator(".home-card");
    await cards.nth(9).waitFor({ state: "attached" });
    await cards.first().locator(".catalog-jellyfin-badge.is-owned").waitFor();
    assert.equal(await cards.count(), 10);
    assert.equal(await cards.nth(9).locator(".home-card-rank").textContent(), "10");
    assert.equal(await cards.first().locator(".daily-top-movement").textContent(), "↑ 2");
    assert.equal(await cards.nth(1).locator(".daily-top-movement").textContent(), "RE");
    assert.equal(await cards.nth(2).locator(".daily-top-movement").textContent(), "NEW");
    assert.equal(await cards.nth(4).locator(".daily-top-movement").count(), 0);
    await rail.evaluate(node => node.scrollIntoView({ block: "center", behavior: "instant" }));
    const geometry = await cards.first().locator(".home-card-art").boundingBox();
    assert.ok(Math.abs(geometry.width / geometry.height - 2 / 3) < 0.02, "ranked poster stays 2:3");
    assert.ok(await track.evaluate(node => node.scrollWidth > node.clientWidth), "native carousel remains scrollable");
    assert.ok(await rail.locator(".royal-charts-controls").evaluate(node =>
      node.getBoundingClientRect().right <= innerWidth), "chart controls fit the viewport");
    await rail.screenshot({ path: resolve(output, mobile ? "mobile.png" : "desktop.png"), animations: "disabled" });

    await click(rail.getByRole("button", { name: "Diese Woche", exact: true }));
    await rail.getByText("Charts werden geladen …").waitFor();
    await track.getByText("Unter Strom").waitFor();
    assert.equal(await cards.first().locator(".home-card-rank").textContent(), "1");
    assert.equal(await cards.first().getAttribute("data-daily-top-global-rank"), "2");
    await click(rail.getByRole("button", { name: "Durchstarter", exact: true }));
    await rail.getByText("Charts konnten nicht geladen werden.").waitFor();
    await click(rail.getByRole("button", { name: "Erneut laden" }));
    await rail.getByText("Für diese Wertung fehlen noch vergleichbare Tagesstände.").waitFor();
    await click(rail.getByRole("button", { name: "Heute", exact: true }));
    assert.equal(calls.filter(mode => mode === "today").length, 1);

    const info = cards.first().getByRole("button", { name: "Chart-Details zu Nachtfahrt" });
    if (!mobile) await cards.first().hover();
    const infoBounds = await info.boundingBox();
    const dismissBounds = await cards.first().getByRole("button", { name: "Nicht für mich" }).boundingBox();
    assert.ok(infoBounds.y >= dismissBounds.y + dismissBounds.height, "details and feedback hit targets are separate");
    await click(info);
    const explanation = page.locator("#royal-chart-detail");
    await explanation.getByText("Gestern Platz 3").waitFor();
    assert.equal(await explanation.locator(".royal-chart-timeline li").count(), 7);
    await explanation.getByLabel("Zeitraum des Chart-Verlaufs").selectOption("last_30");
    assert.equal(await explanation.locator(".royal-chart-timeline li").count(), 30);
    await click(explanation.getByRole("button", { name: "Chart-Details schließen" }));
    await click(rail.getByRole("button", { name: "Alle Charts entdecken" }));
    const full = page.locator("#royal-charts");
    await full.waitFor();
    assert.equal(await full.locator(".home-card").count(), 11);
    await full.screenshot({ path: resolve(output, mobile ? "charts-mobile.png" : "charts-desktop.png"), animations: "disabled" });
    await click(full.getByRole("button", { name: "30 Tage" }));
    await full.getByText("3 erfasste Tage in dieser Wertung").waitFor();
    assert.equal(await full.locator(".home-card").count(), 3);
    await click(full.getByRole("button", { name: "Neueinsteiger" }));
    await full.getByText("Roter Horizont").waitFor();
    assert.equal(await full.locator(".home-card").count(), 1);
    await click(full.getByRole("button", { name: "Heute", exact: true }));
    await full.getByLabel("Medientyp").selectOption("series");
    assert.equal(await full.locator(".home-card").count(), 2);
    await full.getByLabel("Genre").selectOption("Krimi");
    assert.equal(await full.locator(".home-card").count(), 1);
    await click(full.getByRole("button", { name: /Platz 1: Unter Strom/ }));
    await page.locator("#series-detail-modal.is-open").waitFor();
    assert.ok(detailRequests.includes("series"));
    assert.equal(await full.evaluate(dialog => dialog.open), false);
    await page.keyboard.press("Escape");
    await click(cards.first().getByRole("button", { name: /Platz 1: Nachtfahrt/ }));
    await page.locator("#fp-detail-modal.is-open").waitFor();
    assert.ok(detailRequests.includes("movie"));
    await page.keyboard.press("Escape");
    const dismiss = cards.first().getByRole("button", { name: "Nicht für mich" });
    if (mobile) await dismiss.tap();
    else { await dismiss.focus(); await page.keyboard.press("Enter"); }
    await track.getByText("Nachtfahrt").waitFor({ state: "detached" });
    assert.equal(feedback[0].action, "dismiss");
    assert.deepEqual(errors, []);
  } finally {
    await close();
  }
}

(async () => {
  mkdirSync(output, { recursive: true });
  await verify({ width: 1440, height: 1000 }, false);
  await verify({ width: 390, height: 844 }, true);
  console.log("Royal Charts passed desktop and mobile browser checks");
})().catch(error => { console.error(error); process.exitCode = 1; });
