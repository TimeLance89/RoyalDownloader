import test from 'node:test';
import assert from 'node:assert/strict';
import { createSeriesChecks } from '../../web/js/features/media-details/series-checks.js';
import { createSeriesEpisodes } from '../../web/js/features/media-details/series-episodes.js';

const tick = () => new Promise(resolve => setImmediate(resolve));
async function requestAt(f, index) {
  for (let n = 0; n < 100 && !f.requests[index]; n++) await new Promise(resolve => setTimeout(resolve, 1));
  assert.ok(f.requests[index], `request ${index} starts`);
  return f.requests[index];
}
function fixture(count = 12, languageConcurrency = 1) {
  const episodes = Array.from({length: count}, (_, i) => ({slug: `sto:show-s01e${i+1}`, season: 1, episode: i+1}));
  const series = {base_slug: 'sto:show', provider: 'serienstream', seasons: [{season: 1, episodes}]};
  const state = {current: series, viewGeneration: 1, epPicked: new Set()};
  const node = () => Object.assign(new EventTarget(), {dataset: {}, textContent: '', innerHTML: '',
    setAttribute() {}, removeAttribute() {}, append() {}, appendChild() {}, prepend() {},
    querySelector: () => null, querySelectorAll: () => []});
  const nodes = new Map();
  const root = Object.assign(node(), {hidden: false, ownerDocument: {createElement: node}, querySelector(id) {
    if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id);
  }});
  const requests = [], status = {textContent: ''};
  let model;
  const checks = createSeriesChecks(status, {seriesState: state, isVisible: () => true, retryDelays: [0, 0], languageConcurrency,
    pruneSeriesEpisodeSelection: () => model?.pruneSeriesEpisodeSelection(),
    renderSeriesTiles: () => model?.renderSeriesTiles(),
    client: {post: (url, body, options) => new Promise((resolve, reject) => requests.push({body, options, resolve, reject}))}});
  model = createSeriesEpisodes(root, {status, seriesState: state, getQueuedSlugs: () => new Set(),
    getEnabledLanguages: () => ['de'], verifyHuhuEpisodeLanguages: checks.verifyLanguages});
  const respond = (request, denied = []) => request.resolve({
    available: Object.fromEntries(request.body.slugs.map(slug => [slug, !denied.includes(slug)])),
    languages: Object.fromEntries(request.body.slugs.map(slug => [slug, [denied.includes(slug) ? 'en' : 'de']]))});
  return {episodes, series, state, model, checks, requests, respond, status, root, nodes};
}

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
