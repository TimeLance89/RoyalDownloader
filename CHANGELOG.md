# Changelog

## Unreleased

- Fix the mobile bottom navigation so it spans the viewport, respects device
  safe areas, and distributes all currently visible tabs evenly without a
  five-column wrap conflict.

## v1.0.0-rc.2 – 2026-08-02

- Add persistent **Stable** (`main`) and **Overnight** (`overnight`) update
  channels while keeping Stable as the backward-compatible default.
- Keep the existing exact-commit staging, backup, restart, and rollback path
  for both channels; require explicit confirmation when returning to Stable
  may activate an older or diverged build.
- Show channel, branch, application version, installed build, available build,
  and development/downgrade warnings in the update UI and API.
- Run the complete quality workflow for both branches and require official
  release commits to be contained in `main`.
- Offer an Overnight commit only after the complete Quality workflow has
  succeeded for that exact revision; missing, pending, or failed results remain
  unavailable.
- Classify releases from their semantic tag: release candidates and other
  hyphenated versions are pre-releases, while stable versions are no longer
  marked as pre-releases unconditionally.
- Make tag and Release creation idempotent in the same quality-gated workflow;
  GitHub-token tag pushes intentionally do not rely on recursively starting a
  second workflow.

This is a **release candidate**, not the final `v1.0.0` release. External
providers may change pages, domains, availability, or protection mechanisms at
any time.

## v1.0.0-rc.1 – 2026-08-02

- Publish the first officially versioned Royal Downloader release candidate.
- Establish the modular backend and frontend architecture as the documented
  release baseline while preserving legacy, `/api/v1`, and WebSocket contracts.
- Document reproducible Docker and NAS installation, persistent `data/` and
  `runtime/` storage, backup, update, and rollback procedures.
- Retain persistent queue recovery across container and application restarts.
- Include the existing Jellyfin, TMDB, Telegram, and Seerr integrations.
- Include ordered provider fallbacks, persistent provider health states, and
  controlled retries for temporarily unavailable sources.
- Include the existing authentication, path, dependency, update, and runtime
  hardening together with automated tests and CI validation.
- Include the fast Jellyfin movie identity index so movie availability checks
  no longer wait for the full media-quality library payload.

This is a **release candidate**, not the final `v1.0.0` release. External
providers may change their pages, domains, availability, or protection
mechanisms at any time; the release cannot guarantee uninterrupted access to
third-party sources.

## 2026-08-02 – Modularization safety baseline

- Reduced `server.py` from 13,394 lines to a sub-800-line composition root by
  extracting thirteen focused application-service modules while retaining all
  established integration and test seams.
- Keep the home-page series rail populated from other active providers when
  SerienStream trending data is unavailable because of a CAPTCHA or rate limit.
- Extracted the HTTP authentication, origin-validation, and response-hardening
  policy from `server.py` behind an injected application boundary.
- Moved the web and native authentication endpoints into an independently
  tested router while retaining all legacy and `/api/v1` contracts.
- Extracted the first-run setup routes and persistent media-path validation,
  including recovery of completed files from unsafe container locations.
- Split the monolithic browser application into ordered core, feature-screen,
  account, setup, and bootstrap modules with a load-order regression check.
- Replaced the monolithic stylesheet with an ordered manifest of focused base,
  legacy-layer, screen, and media override stylesheets.
- Moved process state, cache ownership, provider singletons, and lock ownership
  from `server.py` into a dedicated `app_state.py` component.
- Extracted bounded WebSocket delivery and added ordering and slow-client
  regression tests.
- Extracted the authenticated WebSocket handshake, origin checks, aliases, and
  initial snapshot from the composition root without changing client contracts.
- Moved movie, series, anime, TMDB metadata, and targeted Jellyfin discovery
  endpoints into their production domain router while preserving flat route
  diagnostics and both API aliases.
- Extracted taste-profile, queue lifecycle, preparation, removal, and download
  cancellation into the queue domain router without changing internal callers.
- Extracted the cover proxy, film subscriptions, series watchlist, watched-state
  reconciliation, and automatic library cleanup into a library domain router.
- Extracted updater, setup transaction, storage, provider, Jellyfin, TMDB,
  automation, Telegram, and Seerr configuration into an administration router.
- Added regression checks for unique API route ownership, duplicate HTML IDs,
  mobile catalog pagination, and JavaScript files in nested frontend modules.
- Added enforceable module-size boundaries and prevented HTTP endpoints from
  drifting back into the `server.py` composition root.
- Added a consolidated modularization guide covering ownership, compatibility,
  extension rules, validation, and deployment impact.

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

Older entries below record the continuous `main` history that preceded the
first versioned release candidate.

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
