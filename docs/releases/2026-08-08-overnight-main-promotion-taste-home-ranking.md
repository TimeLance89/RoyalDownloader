# Overnight → Main Promotion — 2026-08-08 (Taste, Home Personalization, and Daily Top 10)

This document summarizes the tested Overnight changes prepared for promotion to the Stable `main` branch after the previous Stable promotion in PR #100 (`0a9c34fcb8c5a40b3171c7e55265e42e64905d9b`).

## Highlights

This promotion focuses on three areas: hardening subscription/download behavior around real-world race conditions and storage constraints, replacing the first-generation taste model with a deeper unified Taste Profile v2, and rebuilding the Home discovery surfaces so the Hero, personal recommendations, card hover details, and Daily Top 10 each have a clear and technically consistent purpose.

## Movie-subscription and download hardening

- Subscription upgrades now re-check the currently installed movie immediately before publishing a downloaded replacement, preventing a long-running upgrade from overwriting a newer or better file that appeared after the original baseline was measured.
- Audio quality selection is language-aware: the requested content language is preferred before comparing channel count, codec, and bitrate.
- HLS audio renditions remain separate instead of accidentally combining the language of one rendition with the channel count of another.
- Same-resolution HLS variants are ranked by the complete technical quality profile, including HDR, bit depth, codec, audio characteristics, and bitrate rather than resolution alone.
- Probe-cache identity is stable across rotating signed query tokens and hoster ordering while still distinguishing meaningful provider/source/hoster paths.
- Network `ffprobe` traffic uses the existing guarded outbound proxy path.
- Movie-subscription quality inventory receives a configurable wall-clock budget through `MOVIE_SUBSCRIPTION_PROBE_BUDGET_SECONDS` (default 75 seconds).
- Overlapping immediate movie-subscription checks are coalesced instead of silently being dropped when another check currently owns the lock.
- Movie-subscription inventories and the series watchlist use independent scheduling paths so slow movie probes cannot delay series monitoring.
- The duplicate forced Jellyfin library refresh in the movie-subscription quality path was removed.
- Public movie-subscription REST/WebSocket payloads no longer expose large internal probe/baseline cache structures; compact diagnostic counts are exposed instead.
- Downloads now check a configurable destination free-space reserve before staging through `DOWNLOAD_MIN_FREE_GIB` (default 5 GiB).
- A download blocked by local storage capacity does not incorrectly damage provider/hoster health.

## CI hardening

- CI now compiles all `application_services` modules rather than only the older critical subset.
- Broad critical-module coverage is protected by a repository-baseline ratchet instead of being allowed to regress silently.
- The new subscription/download hardening modules have their own stricter minimum combined coverage requirement.
- The existing compile, JavaScript, frontend contract, Ruff, Bandit, dependency audit, Docker Compose, full pytest/coverage, image build, fresh-container, persistent-container, and restart smoke stages remain part of the required `verify` workflow.

## Taste Profile v2

- The persistent taste profile is upgraded to schema v2 while preserving existing stored profile data.
- Cross-provider genre names, media types, and language codes are canonicalized so equivalent values contribute to the same preference dimensions.
- Jellyfin evidence is weighted by completion, repeat plays, favorites, and ratings instead of applying one blanket positive score to every played title.
- Very low ratings can contribute negative evidence even when a title was completed.
- Imported legacy taste values decay over time instead of permanently dominating newer behavior.
- The profile exposes confidence and evidence breakdown metadata so the UI can distinguish a mature profile from one that is still learning.
- Candidate scoring normalizes broad metadata sets so titles with many generic tags do not automatically outrank titles with fewer but more precise matches.
- Negative evidence is intentionally amplified relative to weak positive overlap.
- Mature profiles apply a small penalty to candidates dominated by completely unknown genre signals.
- Franchise/collection identity can contribute as an additional taste dimension when metadata is available.
- `For you` no longer injects a mandatory unrelated surprise candidate. The visible personal lane targets five strong matches plus at most two adjacent discoveries.
- Deliberate out-of-comfort-zone discovery remains available in the separate exploration lane instead of being mixed into the personal lane.
- Explicit reshuffle temporarily suppresses the currently visible personal recommendations for the active browser session so `Shuffle` actually produces meaningfully different candidates.
- Home cards support direct `Not for me` feedback.
- `less` feedback is distinguished from exact-title `dismiss`/`dislike`, allowing Royal to learn weaker style aversion without over-blocking broad genres.
- Dismissed media are blocked by logical identity, including TMDB identity where available, instead of only by provider-specific slugs.
- Jellyfin ProviderIds are used so TMDB-level dismissals can also be respected by Jellyfin recommendation generation.
- The Jellyfin recommendation collection now uses the same aggregated Royal taste model instead of maintaining a separate Jellyfin-only ranking model.

## Home card hover experience

- Home-card hover behavior was rebuilt around the existing card geometry instead of replacing the card with a visually separate control panel.
- The final hover keeps the approved lift/scale while restoring useful contextual detail.
- Hover details can include year, rating, runtime, media type, genres, a short synopsis, and Taste Profile match reasons.
- A clear details hint is shown without restoring the old decorative action circles that looked interactive but had no independent behavior.
- The title remains anchored instead of jumping to a different layout position on hover.
- `Not for me` remains the independent secondary action and is visually subordinate to the media itself.
- Ranked Daily Top 10 cards intentionally keep their dedicated ranked presentation instead of inheriting the rich recommendation-card hover layer.
- Touch and reduced-motion behavior remain supported.

## Taste-aware Home Hero

- The Home Hero no longer uses the legacy composition of four personal entries plus three daily hash-ordered top/trending entries.
- For a sufficiently learned profile, the Hero targets five strong personal matches, one current trend that is still compatible with the user's taste, and one adjacent discovery.
- Hero candidates are evaluated through Taste Profile v2 instead of being admitted solely because they appear in a general top/trending list.
- Useful 16:9 artwork is preferred and low-quality/rating candidates are filtered when enough stronger alternatives exist.
- Persistent Hero exposure history penalizes recently repeated titles.
- Logical/TMDB blocked identities and negative taste affinity are respected.
- Film/series balance is controlled softly so one media type does not unnecessarily dominate all seven positions.
- Already-owned Jellyfin media are also prevented from unnecessarily dominating the Hero when alternatives exist.
- `stableDailyOrder`, the discovery shuffle seed, and the previous pseudo-random daily Hero noise no longer determine the Hero ranking.
- Cold or low-confidence profiles retain a sensible quality-oriented top/trending fallback until enough taste evidence exists.

## Daily Top 10 v2

- The Daily Top 10 is now a real cross-source popularity ranking rather than a deterministic date-hash shuffle of top movies and trending series.
- Original top-list positions from every active movie provider are preserved instead of being discarded after catalog aggregation.
- SerienStream's real trending order is used as the provider popularity signal for series.
- If SerienStream is unavailable, other active series catalogs may contribute availability candidates but do not receive invented popularity points.
- TMDB daily movie/TV trending is used as an independent corroborating signal when TMDB is configured.
- Provider duplicates are merged by stable logical identity, preferring TMDB identity when available and using conservative title/year fallbacks otherwise.
- Candidates are scored with the agreed weighting:
  - 45% provider rank / momentum;
  - 20% independent provider consensus;
  - 15% TMDB trending / popularity;
  - 10% rating quality with vote-count confidence;
  - 10% freshness.
- Rating confidence prevents tiny vote samples from overpowering established ratings with thousands of votes.
- Freshness contributes a bounded bonus without allowing novelty alone to dominate actual popularity.
- A soft media-type guard allows real market skew while preventing unnecessary 10/0 film-or-series domination when at least three genuinely relevant candidates of the other type exist.
- The expensive server-side aggregation is cached for two hours.
- The visible Top 10 is frozen for the local calendar day so reloads and temporary provider outages do not reshuffle the chart.
- The next day's ranking is compared with the previous local-day snapshot and can display `NEW`, `↑n`, `↓n`, or `—` movement indicators.
- Taste Profile is deliberately excluded from the popularity score; personalization remains the responsibility of the Hero and personal recommendation lanes.
- The rail description now communicates its purpose as content that is currently popular across the configured sources.

## Daily Top 10 presentation and navigation fixes

- The large visible rank numbers are always contiguous `1` through `10`, even when blocked items or internal global-rank gaps cause the displayed set to differ from the underlying global positions.
- The true internal `global_rank` is retained separately for score metadata and day-to-day movement calculations.
- Accessibility labels follow the visible card position rather than exposing confusing gaps.
- Daily Top cards now open their detail views from the provider payload that actually produced the ranked candidate.
- Movie cards use the existing movie detail path with their own valid provider `slug`.
- Series cards use the existing series detail path with their own valid `base_slug`.
- This fixes ranked candidates that existed in the deeper Daily Top provider pool but were not simultaneously present in the smaller normal Home catalog arrays.
- Nested actions such as `Not for me` remain isolated from the card-level detail click.

## API and compatibility

- Existing `/api/movies`, `/api/series`, legacy, and `/api/v1` contracts remain compatible.
- Daily Top 10 adds `/api/daily-top` and `/api/v1/daily-top` without removing existing endpoints.
- Existing queue, retry, cancel, persistence, recovery, and WebSocket contracts remain compatible.
- Existing Taste endpoints remain available while the profile data is migrated in place.
- Existing Stable/Overnight updater behavior remains unchanged.
- Existing media files are not automatically renamed or migrated by this promotion.
- Provider priority remains authoritative where provider order is relevant.
- No force push, branch-protection bypass, or protected-branch rule change is required.

## Git history hygiene

- Before preparing this promotion, the previous Stable merge commit from PR #100 was reconciled back into the Overnight history through a zero-file-diff protected PR.
- This leaves `overnight` directly ahead of `main` with no historical commit on Stable that Overnight does not contain, simplifying the next protected promotion without rebasing or force-pushing.

## Validation and regression coverage

The promoted Overnight work adds or expands regression coverage for:

- fresh pre-commit movie-baseline protection against external replacement races;
- language-aware ffprobe/Jellyfin audio selection;
- isolated HLS audio renditions and same-resolution HDR/codec/audio variant ranking;
- stable probe-cache identity and bounded inventory budgets;
- coalesced movie-subscription checks and independent movie/series scheduling;
- compact subscription payloads and storage-reserve handling;
- Taste Profile v2 migration, canonicalization, legacy decay, confidence metadata, Jellyfin completion/repeat weighting, negative evidence, and franchise dimensions;
- strict personal-lane composition, session reshuffle suppression, logical/TMDB blocking, and shared Royal/Jellyfin recommendation ordering;
- Home card hover presentation and rich contextual details;
- Taste-ranked Hero composition, exposure handling, artwork/rating policy, and removal of daily hash/shuffle dependence;
- Daily Top provider consensus, rating confidence, TMDB identity merging, freshness, soft film/series diversity, stable daily snapshots, and movement indicators;
- contiguous visible Top 10 numbering while preserving internal global rank;
- reliable Daily Top movie and series detail navigation from each ranked card's own provider payload.

Every implementation PR included in this promotion passed the repository `verify` workflow. The final promotion candidate must pass that workflow again on the exact protected `main` merge candidate before merge, including Python compilation, JavaScript checks, frontend contract tests, Ruff, Bandit, dependency audit, Docker Compose validation, the complete pytest/coverage stage, container image build, and fresh/persistent startup and restart smoke tests.
