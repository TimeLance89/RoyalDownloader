# Changelog

## 2026-08-02 – Modularization safety baseline

- Extracted the HTTP authentication, origin-validation, and response-hardening
  policy from `server.py` behind an injected application boundary.
- Moved the web and native authentication endpoints into an independently
  tested router while retaining all legacy and `/api/v1` contracts.
- Extracted the first-run setup routes and persistent media-path validation,
  including recovery of completed files from unsafe container locations.
- Split the monolithic browser application into ordered core, feature-screen,
  account, setup, and bootstrap modules with a load-order regression check.
- Added regression checks for unique API route ownership, duplicate HTML IDs,
  mobile catalog pagination, and JavaScript files in nested frontend modules.

## 2026-08-01 – Legacy updater migration fix

- Unblocked dependency-bearing updates from revision `6457b78d` by preserving
  its dependency compatibility sentinel separately from the reviewed lockfile.
- Migrate mounted-folder Docker installations to the persistent, versioned
  runtime on restart so subsequent updates are isolated, smoke-tested, and
  rollback-capable.
- Reconcile restored episode queues against the same targeted Jellyfin series
  lookup as the detail view, removing already-owned episodes before resuming.
- Reject media destinations in Docker's ephemeral container layer, prefer the
  configured persistent movie/series mounts, and recover completed media from
  an unsafe legacy path without deleting the original files.
- Restore automatic catalog pagination on mobile by observing document scrolls
  for both the movie and series tabs in addition to desktop tab scrolling.

## 2026-08-01 – Runtime hardening and modularization

- Bound all long-lived discovery, media-validation, path, and targeted
  Jellyfin caches with TTL/LRU eviction, active-item pinning, maintenance, and
  content-free diagnostics.
- Move persistence-heavy async API work to worker threads and add event-loop
  responsiveness regression tests.
- Pin the resolved Python runtime, Python/Seerr image versions, disable
  unreviewed yt-dlp mutation by default, and verify explicitly enabled yt-dlp
  updates against PyPI SHA-256 metadata.
- Expand CI with all-JavaScript syntax checks, frontend contract smoke tests,
  incremental Ruff/Bandit checks, dependency audit, and coverage artifacts.
- Extract the system API router, frontend store, and CSS design-token layer;
  document service boundaries and lock ownership for further extraction.

This file records user-visible Royal Downloader changes. The project currently
ships continuously from `main`; entries are therefore grouped by date instead
of a separately maintained release version.

## 2026-08-01

### Reliability and security

- Hardened the public translation endpoint with bounded request payloads,
  work-unit rate limiting, a fixed client-tracking cap, and one global outbound
  concurrency budget.
- Made generated media names portable across NAS, Linux, and Windows filesystems
  and prevented finalization from overwriting an existing media file.
- Clarified that the Android client source is maintained separately and added a
  CI-backed check for broken relative documentation links.

### Providers and routing

- Added **Huhu** as a German provider for movies and series.
- Set the default German movie order to start with **Filmpalast**, followed by
  **Huhu**. **FilmFrei24** now comes last in the movie fallback chain.
- Kept **SerienStream** as the primary German series source. Huhu is available
  as the first fallback, followed by Moflix, MegaKino, and Filmpalast.
- Added persistent SerienStream health states with increasing cooldowns,
  restart-safe waiting episodes, a single controlled recovery probe, and a
  manual one-shot retry. CAPTCHA and rate-limit responses are respected; no
  automated CAPTCHA solving or protection bypass is used.
- Improved exact cross-provider series, season, and episode matching and cached
  fallback discovery so unavailable providers do not stall every queued item.

### Queue and downloads

- Movie jobs are no longer held behind a paused series backlog and can start as
  soon as a transfer slot is available.
- Provider searches and episode preparation no longer occupy active download
  slots unnecessarily. Already resolved transfers continue in parallel.
- Queue entries now distinguish provider waiting, preparation, and active file
  transfer more clearly in the download plan and progress display.

### Jellyfin and subscriptions

- Series details now query only the matched Jellyfin series instead of waiting
  for the complete episode library index.
- Added provider-independent subscription matching using stable TMDB IDs,
  titles, and aliases. A series opened through another provider therefore keeps
  its existing subscription state.
- Added short-lived targeted Jellyfin caches with immediate invalidation after
  library updates, configuration changes, and Jellyfin deletions.
- A failed live check preserves the last known result as explicitly stale
  instead of presenting it as current or silently allowing duplicate downloads.
- Added `/api/series/jellyfin-status` and its authenticated mobile v1 alias for
  fast native and web detail updates.

### Personalization

- Added one private, cross-device taste profile shared by the web interface and
  native clients.
- The profile learns from discovery, detail views, downloads, subscriptions,
  explicit positive/negative feedback, and Jellyfin playback history.
- Added profile inspection and reset controls plus API endpoints for native
  clients. Personalization data remains stored on the self-hosted instance.

### Validation

- Added regression coverage for provider-independent subscriptions, ambiguous
  title protection, targeted Jellyfin queries, caching, and API aliases.
- The completed 2026-08-01 state passed the full automated suite with **75
  tests** plus Python and JavaScript syntax checks.
