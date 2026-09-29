# Storage Autopilot: implementation audit

Baseline: Overnight `5e85ee5f47bf78e8a0af2b14fed19370ec8a626f`.

## Existing owners

- `storage_locations.py`: persistent registered roots, media/monitor permission,
  physical filesystem deduplication, explicit bounded analysis and cleanup.
- `storage_manager.py`: cheap `disk_usage` telemetry separated from recursive
  analysis; signed expiring candidates, protected names and symlink rejection.
- `storage_move.py`: signed source revalidation, cross-volume/overlap/collision
  rejection, complete series grouping and destination reserve checks.
- `storage_move_runtime.py`: one serial worker, persistent source fingerprint and
  hidden partial transfer, restart recovery, destination/source verification before
  source removal. This remains the only transfer engine.
- `api_storage_router.py`: administration-owned storage endpoints. Existing
  callers and manual confirmations remain compatible.
- `features/storage/`: scoped polling, scan, location editor, guarded move modal
  and move-job history. Extend this area rather than add a competing dashboard.
- `DownloadJob`: isolated staging and verified publication. Placement must happen
  before job construction so callbacks, queue paths and staging agree.
- `download_storage_guard.py`: existing minimum free-space guard is retained.

## Gaps and safety decisions

Capacity polling currently performs no recursive scan. Preserve that contract.
The registry describes permitted roots, not proof of Royal ownership of every
file. Automatic moves require an inventory item confirmed by download events or
explicit user authorization; a scan alone must not authorize moving foreign data.
Queue reservations and moves must share physical-volume budgets across roots.
Offline registrations remain present; no automatic directory creation/remount is
allowed as a substitute for an unavailable mount.
Playback evidence must be fresh and authoritative. Unknown Jellyfin activity
blocks autonomous media moves rather than pretending the title is idle.
Deleting media is not implied by any autonomy level. Automatic cleanup requires
separate explicit categories and preview; unknown files are never eligible.

## Migration order

1. Bounded atomic state, validated policies, deterministic eligibility/score tests.
2. Inventory/events and physical-volume reservations; integrate placement before
   download construction while keeping monitor/advisor paths unchanged.
3. Recommendations, cooldowns and scheduling using the existing move runtime.
4. Separate cleanup authorization, protection flags and operation history.
5. Extend existing storage UI and admin API, including compact mobile controls.
6. Deterministic safety/restart/offline tests and browser/CI coverage; document the
   final contracts and validate the complete Overnight pipeline.

No framework, build pipeline, parallel transfer engine or host mount management
is introduced. Monitoring is the compatibility default.

## UI plan and brief review

Use the existing Royal palette: dark `#121212`, text `#ece6d8`, storage green
`#46d9aa`, caution `#ffbd5d`, destructive-action red `#f03845`. Inherit Royal's
Archivo/DM Sans settings typography; introduce no fonts or decorative motion.
Keep everything left-aligned and let capacity/permission communicate hierarchy.

```text
Storage status + impact
Autonomy [monitor / advise / automatic / full]
Recommendations (only when relevant)
Existing physical-volume capacity cards
Advanced: roles / thresholds / time window / protection
Separate cleanup permission + concrete preview
Activities (collapsed)
Existing explicit large-content scan / move controls
```

Review: this is an extension of a NAS volume manager, not a generic dashboard.
Physical-volume identity and separate deletion authorization are the meaningful
structural elements. Preserve existing cards and manual actions; use compact
forms instead of wide tables on phones. Technical settings remain collapsed.
