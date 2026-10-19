// A trained, long-lived household profile; the neutral 24-card harness is not
// representative of Home ranking cost. No TMDB or real user data is used.
const { fixture } = require("./performance-fixture.cjs");
const { writeFileSync, mkdirSync } = require("node:fs");
const { resolve } = require("node:path");
const assert = require("node:assert/strict");

(async () => {
  const f = await fixture({ viewport: { width: 1920, height: 1080 } });
  try {
    const result = await f.page.evaluate(() => {
      const dimensions = { genres: { Drama: 18, Action: 12, Mystery: 8 }, media_types: { movie: 12, series: 8 } };
      for (const axis of ["actors", "directors", "tags", "studios", "franchises"]) {
        dimensions[axis] = Object.fromEntries(Array.from({ length: 120 }, (_, i) => [`${axis} ${i}`, 1 + i % 12]));
      }
      fixtureApp.profile.tasteProfile.accept({ dimensions, genres: dimensions.genres,
        home_preferences: { short_term: dimensions, by_media_type: { movie: dimensions, series: dimensions } },
        updated_at: Date.now() / 1000, interactions: 500, confidence: .9 });
      const movies = Array.from({ length: 500 }, (_, i) => ({
        slug: `trained-${i}`, tmdb_id: 100000 + i, title: `Film ${i}`, year: "2025", rating: 7 + i % 20 / 10,
        genres: [i % 2 ? "Drama" : "Action", "Mystery"],
        actors: [`actors ${i % 120}`], directors: [`directors ${i % 120}`], tags: [`tags ${i % 120}`],
        backdrop_url: "/fixture-art.svg", cover_url: "/fixture-art.svg", hosters: [],
      }));
      const data = fixtureApp.home.homeData.get();
      data.newMovies.splice(0, data.newMovies.length, ...movies);
      data.topMovies.splice(0, data.topMovies.length, ...movies.slice(0, 60));
      const days = {};
      for (let age = 1; age <= 21; age++) {
        const day = new Date(Date.now() - age * 86400000).toISOString().slice(0, 10);
        days[day] = { lanes: Object.fromEntries(["personal", "hero", "top", "genre", "gems", "explore"].map(lane =>
          [lane, movies.slice(age * 3, age * 3 + 80).map(movie => `movie:tmdb:${movie.tmdb_id}`)])) };
      }
      localStorage.setItem("royal-home-exposure-v2:performance-fixture", JSON.stringify({ version: 2, days }));
      const original = Storage.prototype.getItem;
      let reads = 0;
      Storage.prototype.getItem = function(key) { if (/royal-(home-exposure|discovery-profile)/.test(key)) reads++; return original.call(this, key); };
      const samples = [];
      try {
        for (let i = 0; i < 3; i++) {
          const before = performance.now();
          fixtureApp.home.actions.renderHome({ force: true });
          samples.push(performance.now() - before);
        }
      } finally { Storage.prototype.getItem = original; }
      return { candidates: movies.length, samples, storageReads: reads };
    });
    result.queue = await f.page.evaluate(() => {
      const count = 350;
      const payload = { count, groups: [{ name: "Active series", items: Array.from({ length: count }, (_, i) => ({
        job_id: `stress-${i}`, slug: `stress-s01e${i + 1}`, title: `Episode ${i + 1}`,
        job_status: i < 2 ? "downloading" : "queued", progress: i < 2 ? 20 : null,
        content_language: "de", provider: "SerienStream", hoster: "VOE",
      })) }], activity: { active_downloads: 2, pending_downloads: 348 }, providers: {} };
      fixtureApp.core.actions.renderQueue(payload);
      const home = document.getElementById("home-movies-track");
      let mutations = 0;
      const observer = new MutationObserver(records => { mutations += records.length; });
      observer.observe(home, { childList: true, subtree: true, attributes: true });
      const before = performance.now();
      for (let i = 0; i < 200; i++) fixtureApp.core.actions.updateQueueJobProgress("stress-0", { pct: i % 100, speed_bps: 5000000 });
      mutations += observer.takeRecords().length;
      observer.disconnect();
      return { jobs: count, updates: 200, elapsedMs: performance.now() - before, homeMutations: mutations };
    });
    console.log(JSON.stringify(result));
    const path = resolve(process.env.ROYAL_HOME_PERF_OUTPUT || "artifacts/home-personalization-performance/current.json");
    mkdirSync(require("node:path").dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(result, null, 2));
    assert.deepEqual(f.errors, []);
    if (process.env.ROYAL_HOME_PERF_VERIFY === "1") {
      assert.ok(result.storageReads <= 12, `ranking must share storage snapshots: ${result.storageReads} reads`);
      assert.ok(Math.max(...result.samples) < 1000, `a trained Home render must not freeze for seconds: ${result.samples}`);
      assert.equal(result.queue.homeMutations, 0, "download progress must not repaint Home");
      assert.ok(result.queue.elapsedMs < 1000, "200 progress updates must remain responsive with 350 jobs");
    }
  } finally { await f.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
