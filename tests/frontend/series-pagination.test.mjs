import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSeriesBrowse } from '../../web/js/features/discovery/series-browse.js';
import { createCatalogSeed } from '../../web/js/features/discovery/catalog-seed.js';
import { readFileSync } from 'node:fs';

function fixture(responses, waitForRetry = async () => {}) {
  const nodes = new Map();
  const node = () => Object.assign(new EventTarget(), { value: '', children: [], replaceChildren() { this.children=[]; }, appendChild(child) { this.children.push(child); } });
  const root = { ownerDocument: { createElement: node }, querySelector(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); } };
  const state = { results: Array.from({length:32}, (_,i)=>({base_slug:`series-${i}`})), sources:[], browseMode:'discover', page:1, lastPageFull:true, browseRequestSeq:0, epPicked:new Set(), loadError:'' };
  const calls=[]; const applied=[]; const noop=()=>{};
  const browse=createSeriesBrowse(root,{ seriesState:state, getActiveTab:()=> 'serien', waitForRetry,
    syncSearchClearButtons:noop,closeSearchSuggestions:noop,rememberSearch:noop,renderSeriesTiles:noop,
    updateSeriesInfiniteState:noop,showSeriesDetail:noop,firstEpisodeSlug:noop,updateSeriesStatus:noop,
    refreshSeriesJellyfinStatus:noop,recheckSeriesInfinite:noop,preloadSeriesPosterImages:noop,
    syncSeriesCatalogFromHome:noop,renderSeriesResults:noop,refreshSeriesCatalogInBackground:noop,
    applySeriesResults(data) { applied.push(data); state.results.push(...data.results); state.page=data.page; state.lastPageFull=data.has_more; state.loadError=''; },
    client:{ async get(url,options) { calls.push({url,options}); const result=responses.shift(); if (result instanceof Error) throw result; return result; } },
  });
  browse.mount(); return {browse,state,calls,applied};
}
const pending=()=>Object.assign(new Error('Dieser Serienabschnitt wird vorbereitet'),{status:409,code:'series_catalog_pending'});
const page2={page:2,has_more:false,results:[{base_slug:'series-32'}]};

test('series pagination retries preparing page without skipping or losing the first 32 cards',async()=>{
  const h=fixture([pending(),page2]);
  try { await h.browse.next(); assert.equal(h.calls.length,2); assert.ok(h.calls.every(call=>call.url.includes('page=2'))); assert.equal(h.state.results.length,33); assert.equal(h.state.page,2); assert.equal(h.state.loadError,''); } finally {h.browse.unmount();}
});

test('transient series failure retries are bounded; scrolling stops until explicit retry',async()=>{
  const h=fixture([pending(),pending(),pending(),page2]);
  try { await h.browse.next(); assert.equal(h.calls.length,3); assert.equal(h.state.page,1); assert.equal(h.state.results.length,32); assert.ok(h.state.loadError); await h.browse.next(); assert.equal(h.calls.length,3); await h.browse.next({retry:true}); assert.equal(h.state.results.length,33); } finally {h.browse.unmount();}
});

test('leaving series during retry backoff prevents another request',async()=>{
  let resume,started; const waiting=new Promise(resolve=>{started=resolve;});
  const h=fixture([pending(),page2],async()=>{started(); await new Promise(resolve=>{resume=resolve;});});
  const load=h.browse.next(); await waiting;
  h.browse.unmount(); resume?.(); await load;
  assert.equal(h.calls.length,1); assert.equal(h.applied.length,0); assert.equal(h.calls[0].options.signal.aborted,true);
});

for (const failure of [Object.assign(new Error('Offline'), {code:'network_error'}), Object.assign(new Error('Unavailable'), {status:503})]) {
  test(`series pagination recovers from ${failure.code || failure.status}`, async()=>{
    const h=fixture([failure,page2]);
    try { await h.browse.next(); assert.equal(h.calls.length,2); assert.equal(h.state.page,2); } finally {h.browse.unmount();}
  });
}

test('permanent request errors are not retried',async()=>{
  const h=fixture([Object.assign(new Error('Invalid request'),{status:400})]);
  try { await h.browse.next(); assert.equal(h.calls.length,1); assert.equal(h.state.page,1); assert.equal(h.state.results.length,32); assert.ok(h.state.loadError); } finally {h.browse.unmount();}
});


test('series catalog seeds only one 32-card page from the warmed Home reservoir', () => {
  const reservoir = Array.from({ length: 220 }, (_, index) => ({
    base_slug: `series-${index}`,
    title: `Series ${index}`,
  }));
  const seriesState = {
    results: [], sources: [], browseMode: null, page: 1, lastPageFull: false,
    loadingBrowse: false, loadError: '', previewFromHome: false, lastCatalogRefreshAt: 0,
  };
  let rendered = 0;
  const seed = createCatalogSeed({
    movieState: { results: [], metadataCache: {} },
    seriesState,
    getActiveTab: () => 'serien',
    getHomeData: () => ({ newMovies: [], discoverySeries: reservoir }),
    mergeFpMetadata: (_old, value) => value,
    fpMetadataPreloadItems: () => [],
    preloadTmdbMetadata() {},
    renderFpResults() {},
    refreshMovieFeatureCandidates() {},
    updateFpInfiniteState() {},
    recheckFpInfinite() {},
    renderSeriesResults() { rendered += 1; },
    renderSeriesCatalogHero() {},
    updateSeriesInfiniteState() {},
    recheckSeriesInfinite() {},
  });

  assert.equal(seed.series(), true);
  assert.equal(seriesState.results.length, 32);
  assert.equal(seriesState.results[0].base_slug, 'series-0');
  assert.equal(seriesState.results.at(-1).base_slug, 'series-31');
  assert.equal(reservoir.length, 220);
  assert.equal(rendered, 1);
});

test('series presentation checks Jellyfin only for the newly applied page', () => {
  const source = readFileSync(
    new URL('../../web/js/features/discovery/series-presentation.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /refreshCatalogJellyfinStatus\(incoming\.map\(homeSeriesEntry\)/);
  assert.doesNotMatch(source, /refreshCatalogJellyfinStatus\(seriesState\.results\.map\(homeSeriesEntry\)/);
  const applyBody = source.split('function applySeriesResults', 2)[1]
    .split('function seriesStructureFingerprint', 1)[0];
  assert.doesNotMatch(applyBody, /recheckSeriesInfinite\(\)/);
});
