# Provider Sentinel

Sentinel extends the existing provider catalog, adapters, ProviderHealth,
HosterIntel and background services. It does not replace provider parsers or
introduce another download stack. The administrative surface is **Settings →
Sources → Provider monitor**. This feature is developed on Overnight; the
published application version remains unchanged until a separate stable release.

## Scheduling and resources

Monitoring starts with the existing post-setup background services. Defaults:
enabled, every 12 hours, standard intensity, automatic validated repair enabled,
notifications disabled. The interval is configurable from 1 to 168 hours.
Only configured providers in selected content languages are scheduled. Their
user order and enablement are never rewritten by Sentinel.

Startup probes wait five minutes plus deterministic per-provider jitter of up
to 15 minutes. Subsequent probes also use jitter. Two probes may run at once;
there is no unbounded executor queue. Manual probes have a 60-second minimum
interval and return HTTP 429 when occupied. Probe-all uses staggered scheduler
slots, including when automatic monitoring is paused. Failed isolated sources
are rechecked within approximately one hour plus jitter.

Light probes check connectivity and supported catalogs. Standard probes add
search and up to three independent details per supported media type. Full
probes use up to five details and inspect an episode where needed for series or
anime hoster extraction. Limits per probe are 60/90 seconds, 32/48 HTTP requests,
and eight seconds per transport call. Oversized responses fail diagnostically;
only the first 250 KB per response is retained temporarily for repair analysis.
At most three repair candidates receive separate bounded full shadow probes.

Sentinel uses disposable HTTP sessions, TLS verification and the existing public
network proxy guard. It never launches CDP/browser verification, solves challenges
or calls a media downloader. Existing user-directed verification remains intact.
Provider adapters may use their own bounded caches; full validation forces anime
details where that contract supports it.

## Diagnostics and health

All 15 catalogued adapters declare their actual media capabilities. A successful
homepage is only the first step. Catalog, search, detail identity, metadata,
hoster extraction and source-link structure appear separately with timing and
HTTP status when available. Series/anime episode hosters require full intensity.

Dynamic canaries come from successful real detail requests and current catalogs;
independent identities are deduplicated. Removed titles are skipped rather than
treated as proof that an entire provider failed. Previously present metadata
must remain present. Fingerprints contain HTML tag/semantic counts or JSON field
shapes, never complete persisted pages.

Runtime Health retains `healthy/cooldown/probing/blocked`. Sentinel diagnosis is
separate: `healthy`, `degraded`, `broken`, `blocked`, `repair_available` or
`needs_attention`. Steps distinguish network errors, temporary HTTP failures,
rate limits, verification gates, empty extraction and identity/metadata failures.
Unsupported structural changes require manual attention.

Isolation requires two failed rounds plus independent failed samples, or repeated
explicit verification blocking. Existing ProviderHealth then excludes that source
from normal transport/routing while configured alternatives remain available.
Three successful independent detail checks can restore health; a light check
cannot release quarantine. Non-light recovery probes automatically use full
intensity, including episode hosters. Exhausted budgets are inconclusive rather
than fabricated metadata/hoster failures. No provider configuration is deleted.

HosterIntel remains independent. A found URL proves only link structure. The
monitor reports known hoster cooldowns and otherwise unknown availability; it
does not claim that a hoster can play/download merely because parsing succeeded.
Live redirect resolution and playback validation are intentionally not probe
capabilities in this implementation.

## Self-healing levels

| Level | Behavior |
| --- | --- |
| 0: Recovery | Existing fallback routing, conservative cooldown and later probes |
| 1: Declarative repair | Verified domain redirects; Filmpalast catalog/title/poster selectors; MegaKino catalog JSON path |
| 2: Ambiguous | Evidence retained, low confidence, no automatic activation |
| 3: Structural rewrite | Manual attention; no generated or executed application code |

Other selectors, pagination formats, metadata mappings, new APIs and token
protocols are not automatically rewritten. In particular, MKissa's token/API
protocol is outside automatic repair. Future repair fields must extend explicit
contracts and deterministic fixture tests.

A domain candidate requires a valid HTTPS redirect from a catalogued provider
origin, a single unambiguous destination, and full shadow validation. TLS alone
does not establish ownership. IP addresses, other providers' known domains,
credentials and nonstandard HTTPS ports are rejected; the network guard rejects
private destinations and unsafe redirects.

Selectors are a small allowlist of simple tag/class/id expressions. JSON paths
are bounded keys rather than executable expressions. Discovery uses uniquely
matching known identities on multiple pages. Shadow validation compares the
current adapter and candidate without changing user traffic: at least three
known independent details, passing catalog/search/metadata/hoster tests, retained
previous successes, metadata fields, poster identities and hoster counts, plus
a concrete improvement. Confidence is evidence-based high/low, not a guessed
percentage. Verification gates and rate limits cannot create parser repairs.

Each repair records an ID, timestamps, reason, prior/new profile and complete
validation evidence. Only one repair is active at a time. Manual activation
requires confirmation and fresh full validation; rollback requires confirmation.
Three distinct real-request failures within 15 minutes trigger automatic
rollback to the previous profile. Repeated failures of the same title do not
count as independent evidence. Observation failures cannot replace a normal
provider result or its original error.

## Persistence and privacy

`provider_monitor.json` lives in the existing configured data directory and is
ignored by Git/container source copying. Version 1 is written using fsync and
atomic replacement. A failed write cannot activate an in-memory repair profile.
No migration modifies accounts, sessions, queue, subscriptions or settings.

History keeps at most 120 events/provider for 30 days; repair journals keep 20
recent records plus an older active record. Canary identities, safe source slugs,
titles, field presence and structural summaries are retained. Passwords, headers,
cookies, raw pages, hoster token URLs and exception text are never persisted by
Sentinel. Repair selectors/JSON field names and sanitized HTTPS origins are
inspectable evidence, not code. Back up this file with the normal data directory.

## Administrator API

All routes require an administrator session; existing origin/CSRF security applies
to writes. Both `/api/providers` and `/api/v1/providers` expose the same contract:

| Method | Suffix | Purpose |
| --- | --- | --- |
| GET | `/diagnostics` | Summary and all provider diagnostics |
| GET | `/{provider}/diagnostics` | One provider |
| PUT | `/monitor/config` | Enabled, interval_hours, intensity, auto_repair, notify_changes |
| POST | `/probe-all` | Stagger enabled providers; body `{"intensity":"full"}` |
| POST | `/{provider}/probe` | Bounded manual probe with selected intensity |
| GET | `/{provider}/history` | Bounded history |
| GET | `/{provider}/repairs` | Repair evidence |
| POST | `/{provider}/repairs/{id}/activate` | Fresh validation; body `{"confirmed":true}` |
| POST | `/{provider}/repairs/{id}/rollback` | Restore prior profile; body `{"confirmed":true}` |

Optional meaningful state-change notices use the existing `provider_diagnostics`
WebSocket event and monitor banner. They are disabled by default; Telegram and
AI diagnostics are not added. Polling runs only while settings are mounted and
the document is visible. Expanded provider, repair and history panels survive
refreshes; unsaved monitor controls are retained.

## Validation

Normal CI uses offline fixtures exclusively. Tests exercise every adapter's
declared contract against empty responses, real Filmpalast HTML and MegaKino JSON
parsers, harmless layout mutations, selector/domain/schema recovery, lost metadata
and hosters, ambiguous identities, atomic persistence, rollback, scheduling,
legacy verification ownership and administrator API boundaries. Desktop and
touch-mobile tests use the actual settings UI and require explicit rollback
confirmation. Existing architecture, browser, CSS, performance, security,
upgrade/rollback and CodeQL gates remain mandatory.

Provider sites can still change beyond these safe repair boundaries. Such failures
are diagnosed and isolated; administrators inspect the steps and journal before
updating the adapter. No live provider success is asserted by fixture CI.
