import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const api = readFileSync(new URL("../web/api.js", import.meta.url), "utf8");
const login = readFileSync(new URL("../web/screens/login.js", import.meta.url), "utf8");
const workflow = readFileSync(new URL("../.github/workflows/quality.yml", import.meta.url), "utf8");
const stylesheet = readFileSync(new URL("../web/style.css", import.meta.url), "utf8");
const accountStyles = readFileSync(
  new URL("../web/styles/legacy-account.css", import.meta.url),
  "utf8",
);
const appModulePaths = [
  "core.js",
  "screens/home.js",
  "screens/movies.js",
  "screens/series.js",
  "screens/anime.js",
  "screens/library.js",
  "screens/notifications.js",
  "screens/settings.js",
  "screens/account.js",
  "screens/setup.js",
  "app.js",
];
const app = appModulePaths
  .map((path) => readFileSync(new URL(`../web/${path}`, import.meta.url), "utf8"))
  .join("\n");
const frontend = `${login}\n${app}`;

function requiresIds(...ids) {
  for (const id of ids) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
    assert.match(frontend, new RegExp(`getElementById\\(["']${id}["']\\)`));
  }
}

test("login flow keeps its browser and API contract", () => {
  requiresIds("login-screen", "login-form", "login-username", "login-password", "login-submit");
  assert.match(api, /authStatus\(\)/);
  assert.match(api, /authLogin\(username, password\)/);
});

test("detail, queue, and settings screens remain wired", () => {
  requiresIds("fp-detail-modal", "fp-detail-title", "fp-detail-add");
  requiresIds("queue-drawer", "queue-list", "queue-count");
  requiresIds("settings-btn");
  assert.match(html, /id=["']settings-general["']/);
  assert.match(html, /id=["']settings-system["']/);
  assert.match(app, /data-settings-target/);
  assert.match(api, /queueGet\(\)/);
  assert.match(api, /queueAdd\(slugs/);
  assert.match(api, /configGet\(\)/);
});

test("movie and series catalogs lazy-load for mobile document scrolling", () => {
  for (const id of ["tab-filme", "fp-infinite", "tab-serien", "series-infinite"]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(app, /window\.addEventListener\("scroll", schedule, \{ passive: true \}\)/);
  assert.match(app, /sentinel\.getBoundingClientRect\(\)\.top <= viewportHeight \+ CATALOG_PRELOAD_PX/);
  assert.match(app, /container\.classList\.contains\("active"\)/);
  assert.match(app, /recheckFpInfinite = bind\("tab-filme", "fp-infinite", loadNextFpPage\)/);
  assert.match(app, /recheckSeriesInfinite = bind\("tab-serien", "series-infinite", loadNextSeriesPage\)/);
  assert.match(html, /app\.js\?v=royal-20260803-1/);
});

test("home series rail falls back when the trending provider is unavailable", () => {
  assert.match(html, /screens\/home\.js\?v=royal-20260802-2/);
  assert.match(app, /function homePopularSeriesEntries\(\)/);
  assert.match(app, /state\.home\.newSeries\.map\(homeSeriesEntry\)/);
  assert.match(app, /state\.home\.discoverySeries\.map\(homeSeriesEntry\)/);
  assert.match(app, /Serien aus deinen aktiven Quellen/);
});

test("feature modules load in dependency order before bootstrap", () => {
  const sources = [...html.matchAll(/<script src="\/([^"?]+)/g)]
    .map((match) => match[1]);
  const positions = appModulePaths.map((path) => sources.indexOf(path));
  assert.ok(positions.every((position) => position >= 0));
  assert.deepEqual(positions, [...positions].sort((left, right) => left - right));
});

test("the stylesheet manifest preserves every ordered CSS module", () => {
  const imports = [...stylesheet.matchAll(/@import url\("\/([^"?]+)/g)]
    .map((match) => match[1]);
  assert.deepEqual(imports, [
    "styles/base.css",
    "styles/legacy-foundation.css",
    "styles/legacy-components.css",
    "styles/legacy-account.css",
    "styles/legacy-layout.css",
    "styles/legacy-details.css",
    "styles/overrides-core.css",
    "styles/movie-subscriptions.css",
    "styles/login.css",
    "styles/library.css",
    "styles/movie-home.css",
    "styles/search.css",
    "styles/series.css",
    "styles/catalog.css",
  ]);
  for (const path of imports) {
    assert.ok(existsSync(new URL(`../web/${path}`, import.meta.url)), path);
  }
});

test("the document has unique IDs and CI checks nested JavaScript", () => {
  const ids = [...html.matchAll(/\sid=["']([^"']+)["']/g)].map((match) => match[1]);
  assert.equal(ids.length, new Set(ids).size, "index.html contains duplicate IDs");
  assert.match(workflow, /find web -type f -name '\*\.js'/);
  assert.doesNotMatch(workflow, /find web -maxdepth 1/);
});

test("mobile navigation fills the viewport and distributes visible tabs", () => {
  assert.match(html, /viewport-fit=cover/);
  assert.match(stylesheet, /legacy-account\.css\?v=royal-20260803-1/);
  assert.match(
    accountStyles,
    /\.mobile-tabs\s*\{[\s\S]*?left:\s*0;[\s\S]*?right:\s*0;[\s\S]*?bottom:\s*0;/,
  );
  assert.match(accountStyles, /env\(safe-area-inset-bottom\)/);
  assert.match(
    accountStyles,
    /\.mobile-tabs \.tab-btn:not\(\.hidden\)\s*\{\s*flex:\s*1 1 0;/,
  );
  assert.doesNotMatch(
    accountStyles,
    /grid-template-columns:\s*repeat\(5,\s*1fr\)/,
  );
});

test("persistent queue jobs expose mobile controls and separate history", () => {
  requiresIds("queue-list", "queue-history-list", "queue-history-count");
  assert.match(api, /queueJobCancel\(jobId\)/);
  assert.match(api, /queueJobRetry\(jobId\)/);
  assert.match(api, /queueJobMove\(jobId, direction\)/);
  assert.match(api, /queueJobResume\(jobId\)/);
  assert.match(app, /row\.dataset\.jobId/);
  assert.match(app, /function renderQueueHistory\(jobs\)/);
  assert.match(app, /function updateQueueJobProgress\(jobId, job\)/);
  assert.match(accountStyles, /\.queue-action-btn[\s\S]*touch-action:\s*manipulation/);
});
