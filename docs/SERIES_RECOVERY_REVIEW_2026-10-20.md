# Series recovery review, 2026-10-20

Reviewed PR #551 at `9e2fb355328640bf9135d8669e762cb608d979d4`
against `overnight` at `ce89c61020378c95200d6b75ffad4f81599fbaf2`.
The primary PC checkout differs and was left untouched.

## Result

The hotfix addresses real problems but does not cover the entire report.

- Progressive requests with `defer_checks=true` previously bypassed shared,
  bounded detail workers. Both catalog and TMDB routes now use those workers;
  retries reuse the same job and do not duplicate provider work.
- The lightweight TV identity lookup and cached provider inventory reuse reduce
  work for TMDB-only suggestions. Exact identity/year confirmation remains.
- The routing change in #550 affects `tmdb:ID` suggestions. Ordinary provider
  slugs still use `/api/series/load`; the two cases must not be conflated.
- Infinite scrolling is unchanged in #551. Its lost-demand bug also exists
  before #549/#550: reaching the end before prefetch completes requires another
  downward gesture after completion. Earlier direct pagination appended when
  the requested response arrived. The follow-up preserves prefetch but remembers
  the user's request across the response, poster preparation and warmup retries.
- The hotfix's 35-second browser deadline was checked only after failed HTTP
  calls. A new 20-second call could start near that deadline and exceed it.
  The follow-up checks before requests and caps each timeout and retry delay
  to the remaining budget, retaining cancellation and the pending error.
- The resolver's 25-second search budget originally excluded the identity
  request and was not checked between candidates. The follow-up checks those
  boundaries too. This limits further work; it cannot interrupt an already
  running synchronous provider request. Provider socket timeouts still apply.

## Verification

- All 343 Node contract tests passed, including pending-to-ready append,
  transient retry recovery, navigation cancellation and both detail transports.
- 40 focused Python tests passed: detail worker sharing/capacity/cancellation,
  provider cache reuse and identity safety, TV lookup caching, candidate budgets,
  detail selection/stability and catalog deadlines/fallbacks.
- Real-browser pagination passed at 390, 1440 and 3840 pixels: a gated second
  response appends without another gesture, with no skipped/duplicate pages.
- Movie/series Discovery detail navigation passed on desktop/mobile in Chromium
  and WebKit. Late inventory adoption, close cancellation and episode selection
  passed in Chromium.

No production provider or NAS timing was measured. A successful fixture test
does not prove that a particular live provider can supply seasons. Neither the
hotfix nor this follow-up was merged or deployed by this task.
