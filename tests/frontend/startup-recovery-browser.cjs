// Real module graph: missing imports, a missing entry, and normal startup.
const { createServer } = require("node:http");
const { readFile } = require("node:fs/promises");
const { resolve, extname, sep } = require("node:path");
const assert = require("node:assert/strict");
const playwright = require(process.env.ROYAL_PLAYWRIGHT || "playwright");
const web = resolve(__dirname, "../../web");
let failing = "", bundled = false;
const seen = [];
async function bundle() {
  let source = await readFile(resolve(web, "style.css"), "utf8");
  const imports = [...source.matchAll(/@import\s+url\(['"]([^'"]+)['"]\);/g)];
  for (const match of imports) source = source.replace(match[0], await readFile(resolve(web, "." + match[1].split("?")[0]), "utf8"));
  return source;
}
const server = createServer(async (req, res) => {
  // Match production static responses: retries must never reuse an old entry.
  res.setHeader("Cache-Control", "no-store");
  const url = new URL(req.url, "http://local"); seen.push(url.pathname);
  if (url.pathname === failing) return res.writeHead(502).end("Controlled module failure");
  if (bundled && url.pathname === "/style.css") { res.setHeader("Content-Type", "text/css"); return res.end(await bundle()); }
  if (url.pathname.startsWith("/api/")) {
    res.setHeader("Content-Type", "application/json");
    return res.end(JSON.stringify(url.pathname === "/api/auth/status" ? { configured: true, authenticated: false } : {}));
  }
  const file = resolve(web, "." + (url.pathname === "/" ? "/index.html" : url.pathname));
  if (!file.startsWith(web + sep)) return res.writeHead(403).end();
  try { res.setHeader("Content-Type", { ".js": "text/javascript", ".css": "text/css", ".html": "text/html" }[extname(file)] || "application/octet-stream"); res.end(await readFile(file)); }
  catch { res.writeHead(404).end(); }
});
(async () => {
  await new Promise(done => server.listen(0, "127.0.0.1", done));
  const browser = await playwright[process.env.ROYAL_BROWSER || "chromium"].launch({ headless: true });
  try {
    async function newContext() {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
      await context.route("**/*", route => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.fulfill({ body: "", contentType: "text/css" }));
      return context;
    }
    const url = `http://127.0.0.1:${server.address().port}/`;
    for (const path of ["/js/features/home/lanes.js", "/app.js"]) {
      // Isolate WebKit's resource/module caches from the previous successful retry.
      const failureContext = await newContext();
      const page = await failureContext.newPage();
      // Recovery must work even when script resource errors are not delivered.
      await page.addInitScript(() => window.addEventListener("error", event => event.stopImmediatePropagation(), true));
      failing = path;
      seen.length = 0;
      const start = Date.now();
      const [failureResponse] = await Promise.all([
        page.waitForResponse(response => new URL(response.url()).pathname === path, { timeout: 5000 }),
        page.goto(url, { waitUntil: "domcontentloaded" }),
      ]);
      assert.equal(failureResponse.status(), 502, `fault injection for ${path} must actually reach the browser`);
      try { await page.locator("#royal-boot-error").waitFor({ timeout: 5000 }); }
      catch (error) { throw new Error(`Boot recovery for ${path} failed: ${error.message}`); }
      assert.equal(await page.locator("#royal-loader").count(), 0);
      assert.ok(Date.now() - start < 5000, `failed ${path} must not wait for the watchdog`);
      assert.equal(seen.filter(request => request === "/app.js").length, 1, "observing the entry must not duplicate its request");
      failing = "";
      await page.getByRole("button", { name: "Erneut laden", exact: true }).click();
      await page.locator("#login-username").waitFor({ state: "visible" });
      assert.equal(await page.locator("#royal-boot-error").count(), 0);
      console.log(JSON.stringify({ recoveryCase: path, injectedStatus: failureResponse.status(), retry: "passed" }));
      await failureContext.close();
    }
    const context = await newContext();
    const page = await context.newPage();
    const stalled = await context.newPage();
    await stalled.clock.install();
    await stalled.route("**/app.js?*", route => route.fulfill({ contentType: "text/javascript", body: "await new Promise(() => {});" }));
    await stalled.goto(url, { waitUntil: "commit" });
    await stalled.locator("#royal-loader").waitFor({ state: "attached" });
    await stalled.clock.fastForward(21000);
    await stalled.locator("#royal-boot-error").waitFor();
    assert.equal(await stalled.locator("#royal-loader").count(), 0);
    await stalled.close();
    // Same viewport, fonts, cascade and login state: compare actual rendered pixels.
    const screenshots = [], counts = [];
    for (const inline of [false, true]) {
      bundled = inline; seen.length = 0;
      await page.goto(url, { waitUntil: "networkidle" });
      await page.locator("#login-username").waitFor({ state: "visible" });
      await page.locator("#royal-loader").waitFor({ state: "detached" });
      assert.equal(await page.locator("#royal-boot-error").count(), 0);
      await page.addStyleTag({ content: "* { animation: none !important; transition: none !important; caret-color: transparent !important; }" });
      screenshots.push(await page.screenshot({ animations: "disabled" }));
      counts.push(seen.filter(path => path.startsWith("/styles/")).length);
    }
    assert.equal(Buffer.compare(screenshots[0], screenshots[1]), 0, "bundling cannot alter visible UI pixels");
    assert.equal(counts[0] - counts[1], 44);
    console.log(JSON.stringify({ engine: process.env.ROYAL_BROWSER || "chromium", recovery: "import + entry", identicalPixels: true, eliminatedStylesheetRequests: 44 }));
    await context.close();
  } finally { await browser.close(); await new Promise(done => server.close(done)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
