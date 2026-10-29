# Coordinated media scans

Royal's scan producers now submit **completed local files** to one durable
coordinator. Download callbacks do no Jellyfin HTTP requests or ffprobe work.
No media is deleted when validation, scanning or recognition fails.

## What the code could cause

Previously `JellyfinClient.refresh_library()` posted `/Library/Refresh`.
Download lifecycle refreshes coalesced only within one in-memory worker, with
repeated refreshes after its 120-second reconciliation loop. Telegram movie and
series completion (and configuration changes during recognition) posted their
own refreshes. Seerr retried completed-but-unrecognized requests every five
minutes without a terminal scan retry budget. These independent producers could
cause frequent full scans even with Jellyfin filesystem monitoring disabled.

This establishes plausible triggers in Royal, **not proof of the reported live
NAS CPU usage, scan cancellations or Immich scheduling failure**. No live NAS
Docker configuration, Immich service or provider was changed.

## Verified API and compatibility

The Jellyfin repository's release tag is `v12.2`. In that source:

- [ScheduledTasksController](https://github.com/jellyfin/jellyfin/blob/v12.2/Jellyfin.Api/Controllers/ScheduledTasksController.cs)
  exposes authenticated/elevated `GET /ScheduledTasks` and
  `POST /ScheduledTasks/Running/{taskId}`.
- [RefreshMediaLibraryTask](https://github.com/jellyfin/jellyfin/blob/v12.2/Emby.Server.Implementations/ScheduledTasks/Tasks/RefreshMediaLibraryTask.cs)
  identifies the full scan by the stable task key `RefreshLibrary`.
- [LibraryController](https://github.com/jellyfin/jellyfin/blob/v12.2/Jellyfin.Api/Controllers/LibraryController.cs)
  calls library validation directly for the old `/Library/Refresh` endpoint.
  `/Library/Media/Updated` reports filesystem changes using paths **as Jellyfin
  sees them**. Royal cannot infer these paths from its separate Docker mounts.
  Movie/series added/updated endpoints also rely on finding existing entities.

Therefore Royal uses the verified scheduled full-scan task rather than guessing
per-directory paths that could miss new titles. It checks task state before and
again after local validation. Running/Cancelling, missing tasks, ambiguous data,
auth failures and unavailable status never authorize a new scan. It never sends
a task stop/cancel request. A separately initiated admin/plugin scan can race the
final check; Jellyfin owns final task execution. This is not an atomic lock over
all external applications or Jellyfin's separate metadata queues.

Plex retains its existing section refresh implementation, behind the same
completed-file queue/cooldown. It never receives Jellyfin ScheduledTasks calls.
User mapping, saved/watchlist APIs and identity matching are unchanged.

## Timing, persistence and bounds

Documented in `.env.example`:

| Option | Default | Effective bounds |
| --- | --- | --- |
| `JELLYFIN_SCAN_DEBOUNCE_SECONDS` | 60 | 1..86400 seconds |
| `JELLYFIN_SCAN_COOLDOWN_SECONDS` | 300 | 300..86400 seconds |
| `JELLYFIN_SCAN_RETRY_SECONDS` | 300 | 60..86400 seconds |

Malformed values use defaults. The first request fixes the batching deadline;
new arrivals cannot postpone it. Once ready, a batch includes up to 128 pending
files, including arrivals within that window. New files during active scans or
cooldowns remain pending. A single lightweight worker wakes on arrivals or at
most every 15 seconds; an empty queue makes no task-status HTTP requests.

`media_scans.sqlite3` and its kernel lock live under the existing persistent
application data directory (`SERIENDL_DATA_DIR`, `/app/data` in Docker). Every
process serving the same installation must share that local persistent directory.
SQLite connections close after transactions; an index bounds queue lookup cost.
A nonblocking OS lock serializes task status/probing/dispatch across threads and
processes and is released when a process dies. Enqueuing remains independent of
the dispatch lock. Do not place this database on a filesystem without reliable
SQLite/kernel locking semantics.

The coordinator reserves each attempt durably **before** POST. A crash with an
unknown POST outcome retains the reservation and cooldown, then retries within
the original budget. HTTP acceptance cannot be made exactly-once across a crash
without server idempotency support; task state and cooldown guard that ambiguity.
The last attempted start and last accepted start both survive restart. Observed
external task start times also enforce the minimum interval.

There are at most three dispatch/status-error attempts per final file identity,
with exponential backoff. An active scan does not consume that budget. Pending
work expires after 24 hours. After HTTP acceptance the file is never resubmitted
just because it remains unrecognized: existing shared inventory reads verify
recognition for up to 30 minutes, then record `media_not_detected` or
`recognition_unavailable`. This is a diagnostic failure, not a download failure.
Identity tombstones remain in SQLite so recurring Seerr/Telegram status checks
cannot reset the budget. A newly published, changed final file has a new identity.

Before dispatch, reuse `media.downloader.validate_media_file`: existing minimum
size and ffprobe checks for audio, video and plausible duration. Reject staging,
unsupported extensions, missing files, symlinks and changed inode/size/mtime
before/after validation and immediately before dispatch. The downloader validates
staged files and publishes the final file only after merging finishes. A full
scan can still encounter **other pre-existing invalid files** in Jellyfin's
library; Royal does not clean them up automatically or disable Jellyfin tasks.

## Producer audit and reconciliation

- Download lifecycle: hand off only successful terminal callbacks/final paths.
- Telegram: hand off completed movies/episodes; preserve notifications and the
  30-minute recognition wait. Poll shared inventory, without forced full reads
  per Telegram job. A changed server configuration gets its own queue scope.
- Seerr: persist successful final paths; retry handoff at most three times with
  persisted backoff. Older records without final paths report a diagnostic and
  cannot request a blind full scan. Availability states stay intact.
- Queue cancellation compatibility calls: **read-only** inventory reconciliation.
- `jellyfin_live`: existing fingerprint and inventory GETs, not scan initiators.
- The legacy Jellyfin `refresh_library()` refuses uncoordinated calls. The only
  task-start HTTP call is the coordinator's verified scheduled task dispatch.

After an accepted batch, preserve existing movie/badge/episode/user-episode reads
and generation-protected watchlist reconciliation at 5/15/30/60/120 seconds.
Shutdown interrupts these waits. A read/cache refresh is not a server scan.

## Diagnostics and remaining live checks

Existing admin runtime diagnostics (`/api/diagnostics/runtime`, also its v1 alias)
include `media_scans`: counts by state, phase, last accepted/attempted full-scan
start timestamps, submitted batch count, incoming request count, avoided redundant
starts, and ten recent failures (source, safe reason, attempts). Logs report
request source, deduplication, batch size, submission and recognition outcomes.
They contain no media paths, URLs, API keys or raw exception messages from the
new coordinator/client endpoints. Times in logs use the existing logging setup;
diagnostic timestamps are Unix seconds. `submitted` means HTTP accepted, not
that Jellyfin finished or indexed the item. Recognition uses existing matching
rules and shared snapshots; unknown/stale snapshots cannot prove a new scan
completed. Failure metadata remains available after restart.

To establish the actual NAS cause, compare these timestamps/counters with
Jellyfin's scheduled task history and server logs. Inspect other external scan
initiators (Seerr's own integration, plugins, scheduled tasks, manual/API clients),
Jellyfin-side mount paths/permissions, and the invalid files reported by ffprobe.
Persisted `scan_status_unavailable` can mean the configured token lacks permission
to inspect tasks; Royal intentionally does not fall back to an unchecked scan.
If task starts continue without corresponding Royal submissions, another trigger
or Jellyfin-internal work remains involved. Do not infer that CPU/Immich issues
are fixed solely from unit tests.

## Verification

`tests/test_jellyfin_scan_manager.py` covers deterministic batching, many threads,
real spawned processes, process-death lock release, cooldown, external/active task
states, crash/restart reservations, invalid/changing/staged/tiny files, bounded
HTTP/status retries and recognition timeouts, authenticated API contracts,
malformed responses and safe error logging. `tests/test_media_scan_handoffs.py`
covers download success/failure, Seerr persistence/backoff, Telegram movies and
episodes, cached reads and existing identity rules. Both run in the existing
media-center CI test step (180-second budget), without network or heavy media.
