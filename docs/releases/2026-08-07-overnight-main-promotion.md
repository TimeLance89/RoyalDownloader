# Overnight → Main Promotion — 2026-08-07

This document summarizes the tested Overnight changes promoted to the Stable `main` branch after the previous `main` baseline from 2026-08-06.

## Highlights

This promotion focuses on three areas: trustworthy provider-backed movie discovery, better German/English coexistence, and a substantially more polished streaming-style catalog experience. It also improves the reliability of in-app frontend updates and broadens the home discovery engine so the same titles are not repeatedly overexposed.

## Movie search and provider verification

- Global movie search no longer treats a TMDB match as proof that a title can actually be downloaded.
- Every TMDB movie identity is verified against the currently active movie providers before it is allowed to remain in the result list.
- Verification considers localized titles, original titles, and release year so alternate-language provider names can still resolve to the same movie.
- A result must resolve to at least one usable provider source with real hosters; metadata-only matches are filtered out.
- Provider failures are isolated so one unavailable source cannot abort the complete search.
- Provider verification results are cached with provider configuration in the cache identity so stale availability is not reused after provider changes.
- The first provider-verified implementation was optimized into one batched provider-search wave per user query instead of multiplying full provider resolution by every TMDB result.
- Active movie providers are searched in parallel and unmatched TMDB identities do not trigger unnecessary provider detail loads.
- Matching detail candidates are checked in configured provider priority order and the search can stop for an identity after the first usable source is confirmed.
- Existing full multi-provider fallback resolution remains unchanged for detail and download flows.
- TMDB relevance ordering is preserved after concurrent verification.
- Ambiguous yearless provider hits are rejected instead of risking false-positive movie matches.

## German and English content behavior

- Mixed German/English catalogs are now balanced by content language instead of being dominated by the larger German provider pool.
- German and English language lanes are alternated while preserving configured provider priority inside each language.
- Bilingual movie and series identities are deduplicated into one logical card rather than appearing once per language/provider slug.
- Catalog cards can expose both known content languages through compact language indicators.
- Movie details lazily resolve active provider languages when needed, avoiding a full language-resolution network cost for every visible card.
- When a movie is genuinely available in both German and English, the Download action now asks which language should be used.
- The selected language constrains automatic provider fallback to that language instead of silently crossing into the other language.
- The chosen language is persisted on the logical queue job so retries and restart recovery keep the same language choice.
- Restored movie fallbacks are filtered by the persisted language preference.
- Single-language installations retain the direct download flow without an unnecessary language chooser.

## Trailer selection and continuity

- An already playing movie trailer is preserved when the detail UI refreshes after download, queue, taste-feedback, subscription, or status actions.
- Trailer playback no longer restarts simply because the underlying detail card rerenders.
- Trailer language selection now follows configured content languages rather than the UI translation language.
- German-only content configuration accepts German trailers only.
- English-only content configuration accepts English trailers only.
- Mixed German + English configuration deliberately prefers English trailers.
- Royal no longer falls back to a trailer in the wrong language when the requested trailer language is unavailable.
- Trailer lookup is covered by dedicated regression tests and caching behavior.

## Discovery Engine v2 and home-page variety

- The home discovery reservoir now extends beyond the previous shallow page window while keeping the initial page load fast.
- Deeper movie and series pages are warmed in independent background waves; individual provider/page failures cannot block the home screen.
- A 21-day browser-side exposure history records which titles have already been surfaced and applies a temporary repeat penalty on following days.
- Today's ranking remains deterministic so asynchronous metadata or Jellyfin refreshes do not intentionally reshuffle the page during the same day.
- “For you” now uses a deliberate 4/2/1 composition: four strong taste matches, two adjacent discoveries, and one intentional surprise.
- Additional diversity penalties reduce repeated genres, providers, media types, and long single-language runs.
- Top 10 now ranks against a broader movie/series reservoir instead of a small fixed candidate window.
- Yesterday's Top 10 carry-over is capped at four entries when enough alternatives exist, increasing daily turnover without making rankings random.
- Logical identities are deduplicated across deeper catalog pages and combined DE/EN metadata is preserved.
- The expanded discovery reservoir continues to use the existing home cache.

## Movie and series catalog presentation

- Movie and series hero areas now share one cinematic composition instead of visibly different layouts.
- Desktop backdrops span the complete hero stage behind the copy, removing the previous hard visual split.
- Desktop backdrop sizing favors the original widescreen composition instead of aggressively cropping 16:9 artwork with `cover`.
- Mobile and narrow layouts retain a coverage-oriented `cover` fallback where filling the available space is more important.
- Movie and series shelves use the same poster geometry so card sizes remain visually consistent between sections.
- Logical movie and series duplicates are merged using TMDB identity first and normalized title/original-title plus year as fallback identity.
- Source, language, genre, and artwork metadata is merged into the retained primary catalog item while provider priority/navigation identity remains authoritative.
- Duplicate reconciliation now runs again after asynchronous TMDB artwork/metadata hydration, fixing cases such as localized and original titles that only become identifiable after enrichment.
- Poster fallback initials are cleaned so punctuation-only fragments no longer create awkward placeholders.

## Desktop navigation and artwork quality

- The desktop header now follows a calmer streaming-service hierarchy with a larger Royal brand and more breathing room.
- The active content section is rendered as a soft rounded pill while inactive sections remain simple text navigation.
- Decorative desktop navigation icons were removed to reduce visual noise.
- Desktop content order is `Startseite · Serien · Filme · Anime · Meine Liste · Abendmodus` without changing the underlying tab identifiers or event contracts.
- Search, inbox, and settings remain secondary utilities on the right side of the header.
- Setup was removed from the desktop primary content navigation; configuration remains available through the dedicated Settings control.
- The dedicated mobile bottom navigation contract remains intact.
- TMDB posters are requested at `w780` instead of `w500`.
- TMDB hero backdrops are requested at `original` instead of `w1280`, avoiding visible upscaling on 2K/4K displays.
- Existing cached TMDB image URLs are upgraded client-side, so users do not need to wait for metadata caches to expire before seeing higher-resolution artwork.
- GPU color filters were removed from movie/series hero artwork and poster images; cinematic darkening remains in the overlay gradients instead of softening the source pixels.

## In-app update reliability

- The frontend now keeps a lightweight heartbeat against the existing public capabilities endpoint.
- The browser remembers the backend build SHA that originally served the open tab.
- When an in-app Stable or Overnight update restarts Royal with a different build SHA, the browser automatically reloads the frontend.
- Temporary connection loss during restart is tolerated and retried.
- Returning to a previously hidden tab triggers an immediate generation check.
- The previous explicit updater `restarting` reload path remains as the fast path.
- Existing health endpoints and updater API contracts are unchanged.

## Compatibility

- No existing Legacy or `/api/v1` response field was removed or renamed by this promotion.
- Existing virtual `tmdb:<id>` movie identities remain unchanged.
- Existing provider priority remains authoritative.
- Full detail/download provider fallback behavior is preserved apart from the intentional same-language constraint after an explicit bilingual language choice.
- No queue, provider, download, updater, persistence, or WebSocket schema migration is required for existing installations.
- No direct force-push or protected-branch bypass is used for this promotion.

## Validation and regression coverage

The promoted Overnight work adds or expands regression coverage for:

- provider-verified TMDB movie search;
- batched provider verification and provider failure isolation;
- original-title/year matching and ambiguous-match rejection;
- provider-configuration-aware caching and relevance-order preservation;
- strict trailer-language policy and trailer continuity;
- balanced German/English catalogs and persisted download-language selection;
- same-language provider fallback after queue retry/restart;
- exposure-aware discovery, 4/2/1 recommendation composition, deeper reservoir loading, and Top-10 carry-over limits;
- movie/series catalog geometry and logical cross-provider deduplication;
- post-hydration duplicate reconciliation;
- automatic frontend reload after backend build changes;
- desktop navigation presentation and mobile-navigation isolation;
- high-resolution TMDB poster/backdrop selection and unfiltered artwork rendering.

The final promotion is required to pass the repository `verify` workflow before merge to protected `main`, including Python compilation, JavaScript checks, frontend contract tests, correctness/security baselines, dependency audit, Docker Compose validation, test coverage, container build, and fresh/persistent startup smoke tests.
