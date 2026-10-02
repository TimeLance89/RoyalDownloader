# Royal Storage Autopilot

The Autopilot extends **Settings → Storage → Monitor and clean storage**. It
uses the existing registered locations, physical-volume telemetry, signed Smart
Scan candidates and restart-safe serial move worker. It does not mount disks,
replace the transfer engine or require migration of `MOVIE_FOLDER`/`SERIES_FOLDER`.

## Permissions

| Mode | Placement | Recommendations | Background moves | Archive |
| --- | --- | --- | --- | --- |
| Monitor (default) | Existing destination | Capacity/pressure only | No | No |
| Advisor | Existing destination | Explicitly confirmed moves; advice for known queued paths | No | Confirmed recommendations only |
| Automatic | Scored media destination | Yes | Verified Royal-owned contents | No |
| Full | Scored media destination | Yes | Verified Royal-owned contents | Age-qualified archive destinations |

**No mode implicitly enables deletion.** Existing explicitly confirmed manual
cleanup remains available. Automatic cleanup is a separate permission, initially
off, with a preview and explicit confirmation. Its sole supported category is
`royal_partials`: strictly marked Royal staging directories orphaned for at least
seven days, containing only recognized download artifacts. Media, unknown files,
backups, symlinks and active attempts are ineligible. A directory containing even
one unrecognized file is skipped; cleanup never recursively deletes such a tree.
The preview explains that permission also covers future qualifying artifacts.
Monitor and Advisor never execute this background cleanup.

## Locations, pressure and placement

The two paths configured under **Settings → Operation & storage → Standard
destinations** remain the safe movie/series starting points and fallback
destinations. They are not a global restriction: in Automatic or Full mode the
placement step may redirect a new download to another eligible registered media
root while preserving its relative movie/series path. Monitor and Advisor modes
never change that original destination.

Each additional registered media root explicitly declares which content types it
may receive (movies, series and/or anime). This simple per-folder routing choice
is authoritative, so two folders on the same physical disk can safely be used as
separate movie and series destinations. Advanced volume rules can still tune the
role, thresholds, reserve and move permissions, but cannot silently widen the
content types selected for that folder.

Each registered media root has a role: Primary, Overflow, Archive or Monitor,
allowed media types (movies/series/anime), target/warning/critical thresholds,
minimum free GiB and move-in/move-out permissions. A location registered as
Monitor must first be explicitly changed to Media before it can receive content.
Archive roots receive older content in Full mode, not new downloads.

Defaults: target **75%**, warning **85%**, critical **92%**, reserve **5 GiB**.
When paths share a physical filesystem, reservations are combined, the largest
reserve and lowest thresholds apply. Space is never counted twice through an
alias. Roles/media permissions remain explicit per registered root.

Eligibility precedes scoring: online, writable, permitted media root, matching
media type, no collision/symlink, sufficient reserve after estimated bytes and
other reservations, and below the critical threshold. An affinity score can
never override these constraints. Scoring explains capacity, role, target
threshold, existing series location, pending work and I/O load. Overflow becomes
preferable when Primary reaches its target. The original media-relative path is
preserved, including series/season directories. Series stay on their known root
unless it is unsafe/unavailable or distribution is explicitly permitted.

Unknown **active** downloads reserve **8 GiB** by default until a real size is
known. Waiting work is demand rather than committed disk space: at most the next
32 pending queue jobs contribute to the near-term capacity forecast. Unknown
pending sizes use 1.5 times the median known size for their media type, with a
0.5 GiB series or 2 GiB movie floor; without samples the estimate is 2 GiB for
series and 8 GiB for movies. All active downloads and moves count in full.
Every new download acquires an atomic per-job reservation before starting and
the live budget guard rechecks real free capacity during transfer and publication.
Persistent reservations use the logical job ID, survive retries and are released
on terminal queue transitions or reconciled against the live queue. Pending jobs
with known final paths are forecast on that root; unplaced jobs use the existing
movie/series destination. Active moves reserve their target space.
Actual download guards recheck destination/staging reserves and remaining known
bytes, at most every five seconds, and stop safely if the budget is lost. Fallback
staging on another filesystem retains the full destination reservation until
publication; its downloaded bytes do not prematurely release target capacity.
Publication uses the exact validated size for a cross-volume copy and no second
copy budget for a same-volume atomic publication. Storage
failures do not blame the external hoster. Completed publication releases the
reservation and records the actual path, including collision-renamed files.

Pressure is Normal, Warning, Critical, Emergency or Offline and includes planned
bytes. Recommendations start above the warning threshold and aim below the
target; per-content cooldown prevents oscillation. Existing registrations and
inventory remain intact offline. A changed physical-volume identity is rejected
until the administrator verifies the host mount and explicitly confirms it.
An empty surviving mount directory is not silently accepted as a different disk.

## Balancing, archive and inventory

Inventory is bounded, persisted beside `sessions.json` as
`storage_autopilot.json`, atomically replaced with fsync and private permissions.
Successful downloads, explicit Smart Scans and verified move completion supply
metadata. Scan results alone do **not** establish Royal ownership.

Before autonomous moves, all actual files must match publication ownership
evidence (relative path, size, modification time and file identity). Foreign or
changed files, incomplete series and symlinks block automation. Explicitly
confirmed manual recommendations still undergo signed source revalidation and
the existing safe move contracts. Protection flags are `no_move`, `no_archive`,
`no_delete` and `keep_volume`, exposed through the administrator API.

Full mode can archive contents whose filesystem/library age reaches **180 days**
by default. This is **not** claimed to be a last-viewed date. Royal currently
uses reliable Jellyfin session activity to block moves during playback or
transcoding; missing/error activity from a configured Jellyfin also blocks them.
Without a configured Jellyfin, there is no Jellyfin playback dependency. There is
no per-title last-viewed inference.

The only execution path is `storage_move_runtime.create_move_job`: signed plan,
cross-volume/collision checks, resumable hidden partial transfer, destination
verification, source revalidation, atomic publication, then source removal.
Configured target reserve is carried into execution/recovery. Persisted
`autopilot_id` connects proposals to recovered jobs; replay does not create a
second transfer. Verified completion updates inventory/protection and history.

Conservative defaults: **one serial large move per round**, **200 GiB per round**,
**02:00–07:00**, **six-hour planning interval**, **seven-day content cooldown**.
`max_moves` is an upper bound; this implementation deliberately starts at most
one move per round even if a larger bound is configured. Any active/pending
download queue, storage move or unknown playback blocks new optimization. Rules
and live queue are rechecked after source verification. Downloads have priority;
there is no additional worker pool or recursive scan in live polling.

Relevant events wake the existing application-owned planner. Metadata planning
is bounded to one event round/hour, with an independent execution cooldown. Time
window deadlines prevent the periodic cadence from skipping a nightly window.
Location changes refresh cheap observations; removed roots lose their policies,
but offline registrations are retained. Explicit large-content analysis remains
the way to discover existing libraries; the planner never automatically crawls
the entire NAS. Inventory failures cannot invalidate an already verified download
or safe move; unreadable state disables autonomous planning and policy writes.

Limits: 10,000 inventory/protection records, 2,000 owned files per content, 80
proposals, 300 history entries, 24 volume observations/policies, and 8 MiB
persisted state. In-flight reservations are bounded by this byte budget rather
than a 512-job count. Ownership verification exceeding its budget is refused.
Cleanup examines bounded direct staging directories, not recursive media roots.

## API and UI

Both `/api/storage/*` and `/api/v1/storage/*` aliases exist. The new endpoints
require an authenticated administrator, using the existing session/user context.

| Method | Suffix | Purpose |
| --- | --- | --- |
| GET / PUT | `autopilot` | Status / validated autonomy and independent cleanup policy |
| PUT | `autopilot/volume` | Root role, media, thresholds and mount confirmation |
| GET | `recommendations` | Refresh bounded explainable proposals |
| POST | `recommendations/{id}/apply` | Signed move; explicit boolean `confirm` |
| POST | `recommendations/{id}/dismiss` | Suppress proposal during cooldown |
| GET | `activity` | Bounded operation journal |
| PUT | `inventory/{id}/protection` | Validated content protection flags |
| GET | `cleanup/preview` | Read-only category/candidate/size preview |
| POST | `optimize` | Run safe policy checks; does not bypass the time window |

The normal view shows impact, reachable capacity, autonomy and actionable
recommendations. Volume policy, thresholds, time window, cleanup permission and
history use progressive disclosure. Existing capacity cards, explicit Smart
Scan, manual cleanup/moves and restart-safe job display are preserved. The
Autopilot uses scoped HTTP/lifecycle handling and avoids replacing controls during
editing or background polling. Operation history stores reason, source/target,
policy, score, expected utilization and result; detailed volume/placement
decisions are available through the same API.

## Validation and operational limits

Offline deterministic tests cover scoring/hard limits, series affinity,
reservations/retries, offline/mount identity, archive/protection, foreign files,
policy revocation, queue/playback safety, source changes, collisions, restart
submission replay, completion reconciliation, actual download guards and explicit
cleanup. Existing move recovery/verification contracts remain required.

`tests/frontend/storage-autopilot-browser.cjs` exercises the real application on
1440 px desktop and 390/430 px touch viewports in Chromium and WebKit: four modes,
volume roles/reserves, offline registration, deletion preview/confirmation,
recommendation apply/dismiss and horizontal-overflow/error checks. It runs in the
required Quality browser and WebKit jobs alongside existing CSS/performance,
security, backend, Docker, E2E and upgrade/rollback gates. No live NAS, Jellyfin
or external source is needed in CI; production disk throughput is not inferred
from fixture tests.

Autopilot placement changes download destinations; administrators must expose all
chosen volumes to Jellyfin/library clients themselves. Existing large libraries
need an explicit analysis for advice and publication evidence for autonomous
moves. Advisor placement advice requires a known pending final path. There is no
automatic remount, automatic deletion of media, recursive background library
scan, or invented viewing history.
