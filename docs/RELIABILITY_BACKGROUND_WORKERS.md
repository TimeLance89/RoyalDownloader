# Reliability: scheduled workers and queue stress

Series automation and Seerr polling previously risked terminating permanently
on unexpected initialization, state or malformed interval errors.

The series automatic-check loop now retries after 60 seconds when its own
processing fails, and clamps malformed intervals to a safe 5–1440 minute
range. Series and movie subscription checks remain independent where possible.

Seerr retries its one-time job hydration after a failure, bounds the persisted
poll interval to 15–86400 seconds and keeps the same worker alive when a poll
unexpectedly raises. It does not create additional polling workers or reset
download claims.

Regression tests live in:
- `tests/test_background_worker_recovery.py`: client initialization,
  transient checks, corrupted schedules and hydration retry
- `tests/test_queue_reliability_stress.py`: 650 logical jobs, 800
  concurrent queue producers, duplicate suppression and bounded history

No live provider download, external requests, new API contract or UI change
is introduced. CI tests should be complemented by a controlled NAS run.
