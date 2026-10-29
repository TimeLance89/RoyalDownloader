# Shared Jellyfin inventory reads

The live monitor and legacy forced readers share in-flight reads in one process.
The key contains the configuration generation, hashed connection/credential scope,
provider, library selection, dataset and (for user data) the linked user. Nothing
is shared across server credentials or user profiles. Plex retains its own loaders.

A queued request may reuse a read completed after that request began. A new
manual request after completion still fetches fresh data: this is not a longer
successful cache lifetime. Cached UI access remains immediate during network I/O.
Publication rejects previous configurations and older read results. Identity
projection happens outside the state lock, including during live snapshots.

Successful rich movie reads publish the same normalized identity fields used by
badges. The download reconciliation still checks at 5, 15, 30, 60 and 120 seconds,
including separate user watched-state reads. It omits the now-redundant identity
HTTP traversal: 20 logical collection reads rather than 25 with a linked user,
or 15 rather than 20 without one. Paginated HTTP request counts depend on library
size; simultaneous callers can save more through coalescing. No idle NAS CPU or
end-to-end latency improvement is claimed without production measurements.

Background failed inventory reads share a 30-second retry budget. The live probe
uses its existing exponential failure delay, capped at 15 seconds, even if stale
UI reads repeatedly wake the monitor. Healthy poll intervals, cache TTLs, scan
debounce/cooldown, download validation and user-visible layouts stay unchanged.
Explicit manual forced reads bypass the background inventory failure budget and
allow an immediate subsequent probe. Unavailability preserves old display rows,
but marks safety data unavailable; an error is never an empty library.

Personal saved-media synchronization still checks every 30 seconds and reads
the current user's visible library. Global membership fingerprints cannot prove
user permissions, playability or watched state, so they never replace those
user-scoped reads. The fresh index requests ProviderIds without MediaSources/Path;
only wished movie IDs are hydrated in batches of at most 100. Wished series keep
their targeted episode reads. Ambiguous TMDB matches remain ambiguous, failed
hydration aborts reconciliation, and private playlist verification/repair is
unchanged. Movie wishes add a small targeted request in exchange for avoiding
playback metadata for the entire library. This does not remove the slim identity
traversal, nor cache ACL changes or skip playlist repair.

`media_scan_diagnostics().inventory_reads` exposes only counts of started,
joined, reused and failed reads, current in-flight reads and retained result
entries. Results are bounded to 16 entries and cleared on configuration changes.
URLs, credentials, item IDs and user IDs are not included in these diagnostics.

Regression coverage: `tests/test_jellyfin_inventory.py`,
`tests/test_jellyfin_live_state.py`, `tests/test_saved_media.py`, plus existing
movie ownership, per-user profile, scan coordinator and handoff tests. The API
parameters used for the two-stage user lookup are documented by Jellyfin's
[ItemsController](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/ItemsController.cs).
