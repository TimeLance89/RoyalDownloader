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
