# Royal Discovery 3.0 — implementation and acceptance

## Current implementation (2026-10-19)

The Home UI/performance correction starts from merged `origin/overnight` at
`b5b52909bd11fe4e4ea473f313d4c23bb41e979d`. The PC's primary checkout
is a different branch with uncommitted work. Development uses a separate
worktree; that work is neither overwritten nor silently incorporated.

- **Taste:** existing long-term scores remain compatible. Home additionally
  uses aggregate interests with a seven-day half-life and a 28-day window,
  capped at three points per value. Contextual movie/series evidence has 75%
  weight and shared evidence 25%. Recent curiosity adds at most 1.05 points,
  never cancels negative evidence, and is not written into enduring scores.
  Hero and personal cards apply the same interpretation as the feed backend.
- **Discovery:** public genres, positive title IDs, exact person names and exact
  collection names provide candidates. Actor and director recommendations use
  actual credits; producer credits cannot be described as directing work.
  TV preferences select TV credits. Strongly rejected media types are excluded.
  When both title and person/collection seeds exist, the pathway rotates by day.
- **Ranking:** saturated personal relevance, Bayesian rating confidence,
  bounded vote evidence, release recency, deterministic daily variation and
  genre diversity rank candidates. Recent interactions and explicit blocked
  titles prevent repetition. Scarce matching genres remain usable.
- **Load and recovery:** at most three external calls per feed, three running
  calls and twelve admitted tasks process-wide. Excess work is rejected without
  growing an unbounded executor queue. Eight seconds bounds result collection;
  already running urllib calls finish under the TMDB client's socket timeout.
  A follower waits at most ten seconds and never starts duplicate work. Successful
  results cache for six hours; empty or partial-outage results retry after five
  minutes. Cache entries are per account, taste, language and day, with copied
  response trees and at most 32 entries. No personalized disk feed cache exists.
- **Learning:** impressions remain per-profile browser-local day/title sets;
  no external analytics are introduced. At least 60% visibility for 1.5 seconds
  is required. Threshold crossings preserve continuous dwell. Hidden tabs,
  rotations, profile changes and unmounts cancel pending measurements.
  Carousel copies cannot double-count; several rows impose at most one daily
  repetition penalty. Shuffle penalizes only titles whose dwell was measured.
  Opening, rating, dismissal and downloading remain separate taste actions.
- **Several browser windows:** Home and taste requests include the profile the
  page expects. If another window changes the shared authentication cookie,
  the server rejects a mismatch with HTTP 409 before loading or modifying a
  profile. The header never selects a different user's store. Responses also
  carry an owner identity that the browser checks. Older clients without this
  optional header retain cookie-authenticated behavior.
- **Presentation:** seven non-cloned Spotlight cards use landscape artwork in
  a two-row desktop grid. Poster-only personal candidates remain eligible for
  artwork hydration. Discovery suggestions open the existing movie/series
  detail modal directly, with one open event per title. TMDB ideas imply no
  confirmed download availability; source resolution still happens in details.
- **Home rendering:** profile/history snapshots and derived ranking tables are
  shared only within one synchronous paint. Exposure penalties are indexed;
  diversity adds only the newest selected title's penalty. No persistent
  profile cache is introduced. A synthetic trained profile with 500 candidates
  and 21 days of exposure history dropped from roughly 2.8–3.0 seconds per paint
  to 150–170 ms initially and 50–60 ms subsequently on the local Chromium run.
  Storage reads fell from 12,850 to six across three paints. With 350 queue jobs,
  200 progress updates took about 3 ms and caused no Spotlight DOM mutations.
  These measurements are fixtures, not a claim about live NAS timing.

## Reproducing verification

Use Python 3.12 and `requirements-dev.lock` in an environment **outside the
repository** (the documentation-link test intentionally inspects Markdown in
the checkout). Node 24 matches CI. Install isolated browser tooling with
`playwright@1.62.1`, `pngjs@7.0.0`, `pixelmatch@7.2.0`, Chromium and WebKit.
Set `ROYAL_PLAYWRIGHT` to that installation's Playwright package directory.

```sh
python -m pytest -q
node --test tests/frontend_smoke.test.mjs tests/series_card_summary.test.mjs tests/frontend/*.test.*
python -m ruff check --select E9,F63,F7,F82 .
python scripts/security_scan.py
python -m bandit -q -ll -r . -x ./tests -s B310
python -m pip_audit -r requirements.lock
python -m pip_audit -r requirements-dev.lock
ROYAL_BROWSER=chromium node tests/frontend/browser-smoke.cjs
node tests/frontend/home-discovery-browser.cjs
node tests/frontend/home-spotlight-browser.cjs
ROYAL_HOME_PERF_VERIFY=1 node tests/frontend/home-personalization-performance.cjs
node tests/frontend/webkit-mobile.cjs
```

Run full Python acceptance on Linux: existing tests require POSIX `resource`,
file permissions, symlinks and path semantics. Windows failures in those tests
must not be hidden with new skips. The feature branch's full-project workflow
invokes the existing quality, Linux stability and WebKit workflows. Discovery
validation additionally runs all Node contracts, relevance scenarios, paired
performance budgets and 18 strict unchanged-rail screenshot comparisons at
desktop/mobile/tablet sizes against frozen baseline
`d3aada9099703c0b9d9b6201f49082c52ddff0d7`. The intentionally changed Spotlight
has separate geometry/artwork checks at seven widths from 390 to 3840 pixels
in Chromium and WebKit.
Evidence lives in workflow artifacts; CI links and final status are recorded in
master issue #548 and the final PR only after successful acceptance.

## Ollama decision and operational limits

No new Ollama call is introduced. Public genres and confirmed credit/collection
relationships already explain the deterministic candidates. There is no measured
evidence that a generative reranker improves these offline scenarios; adding one
would add latency and unverifiable explanations. Existing optional AI features
remain independent. Home works with Ollama absent or offline and sends it no
personal profile. Live user satisfaction and NAS hardware performance cannot be
inferred from synthetic browser fixtures.

After review and explicit deployment approval, activate the tested application
build on UGREEN using the existing Docker update procedure, retain persistent
data volumes, and verify TMDB configuration and two different household profiles.
No migration command is required: older taste schema v2 loads unchanged and
Home aggregates are recomputed from existing evidence. Restarting only clears
the in-memory feed cache. `ROYAL_HOME_DISCOVERY_V3_ENABLED=0` disables external
Home discovery; it is an endpoint rollback, not a rollback of the cinema UI.
Live NAS validation and production deployment remain separate human-controlled
steps. This development task performs neither a release nor a deployment.

## Earlier milestone record

The following records the initial implementation, before the hardening above.

**Base:** \`overnight\` @ \`2447a23df6d1be8dd26ac7b12cb510ea429332f8\` (2026-10-19)
**Target:** \`overnight\` via feature branch and reviewed PR.
**Scope:** Start page and its supporting, isolated recommendation endpoints only.

## Product goal

Royal's start page should become useful to a daily user who opens it *to
discover* something. A personal feed should evolve through observed behavior,
not simply reorder a small, generic, provider-owned catalog.

## Implemented in the initial feature branch

- **Home cold-start:** Five onboarding favorites can unlock personal Home taste
  matching even when the global evidence confidence is under 18%. Global profile
  evidence math and Jellyfin personalization are deliberately unchanged.
- **Stronger visual discovery:** Personal spotlight supports poster-only entries
  and up to 12 visible recommendations; Explore can use posters as well.
- **Active candidate retrieval:** \`GET /api/home/discovery\` discovers up to 24
  ranked TMDB ideas derived from the authenticated user's genre profile, including related-title candidates when a positive TMDB seed exists.
  Requests are bounded to three parallel TMDB discovery queries and 6-hour
  per-user in-memory cache entries. No household user IDs, full search history or Jellyfin history are sent to TMDB. Public genre and positively interacted-with TMDB title IDs may be sent as discovery seeds.
- **New Home section:** "Neu für dich entdeckt" is visible by default alongside
  existing catalog rows, including when an existing Home layout is restored.
  Suggestions are not silently labeled as available downloads: opening one
  searches Royal's currently enabled provider catalog for that title.
- **Privacy/failure behavior:** Personalized TMDB suggestions do not enter the
  shared 7-day browser catalog cache. A user-key guard prevents cross-account
  presentation; a missing TMDB key or TMDB outage leaves original Home intact.

## Ten-phase execution tracking

| Phase | Current status | Exit criterion |
| --- | --- | --- |
| 1. Baseline & isolation | In progress | CI and actual current Home baseline recorded |
| 2. Home taste intelligence | Partial: cold-start readiness | Short/long-term signal separation and checks |
| 3. Active Discovery | Initial working implementation | More diverse sources, TMDB similarity/people and fallback |
| 4. Ranking 3.0 | Initial weighted candidate scorer | Offline relevance benchmark + calibration |
| 5. Home feed service | Initial per-user endpoint & bounded cache | Cache invalidation, metrics and load test |
| 6. Start-page experience | New rail + 12 poster-friendly cards | Desktop/mobile design acceptance |
| 7. Adaptive learning | Explicit block & refresh wired | Conservative impression and dismissal learning |
| 8. Optional Royal Intelligence | Not started | Candidate enrichment and reliable offline fallback |
| 9. Performance/privacy hardening | In progress | NAS, multilingual, concurrency and user-switch tests |
| 10. Controlled activation | Not started | Feature flag, rollback and real-user validation |

## Next implementation priorities

1. Expand candidate seeds beyond genres: related titles, people, franchises,
   personal "because you liked…" links and low-popularity hidden gems.
2. Rank and diversify all personal sections coherently instead of treating the
   new discovery section as an isolated recommendation surface.
3. Add opt-in user-visible recommendation reasons, explicit freshness controls
   and controlled exploration. Avoid interpreting mere impressions as dislikes.
4. Add bounded per-account event metrics (viewed, opened, acted upon), daily
   repeated-card rate and offline relevance comparisons, without leaking
   private watch history to third parties.
5. Test download/provider boundaries, household switching and mobile scroll
   performance on the target NAS and browsers; ship behind a reversible flag.

## Important constraints

- No modifications to queue scheduling, hoster-provider selection, downloads,
  subscriptions, general search behavior, or Jellyfin recommendation collections.
- Royal's deterministic recommender works without Ollama. Ollama remains optional.
- TMDB is a discovery metadata source, **not** evidence that an item can be
  downloaded. Opening its suggestion performs an ordinary source search first.
- Any field test must be verified on a real running RoyalDownloader instance
  before the release is marked ready.

## Operational rollback (Home recommendations only)

Set the Docker environment variable `ROYAL_HOME_DISCOVERY_V3_ENABLED=0`
and restart the RoyalDownloader server to disable the new TMDB Home discovery
endpoint without touching provider routing, queue processing, downloads, or
legacy taste profiles. Other Home changes (the earlier cold-start threshold,
poster support and rail order) are not reverted by this endpoint-only flag.
Do not treat it as a full UI rollback toggle.

Set `ROYAL_HOME_DISCOVERY_V3_ENABLED=1` or remove the variable to enable
the optional Home candidate retrieval again. A working TMDB configuration
is required for additional Home ideas.

## Current personal discovery signals and third-party calls

Genre-based TMDB recommendations are complemented by *one* recent positively
opened TMDB title when available. This yields a bounded call to TMDB's related
titles endpoint rather than expanding to an unrestricted recommendation crawl.
The server sends public genre IDs or a seed-title TMDB ID, **not** a household
user ID, personal search history, passwords, or Jellyfin watch state.
All discovery requests stay within the three-request budget.

A clicked TMDB idea is a weak taste signal and is suppressed from repeated
recommendations for fourteen days. Genre, Explore and Hidden Gems avoid
strongly negatively rated genres. These restrictions do not rewrite the
global Top 10 or chronological New rows.

The current phase still needs real-user relevance measurement, longer-term
taste exploration, and complete NAS/mobile acceptance before a final PR.
