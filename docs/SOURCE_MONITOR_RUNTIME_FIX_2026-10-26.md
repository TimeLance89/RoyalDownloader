# Source monitor runtime fixes

The live NAS audit found synchronous whole-state writes in hoster observations,
a scheduler that exited after storage errors, a saturated dynamic hoster
inventory and multi-megabyte periodic diagnostics. This change addresses those
paths without changing source routing, confirmation or repair validation rules.

## Persistence and scheduling

Non-critical runtime observations update the in-memory store immediately. The
existing scheduler requests background persistence through a single writer,
with at most one outstanding flush and at least 30 seconds between ordinary
flush starts. A blocked flush retains that slot. Serialization/fsync happen
outside the state lock, so observations and diagnostic reads can continue.

Snapshots use copy-on-write entries and a revision check. An older queued
snapshot cannot overwrite a newer durable configuration. Configuration changes,
repair journals and acceptance of a manual all-source schedule still use atomic
durable writes; failures retain the previous state and are not reported as
success. The manual schedule is committed once while retaining staggered starts.

Stop attempts a bounded final telemetry flush and shuts down its writer without
waiting indefinitely for blocked I/O. Non-critical observations not yet flushed
can be lost on abrupt termination. This is not a change to download/queue
persistence. Python cannot cancel a kernel-blocked filesystem call; one such
writer can remain blocked until the NAS recovers.

Scheduler errors are caught per source and per round. Other sources and later
rounds continue. Diagnostics expose scheduler liveness/retries and persistence
failures, and Settings shows a warning instead of silently implying that an
enabled monitor is running successfully.

## Inventory

The 64-hoster bound remains. Recent entries and active repairs are preferred on
load. At capacity, the oldest dynamic entry inactive for more than seven days
can be reclaimed. Built-in contracts, active repair profiles and running checks
are protected. Admission observes owner/hoster lock ordering, and recent seed
activity prevents immediate eviction. If all slots remain protected/recent,
admission stays bounded and the UI reports the rejection.

## API and frontend

Legacy full diagnostics remain available by default. The Settings poll requests
`/api/providers/diagnostics?summary=true`; it preserves service health, current
steps, metrics and counts while omitting histories and repair profiles. Their
existing authenticated endpoints are used only when the corresponding visible
disclosure is opened. The UI caches details by source/revision, reloads changed
open details, and cancels pending requests and clears caches on unmount.

## Validation

- 190 targeted Python tests passed, including eight new regressions for
  coalescing, blocked/concurrent writes, durable rollback, scheduler recovery,
  protected inventory eviction, bounded admission, compact API equivalence and
  one-commit staggered scheduling.
- 341 Node tests passed; correctness lint and the security scan passed.
- Chromium and WebKit at 1440, 390 and 430 pixels passed the settings flow,
  confirmation/rollback behavior, compact polling, on-demand history/repairs,
  unchanged-cache reuse, revision refresh and runtime-warning recovery.
- A separate SSH-launched process on the NAS used temporary copies of its
  real monitor state and temporary copies of the changed Python modules.
  Production code/configuration were not replaced or restarted.

| NAS copy benchmark | Before | After |
| --- | ---: | ---: |
| Serialized diagnostics | 4,903,029 bytes (full) | 296,477 bytes (compact) |
| One hoster observation | 694.64 ms | 26.53 ms |
| Synchronous state writes for that observation | whole-state writes | 0 |
| Several observations persisted together | separate writes | 1 explicit flush |

The compact service summary matched the original. A new dynamic hoster was
admitted from a full real inventory while the cap stayed intact. These are
same-NAS temporary-state measurements, not end-to-end production HTTP latency
or a guarantee for every filesystem/load. GitHub CI validates the PR separately.

## Autonomous watchdog completion

- On restart, enabled provider checks refresh the volatile hoster references
  through the existing two-worker scheduler. Only matching recent hashed
  production successes restore proven media identities; URLs remain in memory.
- Failed checks retry after 5, 15 and then 60 minutes (plus at most 29 seconds
  jitter). Activated repairs receive a confirmation check after five minutes.
  Existing shadow validation, opt-out and rollback rules remain authoritative.
- Two failed meaningful checks create one persistent source incident. Repair
  rollback escalates immediately. Partial browser-only/recognition checks and
  removed references do not themselves claim a broken hoster or recovery.
- Incidents appear in the administrator Abo-Inbox even when alternative sources
  work. Read state is per account and profile-guarded; confirmed recovery clears
  the incident. Read incidents remain under Problems until recovery. Optional
  status push notices still honor `notify_changes`.
- The Linux stability failure was a restart test reading intentionally deferred
  language telemetry before a flush. It now flushes explicitly before loading a
  second instance, preserving its persistence and privacy assertions.
- Deterministic tests cover retry/escalation/recovery, restart, hashed reference
  proof, authorization, profile isolation and browser inbox rendering/lifecycle.
  Download routing, queue behavior and production NAS deployment are unchanged.
