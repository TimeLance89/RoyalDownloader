# Changelog

## Unreleased

- Film- und Seriendetails erhalten im einheitlichen Royal-Aktenstil eigene
  Bereiche für ähnliche Titel, offizielle Trailer und kompakte
  Produktionsinformationen; Empfehlungen verwenden ausschließlich breite
  16:9-Hintergründe.
- Ähnliche Serien öffnen direkt die vollständige Serienakte mit unverändertem
  Staffel- und Episodenbrowser; beim Schließen bleibt der zuvor aktive Kalender
  erhalten.
- Laufende Hero-Trailer in Film- und Seriendetails pausieren automatisch,
  sobald der Kopfbereich aus dem sichtbaren Ausschnitt gescrollt wird, und
  setzen beim Zurückscrollen fort.
- Aus dem Kalender geöffnete Seriendetails bleiben als Modal über dem Kalender; Schließen führt nicht mehr in die Serienübersicht.
- Fertig geladene Kalenderdaten blenden den vorbereitenden Statusblock nun zuverlässig aus; die Kalender-CSS respektiert `hidden` auch gegen ihre eigenen Grid-Regeln.
- Der Kalender beendet den Ladezustand nun auch bei gemischten Browser-Assets und gedrosselten Hintergrund-Timern sicher; ein zweiter Fristwächter fängt hängende Altzustände ab.
- Die Startseite verwendet außerhalb der Top 10 ausschließlich 16:9-Hintergründe, füllt „Aus deinen Klicks und Downloads“ auf bis zu 16 Titel auf und hält beim Aktualisieren die einmal geladenen Karten stabil im DOM.
- Der Serienkalender wird vollständig serverseitig über eine unabhängige SerienStream-Session synchronisiert. Ein atomar gespeicherter, validierter Snapshot übersteht Neustarts und Ausfälle; der Browser ruft die Kalenderdaten nie direkt vom Fremddienst ab.
- Die Kalenderoberfläche besitzt klar begrenzte Abrufe, einen harten Lade-Wächter und abschließende Erfolgs-, Offline- oder Wiederholen-Zustände. Dadurch kann kein dauerhafter Ladehinweis mehr stehen bleiben.
- Die Serienübersicht startet den Jellyfin-Liveabgleich für die komplette erste Katalogseite sofort und unabhängig von Postern/TMDB. Doppelte Serien mit widersprüchlichen Staffel-Jahresangaben werden bei identischem Titel und überlappender Quelle zusammengeführt.

- Preserve each home carousel's horizontal scroll position when progressive
  artwork, Jellyfin status, or discovery data triggers a background rerender.
- Persist the intended carousel target before smooth scrolling begins and bump
  the affected browser asset versions so cached clients receive the fix.
- Keep unchanged carousel sections and cards mounted during background updates;
  only actually changed cards are reconciled, eliminating the visible jump to
  zero and the subsequent snap-back.
- Add a dedicated top-level series calendar with week navigation, day jumps,
  title and language filters, subscription-only mode, direct provider artwork,
  release status, and one-click handoff into the regular series workflow.
- Validate and cache SerienStream calendar data server-side, retain the last
  valid snapshot during short outages, and reject foreign series or image URLs.

## 2026-08-23 – Custom home programme

- Add a visual start-page editor with live preview, drag-and-drop ordering,
  keyboard controls, per-row visibility, optional hero visibility, reset, and
  server-side persistence shared by authenticated browsers.
- Expand the available programme from seven fixed rows to twelve selectable
  carousels, including dedicated new-film, new-series, highly rated, movie-night,
  and Jellyfin-library rows while preserving the established default layout.
- Prioritize artwork hydration in the user's visible row order, load visible
  images eagerly, and show provider posters in a framed fallback treatment until
  wide artwork becomes available.

## 2026-08-23 – AniWorld archive, faster catalogs, and production-only setup

### AniWorld archive and downloads

- Add AniWorld as a dedicated German anime provider and a first-class top-level
  workspace instead of mixing it into the regular movie and series views.
- Enable AniWorld automatically for existing German installations while
  retaining its provider visibility and settings when English sources are
  disabled.
- Cover the complete AniWorld A–Z catalog on the archive start page with
  infinite loading, title search, letter and genre facets, deduplication, and
  dedicated views for new episodes, new anime, trending, and popular titles.
- Keep the compact discovery views bounded to 22 entries while the A–Z archive
  remains fully browsable without page-by-page navigation.
- Use only artwork hosted by AniWorld for AniWorld cards and details, hydrate
  missing posters in bounded batches, cache successful results, and reject
  external poster hosts.
- Add complete anime metadata, language-track selection, seasons, episode
  titles, hoster availability, companion movies as Season 0, per-episode
  selection, whole-season selection, and direct queue handoff.
- Simplify long-running series navigation to one selected season at a time and
  return complete season episode sets without exposing internal pagination to
  the user.
- Preserve the selected language track and season through detail and hoster
  resolution, and include AniWorld in the established fallback and provider
  health infrastructure.
- Store AniWorld episodes with the same clean series, season, and episode
  naming convention as other series instead of embedding provider and language
  identifiers in Jellyfin titles.

### Catalog and Jellyfin responsiveness

- Stream series artwork and visible catalog content before targeted Jellyfin
  availability checks finish so library status cannot delay the first render.
- Await movie Jellyfin readiness once per download decision, reuse the live
  state, and keep duplicate-download protection consistent across the catalog
  and queue boundary.
- Add regression coverage for delayed artwork, stale Jellyfin state, series
  queue circuit breaking, complete AniWorld catalogs, official poster origin,
  language tracks, long-running series, and portable download names.

### Deployment cleanup

- Remove the Demo deployment mode, simulated download pipeline, and all related
  setup, settings, storage, automation, environment, and runtime branches.
- Migrate legacy Demo configurations to Desktop mode and require real media
  paths before downloading, leaving Regular computer and NAS / home server as
  the supported deployment choices.

## v1.0.0 – 2026-08-21

RoyalDownloader 1.0.0 promotes the reviewed RC line and the subsequent
Overnight hardening work to Stable. The release keeps the existing HTTP,
`/api/v1`, WebSocket, Docker-volume, queue, and update-channel contracts while
adding fail-closed authentication, protected first-run ownership, hardened
unprivileged containers, persistent queue/restart recovery, browser isolation,
storage orchestration, and the complete Jellyfin, Telegram, Seerr, and Moonfin
integration set documented below.

Stable promotion is gated by the complete Quality and CodeQL workflows,
including container build and CVE scan, browser/runtime smoke tests, first-run
and web/mobile authentication boundaries, queue persistence, media integration,
and RC3 upgrade, rollback, backup, and recovery verification. See
[`docs/releases/v1.0.0.md`](docs/releases/v1.0.0.md) for installation and
operational notes.

## 2026-08-21 – Smart automation, storage orchestration, search, and provider resilience

### Automation and NAS load control

- Expand unattended automation from a single interval and hour window into a
  NAS-aware policy engine with independent weekday/weekend schedules, live
  limits of one to four parallel downloads, a configurable aggregate bandwidth
  budget, and a minimum-free-space guard for new automatic work.
- Detect active, non-paused Jellyfin playback and optionally reduce Royal's
  transfer budget while somebody is streaming so background downloads are less
  likely to compete with media playback.
- Add a dedicated nighttime policy for automatic movie-quality upgrades while
  keeping manual subscription checks available outside that window.
- Preserve existing automation settings and legacy API behavior while adding
  `/api/automation/policy` and `/api/v1/automation/policy` as the richer policy
  contract.
- Replace raw numeric hour controls with a friendlier schedule editor: weekdays
  use **Any time**, **Night only**, or **Custom times**; weekends use **Any
  time**, **Same as weekdays**, or **Custom times**. Custom schedules and movie
  upgrade windows use clock-style `HH:MM` inputs while the existing whole-hour
  backend semantics remain unchanged.
- Prevent the 15-second live policy refresh from overwriting schedule or load
  settings that the user is still editing but has not saved yet.

### Storage management and safe moves

- Add live storage telemetry and a Smart Scan for unusually large movies,
  series, and folders, with signed short-lived cleanup approvals, revalidation
  before deletion, and protections against path traversal, symlinks, changed
  files, and active Royal staging data.
- Add persistent multi-volume storage management for up to twelve additional
  locations, distinguish read-only **Monitor** locations from writable **Media**
  locations, show offline mounts explicitly, and deduplicate capacity for paths
  that point to the same physical filesystem.
- Add guarded moves between storage volumes: films move as individual media
  files, series move as complete series folders, and Royal blocks same-volume
  moves, overlapping paths, collisions, insufficient target space, monitor-only
  destinations, and overwrites.
- Run storage moves as visible persistent background jobs with a serial NAS-I/O
  worker, active-job locking, status/history UI, and automatic storage/scan
  refresh after completion.
- Make large cross-volume moves restart-safe with deterministic partial paths,
  chunked copying, byte-offset resume for interrupted files, skipping of already
  complete files, destination verification before source deletion, and
  idempotent recovery if a crash happens after publishing the destination.
- Safely adopt older interrupted move jobs only when their source, destination,
  and partial data can be matched unambiguously; otherwise fail closed without
  deleting source media or persisting sensitive scan tokens.

### Search, catalogs, and media details

- Make movie search provider-first: every enabled provider remains a source of
  visible results, while TMDB enriches metadata and helps conservative
  deduplication instead of limiting the provider result set.
- Keep provider hits visible without loading detail/hoster pages during the
  search request. Resolve the selected source lazily when a title is opened or
  queued, try the explicitly chosen provider first, and then fall back through
  the remaining configured sources.
- Remove the inappropriate 15-second browser timeout from provider-wide movie
  searches while retaining bounded catalog browsing, and make global movie,
  series, and anime search progressive so fast catalogs appear while slower
  catalogs continue in the background.
- Show pending and partial-failure state instead of silently dropping a slow
  catalog, avoid a premature empty result while another catalog is still
  running, and start thumbnails immediately for cards that have actually been
  rendered.
- Deduplicate global search results by content identity rather than technical
  provider slugs, repeat the deduplication after metadata hydration, and keep
  the query, filters, results, and scroll position intact while a movie, series,
  or anime detail modal is open above the search page.
- Stabilize season/detail loading and preserve already rendered catalog content
  while slower background refreshes finish, reducing flicker and misleading
  intermediate states.

### SerienStream session reliability

- Follow SerienStream's normal HTTP redirect chain for successful `/r?t=`
  resolutions and accept only a final external embed URL as success; provider
  gate, rate-limit, and Turnstile pages remain explicit blocked states.
- Add an authenticated, user-driven browser verification flow backed by a real
  Chromium profile. Royal can display the browser viewport, forward the user's
  own click/scroll gestures, persist resulting cookies, and retry the original
  redirect without implementing an automated CAPTCHA or Turnstile solver.
- Integrate the persistent browser profile into the normal SerienStream session
  path: HTTP and Chromium share the same Chrome identity, HTTP cookies are
  seeded into the browser, and browser cookies are synchronized back into the
  live and persistent SessionManager.
- Retry a blocked episode page or matching hoster action through that shared
  browser session before marking SerienStream unavailable; if an interactive
  challenge still remains, Royal reports it instead of synthesizing a bypass.
- Harden provider URL validation and serialized profile ownership, and extend
  the final Docker smoke tests so both verification and shared-session Chromium
  runtimes are exercised in the built image.

### Updates, UI, and quality

- Harden Stable/Overnight revision comparison when GitHub's compare endpoint
  returns a transient 404 by using bounded parent/ancestry checks; retain a
  fail-safe `unknown` result when history cannot be proven instead of guessing
  a dangerous downgrade/divergence state.
- Extend the administration and storage UI with live status for background
  work, responsive controls, clearer loading/error states, keyboard focus
  handling, and cache revisions for the new runtime modules.
- Expand regression coverage for storage safety and resume, provider-first and
  progressive search, SerienStream session ownership, smart automation,
  schedule UX, and update comparison behavior.
- Expand Bandit/security coverage to the new automation, storage, browser
  session, and move-runtime modules while retaining the complete Python/JS
  syntax, frontend contract, dependency-audit, Docker Compose, test/coverage,
  image-build, browser-runtime, fresh-start, persistence, and restart gates.

## 2026-08-11 – Instant catalogs, immediate artwork, and Jellyfin throughput

- Make movie and series catalogs appear almost immediately by enforcing bounded
  provider deadlines, returning partial pages safely, caching series discovery,
  and continuing slow source work without blocking browsing or infinite scroll.
- Show provider artwork as soon as a title arrives across all twelve movie
  adapters, then replace it unobtrusively with decoded TMDB artwork when richer
  metadata becomes available; keep existing cards stable during the swap.
- Replace repeated full-catalog Jellyfin checks with a deduplicated incremental
  queue that checks only new or metadata-refined titles in bounded batches.
- Build the Jellyfin movie identity index once per batch instead of rescanning
  and renormalizing the complete library for every title, allowing ownership
  badges to keep pace with the faster catalog.
- Harden deep pagination, title/year/TMDB identity resolution, slow-provider
  recovery, browser-pool cleanup, and provider-specific poster extraction while
  preserving already visible results when a source misses its response budget.
- Split catalog and trailer runtime work into focused frontend modules, refresh
  cache revisions, and expand regression coverage for deadlines, provider
  artwork, Jellyfin matching, metadata hydration, and idle browser cleanup.

## 2026-08-10 – NAS updates, persistence, and settings workspace

- Add a first-run Demo mode that requires no media paths and visibly simulates
  queue, progress, verification, and completion without downloading streams,
  creating staging directories, writing media files, or triggering delivery
  side effects such as Jellyfin scans; automatic downloading remains disabled
  so a demonstration cannot grow its history unattended.
- Replace the previous NAS update path with a portable update bundle, verified
  runtime activation, safe legacy-container cutover, persistent rollback data,
  and exact revision checks against the process that is actually serving the
  application.
- Preserve existing `.env`, account, subscription, queue, session, and settings
  data across copied deployments and container recreation; validate writable
  Docker mounts without rejecting intentionally mapped external movie or series
  volumes.
- Keep Stable and Overnight selections persistent, report the installed and
  available revisions accurately, and prevent an update from being reported as
  complete until the requested revision is active.
- Rebuild Settings as a responsive system workspace with a dedicated overview,
  separate operating, source, service, automation, access, and maintenance
  views, clearer media-service grouping, and guarded persistent save actions.
- Reduce NAS image build context by excluding media, runtime, cache, backup, and
  generated data while expanding regression coverage for updates, persistence,
  Docker startup, frontend contracts, accessibility, and deployment safety.

## 2026-08-09 – Discovery, library, downloads, and updater hardening

- Make the Top 10 a strictly daily, cross-source ranking; merge provider-tagged
  duplicates through TMDB and title/year aliases, discard stale snapshots, and
  exclude raw, artwork-less, or otherwise incomplete candidates.
- Correct Jellyfin availability for lazy-loaded catalog pages and ambiguous
  same-title releases by using stable TMDB, title, and year identities; hide
  download actions for content already present in Jellyfin.
- Prevent movie quality subscriptions from repeatedly downloading an equal or
  inferior file by validating the delivered media, persisting attempted source
  signatures, and committing replacements only after a real upgrade.
- Treat unreleased series episodes as scheduled instead of failed, avoid retry
  storms for unavailable providers, recognize already complete libraries, and
  exclude Season 0 specials from subscription and missing-episode workflows.
- Redesign catalog-card hover details without changing the compact resting
  layout and keep Jellyfin status checks bounded and responsive.
- Harden Stable/Overnight switching, GitHub-token loading, cross-channel build
  detection, manually copied NAS runtime activation, bootstrap isolation, and
  immediate persistence of the selected update channel.
- Keep `FireTVApp` outside repository commits and expand regression coverage
  across discovery, Jellyfin, subscriptions, runtime activation, and updates.

## 2026-08-08 – Royal Cinema branding

- Replace the previous text-only header mark with the transparent Royal Cinema
  wordmark asset and preserve the existing accessible brand text in the DOM.
- Add a dedicated, responsive brand stylesheet with desktop, tablet, mobile,
  and narrow-phone sizing so the full wordmark remains visible without
  clipping or wrapping.
- Integrate the logo stylesheet into the central frontend manifest and add
  explicit cache-busting revisions for both stylesheet and image assets.
- Preserve the existing hover styling contract and disable the decorative logo
  shadow when reduced motion is requested.
- Add frontend regression coverage for asset format and dimensions, stylesheet
  wiring, responsive sizing, cache-busting URLs, and accessible brand labels.

## v1.0.0-rc.3 – 2026-08-05

- Introduce persistent logical download jobs with stable `job_id` values,
  atomic queue/history snapshots, restart recovery, per-job REST controls, and
  additive WebSocket job identity while retaining all slug-based contracts.
- Add unique execution `attempt_id` values, a durable `cancelling` state,
  retry blocking until worker completion, stale-callback protection, and
  attempt-specific staging directories.
- Retain the latest 500 completed, failed, or cancelled jobs and expose
  progress, bytes, speed, ETA, retry, cancellation, and ordering in the web UI.
- Add Mood Mode, global movie/series/anime search, daily Top 10 rotation,
  expanded discovery lanes, Royal Archive search, and improved family-safe
  recommendations.
- Preserve future episode release metadata, show scheduled episodes as
  unavailable, and reject unreleased episodes across direct and automated
  queue paths.
- Add Filmo as a fully integrated movie provider and improve Huhu, fallback,
  provider, and hoster metadata behavior.
- Add Regular computer and NAS / home server modes, English-first live setup
  translation, mandatory TMDB validation, safe `.env` generation, a Windows
  launcher, and more reliable mounted-source runtime activation.
- Improve Jellyfin availability matching, metadata hydration, mobile
  navigation, catalog lazy loading, responsive layouts, accessibility, and
  frontend cache invalidation.
- Rewrite and expand installation, Docker, queue, provider, Android API,
  update, backup, and rollback documentation.
- Expand regression, frontend contract, provider, setup, deployment, queue,
  security, dependency, container, persistence, and restart validation.

The complete release notes are available in
[`docs/releases/v1.0.0-rc.3.md`](docs/releases/v1.0.0-rc.3.md).

This is a **release candidate**, not the final `v1.0.0` release. Back up at
least `.env` and `data/` before updating. Third-party providers may change
their pages, domains, availability, or protection mechanisms at any time.

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
