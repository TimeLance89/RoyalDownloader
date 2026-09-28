# Changelog

## Unreleased

### Multi-language provider capabilities

- Separate legacy primary language, supported provider languages and concrete
  title/episode tracks. AniWorld supports DE/EN selection; German dub/sub remain
  distinct tracks but count as one German source. MKissa remains an EN provider,
  with explicitly selected Japanese raw episodes correctly labeled and persisted.
- Make setup, administration, priorities, monitoring and source settings use
  language-set intersection. Existing configuration and queue language values
  remain compatible without manual migration.
- Evaluate only configured media/language paths, using fresh concrete track
  evidence for multi-language availability instead of assuming every supported
  track works. Show available and unavailable languages together only when an
  area is affected; preserve the compact healthy overview and Sentinel safety.
- Add offline catalog/setup/routing/persistence/evidence regressions and desktop,
  390/430 px touch and WebKit source-selection/availability coverage.

### Source Sentinel availability overview

- Replace the default diagnostic lists with a compact availability card for movies,
  series and anime, automatic monitoring/repairs and clear action requirements.
- Evaluate configured media/language paths and working alternatives centrally;
  distinguish missing evidence from confirmed outages without changing source
  health, ranking or conservative repair qualification.
- Keep complete provider, video-service and repair diagnostics behind Technical
  details; move interval/intensity/manual checks into Advanced settings.
- Suppress alarms for safely handled individual failures and incomplete probes,
  notify only on meaningful service-impact transitions, and hide raw external
  error bodies from everyday messages.
- Cover compact 390/430 px touch layouts, desktop and WebKit disclosure/actions
  alongside offline availability-policy and notification regressions.

### Hoster probe evidence correction

- Distinguish HTTP-only probes from browser-assisted production resolvers, including
  provider-dependent generic embeds. Unconfirmed HTTP parsing no longer falsely
  marks VOE/Veev and similar hosters broken or applies the hard ranking penalty.
- Combine active probe completeness with independent production outcomes; retain
  defect detection for complete HTTP resolvers and real runtime failures.
- Explain browser/runtime validation limitations in Settings, correct legacy cached
  diagnoses and omit synthetic zero-millisecond step durations.
- Preserve repair validation, rollback and resource/security limits; add offline
  regression coverage and desktop/mobile diagnostic UI checks.

### Source Sentinel: Hoster hardening

- Extend the existing Provider Sentinel with separate hoster contracts, staged
  resolver probes, bounded runtime success/timing metrics and independent health.
- Preserve provider health when only an external hoster fails; apply hoster health
  as an additional fail-open ranking factor so working alternatives are preferred.
- Share scheduling, resource limits, atomic storage, repair activation and rollback.
  Keep embed canaries and raw player evidence ephemeral, with no persisted tokens.
- Validate declarative player/JSON/attribute/domain repair profiles against five
  proven independent canaries before activation; monitor real outcomes for rollback.
- Extend Settings → Sources with Provider, Hoster and Repairs/history tabs, protected
  admin actions, offline mutation contracts and desktop/mobile browser coverage.


### Provider Sentinel and conservative self-healing

- Monitor enabled movie, series and anime providers through their existing
  adapters, with staggered scheduling, configurable intensity and bounded HTTP
  concurrency. Connectivity, catalog, search, details, metadata and extracted
  hoster/source structures have separate diagnostic results.
- Feed confirmed independent failures into existing ProviderHealth cooldowns and
  fallback routing without changing provider selections. Successful independent
  detail probes restore availability automatically.
- Detect structural changes with bounded fingerprints and dynamic reference
  titles. Persist bounded diagnostics and versioned repair evidence separately
  from provider sessions, settings and download jobs.
- Validate trusted HTTPS domain redirects, Filmpalast catalog/title/poster
  selector changes and MegaKino catalog JSON-path changes in full shadow probes
  against at least three known titles. Preserve identities, metadata, artwork
  and hoster extraction before activating a declarative profile.
- Roll back active repairs after three independent real-request failures;
  administrators can inspect evidence, request probes and confirm rollback in
  **Settings → Sources → Provider monitor**. Optional state-change notices use
  the existing WebSocket transport.
- Keep challenges, rate limits and unsupported protocol changes separate from
  parser repairs. Probes never download media, launch verification browsers or
  generate application code. Source checks validate extracted link structure,
  not live playback availability.
- Add offline adapter/repair/mutation/security tests and desktop/touch settings
  regression coverage to CI. Fix mobile More-menu positioning so settings remain
  reachable above the navigation dock.

See [Provider Sentinel](docs/PROVIDER_SENTINEL.md) for supported repair levels,
resource limits, API access, persistence and operational limitations.

## v1.2.3 – 2026-09-27

### Series pagination recovery

- Retry temporary preparation, network and upstream failures while loading the
  next series page, with at most three attempts inside a 30-second total deadline.
- Keep loaded cards and the page cursor intact until the next page succeeds.
  An incomplete follow-up page at the provider deadline now reports a retryable
  preparation state instead of silently advancing past pending titles.
- Stop scroll-triggered requests after retries are exhausted. The visible
  **Erneut versuchen** action retries the same page; leaving the view cancels work.
- Add backend deadline/API-contract tests and desktop/touch-mobile browser tests
  for automatic recovery, bounded failure and manual retry to the normal CI gate.
- Preserve existing design, logical contents, carousel behavior and persistence.

See [v1.2.3 release notes](docs/releases/v1.2.3.md). No persistent-data migration.

## v1.2.2 – 2026-09-27

### Similar-title detail reliability

- Keep known recommendation artwork, description, genres and language when opening
  similar movies or series. Load full TMDB data independently of provider results.
- Run movie metadata, Jellyfin and provider checks independently, with dialog-owned
  cancellation. Late responses cannot overwrite the next selected title.
- Preserve rich metadata when providers return sparse data or fail. Separate
  unavailable sources from metadata errors and replace raw Cloudflare/origin text
  with a concise availability message; technical diagnostics remain in logs.
- Include virtual TMDB selections in library badge updates and prevent catalog
  background enrichment from restarting a completed detail availability state.
- Bound interactive cross-provider search and detail waits, preserving completed
  matches and provider priority. Limit outstanding worker jobs; background scraper
  calls retain their existing network timeouts. Download exhaustion rules remain.
- Resolve similar-series metadata by TMDB ID, retain it after provider failure,
  and keep the existing provider-based episode resolver and lifecycle checks.
- Add desktop/mobile browser coverage for same-modal navigation, independent
  failures, recovery, rapid selection changes, empty hosters and similar series,
  plus loader and backend deadline/error-contract regression tests.
- Preserve the catalog hotfix, layout, CSS, carousel and performance optimizations.

See [v1.2.2 release notes](docs/releases/v1.2.2.md). No persistent-data migration.

## v1.2.1 – 2026-09-27

### Critical catalog hotfix

- Fix a temporal-dead-zone error in the shared result-card renderer: a local
  poster candidate array shadowed the injected `coverCandidates` function,
  preventing movie and series catalog cards from rendering. Separate the local
  candidate value from the dependency while preserving lazy/asynchronous artwork.
- Fix the same class of error in Home's card-dock queue action, where a local
  queue-state boolean shadowed the lifecycle scope after the awaited operation.
- Add movie/series regression tests that fail with the original exception, plus
  populated desktop and mobile browser checks for actual cards, decoded posters,
  metadata/Jellyfin badges, details, filters, pagination and vertical touch scroll.
  Exercise queue add/remove completion in the Home dock as well.
- Keep unexpected runtime/console errors fatal; narrow the existing intentional
  503-fixture exception to the exact browser network diagnostic.
- Audit all 166 frontend modules for lexical initialization/shadowing hazards;
  no further matching immediate-use TDZ cases remain after these two fixes.
- Preserve the v1.2.0 design, native module architecture, carousel buffers,
  offscreen rendering, artwork quality and touch/momentum optimizations.

See [v1.2.1 release notes](docs/releases/v1.2.1.md). Existing v1.2.0 installations
should update; no persistence migration or configuration reset is needed.

## v1.2.0 – 2026-09-27

### Native frontend architecture

- Replace the historical Vanilla JavaScript runtime/screen scripts with native
  ES modules organized as `core/`, `shared/`, `features/`, `shell/` and
  `composition/`. Keep the existing UI, functionality and native browser stack;
  no React/Vue/Svelte, framework migration or application build pipeline.
- Centralize HTTP in `core/api.js` and WebSocket ownership/reconnects in
  `core/websocket.js`. Introduce feature-owned state and scoped
  mount/refresh/unmount lifecycles that clean up timers, listeners and subscriptions.
- Split the large composition root into domain modules and group application
  dependencies by area. Remove `sharedPresentation`, historical browser globals
  and cyclic ES-module imports; inject named dependencies explicitly.
- Move business actions into features, retain navigation/application chrome in
  the shell, and share cards, carousels, dialogs, feedback and loading components.
- Consolidate CSS design tokens while protecting the existing computed styles.
  Document ownership, APIs, lifecycle and allowed dependencies in
  `docs/FRONTEND_ARCHITECTURE.md`; enforce core/shared/feature layering,
  resolvable modules and cycle-free imports automatically.

### Mobile interaction and carousel rendering

- Repair mobile horizontal scrolling and the hidden navigation scrim that could
  intercept touch. Give touch/pen native panning and momentum priority; defer
  loop corrections until scrolling settles, with a fallback without `scrollend`.
- Distinguish taps from swipes, keep vertical page scrolling over cards, and
  preserve logical rail position across loop seams, rapid gestures, tab/history
  navigation, hidden refreshes and portrait/landscape resizing.
- Fix the detail-poster variable-shadowing error found by real card tap tests.
- Replace complete triple-clone rails with bounded dynamic edge buffers.
  **No titles or rails are removed:** all logical content and the visible design
  remain; only redundant rendering work is reduced.
- Skip distant rail rendering with measured `content-visibility`, intrinsic
  sizing and Intersection/ResizeObserver activation. Batch artwork geometry reads
  before writes and avoid rehydrating already-started images. Keep page height,
  timely artwork, typography, effects and image quality intact.

### Measured performance

- In the fixed 97-logical-entry fixture, full cards decrease **257 → 137** on
  desktop (**−46.7%**) and **257 → 117** on mobile (**−54.5%**). Total DOM nodes
  decrease **6,320 → 4,640** and **6,320 → 4,360**, respectively.
- A documented paired three-sample Chromium CI run measured desktop 4x CPU
  initial render **208.3 → 137.4 ms**, blocking time **529 → 386 ms**, layout
  **99.7 → 69.2 ms**; desktop 6x **305.1 → 218.0**, **1092 → 860**,
  **147.2 → 105.7 ms**; mobile 4x **196.2 → 122.2**, **497 → 308**,
  **79.5 → 56.1 ms**, in the same order.
- These are fixture/profile measurements, not universal device guarantees.
  Long-task counts and LCP do not improve in every run. Baseline, final-code
  results, methodology and raw data remain in `docs/FRONTEND_PERFORMANCE_*.md`
  and `docs/performance/`.

### Integration status, live updates and personal data

- Add structured integration health (`healthy`, `degraded`, `offline`,
  `auth_failed`, `disabled`, `unknown`) derived from explicit controller facts,
  not translated errors or Jellyfin media ownership.
- Broadcast committed movie-subscription save/removal and watchlist-removal
  snapshots; persistence failures do not emit successful updates.
- Preserve the compatibility `web/i18n.js` marker required by installed legacy
  updater archive validators while loading localization through ES modules.
- Retain household accounts, isolated sessions, first-login/onboarding, taste
  profiles, recommendations and the Profile Hub in the modular frontend.
  These capabilities were **already included in v1.1.0**.
- Preserve durable personal request history and its profile/Home integration:
  **Personal Request ≠ Download Job ≠ Queue**. Existing user isolation,
  restart/queue-cleanup persistence and retry deduplication remain protected.
  The persistent store also predates this release; it is not a new data format.

### Browser quality and release safety

- Make the required `verify` gate depend on Chromium smoke, setup/login,
  mobile touch/carousel tests at phone/tablet sizes, no-`scrollend` fallback,
  WebKit mobile validation, frozen CSS equivalence, visual rail comparisons,
  performance/content budgets and offscreen layout budgets.
- Preserve Python, frontend/core contracts, security scans, CodeQL, container
  validation, authentication E2E, persistence/restart and RC3 upgrade/rollback
  checks. Add upgrade/restart/rollback/backup verification from the actual
  published v1.1.0 commit with populated multi-user data and a runtime volume.
- Set authoritative `APP_VERSION` and active installation/capabilities/release
  documentation to **1.2.0**, resolving the v1.1.0 tag versus 1.0.0 application
  metadata discrepancy. Keep historical release documents unchanged.

See [v1.2.0 release notes](docs/releases/v1.2.0.md) for compatibility,
upgrade/rollback instructions, benchmark context and WebKit testing limitations.

## v1.1.0 – published 2026-09-24

The following previously unversioned notes describe functionality already in the
published v1.1.0 source. That tag reported application version 1.0.0; this historical
discrepancy is corrected prospectively in v1.2.0, without moving the old tag.


- Add household accounts with isolated sessions, passwords, onboarding,
  recommendations, browser state, downloads, subscriptions, and taste profiles.
- Introduce the Royal Intelligence and Royal Reflex recommendation flow with
  per-user local ranking, cache isolation, resilient background refinement, and
  a dedicated personal profile hub.
- Redesign the personal profile as a Royal media home with identity, confidence,
  learning signals, ratings, relative genre affinity, personal activity, recent
  requests, and secondary account controls.
- Classify subscription episodes semantically: language-mismatched episodes wait
  for the requested language, announced episodes remain upcoming, source gaps
  wait with backoff, and only an actual failed transfer is shown as a problem.
- Stabilize home and Intelligence carousels by eager-loading visible artwork,
  reconciling rails without layout jumps, and preserving the established series
  rail design.

- Add a compact Royal transfer deck with clearer download hierarchy, segmented
  progress, a next-up view, and responsive queue controls.
- Redesign home cards and carousels with stable layout, reliable poster and
  backdrop fallbacks, preserved scroll position, and incremental reconciliation
  that prevents visual jumps during background updates.
- Refresh the series catalog and detail views without flicker; expand details
  with trailers, production information, similar titles, and persistent season
  and episode context when opened from the calendar.
- Introduce a server-synchronised series calendar with validated snapshots,
  week navigation, filters, subscription mode, clear final loading states, and
  resilient retry and offline handling.
- Add a redesigned Releases view for movies and series, including localized
  content, older titles, bounded provider requests, and resilient timeouts.
- Restore Releases as the first item in the Discover menu on desktop and mobile.
- Add TMDB movie collections to search. Collection views check Jellyfin before
  providers, show per-movie library, provider, and queue state, and allow safe
  partial selection and download of the available titles.
- Make movie collections ready on first open by waiting for the initial
  Jellyfin identity snapshot; downloads no longer require closing and reopening
  the collection.
- Keep Jellyfin availability current after browser idle, standby, tab changes,
  and network recovery while failing closed when ownership cannot be verified.
- Redesign the subscription inbox and media archive as a unified subscription
  center, including persistent notifications for automatically downloaded
  episodes.
- Localize subscription and watchlist series titles, improve personalised
  evening recommendations, and filter explicitly English provider releases when
  English content is disabled.
- Add consistent Royal startup loading and richer movie and series detail
  presentation, including scroll-aware trailer playback and 16:9 artwork for
  recommendations.
- Make language switching immediate and persistent, including dynamically
  inserted settings and storage navigation, without blocking catalog startup.

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
