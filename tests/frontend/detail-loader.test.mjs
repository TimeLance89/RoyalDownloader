import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMovieDetailsLoader } from '../../web/js/features/media-details/movie-loader.js';
import { fetchMovieAvailability, freshMovieAvailability } from '../../web/js/features/media-details/movie-availability.js';
import { loadSeriesDetails } from '../../web/js/features/media-details/series-api.js';
import { createSeriesDetailsLoader } from '../../web/js/features/media-details/series-loader.js';

test('canonical Discovery TMDB series uses the existing detail resolver and cancellation', async () => {
  const signal = new AbortController().signal;
  for (const slug of ['tmdb:8001', 'people-tmdb:8001']) {
    const result = await loadSeriesDetails({ get: async (url, options) => {
      assert.match(url, /^\/api\/people\/series\/8001\?/);
      assert.equal(options.signal, signal);
      return { title: 'Discovery series', seasons: [] };
    }, post: () => assert.fail('TMDB identity must resolve through existing details') }, slug, slug, { signal });
    assert.equal(result.title, 'Discovery series');
  }
});

test('switching series stops old checks before waiting for the new provider', async () => {
  const events = [], noop = () => {};
  const state = { current: { base_slug: 'old' }, requestSeq: 0, viewGeneration: 0, cache: {} };
  const loader = createSeriesDetailsLoader({}, {}, {
    seriesState: state, cancelSeriesChecks: () => events.push('cancel old checks'),
    trackDiscoveryPreference: noop, updateSeriesResultSelection: noop,
    showSeriesLoading: () => { state.current = null; state.viewGeneration++; },
    openMediaModal: noop, findSeriesResultCard: () => null,
    client: { post(_url, _body, options) {
      events.push('request new provider');
      return new Promise((_resolve, reject) => options.signal.addEventListener('abort',
        () => reject(new DOMException('closed', 'AbortError')), { once: true }));
    } },
  });
  const result = { base_slug: 'new', sample_slug: 'new-s01e01', title: 'New series' };
  const pending = loader.open(result);
  assert.deepEqual(events, ['cancel old checks', 'request new provider']);
  await loader.open(result);
  assert.equal(events.length, 2, 'repeated click must retain the current request');
  loader.unmount();
  await pending;
});

test('series detail retries pending and busy responses and adopts the completed inventory', async () => {
  const requests = [], pauses = [];
  const signal = new AbortController().signal;
  const client = { async post(url, body, options) {
    requests.push({ url, body, options });
    if (requests.length < 3) throw Object.assign(new Error('preparing'), {
      status: 503, code: requests.length === 1 ? 'series_details_pending' : 'series_details_busy',
    });
    return { title: 'Fixture', availability_pending: false };
  } };
  const result = await loadSeriesDetails(client, 'episode', 'series', {
    signal, waitForRetry: async (ms, current) => { pauses.push(ms); assert.equal(current, signal); },
  });
  assert.equal(result.availability_pending, false);
  assert.deepEqual(pauses, [1000, 1000]);
  assert.equal(requests.length, 3);
  assert.ok(requests.every(row => row.url === '/api/series/load' && row.body.base_slug === 'series'
    && row.options.signal === signal));
});

test('closing series details stops pending retries before another request', async () => {
  const owner = new AbortController(); let requests = 0;
  const client = { async post() {
    requests++;
    throw Object.assign(new Error('pending'), { status: 503, code: 'series_details_pending' });
  } };
  await assert.rejects(loadSeriesDetails(client, 'episode', 'series', {
    signal: owner.signal, waitForRetry: async () => owner.abort(),
  }), { name: 'AbortError' });
  assert.equal(requests, 1);
});

test('series detail does not silently retry unrelated provider or authentication failures', async () => {
  for (const status of [401, 404, 503]) {
    const error = Object.assign(new Error('failed'), { status, code: 'unrelated_error' });
    let requests = 0;
    const client = { async post() { requests++; throw error; } };
    await assert.rejects(loadSeriesDetails(client, 'episode', 'series', {
      waitForRetry: async () => assert.fail('unexpected retry'),
    }), value => value === error);
    assert.equal(requests, 1);
  }
});

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function harness() {
  const requests = [], views = [], badges = [];
  const movieState = { selectedSlug: null, results: [], moviesCache: {}, metadataCache: {}, requestSeq: 0 };
  const noop = () => {};
  const client = Object.fromEntries(['get', 'post'].map(method => [method, (url, ...args) => {
    const request = { ...deferred(), url, options: args.at(-1) }; requests.push(request); return request.promise;
  }]));
  const loader = createMovieDetailsLoader({ movieState, client,
    resolveAvailability: options => fetchMovieAvailability({ ...options, pause: async () => {} }),
    updateFpResultSelection: noop, homeMovieBySlug: () => null, trackDiscoveryPreference: noop,
    showFpDetail: (slug, movie, loading) => views.push({ slug, movie, loading }),
    metadataPreviewMovie: movie => ({ ...movie, hosters: [] }), basicMovieMetadata: movie => ({ ...movie }),
    setFpDetailAvailability: (...args) => badges.push(args), openMediaModal: noop, findFpResultCard: noop,
    updateFpResultCard: noop, refreshMovieFeatureCandidates: noop, refreshFpJellyfinStatus: async () => {},
  });
  const item = id => ({ slug: `tmdb:${id}`, tmdb_id: id, title: `Movie ${id}`, description: 'Known recommendation', original_language: 'de' });
  return { loader, requests, views, badges, movieState, item };
}

test('similar movie starts provider independently of metadata and keeps rich metadata after failure', async () => {
  const h = harness(); const open = h.loader.open('tmdb:1', h.item(1));
  try {
    assert.equal(h.views[0].movie.description, 'Known recommendation');
    const provider = h.requests.find(r => r.url.startsWith('/api/movie/'));
    assert.ok(provider, 'provider must start without waiting for TMDB');
    h.requests.find(r => r.url === '/api/tmdb/movie').resolve({ movie: { ...h.item(1), description: 'Full TMDB', genres: ['Drama'], details_loaded: true } });
    provider.reject(new Error('Cloudflare 520 origin invalid response'));
    await open;
    assert.equal(h.views.at(-1).movie.description, 'Full TMDB');
    assert.deepEqual(h.views.at(-1).movie.genres, ['Drama']);
    assert.equal(h.views.at(-1).loading, false);
    assert.doesNotMatch(h.badges.at(-1)[0], /Cloudflare|origin/);
  } finally { h.loader.unmount(); }
});

test('late metadata cannot remove successful hosters; empty provider fields cannot erase metadata', async () => {
  const h = harness(); const open = h.loader.open('tmdb:2', h.item(2));
  try {
    const provider = h.requests.find(r => r.url.startsWith('/api/movie/'));
    assert.ok(provider);
    provider.resolve({ title: 'Movie 2', description: '', original_language: '', genres: [], hosters: [{ name: 'VOE' }] });
    await new Promise(resolve => setImmediate(resolve));
    h.requests.find(r => r.url === '/api/tmdb/movie').resolve({ movie: { ...h.item(2), description: 'Full TMDB', genres: ['Drama'], details_loaded: true } });
    await open;
    assert.equal(h.views.at(-1).movie.description, 'Full TMDB');
    assert.equal(h.views.at(-1).movie.hosters.length, 1);
    assert.equal(h.views.at(-1).loading, false);
  } finally { h.loader.unmount(); }
});

test('late old selection responses cannot overwrite next title, even when transport ignores abort', async () => {
  const h = harness(); const first = h.loader.open('tmdb:3', h.item(3));
  const old = [...h.requests];
  const second = h.loader.open('tmdb:4', h.item(4));
  try {
    assert.ok(old.every(r => r.options.signal.aborted));
    for (const r of h.requests.filter(r => !old.includes(r))) r.resolve(r.url === '/api/tmdb/movie' ? { movie: { ...h.item(4), details_loaded: true } } : { hosters: [{ name: 'VOE' }] });
    await second;
    const count = h.views.length;
    for (const r of old) r.resolve(r.url === '/api/tmdb/movie' ? { movie: h.item(3) } : { hosters: [] });
    await first;
    assert.equal(h.views.length, count);
    assert.equal(h.views.at(-1).slug, 'tmdb:4');
  } finally { h.loader.unmount(); }
});

for (const code of ['request_timeout', 'movie_hoster_unavailable']) test(`provider ${code} preserves metadata and next selection recovers`, async () => {
  const h = harness();
  try {
    const first = h.loader.open('tmdb:7', h.item(7));
    h.requests[0].resolve({ movie: { ...h.item(7), description: 'Full', details_loaded: true } });
    h.requests[1].reject(Object.assign(new Error('External technical error'), { code }));
    if (code === 'request_timeout') {
      for (let attempt = 0; attempt < 2; attempt++) {
        await new Promise(resolve => setImmediate(resolve));
        h.requests.at(-1).reject(Object.assign(new Error('Timeout'), { code }));
      }
    }
    await first;
    assert.equal(h.views.at(-1).movie.description, 'Full');
    assert.equal(h.movieState.detail.availabilityState, code === 'request_timeout' ? 'pending' : 'unavailable');
    assert.ok(h.requests[1].options.timeoutMs > 0 && h.requests[1].options.timeoutMs <= 20_000);
    const count = h.requests.length;
    const second = h.loader.open('tmdb:8', h.item(8));
    h.requests[count].resolve({ movie: { ...h.item(8), details_loaded: true } });
    h.requests[count + 1].resolve({ hosters: [{ name: 'VOE' }] });
    await second;
    assert.equal(h.movieState.detail.availabilityState, 'available');
    assert.equal(h.views.at(-1).movie.title, 'Movie 8');
    assert.equal(h.views.at(-1).movie.hosters.length, 1);
  } finally { h.loader.unmount(); }
});

test('open view adopts a late provider answer after pending status without reopening', async () => {
  const h = harness();
  try {
    const opened = h.loader.open('tmdb:9', h.item(9));
    h.requests[0].resolve({ movie: { ...h.item(9), details_loaded: true } });
    assert.match(h.requests[1].url, /progressive=true/);
    h.requests[1].resolve({ hosters: [], availability: { state: 'checking', complete: false } });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.movieState.detail.availabilityState, 'checking');
    assert.equal(h.views.at(-1).loading, true);
    assert.equal(h.requests.length, 3);
    h.requests[2].resolve({ hosters: [{ name: 'VOE' }], availability: { state: 'available', complete: true, expires_at: Date.now() / 1000 + 180 } });
    await opened;
    assert.equal(h.movieState.detail.availabilityState, 'available');
    assert.equal(h.views.at(-1).movie.hosters.length, 1);
  } finally { h.loader.unmount(); }
});

test('retrying movie availability states that provider search is still running', async () => {
  const h = harness();
  try {
    const opened = h.loader.open('tmdb:12', h.item(12));
    h.requests[0].resolve({ movie: { ...h.item(12), details_loaded: true } });
    h.requests[1].resolve({
      hosters: [],
      availability: { state: 'retrying', complete: false, retry_after_ms: 1200 },
    });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(h.badges.at(-1), ['Suche läuft weiter · Weitere Anbieter werden geprüft …', 'loading']);
    assert.equal(h.movieState.detail.availabilityState, 'checking',
      'a retrying probe must not be treated as an unavailable movie');
    h.requests[2].resolve({
      hosters: [{ name: 'VOE' }],
      availability: { state: 'available', complete: true, expires_at: Date.now() / 1000 + 180 },
    });
    await opened;
    assert.equal(h.movieState.detail.availabilityState, 'available');
  } finally { h.loader.unmount(); }
});

test('a usable source is rendered before enrichment finishes', async () => {
  const h = harness();
  try {
    const opened = h.loader.open('tmdb:10', h.item(10));
    h.requests[0].resolve({ movie: { ...h.item(10), details_loaded: true } });
    h.requests[1].resolve({ hosters: [{ name: 'VOE' }], availability: { state: 'available', complete: false, expires_at: Date.now() / 1000 + 1 } });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.movieState.detail.availabilityState, 'available');
    assert.equal(h.views.at(-1).loading, false);
    h.requests[2].resolve({ hosters: [{ name: 'VOE' }, { name: 'Other' }], availability: { state: 'available', complete: true } });
    await opened;
    assert.equal(h.views.at(-1).movie.hosters.length, 2);
  } finally { h.loader.unmount(); }
});

test('stale cached hosters trigger revalidation; an expired proof cannot enable downloads', async () => {
  const h = harness();
  try {
    const stale = { hosters: [{ name: 'Old' }], availability: { expires_at: Date.now() / 1000 - 1 } };
    assert.equal(freshMovieAvailability(stale), false);
    h.movieState.moviesCache['tmdb:11'] = stale;
    const opened = h.loader.open('tmdb:11', h.item(11));
    assert.equal(h.views[0].loading, true);
    assert.equal(h.views[0].movie.hosters.length, 0);
    h.requests[0].resolve({ movie: { ...h.item(11), details_loaded: true } });
    h.requests[1].resolve({ hosters: [{ name: 'Fresh' }], availability: { complete: true, expires_at: Date.now() / 1000 + 180 } });
    await opened;
    assert.equal(h.views.at(-1).movie.hosters[0].name, 'Fresh');
    assert.ok(freshMovieAvailability(h.movieState.moviesCache['tmdb:11']));
  } finally { h.loader.unmount(); }
});

test('exhausted pending budget remains unknown rather than unavailable', async () => {
  await assert.rejects(fetchMovieAvailability({ slug: 'slow', budgetMs: 0,
    client: { get: async () => { throw new Error('must not start'); } } }),
    error => error.code === 'movie_probe_pending');
});

test('download preparation can use a confirmed source while further sources are pending', async () => {
  let calls = 0;
  const movie = await fetchMovieAvailability({ slug: 'fast', firstAvailable: true,
    client: { get: async () => { calls++; return { hosters: ['ready'], availability: { complete: false } }; } } });
  assert.deepEqual(movie.hosters, ['ready']);
  assert.equal(calls, 1);
});

test('provider-only catalog hit retries with late TMDB identity inside the original deadline', async () => {
  const h = harness();
  try {
    const opened = h.loader.open('source-only', { slug: 'source-only', title: 'Movie' });
    assert.equal(h.requests.length, 2);
    h.requests[1].reject(Object.assign(new Error('Unavailable'), { code: 'movie_hoster_unavailable' }));
    h.requests[0].resolve({ movie: { tmdb_id: 42, title: 'Movie', description: 'Complete', details_loaded: true } });
    await new Promise(resolve => setImmediate(resolve));
    assert.match(h.requests[2].url, /tmdb_id=42/);
    assert.ok(h.requests[2].options.timeoutMs <= h.requests[1].options.timeoutMs);
    h.requests[2].resolve({ hosters: [{ name: 'VOE' }] });
    await opened;
    assert.equal(h.views.at(-1).movie.description, 'Complete');
    assert.equal(h.views.at(-1).movie.hosters.length, 1);
  } finally { h.loader.unmount(); }
});

test('series detail polling has a deadline even when the modal stays mounted', async () => {
  let calls = 0, elapsed = 0;
  const client = { async post() {
    calls += 1;
    throw Object.assign(new Error('still preparing'), {
      status: 503, code: 'series_details_pending',
    });
  } };
  const signal = new AbortController().signal;
  await assert.rejects(loadSeriesDetails(client, 'episode', 'series', {
    signal, now: () => elapsed,
    waitForRetry: async (ms) => { assert.equal(ms, 1000); elapsed += 18_000; },
  }), error => error.status === 503 && error.code === 'series_details_pending');
  assert.equal(calls, 2, 'must not start another request after the retry wait exhausts the deadline');
});

test('series detail HTTP timeouts cannot extend beyond the overall retry deadline', async () => {
  for (const slug of ['provider:show', 'tmdb:111']) {
    let elapsed = 0;
    const timeouts = [];
    const pending = Object.assign(new Error('pending'), { status: 503, code: 'series_details_pending' });
    const request = async (...args) => {
      const options = args.at(-1);
      timeouts.push(options.timeoutMs);
      elapsed += options.timeoutMs;
      throw pending;
    };
    await assert.rejects(loadSeriesDetails({ get: request, post: request }, slug, slug, {
      signal: new AbortController().signal, now: () => elapsed,
      waitForRetry: async ms => { elapsed += ms; },
    }), error => error === pending);
    assert.deepEqual(timeouts, [20_000, 14_000]);
    assert.equal(elapsed, 35_000);
  }
});

test('TMDB series detail uses the bounded progressive people endpoint', async () => {
  const result = await loadSeriesDetails({
    async get(url, options) {
      assert.match(url, /^\/api\/people\/series\/111\?/);
      assert.match(url, /progressive=true/);
      assert.match(url, /defer_checks=false/);
      assert.equal(options.timeoutMs, 20_000);
      return { seasons: [{ season: 1, episodes: [] }] };
    },
    post() { assert.fail('should not submit a provider slug that is only a TMDB identity'); },
  }, 'tmdb:111', 'tmdb:111');
  assert.equal(result.seasons.length, 1);
});
