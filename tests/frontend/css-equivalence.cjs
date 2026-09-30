// Compare all existing shell elements against the repository's original CSS.
// Requires an existing Playwright installation, just like browser-smoke.cjs.
const { chromium } = require(process.env.ROYAL_PLAYWRIGHT || "playwright");
const { readFileSync } = require("node:fs");
const { execFileSync } = require("node:child_process");
const { resolve } = require("node:path");
const assert = require("node:assert/strict");
const root = resolve(__dirname, "../..");
// Frozen pre-refactor baseline; HEAD changes as migration commits land.
const baselineRef = process.env.ROYAL_CSS_BASELINE || "7d93908";

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.ROYAL_BROWSER === "chromium" ? undefined : process.env.ROYAL_BROWSER || "msedge" });
  try {
    let baseline = true;
    const context = await browser.newContext();
    let page;
    await context.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.hostname !== "royal.test") return route.abort();
      const path = `web${url.pathname}`;
      if (!path.endsWith(".css")) return route.abort();
      let body;
      try {
        body = baseline && path !== "web/styles/components.css"
          ? execFileSync("git", ["show", `${baselineRef}:${path}`], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })
          : readFileSync(resolve(root, path), "utf8");
      } catch { body = readFileSync(resolve(root, path), "utf8"); }
      return route.fulfill({ contentType: "text/css", body });
    });
    const html = readFileSync(resolve(root, "web/index.html"), "utf8")
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
      .replace("<head>", '<head><base href="http://royal.test/">');
    const legacyRankingCss = ["web/storage-manager.js", "web/storage-move-jobs.js", "web/taste_v2.js", "web/daily_top_v2.js", "web/store.js"].map(path => {
      const script = execFileSync("git", ["show", `${baselineRef}:${path}`], { cwd: root, encoding: "utf8" });
      return script.match(/style\.textContent = `([\s\S]*?)`;/)?.[1] || "";
    }).join("\n");
    async function rankingFixture(withLegacyStyles) {
      // Intentional state bug fix, not a new visual baseline: legacy mobile CSS
      // paints the CLOSED menu's hidden scrim over the whole page. Compare the
      // intended closed state; its open-state styles remain unchanged.
      if (withLegacyStyles) await page.addStyleTag({ content: ".nav-menu-scrim[hidden] { display: none !important; }" });
      if (withLegacyStyles) await page.evaluate(async () => {
        for (const path of ["movie-releases", "storage-manager", "automation-policy", "subscription-center"]) {
          const link = document.createElement("link"); link.rel = "stylesheet"; link.href = `/styles/${path}.css`;
          const loaded = new Promise(resolve => { link.onload = resolve; link.onerror = resolve; });
          document.head.append(link); await loaded;
        }
      });
      await page.evaluate(({ css, withLegacyStyles }) => {
        if (withLegacyStyles) { const style = document.createElement("style"); style.textContent = css; document.head.append(style); }
        const track = document.getElementById("home-top-track");
        const card = document.createElement("article"); card.className = "home-card is-ranked";
        card.innerHTML = '<span class="home-card-art"><button class="taste-v2-dismiss" type="button">⊘</button><span class="home-card-overlay"><strong>Ranking fixture</strong><span class="daily-top-movement is-up">↑2</span></span></span>';
        track.append(card);
        const language = document.createElement("div"); language.className = "movie-language-choice";
        language.innerHTML = '<section class="movie-language-panel"><span class="movie-language-kicker">DOWNLOADSPRACHE</span><h3>Welche Sprache möchtest du?</h3><p>Fixture</p><div class="movie-language-options"><button class="movie-language-option"><b>🇩🇪</b><span><strong>Deutsch</strong><small>2 Hoster</small></span></button></div><button class="movie-language-cancel">Abbrechen</button></section>';
        document.body.append(language);
      }, { css: legacyRankingCss, withLegacyStyles });
    }
    const snapshot = () => page.evaluate(() => [...document.querySelectorAll("body, body *")]
      // The frozen baseline protects elements that already existed at 7d93908.
      // The household profile editor is a new post-baseline component and has
      // dedicated browser/API regressions, so there is no legacy visual state
      // for this subtree to compare against.
      .filter(element => !element.closest("#household-manage"))
      .map(element => {
        const style = getComputedStyle(element);
        return [element.id || element.className || element.tagName,
          ...["color", "backgroundColor", "backgroundImage", "borderTopColor", "borderRadius", "boxShadow", "fontSize", "padding", "display", "width", "height"].map(key => style[key])];
      }));
    for (const width of [1440, 390]) {
      if (page) await page.close();
      page = await context.newPage();
      await page.setViewportSize({ width, height: 1000 });
      baseline = true;
      await page.setContent(html, { waitUntil: "networkidle" });
      await rankingFixture(true);
      const before = await snapshot();
      baseline = false;
      await page.close(); page = await context.newPage();
      await page.setViewportSize({ width, height: 1000 });
      await page.setContent(html, { waitUntil: "networkidle" });
      await rankingFixture(false);
      const after = await snapshot();
      const changes = after.flatMap((row, index) => JSON.stringify(row) === JSON.stringify(before[index]) ? [] : [{ element: row[0], before: before[index], after: row }]);
      assert.deepEqual(changes, [], `Computed CSS changed at ${width}px`);
      console.log(JSON.stringify({ width, elements: after.length, equal: true }));
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
