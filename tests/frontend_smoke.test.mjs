import { createSeriesEpisodes } from "../web/js/features/media-details/series-episodes.js";
import { queueAddFailureReason } from "../web/js/features/downloads/outcome.js";
import { createHomeCatalog } from "../web/js/features/home/catalog.js";
import { createMoodModel } from "../web/js/features/mood/model.js";
import { MOOD_GENRE_COMPASS } from "../web/js/features/mood/config.js";
import { createRailRenderer } from "../web/js/features/home/rail-renderer.js";
import { carouselWrap } from "../web/js/shared/components/carousel-geometry.js";
import { createHomeData } from "../web/js/features/home/data.js";
import { createCatalogArtwork } from "../web/js/features/discovery/artwork.js";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import "./movie_catalog_refresh.test.mjs";
import { createCalendarState } from "../web/js/features/calendar/state.js";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const transport = readFileSync(new URL("../web/js/core/api.js", import.meta.url), "utf8");
const api = ["shared/utils/artwork-url", "features/downloads/sync", "features/downloads/view", "features/downloads/movies", "features/integrations/catalog-jellyfin"].map(path => readFileSync(new URL(`../web/js/${path}.js`, import.meta.url), "utf8")).join("\n");
const localization = readFileSync(new URL("../web/js/core/localization.js", import.meta.url), "utf8");
const login = readFileSync(new URL("../web/js/features/auth/index.js", import.meta.url), "utf8");
const loader = readFileSync(new URL("../web/js/shared/components/startup-curtain.js", import.meta.url), "utf8");
const mood = ["config", "model", "view", "index"].map(name => readFileSync(new URL(`../web/js/features/mood/${name}.js`, import.meta.url), "utf8")).join("\n");
const homeRows = readFileSync(new URL("../web/js/features/home/rows.js", import.meta.url), "utf8");
const home = readFileSync(new URL("../web/js/features/home/actions.js", import.meta.url), "utf8");
const homeExperience = readFileSync(new URL("../web/js/features/home/hero-selection.js", import.meta.url), "utf8");
const homeRailRuntime = ["features/home/rail-renderer", "shared/components/card-artwork"].map(name => readFileSync(new URL(`../web/js/${name}.js`, import.meta.url), "utf8")).join("\n");
const carousel = readFileSync(new URL("../web/js/shared/components/carousel.js", import.meta.url), "utf8");
const mediaCard = readFileSync(new URL("../web/js/shared/components/media-card.js", import.meta.url), "utf8");
const homeLayoutEditor = ["layout-model", "layout"].map(name => readFileSync(new URL(`../web/js/features/home/${name}.js`, import.meta.url), "utf8")).join("\n");
const seriesPresentation = readFileSync(new URL("../web/js/features/discovery/series-presentation.js", import.meta.url), "utf8");
const seriesScreen = readFileSync(new URL("../web/js/features/discovery/series-actions.js", import.meta.url), "utf8");
const seriesCalendar = ["index", "model", "state", "storage", "view"].map(name => readFileSync(new URL(`../web/js/features/calendar/${name}.js`, import.meta.url), "utf8")).join("\n");
const movieReleases = readFileSync(new URL("../web/js/features/releases/index.js", import.meta.url), "utf8");
import { createDetailHeroScroll } from "../web/js/features/trailers/scroll.js";
import { createJellyfinResume } from "../web/js/features/integrations/resume.js";
const workflow = readFileSync(new URL("../.github/workflows/quality.yml", import.meta.url), "utf8");
const stylesheet = readFileSync(new URL("../web/style.css", import.meta.url), "utf8");
const accountStyles = readFileSync(
  new URL("../web/styles/legacy-account.css", import.meta.url),
  "utf8",
);
const seriesStyles = readFileSync(new URL("../web/styles/series.css", import.meta.url), "utf8");
const appModulePaths = [
  "js/features/settings/providers.js",
  "js/features/integrations/settings.js",
  "js/features/settings/navigation.js", "js/features/settings/directory.js",
  "js/features/settings/updater.js",
  "js/features/search/index.js", "js/features/search/support.js",
  "js/features/search/home.js",
  "js/features/media-details/language.js",
  "js/features/home/daily-top.js", "js/features/home/discovery-policy.js",
  "js/features/home/taste-ranking.js",
  "js/features/home/hero-selection.js",
  "js/features/home/data.js", "js/features/home/cache.js",
  "js/features/discovery/artwork.js",
  "js/shell/actions.js",
  "js/features/subscriptions/model.js",
  "js/features/subscriptions/view.js",
  "js/features/subscriptions/index.js",
  "js/features/downloads/view.js",
  "js/features/downloads/sync.js",
  "js/features/downloads/events.js", "js/features/downloads/movies.js", "js/features/downloads/outcome.js",
  "js/shared/components/media-card.js", "js/shared/components/result-card.js",
  "js/shared/components/status-badge.js",
  "js/core/websocket.js", "js/core/shell.js",
  "js/composition/application.js",
  "js/shared/constants/watch-policy.js",
  "js/composition/core.js",
  "js/composition/discovery.js",
  "js/composition/downloads.js",
  "js/composition/home.js",
  "js/composition/index.js",
  "js/composition/integrations.js",
  "js/composition/profile.js",
  "js/composition/search.js",
  "js/composition/settings.js",
  "js/composition/subscriptions.js",
  "js/features/home/hero.js",
  "js/features/home/rows.js",
  "js/features/home/card-dock.js",
  "js/features/home/rail-renderer.js", "js/shared/components/card-artwork.js",
  "js/features/home/actions.js",
  "js/features/home/catalog.js", "js/features/home/cards.js",
  "js/features/home/lanes.js",
  "js/features/home/presenter.js", "js/features/collections/index.js",
  "js/features/home/index.js",
  "js/features/profile/taste.js",
  "js/features/home/layout.js", "js/features/home/layout-model.js",
  "js/features/mood/config.js", "js/features/mood/model.js", "js/features/mood/view.js", "js/features/mood/index.js",
  "js/features/trailers/index.js",
  "js/features/discovery/catalog-seed.js",
  "js/features/discovery/movie-browse.js",
  "js/features/discovery/series-browse.js",
  "js/features/discovery/catalog-refresh.js",
  "js/features/discovery/catalog-metadata.js",
  "js/features/trailers/scroll.js",
  "js/features/downloads/actions.js",
  "js/features/media-details/discovery.js",
  "js/features/discovery/movie-actions.js", "js/features/discovery/movie-presentation.js",
  "js/features/discovery/movie-filters.js",
  "js/features/media-details/movie-loader.js",
  "js/features/media-details/series-loader.js",
  "js/features/media-details/series-status.js", "js/features/integrations/movie-status.js",
  "js/features/media-details/series-checks.js", "js/features/media-details/series-episodes.js",
  "js/features/media-details/series-api.js",
  "js/features/discovery/series-actions.js", "js/features/discovery/series-presentation.js",
  "js/features/calendar/index.js",
  "js/features/calendar/view.js",
  "js/features/discovery/anime-actions.js",
  "js/features/discovery/anime.js",
  "js/features/subscriptions/actions.js",
  "js/features/settings/actions.js",
  "js/features/settings/index.js",
  "js/features/settings/deployment.js",
  "js/features/integrations/jellyfin.js",
  "js/features/integrations/catalog-jellyfin.js",
  "js/features/integrations/jellyfin-users.js",
  "js/core/startup.js",
  "js/features/discovery/genres.js",
  "js/features/setup/index.js",
  "js/features/setup/copy.js",
  "js/shared/components/infinite-scroll.js",
  "js/features/integrations/resume.js",
  "app.js",
];
const app = appModulePaths
  .map((path) => readFileSync(new URL(`../web/${path}`, import.meta.url), "utf8"))
  .join("\n");
const frontend = `${login}\n${app}`;

test("episode selection requires an enabled stream language", () => {
  const state = {
    series: {
      current: { provider: "serienstream", enabled_content_languages: ["de"] },
    },
    queuedSlugs: new Set(),
    providers: { contentLanguages: new Set(["de"]) },
  };
  const episodes = createSeriesEpisodes({}, { seriesState: state.series, getQueuedSlugs: () => state.queuedSlugs,
    getEnabledLanguages: () => state.providers.contentLanguages });
  const context = vm.createContext({ state, sharedPresentation: { seriesEpisodes: episodes, seriesState: state.series } });
  Object.assign(context, episodes);
  const selectable = (episode) => vm.runInContext(
    `isEpisodeSelectable(${JSON.stringify(episode)})`, context,
  );
  const actionable = (episode) => vm.runInContext(
    `isEpisodeActionable(${JSON.stringify(episode)})`, context,
  );

  assert.equal(selectable({ slug: "e15", content_languages: ["de", "en"] }), true);
  assert.equal(selectable({ slug: "e17", content_languages: ["en"] }), false);
  assert.equal(actionable({ slug: "e17", content_languages: ["en"] }), false);
  assert.equal(vm.runInContext(
    'episodeLanguageLockLabel({ slug: "e17", content_languages: ["en"] })', context,
  ), "NUR EN");
  state.series.current = { provider: "huhu", enabled_content_languages: ["de"] };
  assert.equal(selectable({ slug: "huhu17" }), false);
  assert.equal(actionable({ slug: "huhu17" }), true);
  assert.equal(selectable({
    slug: "huhu15", huhu_language_checked: true, huhu_language_available: true,
  }), true);
  assert.equal(selectable({
    slug: "huhu17", huhu_language_checked: true, huhu_language_available: false,
  }), false);
  assert.equal(actionable({
    slug: "huhu17", huhu_language_checked: true, huhu_language_available: false,
  }), false);
  assert.equal(vm.runInContext(
    'episodeLanguageLockLabel({ slug: "huhu17", huhu_language_checked: true, huhu_language_available: false, content_languages: ["en"] })', context,
  ), "NUR EN");
});

test("home rails use carousel controls only, without a meaningless show-all action", () => {
  assert.doesNotMatch(html, /data-home-show-all/);
  assert.doesNotMatch(homeLayoutEditor, /data-home-show-all/);
  assert.doesNotMatch(homeLayoutEditor, /home-rail\\.is-expanded/);
});

test("release calendar routes movies and series and unlocks past dates", () => {
  assert.match(movieReleases, /entry\.media_type === "series"/);
  assert.match(movieReleases, /openMedia\(entry\.media_type, match\)/);
  assert.match(app, /coreDomain\.actions\.switchTab\("serien"\); discoveryDomain\.seriesActions\.loadSeries\(match\)/);
  assert.match(movieReleases, /period === "past"/);
  assert.match(movieReleases, /e\.has_started/);
});

test("royal startup loader is branded, accessible, and wired to every exit path", () => {
  assert.match(html, /id="royal-loader"[^>]+role="status"[^>]+aria-label="Royal Downloader wird geladen"/);
  assert.match(html, /class="royal-loader-crown"/);
  assert.doesNotMatch(html, /<script(?![^>]*type="module")/);
  assert.match(loader, /prefers-reduced-motion: reduce/);
  assert.match(loader, /scope\.dispose\(\)/);
  assert.match(app, /startupCurtain\.finish\(\)/);
  assert.match(login, /finishLoading\(\)/);
});

test("series calendar always leaves loading and restores a validated snapshot", () => {
  assert.match(seriesCalendar, /SERIES_CALENDAR_CACHE_MAX_AGE/);
  assert.match(seriesCalendar, /restoreSnapshot\(\)/);
  assert.match(seriesCalendar, /storeSnapshot\(payload\)/);
  assert.match(seriesCalendar, /SERIES_CALENDAR_WATCHDOG_MS = 16_000/);
  assert.match(seriesCalendar, /Aktualisierung fehlgeschlagen/);
  assert.doesNotMatch(seriesCalendar, /https:\/\/serienstream\.to\/api\/calendar/);
  assert.doesNotMatch(html, /Sendeplan wird geladen/);
  assert.doesNotMatch(html, /screens\/series-calendar\.js/);
  assert.doesNotMatch(seriesCalendar, /setInterval|window\.__royalCalendarSafetyTimer/);
  assert.match(stylesheet, /series-calendar\.css\?v=royal-20260912-1/);
  assert.match(html, /style\.css\?v=royal-20260921-3/);
  const calendarStyles = readFileSync(
    new URL("../web/styles/series-calendar.css", import.meta.url),
    "utf8",
  );
  assert.match(calendarStyles, /\.calendar-status\[hidden\][\s\S]*display: none !important/);
  assert.match(calendarStyles, /\.calendar-days\[hidden\][\s\S]*display: none !important/);
  const calendarOpenEntry = seriesCalendar.split("function calendarOpenEntry", 2)[1]
    .split("function initSeriesCalendar", 1)[0];
  assert.match(calendarOpenEntry, /loadSeries\(\{/);
  assert.doesNotMatch(calendarOpenEntry, /switchTab\(/);
});

const emptyCalendarCache = { restoreSnapshot: () => null, storeSnapshot() {} };

test("series calendar terminates failed initial requests with a visible error state", async () => {
  const model = createCalendarState({ cache: emptyCalendarCache, client: { get: async () => { throw new Error("offline"); } } });
  assert.equal(await model.refresh(), false);
  assert.equal(model.get().loading, false);
  assert.equal(model.get().phase, "error");
  assert.equal(model.get().error, "offline");
  model.unmount();
});

test("series calendar deadline settles and aborts a request that never responds", async () => {
  let signal;
  const model = createCalendarState({ cache: emptyCalendarCache, deadlineMs: 5,
    client: { get: (_path, options) => { signal = options.signal; return new Promise(() => {}); } },
  });
  assert.equal(await model.refresh(), false);
  assert.equal(model.get().loading, false);
  assert.equal(model.get().phase, "error");
  assert.match(model.get().error, /Zeitlimit überschritten/);
  assert.equal(signal.aborted, true);
  model.unmount();
});

function requiresIds(...ids) {
  for (const id of ids) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
    const detailCard = id.match(/^(?:fp|series)-detail-((?:similar|extras)(?:-section)?)$/);
    if (detailCard) {
      assert.ok(frontend.includes('byId(`${prefix}-' + detailCard[1] + '`)'));
      continue;
    }
    assert.match(frontend, new RegExp(`(?:(?:getElementById|find|byId|listen)\\(["']${id}["'](?:\\)|,)|querySelector\\(["']#${id}["']\\))`));
  }
}

test("login flow keeps its browser and API contract", () => {
  requiresIds("login-screen", "login-form", "login-username", "login-password", "login-submit");
  assert.match(login, /client.get\("\/api\/auth\/status"/);
  assert.match(login, /client.post\("\/api\/auth\/login", \{ username, password \}/);
});

test("detail, queue, and settings screens remain wired", () => {
  requiresIds("fp-detail-modal", "fp-detail-title", "fp-detail-add");
  requiresIds(
    "fp-detail-similar-section", "fp-detail-similar", "fp-detail-extras-section",
    "fp-detail-extras",
  );
  assert.match(html, /id=["']fp-detail-about-title["']/);
  assert.match(html, /id=["']fp-detail-about-cast["']/);
  assert.match(app, /function renderFpAbout\(movie\)/);
  assert.match(app, /function renderSimilarTitles\(titles\)/);
  assert.match(app, /function renderExtras\(movie\)/);
  assert.match(app, /selectFpRow\(slug, \{/);
  assert.ok(
    html.indexOf('class="detail-queue-note"')
      < html.indexOf('id="fp-detail-similar-section"'),
    "Filmempfehlungen müssen am Ende der Detailansicht stehen",
  );
  requiresIds(
    "series-detail-similar-section", "series-detail-similar",
    "series-detail-extras-section", "series-detail-extras",
    "series-detail-about-section",
  );
  assert.match(html, /id=["']series-detail-about-title["']/);
  assert.ok(
    html.indexOf('id="series-episodes-title"')
      < html.indexOf('id="series-detail-similar-section"'),
    "Serienepisoden müssen vor ähnlichen Titeln stehen",
  );
  assert.match(
    seriesStyles,
    /\.series-detail-lower-grid > \.detail-extras,[\s\S]*?\.series-detail-lower-grid > \.series-detail-about \{[\s\S]*?grid-area: auto;/,
    "Trailer und Serieninformationen dürfen keine geerbten Grid-Flächen überlagern",
  );
  assert.match(app, /function render\(media\) \{ renderSimilarTitles\(media\.similar_titles\); renderExtras\(media\); renderAbout\(media\); \}/);
  assert.match(app, /SERIENAKTE ÖFFNEN →/);
  requiresIds("queue-drawer", "queue-list", "queue-count");
  requiresIds("settings-btn");
  assert.match(html, /id=["']settings-overview["']/);
  assert.match(html, /id=["']settings-general["']/);
  assert.match(html, /id=["']settings-system["']/);
  assert.match(app, /data-settings-target/);
  assert.match(html, /data-settings-open=["']settings-media["']/);
  assert.match(app, /section\.hidden = !active/);
  assert.match(app, /panel\.classList\.toggle\("is-overview"/);
  assert.match(api, /client.get\("\/api\/queue", \{ signal \}\)/);
  assert.match(api, /client.post\("\/api\/queue\/add"/);
  assert.match(app, /client.get\("\/api\/config"/);
});

test("setup and settings expose only desktop and NAS deployment modes", () => {
  for (const id of [
    "setup-mode-desktop",
    "setup-mode-nas",
    "deployment-mode-desktop",
    "deployment-mode-nas",
    "deployment-mode-status",
  ]) assert.match(html, new RegExp(`id=["']${id}["']`));
  assert.match(html, /Normaler Computer/);
  assert.match(html, /NAS \/ Heimserver/);
  assert.doesNotMatch(html, /setup-mode-demo|deployment-mode-demo|Demo-Modus/);
  assert.doesNotMatch(app, /=== "demo"|Demo-Modus/);
  assert.match(app, /deployment_mode: selectedDeploymentMode\(root, "setup-deployment-mode"\)/);
  assert.match(app, /deployment_mode: selectedDeploymentMode\(root\)/);
});

test("fresh setup starts in English and prioritizes live setup translation", () => {
  assert.match(html, /<option value="en" translate="no" selected>English<\/option>/);
  assert.match(app, /defaults\.ui_language_configured\s*\? defaults\.ui_language\s*:\s*"en"/);
  assert.match(app, /changeSetupLanguage\(event\.target\.value, true\)/);
  assert.match(app, /#setup-wizard \.setup-stage-head/);
  assert.match(localization, /priorityRoot = null/);
  assert.match(localization, /translateTexts/);
  assert.match(localization, /LANGUAGE_STORAGE_KEY = "royal\.ui\.language"/);
  assert.match(localization, /primeStoredInterface/);
  assert.match(localization, /persistTranslationCache/);
  for (const label of ["Übersicht", "Betrieb", "Speicher", "Automatik", "Zugang"]) {
    assert.match(localization, new RegExp(`"${label}":`));
  }
  assert.doesNotMatch(localization, /await changeLanguage\(language\)/);
  assert.match(localization, /changeLanguage\(language\)\.catch/);
  assert.match(app, /userInitiated: true, persist: true/);
  assert.doesNotMatch(html, /src="\/i18n\.js/);
  assert.match(app, /createLocalization\(document\)/);
  assert.match(app, /createSetup\(document.getElementById\("setup-wizard"\)/);
  assert.match(html, /id="setup-tmdb-key"[^>]+required[^>]+aria-required="true"/);
  assert.match(app, /TMDB ist erforderlich/);
});

test("movie and series catalogs lazy-load for mobile document scrolling", () => {
  for (const id of ["tab-filme", "fp-infinite", "tab-serien", "series-infinite"]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(app, /scope\.listen\(win, "scroll", refresh, \{ passive: true \}\)/);
  assert.match(app, /sentinel\.getBoundingClientRect\(\)\.top/);
  assert.match(app, /if \(!scope\?\.active \|\| scheduled\) return/);
  assert.match(app, /createInfiniteScroll\(document.getElementById\("tab-filme"\)/);
  assert.match(app, /createInfiniteScroll\(document.getElementById\("tab-serien"\)/);
  assert.match(html, /app\.js\?v=royal-20260921-1/);
});

test("searches run only after an explicit submit", () => {
  assert.match(app, /scope\.listen\(byId\("home-search"\), "input",/);
  assert.match(app, /scope\.listen\(toggle, "click", openGlobalSearch\)/);
  assert.match(app, /scope\.listen\(input, "input", syncGlobalSearchDraft\)/);
  assert.match(app, /if \(event\.key === "Enter"\) \{[\s\S]*?runGlobalSearch\(\)/);
  assert.match(app, /scope\.listen\(byId\("fp-search"\), "input", \(\) => \{\s*syncSearchClearButtons\(\);\s*closeSearchSuggestions\("fp-search-suggestions", "fp-search"\);/);
  assert.match(app, /scope\.listen\(byId\("series-search"\), "input", \(\) => \{\s*syncSearchClearButtons\(\);\s*closeSearchSuggestions\("series-search-suggestions", "series-search"\);/);
  assert.match(app, /view\.listen\(byId\("anime-search"\), "keydown", \(event\) => \{\s*if \(event\.key !== "Enter"\) return;/);
  assert.doesNotMatch(app, /queueGlobalSearch/);
  assert.doesNotMatch(app, /debounceTimer/);
  assert.doesNotMatch(app, /addEventListener\("focus", \(\) => \{\s*renderSearchSuggestions/);
  assert.doesNotMatch(app, /value\.trim\(\)\) homeSearch\(\)/);
  assert.match(app, /scope\.listen\(page, "click", \(event\) => \{/);
  assert.match(app, /if \(event\.target\.closest\("\.global-search-head, \.home-card"\)\) return;/);
});

test("global search covers every catalog and exposes Jellyfin filters", () => {
  requiresIds("global-search-input", "global-search-page", "global-search-jellyfin");
  for (const scope of ["all", "movie", "series", "anime"]) {
    assert.match(html, new RegExp(`data-global-search-scope=["']${scope}["']`));
  }
  assert.match(app, /client\.get\(`\/api\/anime\?/);
  assert.match(app, /function refreshCatalogJellyfinStatus\(entries, render, \{ signal \} = \{\}\)/);
  assert.match(app, /media_type: kind === "movie" \? "movie" : "series"/);
  assert.match(app, /setFpJellyfinBadge\(jellyfin, mediaJellyfinStatus\(result\)\)/);
  assert.match(app, /getAnime\(\)\.get\(\)\.results\.map\(homeAnimeEntry\)/);
  assert.match(app, /for \(let index = 0; index < requests\.length; index \+= 100\)/);
  assert.match(app, /batches\.map\(\(batch\) => client\.post\("\/api\/jellyfin\/matches"/);
  assert.match(app, /\[401, 403\]\.includes\(Number\(result\.reason\?\.status\)\)/);
  assert.match(app, /Jellyfin-Statusanfrage blockiert/);
});

test("movie detail refreshes stale Jellyfin state for Home selections", () => {
  assert.match(app, /features\/discovery\/movie-actions\.js/);
  assert.match(app, /const selectedHomeMovie = homeMovieBySlug\((?:movieState|getMovieState\(\))\.selectedSlug\)/);
  assert.match(app, /function applyMovieJellyfinStatus\(slug, status, owned = null\)/);
  assert.match(app, /statuses\.set\(`movie:\$\{slug\}`, status\)/);
  assert.match(app, /\|\| homeMovieBySlug\((?:movieState|getMovieState\(\))\.selectedSlug\)/);
  assert.match(app, /function beginCatalogJellyfinRequest\(keys\)/);
  assert.match(app, /const fpJellyfinPending = new Map\(\)/);
  assert.match(app, /await refreshCatalogJellyfinStatus\(targets\.map\(homeMovieEntry\), null, \{ signal: owner\.signal \}\)/);
  assert.match(app, /HOME_CACHE_KEY = "royal-home-cache-v5"/);
  assert.match(app, /known\.catalog_identity_version !== 2/);
});

test("standby refreshes Jellyfin once and removes idle listeners on session end", async t => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  let now = 1_000;
  const calls = [], window = new EventTarget(), document = Object.assign(new EventTarget(), { hidden: false });
  const service = createJellyfinResume({ window, document, now: () => now,
    refreshAllCatalogJellyfinStatuses() { calls.push("catalog"); },
    refreshFpJellyfinStatus() { calls.push("movies"); },
    refreshSeriesJellyfinStatus(force) { calls.push(force ? "series-force" : "series"); },
  });
  service.mount(); service.mount(); window.dispatchEvent(new Event("blur"));
  now += 3_600_001; window.dispatchEvent(new Event("focus"));
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(calls.sort(), ["catalog", "movies", "series-force"]);
  window.dispatchEvent(new Event("online")); await Promise.resolve(); assert.equal(calls.length, 3);
  service.unmount(); now += 3_600_001; window.dispatchEvent(new Event("focus"));
  t.mock.timers.tick(60000); await Promise.resolve(); assert.equal(calls.length, 3);
});

test("deep movie pagination hydrates only the newly appended page", () => {
  assert.match(app, /const metadataItems = fpMetadataPreloadItems\(incoming\)/);
  assert.match(app, /!metadata\?\.cover_url/);
  assert.match(app, /tmdb_id: result\.tmdb_id \|\| movieState\.metadataCache/);
  assert.match(app, /attempt < maxAttempts && unresolved\.size/);
  assert.match(app, /preloadTmdbMetadata\((?:movieState|getMovieState\(\))\.metadataRequestSeq, metadataItems\)/);
  assert.match(app, /refreshFpJellyfinStatus\(incoming\)/);
  assert.match(app, /refreshedSlugs\.has\(item\.slug\)/);
  assert.doesNotMatch(app, /let fpJellyfinRequestSeq/);
  assert.match(app, /requestId !== (?:movieState|getMovieState\(\))\.metadataRequestSeq/);
  assert.doesNotMatch(app, /const items = (?:movieState|getMovieState\(\))\.results\s*\.filter\(\(r\) => !(?:movieState|getMovieState\(\))\.metadataCache/);
});

test("movie shelf posters use bounded thumbnail payloads", () => {
  assert.match(api, /coverThumbnailCandidates\(url\)/);
  assert.match(api, /"\/t\/p\/w500\/"/);
  assert.match(app, /coverCandidates\(media\?\.cover_url\)/);
  assert.doesNotMatch(html, /src="\/api\.js/);
});

test("movie queue updates keep poster DOM stable and lock repeated clicks", () => {
  const queueRefreshStart = app.indexOf("function refreshQueueUiAfterChange(resp)");
  const queueRefreshEnd = app.indexOf("function ", queueRefreshStart + 10);
  const queueRefresh = app.slice(queueRefreshStart, queueRefreshEnd);
  assert.match(queueRefresh, /refreshFpQueuePresentation\(\)/);
  assert.doesNotMatch(queueRefresh, /renderFpResults\(\)/);
  assert.match(app, /pending = new Set\(\)/);
  assert.match(app, /if \(!scope\.active \|\| pending\.has\(slug\)\) return/);
  assert.match(app, /pending\.add\(slug\)/);
  assert.match(app, /pending\.delete\(slug\)/);
  assert.doesNotMatch(app, /oldVisual\?\.replaceWith\(createResultCardVisual/);
  assert.match(app, /syncResultCardPoster\(visual, media\)/);
  assert.doesNotMatch(app, /waitsForTmdb/);
  assert.match(app, /await image\.decode\(\)/);
  assert.match(app, /image\.classList\.add\("is-pending-poster"\)/);
  assert.match(app, /job\.listen\(image, "transitionend", removePreviousPoster/);
  assert.match(app, /const preserveRenderedCards = !append/);
  assert.match(app, /if \(preserveRenderedCards\)/);
});

test("home series rail falls back when the trending provider is unavailable", () => {
  assert.doesNotMatch(html, /src="\/api\.js/);
  assert.match(app, /features\/home\/actions\.js/);
  assert.match(app, /function homePopularSeriesEntries\(\)/);
  assert.match(app, /getData\(\)\.newSeries\.map\(homeSeriesEntry\)/);
  assert.match(app, /getData\(\)\.discoverySeries\.map\(homeSeriesEntry\)/);
  assert.match(app, /Serien aus deinen aktiven Quellen/);
});

test("movie and series catalogs show cached content immediately and refresh in the background", () => {
  assert.match(app, /syncFpCatalogFromHome\(\)/);
  assert.match(app, /syncSeriesCatalogFromHome\(\)/);
  assert.match(app, /refreshFpCatalogInBackground\(\)/);
  assert.match(app, /refreshSeriesCatalogInBackground\(\)/);
  assert.match(app, /getCardArtwork\(\).set\(image, coverCandidates.map/);
  assert.match(app, /preload = 1200/);
  assert.match(app, /const FP_METADATA_BATCH_SIZE = 12/);
  assert.match(app, /client\.post\("\/api\/tmdb\/movies",[\s\S]*?background: true/);
  assert.match(app, /scheduleResultPoster\(image, coverCandidates\)/);
  assert.doesNotMatch(app, /await prepareFpCatalogPage\(data\)/);
  assert.match(app, /applyFpResults\(data, \{ append: true \}\)/);
  assert.doesNotMatch(app, /void preloadFpPosterImages\(data\.results \|\| \[\], 2000\)/);
  assert.match(app, /append && data\.page_complete === false/);
  assert.doesNotMatch(app, /await prepareSeriesCatalogPage\(data\)/);
  assert.match(app, /applySeriesResults\(data, \{ append \}\)/);
  assert.match(app, /void preloadSeriesPosterImages\(data\.results \|\| \[\], 2000, scope\.signal\)/);
  assert.match(app, /await preloadSeriesPosterImages\(data\.results \|\| \[\], 6000, owner\.signal\)/);
  assert.match(app, /applySeriesResults\(data, \{ backgroundRefresh: true \}\)/);
  assert.match(app, /function updateSeriesResultCard\(baseSlug\)/);
  assert.match(app, /syncResultCardPoster\(visual, result\)/);
  assert.doesNotMatch(app, /updateSeriesResultArtwork/);
  assert.match(app, /for \(const result of (?:seriesState|getSeriesState\(\))\.results\) updateSeriesResultCard\(result\.base_slug\)/);
  const seriesRenderer = seriesPresentation.split("function renderSeriesResults")[1].split(
    "function findSeriesResultCard",
  )[0];
  assert.match(seriesPresentation, /function createSeriesResultRow\(result, \{ suppressEntryAnimation = false \} = \{\}\)/);
  assert.match(seriesPresentation, /function updateSeriesFeatureArtwork\(featureArt, artwork\)/);
  assert.match(seriesPresentation, /featureArt\.dataset\.artworkRequest/);
  assert.match(seriesRenderer, /const existingRows = new Map/);
  assert.match(seriesRenderer, /container\.insertBefore\(row, insertionPoint\)/);
  assert.match(seriesRenderer, /row\.style\.animation = "none"/);
  assert.doesNotMatch(seriesRenderer, /container\.replaceChildren\(fragment\)/);
  assert.doesNotMatch(seriesRenderer, /container\.innerHTML = ""/);
  assert.match(transport, /const pending = new Map\(\)/);
  assert.match(api, /15_000/);
  assert.match(app, /Filmkatalog antwortet zu langsam/);
});

test("movie catalog combines practical filters without rebuilding stable cards", () => {
  for (const id of [
    "movie-filter-genre", "movie-filter-period", "movie-filter-rating",
    "movie-filter-availability", "movie-filter-language", "movie-filter-sort",
    "movie-filter-reset", "movie-filter-chips",
  ]) assert.match(html, new RegExp(`id=["']${id}["']`));
  assert.match(app, /function fpSmartFilterMatches\(result\)/);
  assert.match(app, /function applyFpSmartFilters\(\)/);
  assert.match(app, /mediaContentLanguages\(media\)\.has\(filters\.language\)/);
  assert.match(app, /row\.hidden = !shown/);
  assert.match(app, /row\.style\.order/);
  assert.match(app, /function resetFpSmartFilters\(\)/);
});

test("movie details keep catalog artwork while full metadata loads directly", () => {
  assert.match(app, /cover_url: item\.cover_url \|\| ""/);
  assert.match(app, /backdrop_url: item\.backdrop_url \|\| ""/);
  assert.match(app, /if \(!metadata\?\.details_loaded\)/);
  assert.match(app, /const detailResponse = await client\.post\("\/api\/tmdb\/movie"/);
  assert.match(app, /setFpDetailAvailability\("Metadaten nicht verfügbar", "error"\)/);
});

test("Top 10 rotates daily instead of weekly", () => {
  assert.match(html, /Heute neu/);
  assert.match(html, /Top 10 des Tages/);
  assert.match(app, /DAILY_TOP_STORAGE_KEY = "royal-home-daily-top-v3"/);
  assert.match(app, /function reconcileSnapshot/);
  assert.match(app, /stored.period === period/);
  assert.match(app, /Same-day ranks are immutable/);
  assert.doesNotMatch(home, /weekly|WeekKey|WEEKLY/i);
});

test("changing the updater channel persists immediately", () => {
  assert.match(app, /scope\.listen\(byId\("updater-channel"\), "change", async/);
  assert.match(app, /const saved = await client\.post\("\/api\/updater\/config", \{/);
  assert.match(app, /update_channel: selected/);
  assert.match(app, /applyUpdaterConfig\(saved\)/);
  assert.match(app, /await checkForUpdates\(true\)/);
});

test("an updater restart reloads only after the exact target revision is active", () => {
  assert.match(app, /waitForUpdatedServer\(installer\.target_sha/);
  assert.match(app, /\/api\/updater\/status\?force=true/);
  assert.match(app, /installed === normalizedTarget/);
  assert.match(app, /Neustart fehlgeschlagen/);
  assert.doesNotMatch(app, /fetch\("\/api\/health"/);
});

test("Top 10 merges provider-tagged duplicates before all metadata is hydrated", () => {
  const context = vm.createContext({
    state: {
      fp: {
        metadataCache: {
          "spider-man": { title: "Spider-Man: Brand New Day", year: 2026, tmdb_id: 1265609 },
        },
      },
    },
  });
  const catalog = createHomeCatalog({ getMovieMetadata: () => context.state.fp.metadataCache });
  context.entries = [
    { kind: "movie", item: { slug: "spider-man", title: "Spider-Man: Brand New Day", year: 2026 } },
    { kind: "movie", item: { slug: "spider-man-sflix", title: "Spider-Man: Brand New Day [SFlix]", year: 2026 } },
  ];
  const result = catalog.uniqueHomeContentEntries(context.entries);
  assert.equal(result.length, 1);
});

test("home cards and hero fall back to available posters when wallpapers are missing", () => {
  assert.match(mediaCard, /\{ url: media\.backdrop_url, posterFallback: false \}, \{ url: media\.cover_url, posterFallback: true \}/);
  assert.match(homeRailRuntime, /image\.classList\.toggle\("is-poster-fallback", candidate\.posterFallback\)/);
  assert.match(home, /getHeroSelection\(\)\.candidates\(\)/);
  assert.match(homeExperience, /const artwork = media\.backdrop_url \|\| media\.cover_url \|\| ""/);
  assert.match(homeRailRuntime, /media\.backdrop_url \|\| media\.cover_url \|\| ""/);
});

test("series wallpaper hydration updates every duplicate catalog object", async () => {
  const trending = { base_slug: "same-series", title: "Same Series", cover_url: "/poster.jpg", genres: [] };
  const discovery = { base_slug: "same-series", title: "Same Series", cover_url: "/poster.jpg", genres: [] };
  const artwork = createCatalogArtwork({
    client: {
      post: async () => ({
        series: {
          "same-series": {
            backdrop_url: "/wallpaper.jpg",
            genres: ["Drama"],
          },
        },
      }),
    },
    renderHome: () => {},
    saveHomeCache: () => {},
  });
  await artwork.series([trending, discovery], { render: false });
  assert.equal(trending.backdrop_url, "/wallpaper.jpg");
  assert.equal(discovery.backdrop_url, "/wallpaper.jpg");
  assert.deepEqual(trending.genres, ["Drama"]);
  assert.deepEqual(discovery.genres, ["Drama"]);
});

test("series wallpapers paint progressively and retry only server-reported pending titles", async () => {
  const calls = [];
  let renders = 0;
  let cacheWrites = 0;
  const artwork = createCatalogArtwork({
    client: {
      post: async (_url, { items }) => {
        calls.push(items.map((item) => item.base_slug));
        const resolved = calls.length === 1 ? items.slice(0, 7) : items;
        return {
          series: Object.fromEntries(resolved.map((item) => [item.base_slug, {
            backdrop_url: `/wallpaper/${item.base_slug}.jpg`,
          }])),
          pending: calls.length === 1 ? [items[7].base_slug] : [],
        };
      },
    },
    renderHome: () => { renders += 1; },
    saveHomeCache: () => { cacheWrites += 1; },
  });
  const items = Array.from({ length: 10 }, (_, index) => ({
    base_slug: `series-${index}`,
    title: `Series ${index}`,
    cover_url: "/poster.jpg",
    backdrop_url: "",
    genres: ["Drama"],
  }));

  const hydrated = await artwork.series(items);

  assert.deepEqual(calls.map((batch) => batch.length), [8, 1, 2]);
  assert.equal(renders, 3);
  assert.equal(cacheWrites, 3);
  assert.equal(hydrated.length, 10);
  assert.ok(items.every((item) => item.backdrop_url));
});

test("home load waits for movie Jellyfin truth but never blocks on series Jellyfin", async () => {
  let releaseMovie;
  let releaseSeries;
  const movieStatus = new Promise((resolve) => { releaseMovie = resolve; });
  const seriesStatus = new Promise((resolve) => { releaseSeries = resolve; });
  const calls = [];
  const model = createHomeData({
    storage: null, getMovieMetadata: () => ({}), isRendered: () => false,
    client: { get: async url => ({ results: url.startsWith("/api/movies")
      ? [{ slug: "movie", title: "Movie" }] : [{ base_slug: "series", title: "Series" }] }) },
    homeAllEntries: () => [
      { kind: "movie", item: { slug: "movie", title: "Movie" } },
      { kind: "series", item: { base_slug: "series", title: "Series" } },
    ],
    homeArtworkEntriesInLayout: () => [
      { kind: "movie", item: { slug: "movie", title: "Movie" } },
      { kind: "series", item: { base_slug: "series", title: "Series" } },
    ],
    renderHome: () => { calls.push("render"); },
    syncFpCatalogFromHome: () => {},
    syncSeriesCatalogFromHome: () => {},
    hydrateHomeMovieArtwork: async () => {},
    hydrateHomeSeriesArtwork: async () => { calls.push("series-artwork"); },
    refreshCatalogJellyfinStatus: (entries, render) => {
      const kind = entries[0]?.kind;
      calls.push(`jellyfin-${kind}`);
      if (kind === "movie") return movieStatus;
      return seriesStatus.then(() => render?.());
    },
  });

  let completed = false;
  const load = model.load().then(() => { completed = true; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(calls.includes("series-artwork"));
  assert.ok(calls.includes("jellyfin-movie"));
  assert.equal(completed, false);

  releaseMovie();
  await load;
  assert.equal(completed, true);
  assert.equal(model.get().loading, false);
  assert.equal(calls.filter((call) => call === "render").length, 2);
  assert.ok(calls.includes("jellyfin-series"));
  releaseSeries();
  model.unmount();
});

test("home discovery is larger, shuffleable, and avoids repetitive rails", () => {
  assert.match(html, /id=["']home-program-title["']/);
  requiresIds("home-program-note", "home-discovery-shuffle");
  assert.match(app, /function homeDiscoveryLanes\(\)/);
  assert.match(app, /function takeDistinctHomeLane\(entries, seen, limit, minimum = 4\)/);
  assert.match(app, /genre: takeDistinctHomeLane\(homeGenreEntries\(\), seen, 16, 16\)/);
  assert.match(app, /fresh: homeNewEntries\(\)/);
  assert.match(app, /function shuffleHomeDiscovery\(\)/);
  assert.match(app, /layout === "spotlight"/);
  assert.match(stylesheet, /catalog\.css\?v=royal-20260830-1/);
  assert.match(app, /addBtn\.hidden = owned && !queued/);
});

test("home programme planner controls visibility, order, and fast artwork", () => {
  requiresIds(
    "home-layout-open", "home-layout-modal", "home-layout-list", "home-layout-hero",
    "home-layout-reset", "home-layout-cancel", "home-layout-save", "home-layout-status",
  );
  assert.match(homeLayoutEditor, /const HOME_RAIL_CATALOG = \[/);
  for (const rail of ["new_movies", "new_series", "high_rated", "movies", "library"]) {
    assert.match(homeLayoutEditor, new RegExp(`id: ["']${rail}["']`));
  }
  assert.match(homeLayoutEditor, /event\.dataTransfer\.setData\("text\/plain", railId\)/);
  assert.match(homeLayoutEditor, /client\.put\("\/api\/home\/layout", currentHomeLayout\(\), \{ signal: active\.signal \}\)/);
  assert.doesNotMatch(html, /src="\/home_rail_runtime\.js/);
  assert.match(homeLayoutEditor, /section\.style\.order = String\(index\)/);
  assert.doesNotMatch(stylesheet, /\.home-rail-spotlight \{ order:/);
  assert.match(mediaCard, /setArtwork\(image, artworkCandidates\)/);
  assert.match(app, /setArtwork: setHomeCardArtworkCandidates/);
  assert.match(homeRailRuntime, /new window\.IntersectionObserver/);
  assert.match(homeRailRuntime, /startHomeCardArtwork\(image, visible \? "high" : "auto"\)/);
  assert.match(homeRows, /cycle === 1 && index < eagerCount/);
  assert.doesNotMatch(home, /image\.src = candidate\.url/);
  assert.match(mediaCard, /image\.fetchPriority = eager \? "high" : "auto"/);
  assert.match(mediaCard, /posterFallback: true/);
  assert.match(stylesheet, /home-layout-editor\.css\?v=royal-20260830-1/);
});

test("home carousels loop naturally without duplicating the spotlight grid", () => {
  assert.match(homeRailRuntime, /loop && logicalCount > 1/);
  assert.match(homeRows, /\{ loop: layout !== "spotlight" && !ranked \}/);
  assert.match(carousel, /HOME_RAIL_SCROLL_STEP_RATIO = 0\.68/);
  assert.match(carousel, /HOME_RAIL_WHEEL_FACTOR = 0\.78/);
  assert.match(carousel, /behavior: reducedMotion \? "auto" : "smooth"/);
  const pointerMovement = carousel.slice(carousel.indexOf('scope.listen(home, "pointermove"'), carousel.indexOf("const endTouch"));
  assert.doesNotMatch(pointerMovement, /scrollLeft\s*=|scrollTo|preventDefault/);
  assert.match(carousel, /normalizeHomeRailLoop\(track/);


  const animationFrames = [];
  const track = {
    id: "home-test-track", scrollLeft: 640, clientWidth: 600,
    get scrollWidth() { return this.children.length * 200; },
    children: [], classList: { toggle() {} },
    replaceChildren() { this.replaceCount = (this.replaceCount || 0) + 1; this.children = []; this.scrollLeft = 0; },
    appendChild(child) { this.insertBefore(child, null); },
    insertBefore(child, before) {
      child.remove?.(); child.parentElement = this;
      this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, child);
    },
    scrollTo(options) { this.requestedScrollLeft = options.left; },
  };
  const context = vm.createContext({
    state: { home: { loading: false, railScrollPositions: {}, railScrollTargets: {} } },
    sharedPresentation: { catalogJellyfin: { getStatus: () => undefined } },
    document: { getElementById: () => track, querySelectorAll: () => [] },
    requestAnimationFrame: (callback) => animationFrames.push(callback),
    clearTimeout: () => {},
    window: { setTimeout: () => 1 },
    updateHomeRailNavigation: () => {},
    carouselWrap,
    createHomeCard: (entry) => ({ ...entry, dataset: {}, querySelector: () => null,
      get offsetLeft() { return this.parentElement.children.indexOf(this) * 200; },
      remove() { if (this.parentElement) { const a = this.parentElement.children; a.splice(a.indexOf(this), 1); this.parentElement = null; } },
    }),
    homeEntryMedia: (entry) => entry.item || entry,
    homeEntryKey: (entry) => String(entry.index),
    mediaJellyfinStatus: () => "unknown",
  });
  context.CSS = { escape: value => value };
  context.root = { querySelector: () => track, querySelectorAll: () => [] };
  vm.runInContext(carousel.replace(/^import .*;\n/gm, "").replace("export function", "function"), context);
  vm.runInContext("Object.assign(globalThis, createCarousel(root, state.home))", context);
  const renderer = createRailRenderer({ ownerDocument: { defaultView: {} } }, {
    artwork: { start() {} }, carousel: context,
    homeEntryMedia: context.homeEntryMedia, homeEntryKey: context.homeEntryKey,
    mediaJellyfinStatus: context.mediaJellyfinStatus, getJellyfinStatus: () => undefined,
  });
  Object.assign(context, { reconcileHomeRail: renderer.reconcile, homeRailCardSignature: renderer.signature, syncHomeCardContent: renderer.sync });
  vm.runInContext(homeRows.replace("export function", "function"), context);
  vm.runInContext("globalThis.renderHomeRail = createHomeRows(root, { isLoading: () => false, reconcileHomeRail, homeRailCardSignature, createHomeCard, syncHomeCardContent })", context);
  context.entries = Array.from({ length: 12 }, (_, index) => ({ index }));

  vm.runInContext('renderHomeRail("home-test-track", entries)', context);
  assert.equal(track.scrollLeft, 600);
  assert.equal(track.replaceCount || 0, 0);
  animationFrames.forEach((callback) => callback());
  assert.equal(track.scrollLeft, 600);

  // Smooth scrolling starts asynchronously. A data refresh in the same frame
  // must restore the requested target, not the still-current zero position.
  track.scrollLeft = 0;
  vm.runInContext("moveHomeRail({ dataset: { homeScroll: 'home-test-track', direction: '1' } })", context);
  assert.ok(Math.abs(context.state.home.railScrollTargets[track.id] - 2808) < 0.01);
  track.scrollLeft = 137;
  vm.runInContext('renderHomeRail("home-test-track", entries)', context);
  assert.equal(track.scrollLeft % 600, 137);
  assert.equal(track.children.length, 18);
  assert.equal(track.children.filter(card => card.dataset.renderSignature.startsWith('loop:1:')).length, 12);
  assert.equal(track.replaceCount || 0, 0);

  track.children = [];
  track.scrollLeft = 0;
  vm.runInContext('renderHomeRail("home-test-track", entries, { layout: "spotlight" })', context);
  assert.equal(track.children.length, 7);
  assert.equal(track.dataset.homeLoopCount, "0");

  track.children = [];
  track.scrollLeft = 0;
  vm.runInContext('renderHomeRail("home-test-track", entries.slice(0, 10), { ranked: true })', context);
  assert.equal(track.children.length, 10);
  assert.equal(track.dataset.homeLoopCount, "0");
});

test("evening direction is progressive, explainable, and optionally deep", () => {
  requiresIds(
    "mood-modal", "mood-journey", "mood-options", "mood-results", "mood-lead",
    "mood-back", "mood-quick", "mood-refine", "mood-refine-toggle", "mood-next",
    "mood-genre-compass", "mood-genre-toggle", "mood-genre-panel", "mood-genre-options",
  );
  assert.match(html, /id="mood-nav-open"[^>]*data-mood-open/);
  assert.match(html, /id="home-program-mood"[^>]*data-mood-open/);
  assert.match(app, /const MOOD_MATCH_STEPS = \[/);
  assert.match(app, /Was soll heute laufen/);
  assert.match(app, /Was soll der Titel mit dir machen/);
  assert.match(app, /const MOOD_GENRE_COMPASS = \[/);
  assert.match(app, /function toggleMoodGenreCompass\(\)/);
  assert.match(app, /function moodMatchesGenreFocus\(entry, answers/);
  assert.match(html, /Bis zu zwei Genres[^<]*muss jeder Treffer beide tragen/);
  assert.match(app, /function moodMatchQuickResult\(\)/);
  assert.match(app, /function openMoodRefinement\(\)/);
  assert.match(app, /function moodFamilyPool\(entries\)/);
  assert.match(app, /function moodMatchResults\(answers,/);
  assert.match(app, /const MOOD_MATCH_RULES = MOOD_MATCH_PROFILES/);
  assert.match(app, /function moodMatchesRefinements\(entry, refinements/);
  assert.match(app, /Unbekannte Laufzeiten zählen bei einem Limit nicht als Treffer/);
  assert.match(app, /Diese Kombination wird nicht mit unpassenden oder unbekannten Titeln aufgefüllt/);
  assert.match(app, /function prepareMoodCandidates\(signal/);
  assert.match(app, /await Promise\.race\(\[prepareMoodCandidates\(request\.signal\), delay\(8000, request\.signal\)\]\)/);
  assert.match(app, /return moodIntentTier\(entry, answers\) < 2/);
  assert.match(app, /requestId !== moodState\.requestId/);
  assert.match(app, /function resumeMoodMatchAfterDetail\(\)/);
  assert.match(app, /resumeMoodMatchAfterDetail\(\)/);
  assert.match(app, /shell\/actions\.js/);
  assert.doesNotMatch(html, /src="\/screens\/mood\.js/);
  assert.doesNotMatch(mood, /source: "mood-session"/);
});

test("evening recommendations keep hard constraints and unknown metadata out", () => {
  const entries = [
    { kind: "movie", item: { slug: "slasher", title: "Slasher", genres: ["Horror"], runtime: "82 min", year: "2024" } },
    { kind: "movie", item: { slug: "thriller", title: "Dark Thriller", genres: ["Thriller"], runtime: "112 min", year: "2015" } },
    { kind: "movie", item: { slug: "unknown", title: "Unknown", genres: [] } },
    { kind: "movie", item: { slug: "comedy", title: "Horror Comedy", genres: ["Horror", "Komödie"] } },
    { kind: "movie", item: { slug: "family", title: "Family Adventure", genres: ["Animation", "Abenteuer"] } },
    { kind: "movie", item: { slug: "documentary", title: "True Story", genres: ["Dokumentation"], runtime: 88 } },
    { kind: "movie", item: { slug: "western", title: "Open Range", genres: ["Western"], runtime: 120 } },
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
  Object.assign(context, createMoodModel(context), { MOOD_GENRE_COMPASS });
  context.entries = entries;
  const results = vm.runInContext(`moodMatchResults({
    mood: "shadow", company: "alone", format: "movie"
  })`, context);
  assert.deepEqual(
    Array.from(results, (entry) => entry.item.title),
    ["Slasher", "Dark Thriller"],
  );

  const short = vm.runInContext(`moodMatchResults(
    { mood: "open", company: "alone", format: "movie" },
    { ...createMoodRefinements(), duration: "90" }
  )`, context);
  assert.deepEqual(Array.from(short, (entry) => entry.item.title), ["Slasher", "True Story"]);

  const family = vm.runInContext("moodFamilyPool(entries)", context);
  assert.deepEqual(Array.from(family, (entry) => entry.item.title), ["Family Adventure"]);
  assert.equal(vm.runInContext('moodHasGenre(new Set(["Drama"]), "a")', context), false);

  const genreBlend = vm.runInContext(`moodMatchResults({
    mood: "laugh", company: "alone", format: "movie", genres: ["Horror", "Komödie"]
  })`, context);
  assert.deepEqual(Array.from(genreBlend, (entry) => entry.item.title), ["Horror Comedy"]);
  const documentary = vm.runInContext(`moodMatchResults({
    mood: "real", company: "alone", format: "movie", genres: ["Dokumentation"]
  })`, context);
  assert.deepEqual(Array.from(documentary, (entry) => entry.item.title), ["True Story"]);
  assert.equal(vm.runInContext("MOOD_GENRE_COMPASS.length", context), 24);
  assert.equal(vm.runInContext('moodHasGenre(normalizedMoodGenres({ genres: ["Sci-Fi & Fantasy"] }), "Fantasy")', context), true);
});

test("feature modules load in dependency order before bootstrap", () => {
  const sources = [...html.matchAll(/<script(?: type="module")? src="\/([^"?]+)/g)]
    .map((match) => match[1]);
  const positions = appModulePaths.filter(path => !path.startsWith("js/")).map((path) => sources.indexOf(path));
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
    "styles/movie-collections.css",
    "styles/series.css",
    "styles/catalog.css",
    "styles/catalog-polish.css",
    "styles/movie-releases.css",
    "styles/storage-manager.css",
    "styles/storage-move.css",
    "styles/storage-move-jobs.css",
    "styles/movie-language.css",
    "styles/taste-feedback.css",
    "styles/daily-top.css",
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
  assert.match(stylesheet, /legacy-account\.css\?v=royal-20260921-2/);
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
  assert.match(api, /queueJobCancel: id => post\(/);
  assert.match(api, /queueJobRetry: id => post\(/);
  assert.match(api, /queueJobMove: \(id, direction\) => post\(/);
  assert.match(api, /queueJobResume: id => post\(/);
  assert.match(app, /row\.dataset\.jobId/);
  assert.match(app, /function renderQueueHistory\(jobs\)/);
  assert.match(app, /function updateQueueJobProgress\(jobId, job\)/);
  assert.match(accountStyles, /\.queue-action-btn[\s\S]*touch-action:\s*manipulation/);
});

test("movie download failures stay visible with their exact queue reason", () => {
  requiresIds("fp-detail-add", "fp-detail-download-status");
  assert.equal(
    queueAddFailureReason(
      { added: 0, skipped: 1, skipped_details: { movie: "kein Hoster verfügbar" } },
      ["movie"],
    ),
    "kein Hoster verfügbar",
  );
  assert.equal(
    queueAddFailureReason({ added: 1, skipped: 0 }, ["movie"]),
    "",
  );
  assert.match(app, /applyFpQueueAddResponse\(slug, resp\)/);
  assert.match(app, /applyFpDownloadJobResult\(data\)/);
  assert.match(app, /features\/downloads\/actions\.js/);
  assert.match(
    app,
    /const movie = provided \|\| await prepareFpMovieDownload\(slug, owner\);[\s\S]*?if \(!movie \|\| !owner\.active\) return;[\s\S]*?await client\.post\("\/api\/queue\/add"/,
  );
  assert.match(app, /Jellyfin wird live geprüft\. Der Download startet danach automatisch\./);
  assert.match(app, /if \(Array\.isArray\(cached\?\.hosters\) && cached\.hosters\.length\) return cached/);
  assert.doesNotMatch(app, /void api\.movie\(slug\)\.then/);
  assert.match(app, /Download nicht gestartet:/);
  assert.match(app, /Download fehlgeschlagen:/);
  assert.match(
    app,
    /await loadFpMetadata\(item, owner\);[\s\S]*?if \(!current\(owner, slug\)\) return;[\s\S]*?await client\.get\(`/,
  );
  assert.doesNotMatch(app, /!String\(slug\)\.startsWith\("tmdb:"\)/);
  assert.match(app, /!queued && \(metadataOnly \|\| !hasHosters\)/);
  assert.match(app, /Prüfe Verfügbarkeit …/);
  assert.match(app, /Derzeit nicht verfügbar/);
  assert.match(app, /error\.code === "movie_hoster_unavailable"/);
  assert.match(
    app,
    /const tmdbId = movieState\.metadataCache\[slug\]\?\.tmdb_id[\s\S]*?client\.get\(`/,
  );
  assert.match(api, /client.get\(`\/api\/movie\//);
  assert.match(api, /new URLSearchParams\(\{ tmdb_id: String\(tmdbId\) \}\)/);
});

test("Royal archive behaves like a searchable media center", () => {
  requiresIds(
    "library-hero-title", "wl-hero-open", "wl-hero-check",
    "wl-search-form", "wl-search", "wl-sort", "wl-visible-count",
  );
  for (const filter of ["all", "attention", "current", "queued"]) {
    assert.match(html, new RegExp(`data-library-filter=["']${filter}["']`));
  }
  assert.match(app, /function libraryVisibleItems\(items, ui\)/);
  assert.match(app, /function showLibraryHero\(entry\)/);
  assert.match(app, /listen\("wl-search-form", "submit"/);
  assert.match(app, /entry\.backdrop_url/);
  assert.match(app, /library-card-progress/);
  assert.match(stylesheet, /library\.css\?v=royal-20260825-1/);
  assert.match(html, /style\.css\?v=royal-20260921-3/);
});

test("scheduled episodes stay disabled and hero trailers return to artwork", () => {
  assert.match(html, /is-scheduled[^\n]*Terminiert/);
  assert.match(app, /ep\.unreleased \? `Folge \$\{ep\.episode\}, verfügbar ab/);
  assert.match(app, /completedSeriesHeroTrailers\.add/);
  assert.match(app, /playerState === 0/);
  assert.doesNotMatch(app, /controls=0&loop=1/);
  assert.match(app, /disablekb=1&fs=0&iv_load_policy=3/);
});

test("detail hero trailers pause below the header and stop listening on unmount", t => {
  const messages = [];
  const classes = new Set();
  const panel = new EventTarget();
  panel.scrollTop = 0;
  const shell = { hidden: false, clientHeight: 600, dataset: {},
    classList: { add: value => classes.add(value), remove: value => classes.delete(value) } };
  const frame = { getAttribute: () => "https://www.youtube-nocookie.com/embed/test",
    contentWindow: { postMessage: message => messages.push(JSON.parse(message)) } };
  let pending;
  const previousFrame = globalThis.requestAnimationFrame;
  const previousCancel = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = callback => { pending = callback; return 1; };
  globalThis.cancelAnimationFrame = () => { pending = null; };
  t.after(() => { globalThis.requestAnimationFrame = previousFrame; globalThis.cancelAnimationFrame = previousCancel; });
  const scroll = createDetailHeroScroll({
    querySelector: selector => selector === "#fp-detail-panel" ? panel : null,
    getElementById: id => id === "fp-detail-hero-trailer" ? shell : frame,
  });
  scroll.mount(); scroll.mount();
  panel.scrollTop = 300;
  panel.dispatchEvent(new Event("scroll")); pending();
  panel.scrollTop = 0;
  panel.dispatchEvent(new Event("scroll")); pending();
  assert.deepEqual(messages.map(message => message.func), ["pauseVideo", "playVideo"]);
  assert.equal(classes.has("is-scroll-paused"), false);
  panel.dispatchEvent(new Event("scroll"));
  scroll.unmount();
  assert.equal(pending, null);
  panel.dispatchEvent(new Event("scroll"));
  assert.equal(pending, null);
});

test("trailer player opens immediately with resilient playback states", () => {
  requiresIds(
    "fp-trailer-state", "fp-trailer-retry", "fp-trailer-external",
    "fp-trailer-autoplay", "fp-trailer-focus-end",
  );
  assert.match(app, /function openFpTrailerModal\(movie, trigger, heroKind = "film"\)/);
  assert.doesNotMatch(app, /async function openFpTrailerModal/);
  assert.match(app, /openTrailerPlayer\(movie, key, startAt, trigger\)/);
  assert.match(app, /heroTrailerAutoplayEnabled\(\)/);
  assert.match(app, /setTrailerPlayerState\("error"/);
  assert.match(app, /function trailerModalFocusableElements\(\)/);
  assert.match(app, /return saved === null \? true : saved === "true"/);
  assert.doesNotMatch(html, /src="\/trailer-runtime\.js/);
  assert.match(stylesheet, /legacy-details\.css\?v=royal-20260810-2/);
});

test("taste feedback is a compact accessible two-way control", () => {
  assert.match(html, /class="taste-feedback" role="group" aria-label="Serie bewerten"/);
  assert.match(html, /class="btn btn-ghost taste-like"/);
  assert.match(html, /class="btn btn-ghost taste-dislike"/);
  assert.match(app, /like\.querySelector\("\.taste-icon"\)\.textContent = liked \? "♥" : "♡"/);
  assert.match(app, /dislike\.querySelector\("\.taste-icon"\)\.textContent = disliked \? "⊗" : "⊘"/);
  assert.match(app, /pendingTasteFeedbackKeys\.add\(target\.key\)/);
  assert.match(app, /applyLocalTasteFeedback\(target\.key, action\)/);
  assert.match(app, /pendingTasteFeedbackKeys\.delete\(target\.key\)/);
  assert.match(stylesheet, /catalog\.css\?v=royal-20260830-1/);
});


test("artwork preserves provider identity and ignores aborted late responses", async () => {
  let resolve;
  let signal;
  let writes = 0;
  const cache = {};
  const artwork = createCatalogArtwork({
    getMovieMetadata: () => cache,
    saveHomeCache: () => writes++, renderHome: () => writes++,
    onSeriesHydrated: () => writes++,
    client: { post: (_url, _body, options) => {
      signal = options.signal;
      return new Promise(done => { resolve = done; });
    } },
  });
  const entry = { base_slug: "source", title: "Provider title", year: "2022", tmdb_id: 12,
    genres: ["Drama"], metadata_policy: "provider_authoritative" };
  const pending = artwork.series([entry]);
  resolve({ series: { source: { title: "Other", year: "1990", tmdb_id: 99, genres: ["Other"],
    base_slug: "wrong", cover_url: "poster", backdrop_url: "wallpaper" } } });
  await pending;
  assert.deepEqual(entry, { base_slug: "source", title: "Provider title", year: "2022", tmdb_id: 12,
    genres: ["Drama"], metadata_policy: "provider_authoritative", cover_url: "poster", backdrop_url: "wallpaper" });
  const before = writes;
  const movie = artwork.movies([{ slug: "movie", title: "Movie" }]);
  artwork.unmount();
  assert.equal(signal.aborted, true);
  resolve({ movies: { movie: { cover_url: "late" } } });
  await movie;
  assert.deepEqual(cache, {});
  assert.equal(writes, before);
  artwork.mount();
  const controller = new AbortController();
  const other = { base_slug: "other", title: "Other" };
  const cancelled = artwork.series([other], { signal: controller.signal });
  controller.abort();
  assert.equal(signal.aborted, true);
  resolve({ series: { other: { cover_url: "late" } } });
  await cancelled;
  assert.equal(other.cover_url, undefined);
  assert.equal(writes, before);
  artwork.unmount();
});
