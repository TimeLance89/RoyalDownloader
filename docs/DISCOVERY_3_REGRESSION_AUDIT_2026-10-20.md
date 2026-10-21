# Discovery 3.0 regression audit, 2026-10-20

Compared pre-3.0 `2447a23` with current `overnight` `9cbbe2f`, including
the merged recovery changes #550, #551 and #552. The independent movie
Jellyfin correction remains in #553 and is not duplicated here. Development
uses the existing isolated worktree; the PC checkout is unchanged.

## Confirmed additional regressions

Both findings originate in the series recovery changes in #551. They affect
existing people/filmography series resolution as well as new Home suggestions.

1. **Valid source titles rejected before identity verification.** The new
   local prefilter normalized punctuation and accents differently from the
   established TMDB verifier. `S.W.A.T.`/`SWAT`, accented/plain spelling and
   apostrophe variants could pass exact TMDB ID/year verification but never
   reach it. Three tests reproduced the failures. The prefilter now reuses
   that existing normalization; exact ID/year verification remains mandatory.
2. **Cached seasons bypassed source selection.** The new inventory shortcut
   inspected every cached provider in dictionary insertion order, including
   disabled or language-excluded sources. Six API scenarios reproduced wrong
   priority and even successful resolution with no enabled sources. Cached
   candidates now follow the current series-provider list and its ordering.

These changes restore existing contracts. They do not change queue behavior,
library matching, source-language verification or the ordinary catalog UI.

## Verification scope

- 372 Node contract tests passed across frontend components, movie/series
  browsing, pagination, preferences, saved media, navigation and downloads.
- 266 selected Python tests passed across queue jobs and replacement safety,
  authentication, per-user profiles, preferences/onboarding APIs, saved media,
  Jellyfin identities, source identity, provider fallback/deadlines, shared
  series work, layout migration and Home recommendation scenarios.
- Chromium browser checks cover people discovery on desktop/mobile, similar
  title navigation and partial failures, trailer handoff, saved-media actions,
  mobile navigation, episode probing/recovery and the Download Center. The
  latter includes 150 jobs with 200 snapshots and stable retained state.
- WebKit browser checks cover people discovery, similar title navigation and
  personal saved media. Browser fixtures use the real application and mocked
  HTTP/provider responses; they do not contact a live NAS.
- First-run onboarding passed at desktop/mobile sizes. The broad Chromium
  lifecycle suite passed with three socket lifetimes, 14 release requests,
  no missing resources and no page errors; it covers authentication recovery,
  profile/household navigation and cancellation of late responses as well.
- Python correctness lint, compilation of the touched modules and the project
  security regression scan passed.

No additional failures were observed in the completed checks above. That is
bounded test evidence, not proof that every live provider and household state
is correct. Live provider latency, production credentials and NAS filesystem
behavior were not tested. No merge or production deployment was performed.

## Storage follow-up from the reported screenshots

- Standard targets no longer claim to be always available. Unreachable,
  read-only and usable targets have distinct labels. A physically reachable
  root with a changed disk identity is marked as requiring confirmation,
  rather than as an unreachable mount.
- Changed identity still blocks placement and file actions until explicit
  confirmation. Cancelling the confirmation writes nothing. The existing
  confirmation API is accessible beside the standard target and refreshes
  both storage displays immediately after success.
- An absent mount preserves its actual filesystem error instead of replacing
  it with an identity-change diagnosis. A per-volume capacity warning no
  longer implies that the sum of all volumes is nearly full.
- New browser coverage passes in Chromium/WebKit at 390/1440px, including
  cancellation, explicit confirmation, immediate refresh and distinct offline
  state. Existing Chromium storage autonomy/cleanup tests also pass.
- The pre-existing scan test compared a normalized Windows path to a literal
  POSIX string. It now compares path identity, preserving the same expected
  scan target on both platforms. No skip was added. The full storage selection
  is included in Linux CI.
- Final local storage selection: 128 passed, one existing skip. The full Node
  selection also remains green with 372 tests.

Completed move history describes the verified result at that past time; it
does not prove that the destination is still mounted later. No historical
move was replayed and no production mount was confirmed by this task.
