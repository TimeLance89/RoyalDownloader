# NAS resource and startup hotfix

The observed origin EOF/reset errors and the NAS container-manager encryption
status timeout do not establish a single root cause. This change closes the
resource-amplification paths reproduced in the code audit. It does not claim
to repair a NAS kernel, filesystem or container-manager fault.

## Resource limits

- Optional Royal Intelligence admits at most **two** inferences across all
  service instances in a Python process. There is no waiting inference queue.
  Excess requests immediately receive the normal deterministic baseline.
- Successful results are limited to **64** entries and expire after six hours.
  Job history is limited to **128** entries. Failed fingerprints back off for
  **60 seconds**. Reconfiguration invalidates results without freeing slots
  still occupied by old network calls, and old results cannot repopulate caches.
- Storage mutations/explicit analyses run in a separate **two-worker** pool
  with at most **four** outstanding jobs. They are never cached or automatically
  retried. Confirmation, ownership, mount and durability rules remain in place.
- Telemetry has **one worker**, at most **two** outstanding distinct jobs, and
  a **one-second** result retention. Equivalent requests share one future.
  A read returns HTTP 503 after **three seconds**, retaining the original
  admission slot until the real filesystem operation exits. Repeated polls
  cannot spawn replacement probes for the same blocked operation.
- Actual work completion invalidates telemetry, including after an HTTP caller
  disconnects. Cached values are copied per reader. Inventory transactions
  skip disk serialization, replacement and fsync when the document is unchanged;
  changed documents retain the existing atomic durable commit.

Python cannot forcibly interrupt a kernel-blocked mount syscall. The limits
protect HTTP/auth/static worker capacity and prevent accumulating replacement
work; storage-dependent operations can remain unavailable until the NAS recovers.

## Startup and unchanged presentation

`web/boot.js` is a small independent external classic script. It runs before the
application graph and needs no inline script or weaker CSP. Import failures or
an unavailable entry point show a manual retry screen; stalled startup has a
20-second watchdog. No automatic reload loop is introduced. The ordinary loader,
login, application layout and interactions remain unchanged.

The guard also observes the exact entry URL through the native import promise:
Linux WebKit does not reliably emit script resource errors for a missing entry.
The module registry shares that URL, so the guard neither fetches nor executes
the entry twice. Browser regression tests suppress resource-error delivery to
exercise this path explicitly.

`web/app.js` catches module-graph import errors explicitly, including WebKit,
and starts safely even if DOMContentLoaded occurred while importing.

The existing `web/style.css` remains the editable 44-import manifest. Static
serving combines its exact contents in cascade order, caches the generated
bytes using source signatures, and offers gzip without a build step. Unsupported
or temporarily missing inputs fall back to the original manifest. Existing
no-store/update semantics remain unchanged.

Measured stylesheet: **792,272 bytes**, gzip **146,322 bytes** (81.5% smaller than
uncompressed contents). **44 fewer stylesheet requests** on a cold page load.
This is a request/payload measurement, not a claim that every network or total
page-load duration improves by 81.5%.

## Verification

- 251 focused Python tests passed; one existing platform-dependent test skipped.
- 372 Node tests passed.
- Chromium and WebKit: missing dependency, missing app entry, stalled startup,
  manual retry, ordinary login and **identical rendered login pixels** with
  original versus bundled CSS. Exact full CSS-content/cascade equality checked
  separately through the actual Python static-serving implementation.
- Chromium application smoke: login/session expiry, navigation, websocket
  reconnect, 14 release requests, no missing resources or browser errors.
- Chromium/WebKit storage UI: mount availability, explicit confirmations,
  immediate refresh, roles and existing controls on desktop/mobile.
- New regressions are included in the quality and WebKit workflows.

No deployment, NAS configuration or Jellyfin connection changes are included.
