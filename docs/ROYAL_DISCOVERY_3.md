# Royal Discovery 3.0 — Home-only development roadmap

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
