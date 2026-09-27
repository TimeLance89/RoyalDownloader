import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSeriesBrowse } from '../../web/js/features/discovery/series-browse.js';

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
