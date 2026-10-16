# Reliability: provider retry worker exception containment

The source retry daemon manages persistent waiting work and uses the
existing provider health/cooldown states.

Previously, an unexpected exception in status handling or retry setup
escaped the worker; a finally-block immediately started another worker
whenever any waiting job was present. A persistent exception could produce
a rapid series of replacement threads.

Unexpected per-iteration exceptions now remain within the same worker,
are logged, and are followed by a ten-second minimum recovery pause.
Existing provider selection, cooldowns, pending claims and explicit
source retry deadlines are unchanged. Fatal infrastructure failure can
still require operator intervention.

Regression tests:
`tests/test_provider_retry_recovery.py` exercises broken health status
and malformed waiting-job deadlines without contacting any provider.

An independent NAS test is still required to establish long-running
behavior under genuine network and storage faults.

## Poison-pill deadline isolation (follow-up)

The shared retry scheduler now safely interprets each waiting episode's
`next_retry_at` independently. A malformed value, negative timestamp, NaN
or infinity is treated as already due instead of throwing and repeatedly
aborting a scan of every queued episode.

The existing provider availability checks, cooldown gate, fallback throttling
and source backoff remain authoritative: interpreting a bad deadline as due
does not bypass those gates. A normal retry writes a fresh deadline using
the existing logic. Valid future deadlines remain unchanged.

Regression coverage: `tests/test_provider_retry_deadline_isolation.py`.
The tests do not perform network traffic or touch the user's NAS data.
