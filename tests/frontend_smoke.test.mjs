import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const api = readFileSync(new URL("../web/api.js", import.meta.url), "utf8");
const login = readFileSync(new URL("../web/screens/login.js", import.meta.url), "utf8");
const mood = readFileSync(new URL("../web/screens/mood.js", import.meta.url), "utf8");
const home = readFileSync(new URL("../web/screens/home.js", import.meta.url), "utf8");
const workflow = readFileSync(new URL("../.github/workflows/quality.yml", import.meta.url), "utf8");
const stylesheet = readFileSync(new URL("../web/style.css", import.meta.url), "utf8");
const accountStyles = readFileSync(
  new URL("../web/styles/legacy-account.css", import.meta.url),
  "utf8",
);
const appModulePaths = [
  "core.js",
  "screens/home.js",
  "screens/mood.js",
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
  assert.match(html, /app\.js\?v=royal-20260805-7/);
});

test("searches run only after an explicit submit", () => {
  assert.match(app, /globalSearchToggle\.addEventListener\("click", openGlobalSearch\)/);
  assert.match(app, /globalSearchInput\.addEventListener\("input", syncGlobalSearchDraft\)/);
  assert.match(app, /if \(event\.key === "Enter"\) \{[\s\S]*?runGlobalSearch\(\)/);
  for (const [inputId, panelId] of [
    ["home-search", "home-search-suggestions"],
    ["fp-search", "fp-search-suggestions"],
    ["series-search", "series-search-suggestions"],
  ]) {
    assert.match(
      app,
      new RegExp(`getElementById\\("${inputId}"\\)\\.addEventListener\\("input", \\(\\) => \\{\\s*syncSearchClearButtons\\(\\);\\s*closeSearchSuggestions\\("${panelId}", "${inputId}"\\);`),
    );
  }
  assert.match(app, /getElementById\("anime-search"\)\.addEventListener\("keydown", \(event\) => \{\s*if \(event\.key !== "Enter"\) return;/);
  assert.doesNotMatch(app, /queueGlobalSearch/);
  assert.doesNotMatch(app, /debounceTimer/);
  assert.doesNotMatch(app, /addEventListener\("focus", \(\) => \{\s*renderSearchSuggestions/);
  assert.doesNotMatch(app, /value\.trim\(\)\) homeSearch\(\)/);
  assert.match(app, /globalSearchPage\.addEventListener\("click", \(event\) => \{/);
  assert.match(app, /if \(event\.target\.closest\("\.global-search-head, \.home-card"\)\) return;/);
});

test("global search covers every catalog and exposes Jellyfin filters", () => {
  requiresIds("global-search-input", "global-search-page", "global-search-jellyfin");
  for (const scope of ["all", "movie", "series", "anime"]) {
    assert.match(html, new RegExp(`data-global-search-scope=["']${scope}["']`));
  }
  assert.match(app, /api\.anime\(\{ mode: "search", query, page: 1 \}\)/);
  assert.match(app, /function refreshCatalogJellyfinStatus\(entries, render\)/);
  assert.match(app, /media_type: kind === "movie" \? "movie" : "series"/);
  assert.match(app, /setFpJellyfinBadge\(jellyfin, mediaJellyfinStatus\(result\)\)/);
  assert.match(app, /state\.anime\.results\.map\(homeAnimeEntry\)/);
  assert.match(app, /for \(let index = 0; index < requests\.length; index \+= 100\)/);
  assert.match(app, /batches\.map\(\(batch\) => api\.jellyfinMatches\(batch\)\)/);
});

test("home series rail falls back when the trending provider is unavailable", () => {
  assert.match(html, /api\.js\?v=royal-20260805-2/);
  assert.match(html, /screens\/home\.js\?v=royal-20260805-9/);
  assert.match(app, /function homePopularSeriesEntries\(\)/);
  assert.match(app, /state\.home\.newSeries\.map\(homeSeriesEntry\)/);
  assert.match(app, /state\.home\.discoverySeries\.map\(homeSeriesEntry\)/);
  assert.match(app, /Serien aus deinen aktiven Quellen/);
});

test("only Top 10 cards may fall back to portrait posters", () => {
  assert.match(app, /rank\s*\? \[media\.cover_url, media\.backdrop_url\]\s*:\s*\[media\.backdrop_url\]/);
  assert.doesNotMatch(app, /rank \? media\.backdrop_url : media\.cover_url/);
});

test("series wallpaper hydration updates every duplicate catalog object", async () => {
  const trending = { base_slug: "same-series", title: "Same Series", cover_url: "/poster.jpg", genres: [] };
  const discovery = { base_slug: "same-series", title: "Same Series", cover_url: "/poster.jpg", genres: [] };
  const context = vm.createContext({
    console,
    api: {
      tmdbSeries: async () => ({
        series: {
          "same-series": {
            backdrop_url: "/wallpaper.jpg",
            genres: ["Drama"],
          },
        },
      }),
    },
    renderHome: () => {},
  });
  vm.runInContext(home.slice(home.indexOf("async function hydrateHomeSeriesArtwork")), context);
  context.items = [trending, discovery];
  await vm.runInContext("hydrateHomeSeriesArtwork(items, { render: false })", context);
  assert.equal(trending.backdrop_url, "/wallpaper.jpg");
  assert.equal(discovery.backdrop_url, "/wallpaper.jpg");
  assert.deepEqual(trending.genres, ["Drama"]);
  assert.deepEqual(discovery.genres, ["Drama"]);
});

test("home discovery is larger, shuffleable, and avoids repetitive rails", () => {
  assert.match(html, /id=["']home-program-title["']/);
  requiresIds("home-program-note", "home-discovery-shuffle");
  assert.match(app, /function homeDiscoveryLanes\(\)/);
  assert.match(app, /function takeDistinctHomeLane\(entries, seen, limit, minimum = 4\)/);
  assert.match(app, /fresh: homeNewEntries\(\)/);
  assert.match(app, /function shuffleHomeDiscovery\(\)/);
  assert.match(app, /layout === "spotlight"/);
  assert.match(stylesheet, /catalog\.css\?v=royal-20260805-5/);
});

test("mood mode asks for the moment, protects family picks, and nudges taste", () => {
  requiresIds("mood-modal", "mood-options", "mood-results", "mood-back", "mood-next");
  assert.match(html, /id="mood-nav-open"[^>]*data-mood-open/);
  assert.match(html, /id="home-program-mood"[^>]*data-mood-open/);
  assert.match(app, /const MOOD_MATCH_STEPS = \[/);
  assert.match(app, /Dunkel & brutal/);
  assert.match(app, /Mit der Familie/);
  assert.match(app, /function moodFamilyPool\(entries\)/);
  assert.match(app, /function moodMatchResults\(answers\)/);
  assert.match(app, /const MOOD_MATCH_RULES = \{/);
  assert.match(app, /pool = pool\.filter\(\(entry\) => moodMatchesIntent\(entry, answers\)\)/);
  assert.match(app, /horror:[\s\S]*?required: \["Horror", "Slasher", "Splatter"\]/);
  assert.match(app, /fallback: \["Thriller", "Mystery", "Krimi", "Crime"\]/);
  assert.match(app, /hardExcluded: \["Komödie", "Comedy", "Animation", "Romanze", "Musik"\]/);
  assert.match(app, /left\.tier - right\.tier \|\| right\.score - left\.score/);
  assert.match(app, /function prepareMoodCandidates\(\)/);
  assert.match(app, /await prepareMoodCandidates\(\)/);
  assert.match(app, /return moodIntentTier\(entry, answers\) < 3/);
  assert.match(app, /Genres und Metadaten werden vervollständigt/);
  assert.match(app, /card\.addEventListener\("click", suspendMoodMatchForDetail/);
  assert.match(app, /function resumeMoodMatchAfterDetail\(\)/);
  assert.match(app, /resumeMoodMatchAfterDetail\(\)/);
  assert.match(html, /core\.js\?v=royal-20260805-4/);
  assert.match(html, /screens\/mood\.js\?v=royal-20260805-5/);
  assert.match(app, /source: "mood-session"/);
  assert.match(app, /profile\.genres\[genre\].*\+ \.2/);
});

test("mood recommendations remain useful without admitting contradictory filler", () => {
  const entries = [
    { kind: "movie", item: { slug: "slasher", title: "Slasher", genres: ["Horror"] } },
    { kind: "movie", item: { slug: "thriller", title: "Dark Thriller", genres: ["Thriller"] } },
    { kind: "movie", item: { slug: "unknown", title: "Unknown", genres: [] } },
    { kind: "movie", item: { slug: "comedy", title: "Horror Comedy", genres: ["Horror", "Komödie"] } },
    { kind: "movie", item: { slug: "family", title: "Family Adventure", genres: ["Animation", "Abenteuer"] } },
  ];
  const context = vm.createContext({
    console,
    state: { fp: { metadataCache: {} }, home: { mood: {} } },
    homeEntryMedia: (entry) => entry.item,
    homeEntryKey: (entry) => `${entry.kind}:${entry.item.slug}`,
    homeAllEntries: () => entries,
    allowedHomeEntries: (items) => items,
    uniqueHomeEntries: (items) => items,
    loadDiscoveryProfile: () => ({ genres: {}, recent: [] }),
    stableDiscoveryHash: () => 0,
    localDateKey: () => "2026-08-05",
  });
  vm.runInContext(mood, context);
  const results = vm.runInContext(`moodMatchResults({
    mood: "horror", company: "alone", intensity: "hard", format: "movie"
  })`, context);
  assert.deepEqual(
    Array.from(results, (entry) => entry.item.title),
    ["Slasher", "Dark Thriller", "Unknown"],
  );
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

test("Royal archive behaves like a searchable media center", () => {
  requiresIds(
    "library-hero-title", "wl-hero-open", "wl-hero-check",
    "wl-search-form", "wl-search", "wl-sort", "wl-visible-count",
  );
  for (const filter of ["all", "attention", "current", "queued"]) {
    assert.match(html, new RegExp(`data-library-filter=["']${filter}["']`));
  }
  assert.match(app, /function libraryVisibleItems\(\)/);
  assert.match(app, /function showLibraryHero\(entry\)/);
  assert.match(app, /getElementById\("wl-search-form"\)\.addEventListener\("submit"/);
  assert.match(app, /entry\.backdrop_url/);
  assert.match(app, /library-card-progress/);
  assert.match(stylesheet, /library\.css\?v=royal-20260805-2/);
  assert.match(html, /style\.css\?v=royal-20260805-6/);
});

test("scheduled episodes stay disabled and hero trailers return to artwork", () => {
  assert.match(html, /is-scheduled[^\n]*Terminiert/);
  assert.match(app, /ep\.unreleased \? `Folge \$\{ep\.episode\}, verfügbar ab/);
  assert.match(app, /completedSeriesHeroTrailers\.add/);
  assert.match(app, /playerState === 0/);
  assert.doesNotMatch(app, /controls=0&loop=1/);
  assert.match(app, /disablekb=1&fs=0&iv_load_policy=3/);
});

test("taste feedback is a compact accessible two-way control", () => {
  assert.match(html, /class="taste-feedback" role="group" aria-label="Serie bewerten"/);
  assert.match(html, /class="btn btn-ghost taste-like"/);
  assert.match(html, /class="btn btn-ghost taste-dislike"/);
  assert.match(app, /like\.querySelector\("\.taste-icon"\)\.textContent = liked \? "♥" : "♡"/);
  assert.match(app, /dislike\.querySelector\("\.taste-icon"\)\.textContent = disliked \? "⊗" : "⊘"/);
});
