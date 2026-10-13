import { test } from "node:test";
import assert from "node:assert/strict";
import { queueArtwork, queueFocus, queueEpisode, queuePercent, queueStatus } from "../../web/js/features/downloads/presentation.js";

test("queue focus uses a real active job before the next planned item", () => {
  const items = ["queued", "preparing", "downloading", "downloading"].map((job_status, job_id) => ({ job_status, job_id: String(job_id) }));
  assert.equal(queueFocus([{ items }]).job_id, "2");
  assert.equal(queueFocus([{ items }], "3").job_id, "3");
  assert.equal(queueFocus([{ items }], "1").job_id, "2", "A previous preparing job cannot displace a running transfer");
  assert.equal(queueFocus([{ items: [items[0]] }]).job_id, "0");
  assert.equal(queueFocus([]), null);
  assert.equal(queueFocus([{ items: [{ job_status: "failed" }] }]), null);
});

test("unknown percentages never become a fabricated zero", () => {
  for (const value of [null, undefined, "", NaN, Infinity, -1, "unknown"]) assert.equal(queuePercent(value), null);
  assert.equal(queuePercent(0), 0);
  assert.equal(queuePercent(55.5), 55.5);
  assert.equal(queuePercent(200), 100);
  assert.equal(queueStatus({ done: true, job_status: "queued" }), "queued");
  assert.equal(queueStatus({ done: true, job_status: "downloading" }), "downloading");
  assert.equal(queueStatus({ done: true, job_status: "failed" }), "failed");
  assert.equal(queueStatus({ done: true }), "completed");
});

test("exact series identity selects series artwork and never an episode still", () => {
  const meta = { movieState: { moviesCache: {}, metadataCache: {} }, seriesState: {
    cache: { show: { backdrop_url: "/series.jpg", cover_url: "/poster.jpg" } }, results: [], current: null,
  }, homeMovie: () => null, homeSeries: () => null };
  const episode = { slug: "show-s02e007", backdrop_url: "/episode.jpg" };
  assert.deepEqual(queueEpisode(episode.slug), { base: "show", season: 2, episode: 7 });
  assert.deepEqual(queueArtwork(episode, meta, "https://royal.test"), ["https://royal.test/series.jpg", "https://royal.test/poster.jpg"]);
  delete meta.seriesState.cache.show;
  meta.seriesState.current = { base_slug: "different", backdrop_url: "/wrong.jpg" };
  assert.deepEqual(queueArtwork(episode, meta, "https://royal.test"), []);
});

test("movie artwork uses loaded metadata with bounded image resolution and safe fallbacks", () => {
  const meta = { movieState: { moviesCache: {}, metadataCache: { film: { backdrop_url: "https://image.tmdb.org/t/p/original/back.jpg", cover_url: "/poster.jpg" } } },
    seriesState: { cache: {}, results: [] }, homeMovie: () => null, homeSeries: () => null };
  assert.deepEqual(queueArtwork({ slug: "film" }, meta, "https://royal.test"), ["https://image.tmdb.org/t/p/w500/back.jpg", "https://royal.test/poster.jpg"]);
  meta.movieState.metadataCache.film = { backdrop_url: "javascript:alert(1)", cover_url: "/poster.jpg" };
  assert.deepEqual(queueArtwork({ slug: "film" }, meta, "https://royal.test"), ["https://royal.test/poster.jpg"]);
  assert.deepEqual(queueArtwork(null, meta, "https://royal.test"), []);
});
