# Gates: Live Jellyfin state everywhere

Scope: Make Jellyfin ownership/library state near-live across every Royal surface that depends on it, without blocking UI rendering or multiplying expensive library scans.

- [ ] G1: All user-visible Jellyfin ownership checks use one shared live-state path instead of independent stale/full-library checks, and already-known state is returned immediately while refresh happens asynchronously.
  CHECK: python -m pytest -q tests/test_jellyfin_live_state.py -k "shared or immediate"
  EXPECT: /passed/
  EVIDENCE: pending

- [ ] G2: Movie catalog, series catalog/details, home/global search and download-availability flows receive refreshed Jellyfin state automatically and cannot remain indefinitely in a "checking" state after a successful Jellyfin response.
  CHECK: python -m pytest -q tests/test_jellyfin_live_state.py tests/test_global_search_runtime.py tests/frontend_smoke.test.mjs
  EXPECT: /passed/
  EVIDENCE: pending

- [ ] G3: Jellyfin state invalidates/refreshed immediately after Royal-side media mutations and Jellyfin configuration changes, while external Jellyfin changes are detected by a bounded background refresh cadence.
  CHECK: python -m pytest -q tests/test_jellyfin_live_state.py -k "invalidate or mutation or background"
  EXPECT: /passed/
  EVIDENCE: pending

- [ ] G4: Live refresh work is coalesced and bounded: concurrent consumers do not trigger duplicate full-library scans, refresh failures preserve the last known state as stale, and UI/API requests are not held behind a full-library refresh.
  CHECK: python -m pytest -q tests/test_jellyfin_live_state.py -k "coalesce or stale or nonblocking or bounded"
  EXPECT: /passed/
  EVIDENCE: pending

- [ ] G5: The final branch is based on the current overnight baseline, contains no temporary .unlazy ledger files, passes JavaScript syntax/frontend contracts/Python correctness/security/dependency/Docker/tests/browser-runtime/startup checks, and only then is merged to overnight.
  CHECK: git diff --exit-code overnight...HEAD -- GATES.md PLAN.md gates || true
  EXPECT: /./
  EVIDENCE: pending
