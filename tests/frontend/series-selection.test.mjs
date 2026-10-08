import test from 'node:test';
import assert from 'node:assert/strict';
import { createSeriesChecks } from '../../web/js/features/media-details/series-checks.js';
import { createSeriesEpisodes } from '../../web/js/features/media-details/series-episodes.js';
import { createSeriesDetailsLoader } from '../../web/js/features/media-details/series-loader.js';
import { episodeLanguageBatches } from '../../web/js/features/media-details/series-language-order.js';

const tick = () => new Promise(resolve => setImmediate(resolve));
async function requestAt(f, index) {
  for (let n = 0; n < 100 && !f.requests[index]; n++) await new Promise(resolve => setTimeout(resolve, 1));
  assert.ok(f.requests[index], `request ${index} starts`);
  return f.requests[index];
}

function inventoryFixture(count = 15, episodesPerSeason = 12) {
  const seasons = Array.from({length: count}, (_, index) => ({season: index + 1,
    episodes: Array.from({length: episodesPerSeason}, (_, episode) => ({season: index + 1, episode: episode + 1,
      slug: `sto:show-s${index + 1}e${episode + 1}`}))}));
  return {base_slug: 'sto:show', provider: 'serienstream', seasons};
}
const missingEpisodes = series => series.seasons.flatMap(season => season.episodes)
  .filter(episode => !episode.downloaded && !episode.in_jellyfin && !episode.unreleased);

test('a new fifteen-season series starts at the beginning even with shuffled catalog seasons', () => {
  const series = inventoryFixture();
  series.seasons.reverse();
  const before = structuredClone(series);
  const batches = episodeLanguageBatches(series, missingEpisodes(series));
  assert.deepEqual(batches[0].map(episode => episode.slug), ['sto:show-s1e1', 'sto:show-s1e2', 'sto:show-s1e3', 'sto:show-s1e4']);
  assert.equal(batches.at(-1).at(-1).slug, 'sto:show-s15e12');
  assert.deepEqual(series, before, 'scheduling never changes the displayed catalog or evidence');
});

test('Chicago P.D. continues at S13E07 and regularly probes older inventory gaps', () => {
  const series = inventoryFixture();
  for (const season of series.seasons) for (const episode of season.episodes) {
    episode.downloaded = season.season < 13 || (season.season === 13 && episode.episode <= 5);
    episode.in_jellyfin = season.season === 13 && episode.episode === 6;
  }
  for (const episode of series.seasons[0].episodes) episode.downloaded = false;
  const batches = episodeLanguageBatches(series, missingEpisodes(series));
  assert.equal(batches[0][0].slug, 'sto:show-s13e7');
  assert.equal(batches[1][0].slug, 'sto:show-s13e11');
  assert.equal(batches[2][0].slug, 'sto:show-s1e1', 'old gaps progress before all newer seasons complete');
  assert.equal(batches[3][0].slug, 'sto:show-s14e3');
  assert.equal(batches.flat().length, missingEpisodes(series).length);
  assert.equal(new Set(batches.flat().map(episode => episode.slug)).size, batches.flat().length);
});

test('a completed library prioritizes the next published season and skips upcoming episodes', () => {
  const series = inventoryFixture(15, 4);
  for (const season of series.seasons.slice(0, 14)) for (const episode of season.episodes) episode.in_jellyfin = true;
  series.seasons[14].episodes[3].unreleased = true;
  assert.deepEqual(episodeLanguageBatches(series, missingEpisodes(series))[0].map(episode => episode.slug),
    ['sto:show-s15e1', 'sto:show-s15e2', 'sto:show-s15e3']);
});

test('provider listings and queued episodes never establish an inventory continuation', () => {
  const series = inventoryFixture(15, 4);
  for (const episode of series.seasons[14].episodes) Object.assign(episode, {queued: true, content_languages: ['de']});
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s1e1');
});

test('an unavailable or pending library is unknown rather than empty; retained positives still anchor it', () => {
  const series = inventoryFixture();
  Object.assign(series, {jellyfin_configured: true, jellyfin_available: false});
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s15e1');
  series.jellyfin_available = true;
  series.jellyfin_pending = true;
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s15e1');
  series.seasons[12].episodes[0].in_jellyfin = true;
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s13e2');
  series.seasons[12].episodes[0].in_jellyfin = false;
  series.jellyfin_pending = false;
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s1e1');
  series.jellyfin_stale = true;
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s15e1');
});

test('a hole inside the current season is checked before continuing and a finished library backfills old holes', () => {
  const series = inventoryFixture(3, 4);
  for (const season of series.seasons) for (const episode of season.episodes) episode.downloaded = true;
  series.seasons[2].episodes[1].downloaded = false;
  series.seasons[0].episodes[0].downloaded = false;
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s3e2');
  series.seasons[2].episodes[1].downloaded = true;
  assert.equal(episodeLanguageBatches(series, missingEpisodes(series))[0][0].slug, 'sto:show-s1e1');
});

test('subscription language is sent to probes and mixed-profile evidence cannot grant German selection', async () => {
  const f = fixture(1);
  f.series.enabled_content_languages = ['de'];
  Object.assign(f.episodes[0], {language_checked: true, language_available: true,
    content_languages: ['en'], language_profile: ['de', 'en']});
  assert.equal(f.model.isEpisodeSelectable(f.episodes[0]), false);
  const selection = f.model.toggleEpisodeTile(f.episodes[0].slug);
  for (let i = 0; i < 2; i++) {
    const request = await requestAt(f, i);
    assert.deepEqual(request.body.content_languages, ['de']);
    request.resolve({languages: {[f.episodes[0].slug]: ['en']},
      available: {[f.episodes[0].slug]: false}, selected_content_languages: ['de']});
  }
  await selection;
  assert.equal(f.model.tileClass(f.episodes[0]), 'wrong-language');
  await f.model.seriesAddSelected();
  assert.equal(f.queueRequests.length, 0);
});

test('source identity keeps incomplete subscribed payloads behind language verification', () => {
  const f = fixture(1);
  delete f.series.provider;
  f.series.base_slug = 'serienstream:show';
  assert.equal(f.model.isEpisodeSelectable(f.episodes[0]), false);
  assert.equal(f.model.tileClass(f.episodes[0]), 'language-pending');
});

test('language changes ignore a delayed response from the previous profile', async () => {
  const f = fixture(1);
  f.series.enabled_content_languages = ['en'];
  const selection = f.model.toggleEpisodeTile(f.episodes[0].slug);
  const request = await requestAt(f, 0);
  f.series.enabled_content_languages = ['de'];
  request.resolve({languages: {[f.episodes[0].slug]: ['en']},
    available: {[f.episodes[0].slug]: true}, selected_content_languages: ['en']});
  await selection;
  assert.equal(f.model.isEpisodeSelectable(f.episodes[0]), false);
  assert.equal(f.episodes[0].language_checked, undefined);
});
function fixture(count = 12, languageConcurrency = 1) {
  const episodes = Array.from({length: count}, (_, i) => ({slug: `sto:show-s01e${i+1}`, season: 1, episode: i+1}));
  const series = {base_slug: 'sto:show', provider: 'serienstream', seasons: [{season: 1, episodes}]};
  const state = {current: series, cache: {}, viewGeneration: 1, epPicked: new Set()};
  const node = () => Object.assign(new EventTarget(), {dataset: {}, textContent: '', innerHTML: '',
    setAttribute() {}, removeAttribute() {}, append() {}, appendChild() {}, prepend() {},
    querySelector: () => null, querySelectorAll: () => []});
  const nodes = new Map();
  const root = Object.assign(node(), {hidden: false, ownerDocument: {createElement: node}, querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id);
  }});
  const requests = [], queueRequests = [], queued = new Set(), status = {textContent: ''};
  let model;
  const merger = createSeriesDetailsLoader(root, status, {seriesState: state});
  const checks = createSeriesChecks(status, {seriesState: state, isVisible: () => true, retryDelays: [0, 0], languageConcurrency,
    firstEpisodeSlug: current => current.seasons[0]?.episodes[0]?.slug,
    syncSeriesQueueFlags() {}, seriesStructureFingerprint: () => '', mergeSeriesDetailPayload: merger.merge,
    updateSeriesOverview() {}, updateWatchBtn() {}, updateSeriesStatus() {},
    pruneSeriesEpisodeSelection: () => model?.pruneSeriesEpisodeSelection(),
    refreshSeriesTileStates: () => model?.refreshSeriesTileStates(),
    renderSeriesTiles: () => model?.renderSeriesTiles(),
    client: {post: (url, body, options) => new Promise((resolve, reject) => requests.push({url, body, options, resolve, reject}))}});
  model = createSeriesEpisodes(root, {status, seriesState: state, getQueuedSlugs: () => queued,
    getEnabledLanguages: () => ['de'], verifyHuhuEpisodeLanguages: checks.verifyLanguages,
    trackDiscoveryPreference() {}, refreshQueueUiAfterChange() {},
    client: {post: (url, body, options) => new Promise((resolve, reject) => queueRequests.push({url, body, options, resolve, reject}))}});
  const respond = (request, denied = []) => request.resolve({
    available: Object.fromEntries(request.body.slugs.map(slug => [slug, !denied.includes(slug)])),
    languages: Object.fromEntries(request.body.slugs.map(slug => [slug, [denied.includes(slug) ? 'en' : 'de']]))});
  return {episodes, series, state, model, checks, requests, queueRequests, queued, respond, status, root, nodes};
}

async function finishBackground(f, work) {
  let finished = false;
  const done = work.finally(() => { finished = true; });
  for (let iteration = 0; iteration < 150 && !finished; iteration++) {
    for (const request of f.requests.filter(request => request.url === '/api/series/episode-languages' && !request.answered)) {
      request.answered = true; f.respond(request);
    }
    await tick();
  }
  assert.equal(finished, true, 'independent background batches finish');
  await done;
}

test('a late Jellyfin inventory reprioritizes waiting probes while a selected older episode keeps precedence', async () => {
  const f = fixture(1);
  f.state.current = inventoryFixture();
  Object.assign(f.state.current, {jellyfin_configured: true, jellyfin_available: false});
  const work = f.checks.refresh();
  const libraryRequest = f.requests[0], loadRequest = f.requests[1];
  assert.equal(libraryRequest.url, '/api/series/jellyfin-status');
  loadRequest.resolve(structuredClone(f.state.current));
  const active = await requestAt(f, 2);
  assert.equal(active.body.slugs[0], 'sto:show-s15e1');
  const selection = f.model.toggleEpisodeTile('sto:show-s1e9');
  libraryRequest.resolve({configured: true, available: true, stale: false,
    episodes: Object.fromEntries(missingEpisodes(f.state.current).map(episode => [episode.slug,
      episode.season === 13 && episode.episode <= 6]))});
  await tick();
  assert.equal(active.options.signal.aborted, false, 'new inventory does not cancel a running probe');
  active.answered = true; f.respond(active);
  const clicked = await requestAt(f, 3);
  assert.equal(clicked.body.slugs[0], 'sto:show-s1e9');
  clicked.answered = true; f.respond(clicked); await selection;
  const continuation = await requestAt(f, 4);
  assert.equal(continuation.body.slugs[0], 'sto:show-s13e7');
  assert.equal(f.state.epPicked.has('sto:show-s1e9'), true);
  await finishBackground(f, work);
  assert.equal(f.requests.filter(request => request.url === '/api/series/episode-languages')
    .some(request => request.body.slugs.some(slug => /^sto:show-s13e[1-6]$/.test(slug))), false,
    'newly confirmed inventory is skipped even if its batch was already waiting');
});

test('automatic probes defer a lightweight inventory snapshot while explicit selections remain independent', async () => {
  const f = fixture(4);
  f.series.availability_pending = true;
  await f.checks.verifyLanguages(f.episodes, f.series, {background: true});
  assert.equal(f.requests.length, 0);
  const selection = f.model.toggleEpisodeTile(f.episodes[0].slug);
  const request = await requestAt(f, 0);
  assert.deepEqual(request.body.slugs, [f.episodes[0].slug]);
  f.respond(request); await selection;
  assert.equal(f.state.epPicked.has(f.episodes[0].slug), true);
});

test('a live inventory received before cached enrichment still starts at the continuation', async () => {
  const f = fixture(1);
  f.state.current = inventoryFixture(15, 4);
  Object.assign(f.state.current, {jellyfin_configured: true, jellyfin_available: false});
  const cached = structuredClone(f.state.current);
  const work = f.checks.refresh();
  f.requests[0].resolve({configured: true, available: true, stale: false,
    episodes: {'sto:show-s13e1': true}});
  await tick();
  f.requests[1].resolve(cached);
  const first = await requestAt(f, 2);
  assert.equal(first.body.slugs[0], 'sto:show-s13e2');
  assert.equal(f.state.current.seasons[12].episodes[0].in_jellyfin, true);
  assert.equal(f.state.current.jellyfin_available, true);
  await finishBackground(f, work);
});

test('an unavailable live inventory and cached enrichment retain previously confirmed Jellyfin episodes', async () => {
  const f = fixture(1);
  f.state.current = inventoryFixture(15, 4);
  Object.assign(f.state.current, {jellyfin_configured: true, jellyfin_available: true});
  f.state.current.seasons[12].episodes[0].in_jellyfin = true;
  const unavailable = structuredClone(f.state.current);
  unavailable.jellyfin_available = false;
  unavailable.seasons[12].episodes[0].in_jellyfin = false;
  const work = f.checks.refresh();
  f.requests[0].resolve({configured: true, available: false, stale: false,
    episodes: {'sto:show-s13e1': false}});
  await tick();
  f.requests[1].resolve(unavailable);
  const first = await requestAt(f, 2);
  assert.equal(first.body.slugs[0], 'sto:show-s13e2');
  assert.equal(f.state.current.seasons[12].episodes[0].in_jellyfin, true);
  await finishBackground(f, work);
  const fresh = structuredClone(f.state.current);
  fresh.jellyfin_available = true;
  fresh.jellyfin_stale = false;
  fresh.seasons[12].episodes[0].in_jellyfin = false;
  const loader = createSeriesDetailsLoader(f.root, f.status, {seriesState: f.state});
  assert.equal(loader.merge(f.state.current, fresh).seasons[12].episodes[0].in_jellyfin, false,
    'an authoritative later removal still updates the inventory');
});

test('confirmed fallback releases a TMDB-scheduled episode and survives enrichment', async () => {
  const f = fixture(2);
  Object.assign(f.episodes[0], {unreleased: true, provider_unreleased: false});
  Object.assign(f.episodes[1], {unreleased: true, provider_unreleased: true, release_label: 'Demnächst'});
  const checking = f.checks.verifyLanguages(f.episodes, f.series);
  const request = await requestAt(f, 0);
  assert.deepEqual(request.body.slugs, [f.episodes[0].slug]);
  request.resolve({available: {[f.episodes[0].slug]: true}, languages: {[f.episodes[0].slug]: ['de']},
    source_providers: {[f.episodes[0].slug]: ['hdfilme_family']}});
  await checking;
  assert.equal(f.model.isEpisodeSelectable(f.episodes[0]), true);
  assert.equal(f.model.isEpisodeSelectable(f.episodes[1]), false);
  const loader = createSeriesDetailsLoader(f.root, f.status, {seriesState: f.state});
  const fresh = structuredClone(f.series);
  Object.assign(fresh.seasons[0].episodes[0], {unreleased: true, content_languages: ['en'],
    language_checked: false, huhu_language_checked: false});
  f.state.current = loader.merge(f.series, fresh);
  assert.equal(f.model.isEpisodeSelectable(f.state.current.seasons[0].episodes[0]), true);
  const upcoming = structuredClone(fresh);
  upcoming.seasons[0].episodes[0].provider_unreleased = true;
  f.state.current = loader.merge(f.state.current, upcoming);
  assert.equal(f.model.isEpisodeSelectable(f.state.current.seasons[0].episodes[0]), false);
});

test('an unverified season cannot enter the queue; confirmed batches become downloadable', async () => {
  const f = fixture(8);
  const selection = f.model.toggleSeasonTiles(1);
  assert.equal(f.nodes.get('#series-add-btn').disabled, true);
  assert.match(f.nodes.get('#series-pick-count').textContent, /0 ausgewählt · 8 in Prüfung/);
  await f.model.seriesAddSelected();
  assert.equal(f.queueRequests.length, 0, 'programmatic submission cannot bypass the disabled button');
  f.respond(f.requests[0]); await tick();
  const download = f.model.seriesAddSelected();
  await f.model.seriesAddSelected();
  assert.equal(f.queueRequests.length, 1, 'double click does not submit twice');
  assert.deepEqual(f.queueRequests[0].body.slugs, f.episodes.slice(0, 4).map(ep => ep.slug));
  f.queueRequests[0].resolve({added: 4}); await download;
  f.respond(await requestAt(f, 1)); await selection;
  assert.deepEqual([...f.state.epPicked], f.episodes.slice(4).map(ep => ep.slug), 'independent pending batches retain their selection intent');
  assert.equal(f.nodes.get('#series-add-btn').disabled, false);
});

test('a mixed selection submits only verified episodes and keeps pending intent across hydration', async () => {
  const f = fixture(5);
  f.episodes[0].language_checked = true; f.episodes[0].content_languages = ['de'];
  f.episodes[1].language_checked = true; f.episodes[1].content_languages = ['en'];
  f.episodes[2].unreleased = true;
  const selection = f.model.toggleSeasonTiles(1);
  const download = f.model.seriesAddSelected();
  assert.deepEqual(f.queueRequests[0].body.slugs, [f.episodes[0].slug]);
  // Hydration must not strand the submitted selection in the same view.
  f.state.current = structuredClone(f.series);
  f.queueRequests[0].resolve({added: 1}); await download;
  f.respond(f.requests[0]); await selection;
  assert.deepEqual([...f.state.epPicked], [f.episodes[3].slug, f.episodes[4].slug]);
});

test('a failed queue request keeps the confirmed selection available for retry', async () => {
  const f = fixture(4);
  const selection = f.model.toggleSeasonTiles(1);
  f.respond(f.requests[0]); await selection;
  const download = f.model.seriesAddSelected();
  f.queueRequests[0].reject(new Error('offline')); await download;
  assert.equal(f.nodes.get('#series-add-btn').disabled, false);
  const retry = f.model.seriesAddSelected();
  assert.deepEqual(f.queueRequests[1].body.slugs, f.episodes.map(ep => ep.slug));
  f.queueRequests[1].resolve({added: 4}); await retry;
  assert.equal(f.state.epPicked.size, 0);
});

test('queued unverified episodes show queue state instead of a new pending selection', () => {
  const f = fixture(1);
  f.queued.add(f.episodes[0].slug);
  assert.equal(f.model.tileClass(f.episodes[0]), 'queued');
  assert.equal(f.model.isEpisodeActionable(f.episodes[0]), false);
});

test('a queue response preserves a different selection made while the request was pending', async () => {
  const f = fixture(2);
  Object.assign(f.episodes[0], {language_checked: true, content_languages: ['de']});
  const first = f.model.toggleEpisodeTile(f.episodes[0].slug);
  const download = f.model.seriesAddSelected();
  const second = f.model.toggleEpisodeTile(f.episodes[1].slug);
  f.queueRequests[0].resolve({added: 1}); await download;
  await first;
  f.respond(f.requests[0]); await second;
  assert.deepEqual([...f.state.epPicked], [f.episodes[1].slug]);
  assert.deepEqual(f.queueRequests[0].body.slugs, [f.episodes[0].slug]);
});

test('checks finishing before queue acceptance preserve newly confirmed, unsubmitted episodes', async () => {
  const f = fixture(4);
  Object.assign(f.episodes[0], {language_checked: true, content_languages: ['de']});
  const selection = f.model.toggleSeasonTiles(1);
  const download = f.model.seriesAddSelected();
  f.respond(f.requests[0]); await selection;
  assert.equal(f.state.epPicked.size, 4);
  assert.deepEqual(f.queueRequests[0].body.slugs, [f.episodes[0].slug]);
  f.queueRequests[0].resolve({added: 1}); await download;
  assert.deepEqual([...f.state.epPicked], f.episodes.slice(1).map(ep => ep.slug));
  assert.equal(f.nodes.get('#series-add-btn').disabled, false);
});

test('an episode click waits only for its batch, not the rest of the series', async () => {
  const f = fixture();
  const background = f.checks.verifyLanguages(f.episodes, f.series, {background: true});
  const click = f.model.toggleEpisodeTile(f.episodes[0].slug);
  assert.equal(f.requests[0].options.timeoutMs, 15_000);
  f.respond(f.requests[0]);
  await click;
  assert.deepEqual([...f.state.epPicked], [f.episodes[0].slug]);
  await tick();
  assert.equal(f.requests.length, 2);
  f.respond(f.requests[1]); await tick(); f.respond(f.requests[2]); await background;
});

test('clicked batches move ahead of unrelated queued background work', async () => {
  const f = fixture();
  const background = f.checks.verifyLanguages(f.episodes, f.series, {background: true});
  const click = f.model.toggleEpisodeTile(f.episodes[8].slug);
  f.respond(f.requests[0]); await tick();
  assert.deepEqual(f.requests[1].body.slugs, f.episodes.slice(8).map(ep => ep.slug));
  f.respond(f.requests[1]); await click; await tick();
  assert.ok(f.state.epPicked.has(f.episodes[8].slug));
  f.respond(f.requests[2]); await background;
});

test('season selection progresses per verified batch and survives same-view hydration', async () => {
  const f = fixture(8);
  const click = f.model.toggleSeasonTiles(1);
  assert.equal(f.state.epPicked.size, 0, 'unverified episodes remain excluded from downloads');
  f.state.current = structuredClone(f.series);
  f.respond(f.requests[0], [f.episodes[1].slug]); await tick();
  assert.equal(f.state.epPicked.size, 3, 'first batch is usable before later requests complete');
  assert.ok(!f.state.epPicked.has(f.episodes[1].slug), 'wrong-language episode stays blocked');
  f.respond(await requestAt(f, 1), [f.episodes[1].slug]);
  f.respond(await requestAt(f, 2)); await click;
  assert.equal(f.state.epPicked.size, 7);
});

test('known episodes select immediately and partial failure remains retryable', async () => {
  const f = fixture(5);
  f.episodes[0].language_checked = f.episodes[0].language_available = true;
  const click = f.model.toggleSeasonTiles(1);
  assert.ok(f.state.epPicked.has(f.episodes[0].slug));
  f.requests[0].reject(new Error('timeout'));
  (await requestAt(f, 1)).reject(new Error('timeout'));
  (await requestAt(f, 2)).reject(new Error('timeout')); await click; await tick();
  assert.equal(f.state.epPicked.size, 1);
  assert.match(f.status.textContent, /timeout/);
  const retry = f.model.toggleSeasonTiles(1);
  assert.equal(f.requests.length, 4); f.respond(f.requests[3]); await retry;
  assert.equal(f.state.epPicked.size, 5);
});

test('deselecting a pending season cancels the intent immediately', async () => {
  const f = fixture(4);
  const click = f.model.toggleSeasonTiles(1);
  await f.model.toggleSeasonTiles(1);
  f.respond(f.requests[0]); await click;
  assert.equal(f.state.epPicked.size, 0);
});

test('clear selection and a new view ignore delayed language results', async () => {
  const f = fixture(4); f.model.mount();
  const click = f.model.toggleSeasonTiles(1);
  f.nodes.get('#series-select-none').dispatchEvent(new Event('click'));
  f.respond(f.requests[0]); await click;
  assert.equal(f.state.epPicked.size, 0);
  f.episodes.forEach(ep => { ep.language_checked = ep.huhu_language_checked = false; });
  const next = f.model.toggleSeasonTiles(1);
  f.state.viewGeneration++; f.state.epPicked = new Set(['new-view']);
  f.respond(f.requests[1]); await next;
  assert.deepEqual([...f.state.epPicked], ['new-view']);
  f.model.unmount(); f.checks.unmount();
});

test('verified German tracks use the enabled profile instead of a stale availability flag', () => {
  const f = fixture(1);
  const episode = f.episodes[0];
  Object.assign(episode, {language_checked: true, language_available: false, content_languages: ['de']});
  f.state.current.enabled_content_languages = ['de'];
  assert.equal(f.model.isEpisodeSelectable(episode), true);
  assert.equal(f.model.episodeLanguageLockLabel(episode), '');
  episode.content_languages = ['en']; episode.language_available = true;
  assert.equal(f.model.isEpisodeSelectable(episode), false);
  assert.equal(f.model.episodeLanguageLockLabel(episode), 'NUR EN');
  episode.language_checked = false; episode.content_languages = ['de'];
  assert.equal(f.model.isEpisodeSelectable(episode), false, 'listing hints are not concrete track evidence');
});

test('hydration cannot relabel confirmed English or unknown tracks as German', async () => {
  const {createSeriesDetailsLoader} = await import('../../web/js/features/media-details/series-loader.js');
  const f = fixture(1);
  const loader = createSeriesDetailsLoader({}, {}, {seriesState: f.state});
  Object.assign(f.episodes[0], {language_checked: true, language_available: false, content_languages: ['en']});
  const fresh = structuredClone(f.series);
  delete fresh.seasons[0].episodes[0].language_checked;
  delete fresh.seasons[0].episodes[0].language_available;
  fresh.seasons[0].episodes[0].content_languages = ['de'];
  const enriched = loader.merge(f.series, fresh);
  assert.deepEqual(enriched.seasons[0].episodes[0].content_languages, ['en']);
  f.episodes[0].content_languages = [];
  assert.deepEqual(loader.merge(f.series, fresh).seasons[0].episodes[0].content_languages, []);
});

test('one missing episode page recovers automatically without losing the selection', async () => {
  const f = fixture(6);
  const click = f.model.toggleSeasonTiles(1);
  const first = f.requests[0], missing = f.episodes[0].slug;
  const known = first.body.slugs.filter(slug => slug !== missing);
  first.resolve({languages: Object.fromEntries(known.map(slug => [slug, ['de']])),
    available: Object.fromEntries(known.map(slug => [slug, true])), pending: [missing]});
  const retry = await requestAt(f, 1);
  assert.equal(f.state.epPicked.size, 3);
  assert.deepEqual(retry.body.slugs, [missing], 'only unconfirmed episodes are retried');
  assert.equal(retry.body.attempt, 1);
  assert.equal(f.model.episodeLanguageLockLabel(f.episodes[0]), '');
  f.respond(retry);
  f.respond(await requestAt(f, 2)); await click;
  assert.equal(f.state.epPicked.size, 6);
});

test('a first negative language response is verified again and can recover to German', async () => {
  const f = fixture(1);
  const click = f.model.toggleEpisodeTile(f.episodes[0].slug);
  f.respond(f.requests[0], [f.episodes[0].slug]);
  const retry = await requestAt(f, 1);
  assert.equal(f.episodes[0].language_checked, undefined);
  f.respond(retry); await click;
  assert.equal(f.state.epPicked.size, 1);
  assert.deepEqual(f.episodes[0].content_languages, ['de']);
});

test('unknown responses remain retryable after three attempts and a new click can recover', async () => {
  const f = fixture(1), missing = f.episodes[0].slug;
  const click = f.model.toggleEpisodeTile(missing);
  for (let i = 0; i < 3; i++) (await requestAt(f, i)).resolve({languages: {}, available: {}, pending: [missing]});
  await click;
  assert.equal(f.episodes[0].language_checked, undefined);
  assert.equal(f.model.episodeLanguageLockLabel(f.episodes[0]), '');
  const retry = f.model.toggleEpisodeTile(missing);
  f.respond(await requestAt(f, 3)); await retry;
  assert.equal(f.state.epPicked.size, 1);
});

test('closing a view during backoff cancels automatic retry', async () => {
  const f = fixture(1);
  const click = f.model.toggleEpisodeTile(f.episodes[0].slug);
  f.requests[0].reject(new Error('timeout'));
  f.state.viewGeneration++;
  await click; await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(f.requests.length, 1);
});


test('Chicago P.D. EN-only evidence stays visible and cannot be queued while alternatives are pending', async () => {
  const f = fixture(1);
  const click = f.model.toggleEpisodeTile(f.episodes[0].slug);
  for (let i = 0; i < 3; i++) {
    const request = await requestAt(f, i);
    request.resolve({languages: {[f.episodes[0].slug]: ['en']},
      available: {[f.episodes[0].slug]: false}, pending: [f.episodes[0].slug]});
  }
  await click;
  assert.deepEqual(f.episodes[0].content_languages, ['en']);
  assert.equal(f.model.tileClass(f.episodes[0]), 'language-pending');
  assert.equal(f.model.isEpisodeSelectable(f.episodes[0]), false);
  await f.model.seriesAddSelected();
  assert.equal(f.queueRequests.length, 0);
  const tile = {setAttribute() {}, removeAttribute() {}, appendChild(child) {this.notice = child;}, querySelector() {return null;}};
  f.model.applySeriesEpisodeTileState(tile, f.episodes[0], f.series);
  assert.equal(tile.notice.textContent, 'NUR EN');
  // A failed alternative must remain retryable; a later real DE source releases it.
  const retry = f.model.toggleEpisodeTile(f.episodes[0].slug);
  f.respond(await requestAt(f, 3)); await retry;
  assert.equal(f.model.isEpisodeSelectable(f.episodes[0]), true);
});


test('two independent batches run concurrently with bounded requests', async () => {
  const f = fixture(12, 2);
  const click = f.model.toggleSeasonTiles(1);
  assert.equal(f.requests.length, 2);
  f.respond(f.requests[1]);
  await requestAt(f, 2);
  assert.equal(f.state.epPicked.size, 4, 'fast batch is usable while the first is still pending');
  f.respond(f.requests[2]); await tick();
  assert.equal(f.state.epPicked.size, 8);
  assert.equal(f.requests.length, 3);
  f.respond(f.requests[0]); await click;
  assert.equal(f.state.epPicked.size, 12);
});
